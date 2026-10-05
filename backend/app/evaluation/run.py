"""Evaluation CLI: run the suite and persist results (task 11.12).

Usage:  python -m app.evaluation.run [output_path.json]
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

from app.evaluation.runner import EvaluationRunner


def main() -> None:
    out = Path(sys.argv[1]) if len(sys.argv) > 1 else Path("eval_results.json")
    report = EvaluationRunner().run_all()
    out.write_text(report.model_dump_json(indent=2), encoding="utf-8")

    print(f"Evaluation report written to {out}")
    print("\nAggregate metrics:")
    for k, v in report.aggregate().items():
        print(f"  {k}: {v}")
    print("\nBaseline vs agentic:")
    print(json.dumps(report.baseline_vs_agentic, indent=2))
    print("\nPer-case:")
    for c in report.cases:
        print(f"  [{c.case}] hallucination_rate={c.hallucination_rate}")
        for m in c.metrics:
            score = m.f1 if m.f1 is not None else m.accuracy
            print(f"    {m.name}: {score}")


if __name__ == "__main__":
    main()