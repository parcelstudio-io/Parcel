"""Card HW-7 (`scrum/20260822/task_42`) — the gate is honest on aarch64.

WHAT THIS FILE IS FOR. `scripts/ci_gate.py --tier commit` has only ever run on
one x86_64 desktop. The Go2 EDU+'s Orin NX is aarch64, and three of its four
venvs are deliberately not the product venv, so a gate run there can meet a
missing capability. Before this card that produced a hard ERROR out of
`_collect_ids` or a `fail` that read "scene does not compile:
ModuleNotFoundError" — true, useless, and not actionable. After it, such a row
is a typed SKIP that names the capability and the command that un-skips it.

WHAT THIS FILE DOES NOT DO. It never runs a tier. Every assertion here is
against the probe, the requirement table, the transform and the two shell
scripts' resolved values — no pytest is spawned, no gate is executed, no
network is touched. (The card's own gate runs are capped at two and belong in
a container, not in a test.)

WHY THE SHELL PINS ARE VALUES AND NOT A `git show` DIFF. The obvious test for
"the x86_64 branch did not change" is to diff against `HEAD`. It is also a test
that evaporates the moment this card is committed, because HEAD becomes the new
file. The x86_64 values are therefore written down here, copied from
`git show e15e466:scripts/env-audio.sh` and
`git show e15e466:scripts/install_speech_services.sh` while the card was open,
and a change to either side reddens.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

from scripts.ci_gate import (
    COMMIT_TIER_STAGE_NAMES,
    STAGE_REQUIREMENTS,
    GateResult,
    evaluate_host_capabilities,
    host_capabilities,
    hw7_apply_host_skips,
    summarize,
)

REPO = Path(__file__).resolve().parents[1]

#: The facts the probe reports about the host but never skips anything for.
#: `interpreter` is the correction pass's F3: on the Orin there are four venvs
#: and "mujoco is absent" means something different in each one.
EXPECTED_FACTS = {"arch", "cpython", "libc", "cpus", "repo", "interpreter"}

#: The capabilities it can be asked about. The last three are REPORT ONLY --
#: no commit-tier row needs them, which is itself one of this card's findings.
EXPECTED_CAPABILITIES = {
    "mujoco",
    "pytest",
    "xdist",
    "ruff",
    "portaudio",
    "onnxruntime",
    "cuda",
}

#: Card HW-7's measurement: the commit tier needs none of these. Declaring one
#: of them as a stage requirement would be the masking failure this card's
#: DESIGN §(g) names, so the test is written as a prohibition.
REPORT_ONLY = {"portaudio", "onnxruntime", "cuda"}


def _stub_stages() -> tuple[tuple[str, object], ...]:
    """One cheap green thunk per declared stage. Nothing here runs a gate."""

    return tuple(
        (name, (lambda n=name: GateResult(n, "commit", True, "pass", "stub")))
        for name in COMMIT_TIER_STAGE_NAMES
    )


# ---------------------------------------------------------------------------
# The probe (rows P1-P4)
# ---------------------------------------------------------------------------


def test_probe_reports_every_declared_entry_and_never_raises() -> None:
    caps = host_capabilities()
    assert set(caps) == EXPECTED_FACTS | EXPECTED_CAPABILITIES
    for name, entry in caps.items():
        assert entry["kind"] in {"fact", "capability"}, name
        assert isinstance(entry["present"], bool), name
        assert entry["detail"], f"{name} has no detail"
        if entry["kind"] == "capability":
            assert entry["unskip"], f"{name} is a capability with no un-skip command"


def test_arch_is_reported_as_a_measurement_when_nothing_overrides_it(monkeypatch) -> None:
    monkeypatch.delenv("PARCEL_HOST_ARCH", raising=False)
    detail = str(host_capabilities()["arch"]["detail"])
    assert detail.endswith("(measured)"), detail
    assert "OVERRIDE" not in detail


def test_the_arch_override_says_it_is_an_override_and_names_the_measured_value() -> None:
    """Row P3. There is no aarch64 box and no emulator on the dev host, so the
    override is the only way to evaluate the row set as the Orin would see it.
    An override that printed like a measurement would be worse than none."""

    import platform

    measured = platform.machine()
    detail = str(host_capabilities(env={"PARCEL_HOST_ARCH": "aarch64"})["arch"]["detail"])
    assert detail.startswith("aarch64")
    assert "OVERRIDE PARCEL_HOST_ARCH" in detail
    assert measured in detail, "the override must not hide what the host actually is"


def test_the_probe_starts_no_subprocess(monkeypatch) -> None:
    """Row P4. GATE-0b's rule for the skip-list row, applied to this one: a
    declaration is a stat or a spec lookup, never a platform test. A probe that
    shells out is a probe that can hang a gate."""

    def explode(*args, **kwargs):  # pragma: no cover - the assertion is that it never runs
        raise AssertionError(f"the host probe started a subprocess: {args!r}")

    monkeypatch.setattr(subprocess, "run", explode)
    monkeypatch.setattr(subprocess, "Popen", explode)
    caps = host_capabilities()
    assert caps["arch"]["present"] is True


# ---------------------------------------------------------------------------
# The requirement table (rows P5, P6)
# ---------------------------------------------------------------------------


def test_every_requirement_names_a_declared_capability_of_a_declared_stage() -> None:
    caps = host_capabilities()
    for stage, required in STAGE_REQUIREMENTS.items():
        assert stage in COMMIT_TIER_STAGE_NAMES, f"{stage} is not a commit-tier stage"
        assert required, f"{stage} declares an empty requirement tuple; drop the row instead"
        for name in required:
            assert name in caps, f"{stage} requires undeclared capability {name!r}"
            assert caps[name]["kind"] == "capability", f"{stage} requires the FACT {name!r}"


def test_no_stage_gates_on_a_report_only_capability() -> None:
    """The measurement this card exists to record: NOTHING in the commit tier
    needs CUDA, a GPU, onnxruntime or PortAudio. GATE-0b's clean clone
    installed `.[dev,voice]` -- no perception extra, no nvidia-* -- and passed
    10/10 hard gates. Declaring one of them here would let a real regression
    hide behind a skip on the very host the gate is meant to be honest on."""

    for stage, required in STAGE_REQUIREMENTS.items():
        overlap = REPORT_ONLY.intersection(required)
        assert not overlap, f"{stage} gates on report-only capability/ies {sorted(overlap)}"


#: The declaration this card is FOR, written out so that changing it is a
#: visible edit and not a silently shorter skip set — the same argument
#: `COMMIT_TIER_STAGE_NAMES` makes for itself. Each entry is derived in
#: `DESIGN.md`'s row table and cited in the `CARD HW-7` region of ci_gate.py.
PINNED_REQUIREMENTS = {
    "ruff": ("ruff",),
    "unitree-assets": ("mujoco",),
    "hard-safety": ("mujoco",),
    "tier-coverage": ("pytest", "mujoco"),
    "model-off-non-inferiority": ("pytest",),
    "release-parity-integrity": ("pytest",),
    "owner-store-isolation": ("pytest",),
    "default-suite": ("pytest", "xdist", "mujoco"),
}


def test_the_requirement_table_is_what_this_card_measured() -> None:
    assert STAGE_REQUIREMENTS == PINNED_REQUIREMENTS, (
        "the aarch64 skip declaration moved. That is allowed, and it is a "
        "DELIBERATE edit: change this pin in the same commit, and say in the "
        "card why the new set is what a mujoco-less or pytest-less venv needs"
    )


def test_a_stage_that_collects_the_whole_tree_declares_mujoco_while_any_test_needs_it() -> None:
    """Row S2's guard, DERIVED rather than copied.

    `tier-coverage` runs three `--collect-only` passes over the entire tree and
    `default-suite` runs it; nine test modules `import mujoco` at module scope
    with no `importorskip`, so on a venv without mujoco those two rows are a
    hard ERROR and a wall of collection failures. As long as one such module
    exists, both rows must declare the requirement — and if somebody guards the
    last one, this test says so instead of quietly staying true."""

    unguarded = sorted(
        path.name
        for path in (REPO / "tests").glob("test_*.py")
        for line in path.read_text(encoding="utf-8", errors="replace").splitlines()
        if line.startswith(("import mujoco", "from mujoco"))
    )
    assert unguarded, (
        "no test module imports mujoco at module scope any more — re-derive "
        "STAGE_REQUIREMENTS for tier-coverage/default-suite instead of "
        "inheriting this card's answer"
    )
    for stage in ("tier-coverage", "default-suite"):
        assert "mujoco" in STAGE_REQUIREMENTS[stage], (
            f"{stage} collects {len(unguarded)} module(s) that import mujoco "
            f"unguarded ({unguarded[:3]}...) and must declare it, or a "
            f"mujoco-less host gets a hard ERROR instead of a typed SKIP"
        )


@pytest.mark.parametrize("stage", sorted(STAGE_REQUIREMENTS))
def test_each_skip_row_names_the_reason_and_a_command_that_un_skips_it(stage: str) -> None:
    """Row P6. A skip nobody can act on is a test that quietly stopped
    existing (GATE-0b's sentence, applied to a whole stage)."""

    caps = {name: dict(entry) for name, entry in host_capabilities().items()}
    for name in STAGE_REQUIREMENTS[stage]:
        caps[name]["present"] = False
    out = dict(hw7_apply_host_skips(_stub_stages(), tier="commit", caps=caps))
    result = out[stage]()
    assert result.status == "skip"
    assert result.hard is True, "a hard gate that did not run is still a hard gate"
    assert result.is_red is False, "a skip must not change the exit code"
    for name in STAGE_REQUIREMENTS[stage]:
        assert name in result.detail
    assert "un-skip:" in result.detail
    assert result.extra["hw7_missing"] == list(STAGE_REQUIREMENTS[stage])
    for line in result.detail.split("un-skip: ")[1:]:
        command = line.split(" | ")[0].strip()
        assert command.startswith(
            ("pip", "python", ".parcel/", "scripts/", "apt", "sudo apt", "x86_64:", "(")
        ), f"{stage}: un-skip clause is not a command: {command!r}"


# ---------------------------------------------------------------------------
# The transform (rows P7, P8)
# ---------------------------------------------------------------------------


def test_the_transform_is_the_identity_when_every_capability_is_present() -> None:
    """Row P7, and the reason `tests/test_ci_gate.py` (card XD-1's file, not
    edited by this card) still sees a clean tier of `pass` rows: on a
    provisioned host this transform returns the very same thunk objects."""

    caps = {name: dict(entry) for name, entry in host_capabilities().items()}
    for entry in caps.values():
        entry["present"] = True
    stages = _stub_stages()
    out = hw7_apply_host_skips(stages, tier="commit", caps=caps)
    assert tuple(name for name, _ in out) == tuple(name for name, _ in stages)
    assert all(a is b for (_, a), (_, b) in zip(out, stages))


def test_a_present_capability_never_shortens_the_row_set() -> None:
    caps = {name: dict(entry) for name, entry in host_capabilities().items()}
    caps["mujoco"]["present"] = False
    out = hw7_apply_host_skips(_stub_stages(), tier="commit", caps=caps)
    assert tuple(name for name, _ in out) == COMMIT_TIER_STAGE_NAMES
    skipped = {name for name, thunk in out if thunk().status == "skip"}
    assert skipped == {stage for stage, req in STAGE_REQUIREMENTS.items() if "mujoco" in req}


def test_the_transform_cannot_turn_a_red_into_a_green() -> None:
    """The failure mode a post-hoc rescue would have: "the suite failed, so
    call it a skip". This transform decides BEFORE the thunk runs, so a stage
    whose requirements are met is handed through and keeps its own verdict."""

    caps = {name: dict(entry) for name, entry in host_capabilities().items()}
    for entry in caps.values():
        entry["present"] = True
    red = (("ruff", lambda: GateResult("ruff", "commit", True, "fail", "seeded red")),)
    out = hw7_apply_host_skips(red, tier="commit", caps=caps)
    assert out[0][1]().status == "fail"


def test_the_host_row_reports_and_never_gates() -> None:
    result = evaluate_host_capabilities(tier="commit")
    assert result.name == "host"
    assert result.hard is False
    assert result.status == "pass"
    assert result.gating_red is False
    assert "capabilities absent:" in result.detail
    assert "rows this host will SKIP:" in result.detail
    assert set(result.extra["capabilities"]) == EXPECTED_FACTS | EXPECTED_CAPABILITIES


def test_the_two_report_only_rows_sit_together_at_the_bottom() -> None:
    """`host` was going to be FIRST — a legend belongs above what it explains.
    It is last instead, and the reason is a contract in a file this card must
    not edit: `tests/test_ci_gate.py` seeds the first evaluator to raise and
    asserts `payload["gates"][0]["status"] == "error"`, so position 0 belongs
    to the first HARD gate. Both report rows now sit directly above RESULT,
    which is where a reader looks for "which box was this, and what did it not
    run". Cheap to lose in a merge, so it is pinned."""

    assert COMMIT_TIER_STAGE_NAMES[-1] == "host"
    assert COMMIT_TIER_STAGE_NAMES[-2] == "skip-list"
    assert COMMIT_TIER_STAGE_NAMES[0] == "ruff"


# ---------------------------------------------------------------------------
# CORRECTION PASS — the verifier's F1-F4 (2026-08-23)
# ---------------------------------------------------------------------------


def _row_set(statuses: dict[str, str]) -> list[GateResult]:
    """The commit tier's real row shape: 10 hard + the two report rows.

    `stopping-envelope` is card HW-6's SOFT row and `skip-list`/`host` are
    report-only, so the hard count this file asserts on is the real one.
    """

    soft = {"stopping-envelope", "skip-list", "host"}
    return [
        GateResult(name, "commit", name not in soft, statuses.get(name, "pass"), "detail")
        for name in COMMIT_TIER_STAGE_NAMES
    ]


def test_the_result_line_is_unchanged_when_nothing_skipped() -> None:
    """F1, branch one. The sentence this repo has always printed, byte for
    byte, on every host where every hard gate ran."""

    result = summarize(_row_set({}), "commit", 1.0).splitlines()[-2]
    assert result == "RESULT: PASS — every hard gate green."


def test_the_result_line_says_so_when_a_hard_gate_skipped() -> None:
    """F1, branch two, and the reason this card touched shared reporting code.

    On a venv without mujoco, four HARD rows print `[  skip]` and nothing is
    gating-red — so the old summary printed "every hard gate green" directly
    underneath them. The rows and the JSON were truthful; the one line an
    operator reads was not."""

    skipped = ["unitree-assets", "hard-safety", "tier-coverage", "default-suite"]
    result = summarize(_row_set(dict.fromkeys(skipped, "skip")), "commit", 1.0).splitlines()[-2]
    assert "every hard gate green" not in result
    assert result.startswith("RESULT: PASS — ")
    assert "SKIPPED on this host:" in result
    for name in skipped:
        assert name in result
    # The count is of gates that actually ran green, not of all hard rows.
    assert result == (
        "RESULT: PASS — 6 hard gate(s) green, 4 SKIPPED on this host: "
        "unitree-assets, hard-safety, tier-coverage, default-suite"
    )


def test_a_red_gate_still_reads_as_fail_whatever_else_skipped() -> None:
    """The FAIL branch is deliberately untouched: "N hard gate(s) red: …" is
    true whether or not other rows skipped, and the exit code is unchanged."""

    rows = _row_set({"ruff": "fail", "tier-coverage": "skip"})
    result = summarize(rows, "commit", 1.0).splitlines()[-2]
    assert result == "RESULT: FAIL — 1 hard gate(s) red: ruff"
    assert sum(1 for r in rows if r.gating_red) == 1


@pytest.mark.parametrize("raised", [RuntimeError, KeyError, ValueError, OSError])
def test_no_exception_from_the_probe_can_kill_the_runner(monkeypatch, raised) -> None:
    """F2. The transform runs BEFORE `run_stage`'s containment, so anything it
    lets escape takes the whole tier with it — no rows, no JSON, card GATE-0's
    original disease. The first version named four exception classes and the
    verifier walked a `RuntimeError` straight through it."""

    import scripts.ci_gate as gate

    def explode(**kwargs):
        raise raised("seeded: the probe is broken")

    monkeypatch.setattr(gate, "host_capabilities", explode)
    stages = _stub_stages()
    out = gate.hw7_apply_host_skips(stages, tier="commit")
    assert tuple(name for name, _ in out) == tuple(name for name, _ in stages)
    assert all(a is b for (_, a), (_, b) in zip(out, stages)), "a broken probe declares NOTHING"
    row = gate.evaluate_host_capabilities(tier="commit")
    assert row.status == "error"
    assert row.hard is False
    assert raised.__name__ in row.detail, "the row must say WHAT failed, not only that it did"


def test_a_hostile_meta_path_finder_is_absence_not_a_crash() -> None:
    """F2's exact reproduction: a finder that RAISES for one module. It is not
    an error — it is the strongest possible statement that the module cannot be
    imported here — so the four rows skip and the evidence says `raised`."""

    import importlib.abc

    class Hostile(importlib.abc.MetaPathFinder):
        def find_spec(self, fullname, path=None, target=None):
            # Returns nothing for every other name, which is how a meta-path
            # finder says "not mine" — the explicit `return None` is left out
            # because this repo's ruff selection reports it (RET501/PLR1711).
            if fullname.split(".")[0] == "mujoco":
                raise RuntimeError("seeded: this finder refuses mujoco")

    sys.meta_path.insert(0, Hostile())
    # find_spec never consults meta_path for a module already in sys.modules —
    # it returns sys.modules["mujoco"].__spec__ directly — and under
    # `--dist loadfile` this file usually shares a worker with a test that
    # imported mujoco. The finder can only refuse an import that happens.
    saved_mujoco = {
        name: sys.modules.pop(name)
        for name in list(sys.modules)
        if name.split(".")[0] == "mujoco"
    }
    try:
        caps = host_capabilities()
        assert caps["mujoco"]["present"] is False
        assert "raised RuntimeError" in str(caps["mujoco"]["evidence"])
        out = dict(hw7_apply_host_skips(_stub_stages(), tier="commit", caps=caps))
        assert out["unitree-assets"]().status == "skip"
    finally:
        sys.meta_path.pop(0)
        sys.modules.update(saved_mujoco)


def test_every_capability_carries_the_observation_not_just_the_verdict() -> None:
    """F3. `evidence` is what the probe SAW; `detail` is what the capability is
    FOR. A row that only carries the second cannot be audited from a JSON."""

    for name, entry in host_capabilities().items():
        if entry["kind"] != "capability":
            continue
        evidence = str(entry["evidence"])
        assert evidence, f"{name} reports no evidence"
        assert str(entry["probe"]) in {"importlib.util.find_spec", "path stat"}
        if entry["probe"] == "importlib.util.find_spec":
            assert evidence.startswith(f"importlib.util.find_spec({entry['module']!r})")
            assert ("-> None" in evidence) or ("-> spec at " in evidence) or ("raised " in evidence)


def test_a_skip_row_prints_the_evidence_and_the_interpreter() -> None:
    """F3 where it matters: the row an operator reads on the dog. Four venvs
    live on the Orin and only the interpreter path distinguishes "ran in the
    perception venv, as expected" from "ran in the product venv, a defect"."""

    caps = {name: dict(entry) for name, entry in host_capabilities().items()}
    caps["mujoco"]["present"] = False
    caps["mujoco"]["evidence"] = "importlib.util.find_spec('mujoco') -> None"
    row = dict(hw7_apply_host_skips(_stub_stages(), tier="commit", caps=caps))["unitree-assets"]()
    assert "evidence: importlib.util.find_spec('mujoco') -> None" in row.detail
    assert sys.executable in row.detail, "the skip must name the interpreter it asked"
    assert row.extra["hw7_evidence"]["mujoco"] == "importlib.util.find_spec('mujoco') -> None"
    assert sys.executable in row.extra["hw7_interpreter"]


def test_the_probe_agrees_with_a_real_import_on_this_host() -> None:
    """F4 — the probe pinned to an INDEPENDENT truth.

    Every other test in this file takes `host_capabilities()` at its word, so a
    probe that simply LIED about mujoco passed all of them; only card XD-1's
    file caught it, and only on a host where everything is present. This is the
    one test that asks a second question: does the module actually import?

    `find_spec` and `import_module` can legitimately disagree in one direction
    — a module whose spec exists but whose import raises — so the assertion is
    written as an equality with the failure message naming both sides, and any
    real disagreement on this host is a defect worth reading, not a flake."""

    import importlib

    caps = host_capabilities()
    checked = 0
    for name, entry in caps.items():
        if entry.get("probe") != "importlib.util.find_spec":
            continue
        module = str(entry["module"])
        try:
            importlib.import_module(module)
            importable = True
        except ImportError:
            importable = False
        checked += 1
        assert entry["present"] is importable, (
            f"the probe says {name} present={entry['present']} with evidence "
            f"{entry['evidence']!r}, but `import {module}` "
            f"{'succeeds' if importable else 'fails'} in {sys.executable}"
        )
    assert checked >= 5, f"only {checked} module capabilities were pinned to a real import"


# ---------------------------------------------------------------------------
# The shell scripts (rows X1-X7)
# ---------------------------------------------------------------------------

ENV_AUDIO = REPO / "scripts" / "env-audio.sh"
INSTALL_SPEECH = REPO / "scripts" / "install_speech_services.sh"
INSTALL_JETSON = REPO / "scripts" / "install_perception_jetson.sh"

#: A dry run must not be able to write anywhere, even if it is broken: the venv
#: it names is redirected out of $HOME for every subprocess this file starts.
_JETSON_ENV = {
    "PATH": "/usr/bin:/bin",
    "HOME": "/nonexistent-hw7",
    "PARCEL_PERCEPTION_VENV": "/nonexistent-hw7/venv",
}

#: Recorded from `git show e15e466:scripts/env-audio.sh` while this card was
#: open. The x86_64 branch must keep every one of them.
X86_LIBDIR_SUFFIX = "usr/lib/x86_64-linux-gnu"
X86_DEB_SHAS = (
    "libportaudio2:2c6290fe3730f63569a0f3ee4b24ffcaede479611af608f5f9f643336e0df16d",
    "libjack-jackd2-0:129857d470a11901a74ad51eb249b5a7c4f46ff22981d9cb4e2996c6bdb8fe99",
)
#: Measured 2026-08-23 from ports.ubuntu.com (jammy = JetPack 6's Ubuntu); the
#: .debs were fetched and hashed on this desktop, nothing aarch64 executed.
ARM64_LIBDIR_SUFFIX = "usr/lib/aarch64-linux-gnu"
ARM64_DEB_SHAS = (
    "libportaudio2:c01c97bab1b95dd60e059e7d441a4ee42155c6659716f16fb84d546ac6b943a8",
    "libjack-jackd2-0:a52e0d8abb1186dfc64af8ef937a97fc013fbbfdd195700a93fb07207e77b0f5",
)


def _dry_run(script: Path, arch: str, arch_env: str) -> str:
    proc = subprocess.run(
        ["bash", str(script), "--dry-run"],
        cwd=str(REPO),
        env={"PATH": "/usr/bin:/bin", "HOME": "/nonexistent-hw7", arch_env: arch},
        capture_output=True,
        text=True,
        timeout=120,
        check=False,
    )
    assert proc.returncode == 0, f"{script.name} --dry-run rc={proc.returncode}: {proc.stderr}"
    return proc.stdout


@pytest.mark.parametrize("script", [ENV_AUDIO, INSTALL_SPEECH, INSTALL_JETSON])
def test_the_shell_scripts_parse(script: Path) -> None:
    proc = subprocess.run(["bash", "-n", str(script)], capture_output=True, text=True, check=False)
    assert proc.returncode == 0, proc.stderr


def test_env_audio_keeps_the_x86_64_branch_it_had(tmp_path: Path) -> None:
    """Row X1 as a durable pin. The functional half of this row (running HEAD's
    copy and this one side by side against a pre-populated prefix and diffing
    their output) is recorded in HW7_STATUS.md; what lives here is the pin that
    survives the commit."""

    out = _dry_run(ENV_AUDIO, "x86_64", "PARCEL_AUDIO_ARCH")
    assert X86_LIBDIR_SUFFIX in out
    assert ARM64_LIBDIR_SUFFIX not in out
    for sha in X86_DEB_SHAS:
        assert sha in out


def test_env_audio_has_an_aarch64_branch_with_its_own_measured_snapshot() -> None:
    out = _dry_run(ENV_AUDIO, "aarch64", "PARCEL_AUDIO_ARCH")
    assert ARM64_LIBDIR_SUFFIX in out
    assert X86_LIBDIR_SUFFIX not in out
    for sha in ARM64_DEB_SHAS:
        assert sha in out
    assert "DRY RUN" in out


def test_env_audio_does_not_pretend_to_have_pinned_an_unknown_architecture() -> None:
    """Prototype rule: ask over refuse. An unpinned port still gets a libdir and
    a working script; what it does not get is a checksum comparison that was
    never made."""

    out = _dry_run(ENV_AUDIO, "riscv64", "PARCEL_AUDIO_ARCH")
    assert "usr/lib/riscv64-linux-gnu" in out
    assert "NONE for riscv64" in out


def test_install_speech_services_selects_the_piper_asset_by_architecture() -> None:
    x86 = _dry_run(INSTALL_SPEECH, "x86_64", "PARCEL_TARGET_ARCH")
    assert "piper_linux_x86_64.tar.gz" in x86
    arm = _dry_run(INSTALL_SPEECH, "aarch64", "PARCEL_TARGET_ARCH")
    assert "piper_linux_aarch64.tar.gz" in arm
    # Measured 2026-08-23 against the pinned release's asset list: the aarch64
    # asset exists AT THE TAG THIS REPO ALREADY PINS, so nothing else moves.
    assert "2023.11.14-2" in arm


def test_install_speech_services_dry_run_writes_nothing() -> None:
    before = sorted(p.name for p in (REPO / "third_party").glob("*"))
    _dry_run(INSTALL_SPEECH, "aarch64", "PARCEL_TARGET_ARCH")
    assert sorted(p.name for p in (REPO / "third_party").glob("*")) == before


def test_the_jetson_installer_refuses_on_this_x86_64_host(tmp_path: Path) -> None:
    """Row X5. It installs an aarch64 wheel into a venv for the Orin; on the
    desktop the honest answer is a refusal that names the desktop's own path,
    not a best-effort install.

    PARCEL_PERCEPTION_VENV is redirected into tmp_path deliberately. When card
    HW-7 seeded this refusal away to prove the test reddens, the seeded script
    went on and created `$HOME/parcel-perception-venv` — a seed that has to be
    cleaned up by hand is a seed nobody re-runs. The redirection makes the
    proof cost nothing."""

    proc = subprocess.run(
        ["bash", str(INSTALL_JETSON), "--jetpack", "6.1"],
        cwd=str(REPO),
        env={
            "PATH": "/usr/bin:/bin",
            "HOME": str(tmp_path),
            "PARCEL_PERCEPTION_VENV": str(tmp_path / "venv"),
        },
        capture_output=True,
        text=True,
        timeout=120,
        check=False,
    )
    assert proc.returncode == 2, proc.stdout + proc.stderr
    assert "REFUSED on x86_64" in proc.stderr
    assert "[perception]" in proc.stderr, "the refusal must name what the desktop should run"


def test_the_jetson_installer_records_its_wheel_provenance_and_says_what_is_unconfirmed() -> None:
    """Row X6. The index is measured (both jp6 paths answered 200 on
    2026-08-23 and serve the SAME wheel); WHICH one the dock needs is box-day
    read B9 and the script refuses to guess it."""

    text = INSTALL_JETSON.read_text(encoding="utf-8")
    assert "onnxruntime_gpu-1.24.0-cp310-cp310-linux_aarch64.whl" in text
    assert "d980b934b9a29c1a9d6f39751edd7662b69fadd75556a10ff363773a58ce0950" in text
    assert "https://pypi.jetson-ai-lab.io/jp6/cu126" in text
    assert "https://pypi.jetson-ai-lab.io/jp6/cu128" in text
    assert "UNCONFIRMED" in text
    out = subprocess.run(
        ["bash", str(INSTALL_JETSON), "--dry-run", "--jetpack", "6.1"],
        cwd=str(REPO),
        env=_JETSON_ENV,
        capture_output=True,
        text=True,
        timeout=120,
        check=False,
    )
    assert out.returncode == 0, out.stderr
    assert "cu126" in out.stdout
    assert "UNCONFIRMED" in out.stdout


def test_the_jetson_installer_will_not_guess_an_index() -> None:
    """The refusal that matters most: a wheel built against the wrong CUDA
    loads, advertises CUDAExecutionProvider from a stub and silently builds a
    CPU session (PG-1 §6). Guessing the index is how you get there."""

    text = INSTALL_JETSON.read_text(encoding="utf-8")
    assert "will NOT guess" in text
    out = subprocess.run(
        ["bash", str(INSTALL_JETSON), "--dry-run"],
        cwd=str(REPO),
        env=_JETSON_ENV,
        capture_output=True,
        text=True,
        timeout=120,
        check=False,
    )
    assert "<unselected: pass --jetpack or --index-url>" in out.stdout


# ---------------------------------------------------------------------------
# CI (row Y1)
# ---------------------------------------------------------------------------


def test_the_workflow_parses_and_carries_one_fenced_aarch64_nightly_job() -> None:
    yaml = pytest.importorskip("yaml")
    path = REPO / ".github" / "workflows" / "ci.yml"
    parsed = yaml.safe_load(path.read_text(encoding="utf-8"))
    job = parsed["jobs"]["aarch64-nightly"]
    assert "schedule" in job["if"], "the emulated job must never run on a push"
    assert job["continue-on-error"] is True, (
        "this job has never produced a recorded run; until it does it reports "
        "rather than gates, and the line comes off in the commit that records one"
    )
    text = path.read_text(encoding="utf-8")
    assert "# ---- CARD HW-7 gate-on-aarch64 (scrum/20260822/task_42) ----" in text
    assert "# ---- END CARD HW-7 gate-on-aarch64 ----" in text


def test_this_card_did_not_edit_another_cards_region() -> None:
    """Ownership, executable. Card HW-7 adds fenced regions to `ci_gate.py` and
    edits inside none of card XD-1's, GATE-0b's or HW-6's."""

    text = (REPO / "scripts" / "ci_gate.py").read_text(encoding="utf-8")
    for marker in ("CARD HW-7", "CARD XD-1", "CARD GATE-0b", "CARD HW-6"):
        closes = text.count(f"END {marker}")
        # Every closing marker contains its own opening text, so the opens are
        # the difference. Unbalanced fences mean somebody's region swallowed
        # somebody else's code.
        opens = text.count(marker) - closes
        assert opens == closes > 0, f"{marker}: {opens} open, {closes} close"
    assert "CARD HW-7" not in (REPO / "tests" / "test_ci_gate.py").read_text(encoding="utf-8")


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-q", *sys.argv[1:]]))
