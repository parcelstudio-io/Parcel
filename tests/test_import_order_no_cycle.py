"""Import-order hard gate: nothing may silently disable the InstructNav ladder.

``navigation/pipeline.py`` imports the whole semantic-nav ladder (GrounderV2,
ProposerBus / GoalArbiter, SemanticMemory2D, value-directed search, scan
recovery) behind one ``try: ... except ImportError:`` so historical frozen BARN
bundles -- which ship a ``parcel_robot`` tree without ``instructnav/`` -- can
still load the grid_v1 sidecars.

That guard is also a perfect trap. If ANY module introduces a cross-package
import cycle that reaches ``navigation.pipeline`` while ``instructnav`` is only
partially initialized, the guard swallows the resulting ``ImportError`` and
``_HAS_INSTRUCTNAV`` silently flips to ``False``. The ladder degrades to the
no-op path, and because ``import parcel_robot.instructnav`` happening *first*
is what triggers it, a unit suite that imports modules in a different order
stays entirely green. That is exactly how a real regression shipped.

So: import each candidate first-mover in a FRESH SUBPROCESS, then import the
pipeline, and assert the ladder is still wired. A fresh process per case is
mandatory -- ``sys.modules`` caching inside a single interpreter would hide the
very ordering effect under test.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]

#: Modules that (transitively) touch instructnav, core, or navigation. Importing
#: any of them before the pipeline must leave the ladder fully wired.
FIRST_IMPORTS = (
    "",  # plain baseline -- pipeline imported first, nothing else loaded
    "parcel_robot.instructnav",
    "parcel_robot.instructnav.arbiter",
    "parcel_robot.core.arbiter",
    "parcel_robot.simulation.headless_city",
    "evals.nav_instruct.runner",
    "parcel_robot.counterfactual",
    "parcel_robot.authority",
)

_PROBE = (
    "from parcel_robot.navigation import pipeline\n"
    "print('_HAS_INSTRUCTNAV=' + repr(pipeline._HAS_INSTRUCTNAV))\n"
)


def _probe(first_import: str) -> subprocess.CompletedProcess[str]:
    preamble = f"import {first_import}\n" if first_import else ""
    return subprocess.run(
        [sys.executable, "-c", preamble + _PROBE],
        capture_output=True,
        text=True,
        cwd=str(REPO_ROOT),  # evals/ is a source tree, not an installed package
        timeout=300,
        check=False,
    )


@pytest.mark.parametrize("first_import", FIRST_IMPORTS, ids=lambda v: v or "baseline")
def test_instructnav_ladder_survives_import_order(first_import: str) -> None:
    """``_HAS_INSTRUCTNAV`` must be True no matter what is imported first."""

    proc = _probe(first_import)
    label = first_import or "(baseline)"
    assert proc.returncode == 0, (
        f"importing {label} before parcel_robot.navigation.pipeline failed:\n"
        f"--- stdout ---\n{proc.stdout}\n--- stderr ---\n{proc.stderr}"
    )
    assert "_HAS_INSTRUCTNAV=True" in proc.stdout, (
        f"importing {label} first SILENTLY DISABLED the InstructNav ladder "
        f"(_HAS_INSTRUCTNAV flipped to False). This is an import cycle: some "
        f"module reachable from {label} imports navigation.pipeline while "
        f"instructnav is still partially initialized, and pipeline's guarded "
        f"import swallows the ImportError. Break the cycle -- move the shared "
        f"symbol into a leaf module, or import it lazily.\n"
        f"--- stdout ---\n{proc.stdout}\n--- stderr ---\n{proc.stderr}"
    )


def test_guarded_import_does_not_swallow_a_cycle() -> None:
    """A non-absence ImportError inside the ladder must be LOUD, not swallowed.

    Simulate the failure mode directly: make ``instructnav.arbiter`` raise a
    plain ``ImportError`` (the shape a circular import takes) and confirm the
    pipeline refuses to load rather than quietly degrading.
    """

    code = (
        "import sys, types\n"
        "mod = types.ModuleType('parcel_robot.instructnav.arbiter')\n"
        "import parcel_robot.instructnav.arbiter as real\n"
        "for _name in ('GoalArbiter', 'ProposerBus'):\n"
        "    setattr(mod, _name, getattr(real, _name))\n"
        "# SE2Goal deliberately missing -- exactly what a partially initialized\n"
        "# module looks like mid-cycle.\n"
        "sys.modules['parcel_robot.instructnav.arbiter'] = mod\n"
        "for _k in [k for k in sys.modules if k.startswith('parcel_robot.navigation')]:\n"
        "    del sys.modules[_k]\n"
        "try:\n"
        "    from parcel_robot.navigation import pipeline\n"
        "except Exception as exc:\n"
        "    print('LOUD=' + type(exc).__name__)\n"
        "else:\n"
        "    print('SILENT=' + repr(pipeline._HAS_INSTRUCTNAV))\n"
    )
    proc = subprocess.run(
        [sys.executable, "-c", code],
        capture_output=True,
        text=True,
        cwd=str(REPO_ROOT),
        timeout=300,
        check=False,
    )
    assert "LOUD=" in proc.stdout, (
        "pipeline swallowed a non-absence ImportError from the InstructNav "
        "ladder instead of failing loudly:\n"
        f"--- stdout ---\n{proc.stdout}\n--- stderr ---\n{proc.stderr}"
    )


def test_genuinely_absent_instructnav_still_soft_degrades() -> None:
    """The documented frozen-BARN path must keep working: absent -> soft.

    Absence is a ``ModuleNotFoundError`` for a module with no spec on disk. That
    -- and only that -- may set ``_HAS_INSTRUCTNAV = False``.

    ``parcel_robot.voice.amendment`` is the module hidden here rather than an
    instructnav one: ``navigation/approach.py`` (imported by the pipeline
    OUTSIDE any guard, at module line 14) hard-requires
    ``instructnav.relations``, and ``instructnav/__init__.py`` eagerly imports
    every instructnav submodule -- so a tree actually missing instructnav can no
    longer load the pipeline at all, guard or no guard. The guard's remaining
    real job is absent *optional* dependencies, which is what this exercises.
    """

    code = (
        "import sys\n"
        "import importlib.abc\n"
        "_HIDDEN = 'parcel_robot.voice.amendment'\n"
        "class _Blocker(importlib.abc.MetaPathFinder):\n"
        "    def find_spec(self, fullname, path=None, target=None):\n"
        "        if fullname == _HIDDEN:\n"
        "            raise ModuleNotFoundError(\n"
        "                'No module named ' + repr(fullname), name=fullname\n"
        "            )\n"
        "        return None\n"
        "sys.meta_path.insert(0, _Blocker())\n"
        "from parcel_robot.navigation import pipeline\n"
        "print('_HAS_INSTRUCTNAV=' + repr(pipeline._HAS_INSTRUCTNAV))\n"
        "print('GrounderV2=' + repr(pipeline.GrounderV2))\n"
        "print('health=' + repr(pipeline.soft_import_health()['instructnav']))\n"
    )
    proc = subprocess.run(
        [sys.executable, "-c", code],
        capture_output=True,
        text=True,
        cwd=str(REPO_ROOT),
        timeout=300,
        check=False,
    )
    assert proc.returncode == 0, (
        "a genuinely absent optional module must soft-degrade (frozen BARN "
        f"bundle path), not raise:\n--- stdout ---\n{proc.stdout}\n"
        f"--- stderr ---\n{proc.stderr}"
    )
    assert "_HAS_INSTRUCTNAV=False" in proc.stdout, proc.stdout
    assert "GrounderV2=None" in proc.stdout, proc.stdout
    assert "health=False" in proc.stdout, proc.stdout
