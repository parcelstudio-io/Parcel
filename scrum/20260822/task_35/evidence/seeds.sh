#!/usr/bin/env bash
# HW-1 seeds S1-S5 + the verifier's V1/V2 (correction pass).
# Usage: seeds.sh <python>          — every seed on the SCRATCH tree only;
# restored by sha256; __pycache__ purged. Never the working tree.
set -u
REPO=/home/jaewoo-jang/Desktop/Projects/Parcel
SCRATCH=$HOME/.cache/parcel-hw1/tree
HEADSRC=$HOME/.cache/parcel-hw1/head-src/src/parcel_robot
PY="${1:-$REPO/.parcel/bin/python}"
GUARD=$HOME/.cache/parcel-guard/pytest_guard.sh
export PYTHONPATH="$SCRATCH:$SCRATCH/src"
cd "$SCRATCH" || exit 1

echo "INTERPRETER: $(env -u TMPDIR "$PY" -c 'import sys;print(sys.version.split()[0])')  ($PY)"
resolved=$(env -u TMPDIR "$PY" -c "import parcel_robot;print(parcel_robot.__file__)")
case "$resolved" in
  "$SCRATCH"/*) echo "IMPORT-VERIFIED: $resolved";;
  *) echo "REFUSING TO SEED: parcel_robot resolves to $resolved"; exit 2;;
esac

run() { env -u TMPDIR "$GUARD" --label hw1 "$PY" -m pytest "$@" 2>&1 | tail -4; }
purge() { find "$SCRATCH" -name __pycache__ -type d -prune -exec rm -rf {} + ; }
NAMECELL="tests/test_hw1_py310_clean.py::test_the_product_package_has_no_unguarded_post_310_names"
GRAMCELL="tests/test_hw1_py310_clean.py::test_every_product_module_parses_under_310_grammar"

restore_file() {  # $1 rel, $2 expected sha
  cp "$REPO/src/parcel_robot/$1" "$SCRATCH/src/parcel_robot/$1"
  got=$(sha256sum "$SCRATCH/src/parcel_robot/$1" | cut -d' ' -f1)
  purge
  [ "$got" = "$2" ] && echo "  RESTORED byte-identical ($got)" || echo "  RESTORE MISMATCH want=$2 got=$got"
}

echo "=========== S1: re-introduce datetime.UTC at observability.py:12 (HEAD form)"
S1SHA=$(sha256sum "$SCRATCH/src/parcel_robot/observability.py" | cut -d' ' -f1)
cp "$HEADSRC/observability.py" "$SCRATCH/src/parcel_robot/observability.py"; purge
echo "--- expect RED:"; run "$NAMECELL" -q
restore_file observability.py "$S1SHA"

echo "=========== S2: re-introduce unguarded typing.Self at online_map/store.py:40 (HEAD form)"
S2SHA=$(sha256sum "$SCRATCH/src/parcel_robot/online_map/store.py" | cut -d' ' -f1)
cp "$HEADSRC/online_map/store.py" "$SCRATCH/src/parcel_robot/online_map/store.py"; purge
echo "--- expect RED:"; run "$NAMECELL" -q
restore_file online_map/store.py "$S2SHA"

echo "=========== S3: PEP 695 type alias (3.12 syntax) in evidence_origin.py"
S3SHA=$(sha256sum "$SCRATCH/src/parcel_robot/evidence_origin.py" | cut -d' ' -f1)
printf '\n\ntype _Hw1SeedAlias = int\n' >> "$SCRATCH/src/parcel_robot/evidence_origin.py"; purge
echo "--- expect RED (grammar cell):"; run "$GRAMCELL" -q
echo "--- expect RED (name cell):";    run "$NAMECELL" -q
restore_file evidence_origin.py "$S3SHA"

echo "=========== S4: tomllib + StrEnum + itertools.batched in memory_path.py"
S4SHA=$(sha256sum "$SCRATCH/src/parcel_robot/memory_path.py" | cut -d' ' -f1)
printf '\n\nimport tomllib\nfrom enum import StrEnum\nimport itertools\n_hw1_seed = list(itertools.batched([1, 2, 3], 2))\n' >> "$SCRATCH/src/parcel_robot/memory_path.py"; purge
echo "--- expect RED:"; run "$NAMECELL" -q
restore_file memory_path.py "$S4SHA"

echo "=========== V1 (verifier): 'if not TYPE_CHECKING:' in bridge/client.py"
V1SHA=$(sha256sum "$SCRATCH/src/parcel_robot/bridge/client.py" | cut -d' ' -f1)
sed -i 's/^if TYPE_CHECKING:  # pragma: no cover/if not TYPE_CHECKING:  # pragma: no cover/' "$SCRATCH/src/parcel_robot/bridge/client.py"; purge
echo "--- the mutated module on THIS interpreter:"
env -u TMPDIR "$PY" -c "import parcel_robot.bridge.client" 2>&1 | tail -1
echo "--- expect RED:"; run "$NAMECELL" -q
restore_file bridge/client.py "$V1SHA"

echo "=========== V2 (verifier): the Self import in an 'else:' arm, providers.py"
V2SHA=$(sha256sum "$SCRATCH/src/parcel_robot/providers.py" | cut -d' ' -f1)
env -u TMPDIR "$PY" - "$SCRATCH/src/parcel_robot/providers.py" <<'PY'
import pathlib, sys
p = pathlib.Path(sys.argv[1])
s = p.read_text()
old = "if TYPE_CHECKING:  # pragma: no cover - annotations only; never evaluated at runtime\n    from typing import Self\n"
new = ("if TYPE_CHECKING:  # pragma: no cover - annotations only; never evaluated at runtime\n"
       "    pass\nelse:\n    from typing import Self\n")
assert old in s
p.write_text(s.replace(old, new, 1))
PY
purge
echo "--- the mutated module on THIS interpreter:"
env -u TMPDIR "$PY" -c "import parcel_robot.providers" 2>&1 | tail -1
echo "--- expect RED:"; run "$NAMECELL" -q
restore_file providers.py "$V2SHA"

echo "=========== S5: negative control — no mutation, the whole file must be green"
purge
run tests/test_hw1_py310_clean.py -q
