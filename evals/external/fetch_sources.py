"""Fetch immutable external-evaluation source snapshots.

The repositories are deliberately kept out of Parcel's Python environment and
Git tree.  This command only creates detached, commit-pinned working trees in
``.cache/external-evals/repos``; benchmark adapters live in this repository.
"""

from __future__ import annotations

import argparse
import json
import subprocess
from collections.abc import Sequence
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_LOCK = Path(__file__).with_name("sources.lock.json")
DEFAULT_DESTINATION = REPO_ROOT / ".cache" / "external-evals" / "repos"


def load_lock(path: Path = DEFAULT_LOCK) -> dict[str, dict[str, str]]:
    payload: Any = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict) or payload.get("schema_version") != 1:
        raise ValueError(f"unsupported source lock schema: {path}")
    sources = payload.get("sources")
    if not isinstance(sources, dict) or not sources:
        raise ValueError(f"source lock has no sources: {path}")
    validated: dict[str, dict[str, str]] = {}
    for name, raw in sources.items():
        if not isinstance(name, str) or not isinstance(raw, dict):
            raise TypeError(f"invalid source entry in {path}")
        if raw.get("kind") != "git":
            raise ValueError(f"unsupported source kind for {name!r}")
        url = raw.get("url")
        commit = raw.get("commit")
        if (
            not isinstance(url, str)
            or not url.startswith("https://")
            or not isinstance(commit, str)
            or len(commit) != 40
            or any(ch not in "0123456789abcdef" for ch in commit)
        ):
            raise ValueError(f"invalid immutable git source {name!r}")
        validated[name] = {str(key): str(value) for key, value in raw.items()}
    return validated


def _run_git(arguments: Sequence[str], *, cwd: Path | None = None) -> str:
    result = subprocess.run(
        ["git", *arguments],
        cwd=cwd,
        check=True,
        text=True,
        capture_output=True,
    )
    return result.stdout.strip()


def fetch_source(name: str, source: dict[str, str], destination: Path) -> Path:
    destination = destination.expanduser().resolve()
    destination.mkdir(parents=True, exist_ok=True)
    target = destination / name
    if target.exists() and not (target / ".git").is_dir():
        raise FileExistsError(f"refusing to reuse non-git path: {target}")
    if not target.exists():
        _run_git(["clone", "--filter=blob:none", "--no-checkout", source["url"], str(target)])
    remote = _run_git(["remote", "get-url", "origin"], cwd=target)
    if remote.rstrip("/").removesuffix(".git") != source["url"].rstrip("/").removesuffix(
        ".git"
    ):
        raise ValueError(f"origin mismatch for {name}: {remote}")
    try:
        _run_git(["cat-file", "-e", f"{source['commit']}^{{commit}}"], cwd=target)
    except subprocess.CalledProcessError:
        _run_git(["fetch", "--depth=1", "origin", source["commit"]], cwd=target)
    _run_git(["checkout", "--detach", source["commit"]], cwd=target)
    actual = _run_git(["rev-parse", "HEAD"], cwd=target)
    if actual != source["commit"]:
        raise RuntimeError(f"commit verification failed for {name}: {actual}")
    return target


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("sources", nargs="*", help="source ids; default: all pinned sources")
    parser.add_argument("--lock", type=Path, default=DEFAULT_LOCK)
    parser.add_argument("--destination", type=Path, default=DEFAULT_DESTINATION)
    args = parser.parse_args(argv)

    locked = load_lock(args.lock)
    names = list(args.sources) if args.sources else list(locked)
    unknown = sorted(set(names) - set(locked))
    if unknown:
        parser.error(f"unknown source id(s): {', '.join(unknown)}")
    for name in names:
        target = fetch_source(name, locked[name], args.destination)
        print(f"{name}\t{locked[name]['commit']}\t{target}")
    return 0


if __name__ == "__main__":  # pragma: no cover - exercised through the CLI
    raise SystemExit(main())
