#!/usr/bin/env bash
# Sandbox entrypoint (task 5.3).
# Runs the target repo test suite under coverage and writes coverage.json +
# a result manifest into the writable scratch dir (/scratch), which the host
# reads back. The repo is mounted read-only at /work/repo.
set -uo pipefail

REPO_DIR="${REPO_DIR:-/work/repo}"
SCRATCH="${SCRATCH:-/scratch}"
TIMEOUT_SECONDS="${TIMEOUT_SECONDS:-600}"

mkdir -p "$SCRATCH"
cd "$REPO_DIR" || { echo "repo dir missing" > "$SCRATCH/error.txt"; exit 3; }

# Install repo deps into an isolated venv in scratch (best-effort; no network
# means this only succeeds if wheels are vendored — usually it is skipped).
export PYTHONDONTWRITEBYTECODE=1

START=$(date +%s)
# Run pytest with coverage over the repo. Data files live in scratch.
COVERAGE_FILE="$SCRATCH/.coverage" \
  timeout "${TIMEOUT_SECONDS}s" python -m pytest \
    --cov="$REPO_DIR" \
    --cov-report="json:$SCRATCH/coverage.json" \
    -q 2>"$SCRATCH/stderr.txt" 1>"$SCRATCH/stdout.txt"
EXIT_CODE=$?
END=$(date +%s)

echo "{\"exit_code\": $EXIT_CODE, \"duration_seconds\": $((END-START))}" > "$SCRATCH/result.json"
exit $EXIT_CODE