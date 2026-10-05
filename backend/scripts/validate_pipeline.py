#!/usr/bin/env python
"""End-to-end validation harness (tasks 12.1 + 12.2).

This is the runnable counterpart to the automated unit tests. It exercises the
*real* pipeline against *real* open-source Python repositories and validates the
sandbox security boundary live, which requires a Docker host and network access
that CI/unit-test environments deliberately don't have.

What it does
------------
1. **Sandbox isolation (12.2)** — builds the sandbox image if needed, then runs
   an outbound-connection probe inside a container using the exact isolation
   flags the production runner applies (``isolation_run_kwargs``). Confirms the
   network is BLOCKED.
2. **Full pipeline on real repos (12.1)** — clones 2-3 real Python repos of
   varying size via the real ``IngestionService`` and runs the full LangGraph
   workflow end-to-end, asserting each run reaches synthesis and produces the
   onboarding + tech-debt artifacts.

Usage
-----
    # from backend/, with the venv active and Docker running:
    python -m scripts.validate_pipeline                 # default repo set
    python -m scripts.validate_pipeline --skip-sandbox  # pipeline only
    python -m scripts.validate_pipeline --skip-pipeline # sandbox only
    python -m scripts.validate_pipeline --repo https://github.com/psf/cachecontrol

Exit code is non-zero if any validation fails, so it can gate a release.
"""

from __future__ import annotations

import argparse
import subprocess
import sys
import tempfile
import time
import traceback
from pathlib import Path

from app.config import get_settings
from app.orchestration.graph import run_workflow
from app.orchestration.state import make_initial_state
from app.sandbox import SANDBOX_IMAGE, isolation_run_kwargs
from app.services.ingestion import IngestionService

# Small-to-medium, permissively licensed, pure-Python repos with a real test
# suite and manifests. Kept small so a full run finishes in minutes.
DEFAULT_REPOS = [
    "https://github.com/benjaminp/six",            # tiny, single module
    "https://github.com/psf/cachecontrol",         # small, has tests + deps
    "https://github.com/pallets/click",            # medium, well-known
]

SANDBOX_DOCKERFILE_DIR = Path(__file__).resolve().parents[2] / "infra" / "sandbox"

NET_PROBE = (
    "import socket, sys\n"
    "try:\n"
    "    socket.setdefaulttimeout(5)\n"
    "    socket.create_connection(('1.1.1.1', 53))\n"
    "    print('NETWORK_REACHABLE'); sys.exit(0)\n"
    "except Exception:\n"
    "    print('NETWORK_BLOCKED'); sys.exit(1)\n"
)


def _p(msg: str) -> None:
    print(msg, flush=True)


# --------------------------------------------------------------------------
# 12.2 — live sandbox isolation
# --------------------------------------------------------------------------

def _ensure_sandbox_image(client) -> str:
    try:
        client.images.get(SANDBOX_IMAGE)
        return SANDBOX_IMAGE
    except Exception:
        pass
    _p(f"  sandbox image {SANDBOX_IMAGE} not found; building from "
       f"{SANDBOX_DOCKERFILE_DIR} ...")
    client.images.build(path=str(SANDBOX_DOCKERFILE_DIR), tag=SANDBOX_IMAGE, rm=True)
    return SANDBOX_IMAGE


def validate_sandbox_isolation() -> bool:
    _p("[12.2] Validating sandbox network isolation ...")
    try:
        import docker
    except ImportError:
        _p("  FAIL: docker SDK not installed (pip install docker).")
        return False

    try:
        client = docker.from_env()
        client.ping()
    except Exception as exc:
        _p(f"  FAIL: Docker daemon not reachable: {exc}")
        return False

    try:
        image = _ensure_sandbox_image(client)
    except Exception as exc:
        _p(f"  WARN: could not build sandbox image ({exc}); "
           f"falling back to python:3.12-slim for the probe.")
        image = "python:3.12-slim"
        try:
            client.images.pull("python:3.12-slim")
        except Exception:
            pass

    kwargs = isolation_run_kwargs(get_settings())
    try:
        out = client.containers.run(
            image,
            entrypoint=["python"],
            command=["-c", NET_PROBE],
            remove=True,
            stdout=True,
            stderr=True,
            **kwargs,
        ).decode("utf-8", errors="replace")
    except Exception as exc:
        _p(f"  FAIL: probe container errored: {exc}")
        return False

    blocked = "NETWORK_BLOCKED" in out and "NETWORK_REACHABLE" not in out
    _p(f"  probe output: {out.strip()!r}")
    _p("  PASS: outbound network is blocked." if blocked
       else "  FAIL: outbound network was REACHABLE inside the sandbox!")
    return blocked


# --------------------------------------------------------------------------
# 12.1 — full pipeline on real repos
# --------------------------------------------------------------------------

def validate_pipeline_on_repo(repo_url: str, index: int) -> bool:
    name = repo_url.rstrip("/").split("/")[-1]
    _p(f"[12.1] Running full pipeline on {repo_url} ...")
    settings = get_settings()
    ingestion = IngestionService(settings)
    run_id = f"validate-{name}-{int(time.time())}"

    try:
        result = ingestion.ingest(run_id, repo_url=repo_url)
    except Exception as exc:
        _p(f"  FAIL: ingestion failed: {exc}")
        return False

    _p(f"  ingested rev={result.revision[:10]} size={result.size_mb} MB "
       f"lang={result.language} manifests={result.manifest_files}")

    state = make_initial_state(
        run_id=run_id, repo_id=f"repo-{index}", job_id=run_id,
        workdir=str(result.workdir), revision=result.revision,
        language=result.language, manifest_files=result.manifest_files,
    )

    try:
        started = time.time()
        final = run_workflow(state)
        elapsed = time.time() - started
    except Exception as exc:
        _p(f"  FAIL: workflow raised: {exc}")
        traceback.print_exc()
        return False

    status = final.get("node_status", {})
    artifacts = final.get("artifacts", {})
    synth_ok = status.get("synthesis") == "complete"
    has_onboarding = "onboarding" in artifacts
    has_tech_debt = "tech_debt_report" in artifacts

    _p(f"  node_status: {status}")
    _p(f"  findings: {len(final.get('findings', []))}  "
       f"errors: {len(final.get('errors', []))}  elapsed: {elapsed:.1f}s")

    ok = synth_ok and has_onboarding and has_tech_debt
    if ok:
        _p(f"  PASS: pipeline completed with onboarding + tech-debt artifacts.")
    else:
        _p(f"  FAIL: synthesis={synth_ok} onboarding={has_onboarding} "
           f"tech_debt={has_tech_debt}")
    return ok


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", action="append", dest="repos",
                        help="Repo URL to run (repeatable). Overrides defaults.")
    parser.add_argument("--skip-sandbox", action="store_true",
                        help="Skip the live sandbox isolation check (12.2).")
    parser.add_argument("--skip-pipeline", action="store_true",
                        help="Skip the full-pipeline runs (12.1).")
    args = parser.parse_args()

    results: dict[str, bool] = {}

    if not args.skip_sandbox:
        results["sandbox_isolation (12.2)"] = validate_sandbox_isolation()
        _p("")

    if not args.skip_pipeline:
        repos = args.repos or DEFAULT_REPOS
        for i, url in enumerate(repos):
            results[f"pipeline:{url} (12.1)"] = validate_pipeline_on_repo(url, i)
            _p("")

    _p("=" * 60)
    _p("VALIDATION SUMMARY")
    _p("=" * 60)
    all_ok = True
    for label, ok in results.items():
        _p(f"  [{'PASS' if ok else 'FAIL'}] {label}")
        all_ok = all_ok and ok
    if not results:
        _p("  (nothing ran)")
    return 0 if all_ok else 1


if __name__ == "__main__":
    sys.exit(main())
