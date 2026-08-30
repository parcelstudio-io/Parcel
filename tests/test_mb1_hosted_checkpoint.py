from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[1]
MB1 = ROOT / "research/20260829/model-b-narration-1"


def _module():
    sys.path.insert(0, str(MB1))
    spec = importlib.util.spec_from_file_location("mb1_hosted_checkpoint_run", MB1 / "run.py")
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def mb1(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    module = _module()
    realtime = tmp_path / "realtime.yaml"
    robot = tmp_path / "robot.yaml"
    ledger = tmp_path / "spend.jsonl"
    realtime.write_text("mode: text\n", encoding="utf-8")
    robot.write_text("audio: {}\n", encoding="utf-8")
    ledger.write_text("", encoding="utf-8")
    monkeypatch.setattr(module, "WAVE_REALTIME_CONFIG", realtime)
    monkeypatch.setattr(module, "WAVE_ROBOT_CONFIG", robot)
    monkeypatch.setattr(module, "WAVE_LEDGER", ledger)
    return module


def test_checkpoint_is_atomic_resumable_and_tamper_evident(mb1, tmp_path: Path) -> None:
    corpus = (SimpleNamespace(scenario_id="s1"),)
    fingerprint, config = mb1._hosted_fingerprint(
        corpus, seed=7, cap_usd=4.5, samples=1, arms=("Q",)
    )
    path = tmp_path / "checkpoint.json"
    checkpoint = mb1._read_hosted_checkpoint(
        path, fingerprint=fingerprint, config=config, resume=False
    )
    entry = {
        "key": "Q:0:s1",
        "arm": "Q",
        "sample": 0,
        "scenario_id": "s1",
        "session_id": "rt_test",
        "provenance": "exact_checkpoint",
        "turns": [],
        "ledger_before": mb1._ledger_evidence(),
        "ledger_after": mb1._ledger_evidence(),
        "recorded_utc": "2026-08-29T00:00:00Z",
    }
    entry["entry_sha256"] = mb1._entry_digest(entry)
    checkpoint["completed"].append(entry)
    mb1._checkpoint_save(path, checkpoint)

    loaded = mb1._read_hosted_checkpoint(
        path, fingerprint=fingerprint, config=config, resume=True
    )
    assert [row["key"] for row in loaded["completed"]] == ["Q:0:s1"]
    assert not list(tmp_path.glob(".*.tmp"))
    with pytest.raises(RuntimeError, match="pass --hosted-resume"):
        mb1._read_hosted_checkpoint(
            path, fingerprint=fingerprint, config=config, resume=False
        )

    tampered = json.loads(path.read_text(encoding="utf-8"))
    tampered["completed"][0]["session_id"] = "rt_tampered"
    path.write_text(json.dumps(tampered), encoding="utf-8")
    with pytest.raises(ValueError, match="digest mismatch"):
        mb1._read_hosted_checkpoint(
            path, fingerprint=fingerprint, config=config, resume=True
        )


def test_quota_exit_checkpoints_incomplete_and_never_retries(mb1, tmp_path: Path) -> None:
    from parcel_robot.realtime.ws_transport import RealtimeQuotaError

    corpus = (mb1.ev.build_corpus()[0],)
    checkpoint = tmp_path / "quota.checkpoint.json"

    class Governor:
        def snapshot(self):
            return {"month_readable": True, "month_to_date_usd": 0.0}

    class Runtime:
        realtime_governor = Governor()

        def close(self):
            self.closed = True

    class QuotaBackend:
        attempts = 0

        def __init__(self, _runtime, **_kwargs):
            self.refusals = []
            self.last_session_id = "rt_partial"

        def spend_usd(self):
            return 0.0

        def open_session(self, _scenario): ...

        def inject_item(self, **_kwargs):
            return 1

        def owner_turn(self, _text):
            type(self).attempts += 1
            raise RealtimeQuotaError("organization org-Private123 requests per day exhausted")

        def trigger_response(self):
            raise AssertionError("owner turn should fail first")

        def close(self): ...

    first = mb1.stage_hosted(
        corpus,
        mb1.sc.default_registry(),
        seed=20260829,
        cap_usd=4.5,
        samples=1,
        arms=("Q",),
        checkpoint_path=checkpoint,
        resume=False,
        runtime_factory=Runtime,
        backend_factory=QuotaBackend,
    )
    assert first["status"] == "PARTIAL_QUOTA"
    assert QuotaBackend.attempts == 1
    saved = json.loads(checkpoint.read_text(encoding="utf-8"))
    assert saved["completed"] == []
    assert saved["incomplete"][0]["key"].startswith("Q:0:")
    assert saved["incomplete"][0]["entry_sha256"]
    assert "org-[REDACTED]" in saved["incomplete"][0]["error"]
    assert "org-Private123" not in checkpoint.read_text(encoding="utf-8")

    second = mb1.stage_hosted(
        corpus,
        mb1.sc.default_registry(),
        seed=20260829,
        cap_usd=4.5,
        samples=1,
        arms=("Q",),
        checkpoint_path=checkpoint,
        resume=True,
        runtime_factory=lambda: (_ for _ in ()).throw(
            AssertionError("runtime must not be built")
        ),
        backend_factory=QuotaBackend,
    )
    assert second["status"] == "PARTIAL_INCOMPLETE_NEEDS_OVERRIDE"
    assert QuotaBackend.attempts == 1
