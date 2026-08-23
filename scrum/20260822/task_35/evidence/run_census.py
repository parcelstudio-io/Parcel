"""HW-1 rows R1/R2: run the SHIPPED scanner over a given tree root.

Usage:  .parcel/bin/python scrum/20260822/task_35/evidence/run_census.py <root>
where <root> is a ``parcel_robot`` package directory (the working tree's
``src/parcel_robot``, or a ``git archive HEAD`` copy for the pre-fix census).
The scanner is loaded from the shipped test file by path so this script cannot
drift from the guard it is reporting on.
"""

import importlib.util
import sys
from pathlib import Path

REPO = Path("/home/jaewoo-jang/Desktop/Projects/Parcel")
GUARD = REPO / "tests" / "test_hw1_py310_clean.py"

spec = importlib.util.spec_from_file_location("hw1guard", GUARD)
mod = importlib.util.module_from_spec(spec)
sys.modules["hw1guard"] = mod
spec.loader.exec_module(mod)

root = Path(sys.argv[1])
files = sorted(root.rglob("*.py"))
findings = []
for path in files:
    findings.extend(
        mod.scan_source(path.read_text(encoding="utf-8"), label=str(path.relative_to(root)))
    )

by_class: dict[str, list] = {}
for finding in findings:
    by_class.setdefault(finding.symbol, []).append(finding)

print(f"root={root}  files={len(files)}  findings={len(findings)}")
for symbol, group in sorted(by_class.items()):
    print(f"  {symbol}: {len(group)}  unguarded={sum(1 for x in group if not x.guarded)}")
print("--- sites ---")
for finding in sorted(findings, key=lambda f: (f.path, f.line)):
    print(f"  {finding}")
print("UNGUARDED_TOTAL", sum(1 for f in findings if not f.guarded))
