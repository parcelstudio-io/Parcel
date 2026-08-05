"""D-S1: DuplexFrame contract + FrameInterleaver merge rules."""

from __future__ import annotations

import pytest

from parcel_robot.duplex.frames import ACT_IDLE, TEXT_SILENCE, DuplexFrame, FrameInterleaver


def test_tick_always_returns_idle_silence_when_empty() -> None:
    inter = FrameInterleaver(frame_hz=10.0)
    frame = inter.tick(now_s=0.0)
    assert isinstance(frame, DuplexFrame)
    assert frame == DuplexFrame(t=0, epoch=0, text=TEXT_SILENCE, act=ACT_IDLE)


def test_text_drains_one_token_per_frame_fifo() -> None:
    inter = FrameInterleaver()
    inter.push_text("hello", epoch=0)
    inter.push_text("world", epoch=0)
    first = inter.tick(now_s=0.0)
    second = inter.tick(now_s=0.1)
    third = inter.tick(now_s=0.2)
    assert first.text == "hello"
    assert second.text == "world"
    assert third.text == TEXT_SILENCE


def test_multiple_act_pushes_keep_last_in_window() -> None:
    inter = FrameInterleaver()
    inter.push_act("<gaze_owner>", epoch=0)
    inter.push_act("<twist:0:0>", epoch=0)
    frame = inter.tick(now_s=0.0)
    assert frame.act == "<twist:0:0>"
    # Acts do not backlog into the next window.
    assert inter.tick(now_s=0.1).act == ACT_IDLE


def test_set_epoch_drops_older_and_tick_matches_current() -> None:
    inter = FrameInterleaver()
    inter.push_text("stale", epoch=0)
    inter.push_act("<gaze_owner>", epoch=0)
    inter.set_epoch(1)
    inter.push_text("fresh", epoch=1)
    frame = inter.tick(now_s=0.0)
    assert frame.epoch == 1
    assert frame.text == "fresh"
    assert frame.act == ACT_IDLE


def test_frame_index_monotonic_across_epoch_bumps() -> None:
    inter = FrameInterleaver()
    assert inter.tick(now_s=0.0).t == 0
    inter.set_epoch(2)
    assert inter.tick(now_s=0.1).t == 1
    inter.set_epoch(3)
    assert inter.tick(now_s=0.2).t == 2


def test_drift_free_timing_over_10000_ticks() -> None:
    inter = FrameInterleaver(frame_hz=10.0)
    for index in range(10_000):
        frame = inter.tick(now_s=index * 0.1)
        assert frame.t == index
    snap = inter.snapshot()
    assert snap["t"] == 10_000
    assert snap["expected_t_from_clock"] == 10_000


def test_stale_epoch_pushes_ignored() -> None:
    inter = FrameInterleaver()
    inter.set_epoch(5)
    inter.push_text("old", epoch=4)
    inter.push_act("<gaze_owner>", epoch=4)
    frame = inter.tick(now_s=1.0)
    assert frame.text == TEXT_SILENCE
    assert frame.act == ACT_IDLE


def test_invalid_frame_hz() -> None:
    with pytest.raises(ValueError):
        FrameInterleaver(frame_hz=0.0)
