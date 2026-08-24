"""Card P1-C — ``tools/enroll_owner_appearance.py``: what it refuses to write.

The enroller is the only place a human hands this system an identity, so almost
every assertion here is about a refusal. The two that matter most:

* it will not write the gallery **inside the repository** — the file describes a
  person's appearance and must not become a commit (the voice enroller's rule,
  kept identical so an operator learns one rule and not two);
* it will not write an **uncalibrated** gallery without being told to in so many
  words, because the derived boundary was *measured* admitting a stranger.

It also never opens the owner's ``parcel_memory.sqlite3``; card R27's isolation
rule is asserted here at the import surface rather than assumed.
"""

from __future__ import annotations

import importlib.util
import json
import stat
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
TOOL_PATH = REPO_ROOT / "tools" / "enroll_owner_appearance.py"
CLIP_PATH = REPO_ROOT / "tests" / "data" / "p1c_two_person_clip.json"


@pytest.fixture(scope="module")
def tool():
    spec = importlib.util.spec_from_file_location("enroll_owner_appearance", TOOL_PATH)
    module = importlib.util.module_from_spec(spec)
    sys.modules["enroll_owner_appearance"] = module
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def crops():
    from parcel_robot.owner_tracking.synthetic_clip import ClipScript, crop_for

    script = ClipScript.load(CLIP_PATH)
    return (
        [crop_for(script, i, "owner") for i in range(6)],
        [crop_for(script, i, "other") for i in range(6)],
    )


@pytest.fixture(scope="module")
def embed():
    from parcel_robot.owner_tracking.synthetic_clip import histogram_embed_image

    return histogram_embed_image


# ------------------------------------------------------------------ enroll()
def test_enroll_with_negatives_produces_a_calibrated_gallery(tool, crops, embed) -> None:
    owner, negative = crops
    gallery, report = tool.enroll(
        owner,
        negative,
        owner_id="owner-1",
        allow_uncalibrated=False,
        embed_fn=embed,
        model="fixture:histogram_embed_image/v1",
    )
    assert gallery.calibrated is True
    assert gallery.crops == 6
    assert report["negative_reference"] < report["threshold"] < report["leave_one_out_min"]
    assert len(report["per_crop_leave_one_out"]) == 6


def test_R11_enroll_without_negatives_is_refused_by_default(tool, crops, embed) -> None:
    owner, _negative = crops
    with pytest.raises(tool.EnrollmentRefusal, match="no negative crops"):
        tool.enroll(
            owner,
            [],
            owner_id="owner-1",
            allow_uncalibrated=False,
            embed_fn=embed,
            model="fixture:histogram_embed_image/v1",
        )


def test_R11_uncalibrated_is_available_but_must_be_asked_for(tool, crops, embed) -> None:
    owner, _negative = crops
    gallery, report = tool.enroll(
        owner,
        [],
        owner_id="owner-1",
        allow_uncalibrated=True,
        embed_fn=embed,
        model="fixture:histogram_embed_image/v1",
    )
    assert gallery.calibrated is False
    assert report["calibrated"] is False
    assert "negative_reference" not in report


def test_R11_too_few_crops_is_refused_with_the_count(tool, crops, embed) -> None:
    owner, negative = crops
    with pytest.raises(tool.EnrollmentRefusal, match="is not an enrollment"):
        tool.enroll(
            owner[:3],
            negative,
            owner_id="owner-1",
            allow_uncalibrated=True,
            embed_fn=embed,
            model="fixture:histogram_embed_image/v1",
        )


def test_R11_an_enrollment_that_is_two_different_people_is_refused(tool, crops, embed) -> None:
    """SEEDED RED: a gallery whose own crops disagree must not be written.

    Three crops of the owner and three of the stranger, presented as one person.
    The refusal is the *separation* check inside ``build_gallery`` — the owner's
    leave-one-out floor collapses to the cross-person score, and the negative
    (which is the same stranger) then clears it.
    """

    owner, negative = crops
    mixed = owner[:3] + negative[:3]
    with pytest.raises(Exception) as excinfo:
        tool.enroll(
            mixed,
            negative[3:],
            owner_id="owner-1",
            allow_uncalibrated=False,
            embed_fn=embed,
            model="fixture:histogram_embed_image/v1",
        )
    assert "cannot identify its owner" in str(excinfo.value)


def test_an_unnamed_encoder_is_refused(tool, crops, embed) -> None:
    owner, negative = crops
    with pytest.raises(tool.EnrollmentRefusal, match="does not name its encoder"):
        tool.enroll(
            owner, negative, owner_id="o", allow_uncalibrated=True, embed_fn=embed, model=""
        )


# --------------------------------------------------------------- the target
def test_the_gallery_may_not_be_written_inside_the_repository(tool) -> None:
    with pytest.raises(tool.EnrollmentRefusal, match="inside the repository"):
        tool.refuse_repo_path(REPO_ROOT / "tests" / "data" / "leak.json")
    with pytest.raises(tool.EnrollmentRefusal, match="inside the repository"):
        tool.refuse_repo_path(REPO_ROOT / "configs" / "leak.json")


def test_a_path_outside_the_repository_is_accepted(tool, tmp_path) -> None:
    tool.refuse_repo_path(tmp_path / "owner_appearance_gallery.json")  # no raise


def test_the_default_target_is_outside_the_repo(tool) -> None:
    from parcel_robot.owner_tracking.gallery import default_gallery_path

    target = default_gallery_path(None).resolve()
    with pytest.raises(ValueError):
        target.relative_to(REPO_ROOT)


# ------------------------------------------------------------------- the CLI
def _cli(tool, argv: list[str], monkeypatch, embed) -> int:
    """Run ``main`` with the encoder pinned to the deterministic stand-in."""

    monkeypatch.setattr(
        tool,
        "resolve_embed_fn",
        lambda **_kw: type(
            "R",
            (),
            {
                "available": True,
                "embed_fn": staticmethod(embed),
                "model": "fixture:histogram_embed_image/v1",
                "provider": "cpu_fixture",
                "reason": "",
            },
        )(),
    )
    monkeypatch.setattr(tool, "vision_model_sha256", lambda *a, **k: "")
    return tool.main(argv)


def test_cli_enrolls_from_the_clip_and_writes_0600(tool, tmp_path, monkeypatch, embed) -> None:
    target = tmp_path / "gallery.json"
    code = _cli(
        tool,
        [
            "--clip", str(CLIP_PATH),
            "--clip-person", "owner",
            "--clip-frames", "0-5",
            "--clip-negative", "other",
            "--clip-negative-frames", "0-5",
            "--out", str(target),
            "--yes",
        ],
        monkeypatch,
        embed,
    )
    assert code == tool.EXIT_OK
    assert stat.S_IMODE(target.stat().st_mode) == 0o600
    payload = json.loads(target.read_text(encoding="utf-8"))
    assert payload["calibrated"] is True
    assert payload["crops"] == 6
    assert payload["model"] == "fixture:histogram_embed_image/v1"


def test_cli_refuses_a_repo_target(tool, monkeypatch, embed, capsys) -> None:
    code = _cli(
        tool,
        ["--clip", str(CLIP_PATH), "--out", str(REPO_ROOT / "tests" / "data" / "leak.json"), "--yes"],
        monkeypatch,
        embed,
    )
    assert code == tool.EXIT_REFUSED
    assert "inside the repository" in capsys.readouterr().err
    assert not (REPO_ROOT / "tests" / "data" / "leak.json").exists()


def test_cli_refuses_without_negatives(tool, tmp_path, monkeypatch, embed, capsys) -> None:
    code = _cli(
        tool,
        ["--clip", str(CLIP_PATH), "--out", str(tmp_path / "g.json"), "--yes"],
        monkeypatch,
        embed,
    )
    assert code == tool.EXIT_REFUSED
    assert "no negative crops" in capsys.readouterr().err
    assert not (tmp_path / "g.json").exists()


def test_cli_needs_a_source(tool, tmp_path, monkeypatch, embed, capsys) -> None:
    code = _cli(tool, ["--out", str(tmp_path / "g.json"), "--yes"], monkeypatch, embed)
    assert code == tool.EXIT_REFUSED
    assert "pick a source" in capsys.readouterr().err


def test_cli_show_reports_absent_as_absent(tool, tmp_path, monkeypatch, embed, capsys) -> None:
    code = _cli(tool, ["--show", "--out", str(tmp_path / "nothing.json")], monkeypatch, embed)
    assert code == tool.EXIT_ABSENT
    assert "nobody has enrolled" in capsys.readouterr().out


def test_cli_show_refuses_a_broken_gallery(tool, tmp_path, monkeypatch, embed, capsys) -> None:
    broken = tmp_path / "broken.json"
    broken.write_text('{"schema": "wrong"}', encoding="utf-8")
    code = _cli(tool, ["--show", "--out", str(broken)], monkeypatch, embed)
    assert code == tool.EXIT_REFUSED
    assert "declares schema" in capsys.readouterr().err


def test_cli_show_warns_loudly_about_an_uncalibrated_gallery(
    tool, tmp_path, monkeypatch, embed, capsys
) -> None:
    target = tmp_path / "g.json"
    assert (
        _cli(
            tool,
            [
                "--clip", str(CLIP_PATH),
                "--clip-frames", "0-5",
                "--allow-uncalibrated",
                "--out", str(target),
                "--yes",
            ],
            monkeypatch,
            embed,
        )
        == tool.EXIT_OK
    )
    capsys.readouterr()
    assert _cli(tool, ["--show", "--out", str(target)], monkeypatch, embed) == tool.EXIT_OK
    captured = capsys.readouterr()
    assert "calibrated: False" in captured.out
    assert "admitting a stranger" in captured.err


def test_cli_declining_the_confirmation_writes_nothing(
    tool, tmp_path, monkeypatch, embed
) -> None:
    monkeypatch.setattr("builtins.input", lambda _prompt: "n")
    target = tmp_path / "g.json"
    code = _cli(
        tool,
        [
            "--clip", str(CLIP_PATH),
            "--clip-negative", "other",
            "--out", str(target),
        ],
        monkeypatch,
        embed,
    )
    assert code == tool.EXIT_ABSENT
    assert not target.exists()


def test_frame_range_parsing(tool) -> None:
    assert tool._parse_range("0-5") == [0, 1, 2, 3, 4, 5]
    assert tool._parse_range("0,2,4") == [0, 2, 4]
    assert tool._parse_range("0-2,7") == [0, 1, 2, 7]


def test_the_camera_path_refuses_cleanly_when_there_is_no_camera(tool) -> None:
    """OWNER-GATED. This host has no camera; the refusal must name the reason."""

    with pytest.raises(tool.EnrollmentRefusal) as excinfo:
        tool.crops_from_camera("/dev/video-does-not-exist", 0.1, 2.0)
    message = str(excinfo.value)
    assert "opencv-python" in message or "no camera" in message


def test_the_tool_never_reaches_the_owner_store(tool) -> None:
    """R27: an enrollment must not be the thing that opens parcel_memory.sqlite3."""

    import ast

    tree = ast.parse(TOOL_PATH.read_text(encoding="utf-8"))
    imported: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported.add(node.module)
    # An AST walk and not a text scan: the module DOCSTRING names the store, on
    # purpose, to say it is not touched. A grep would fail on the sentence that
    # promises the property.
    forbidden = ("sqlite3", "parcel_robot.memory.conversation", "parcel_robot.memory.path",
                 "parcel_robot.memory.store", "parcel_robot.memory.tiered")
    reached = sorted(name for name in imported if name.startswith(forbidden))
    assert reached == [], f"the enroller imports {reached}"
