"""Run-to-run finding diff (task 7.4).

Compares the finding set of a current run against a previous run and classifies
each as new / resolved / changed / unchanged. Findings are matched by a stable
identity key (agent + category + affected components) rather than the random
finding id, since ids differ across runs.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from app.schemas.finding import Finding


def _identity(f: Finding) -> tuple:
    return (f.agent, f.category, tuple(sorted(f.affected_components)))


@dataclass
class RunDiff:
    new: list[Finding] = field(default_factory=list)
    resolved: list[Finding] = field(default_factory=list)
    changed: list[tuple[Finding, Finding]] = field(default_factory=list)  # (prev, curr)
    unchanged: list[Finding] = field(default_factory=list)

    def summary(self) -> dict:
        return {
            "new": len(self.new),
            "resolved": len(self.resolved),
            "changed": len(self.changed),
            "unchanged": len(self.unchanged),
        }


def diff_runs(previous: list[Finding], current: list[Finding]) -> RunDiff:
    prev_by_id = {_identity(f): f for f in previous}
    curr_by_id = {_identity(f): f for f in current}

    diff = RunDiff()
    for key, curr in curr_by_id.items():
        prev = prev_by_id.get(key)
        if prev is None:
            diff.new.append(curr)
        elif (prev.severity != curr.severity) or (
            round(prev.confidence, 3) != round(curr.confidence, 3)
        ) or (prev.status != curr.status):
            diff.changed.append((prev, curr))
        else:
            diff.unchanged.append(curr)

    for key, prev in prev_by_id.items():
        if key not in curr_by_id:
            diff.resolved.append(prev)

    return diff