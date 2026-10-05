"""Sandboxed execution of untrusted repository code (Phase 5).

Repository code MUST only ever run inside a sandbox (Req 6). The Docker runner
is the production path (network-isolated, resource-limited, destroyed after
use). A local-subprocess runner exists ONLY for development/tests where Docker
is unavailable; it is explicitly opt-in and never used to run untrusted code in
production.
"""

from app.sandbox.models import SandboxResult, SandboxStatus
from app.sandbox.runner import (
    SANDBOX_IMAGE,
    SandboxRunner,
    get_sandbox_runner,
    isolation_run_kwargs,
)

__all__ = [
    "SandboxResult",
    "SandboxStatus",
    "SandboxRunner",
    "get_sandbox_runner",
    "isolation_run_kwargs",
    "SANDBOX_IMAGE",
]