"""Evidence Validation (tasks 6.7, 6.8).

Validates important findings (high severity AND/OR high confidence) against the
evidence they cite. Validation here is deterministic: it checks that the cited
evidence actually exists and is well-formed for the finding's claim type. It is
NOT an LLM step - an LLM could later add semantic checks, but the structural
guarantee (a claim must be backed by resolvable provenance) stays deterministic.

Status transitions (task 6.8):
  * observed  -> validated   : evidence present + consistent
  * observed  -> disputed    : important claim lacks resolvable evidence
  * inferred  -> unchanged   : inferences are not evidence-validated here
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path

from app.schemas.finding import (
    EvidenceSourceType,
    Finding,
    FindingSeverity,
    FindingStatus,
)

logger = logging.getLogger(__name__)

IMPORTANT_SEVERITIES = {FindingSeverity.CRITICAL.value, FindingSeverity.HIGH.value}
HIGH_CONFIDENCE = 0.8


@dataclass
class ValidationOutcome:
    finding_id: str
    previous_status: str
    new_status: str
    reason: str


class EvidenceValidator:
    def __init__(self, repo_root: Path | None = None):
        # repo_root optionally enables file-existence checks for FILE evidence.
        self._repo_root = Path(repo_root) if repo_root else None

    def is_important(self, f: Finding) -> bool:
        return f.severity in IMPORTANT_SEVERITIES or f.confidence >= HIGH_CONFIDENCE

    def validate(self, findings: list[Finding]) -> tuple[list[Finding], list[ValidationOutcome]]:
        outcomes: list[ValidationOutcome] = []
        out: list[Finding] = []
        for f in findings:
            new = f
            if f.status == FindingStatus.INFERRED.value:
                out.append(f)
                continue
            if not self.is_important(f):
                out.append(f)
                continue

            ok, reason = self._check_evidence(f)
            new_status = (
                FindingStatus.VALIDATED.value if ok else FindingStatus.DISPUTED.value
            )
            if new_status != f.status:
                new = f.model_copy(update={"status": new_status})
                outcomes.append(
                    ValidationOutcome(
                        finding_id=f.id, previous_status=f.status,
                        new_status=new_status, reason=reason,
                    )
                )
            out.append(new)
        return out, outcomes

    def _check_evidence(self, f: Finding) -> tuple[bool, str]:
        if not f.evidence:
            return False, "important finding has no evidence"
        # At least one evidence must carry a non-empty source.
        resolvable = [e for e in f.evidence if e.source and e.source.strip()]
        if not resolvable:
            return False, "evidence records lack a resolvable source"

        # If FILE evidence references a repo path and we have the repo, verify
        # the file exists at the analyzed revision snapshot.
        if self._repo_root is not None:
            for e in f.evidence:
                if e.source_type == EvidenceSourceType.FILE.value and e.location:
                    # location often "path" or "L10-L20"; source may be the path
                    candidate = self._repo_root / e.source
                    if e.source.endswith(".py") and not candidate.exists():
                        return False, f"cited file not found: {e.source}"
        return True, "evidence present and resolvable"