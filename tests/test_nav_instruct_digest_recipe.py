"""Card AF-2 — the nav_instruct report/payload digest recipes, pinned.

Provenance: ``scrum/20260811/task_1/AUDIT_WAVE2_FABLE.md``, should-fix 4 —
"the ee234c63 recipe as documented does not reproduce; the payload shas are
serializer-unpinned — record the exact recipe or drop the numbers".

Three separate lanes published five digests of the SAME frozen row and each
wrote the recipe down differently, so none of them reproduced from the
documented text:

* the exclusion set was documented as four fields
  ``{report_id, elapsed_s, scene, navigator_flags}`` but is FIVE — the report
  also carries ``refreeze_provenance``, a free-text field that moves with every
  re-freeze. With four the digest is ``200f5653…``, not ``ee234c63…``;
* ``aggregate.scene`` is a SECOND, absolute copy of the scene path, so the
  ``ee234c63…`` form is path-dependent by construction (VS-4 §4 measured this
  correctly). Dropping it gives the path-independent form;
* ``json.dumps`` default separators (``", "`` / ``": "``) and compact
  separators (``","`` / ``":"``) give different bytes for the same content —
  that, and nothing else, is the whole difference between VS-4's
  ``897d6ce7…`` and VS-5's ``c172da37…``, and between the two lanes' episodes
  payload shas (VS-4 also sorted the rows by ``episode_id`` first).

These cells pin all five against the committed frozen row so a serializer or
field change can never silently invalidate a published number again. They claim
nothing about navigation: a legitimate re-freeze moves every one of them, and
the test skips when the row is absent.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
FROZEN_ROW = (
    REPO
    / "evals"
    / "nav_instruct"
    / "results"
    / "nav-instruct-v1-baseline-v4-20260811T070536Z.json"
)

#: The FIVE report-level fields a cross-run comparison must drop. Every one of
#: them is run identity or provenance, not a navigation outcome.
REPORT_EXCLUSIONS = frozenset(
    {"report_id", "elapsed_s", "scene", "navigator_flags", "refreeze_provenance"}
)

PATH_DEPENDENT_REPORT_DIGEST = (
    "ee234c6376d63dbfb9c1ffa1eb8d7333ac9fcfd57bc62495795cbe7010fa70f8"
)
PATH_INDEPENDENT_REPORT_DIGEST = (
    "897d6ce7ea709415eb11e498271f8292cd7b651042673928292d8a137df65bb9"
)
PATH_INDEPENDENT_REPORT_DIGEST_COMPACT = (
    "c172da375ff23987cb6414fe8899fa263f7ec00ef363659306a38c7719f7553a"
)
EPISODES_PAYLOAD_SORTED_BY_ID = (
    "bfb21cd25be4db9e02b3944479cfaf068d8f17f333743c32adc25c0b9d6ea8ca"
)
EPISODES_PAYLOAD_REPORT_ORDER_COMPACT = (
    "440fd8842854d446a0c5ffc6ccf625def708d4c9889cb4324a10f6a3ee41f8d6"
)
EPISODE_DIGEST = "4113607b92c734dfdd46004b6e77baf6575fc2a1c493e5d9dc5a12c6c5490222"


def _report() -> dict:
    if not FROZEN_ROW.exists():  # pragma: no cover - re-freeze removes the row
        pytest.skip(f"frozen row absent: {FROZEN_ROW.name}")
    return json.loads(FROZEN_ROW.read_text(encoding="utf-8"))


def _sha(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def report_digest(report: dict, *, drop_aggregate_scene: bool, compact: bool) -> str:
    """THE recipe. Every published nav_instruct report digest is one of these."""

    body = {k: v for k, v in report.items() if k not in REPORT_EXCLUSIONS}
    if drop_aggregate_scene and isinstance(body.get("aggregate"), dict):
        body = dict(body)
        body["aggregate"] = {k: v for k, v in body["aggregate"].items() if k != "scene"}
    kwargs: dict = {"sort_keys": True}
    if compact:
        kwargs["separators"] = (",", ":")
    return _sha(json.dumps(body, **kwargs))


def test_the_five_field_exclusion_reproduces_the_published_report_digest() -> None:
    report = _report()
    assert report_digest(
        report, drop_aggregate_scene=False, compact=False
    ) == PATH_DEPENDENT_REPORT_DIGEST


def test_the_documented_four_field_exclusion_does_not_reproduce() -> None:
    """The audit's finding, made concrete: the documented set is incomplete."""

    report = _report()
    four = {k: v for k, v in report.items() if k not in (REPORT_EXCLUSIONS - {"refreeze_provenance"})}
    assert _sha(json.dumps(four, sort_keys=True)) != PATH_DEPENDENT_REPORT_DIGEST


def test_the_path_dependent_digest_really_is_path_dependent() -> None:
    """``aggregate.scene`` holds an ABSOLUTE path; a scratch run cannot match."""

    report = _report()
    assert Path(report["aggregate"]["scene"]).is_absolute()
    moved = json.loads(json.dumps(report))
    moved["aggregate"]["scene"] = "/somewhere/else/city_block.xml"
    assert report_digest(
        moved, drop_aggregate_scene=False, compact=False
    ) != PATH_DEPENDENT_REPORT_DIGEST
    # ... and dropping it makes the SAME content reproducible anywhere.
    assert report_digest(
        moved, drop_aggregate_scene=True, compact=False
    ) == report_digest(report, drop_aggregate_scene=True, compact=False)


def test_the_two_published_path_independent_digests_differ_only_by_serializer() -> None:
    """VS-4's ``897d6ce7…`` and VS-5's ``c172da37…`` are the same claim."""

    report = _report()
    assert report_digest(
        report, drop_aggregate_scene=True, compact=False
    ) == PATH_INDEPENDENT_REPORT_DIGEST
    assert report_digest(
        report, drop_aggregate_scene=True, compact=True
    ) == PATH_INDEPENDENT_REPORT_DIGEST_COMPACT


def test_both_published_episodes_payload_shas_reproduce() -> None:
    """Row ORDER and separators are both part of the recipe."""

    episodes = _report()["episodes"]
    by_id = sorted(episodes, key=lambda row: row["episode_id"])
    assert _sha(json.dumps(by_id, sort_keys=True)) == EPISODES_PAYLOAD_SORTED_BY_ID
    assert (
        _sha(json.dumps(episodes, sort_keys=True, separators=(",", ":")))
        == EPISODES_PAYLOAD_REPORT_ORDER_COMPACT
    )
    # The report's own order is NOT sorted by id, which is why the two lanes'
    # payload shas differ even before the separators do.
    assert [row["episode_id"] for row in episodes] != [row["episode_id"] for row in by_id]


def test_the_in_report_episode_digest_is_unmoved() -> None:
    assert _report()["episode_digest"] == EPISODE_DIGEST
