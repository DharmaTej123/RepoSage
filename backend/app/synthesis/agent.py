"""Synthesis Agent (tasks 7.2, 7.3, 7.5, 7.6).

Deterministic assembly of onboarding + tech-debt artifacts from the run state.
Every claim is either backed by a finding/evidence reference or explicitly
labeled an inference. Unavailable analyses are reported as UNAVAILABLE, never
silently treated as clean (task 7.5).
"""

from __future__ import annotations

import logging
from typing import Any

from app.schemas.finding import Finding

logger = logging.getLogger(__name__)

AGENT_NAME = "synthesis"


def _node_status(state: dict, node: str) -> str:
    return (state.get("node_status") or {}).get(node, "pending")


class SynthesisAgent:
    """Builds structured onboarding + tech-debt artifacts.

    Artifacts are structured dicts (not free prose) so attribution is explicit
    and machine-checkable. A downstream LLM layer can render these into prose
    while remaining constrained to the cited evidence.
    """

    def build_onboarding(self, state: dict) -> dict:
        arch = state.get("architecture")
        ownership = state.get("ownership_report")
        findings: list[Finding] = state.get("findings") or []

        # Reading order: highest-centrality modules first (observed fact).
        reading_order: list[dict] = []
        analysis_status: dict[str, str] = {}

        if arch is not None:
            from app.analyzers.graph import ModuleGraph
            g = ModuleGraph.from_architecture(arch)
            top = g.high_centrality_modules(arch.centrality, top_n=10)
            for c in top:
                node = next((n for n in arch.nodes if n.id == c.module), None)
                reading_order.append({
                    "module": c.module,
                    "file_path": node.file_path if node else None,
                    "reason": f"high dependency centrality (in-degree {c.in_degree})",
                    "claim_type": "observed",
                    "evidence": f"architecture graph @ {arch.revision}",
                })
            analysis_status["architecture"] = "complete"
        else:
            analysis_status["architecture"] = self._unavailable_status(state, "architecture")

        # Historical contributors (NOT owners) per high-churn module.
        contributors: list[dict] = []
        if ownership is not None:
            for m in (ownership.modules or [])[:10]:
                contributors.append({
                    "module": m.module,
                    "primary_contributor": m.primary_contributor,
                    "share": round(m.primary_contributor_share, 3),
                    "note": "historical contribution, not formal ownership",
                    "claim_type": "observed",
                    "evidence": "git history",
                })
            analysis_status["git_history"] = "complete"
        else:
            analysis_status["git_history"] = self._unavailable_status(state, "git_history")

        high_risk = [
            {
                "title": f.title,
                "component": f.affected_components,
                "severity": f.severity,
                "status": f.status,
                "finding_id": f.id,
            }
            for f in findings
            if f.severity in ("critical", "high")
        ]

        return {
            "revision": state.get("revision"),
            "reading_order": reading_order,
            "historical_contributors": contributors,
            "high_risk_areas": high_risk,
            "analysis_status": analysis_status,
            "disclaimer": "Claims labeled 'observed' derive from deterministic "
                          "analysis; 'inferred' claims are interpretations.",
        }

    def build_tech_debt_report(self, state: dict) -> dict:
        art = state.get("artifacts") or {}
        ranked = art.get("tech_debt_ranked") or []
        findings_by_id = {f.id: f for f in (state.get("findings") or [])}

        items: list[dict] = []
        for entry in ranked:
            f = findings_by_id.get(entry.get("finding_id"))
            attribution = self._attribution(f) if f else []
            items.append({
                **entry,
                "attribution": attribution,   # per-finding source references (7.3)
                "claim_type": ("inferred" if (f and f.status == "inferred") else "observed"),
            })

        return {
            "revision": state.get("revision"),
            "items": items,
            "correlation_groups": art.get("correlation_groups", []),
            "conflicts": state.get("conflicts", []),
            "analysis_status": self._all_status(state),
        }

    @staticmethod
    def _attribution(f: Finding) -> list[dict]:
        return [
            {
                "source_type": e.source_type,
                "source": e.source,
                "location": e.location,
            }
            for e in f.evidence
        ]

    @staticmethod
    def _unavailable_status(state: dict, node: str) -> str:
        st = _node_status(state, node)
        if st in ("skipped", "not_applicable"):
            return "unavailable"
        if st == "failed":
            return "failed"
        if st == "no_finding":
            return "clean"
        return "unavailable"

    def _all_status(self, state: dict) -> dict[str, str]:
        out = {}
        for node in ("architecture", "dependency", "git_history", "coverage"):
            st = _node_status(state, node)
            if st == "no_finding":
                out[node] = "clean"
            elif st in ("skipped", "not_applicable", "pending"):
                out[node] = "unavailable"
            elif st == "failed":
                out[node] = "failed"
            else:
                out[node] = "complete"
        return out