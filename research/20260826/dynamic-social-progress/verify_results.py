"""Independent integrity and deterministic-replay checks for results.json."""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--results", type=Path, default=ROOT / "results" / "results.json")
    parser.add_argument("--rerun", action="store_true")
    args = parser.parse_args()
    payload = json.loads(args.results.read_text())
    fixtures_path = ROOT / "fixtures.json"
    experiment_path = ROOT / "experiment.py"
    fixtures = json.loads(fixtures_path.read_text())

    assert payload["fixtures_sha256"] == sha256(fixtures_path)
    assert payload["experiment_sha256"] == sha256(experiment_path)
    episodes = payload["episode_results"]
    digest = hashlib.sha256(json.dumps(episodes, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    assert digest == payload["episode_result_sha256"]
    expected = {
        (arm, template, seed)
        for arm in ("A0", "A1", "A2", "A3", "A4")
        for template in fixtures["splits"]["test"]["template_ids"]
        for seed in fixtures["splits"]["test"]["seeds"]
    }
    observed = {(e["arm"], e["template_id"], e["seed"]) for e in episodes}
    assert observed == expected
    assert len(episodes) == len(observed) == payload["episodes"]
    assert all(h["status"] in {"PASS", "REFUTED"} for h in payload["hypotheses"].values())

    replay_match = None
    if args.rerun:
        with tempfile.TemporaryDirectory(prefix="parcel-social-progress-") as directory:
            replay = Path(directory) / "results.json"
            subprocess.run(
                [str(ROOT.parents[2] / ".parcel" / "bin" / "python"), str(experiment_path), "--output", str(replay)],
                check=True,
                cwd=ROOT.parents[2],
            )
            replay_match = replay.read_bytes() == args.results.read_bytes()
            assert replay_match
    print(json.dumps({"integrity": "PASS", "episode_result_sha256": digest, "deterministic_replay_match": replay_match}, indent=2))


if __name__ == "__main__":
    main()
