"""Sandbox network-isolation test (tasks 5.7, 12.2).

Confirms that code running inside the sandbox container CANNOT make outbound
network connections. This is a security-boundary regression test: it exercises
the SAME isolation flags the production runner applies (via
``isolation_run_kwargs``) rather than a hand-copied approximation that could
silently drift from the real configuration.

Requires a running Docker daemon; skips cleanly otherwise (e.g. CI without
Docker) so the suite stays green while the assertion runs wherever Docker is
available.
"""

from __future__ import annotations

import pytest

from app.config import get_settings
from app.sandbox import SANDBOX_IMAGE, isolation_run_kwargs


def _docker_available() -> bool:
    try:
        import docker

        client = docker.from_env()
        client.ping()
        return True
    except Exception:
        return False


requires_docker = pytest.mark.skipif(
    not _docker_available(),
    reason="Docker daemon not available; sandbox isolation test requires Docker.",
)

# A minimal script that attempts an outbound connection and reports the result.
# It writes nothing to disk, so it runs fine under the read-only container fs.
NET_PROBE = (
    "import socket, sys\n"
    "try:\n"
    "    socket.setdefaulttimeout(5)\n"
    "    socket.create_connection(('1.1.1.1', 53))\n"
    "    print('NETWORK_REACHABLE')\n"
    "    sys.exit(0)\n"
    "except Exception:\n"
    "    print('NETWORK_BLOCKED')\n"
    "    sys.exit(1)\n"
)


def _image_exists(client, image: str) -> bool:
    try:
        client.images.get(image)
        return True
    except Exception:
        return False


@requires_docker
def test_sandbox_blocks_outbound_network():
    """Repository code in the sandbox must not reach the network (Req 6).

    Runs the probe with the exact isolation kwargs the runner uses. Prefers the
    real sandbox image; falls back to the base python image the sandbox is built
    from when the image hasn't been built locally (the network isolation being
    tested is a runtime flag, not baked into the image).
    """
    import docker

    client = docker.from_env()
    image = SANDBOX_IMAGE if _image_exists(client, SANDBOX_IMAGE) else "python:3.12-slim"
    if not _image_exists(client, image):
        pytest.skip(f"neither {SANDBOX_IMAGE} nor python:3.12-slim available locally")

    kwargs = isolation_run_kwargs(get_settings())

    output = client.containers.run(
        image,
        # override the sandbox entrypoint so we run the probe directly
        entrypoint=["python"],
        command=["-c", NET_PROBE],
        remove=True,
        stdout=True,
        stderr=True,
        **kwargs,
    )
    text = output.decode("utf-8", errors="replace")

    assert "NETWORK_BLOCKED" in text
    assert "NETWORK_REACHABLE" not in text


def test_isolation_kwargs_enforce_security_boundary():
    """Guard the isolation contract itself so it can't be weakened unnoticed.

    Runs without Docker: pure assertions on the kwargs the runner will apply.
    """
    kwargs = isolation_run_kwargs(get_settings())
    assert kwargs["network_disabled"] is True
    assert kwargs["network_mode"] == "none"
    assert kwargs["read_only"] is True
    assert kwargs["cap_drop"] == ["ALL"]
    assert "no-new-privileges" in kwargs["security_opt"]
    assert kwargs["pids_limit"] >= 1
    assert kwargs["nano_cpus"] > 0
    assert kwargs["mem_limit"].endswith("m")
