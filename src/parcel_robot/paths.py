"""Runtime asset path resolution for source checkouts and packaged installs.

Parcel historically resolved ``configs/``, ``prompts/``, and skill YAML via
``REPO_ROOT = parents[N]`` from ``__file__``. That works for editable source
checkouts and fails for wheels / container images that only ship the package.

Resolution order (first hit wins):

1. ``PARCEL_ROOT`` environment variable (compose / CI bind-mount)
2. Repository root inferred from this file (``…/src/parcel_robot/paths.py``)
3. Packaged ``runtime_assets/`` shipped inside the wheel
"""

from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path

_PACKAGE_ROOT = Path(__file__).resolve().parent
_PACKAGED_ASSETS = _PACKAGE_ROOT / "runtime_assets"
_INFERRED_REPO_ROOT = _PACKAGE_ROOT.parents[1]  # …/src/parcel_robot → repo


@lru_cache(maxsize=1)
def parcel_roots() -> tuple[Path, ...]:
    """Ordered roots that may contain ``configs/`` and ``prompts/``."""

    roots: list[Path] = []
    env = os.environ.get("PARCEL_ROOT", "").strip()
    if env:
        roots.append(Path(env).expanduser().resolve())
    if (_INFERRED_REPO_ROOT / "configs").is_dir() or (_INFERRED_REPO_ROOT / "prompts").is_dir():
        roots.append(_INFERRED_REPO_ROOT.resolve())
    if _PACKAGED_ASSETS.is_dir():
        roots.append(_PACKAGED_ASSETS.resolve())
    # Deduplicate while preserving order.
    seen: set[Path] = set()
    ordered: list[Path] = []
    for root in roots:
        if root not in seen:
            seen.add(root)
            ordered.append(root)
    return tuple(ordered)


def package_root() -> Path:
    return _PACKAGE_ROOT


def packaged_assets_root() -> Path:
    return _PACKAGED_ASSETS


def resolve_asset(*parts: str, kind: str = "file") -> Path:
    """Resolve a repo-relative asset path across known roots.

    Raises ``FileNotFoundError`` with every candidate tried when missing.
    """

    relative = Path(*parts)
    tried: list[Path] = []
    for root in parcel_roots():
        candidate = (root / relative).resolve()
        tried.append(candidate)
        if kind == "dir" and candidate.is_dir():
            return candidate
        if kind == "file" and candidate.is_file():
            return candidate
    raise FileNotFoundError(
        f"Parcel asset not found: {relative.as_posix()} "
        f"(kind={kind}; searched={[str(p) for p in tried]})"
    )


def resolve_config_yaml(relative: str = "configs/robot.yaml") -> Path:
    """Prefer canonical repo config; fall back to the packaged module copy."""

    try:
        return resolve_asset(*Path(relative).parts, kind="file")
    except FileNotFoundError:
        fallback = _PACKAGE_ROOT / "config" / "robot.yaml"
        if fallback.is_file():
            return fallback.resolve()
        raise


def resolve_skills_root(configured: str | None = None) -> Path:
    relative = (configured or "configs/skills").strip() or "configs/skills"
    path = Path(relative).expanduser()
    if path.is_absolute():
        if path.is_dir():
            return path.resolve()
        raise FileNotFoundError(f"skills root missing: {path}")
    return resolve_asset(*path.parts, kind="dir")


def resolve_prompts_root(configured: str | None = None) -> Path:
    relative = (configured or "prompts").strip() or "prompts"
    path = Path(relative).expanduser()
    if path.is_absolute():
        if path.is_dir():
            return path.resolve()
        raise FileNotFoundError(f"prompts root missing: {path}")
    return resolve_asset(*path.parts, kind="dir")


def resolve_navigation_config(relative: str = "configs/navigation/default.yaml") -> Path:
    path = Path(relative).expanduser()
    if path.is_absolute():
        if path.is_file():
            return path.resolve()
        raise FileNotFoundError(f"navigation config missing: {path}")
    return resolve_asset(*path.parts, kind="file")
