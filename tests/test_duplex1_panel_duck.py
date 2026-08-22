"""Card DUPLEX-1: the panel half of the duck, evaluated in a real JS engine.

WHY THIS FILE IS NOT A STRING ASSERTION
---------------------------------------
MARK-1's correction pass established the rule the hard way: its browser-half
blocker ("the unpinned hello was read as a pin") shipped green because the test
matched source text instead of running it, and the executor's "no JS engine on
this host" claim was false — ``/usr/bin/gjs`` (SpiderMonkey) is here. So the
functions this card adds to ``ui/index.html`` are LIFTED OUT of the shipped
file and evaluated, against the JSON the product gateway really emits.

Three things are checked:

1. ``duckGainFor`` — the whole admission decision for a ``duck`` frame — run in
   gjs against frames minted by the real :class:`BrowserAudioGateway`;
2. the panel still parses as a whole after the edit (``new Function``), MARK-1's
   own smoke test, because a syntax error in a 2 900-line file is silent until
   an owner clicks the microphone;
3. the structural facts a JS engine cannot see: every playback source goes
   through the gain node, and the gain returns to unity on both frames that end
   an utterance.
"""

from __future__ import annotations

import json
import re
import shutil
import subprocess
from pathlib import Path

import pytest

from parcel_robot.duplex.turn_controller import MIN_DUCK_GAIN
from parcel_robot.realtime.audio_gateway import DUCK_GAIN_RANGE, BrowserAudioGateway

PANEL = Path(__file__).resolve().parents[1] / "src" / "parcel_robot" / "ui" / "index.html"
JS_ENGINE = shutil.which("gjs") or shutil.which("node") or shutil.which("qjs")

TOKEN = "panel-token-duplex1"


def _panel() -> str:
    return PANEL.read_text(encoding="utf-8")


def _duck_gain_for_source() -> str:
    """Lift ``duckGainFor`` out of the shipped panel, verbatim.

    Extracted rather than restated: a test that re-typed the function would go
    on passing while the panel shipped a different one — the exact mistake
    MARK-1's blocker was.
    """

    panel = _panel()
    start = panel.index("function duckGainFor(mic, body) {")
    end = panel.index("\n    }", start) + len("\n    }")
    body = panel[start:end]
    assert body.count("{") == body.count("}"), "duckGainFor did not extract cleanly"
    return body


def _min_duck_gain_source() -> str:
    """Lift the panel's own floor constant, so the test never invents one."""

    match = re.search(r"^\s*const MIN_DUCK_GAIN = [0-9.]+;$", _panel(), re.MULTILINE)
    assert match, "the panel must declare MIN_DUCK_GAIN in one const line"
    return match.group(0).strip()


def _eval_duck_raw(mic: dict, body: dict, tmp_path: Path) -> tuple[str, str]:
    """Run the panel's admission rule and report ``(kind, text)``, not JSON.

    **Correction pass, finding 1.** The first version of this helper serialised
    the answer with ``JSON.stringify``, which encodes ``NaN`` as ``null``. A
    gain that leaked through the guard as ``NaN`` and a gain that was properly
    REFUSED therefore looked identical to the assertion, so the test could not
    fail for the reason it existed. The value is reported as a type tag plus
    ``String(value)`` instead, so ``null``, ``NaN`` and ``0`` are three
    different answers here exactly as they are in the engine.
    """

    script = tmp_path / "duck.js"
    script.write_text(
        f"{_min_duck_gain_source()}\n"
        f"{_duck_gain_for_source()}\n"
        f"const g = duckGainFor({json.dumps(mic)}, {json.dumps(body)});\n"
        "print((g === null ? 'null' : (Number.isNaN(g) ? 'nan' : typeof g)) "
        "+ '\\u0001' + String(g));\n",
        encoding="utf-8",
    )
    proc = subprocess.run(
        [JS_ENGINE, str(script)], capture_output=True, text=True, check=False, timeout=60
    )
    assert proc.returncode == 0, f"{JS_ENGINE} failed: {proc.stderr.strip()}"
    kind, _sep, text = proc.stdout.strip().partition("\u0001")
    return kind, text


def _eval_duck(mic: dict, body: dict, tmp_path: Path) -> float | None:
    """The admitted gain, or ``None`` when the panel refused the frame.

    ``NaN`` is neither: it raises here, because a ``NaN`` reaching the gain node
    is a defect and must never be readable as a refusal.
    """

    kind, text = _eval_duck_raw(mic, body, tmp_path)
    if kind == "null":
        return None
    assert kind == "number", f"duckGainFor returned a {kind}: {text}"
    return float(text)


def _gateway_duck_frames(gain: float) -> list[dict]:
    """The frames the PRODUCT emits, not frames a test invented."""

    gateway = BrowserAudioGateway(on_audio=lambda _f: None, on_mic=lambda _on: None)
    gateway.bind_token(TOKEN)
    gateway.start()
    conn = gateway.attach(TOKEN)
    gateway.begin_utterance()
    gateway.duck(gain)
    frames = [
        json.loads(frame)
        for frame in conn.drain()
        if isinstance(frame, str) and '"duck"' in frame
    ]
    gateway.stop()
    return frames


# =========================================== A. the admission rule, in gjs
@pytest.mark.skipif(JS_ENGINE is None, reason="no ECMAScript engine on this host")
def test_the_panel_accepts_the_duck_frame_the_gateway_actually_sends(tmp_path: Path) -> None:
    """The happy path, end to end across the language boundary."""

    frames = _gateway_duck_frames(0.18)
    assert len(frames) == 1
    frame = frames[0]
    assert frame["type"] == "duck"

    mic = {"gain": {}, "utterance": frame["utterance"]}
    assert _eval_duck(mic, frame, tmp_path) == pytest.approx(0.18)


@pytest.mark.skipif(JS_ENGINE is None, reason="no ECMAScript engine on this host")
def test_a_duck_for_another_utterance_is_refused_by_the_panel(tmp_path: Path) -> None:
    """The rule that stops a late duck making the NEXT reply inaudible.

    Seed: drop the ``utterance !== mic.utterance`` line from ``duckGainFor`` and
    this returns 0.18 instead of null.
    """

    frame = _gateway_duck_frames(0.18)[0]
    stale = {"gain": {}, "utterance": frame["utterance"] + 1}
    assert _eval_duck(stale, frame, tmp_path) is None


@pytest.mark.skipif(JS_ENGINE is None, reason="no ECMAScript engine on this host")
def test_a_panel_with_no_gain_node_refuses_every_duck(tmp_path: Path) -> None:
    """An older tab, or a context that failed to build the node."""

    frame = _gateway_duck_frames(0.18)[0]
    assert _eval_duck({"gain": None, "utterance": frame["utterance"]}, frame, tmp_path) is None


@pytest.mark.skipif(JS_ENGINE is None, reason="no ECMAScript engine on this host")
@pytest.mark.parametrize(
    "gain_field",
    [
        pytest.param({}, id="missing"),
        pytest.param({"gain": None}, id="null"),
        pytest.param({"gain": ""}, id="empty-string"),
        pytest.param({"gain": []}, id="empty-array"),
        pytest.param({"gain": False}, id="false"),
        pytest.param({"gain": True}, id="true"),
        pytest.param({"gain": "0.18"}, id="numeric-string"),
        pytest.param({"gain": "loud"}, id="word"),
        pytest.param({"gain": {}}, id="object"),
    ],
)
def test_the_panel_refuses_every_gain_that_is_not_a_number(gain_field: dict, tmp_path: Path) -> None:
    """**Correction pass, finding 1 — MARK-1's blocker, one card later.**

    ``Number(x)`` is not a type check. ToNumber of ``null``, ``""``, ``[]`` and
    ``false`` is ``+0`` — finite, in range, and clamped to a **silent** reply.
    The shipped panel muted the dog mid-sentence on any of them, and the test
    that was supposed to catch it asserted ``result is None or result == 0.0``,
    which covers the only two outcomes the code could produce: it stayed green
    against a mutant with the finiteness guard deleted.

    Every member of the family must now be a REFUSAL — not a zero, not a NaN.
    Seed: delete the ``typeof body.gain !== "number"`` clause and the four
    ToNumber-to-zero ids go RED.
    """

    frame = _gateway_duck_frames(0.18)[0]
    mic = {"gain": {}, "utterance": frame["utterance"]}
    body = {"type": "duck", "utterance": frame["utterance"], **gain_field}
    kind, text = _eval_duck_raw(mic, body, tmp_path)
    assert kind == "null", f"the panel admitted {text!r} as a gain ({kind})"


@pytest.mark.skipif(JS_ENGINE is None, reason="no ECMAScript engine on this host")
def test_the_panel_never_produces_a_silent_reply(tmp_path: Path) -> None:
    """A duck to silence is a dropped connection, not a quieter dog.

    Correction pass: the previous version of this row asserted that a gain of
    ``-2`` clamps to ``0.0`` under the banner "our own bug must not silence the
    dog" — and clamping to 0.0 *is* silencing the dog. The clamp now bottoms out
    at ``MIN_DUCK_GAIN``, and the product constant is the same object on both
    sides of the language boundary.
    """

    frame = _gateway_duck_frames(0.18)[0]
    mic = {"gain": {}, "utterance": frame["utterance"]}
    for asked in (-2, 0, 0.0001, MIN_DUCK_GAIN / 2):
        body = {"type": "duck", "utterance": frame["utterance"], "gain": asked}
        admitted = _eval_duck(mic, body, tmp_path)
        assert admitted == pytest.approx(MIN_DUCK_GAIN), asked
    high = {"type": "duck", "utterance": frame["utterance"], "gain": 4}
    assert _eval_duck(mic, high, tmp_path) == pytest.approx(1.0)


def test_the_panels_floor_is_the_products_floor() -> None:
    """The JS literal and the Python constant are one number or they will rot."""

    panel = _panel()
    assert f"const MIN_DUCK_GAIN = {MIN_DUCK_GAIN};" in panel
    assert "Math.max(MIN_DUCK_GAIN, Math.min(1, body.gain))" in panel
    assert DUCK_GAIN_RANGE == (MIN_DUCK_GAIN, 1.0)


def test_the_gateway_also_refuses_to_clamp_a_duck_to_silence() -> None:
    """The same rule on the sending side, through the real gateway."""

    for asked in (-1.0, 0.0, 0.001):
        frames = _gateway_duck_frames(asked)
        assert frames[0]["gain"] == pytest.approx(MIN_DUCK_GAIN), asked


# ============================================ B. the file still parses at all
@pytest.mark.skipif(JS_ENGINE is None, reason="no ECMAScript engine on this host")
def test_the_whole_panel_script_still_parses(tmp_path: Path) -> None:
    """MARK-1's smoke test, re-run after this card's edits."""

    panel = _panel()
    start = panel.index("<script>", panel.index("<body>"))
    body = panel[panel.index(">", start) + 1 : panel.index("</script>", start)]
    script = tmp_path / "parse.js"
    payload = tmp_path / "panel_body.js"
    payload.write_text(body, encoding="utf-8")
    script.write_text(
        "const GLib = imports.gi.GLib;\n"
        f"const [ok, bytes] = GLib.file_get_contents({json.dumps(str(payload))});\n"
        "const source = new TextDecoder().decode(bytes);\n"
        "new Function(source);\n"
        "print('PARSE OK ' + source.length);\n",
        encoding="utf-8",
    )
    proc = subprocess.run(
        [JS_ENGINE, str(script)], capture_output=True, text=True, check=False, timeout=60
    )
    assert proc.returncode == 0, f"panel does not parse: {proc.stderr.strip()}"
    assert proc.stdout.startswith("PARSE OK")


# ================================ C. structure a JS engine cannot see for us
def test_every_playback_source_goes_through_the_gain_node() -> None:
    """The one line that makes ducking possible at all.

    Seed: put ``source.connect(mic.playback.destination)`` back and this goes
    RED — and so does every duck row, because the gain node would be attached
    to nothing.
    """

    panel = _panel()
    assert "source.connect(mic.gain || mic.playback.destination);" in panel
    assert "mic.gain = mic.playback.createGain();" in panel
    assert "mic.gain.connect(mic.playback.destination);" in panel
    # ...and no source may bypass it.
    assert not re.search(r"source\.connect\(mic\.playback\.destination\)\s*;", panel)


def test_the_gain_returns_to_unity_on_both_frames_that_end_an_utterance() -> None:
    """A tab left at 0.18 would make the NEXT reply quiet for no visible reason.

    Seed: delete either ``resetDuck(mic)`` call and the panel carries a duck
    across replies.
    """

    panel = _panel()
    utterance = panel[panel.index('if (body.type === "utterance") {') :]
    utterance = utterance[: utterance.index("return;")]
    assert "resetDuck(mic)" in utterance, "a new utterance must start audible"

    stop_playback = panel[panel.index("function stopPlayback(mic) {") :]
    stop_playback = stop_playback[: stop_playback.index("\n    }")]
    assert "resetDuck(mic)" in stop_playback, "a stop must not leave the panel ducked"


def test_the_duck_uses_a_ramp_rather_than_a_step() -> None:
    """A step change in gain is an audible click, and a click sounds broken."""

    panel = _panel()
    assert "setTargetAtTime(level, mic.playback.currentTime, DUCK_RAMP_S)" in panel
    assert re.search(r"const DUCK_RAMP_S = 0\.0\d+;", panel)
