"""D-S2: ActTokenCodec round-trip, clamp, vocabulary stability."""

from __future__ import annotations

import pytest

from parcel_robot.duplex.act_codec import (
    ActCommand,
    ActTokenCodec,
    TwistBins,
    default_twist_bins,
)


def _default_codec() -> ActTokenCodec:
    return ActTokenCodec(twist=default_twist_bins())


def test_encode_decode_round_trip_lands_on_bin_centers() -> None:
    codec = _default_codec()
    bins = default_twist_bins()
    for vx in bins.vx_bins:
        for vyaw in bins.vyaw_bins:
            token = codec.encode_twist(vx, vyaw)
            command = codec.decode(token)
            assert command.kind == "twist"
            assert command.vx == pytest.approx(vx)
            assert command.vyaw == pytest.approx(vyaw)


def test_out_of_range_twists_clamp_to_edge_bins() -> None:
    codec = _default_codec()
    low = codec.decode(codec.encode_twist(-10.0, -10.0))
    high = codec.decode(codec.encode_twist(10.0, 10.0))
    bins = default_twist_bins()
    assert low.vx == bins.vx_bins[0]
    assert low.vyaw == bins.vyaw_bins[0]
    assert high.vx == bins.vx_bins[-1]
    assert high.vyaw == bins.vyaw_bins[-1]


def test_unknown_token_raises() -> None:
    codec = _default_codec()
    with pytest.raises(ValueError, match="unknown act token"):
        codec.decode("<not_a_token>")


def test_encode_gaze_skill_emote_helpers() -> None:
    codec = ActTokenCodec(
        twist=default_twist_bins(),
        skills=("NavigateTo",),
        emotes=("bow",),
    )
    assert codec.decode(codec.encode_gaze_owner()).name == "owner"
    assert codec.decode(codec.encode_gaze_release()).name == "release"
    bearing = codec.decode(codec.encode_gaze_bearing(0.0))
    assert bearing.kind == "gaze"
    assert bearing.name == "bearing_0"
    assert codec.decode(codec.encode_skill("NavigateTo")).name == "NavigateTo"
    assert codec.decode(codec.encode_emote("bow")).name == "bow"
    with pytest.raises(ValueError, match="unknown skill"):
        codec.encode_skill("NotASkill")


def test_vocabulary_stable_sorted_default_config() -> None:
    codec = _default_codec()
    vocab = codec.vocabulary()
    assert vocab == tuple(sorted(vocab))
    # Exact pinned list — reordering is a breaking model-facing change.
    expected = []
    expected.extend(
        f"<filler_gesture_{index}>" for index in range(4)
    )
    expected.extend(
        f"<filler_speech_{index}>" for index in range(4)
    )
    expected.extend(
        [
            "<gaze_bearing_0>",
            "<gaze_bearing_1>",
            "<gaze_bearing_2>",
            "<gaze_bearing_3>",
            "<gaze_bearing_4>",
            "<gaze_bearing_5>",
            "<gaze_bearing_6>",
            "<gaze_bearing_7>",
            "<gaze_owner>",
            "<gaze_release>",
            "<idle>",
        ]
    )
    for vx_i in range(7):
        for vyaw_i in range(5):
            expected.append(f"<twist:{vx_i}:{vyaw_i}>")
    assert vocab == tuple(sorted(expected))
    assert len(vocab) == 4 + 4 + 8 + 2 + 1 + 7 * 5


def test_is_idle_and_typed_commands() -> None:
    codec = ActTokenCodec(
        twist=default_twist_bins(),
        skills=("NavigateTo",),
        emotes=("bow",),
        filler_gestures=2,
    )
    assert codec.is_idle("<idle>")
    assert not codec.is_idle(codec.encode_twist(0.0, 0.0))
    assert codec.decode("<skill:NavigateTo>") == ActCommand(kind="skill", name="NavigateTo")
    assert codec.decode("<emote:bow>") == ActCommand(kind="emote", name="bow")
    gaze = codec.decode("<gaze_bearing_2>")
    assert gaze.kind == "gaze"
    assert gaze.bearing_rad == pytest.approx(2.0 * 3.141592653589793 * 2 / 8)


def test_unsorted_bins_rejected() -> None:
    with pytest.raises(ValueError):
        TwistBins(vx_bins=(0.2, 0.0), vyaw_bins=(0.0,))
