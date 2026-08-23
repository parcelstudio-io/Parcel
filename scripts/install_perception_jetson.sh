#!/usr/bin/env bash
# Install the `perception-jetson` extra into the Orin's own detector venv.
#
# Card HW-7 (scrum/20260822/task_42), design WAVE3_HW_DESIGN_FABLE.md §5.2,
# seam S10. This script exists because ONE fact makes the desktop instructions
# useless on the dog: `onnxruntime-gpu` publishes **no aarch64 wheel on PyPI at
# any version** (measured by card HW-1, `task_35/HW1_STATUS.md` H3 — pip says
# "from versions: none", which is why the `perception-jetson` extra in
# pyproject.toml is deliberately unpinned). The wheel comes from the Jetson
# index instead, and `pip install '.[perception-jetson]'` against plain PyPI is
# EXPECTED to fail. This is the remedy, and it refuses rather than guesses.
#
# WHAT IT DOES NOT TOUCH. The product venv. The detector runs behind
# `perception_daemon/`'s AF_UNIX boundary in a venv of its own (design §5.2);
# `src/parcel_robot` never imports onnxruntime, and an absent daemon is a typed
# degrade, not a failure. Installing this changes nothing above the socket.
#
# WHY CPython 3.10 AND NOT THE PRODUCT VENV'S 3.12. The Jetson index publishes
# the wheel for cp310 ONLY (measured below). The §5.1 amendment says exactly
# this: the product venv is a uv-provisioned CPython 3.12, and 3.10 stays the
# floor for the three vendor-bound venvs — perception is one of them.
#
# ---------------------------------------------------------------- PROVENANCE
# MEASURED 2026-08-23 from this x86_64 desktop by HTTP (no aarch64 code ran):
#
#   index  https://pypi.jetson-ai-lab.io/jp6/cu126   HTTP 200
#   index  https://pypi.jetson-ai-lab.io/jp6/cu128   HTTP 200
#   wheel  onnxruntime_gpu-1.24.0-cp310-cp310-linux_aarch64.whl
#   bytes  73,617,978
#   sha256 d980b934b9a29c1a9d6f39751edd7662b69fadd75556a10ff363773a58ce0950
#
# Three things that measurement settled, and one it did not:
#   * BOTH index paths serve the SAME wheel — byte-identical sha256 — so the
#     cu126-vs-cu128 choice does not change which onnxruntime you get today.
#     It may change other packages on that index, and it may change tomorrow.
#   * The only interpreter tag published is cp310. No cp312, no abi3.
#   * The version is **1.24.0**, not the 1.23.0 the design's §5.2 recorded.
#   * NOT settled: which index the box should use. That depends on the JetPack
#     / CUDA the dock actually ships, which is box-day read B9
#     (`cat /etc/nv_tegra_release`) and is **UNCONFIRMED** until then. This
#     script therefore REFUSES to pick one for you: pass --jetpack or
#     --index-url. A wheel built against the wrong CUDA loads, advertises
#     CUDAExecutionProvider from a stub, and silently builds a CPU session —
#     the exact failure `perception_providers.assert_provider_honoured()`
#     exists to catch, measured at 726 ms/query on the desktop (PG-1 §6).
# --------------------------------------------------------------- /PROVENANCE

set -Eeuo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

WHEEL_NAME="onnxruntime_gpu-1.24.0-cp310-cp310-linux_aarch64.whl"
WHEEL_SHA256="d980b934b9a29c1a9d6f39751edd7662b69fadd75556a10ff363773a58ce0950"
WHEEL_BYTES="73617978"
MEASURED_ON="2026-08-23"

# JetPack -> index path. UNCONFIRMED which row is the dock's (B9).
INDEX_JP6_CU126="https://pypi.jetson-ai-lab.io/jp6/cu126"
INDEX_JP6_CU128="https://pypi.jetson-ai-lab.io/jp6/cu128"

VENV="${PARCEL_PERCEPTION_VENV:-$HOME/parcel-perception-venv}"
PYTHON310="${PARCEL_PERCEPTION_PYTHON:-python3.10}"
INDEX_URL=""
JETPACK=""
DRY_RUN=0

log() { echo "install_perception_jetson: $*"; }
die() { echo "install_perception_jetson: ERROR: $*" >&2; exit 1; }

usage() {
  cat <<EOF
Usage: scripts/install_perception_jetson.sh (--jetpack VER | --index-url URL) [options]

Installs the \`perception-jetson\` extra (onnxruntime-gpu, aarch64) into a
CPython 3.10 venv on the Go2 EDU+'s Orin NX. Refuses to run anywhere else.

Required, one of:
  --jetpack 6.1|6.2       select the measured Jetson index for that JetPack
                          (6.1 -> cu126, 6.2 -> cu128). UNCONFIRMED which one
                          the dock needs until box-day read B9.
  --index-url URL         use this PEP 503 index instead (records it verbatim)

Options:
  --venv PATH             detector venv (default: \$HOME/parcel-perception-venv)
  --python PATH           the CPython 3.10 to build it with (default python3.10)
  --dry-run               print the plan and the provenance; install nothing
  -h, --help              this text

Provenance for the wheel this installs is the PROVENANCE block at the top of
this file; it is printed by --dry-run and written to the venv on install.
EOF
}

refuse_unless_aarch64() {
  local machine
  machine="$(uname -m)"
  case "$machine" in
    aarch64 | arm64) log "architecture $machine — proceeding" ;;
    *)
      echo "install_perception_jetson: REFUSED on $machine." >&2
      echo "  This installs an aarch64 wheel ($WHEEL_NAME)" >&2
      echo "  into a venv for the Orin NX. It is not installable here and it is" >&2
      echo "  not what the desktop needs: on x86_64 the detector comes from PyPI —" >&2
      echo "    ${ROOT}/.parcel/bin/pip install -e '${ROOT}[perception]'" >&2
      echo "  (onnxruntime-gpu[cuda,cudnn]>=1.28, pyproject.toml). Nothing was" >&2
      echo "  downloaded, created or changed. Run --dry-run to read the plan." >&2
      exit 2
      ;;
  esac
}

resolve_index() {
  if [[ -n "$INDEX_URL" && -n "$JETPACK" ]]; then
    die "pass either --jetpack or --index-url, not both — two answers is no answer"
  fi
  if [[ -n "$INDEX_URL" ]]; then
    log "index (explicit): $INDEX_URL"
    return 0
  fi
  case "$JETPACK" in
    6.1) INDEX_URL="$INDEX_JP6_CU126" ;;
    6.2) INDEX_URL="$INDEX_JP6_CU128" ;;
    "")
      die "no index selected. This script will NOT guess: the JetPack/CUDA on
  the dock is box-day read B9 (\`cat /etc/nv_tegra_release; nvcc --version\`)
  and is UNCONFIRMED. Re-run with --jetpack 6.1|6.2, or --index-url URL.
  Measured $MEASURED_ON, both of these serve the same wheel ($WHEEL_SHA256):
    $INDEX_JP6_CU126
    $INDEX_JP6_CU128"
      ;;
    *)
      die "--jetpack $JETPACK is not one of the measured rows (6.1, 6.2).
  Pass --index-url explicitly if the dock ships something else; the URL is
  recorded verbatim in the provenance file so the choice stays auditable."
      ;;
  esac
  log "index (--jetpack $JETPACK): $INDEX_URL"
}

print_plan() {
  echo "install_perception_jetson: PLAN"
  echo "  machine:        $(uname -m)"
  echo "  venv:           $VENV"
  echo "  interpreter:    $PYTHON310 (cp310 — the only tag the index publishes)"
  echo "  index:          ${INDEX_URL:-<unselected: pass --jetpack or --index-url>}"
  echo "  extra:          perception-jetson  (pyproject.toml, unpinned on purpose)"
  echo "  wheel:          $WHEEL_NAME"
  echo "  wheel bytes:    $WHEEL_BYTES"
  echo "  wheel sha256:   $WHEEL_SHA256"
  echo "  measured:       $MEASURED_ON, by HTTP from an x86_64 desktop"
  echo "  UNCONFIRMED:    which index the dock needs (box-day read B9); whether"
  echo "                  this wheel's CUDA EP is honoured on the Orin (Q-ort)."
  echo "  it would run:   $PYTHON310 -m venv $VENV"
  echo "                  $VENV/bin/pip install --extra-index-url <index> -e '$ROOT[perception-jetson]'"
  echo "                  $VENV/bin/python -c 'import onnxruntime; ...'  (provider check)"
}

write_provenance() {
  local out="$VENV/parcel-perception-provenance.txt"
  {
    echo "# Written by scripts/install_perception_jetson.sh (card HW-7)"
    echo "installed_at=$(date -Is)"
    echo "machine=$(uname -m)"
    echo "index_url=$INDEX_URL"
    echo "jetpack_flag=${JETPACK:-<explicit index>}"
    echo "expected_wheel=$WHEEL_NAME"
    echo "expected_sha256=$WHEEL_SHA256"
    echo "measured_on=$MEASURED_ON"
    echo "# What pip actually resolved:"
    "$VENV/bin/pip" freeze 2>/dev/null | grep -i '^onnxruntime' || echo "onnxruntime=NOT INSTALLED"
  } > "$out"
  log "provenance written: $out"
  sed 's/^/  /' "$out"
}

check_provider() {
  log "checking which execution providers the installed runtime offers"
  "$VENV/bin/python" - <<'PY' || log "WARNING: the provider check did not complete"
import sys

try:
    import onnxruntime as ort
except Exception as error:  # broad on purpose: this IS the check
    print(f"install_perception_jetson: onnxruntime did not import: {error}", file=sys.stderr)
    raise SystemExit(1)

providers = ort.get_available_providers()
print(f"install_perception_jetson: onnxruntime {ort.__version__}")
print(f"install_perception_jetson: providers {providers}")
if "CUDAExecutionProvider" not in providers:
    print(
        "install_perception_jetson: WARNING: no CUDAExecutionProvider. The daemon "
        "would run on the CPU. This is exactly what "
        "perception_providers.assert_provider_honoured() refuses at session "
        "construction, so fix the wheel/CUDA pairing before trusting a latency "
        "number.",
        file=sys.stderr,
    )
PY
}

main() {
  while (($#)); do
    case "$1" in
      -h | --help) usage; exit 0 ;;
      --dry-run) DRY_RUN=1 ;;
      --jetpack) shift; JETPACK="${1:-}"; [[ -n "$JETPACK" ]] || die "--jetpack needs a value" ;;
      --jetpack=*) JETPACK="${1#*=}" ;;
      --index-url) shift; INDEX_URL="${1:-}"; [[ -n "$INDEX_URL" ]] || die "--index-url needs a value" ;;
      --index-url=*) INDEX_URL="${1#*=}" ;;
      --venv) shift; VENV="${1:-}"; [[ -n "$VENV" ]] || die "--venv needs a value" ;;
      --venv=*) VENV="${1#*=}" ;;
      --python) shift; PYTHON310="${1:-}"; [[ -n "$PYTHON310" ]] || die "--python needs a value" ;;
      --python=*) PYTHON310="${1#*=}" ;;
      *) die "unknown argument: $1 (see --help)" ;;
    esac
    shift
  done

  if ((DRY_RUN == 1)); then
    # The dry run reports the refusal instead of performing it: an operator on
    # the desktop should be able to READ the aarch64 plan without pretending to
    # be on the dog. It still installs nothing, anywhere.
    case "$(uname -m)" in
      aarch64 | arm64) : ;;
      *) echo "install_perception_jetson: NOTE: on $(uname -m) a real run REFUSES (exit 2)." ;;
    esac
    [[ -n "$INDEX_URL" || -n "$JETPACK" ]] && resolve_index
    print_plan
    exit 0
  fi

  refuse_unless_aarch64
  resolve_index

  command -v "$PYTHON310" >/dev/null 2>&1 || die \
    "$PYTHON310 not found. JetPack 6 ships CPython 3.10 as the system python3;
  pass --python /usr/bin/python3 if that is where it lives."
  local version
  version="$("$PYTHON310" -c 'import sys; print("%d.%d" % sys.version_info[:2])')"
  [[ "$version" == "3.10" ]] || die \
    "$PYTHON310 is CPython $version; the Jetson index publishes cp310 ONLY
  (measured $MEASURED_ON). The product venv's 3.12 is a different venv on
  purpose — design 5.1 amendment."

  [[ -d "$VENV" ]] || { log "creating $VENV"; "$PYTHON310" -m venv "$VENV"; }
  log "installing the perception-jetson extra from $INDEX_URL"
  "$VENV/bin/pip" install --upgrade pip
  "$VENV/bin/pip" install --extra-index-url "$INDEX_URL" -e "$ROOT[perception-jetson]"

  write_provenance
  check_provider
  log "done. Point the daemon at it: PARCEL_PERCEPTION_SOCKET + $VENV/bin/python"
}

main "$@"
