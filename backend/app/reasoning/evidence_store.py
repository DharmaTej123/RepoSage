"""Normalized evidence store (task 6.1).

Collects all evidence referenced by findings into a single addressable store,
indexed by finding id and by affected component, so downstream reasoning
(validation, correlation, synthesis) can look up provenance uniformly.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field

from app.schemas.finding import Evidence, Finding


@dataclass
class EvidenceStore:
    # finding_id -> list of evidence
    by_finding: dict[str, list[Evidence]] = field(default_factory=dict)
    # affected component -> set of finding_ids touching it
    findings_by_component: dict[str, set[str]] = field(default_factory=lambda: defaultdict(set))
    # finding_id -> Finding
    findings: dict[str, Finding] = field(default_factory=dict)

    def evidence_count(self, finding_id: str) -> int:
        return len(self.by_finding.get(finding_id, []))

    def components(self) -> list[str]:
        return sorted(self.findings_by_component.keys())


def build_evidence_store(findings: list[Finding]) -> EvidenceStore:
    store = EvidenceStore()
    for f in findings:
        store.findings[f.id] = f
        store.by_finding[f.id] = list(f.evidence)
        for comp in f.affected_components:
            store.findings_by_component[comp].add(f.id)
    return store