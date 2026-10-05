"""Conflict Resolver (tasks 6.9, 6.10).

Detects contradictory findings about the same component and attempts a
deterministic resolution by comparing evidence strength + confidence. Crucially,
when a conflict cannot be resolved it is PRESERVED explicitly (both findings
kept, marked disputed) rather than silently picking a winner (task 6.10).

Contradiction rule (v1, deterministic): two findings on the same component
conflict when they are in opposing categories (e.g. one asserts a risk in a
category another explicitly clears) OR carry directly contradictory
deterministic signals (a registry of opposing (category_a, category_b) pairs).
"""

from __future__ import annotations

from dataclasses import dataclass, field

from app.schemas.finding import Finding, FindingStatus

# Registry of categories that directly contradict each other on a component.
OPPOSING_CATEGORIES: set[frozenset[str]] = {
    frozenset({"coverage_gap", "well_tested"}),
    frozenset({"vulnerable_dependency", "clean_dependency"}),
    frozenset({"high_centrality", "isolated_module"}),
}


@dataclass
class Conflict:
    component: str
    finding_ids: list[str]
    resolved: bool
    winner_id: str | None = None
    reason: str = ""


@dataclass
class ConflictResolution:
    findings: list[Finding] = field(default_factory=list)
    conflicts: list[Conflict] = field(default_factory=list)


class ConflictResolver:
    def resolve(self, findings: list[Finding]) -> ConflictResolution:
        by_component: dict[str, list[Finding]] = {}
        for f in findings:
            for comp in (f.affected_components or []):
                by_component.setdefault(comp, []).append(f)

        conflicts: list[Conflict] = []
        disputed_ids: set[str] = set()
        winners: dict[str, str] = {}

        for comp, group in by_component.items():
            for i in range(len(group)):
                for j in range(i + 1, len(group)):
                    a, b = group[i], group[j]
                    if not self._contradict(a, b):
                        continue
                    winner = self._try_resolve(a, b)
                    if winner is not None:
                        loser = b if winner is a else a
                        conflicts.append(Conflict(
                            component=comp, finding_ids=[a.id, b.id],
                            resolved=True, winner_id=winner.id,
                            reason=(f"Resolved in favor of {winner.agent}: stronger "
                                    f"evidence/confidence ({winner.confidence:.2f} vs "
                                    f"{loser.confidence:.2f})."),
                        ))
                        winners[winner.id] = winner.id
                    else:
                        conflicts.append(Conflict(
                            component=comp, finding_ids=[a.id, b.id],
                            resolved=False,
                            reason="Contradictory findings with comparable evidence; "
                                   "preserved as unresolved (both kept, disputed).",
                        ))
                        disputed_ids.update({a.id, b.id})

        # Apply: mark unresolved-conflict findings disputed; never drop any.
        out: list[Finding] = []
        for f in findings:
            if f.id in disputed_ids and f.status != FindingStatus.DISPUTED.value:
                out.append(f.model_copy(update={"status": FindingStatus.DISPUTED.value}))
            else:
                out.append(f)
        return ConflictResolution(findings=out, conflicts=conflicts)

    @staticmethod
    def _contradict(a: Finding, b: Finding) -> bool:
        if a.category == b.category:
            return False
        return frozenset({a.category, b.category}) in OPPOSING_CATEGORIES

    @staticmethod
    def _try_resolve(a: Finding, b: Finding) -> Finding | None:
        """Return the stronger finding, or None if too close to call."""
        def strength(f: Finding) -> float:
            return f.confidence + 0.1 * len(f.evidence)

        sa, sb = strength(a), strength(b)
        if abs(sa - sb) < 0.15:  # comparable -> unresolved
            return None
        return a if sa > sb else b