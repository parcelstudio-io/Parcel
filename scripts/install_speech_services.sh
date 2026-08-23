#!/usr/bin/env bash
# Install the two local speech services Parcel's audio mode depends on:
# whisper.cpp (STT, HTTP server) and Piper (TTS, per-utterance subprocess).
#
# No sudo, no writes outside this repo: everything lands under third_party/
# and models/, both gitignored. Every step is idempotent — a re-run verifies
# what is already there (by SHA256, not by mere existence) and skips it.
# Downloads stage through a ".part" file and are only renamed after their
# checksum matches, so an interrupted run can never leave an artifact that
# looks complete. Any failure aborts the whole script loudly.
#
# Disk footprint (approximate, measured sizes marked exact):
#   third_party/whisper.cpp             ~45 MB shallow clone
#   third_party/whisper.cpp/build       ~120 MB (whisper-server target only)
#   models/whisper/ggml-base.en.bin     147,964,211 B (exact, ~148 MB)
#   third_party/piper                   ~26 MB download, ~80 MB extracted
#   models/piper/voice.onnx              63,201,294 B (exact, ~63 MB)
#   models/piper/voice.onnx.json         ~5 KB
#   => ~240 MB downloaded, ~600 MB installed.
#
# CPU / time expectations:
#   Build is a CPU-only C++17 build of one target. Roughly 1-2 min with -j on
#   a many-core desktop, 10-15 min on a 2-core laptop; on a fast link the
#   ~240 MB of downloads usually dominate. No GPU is used or required.
#   At runtime whisper-server base.en holds ~400-600 MB RSS and transcribes
#   faster than real time on ~8 CPU threads; Piper is spawned per utterance
#   and needs about one core for well under real time.
#
# Host prerequisites (this script never installs them, it only checks):
#   git, cmake, a C++17 compiler, tar, sha256sum, and curl or wget.
#   Debian/Ubuntu: sudo apt install git cmake build-essential
#
# Pinned versions and provenance are the PIN BLOCK below.
# -E so the ERR trap fires inside functions too: no silent partial install.
set -Eeuo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

# ---------------------------------------------------------------- PIN BLOCK
# whisper.cpp moved from ggerganov/ to the ggml-org/ organisation; the old
# path only redirects, so the canonical remote is pinned here.
WHISPER_REPO_URL="${PARCEL_WHISPER_REPO_URL:-https://github.com/ggml-org/whisper.cpp.git}"
WHISPER_TAG="${PARCEL_WHISPER_TAG:-v1.9.1}"
WHISPER_TARGET="${PARCEL_WHISPER_BUILD_TARGET:-whisper-server}"
# The GGML model weights still live under the ggerganov/ Hugging Face repo.
WHISPER_MODEL_URL="${PARCEL_WHISPER_MODEL_URL:-https://huggingface.co/ggerganov/whisper.cpp/resolve/main/ggml-base.en.bin}"
# Published by Hugging Face as the file's LFS oid; re-verified against the
# copy already in this repo at models/whisper/ggml-base.en.bin.
WHISPER_MODEL_SHA256="${PARCEL_WHISPER_MODEL_SHA256:-a03779c86df3323075f5e796cb2ce5029f00ec8869eee3fdfb897afe36c6d002}"

PIPER_TAG="${PARCEL_PIPER_TAG:-2023.11.14-2}"
# ---- CARD HW-7 gate-on-aarch64 (scrum/20260822/task_42) -------------------
# Piper ships a PREBUILT BINARY, so unlike whisper.cpp (built from source here,
# and therefore already portable) the asset name is the one thing in this file
# that decided the architecture. It was hard-coded to x86_64; on the Go2 EDU+'s
# aarch64 Orin that tarball downloads, extracts, and produces a binary that
# cannot run.
#
# MEASURED 2026-08-23 against the pinned release's asset list
# (https://api.github.com/repos/rhasspy/piper/releases/tags/2023.11.14-2 ->
# https://github.com/rhasspy/piper/releases/tag/2023.11.14-2, published
# 2023-11-14): the tag carries piper_linux_x86_64.tar.gz (26,460,462 B),
# piper_linux_aarch64.tar.gz (26,004,717 B) and piper_linux_armv7l.tar.gz
# (25,445,955 B). So the aarch64 asset exists at the version this repo already
# pins -- no version move, no second pin block, one name.
#
# NOT SOLVED HERE, stated so nobody assumes it is: `--piper-only`'s fallback
# for the STT half is the official prebuilt tree
# third_party/whisper.cpp-bin/whisper-bin-ubuntu-x64, and that release has no
# ubuntu-arm64 equivalent. On the dog the whisper half is the from-source build
# this script already does; a toolchain-free aarch64 STT install is UNSOLVED.
PARCEL_TARGET_ARCH="${PARCEL_TARGET_ARCH:-$(uname -m)}"
case "$PARCEL_TARGET_ARCH" in
  x86_64 | amd64) PIPER_ARCH_ASSET="piper_linux_x86_64.tar.gz" ;;
  aarch64 | arm64) PIPER_ARCH_ASSET="piper_linux_aarch64.tar.gz" ;;
  armv7l | armhf) PIPER_ARCH_ASSET="piper_linux_armv7l.tar.gz" ;;
  *)
    PIPER_ARCH_ASSET="piper_linux_$PARCEL_TARGET_ARCH.tar.gz"
    echo "install_speech_services: WARNING: $PARCEL_TARGET_ARCH is not one of the three" \
      "linux assets published at $PIPER_TAG (x86_64, aarch64, armv7l);" \
      "guessing $PIPER_ARCH_ASSET, which will 404 if it does not exist" >&2
    ;;
esac
PIPER_ASSET="${PARCEL_PIPER_ASSET:-$PIPER_ARCH_ASSET}"
# ---- END CARD HW-7 gate-on-aarch64 ----------------------------------------
PIPER_URL="${PARCEL_PIPER_URL:-https://github.com/rhasspy/piper/releases/download/$PIPER_TAG/$PIPER_ASSET}"
# rhasspy/piper publishes no checksums with its release assets, so the
# tarball hash is reported, not enforced. Set PARCEL_PIPER_SHA256 to pin it.
PIPER_SHA256="${PARCEL_PIPER_SHA256:-}"

PIPER_VOICE_NAME="${PARCEL_PIPER_VOICE_NAME:-en_US-lessac-medium}"
PIPER_VOICE_BASE_URL="${PARCEL_PIPER_VOICE_BASE_URL:-https://huggingface.co/rhasspy/piper-voices/resolve/main/en/en_US/lessac/medium}"
PIPER_VOICE_SHA256="${PARCEL_PIPER_VOICE_SHA256:-5efe09e69902187827af646e1a6e9d269dee769f9877d17b16b1b46eeaaf019f}"
# The companion JSON is a plain (non-LFS) file on Hugging Face, which exposes
# no SHA256 for it; it is checksum-reported and structurally validated instead.
PIPER_VOICE_JSON_SHA256="${PARCEL_PIPER_VOICE_JSON_SHA256:-}"
# -------------------------------------------------------------- /PIN BLOCK

# Destination paths. These are exactly what configs/robot.yaml's speech block
# points at (speech.piper_binary, speech.piper_voice) — do not rename them
# without updating that config and scripts/run_speech_services.sh.
WHISPER_SRC="$ROOT/third_party/whisper.cpp"
WHISPER_BUILD="$WHISPER_SRC/build"
WHISPER_SERVER="$WHISPER_BUILD/bin/whisper-server"
WHISPER_MODEL_DIR="$ROOT/models/whisper"
WHISPER_MODEL="$WHISPER_MODEL_DIR/ggml-base.en.bin"
PIPER_DIR="$ROOT/third_party/piper"
PIPER_BIN="$PIPER_DIR/piper"
PIPER_VOICE_DIR="$ROOT/models/piper"
PIPER_VOICE="$PIPER_VOICE_DIR/voice.onnx"
PIPER_VOICE_JSON="$PIPER_VOICE_DIR/voice.onnx.json"

FORCE=0
# ---- CARD HW-7: say what it would do, fetch nothing. -----------------------
DRY_RUN=0
JOBS=""
DOWNLOADER=""
STAGE_DIR=""
PIPER_ONLY=0
SUMMARY=()

usage() {
  cat <<EOF
Usage: scripts/install_speech_services.sh [options]

Installs Parcel's local speech services, without sudo, entirely inside this
repo (third_party/ and models/, both gitignored):

  whisper.cpp $WHISPER_TAG (clone + cmake build)
      -> third_party/whisper.cpp/build/bin/whisper-server
  whisper ggml-base.en.bin
      -> models/whisper/ggml-base.en.bin
  piper $PIPER_TAG (pinned release binary)
      -> third_party/piper/piper
  piper voice $PIPER_VOICE_NAME
      -> models/piper/voice.onnx and models/piper/voice.onnx.json

The voice's companion .onnx.json is mandatory, not decoration: the runtime
reads the voice's native sample rate from it, and a wrong rate plays speech
at the wrong speed.

Start the services afterwards with scripts/run_speech_services.sh, and check
them with scripts/run_speech_services.sh --check.

Options:
  -h, --help        Show this help and exit
  -f, --force       Redo every step even if it already looks complete
      --dry-run     Print the resolved pins, the target architecture and every
                    URL this run would fetch, then exit 0 without touching the
                    network or the disk (card HW-7). PARCEL_TARGET_ARCH
                    overrides `uname -m`, which is how the aarch64 plan is
                    inspected from an x86_64 box.
  -j, --jobs N      Parallel build jobs (default: nproc, capped at 16)
      --piper-only  Install ONLY the TTS half (piper binary + voice + JSON).
                    Needs no git, no cmake and no C++ compiler — the pinned
                    piper release is a prebuilt binary and the voice is a
                    plain download. Use this on a host with no toolchain:
                    scripts/run_speech_services.sh already accepts the
                    official prebuilt whisper.cpp tree at
                    third_party/whisper.cpp-bin/whisper-bin-ubuntu-x64 for
                    the STT half, so the two halves compose.

Disk footprint (~240 MB downloaded, ~600 MB installed):
  whisper.cpp clone ~45 MB, build tree ~120 MB (whisper-server target only)
  whisper base.en model 148 MB (147,964,211 bytes)
  piper release ~26 MB compressed, ~80 MB extracted
  piper voice 63 MB (63,201,294 bytes) + ~5 KB JSON

CPU / time: a CPU-only C++17 build of one target, roughly 1-2 min with -j on
a many-core desktop and 10-15 min on a 2-core laptop; downloads usually
dominate. No GPU is used. At runtime whisper-server holds ~400-600 MB RSS on
~8 threads and Piper needs ~1 core per utterance.

Requires on the host (checked, never installed by this script):
  git, cmake, a C++17 compiler, tar, sha256sum, and curl or wget.
  Debian/Ubuntu: sudo apt install git cmake build-essential

Environment overrides:
  PARCEL_WHISPER_REPO_URL, PARCEL_WHISPER_TAG, PARCEL_WHISPER_BUILD_TARGET
  PARCEL_WHISPER_MODEL_URL, PARCEL_WHISPER_MODEL_SHA256
  PARCEL_TARGET_ARCH (default `uname -m`; selects the piper release asset)
  PARCEL_PIPER_TAG, PARCEL_PIPER_ASSET, PARCEL_PIPER_URL, PARCEL_PIPER_SHA256
  PARCEL_PIPER_VOICE_NAME, PARCEL_PIPER_VOICE_BASE_URL
  PARCEL_PIPER_VOICE_SHA256, PARCEL_PIPER_VOICE_JSON_SHA256
Override a *_URL and you must override its *_SHA256 too: the pins below only
describe the pinned artifacts.
EOF
}

log() {
  echo "install_speech_services: $*"
}

die() {
  echo "install_speech_services: ERROR: $*" >&2
  exit 1
}

on_error() {
  local line="$1"
  echo "install_speech_services: FAILED at line $line — install is INCOMPLETE." >&2
  echo "install_speech_services: nothing was left half-renamed; fix the cause and re-run." >&2
}

cleanup() {
  if [[ -n "$STAGE_DIR" && -d "$STAGE_DIR" ]]; then
    rm -rf "$STAGE_DIR"
  fi
}

trap 'on_error "$LINENO"' ERR
trap cleanup EXIT

sha256_of() {
  sha256sum "$1" | awk '{print $1}'
}

human_size() {
  local bytes
  bytes="$(stat -c %s "$1")"
  echo "$bytes bytes ($(numfmt --to=iec --suffix=B "$bytes" 2>/dev/null || echo "$bytes"))"
}

# download URL DEST — writes DEST only on success.
download() {
  local url="$1" dest="$2"
  case "$DOWNLOADER" in
    curl)
      curl --fail --location --retry 3 --retry-delay 2 --connect-timeout 20 \
        --progress-bar --output "$dest" "$url"
      ;;
    wget)
      wget --tries=3 --timeout=30 --output-document="$dest" "$url"
      ;;
    *)
      die "no downloader selected (internal error)"
      ;;
  esac
}

# fetch_verified LABEL URL DEST EXPECTED_SHA256 — idempotent, checksum-gated.
# An empty EXPECTED_SHA256 means "report the hash, do not enforce it".
fetch_verified() {
  local label="$1" url="$2" dest="$3" expected="$4"
  local actual

  if [[ -s "$dest" && "$FORCE" -ne 1 ]]; then
    actual="$(sha256_of "$dest")"
    if [[ -n "$expected" && "$actual" != "$expected" ]]; then
      die "$label already exists at $dest but its SHA256 does not match the pin
  expected $expected
  actual   $actual
Delete the file (or re-run with --force) to re-download it."
    fi
    log "$label already installed: $dest"
    SUMMARY+=("$label|present|$actual|$dest")
    return 0
  fi

  log "downloading $label from $url"
  mkdir -p "$(dirname "$dest")"
  rm -f "$dest.part"
  if ! download "$url" "$dest.part"; then
    rm -f "$dest.part"
    die "$label download failed: $url"
  fi
  if [[ ! -s "$dest.part" ]]; then
    rm -f "$dest.part"
    die "$label download produced an empty file: $url"
  fi
  actual="$(sha256_of "$dest.part")"
  if [[ -n "$expected" && "$actual" != "$expected" ]]; then
    rm -f "$dest.part"
    die "$label SHA256 mismatch — refusing to install a corrupt or unexpected file
  url      $url
  expected $expected
  actual   $actual"
  fi
  mv -f "$dest.part" "$dest"
  log "$label installed: $dest ($(human_size "$dest"))"
  log "$label sha256: $actual"
  SUMMARY+=("$label|downloaded|$actual|$dest")
}

preflight() {
  if [[ -z "$JOBS" ]]; then
    JOBS="$(nproc 2>/dev/null || echo 4)"
    if ((JOBS > 16)); then
      JOBS=16
    fi
  fi
  [[ "$JOBS" =~ ^[1-9][0-9]*$ ]] || die "--jobs must be a positive integer (got: $JOBS)"

  local missing=()
  local tool
  # --piper-only touches no source tree and compiles nothing, so it drops the
  # git/cmake/compiler requirements. tar+sha256sum+awk+a downloader are still
  # mandatory: the piper release is a checksum-verified tarball.
  local required=(tar sha256sum awk)
  if ((PIPER_ONLY == 0)); then
    required+=(git)
  fi
  for tool in "${required[@]}"; do
    command -v "$tool" >/dev/null 2>&1 || missing+=("$tool")
  done
  if command -v curl >/dev/null 2>&1; then
    DOWNLOADER="curl"
  elif command -v wget >/dev/null 2>&1; then
    DOWNLOADER="wget"
  else
    missing+=("curl or wget")
  fi
  if ((PIPER_ONLY == 0)); then
    command -v cmake >/dev/null 2>&1 || missing+=("cmake")
    if ! command -v c++ >/dev/null 2>&1 && ! command -v g++ >/dev/null 2>&1 \
      && ! command -v clang++ >/dev/null 2>&1; then
      missing+=("a C++17 compiler (g++/clang++)")
    fi
  fi
  if ((${#missing[@]} > 0)); then
    local list
    list="$(printf '%s, ' "${missing[@]}")"
    die "missing host prerequisites: ${list%, }
Install them first, e.g. on Debian/Ubuntu:
  sudo apt install git cmake build-essential curl
This script deliberately never runs sudo itself. If you cannot install a
toolchain, scripts/run_speech_services.sh also accepts the official prebuilt
whisper.cpp release tree at third_party/whisper.cpp-bin/whisper-bin-ubuntu-x64
(or any binary named by PARCEL_WHISPER_SERVER); Piper needs no toolchain at
all, since it ships as a prebuilt binary."
  fi

  if ((PIPER_ONLY == 1)); then
    log "using downloader: $DOWNLOADER; --piper-only (no clone, no build)"
  else
    log "using downloader: $DOWNLOADER; build jobs: $JOBS"
  fi
}

install_whisper_source() {
  local commit
  if [[ -e "$WHISPER_SRC" ]]; then
    [[ -d "$WHISPER_SRC/.git" ]] || die \
      "$WHISPER_SRC exists but is not a git checkout — move it aside and re-run"
    local current
    current="$(git -C "$WHISPER_SRC" describe --tags --exact-match 2>/dev/null || true)"
    if [[ "$current" == "$WHISPER_TAG" && "$FORCE" -ne 1 ]]; then
      commit="$(git -C "$WHISPER_SRC" rev-parse HEAD)"
      log "whisper.cpp already at $WHISPER_TAG ($commit)"
      SUMMARY+=("whisper.cpp source|$WHISPER_TAG|$commit|$WHISPER_SRC")
      return 0
    fi
    log "whisper.cpp checkout is at ${current:-an untagged commit}; moving it to $WHISPER_TAG"
    git -C "$WHISPER_SRC" fetch --depth 1 origin "+refs/tags/$WHISPER_TAG:refs/tags/$WHISPER_TAG" \
      || die "could not fetch tag $WHISPER_TAG from $WHISPER_REPO_URL"
    git -C "$WHISPER_SRC" checkout --quiet "refs/tags/$WHISPER_TAG" \
      || die "could not check out tag $WHISPER_TAG in $WHISPER_SRC"
  else
    local tmp="$WHISPER_SRC.tmp.$$"
    rm -rf "$tmp"
    log "cloning $WHISPER_REPO_URL at $WHISPER_TAG"
    mkdir -p "$(dirname "$WHISPER_SRC")"
    if ! git -c advice.detachedHead=false clone --depth 1 --branch "$WHISPER_TAG" \
      "$WHISPER_REPO_URL" "$tmp"; then
      rm -rf "$tmp"
      die "git clone of $WHISPER_REPO_URL at $WHISPER_TAG failed"
    fi
    mv "$tmp" "$WHISPER_SRC"
  fi
  commit="$(git -C "$WHISPER_SRC" rev-parse HEAD)"
  log "whisper.cpp source: $WHISPER_TAG ($commit)"
  SUMMARY+=("whisper.cpp source|$WHISPER_TAG|$commit|$WHISPER_SRC")
}

build_whisper_server() {
  if [[ -x "$WHISPER_SERVER" && "$FORCE" -ne 1 ]]; then
    log "whisper-server already built: $WHISPER_SERVER"
    SUMMARY+=("whisper-server binary|built|$(sha256_of "$WHISPER_SERVER")|$WHISPER_SERVER")
    return 0
  fi
  log "configuring whisper.cpp (Release, CPU-only) — this is the slow step"
  cmake -B "$WHISPER_BUILD" -S "$WHISPER_SRC" -DCMAKE_BUILD_TYPE=Release \
    || die "cmake configure failed in $WHISPER_SRC"
  log "building target $WHISPER_TARGET with $JOBS jobs"
  cmake --build "$WHISPER_BUILD" --config Release --target "$WHISPER_TARGET" -j "$JOBS" \
    || die "cmake build of $WHISPER_TARGET failed"
  [[ -x "$WHISPER_SERVER" ]] || die \
    "build reported success but $WHISPER_SERVER is missing — the upstream target layout changed"
  log "whisper-server built: $WHISPER_SERVER"
  SUMMARY+=("whisper-server binary|built|$(sha256_of "$WHISPER_SERVER")|$WHISPER_SERVER")
}

install_piper_binary() {
  if [[ -x "$PIPER_BIN" && "$FORCE" -ne 1 ]]; then
    log "piper already installed: $PIPER_BIN"
    SUMMARY+=("piper binary|$PIPER_TAG|$(sha256_of "$PIPER_BIN")|$PIPER_BIN")
    return 0
  fi

  mkdir -p "$ROOT/third_party"
  STAGE_DIR="$(mktemp -d "$ROOT/third_party/.piper-stage.XXXXXX")"
  local tarball="$STAGE_DIR/$PIPER_ASSET"
  log "downloading piper $PIPER_TAG from $PIPER_URL"
  download "$PIPER_URL" "$tarball" || die "piper download failed: $PIPER_URL"
  [[ -s "$tarball" ]] || die "piper download produced an empty file: $PIPER_URL"
  local actual
  actual="$(sha256_of "$tarball")"
  if [[ -n "$PIPER_SHA256" && "$actual" != "$PIPER_SHA256" ]]; then
    die "piper tarball SHA256 mismatch
  url      $PIPER_URL
  expected $PIPER_SHA256
  actual   $actual"
  fi
  log "piper tarball sha256: $actual ($(human_size "$tarball"))"

  mkdir -p "$STAGE_DIR/x"
  tar -xzf "$tarball" -C "$STAGE_DIR/x" || die "could not extract $tarball"
  # The release tarball nests everything under a top-level piper/ directory,
  # but do not depend on that: locate the binary and lift its directory.
  local found
  found="$(find "$STAGE_DIR/x" -maxdepth 3 -type f -name piper -print -quit)"
  [[ -n "$found" ]] || die \
    "no 'piper' binary inside $PIPER_ASSET — the release layout changed; inspect $PIPER_URL"
  local srcdir
  srcdir="$(dirname "$found")"
  rm -rf "$PIPER_DIR"
  mkdir -p "$PIPER_DIR"
  # cp -a keeps the bundled libonnxruntime/espeak-ng shared objects and data
  # next to the binary; it resolves them relative to its own directory.
  cp -a "$srcdir/." "$PIPER_DIR/"
  chmod +x "$PIPER_BIN"
  rm -rf "$STAGE_DIR"
  STAGE_DIR=""
  [[ -x "$PIPER_BIN" ]] || die "piper install finished but $PIPER_BIN is not executable"
  log "piper installed: $PIPER_BIN"
  SUMMARY+=("piper binary|$PIPER_TAG|$(sha256_of "$PIPER_BIN")|$PIPER_BIN")
  SUMMARY+=("piper tarball|$PIPER_TAG|$actual|$PIPER_URL")
}

install_piper_voice() {
  log "installing piper voice $PIPER_VOICE_NAME"
  fetch_verified "piper voice" \
    "$PIPER_VOICE_BASE_URL/$PIPER_VOICE_NAME.onnx" \
    "$PIPER_VOICE" "$PIPER_VOICE_SHA256"
  # Mandatory companion metadata: build_speech_stack reads audio.sample_rate
  # from this file. Without it Parcel guesses 22050 Hz and a mismatched voice
  # plays at the wrong speed.
  fetch_verified "piper voice metadata" \
    "$PIPER_VOICE_BASE_URL/$PIPER_VOICE_NAME.onnx.json" \
    "$PIPER_VOICE_JSON" "$PIPER_VOICE_JSON_SHA256"

  local rate=""
  if command -v python3 >/dev/null 2>&1; then
    rate="$(python3 -c 'import json,sys; d=json.load(open(sys.argv[1])); print(d["audio"]["sample_rate"])' \
      "$PIPER_VOICE_JSON" 2>/dev/null || true)"
    [[ -n "$rate" ]] || die \
      "$PIPER_VOICE_JSON is not a usable Piper voice config (no audio.sample_rate) — re-run with --force"
    log "voice native sample rate: $rate Hz (read from $(basename "$PIPER_VOICE_JSON"))"
  else
    log "python3 not found; skipped the audio.sample_rate validation of $PIPER_VOICE_JSON"
  fi
}

# ---- CARD HW-7 gate-on-aarch64 (scrum/20260822/task_42) -------------------
print_plan() {
  local tool state
  echo "install_speech_services: DRY RUN — nothing is downloaded, built or written"
  echo "  target arch (PARCEL_TARGET_ARCH or uname -m): $PARCEL_TARGET_ARCH"
  echo "  piper release asset:  $PIPER_ASSET"
  echo "  piper url:            $PIPER_URL"
  echo "  piper sha256 pin:     ${PIPER_SHA256:-(none — reported, not enforced)}"
  echo "  piper voice:          $PIPER_VOICE_NAME"
  echo "  piper voice url:      $PIPER_VOICE_BASE_URL/$PIPER_VOICE_NAME.onnx"
  echo "  piper voice sha256:   $PIPER_VOICE_SHA256"
  echo "  whisper repo/tag:     $WHISPER_REPO_URL @ $WHISPER_TAG (built from source — arch-independent)"
  echo "  whisper model url:    $WHISPER_MODEL_URL"
  echo "  whisper model sha256: $WHISPER_MODEL_SHA256"
  echo "  destinations:         $PIPER_BIN, $PIPER_VOICE, $WHISPER_SERVER, $WHISPER_MODEL"
  if ((PIPER_ONLY == 1)); then
    echo "  --piper-only:         the whisper half is SKIPPED (no clone, no build)"
    case "$PARCEL_TARGET_ARCH" in
      x86_64 | amd64) : ;;
      *) echo "  NOTE: the toolchain-free STT fallback (whisper-bin-ubuntu-x64) is x86_64 only;" \
           "on $PARCEL_TARGET_ARCH the whisper half needs the from-source build" ;;
    esac
  fi
  echo "  host tools:"
  for tool in git cmake tar sha256sum awk curl wget python3; do
    if command -v "$tool" >/dev/null 2>&1; then state="present"; else state="MISSING"; fi
    printf "    %-12s %s\n" "$tool" "$state"
  done
}
# ---- END CARD HW-7 gate-on-aarch64 ----------------------------------------

print_summary() {
  echo
  echo "install_speech_services: INSTALL COMPLETE"
  echo
  printf '  %-28s %-24s %s\n' "COMPONENT" "VERSION/STATE" "SHA256"
  local row label version digest path
  for row in "${SUMMARY[@]}"; do
    IFS='|' read -r label version digest path <<<"$row"
    printf '  %-28s %-24s %s\n' "$label" "$version" "$digest"
    printf '  %-28s %s\n' "" "$path"
  done
  echo
  if command -v du >/dev/null 2>&1; then
    echo "  Disk used:"
    local target
    for target in "$WHISPER_SRC" "$WHISPER_MODEL_DIR" "$PIPER_DIR" "$PIPER_VOICE_DIR"; do
      if [[ -e "$target" ]]; then
        printf '    %s\n' "$(du -sh "$target" 2>/dev/null || true)"
      fi
    done
    echo
  fi
  echo "  Next: scripts/run_speech_services.sh          (start whisper-server)"
  echo "        scripts/run_speech_services.sh --check  (verify both services)"
}

main() {
  while (($#)); do
    case "$1" in
      -h | --help)
        usage
        exit 0
        ;;
      -f | --force) FORCE=1 ;;
      --dry-run) DRY_RUN=1 ;;
      --piper-only) PIPER_ONLY=1 ;;
      -j | --jobs)
        shift
        JOBS="${1:-}"
        [[ -n "$JOBS" ]] || die "--jobs needs a value"
        ;;
      --jobs=*) JOBS="${1#*=}" ;;
      --) shift; break ;;
      *) die "unknown argument: $1 (see --help)" ;;
    esac
    shift
  done
  (($# == 0)) || die "unexpected extra arguments: $*"

  # ---- CARD HW-7: the dry run happens BEFORE preflight on purpose. preflight
  # `die`s on a missing toolchain, and "what would you fetch" is exactly the
  # question an operator asks on a host that does not have one yet.
  if ((DRY_RUN == 1)); then
    print_plan
    exit 0
  fi
  # ---- END CARD HW-7
  preflight
  log "installing into $ROOT/third_party and $ROOT/models (both gitignored)"
  if ((PIPER_ONLY == 1)); then
    log "--piper-only: skipping the whisper.cpp clone, build and model download"
    log "  STT still needs a whisper-server; run_speech_services.sh accepts the"
    log "  prebuilt tree at third_party/whisper.cpp-bin/whisper-bin-ubuntu-x64"
  else
    install_whisper_source
    build_whisper_server
    fetch_verified "whisper model (base.en)" "$WHISPER_MODEL_URL" \
      "$WHISPER_MODEL" "$WHISPER_MODEL_SHA256"
  fi
  install_piper_binary
  install_piper_voice
  print_summary
}

main "$@"
