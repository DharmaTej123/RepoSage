"""Finding correlation without double-counting (tasks 6.5, 6.6).

Findings that affect the same component are grouped so a single module with
multiple signals (e.g. high centrality + low coverage + bus-factor) is treated
as ONE correlated risk area rather than three independent risks.

Double-counting avoidance (6.6): a component's group score is the MAX of its
members' scores plus a small, bounded corroboration bonus per additional
distinct signal category - never the naive sum. This rewards corroboration
without letting three related observations inflate the score threefold.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field

from app.reasoning.risk import ScoredFinding

CORROBORATION_BONUS = 0.05
MAX_BONUS = 0.15


@dataclass
class CorrelationGroup:
    component: str
    scored_findings: list[ScoredFinding] = field(default_factory=list)
    group_score: float = 0.0
    categories: list[str] = field(default_factory=list)

    @property
    def finding_ids(self) -> list[str]:
        return [s.finding.id for s in self.scored_findings]


def correlate_findings(scored: list[ScoredFinding]) -> list[CorrelationGroup]:
    """Group scored findings by primary affected component.

    A finding with multiple affected components is attached to each; grouping is
    for reasoning/synthesis, not mutation of the underlying findings.
    """
    by_component: dict[str, list[ScoredFinding]] = defaultdict(list)
    for s in scored:
        comps = s.finding.affected_components or ["<unscoped>"]
        for comp in comps:
            by_component[comp].append(s)

    groups: list[CorrelationGroup] = []
    for comp, members in by_component.items():
        members_sorted = sorted(members, key=lambda s: s.score, reverse=True)
        distinct_categories = sorted({m.finding.category for m in members_sorted})
        base = members_sorted[0].score if members_sorted else 0.0
        # Bounded corroboration bonus for each ADDITIONAL distinct category.
        bonus = min(MAX_BONUS, CORROBORATION_BONUS * max(0, len(distinct_categories) - 1))
        group_score = round(min(1.0, base + bonus), 4)
        groups.append(
            CorrelationGroup(
                component=comp,
                scored_findings=members_sorted,
                group_score=group_score,
                categories=distinct_categories,
            )
        )
    groups.sort(key=lambda g: g.group_score, reverse=True)
    return groups