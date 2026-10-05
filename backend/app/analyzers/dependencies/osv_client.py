"""OSV.dev client (task 2.2).

Uses the public OSV batch query API to look up vulnerabilities for a list of
(package, version) pairs. Returns results aligned to the input order.

The client raises :class:`OSVUnavailableError` on transport / non-2xx errors so
the caller can degrade gracefully (Req 3 / task 2.4) rather than failing the run.
"""

from __future__ import annotations

import logging

import httpx

from app.analyzers.dependencies.models import Vulnerability

logger = logging.getLogger(__name__)

OSV_QUERYBATCH_URL = "https://api.osv.dev/v1/querybatch"
OSV_VULN_URL = "https://api.osv.dev/v1/vulns"

# CVSS-ish / OSV database_specific severity normalization.
_SEVERITY_MAP = {
    "CRITICAL": "critical",
    "HIGH": "high",
    "MODERATE": "medium",
    "MEDIUM": "medium",
    "LOW": "low",
}


class OSVUnavailableError(Exception):
    """OSV could not be queried (network/API failure)."""


def _normalize_severity(vuln: dict) -> str | None:
    # Prefer database_specific.severity (GHSA), fall back to severity[].score.
    dbs = vuln.get("database_specific", {})
    sev = dbs.get("severity")
    if isinstance(sev, str):
        return _SEVERITY_MAP.get(sev.upper())
    for entry in vuln.get("severity", []) or []:
        # CVSS vector — bucket by base score if present in metadata.
        score = entry.get("score")
        if isinstance(score, str) and score.replace(".", "", 1).isdigit():
            f = float(score)
            if f >= 9.0:
                return "critical"
            if f >= 7.0:
                return "high"
            if f >= 4.0:
                return "medium"
            return "low"
    return None


class OSVClient:
    def __init__(self, client: httpx.Client | None = None, timeout: float = 20.0):
        self._client = client or httpx.Client(timeout=timeout)
        self._owns_client = client is None

    def query_batch(
        self, packages: list[tuple[str, str]]
    ) -> list[list[Vulnerability]]:
        """Query vulnerabilities for (name, version) pairs.

        Returns a list aligned with ``packages``; each entry is the list of
        vulnerabilities for that package (possibly empty = clean).
        Raises OSVUnavailableError on failure.
        """
        if not packages:
            return []
        payload = {
            "queries": [
                {"package": {"name": name, "ecosystem": "PyPI"}, "version": version}
                for name, version in packages
            ]
        }
        try:
            resp = self._client.post(OSV_QUERYBATCH_URL, json=payload)
            resp.raise_for_status()
        except (httpx.HTTPError, httpx.HTTPStatusError) as exc:
            logger.warning("OSV batch query failed: %s", exc)
            raise OSVUnavailableError(str(exc)) from exc

        results = resp.json().get("results", [])
        out: list[list[Vulnerability]] = []
        for entry in results:
            vulns: list[Vulnerability] = []
            for v in entry.get("vulns", []) or []:
                # batch returns ids/modified only; hydrate via /vulns/{id}.
                detail = self._get_vuln(v.get("id")) if v.get("id") else None
                if detail is not None:
                    vulns.append(detail)
                elif v.get("id"):
                    vulns.append(Vulnerability(id=v["id"]))
            out.append(vulns)
        # Pad if OSV returned fewer entries than queried.
        while len(out) < len(packages):
            out.append([])
        return out

    def _get_vuln(self, vuln_id: str) -> Vulnerability | None:
        try:
            resp = self._client.get(f"{OSV_VULN_URL}/{vuln_id}")
            resp.raise_for_status()
        except httpx.HTTPError as exc:
            logger.debug("OSV vuln detail fetch failed for %s: %s", vuln_id, exc)
            return Vulnerability(id=vuln_id)
        data = resp.json()
        fixed: list[str] = []
        for affected in data.get("affected", []) or []:
            for rng in affected.get("ranges", []) or []:
                for ev in rng.get("events", []) or []:
                    if "fixed" in ev:
                        fixed.append(ev["fixed"])
        return Vulnerability(
            id=data.get("id", vuln_id),
            summary=data.get("summary"),
            severity=_normalize_severity(data),
            aliases=data.get("aliases", []) or [],
            fixed_versions=sorted(set(fixed)),
            reference=f"{OSV_VULN_URL}/{data.get('id', vuln_id)}",
        )

    def close(self) -> None:
        if self._owns_client:
            self._client.close()
