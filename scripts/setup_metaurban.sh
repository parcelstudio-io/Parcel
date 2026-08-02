#!/usr/bin/env bash
# Install MetaUrban (metaurban) for living-city + pedestrian simulation.
# Requires Conda and typically Python 3.9 + NVIDIA GPU. Do NOT use the Parcel
# Python 3.14 venv for this stack.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
ENV_NAME="${METAURBAN_ENV:-parcel-metaurban}"
PYTHON_VERSION="${METAURBAN_PYTHON:-3.9}"

if ! command -v conda >/dev/null 2>&1; then
  echo "conda not found. Install Miniconda/Anaconda first."
  echo "https://docs.conda.io/en/latest/miniconda.html"
  exit 1
fi

# shellcheck disable=SC1091
source "$(conda info --base)/etc/profile.d/conda.sh"

if ! conda env list | awk '{print $1}' | grep -qx "$ENV_NAME"; then
  echo "Creating conda env $ENV_NAME (python=$PYTHON_VERSION)..."
  conda create -y -n "$ENV_NAME" "python=$PYTHON_VERSION"
fi

conda activate "$ENV_NAME"

python - <<'PY'
import sys
print(f"Using Python {sys.version}")
if sys.version_info >= (3, 12):
    raise SystemExit("MetaUrban expects Python ~3.9; refuse 3.12+ for this env.")
PY

python -m pip install -U pip setuptools wheel
python -m pip install "gymnasium>=0.28" numpy pyyaml

# Official package name on PyPI / GitHub: metaurban (MetaUrban).
# Prefer editable clone so Parcel can pin commits.
VENDOR="$ROOT/third_party/metaurban"
mkdir -p "$ROOT/third_party"
if [[ ! -d "$VENDOR/.git" ]]; then
  git clone --depth 1 https://github.com/metadriverse/metaurban.git "$VENDOR"
fi
python -m pip install -e "$VENDOR"

python - <<'PY'
try:
    import metaurban
    print("metaurban import OK:", getattr(metaurban, "__file__", metaurban))
except Exception as exc:
    print("WARNING: metaurban import failed:", exc)
    print("See https://github.com/metadriverse/metaurban and docs/NAVIGATION_CITY.md")
PY

echo
echo "Done. Activate with: conda activate $ENV_NAME"
echo "Then from Parcel root:"
echo "  PYTHONPATH=src python examples/nav_city_smoke.py"
echo "For living city render (GPU):"
echo "  PYTHONPATH=src python -c \"from parcel_robot.navigation import MetaUrbanNavEnv; MetaUrbanNavEnv(use_metaurban=True)\""
echo
echo "Download open-weight navigators into models/nav/ (CityWalker / NaVILA / NoMaD)."
echo "Set configs/navigation/default.yaml active_model: citywalker_v1 | navila_v1 | ..."
