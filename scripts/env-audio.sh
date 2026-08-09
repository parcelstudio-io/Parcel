#!/usr/bin/env bash
# Put a user-space PortAudio on the library path so `sounddevice` works in the
# project venv WITHOUT root.
#
# WHY THIS EXISTS
#   src/parcel_robot/voice_audio.py opens capture/playback through
#   `sounddevice`, which loads libportaudio.so.2 via ctypes. This host has no
#   libportaudio2 package installed and `sudo apt install libportaudio2` is not
#   available to the build. `apt-get download` + `dpkg -x` need no root at all,
#   so the shared object is unpacked into a private prefix and exported here.
#   The sudo path (docs/ACOUSTIC_BRINGUP_PLAN.md, backlog B1) remains a strictly
#   optional convenience: it would retire this script, nothing more.
#
# USAGE
#   source scripts/env-audio.sh          # export LD_LIBRARY_PATH (installs if needed)
#   scripts/env-audio.sh --install       # (re)build the prefix, then print the exports
#   scripts/env-audio.sh --check         # verify sounddevice enumerates; nonzero on failure
#   scripts/env-audio.sh --print         # print the export line only (for eval)
#
# SCOPE DISCIPLINE (docs risk: three separate LD_LIBRARY_PATH injections)
#   This prefix, third_party/whisper.cpp-bin's ggml .so directory, and any
#   future nvidia cublas/cudnn dirs are THREE different injections for THREE
#   different processes. Source this only in the path that runs Parcel's own
#   Python; run_speech_services.sh already scopes its own export to the
#   whisper-server it spawns. Do not merge them into one global export.
#
# PINNED SNAPSHOT (verified on this host 2026-08-07, Ubuntu resolute/universe)
#   libportaudio2  19.7.0+git20260206.e1b70d33-0ubuntu1  amd64
#     deb sha256 2c6290fe3730f63569a0f3ee4b24ffcaede479611af608f5f9f643336e0df16d
#   libjack-jackd2-0  1.9.22~dfsg-5build1  amd64
#     deb sha256 129857d470a11901a74ad51eb249b5a7c4f46ff22981d9cb4e2996c6bdb8fe99
#   libjack is REQUIRED, not optional: libportaudio.so.2 has a DT_NEEDED on
#   libjack.so.0 and this host does not ship it. Without it the dlopen fails
#   with a bare "cannot open shared object file" that looks like a PortAudio bug.
#   apt-get download serves whatever the mirror currently has; --check compares
#   the fetched .deb against these shas and warns (does not fail) on drift, so a
#   mirror bump is visible instead of silent.
#
# THE DEV SYMLINK IS LOAD-BEARING
#   ctypes.util.find_library("portaudio") does NOT consult LD_LIBRARY_PATH for
#   its ldconfig lookup; its fallback path compiles/inspects with ld/objdump and
#   asks for the UNVERSIONED name. So libportaudio.so -> libportaudio.so.2 must
#   exist in the prefix or sounddevice reports "PortAudio library not found"
#   even though the .so.2 is right there on the path.
#
# FALLBACK IF binutils EVER DISAPPEARS (ld/objdump gone => find_library fails):
#   add this before importing sounddevice, no other change needed --
#     import ctypes.util, os
#     _real = ctypes.util.find_library
#     ctypes.util.find_library = lambda n: (
#         os.environ["PARCEL_PORTAUDIO_SO"] if n == "portaudio" else _real(n))
#   with PARCEL_PORTAUDIO_SO pointing at the prefix's libportaudio.so.2.
#   Keep it here, in the script, rather than in tribal memory.

set -Eeuo pipefail

PARCEL_AUDIO_PREFIX="${PARCEL_AUDIO_PREFIX:-$HOME/.local/opt/portaudio}"
PARCEL_AUDIO_LIBDIR="$PARCEL_AUDIO_PREFIX/usr/lib/x86_64-linux-gnu"

PARCEL_AUDIO_DEB_PACKAGES=(libportaudio2 libjack-jackd2-0)
# package:sha256 of the verified snapshot (see PINNED SNAPSHOT above)
PARCEL_AUDIO_DEB_SHA256=(
  "libportaudio2:2c6290fe3730f63569a0f3ee4b24ffcaede479611af608f5f9f643336e0df16d"
  "libjack-jackd2-0:129857d470a11901a74ad51eb249b5a7c4f46ff22981d9cb4e2996c6bdb8fe99"
)

_env_audio_log() {
  echo "env-audio: $*" >&2
}

# True when the prefix already has everything sounddevice needs.
env_audio_prefix_ready() {
  [[ -e "$PARCEL_AUDIO_LIBDIR/libportaudio.so.2" ]] \
    && [[ -e "$PARCEL_AUDIO_LIBDIR/libportaudio.so" ]] \
    && [[ -e "$PARCEL_AUDIO_LIBDIR/libjack.so.0" ]]
}

env_audio_verify_shas() {
  local deb pkg expected actual
  for entry in "${PARCEL_AUDIO_DEB_SHA256[@]}"; do
    pkg="${entry%%:*}"
    expected="${entry##*:}"
    deb="$(find "$PARCEL_AUDIO_PREFIX" -maxdepth 1 -name "${pkg}_*.deb" -print -quit 2>/dev/null || true)"
    [[ -n "$deb" ]] || continue
    actual="$(sha256sum "$deb" | cut -d' ' -f1)"
    if [[ "$actual" != "$expected" ]]; then
      _env_audio_log "WARNING: $pkg drifted from the verified snapshot"
      _env_audio_log "  expected $expected"
      _env_audio_log "  got      $actual  ($deb)"
      _env_audio_log "  the mirror moved; re-verify the audio gates before trusting them"
    fi
  done
}

env_audio_install() {
  command -v apt-get >/dev/null 2>&1 || {
    _env_audio_log "ERROR: apt-get is required to fetch the PortAudio .debs"
    return 1
  }
  command -v dpkg >/dev/null 2>&1 || {
    _env_audio_log "ERROR: dpkg is required to unpack the PortAudio .debs"
    return 1
  }

  mkdir -p "$PARCEL_AUDIO_PREFIX" || {
    _env_audio_log "ERROR: cannot create the prefix directory $PARCEL_AUDIO_PREFIX"
    return 1
  }
  # apt-get download writes to the CWD, so it MUST run inside the prefix.
  # The `cd || exit` is load-bearing: this function is invoked as
  # `env_audio_install || return 1`, and bash disables `set -e` for the whole
  # of a command used as the left side of `||`. Without the explicit guard a
  # failed cd silently leaves apt-get to litter the caller's working
  # directory with .debs (observed: two .debs dropped in the repo root).
  (
    cd "$PARCEL_AUDIO_PREFIX" || exit 1
    _env_audio_log "downloading ${PARCEL_AUDIO_DEB_PACKAGES[*]} into $PARCEL_AUDIO_PREFIX"
    apt-get download "${PARCEL_AUDIO_DEB_PACKAGES[@]}" >&2 || exit 1
    for deb in *.deb; do
      [[ -e "$deb" ]] || continue
      dpkg -x "$deb" . >&2 || exit 1
    done
  ) || {
    _env_audio_log "ERROR: could not populate $PARCEL_AUDIO_PREFIX"
    return 1
  }

  # ctypes.util.find_library needs the unversioned name (see header).
  if [[ -e "$PARCEL_AUDIO_LIBDIR/libportaudio.so.2" ]]; then
    ln -sf libportaudio.so.2 "$PARCEL_AUDIO_LIBDIR/libportaudio.so"
  fi

  env_audio_verify_shas

  env_audio_prefix_ready || {
    _env_audio_log "ERROR: prefix is incomplete after install: $PARCEL_AUDIO_LIBDIR"
    return 1
  }
  _env_audio_log "prefix ready: $PARCEL_AUDIO_LIBDIR"
}

env_audio_export() {
  case ":${LD_LIBRARY_PATH:-}:" in
    *":$PARCEL_AUDIO_LIBDIR:"*) ;;
    *) export LD_LIBRARY_PATH="$PARCEL_AUDIO_LIBDIR${LD_LIBRARY_PATH:+:$LD_LIBRARY_PATH}" ;;
  esac
  export PARCEL_PORTAUDIO_SO="$PARCEL_AUDIO_LIBDIR/libportaudio.so.2"
}

# Idempotent entry point used by `source` and by the launch scripts.
env_audio_activate() {
  if ! env_audio_prefix_ready; then
    env_audio_install || return 1
  fi
  env_audio_export
}

env_audio_check() {
  local root python
  root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
  python="${PARCEL_PYTHON:-$root/.parcel/bin/python}"
  [[ -x "$python" ]] || python="python3"
  env_audio_activate || return 1
  "$python" - <<'PY'
import sys

try:
    import sounddevice
except Exception as error:  # noqa: BLE001 - this IS the gate
    print(f"env-audio: FAIL: sounddevice did not import: {error}", file=sys.stderr)
    raise SystemExit(1)

devices = sounddevice.query_devices()
hostapis = {sounddevice.query_hostapis(d["hostapi"])["name"] for d in devices}
inputs = [d for d in devices if d["max_input_channels"] > 0]
outputs = [d for d in devices if d["max_output_channels"] > 0]
print(f"env-audio: portaudio {sounddevice.get_portaudio_version()[1]}")
print(f"env-audio: {len(devices)} device(s); hostapis: {', '.join(sorted(hostapis))}")
print(f"env-audio: {len(inputs)} input, {len(outputs)} output")
if not devices:
    print("env-audio: FAIL: PortAudio loaded but enumerated no devices", file=sys.stderr)
    raise SystemExit(1)
print("env-audio: CHECK PASSED")
PY
}

# --- CLI ------------------------------------------------------------------
# Sourcing runs env_audio_activate and defines nothing else; executing takes a
# subcommand. BASH_SOURCE[0] != $0 exactly when this file was sourced.
if [[ "${BASH_SOURCE[0]}" != "${0}" ]]; then
  env_audio_activate || _env_audio_log "WARNING: audio prefix unavailable; speech will degrade to text"
else
  case "${1:---print}" in
    --install)
      env_audio_install
      env_audio_export
      echo "export LD_LIBRARY_PATH=\"$LD_LIBRARY_PATH\""
      ;;
    --check) env_audio_check ;;
    --print)
      env_audio_activate
      echo "export LD_LIBRARY_PATH=\"$LD_LIBRARY_PATH\""
      ;;
    -h | --help)
      sed -n '2,60p' "${BASH_SOURCE[0]}"
      ;;
    *)
      _env_audio_log "unknown option: $1 (see --help)"
      exit 2
      ;;
  esac
fi
