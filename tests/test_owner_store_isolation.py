"""Card R27 — no test, harness or in-process runtime can reach the owner's store.

THE PROPERTY, NOT THE INSTANCE
==============================

Four consecutive card-chains wrote 256 synthetic rows into the owner's real
``parcel_memory.sqlite3`` and three status docs asserted, in good faith, that
they had not. Every one of those executors would have passed a test that
checked "does *this* code path isolate itself?", because none of them knew
which code path was the offender.

So the assertions here are about *reachability*, not about any particular
caller:

* :func:`test_no_shipped_config_can_be_launched_onto_the_owner_store` walks
  **every** ``robot.yaml`` in the tree, so a fourth config copy inherits the
  guard instead of re-opening the hole.
* :func:`test_a_repo_root_in_process_runtime_cannot_reach_the_owner_store`
  spawns a real subprocess doing the exact thing four executors did — a
  default-config runtime, from the repo root, no environment — and asserts it
  dies. It is the card's demonstration, kept executable.
* :func:`test_the_commit_suite_opens_no_connection_to_the_owner_store` runs a
  ``sqlite3.connect`` interceptor over a slice of the suite. That is how the
  original offender was found, and it is here so the *next* one is found by CI
  rather than by an auditor reading a status doc.
* :func:`test_a_test_process_cannot_declare_itself_the_owner` pins the one
  rule that makes the rest a property: the declaration is *ignored* under
  pytest, so no future fixture can opt back in.
"""

from __future__ import annotations

import ast
import os
import re
import sqlite3
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

from parcel_robot import memory_path
from parcel_robot.conversation_store import SqliteConversationStore
from parcel_robot.memory import PROVENANCE_COLUMNS, ConversationMemory
from parcel_robot.memory_path import (
    ENV_PATH,
    ENV_PURPOSE,
    PURPOSE_OWNER,
    PURPOSE_TOOL,
    WRITER_OWNER_STACK,
    WRITER_TEST,
    WRITER_TOOL,
    WRITER_UNKNOWN,
    MemoryPathRefused,
    declared_purpose,
    owner_store_paths,
    resolve_memory_path,
    writer_class,
)

REPO = Path(__file__).resolve().parents[1]
OWNER_STORE = REPO / "parcel_memory.sqlite3"

#: Every shipped config that names a conversation store. Discovered rather than
#: listed: a new copy of ``robot.yaml`` must inherit this test, and a list would
#: quietly not cover it.
SHIPPED_CONFIGS = tuple(
    sorted(
        path
        for path in REPO.glob("**/robot*.yaml")
        if ".parcel" not in path.parts
        and "third_party" not in path.parts
        and ".cache" not in path.parts
        and "scratchpad" not in path.parts
    )
)


def _clean_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv(ENV_PATH, raising=False)
    monkeypatch.delenv(ENV_PURPOSE, raising=False)


# ---------------------------------------------------------------------------
# 1. The owner's file is unreachable for writing
# ---------------------------------------------------------------------------


def test_the_owner_store_is_identified_at_every_parcel_root() -> None:
    assert OWNER_STORE.resolve() in owner_store_paths()


def test_conversation_memory_refuses_the_owner_store_by_absolute_path(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Naming the file outright is refused too — the guard is not path-shaped."""

    _clean_env(monkeypatch)
    with pytest.raises(MemoryPathRefused) as caught:
        ConversationMemory(OWNER_STORE)
    assert "OWNER'S conversation memory" in str(caught.value)
    assert ENV_PATH in str(caught.value)


def test_conversation_memory_refuses_the_owner_store_by_relative_path(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    """And from a DIFFERENT cwd, because the anchor is the repo root now."""

    _clean_env(monkeypatch)
    monkeypatch.chdir(tmp_path)
    with pytest.raises(MemoryPathRefused):
        ConversationMemory("parcel_memory.sqlite3")


def test_no_shipped_config_can_be_launched_onto_the_owner_store(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """THE PROPERTY. Every robot.yaml in the tree, not just the three today."""

    _clean_env(monkeypatch)
    assert SHIPPED_CONFIGS, "no robot*.yaml found — this test would pass vacuously"
    checked = 0
    for config in SHIPPED_CONFIGS:
        data = yaml.safe_load(config.read_text(encoding="utf-8")) or {}
        path = (data.get("memory") or {}).get("path")
        if not path or memory_path.is_in_memory(path):
            continue
        checked += 1
        with pytest.raises(MemoryPathRefused):
            resolve_memory_path(path)
    assert checked >= 3, f"expected the shipped robot.yaml copies to be covered, got {checked}"


def test_a_repo_root_in_process_runtime_cannot_reach_the_owner_store() -> None:
    """The card's demonstration, as a subprocess: what four executors actually did.

    A subprocess and not an in-process call, because the thing being proved is
    about a *process* — its CWD, its environment, and the absence of pytest.
    Run in-process this would be proving the pytest rule a second time.
    """

    env = {k: v for k, v in os.environ.items() if k not in {ENV_PATH, ENV_PURPOSE}}
    env.pop("PYTEST_CURRENT_TEST", None)
    proc = subprocess.run(
        [
            sys.executable,
            "-c",
            (
                "from parcel_robot import web_panel\n"
                "web_panel.build_runtime("
                "'configs/robot.yaml', '/tmp/r27_guard.sock', use_llm=False)\n"
                "print('REACHED')\n"
            ),
        ],
        cwd=str(REPO),
        env=env,
        capture_output=True,
        text=True,
        check=False,
        timeout=300,
    )
    assert proc.returncode != 0, f"a default runtime reached the owner's store:\n{proc.stdout}"
    assert "REACHED" not in proc.stdout
    assert "MemoryPathRefused" in proc.stderr
    assert str(OWNER_STORE) in proc.stderr


def test_the_documented_escape_hatch_actually_works(tmp_path: Path) -> None:
    """A refusal with no way out is a broken product, so prove the way out."""

    env = dict(os.environ)
    env[ENV_PATH] = str(tmp_path / "scratch.sqlite3")
    env.pop(ENV_PURPOSE, None)
    env.pop("PYTEST_CURRENT_TEST", None)
    proc = subprocess.run(
        [
            sys.executable,
            "-c",
            (
                "from parcel_robot import web_panel\n"
                "rt = web_panel.build_runtime("
                "'configs/robot.yaml', '/tmp/r27_ok.sock', use_llm=False)\n"
                "print('STORE', rt.agent.memory.store.path)\n"
            ),
        ],
        cwd=str(REPO),
        env=env,
        capture_output=True,
        text=True,
        check=False,
        timeout=300,
    )
    assert proc.returncode == 0, proc.stderr[-3000:]
    assert f"STORE {tmp_path / 'scratch.sqlite3'}" in proc.stdout


# ---------------------------------------------------------------------------
# 2. A test can never become the owner
# ---------------------------------------------------------------------------


def test_a_test_process_cannot_declare_itself_the_owner(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The rule that turns every other assertion here into a property.

    If a fixture could export ``PARCEL_MEMORY_PURPOSE=owner`` and be believed,
    the guard would be a convention again — one ``monkeypatch.setenv`` away from
    the state this card is cleaning up after.
    """

    monkeypatch.delenv(ENV_PATH, raising=False)
    monkeypatch.setenv(ENV_PURPOSE, PURPOSE_OWNER)
    assert declared_purpose() != PURPOSE_OWNER
    with pytest.raises(MemoryPathRefused):
        ConversationMemory(OWNER_STORE)
    # …nor through the explicit constructor argument.
    with pytest.raises(MemoryPathRefused):
        ConversationMemory(OWNER_STORE, purpose=PURPOSE_OWNER)


def test_the_refusal_is_not_swallowed_by_a_never_kill_a_turn_guard() -> None:
    """``MemoryPathRefused`` must not be a ValueError.

    ``lane._write_ledger`` catches ``(RuntimeError, TypeError, ValueError)``
    around ledger writes and ``ConversationStoreError`` subclasses ``ValueError``
    on purpose. A refusal that landed in that family would be logged and
    swallowed, and the stack would come up with no memory and no complaint.
    """

    assert issubclass(MemoryPathRefused, RuntimeError)
    assert not issubclass(MemoryPathRefused, ValueError)


def test_the_owner_launchers_declare_the_owner_purpose() -> None:
    """The other half of a fail-closed guard: the owner's stack must still work.

    ``PARCEL_MEMORY_PURPOSE=owner`` lives in the two documented launchers and
    nowhere else. If a future edit removes it the guard does not get weaker — it
    gets *worse*, because the owner's own stack starts refusing its own memory
    on launch. This is the test that catches that, and it is why the export uses
    ``${PARCEL_MEMORY_PURPOSE:-owner}``: an executor's explicit override still
    wins over the launcher.
    """

    for name in ("launch_stack.sh", "launch_sim.sh"):
        text = (REPO / "scripts" / name).read_text(encoding="utf-8")
        assert f'export {ENV_PURPOSE}="${{{ENV_PURPOSE}:-{PURPOSE_OWNER}}}"' in text, (
            f"scripts/{name} no longer declares {ENV_PURPOSE}={PURPOSE_OWNER}; "
            "the owner's stack will refuse its own conversation store on launch"
        )


def test_the_library_never_declares_itself_the_owner() -> None:
    """The asymmetry the whole guard rests on.

    If any module under ``src/`` set ``PARCEL_MEMORY_PURPOSE``, then importing
    the runtime would confer owner rights — and an in-process runtime started
    from the repo root would be back to writing into the owner's file, which is
    exactly the defect. The declaration must stay outside the importable code.
    """

    offenders = [
        path.relative_to(REPO).as_posix()
        for path in (REPO / "src").rglob("*.py")
        if "__pycache__" not in path.parts
        and path.name != "memory_path.py"
        and re.search(
            rf"(environ\[[\"']{ENV_PURPOSE}|setenv\([\"']{ENV_PURPOSE}|putenv\([\"']{ENV_PURPOSE})",
            path.read_text(encoding="utf-8", errors="ignore"),
        )
    ]
    assert not offenders, f"library code must not confer owner rights: {offenders}"


# ---------------------------------------------------------------------------
# 3. Relative paths and the override
# ---------------------------------------------------------------------------


def test_a_relative_path_is_refused_even_when_it_is_harmless(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _clean_env(monkeypatch)
    with pytest.raises(MemoryPathRefused) as caught:
        ConversationMemory("some/other/ledger.sqlite3")
    assert "RELATIVE" in str(caught.value)


def test_a_relative_override_is_refused(monkeypatch: pytest.MonkeyPatch) -> None:
    """Otherwise the override would reintroduce the exact bug it exists to fix.

    The second half is the half that actually tests the override rule, and it
    was added because a seed proved the first half does not. Under a ``test``
    purpose a relative override is refused by the GENERAL relative-path rule, so
    deleting the override rule entirely left this test green (seed S8, first
    attempt — R27_STATUS §7.1). Only under an ``owner`` purpose, where the
    general rule stands aside, is the override rule the sole thing standing
    between the owner's stack and a CWD-dependent store.
    """

    monkeypatch.setenv(ENV_PATH, "scratch.sqlite3")
    with pytest.raises(MemoryPathRefused) as caught:
        ConversationMemory(":memory:")
    assert ENV_PATH in str(caught.value)

    # The owner's own stack, whose relative CONFIG path is legitimate, must
    # still be refused a relative OVERRIDE.
    monkeypatch.setattr(memory_path, "_pytest_is_loaded", lambda: False)
    owner_env = {ENV_PURPOSE: PURPOSE_OWNER, ENV_PATH: "scratch.sqlite3"}
    with pytest.raises(MemoryPathRefused) as owner_caught:
        resolve_memory_path("parcel_memory.sqlite3", env=owner_env)
    assert ENV_PATH in str(owner_caught.value)
    # …and the same owner purpose with no override is exactly what still works,
    # so the assertion above is about the override and not about the purpose.
    assert resolve_memory_path(
        "parcel_memory.sqlite3", env={ENV_PURPOSE: PURPOSE_OWNER}
    ).is_owner_store


def test_the_override_beats_the_config(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv(ENV_PATH, str(tmp_path / "wins.sqlite3"))
    memory = ConversationMemory("parcel_memory.sqlite3")
    assert memory.store.path == str(tmp_path / "wins.sqlite3")
    assert memory.store.is_owner_store is False


def test_in_memory_is_always_allowed(monkeypatch: pytest.MonkeyPatch) -> None:
    _clean_env(monkeypatch)
    assert ConversationMemory(":memory:").store.path == ":memory:"


def test_reads_of_the_owner_store_are_still_permitted(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """R18's recall proof and the quarantine dry run both depend on this.

    ``mode=ro`` is the one configuration in which the defect cannot occur, so
    refusing it would cost real evidence and buy nothing.
    """

    _clean_env(monkeypatch)
    if not OWNER_STORE.exists():
        pytest.skip("no owner store on this machine")
    memory = ConversationMemory(OWNER_STORE, read_only=True)
    assert memory.store.is_owner_store is True
    assert memory.connection.execute("SELECT COUNT(*) FROM messages").fetchone()[0] >= 0
    with pytest.raises(sqlite3.OperationalError):
        memory.connection.execute("INSERT INTO messages(role, content) VALUES ('user', 'x')")
    memory.connection.close()


def test_the_conversation_store_obeys_the_same_rules(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """The designated replacement ledger must not inherit the original defect."""

    _clean_env(monkeypatch)
    with pytest.raises(MemoryPathRefused):
        SqliteConversationStore("turns.sqlite3")
    with pytest.raises(MemoryPathRefused):
        SqliteConversationStore(OWNER_STORE)
    store = SqliteConversationStore(tmp_path / "turns.sqlite3")
    assert store.store.is_owner_store is False
    store.close()


# ---------------------------------------------------------------------------
# 4. Per-row provenance (card work item 2)
# ---------------------------------------------------------------------------


def test_every_new_row_records_which_process_class_wrote_it(tmp_path: Path) -> None:
    """Pollution becomes detectable in the data instead of inferred from NULLs."""

    memory = ConversationMemory(tmp_path / "prov.sqlite3")
    memory.add("user", "a legacy-path turn")
    memory.write_realtime_turn(
        session_id="s1", speaker="owner", text="a hosted turn", origin="realtime"
    )
    rows = memory.connection.execute("SELECT content, writer FROM messages ORDER BY id").fetchall()
    assert rows == [("a legacy-path turn", WRITER_TEST), ("a hosted turn", WRITER_TEST)]


def test_the_provenance_column_exists_and_is_migrated_additively(tmp_path: Path) -> None:
    """A pre-R27 database must gain the column without losing a row."""

    path = tmp_path / "legacy.sqlite3"
    legacy = sqlite3.connect(path)
    legacy.execute(
        "CREATE TABLE messages (id INTEGER PRIMARY KEY, role TEXT NOT NULL, "
        "content TEXT NOT NULL, created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP)"
    )
    legacy.execute("INSERT INTO messages(role, content) VALUES ('user', 'older turn')")
    legacy.commit()
    legacy.close()

    memory = ConversationMemory(path)
    columns = {str(row[1]) for row in memory.connection.execute("PRAGMA table_info(messages)")}
    assert {name for name, _type in PROVENANCE_COLUMNS} <= columns
    # The pre-existing row keeps an honest NULL rather than a guessed value.
    assert memory.connection.execute("SELECT writer FROM messages").fetchone() == (None,)
    assert memory.recent(1) == [{"role": "user", "content": "older turn"}]


def test_the_writer_label_does_not_call_an_undeclared_process_a_test(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The provenance column must not contain a small convenient lie.

    ``_pytest_is_loaded`` is neutralised so the ENVIRONMENT half of the mapping
    is what gets asserted. Left alone, every case below would answer ``test``
    because pytest is in ``sys.modules``, and the mapping this test exists to
    pin would go unexercised — a green test proving only that it is a test.
    """

    monkeypatch.setattr(memory_path, "_pytest_is_loaded", lambda: False)
    assert writer_class({}) == WRITER_UNKNOWN
    assert writer_class({ENV_PURPOSE: PURPOSE_OWNER}) == WRITER_OWNER_STACK
    assert writer_class({ENV_PURPOSE: PURPOSE_TOOL}) == WRITER_TOOL
    assert writer_class({ENV_PURPOSE: "nonsense"}) == WRITER_UNKNOWN
    # …and the per-test variable alone is still enough, which is what covers
    # collection-time construction where PYTEST_CURRENT_TEST is absent.
    assert writer_class({"PYTEST_CURRENT_TEST": "x"}) == WRITER_TEST


# ---------------------------------------------------------------------------
# 5. Nothing in the tree reaches for the owner's file by name
# ---------------------------------------------------------------------------

#: Files allowed to name the store: the guard, its test, the tool that cleans up
#: after the incident, and the configs the guard protects.
_NAME_ALLOWLIST = {
    # The resolver is the one module that must know the name, because knowing it
    # is its job (`OWNER_STORE_NAME`).
    "src/parcel_robot/memory_path.py",
    "tests/test_owner_store_isolation.py",
    "tools/quarantine_synthetic_memory.py",
}


def _code_string_literals(tree: ast.AST) -> list[str]:
    """Every string literal that is CODE, with docstrings excluded.

    The distinction is the whole test. ``tests/test_realtime_lane.py`` and
    ``tests/test_fail_closed_limits.py`` both *talk about* the owner's store in
    a docstring — correctly, because both are about it — while neither names it
    in an expression any more. A grep cannot tell those apart, so this walks the
    AST and drops the docstring node of every module, class and function.
    """

    docstrings: set[int] = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
            body = getattr(node, "body", [])
            if (
                body
                and isinstance(body[0], ast.Expr)
                and isinstance(body[0].value, ast.Constant)
                and isinstance(body[0].value.value, str)
            ):
                docstrings.add(id(body[0].value))
    return [
        node.value
        for node in ast.walk(tree)
        if isinstance(node, ast.Constant)
        and isinstance(node.value, str)
        and id(node) not in docstrings
    ]


def test_no_harness_names_the_owner_store_outside_the_allowlist() -> None:
    """A new script that hardcodes the filename is the next pollution vector."""

    offenders: list[str] = []
    for folder in ("src", "tests", "scripts", "tools", "evals"):
        for path in (REPO / folder).rglob("*.py"):
            if "__pycache__" in path.parts:
                continue
            relative = path.relative_to(REPO).as_posix()
            if relative in _NAME_ALLOWLIST:
                continue
            source = path.read_text(encoding="utf-8", errors="ignore")
            if "parcel_memory.sqlite3" not in source:
                continue
            try:
                tree = ast.parse(source)
            except SyntaxError:  # pragma: no cover - a broken file is not our finding
                continue
            if any("parcel_memory.sqlite3" in text for text in _code_string_literals(tree)):
                offenders.append(relative)
    assert not offenders, (
        "these name the owner's store in code; route them through "
        f"{ENV_PATH} or ConversationMemory(..., read_only=True): {offenders}"
    )


def test_the_commit_suite_opens_no_connection_to_the_owner_store(tmp_path: Path) -> None:
    """The sweep that FOUND the offender, kept as a regression test.

    Runs a representative slice of the suite — the modules that build a runtime
    or a store — under a ``sqlite3.connect`` interceptor that records and
    refuses any attempt on the owner's file. The full 7,686-test sweep is a
    five-minute job and lives in R27_STATUS; this is the part that fits in a
    commit gate and would have caught ``test_shipped_config_still_launches``.
    """

    plugin = tmp_path / "ownerstoreprobe.py"
    plugin.write_text(
        "import os, sqlite3, sys\n"
        f"OWNER = {str(OWNER_STORE.resolve())!r}\n"
        "_real = sqlite3.connect\n"
        "def _guard(database, *a, **k):\n"
        "    text = os.fsdecode(database) if isinstance(database, (str, bytes, os.PathLike))"
        " else ''\n"
        "    if text.startswith('file:'):\n"
        "        text = text[5:].split('?', 1)[0]\n"
        "    if text and text != ':memory:':\n"
        "        try:\n"
        "            resolved = os.path.realpath(text)\n"
        "        except OSError:\n"
        "            resolved = text\n"
        "        if resolved == os.path.realpath(OWNER):\n"
        "            raise AssertionError('R27: opened the owner store: ' + resolved)\n"
        "    return _real(database, *a, **k)\n"
        "sqlite3.connect = _guard\n",
        encoding="utf-8",
    )
    env = dict(os.environ)
    env["PYTHONPATH"] = os.pathsep.join([str(tmp_path), str(REPO), env.get("PYTHONPATH", "")])
    env.pop("PYTEST_CURRENT_TEST", None)
    proc = subprocess.run(
        [
            sys.executable,
            "-m",
            "pytest",
            "-q",
            "-p",
            "no:cacheprovider",
            "-p",
            "ownerstoreprobe",
            "tests/test_fail_closed_limits.py",
            "tests/test_conversation_store.py",
            "tests/test_realtime_lane.py",
            "tests/test_scene_and_memory_answers.py",
        ],
        cwd=str(REPO),
        env=env,
        capture_output=True,
        text=True,
        check=False,
        timeout=900,
    )
    hits = [line for line in proc.stdout.splitlines() if "opened the owner store" in line]
    assert not hits, "\n".join(hits)
    assert proc.returncode == 0, proc.stdout[-4000:]


def test_the_read_only_probe_would_actually_catch_a_regression(tmp_path: Path) -> None:
    """A guard nobody has seen fail is a guard nobody should trust.

    The sweep above passes today. This proves the mechanism it relies on —
    intercepting ``sqlite3.connect`` — reddens when a caller really does open
    the owner's file, so a green sweep means "clean" and not "not looking".
    """

    real = sqlite3.connect
    seen: list[str] = []

    def guard(database, *args, **kwargs):  # type: ignore[no-untyped-def]
        text = str(database)
        if text and text != ":memory:" and Path(text).name == OWNER_STORE.name:
            seen.append(text)
            raise AssertionError("R27: opened the owner store")
        return real(database, *args, **kwargs)

    try:
        sqlite3.connect = guard  # type: ignore[assignment]
        with pytest.raises(AssertionError):
            sqlite3.connect(str(tmp_path / OWNER_STORE.name))
    finally:
        sqlite3.connect = real  # type: ignore[assignment]
    assert seen


# ---------------------------------------------------------------------------
# 6. The quarantine tool is not a delete button
# ---------------------------------------------------------------------------


def test_quarantine_defaults_to_dry_run_and_never_deletes(tmp_path: Path) -> None:
    """Card work item 4: the default must not change a byte."""

    source = REPO / "tools" / "quarantine_synthetic_memory.py"
    text = source.read_text(encoding="utf-8")
    # Destructive behaviour must be behind an opt-in flag, not a default.
    assert '"--apply"' in text
    assert "action=\"store_true\"" in text
    assert "DROP TABLE" not in text.upper()
    # Exactly one DELETE runs, it targets `messages`, and it is the statement
    # that follows the verified copy. (The second literal in the file is inside
    # the printed UNDO recipe, which is an instruction to the owner, not a
    # statement this tool executes.)
    deletes = re.findall(r"DELETE FROM (?:messages|\{QUARANTINE_TABLE\})", text)
    assert sorted(deletes) == sorted(
        ["DELETE FROM messages", "DELETE FROM {QUARANTINE_TABLE}"]
    ), deletes
    # The delete is downstream of the verified copy, not beside it.
    assert text.index("refusing to delete") < text.index('f"DELETE FROM messages')

    store = tmp_path / "store.sqlite3"
    memory = ConversationMemory(store)
    memory.connection.execute(
        "INSERT INTO messages(role, content, created_at) VALUES "
        "('user', 'go to the lamppost', '2026-08-21 09:50:00')"
    )
    memory.connection.execute(
        "INSERT INTO messages(role, content, created_at) VALUES "
        "('user', 'a genuine turn', '2026-08-19 09:50:00')"
    )
    memory.connection.commit()
    memory.connection.close()
    before = store.read_bytes()

    proc = subprocess.run(
        [sys.executable, str(source), "--store", str(store)],
        cwd=str(REPO),
        capture_output=True,
        text=True,
        check=False,
        timeout=300,
    )
    assert proc.returncode == 0, proc.stderr
    assert "DRY RUN" in proc.stdout
    assert store.read_bytes() == before, "the dry run modified the store"


def test_quarantine_apply_moves_rows_to_a_side_table_and_keeps_the_rest(
    tmp_path: Path,
) -> None:
    source = REPO / "tools" / "quarantine_synthetic_memory.py"
    store = tmp_path / "store.sqlite3"
    memory = ConversationMemory(store)
    memory.connection.execute(
        "INSERT INTO messages(role, content, created_at) VALUES "
        "('user', 'go to the lamppost', '2026-08-21 09:50:00')"
    )
    memory.connection.execute(
        "INSERT INTO messages(role, content, created_at) VALUES "
        "('user', 'a genuine turn', '2026-08-19 09:50:00')"
    )
    memory.connection.commit()
    memory.connection.close()

    proc = subprocess.run(
        [sys.executable, str(source), "--store", str(store), "--apply"],
        cwd=str(REPO),
        capture_output=True,
        text=True,
        check=False,
        timeout=300,
    )
    assert proc.returncode == 0, proc.stderr
    check = sqlite3.connect(store)
    assert check.execute("SELECT content FROM messages").fetchall() == [("a genuine turn",)]
    quarantined = check.execute(
        "SELECT content, quarantine_reason FROM quarantined_messages"
    ).fetchall()
    assert len(quarantined) == 1
    assert quarantined[0][0] == "go to the lamppost"
    assert "R27" in quarantined[0][1]
    check.close()


def test_quarantine_apply_is_refused_against_the_owner_store() -> None:
    """The tool's destructive mode is gated by the guard this card built.

    Not by a confirmation prompt, which an executor in a non-interactive shell
    would pipe ``yes`` into, but by ``PARCEL_MEMORY_PURPOSE=owner`` — a
    declaration no executor and no test can make.
    """

    source = REPO / "tools" / "quarantine_synthetic_memory.py"
    if not OWNER_STORE.exists():
        pytest.skip("no owner store on this machine")
    digest_before = OWNER_STORE.stat().st_size, OWNER_STORE.stat().st_mtime_ns
    env = {k: v for k, v in os.environ.items() if k not in {ENV_PATH, ENV_PURPOSE}}
    env.pop("PYTEST_CURRENT_TEST", None)
    proc = subprocess.run(
        [sys.executable, str(source), "--apply"],
        cwd=str(REPO),
        env=env,
        capture_output=True,
        text=True,
        check=False,
        timeout=300,
    )
    assert proc.returncode == 3, f"expected a refusal, got {proc.returncode}\n{proc.stdout}"
    assert "OWNER'S conversation memory" in proc.stderr
    assert (OWNER_STORE.stat().st_size, OWNER_STORE.stat().st_mtime_ns) == digest_before
