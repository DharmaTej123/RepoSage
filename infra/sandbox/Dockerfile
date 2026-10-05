# RepoSage sandbox image (task 5.1).
# Runs untrusted repository test suites with NO network and strict resource
# limits. The image itself ships only Python + coverage tooling; the target
# repository is bind-mounted read-only at runtime and its deps (if any) are
# installed into an isolated writable scratch venv by the entrypoint.
#
# Network isolation is enforced at RUN TIME via `--network=none` (see
# app/sandbox/docker_runner.py), not in the image.
FROM python:3.12-slim

# Non-root user; repo code must never run as root inside the container.
RUN useradd --create-home --uid 10001 sandboxer

# Minimal, pinned test tooling available regardless of repo deps.
RUN pip install --no-cache-dir "coverage>=7.6" "pytest>=8.3" "pytest-cov>=5.0"

WORKDIR /work
COPY entrypoint.sh /usr/local/bin/reposage-entrypoint
RUN chmod +x /usr/local/bin/reposage-entrypoint

USER sandboxer

# The runner overrides CMD; default is a safe no-op.
ENTRYPOINT ["/usr/local/bin/reposage-entrypoint"]