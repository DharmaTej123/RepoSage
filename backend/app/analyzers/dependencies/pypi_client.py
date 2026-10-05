"""PyPI JSON API client for release-date / staleness lookups (task 2.3).

Failures are non-fatal: an unreachable PyPI results in ``ReleaseInfo(available=
False)`` rather than raising, so staleness is simply reported as unknown for
that package.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone

import httpx

from app.analyzers.dependencies.models import ReleaseInfo

logger = logging.getLogger(__name__)

PYPI_JSON_URL = "https://pypi.org/pypi/{name}/json"


def _parse_upload_time(value: str | None) -> datetime | None:
    if not value:
        return None
    # PyPI uses ISO-8601, sometimes with trailing 'Z'.
    try:
        dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


class PyPIClient:
    def __init__(self, client: httpx.Client | None = None, timeout: float = 20.0):
        self._client = client or httpx.Client(timeout=timeout)
        self._owns_client = client is None

    def get_release_info(self, name: str, staleness_months: int) -> ReleaseInfo:
        try:
            resp = self._client.get(PYPI_JSON_URL.format(name=name))
            resp.raise_for_status()
        except httpx.HTTPError as exc:
            logger.warning("PyPI lookup failed for %s: %s", name, exc)
            return ReleaseInfo(available=False)

        data = resp.json()
        info = data.get("info", {})
        latest = info.get("version")
        releases = data.get("releases", {})

        last_date: datetime | None = None
        files = releases.get(latest, []) if latest else []
        for f in files:
            dt = _parse_upload_time(f.get("upload_time_iso_8601") or f.get("upload_time"))
            if dt and (last_date is None or dt > last_date):
                last_date = dt

        is_stale = False
        if last_date is not None:
            age_days = (datetime.now(timezone.utc) - last_date).days
            is_stale = age_days > staleness_months * 30

        return ReleaseInfo(
            latest_version=latest,
            last_release_date=last_date,
            is_stale=is_stale,
            available=True,
        )

    def close(self) -> None:
        if self._owns_client:
            self._client.close()
