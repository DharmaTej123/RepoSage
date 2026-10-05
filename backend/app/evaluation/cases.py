"""Ground-truth evaluation cases (tasks 11.2-11.5)."""

from __future__ import annotations

from app.evaluation.models import (
    EvalCase,
    ExpectedDependency,
    ExpectedFinding,
    ExpectedOwnership,
    ExpectedQA,
)

CASES: list[EvalCase] = [
    EvalCase(
        name="layered_app",
        fixture="layered_app",
        expected_dependencies=[
            ExpectedDependency(source="app.db", target="app.utils"),
            ExpectedDependency(source="app.repository", target="app.db"),
            ExpectedDependency(source="app.service", target="app.repository"),
            ExpectedDependency(source="app.web", target="app.service"),
        ],
        expected_blast_radius={
            # changing utils affects everything downstream that (transitively)
            # imports it.
            "app.utils": ["app.db", "app.repository", "app.service", "app.web"],
        },
        expected_ownership=[
            ExpectedOwnership(module="app.service", primary_contributor_email="alice@example.com"),
        ],
        expected_findings=[
            ExpectedFinding(category="bus_factor", component="app.service"),
            ExpectedFinding(category="high_centrality"),
        ],
        qa=[
            ExpectedQA(question="What depends on app.repository?",
                       must_include=["app.service"]),
            ExpectedQA(question="What is the blast radius of changing app.utils?",
                       must_include=["app.web"]),
            ExpectedQA(question="Who has worked on app.service?",
                       must_include=["Alice", "not formal ownership"]),
            ExpectedQA(question="Who worked on app.doesnotexist?",
                       expect_insufficient=True),
        ],
    ),
    EvalCase(
        name="tested_lib",
        fixture="tested_lib",
        expected_dependencies=[
            ExpectedDependency(source="lib.mathx", target="lib.core"),
        ],
        # tests.test_core imports lib.core, so it is (correctly) a dependent.
        expected_blast_radius={"lib.core": ["lib.mathx", "tests.test_core"]},
        qa=[
            ExpectedQA(question="What should I read first?",
                       must_include=["lib.core"]),
        ],
    ),
]