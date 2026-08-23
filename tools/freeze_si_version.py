#!/usr/bin/env python3
"""Freeze one SI version's persona files so its text stays reproducible forever.

Card FZ-1 (``scrum/20260822/task_13``). The SI is assembled from three places:
``realtime/prompting.py``'s preamble, ``lane.GUARDRAILS`` (selected by version
since card R5), and the personality YAML in ``prompts/personalities``. The first
two are code and therefore already versioned; the third was read LIVE for every
version, so on 2026-08-22 a one-line persona edit by the owner changed what
``render_system_instruction(version="si-companion-v1")`` produced and the v1
pins — the provenance of a 52-query, 25-thread voice corpus — stopped being
reproducible from source.

This tool writes the missing third leg: a byte-for-byte snapshot of the live
persona files under ``prompts/personalities/_frozen/<si_version>/``.
:func:`parcel_robot.realtime.prompting.personality_source` reads that snapshot
for every version that is not the current :data:`SI_VERSION`, so a later persona
edit can no longer move a historical render.

WHEN TO RUN IT
--------------
At bump time, in this order:

1. Make the SI edit (persona YAML, preamble, or guardrails).
2. Register the new version: ``SI_Vn``/``SI_VERSION`` and, if the guardrail
   wording moved, its branch in ``si_guardrails``.
3. ``tools/freeze_si_version.py --version si-companion-vN`` — snapshots the live
   persona files for the NEW version and prints its rendered digests.
4. Paste the printed block into ``SI_DIGESTS``.

Freezing the version being *introduced* (not the one being retired) is what
makes the retirement free later: when vN+1 lands, vN already has its snapshot
and its render never moves again.

Usage::

    tools/freeze_si_version.py --version si-companion-v4     # snapshot + digests
    tools/freeze_si_version.py --version si-companion-v4 --force   # overwrite
    tools/freeze_si_version.py --check     # every registered version reproduces
"""

from __future__ import annotations

import argparse
import shutil
import sys
from pathlib import Path

import yaml

from parcel_robot.prompting import PromptLibrary
from parcel_robot.realtime.prompting import (
    SI_DIGESTS,
    SI_VERSION,
    PromptPlaneError,
    frozen_personas_dir,
    frozen_prompt_library,
    personality_source,
    render_system_instruction,
    si_guardrails,
)

REPO = Path(__file__).resolve().parents[1]


def live_personas_dir(prompts_root: Path) -> Path:
    return prompts_root / "personalities"


def live_persona_files(prompts_root: Path) -> list[Path]:
    return sorted(live_personas_dir(prompts_root).glob("*.yaml"))


def freeze(version: str, *, prompts_root: Path, force: bool = False) -> list[Path]:
    """Copy the live persona files into this version's snapshot dir.

    Refuses to overwrite an existing snapshot without ``--force``: a snapshot is
    a record of what a version *was*, and silently rewriting one would forge the
    provenance of every session captured under it.
    """

    sources = live_persona_files(prompts_root)
    if not sources:
        raise PromptPlaneError(
            f"no persona files to freeze under {live_personas_dir(prompts_root)}"
        )
    destination = frozen_personas_dir(version, prompts_root=prompts_root)
    if destination.is_dir() and not force:
        raise PromptPlaneError(
            f"{version} is already frozen at {destination}. A snapshot records the text "
            f"a version shipped with; rewriting it would silently re-attribute every "
            f"session captured under {version}. Pass --force only when the snapshot was "
            f"written in error and nothing has been captured under it yet."
        )
    destination.mkdir(parents=True, exist_ok=True)
    written: list[Path] = []
    for source in sources:
        target = destination / source.name
        shutil.copyfile(source, target)
        written.append(target)
    for stale in sorted(destination.glob("*.yaml")):
        if stale.name not in {source.name for source in sources}:
            stale.unlink()
    return written


def rendered_digests(version: str, *, prompts_root: Path) -> dict[str, str]:
    """Every personality's digest for one version, rendered from its SNAPSHOT.

    Goes through the product renderer, never a local re-implementation: what
    this prints is what ``render_system_instruction`` will produce for that
    version, or the number is worthless.
    """

    library = frozen_prompt_library(version, prompts_root=prompts_root)
    return {
        profile.id: render_system_instruction(
            profile_id=profile.id, library=library, version=version
        ).digest
        for profile in sorted(library.list_personalities(), key=lambda item: item.id)
    }


def digest_block(version: str, digests: dict[str, str]) -> str:
    lines = [f"    {_version_constant(version)}: {{"]
    for profile_id, digest in sorted(digests.items()):
        lines.append(f'        "{profile_id}": "{digest}",')
    lines.append("    },")
    return "\n".join(lines)


def _version_constant(version: str) -> str:
    """``si-companion-v4`` → ``SI_V4`` when it looks like one, else a literal."""

    tail = version.rsplit("-v", 1)
    if len(tail) == 2 and tail[0] == "si-companion" and tail[1].isdigit():
        return f"SI_V{tail[1]}"
    return f'"{version}"'


def check(prompts_root: Path) -> list[str]:
    """Every registered version must reproduce its pins from its snapshot alone."""

    problems: list[str] = []
    for version, pins in sorted(SI_DIGESTS.items()):
        try:
            digests = rendered_digests(version, prompts_root=prompts_root)
        except (PromptPlaneError, OSError, ValueError, TypeError, yaml.YAMLError) as error:
            # A snapshot that will not load is a REPORTABLE problem, not a
            # traceback: --check exists to name which version lost its text, and
            # a corrupted YAML is one of the ways that happens.
            problems.append(f"{version}: {type(error).__name__}: {error}")
            continue
        for profile_id, pinned in sorted(pins.items()):
            actual = digests.get(profile_id)
            if actual is None:
                problems.append(f"{version}/{profile_id}: not present in the snapshot")
            elif actual != pinned:
                problems.append(
                    f"{version}/{profile_id}: snapshot renders {actual[:12]}…, "
                    f"SI_DIGESTS pins {pinned[:12]}…"
                )
        extra = sorted(set(digests) - set(pins))
        if extra:
            problems.append(f"{version}: snapshot has unpinned personalities: {', '.join(extra)}")

    # The current version is the one the live files are still the source for, so
    # its snapshot must equal them byte-for-byte — otherwise the next bump would
    # retire a version into a snapshot that is not the text it shipped.
    current = frozen_personas_dir(SI_VERSION, prompts_root=prompts_root)
    for source in live_persona_files(prompts_root):
        target = current / source.name
        if not target.is_file():
            problems.append(
                f"{SI_VERSION}: {source.name} is not frozen (run --version {SI_VERSION})"
            )
        elif target.read_bytes() != source.read_bytes():
            problems.append(f"{SI_VERSION}: frozen {source.name} != the live persona file")
    return problems


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--version", help="SI version to snapshot, e.g. si-companion-v4")
    mode.add_argument(
        "--check",
        action="store_true",
        help="verify every registered version reproduces its pins from its snapshot",
    )
    parser.add_argument(
        "--force", action="store_true", help="overwrite an existing snapshot (see the refusal)"
    )
    parser.add_argument(
        "--prompts-root",
        type=Path,
        default=None,
        help="prompts tree to operate on (default: the repository's own)",
    )
    args = parser.parse_args(argv)

    prompts_root = (args.prompts_root or (REPO / "prompts")).resolve()
    if not live_personas_dir(prompts_root).is_dir():
        print(f"error: no personalities under {prompts_root}", file=sys.stderr)
        return 2

    if args.check:
        problems = check(prompts_root)
        if problems:
            print("frozen SI snapshots are NOT reproducible:", file=sys.stderr)
            for problem in problems:
                print(f"  - {problem}", file=sys.stderr)
            return 1
        pinned = sum(len(pins) for pins in SI_DIGESTS.values())
        print(
            f"frozen SI snapshots OK: {pinned} pinned digest(s) across "
            f"{len(SI_DIGESTS)} version(s) re-rendered from their snapshots"
        )
        return 0

    version = str(args.version)
    try:
        si_guardrails(version)
    except PromptPlaneError as error:
        print(f"error: {error}", file=sys.stderr)
        return 2
    try:
        written = freeze(version, prompts_root=prompts_root, force=args.force)
        digests = rendered_digests(version, prompts_root=prompts_root)
    except PromptPlaneError as error:
        print(f"error: {error}", file=sys.stderr)
        return 2

    for path in written:
        print(f"froze {path.relative_to(prompts_root.parent)}")
    print()
    print(f"# paste into SI_DIGESTS in src/parcel_robot/realtime/prompting.py ({version}):")
    print(digest_block(version, digests))

    if version == SI_VERSION:
        # Ask the product which library the CURRENT version reads, rooted at the
        # tree we were actually pointed at. Resolving the default root here would
        # compare this tree's snapshot against the REPOSITORY's live personas —
        # green for a --prompts-root that happens to be a copy, and silently
        # blind to drift in the tree the operator named.
        live = personality_source(version, library=PromptLibrary(prompts_root))
        drift = sorted(
            profile.id
            for profile in live.list_personalities()
            if render_system_instruction(
                profile_id=profile.id, library=live, version=version
            ).digest
            != digests.get(profile.id)
        )
        if drift:
            print(
                f"\nwarning: the live files no longer render {version} the way the snapshot "
                f"does for: {', '.join(drift)}",
                file=sys.stderr,
            )
            return 1
    return 0


if __name__ == "__main__":  # pragma: no cover - CLI entry point
    raise SystemExit(main())
