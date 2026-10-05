"""Manifest parsing (task 2.1).

Supports:
* ``requirements.txt`` (PEP 508 specifiers, one per line; -r includes followed).
* ``pyproject.toml`` — both PEP 621 ``[project].dependencies`` /
  ``optional-dependencies`` and Poetry ``[tool.poetry.dependencies]``.

Produces :class:`Dependency` records. A concrete pinned version (``== x.y.z``)
is extracted where present; range-only / unpinned specs keep ``version=None`` so
downstream code can mark them ``UNPINNED`` rather than guessing.
"""

from __future__ import annotations

import logging
import tomllib
from pathlib import Path

from packaging.requirements import InvalidRequirement, Requirement

from app.analyzers.dependencies.models import Dependency, DependencyKind

logger = logging.getLogger(__name__)


def _pinned_version(req: Requirement) -> str | None:
    """Return the version if the specifier pins exactly one (``==``/``===``)."""
    for spec in req.specifier:
        if spec.operator in ("==", "==="):
            return spec.version
    return None


def parse_requirements_txt(path: Path) -> list[Dependency]:
    deps: list[Dependency] = []
    manifest_name = path.name
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError as exc:
        logger.warning("Could not read %s: %s", path, exc)
        return deps

    for raw_line in lines:
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        # Skip pip options and includes (we only parse this manifest's own deps).
        if line.startswith("-"):
            continue
        # Strip inline comments and environment markers hash-comments.
        line = line.split(" #", 1)[0].strip()
        try:
            req = Requirement(line)
        except InvalidRequirement:
            logger.debug("Skipping unparsable requirement line: %s", raw_line)
            continue
        deps.append(
            Dependency(
                name=req.name.lower(),
                version=_pinned_version(req),
                raw=line,
                kind=DependencyKind.DIRECT,
                source_manifest=manifest_name,
            )
        )
    return deps


def _parse_spec_string(name: str, spec: str, manifest_name: str) -> Dependency | None:
    """Parse a single 'name spec' pair (used for Poetry / dict specs)."""
    try:
        req = Requirement(f"{name}{spec}" if spec and spec[0] in "<>=!~" else name)
    except InvalidRequirement:
        req = None
    version = _pinned_version(req) if req else None
    # Poetry pins like "^2.31.0" / "2.31.0" are not PEP 508; capture exact pins.
    if version is None and spec and spec[0].isdigit():
        version = spec
    return Dependency(
        name=name.lower(),
        version=version,
        raw=f"{name} {spec}".strip(),
        kind=DependencyKind.DIRECT,
        source_manifest=manifest_name,
    )


def parse_pyproject(path: Path) -> list[Dependency]:
    deps: list[Dependency] = []
    manifest_name = path.name
    try:
        data = tomllib.loads(path.read_text(encoding="utf-8"))
    except (OSError, tomllib.TOMLDecodeError) as exc:
        logger.warning("Could not parse %s: %s", path, exc)
        return deps

    # PEP 621
    project = data.get("project", {})
    for item in project.get("dependencies", []) or []:
        try:
            req = Requirement(item)
        except InvalidRequirement:
            continue
        deps.append(
            Dependency(
                name=req.name.lower(), version=_pinned_version(req), raw=item,
                kind=DependencyKind.DIRECT, source_manifest=manifest_name,
            )
        )
    for group in (project.get("optional-dependencies", {}) or {}).values():
        for item in group:
            try:
                req = Requirement(item)
            except InvalidRequirement:
                continue
            deps.append(
                Dependency(
                    name=req.name.lower(), version=_pinned_version(req), raw=item,
                    kind=DependencyKind.DIRECT, source_manifest=manifest_name,
                )
            )

    # Poetry
    poetry = data.get("tool", {}).get("poetry", {})
    for name, spec in (poetry.get("dependencies", {}) or {}).items():
        if name.lower() == "python":
            continue
        if isinstance(spec, str):
            dep = _parse_spec_string(name, spec, manifest_name)
        elif isinstance(spec, dict):
            dep = _parse_spec_string(name, str(spec.get("version", "")), manifest_name)
        else:
            dep = None
        if dep:
            deps.append(dep)

    return deps


def parse_manifests(repo_root: Path, manifest_files: list[str]) -> list[Dependency]:
    """Parse all detected manifests, de-duplicating by (name, source)."""
    deps: list[Dependency] = []
    for name in manifest_files:
        path = repo_root / name
        if not path.is_file():
            continue
        if name == "requirements.txt":
            deps.extend(parse_requirements_txt(path))
        elif name == "pyproject.toml":
            deps.extend(parse_pyproject(path))
        # setup.py/setup.cfg intentionally skipped in v1 (dynamic / fragile).

    # De-dupe: keep first occurrence per lowercased name.
    seen: set[str] = set()
    unique: list[Dependency] = []
    for d in deps:
        if d.name in seen:
            continue
        seen.add(d.name)
        unique.append(d)
    return unique
