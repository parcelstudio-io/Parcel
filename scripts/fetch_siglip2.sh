#!/usr/bin/env bash
# fetch_siglip2.sh — download the SigLIP-2 base/patch16-224 ONNX encoders (text +
# vision) plus their tokenizer/preprocessor config into the cache dir the grounding
# matcher probes. NO SUDO, NO torch: this mirrors scripts/install_speech_services.sh
# (curl/wget fallback, .part staging, sha256-gated, idempotent) — exactly how the
# audio stack lands Silero/smart-turn ONNX. The models run under `onnxruntime`
# (already in .parcel), never torch/transformers.
#
# ---------------------------------------------------------------------------
# SOURCE (Apache-2.0 export, ONNX Runtime-compatible):
#   https://huggingface.co/onnx-community/siglip2-base-patch16-224-ONNX
#
# VARIANT CHOICE — int8 (per-channel, symmetric QDQ):
#   onnxruntime here is CPU-only (providers: CPU + Azure; NO CUDAExecutionProvider),
#   and VRAM is already claimed by Gemma (llama.cpp ~15 GB) + Fish. So the pick is
#   driven by the CPU/RAM budget, not the GPU:
#     * fp32 text encoder is 1.1 GB — the accuracy reference, but heavy.
#     * fp16 is a POOR CPU choice: x86 CPUs lack native fp16 matmul, so ORT
#       up-casts fp16->fp32 at runtime (no speedup, extra casts) — fp16 pays off
#       only on GPU, which onnxruntime can't reach here.
#     * int8 QDQ (283 MB text / 94 MB vision) runs on ORT's native int8 CPU
#       kernels and keeps the footprint small alongside Gemma+Fish.
#   We fetch the SEPARATE text_model / vision_model encoders (not the fused
#   model.onnx): grounding's hot path needs only the TEXT encoder; the vision
#   encoder is the deferred B2 (crop-embedding) consumer. int8 accuracy on the
#   cross-class / synonym cosines is validated by calibrate_threshold at
#   bring-up (see scrum/20260809/task_5/SIGLIP_REAL_STATUS.md).
#
# VARIANT CHOICE — fp16 (text 539 MB / vision 177 MB), OPT-IN via --fp16 (P0-C):
#   The "fp16 pays off only on GPU, which onnxruntime can't reach here" line
#   above was true of the CPU-only onnxruntime. `pip install -e '.[perception]'`
#   puts `onnxruntime-gpu` in .parcel and a real CUDAExecutionProvider with it,
#   so the fp16 encoders become the fast path:
#   `perception_providers.resolve_provider` walks (cuda_fp16, cpu_int8) and picks
#   fp16 only when the EP is registered AND the file is on disk. PG-1 measured
#   the image encoder at 45.9 ms int8-CPU vs 3.35 ms fp16-CUDA on this host.
#   ADDITIVE, never a replacement: `--fp16` fetches the fp16 encoders ALONGSIDE
#   the int8 ones, so the CPU fallback keeps its artifacts and a CUDA-less
#   machine resolves exactly as it does today. Text and vision resolve
#   INDEPENDENTLY, so fetching only one of the two is a supported state.
#   NOTE the fused `onnx/model_fp16.onnx` in the same repo (750 MB) is a
#   DIFFERENT artifact and is deliberately not fetched — this path uses the
#   separate encoders.
#
# EXACT URLs + sha256 (LFS oid for the big files; computed blob sha for the
# small JSON) — pinned so a re-run refuses a corrupt/unexpected file:
#   $BASE/onnx/text_model_int8.onnx    283438275 B  3a0603d3a00c05a80a6ded4743c16aaac7b1e62cdcc7e362e7ce418659b96400
#   $BASE/onnx/vision_model_int8.onnx   94553333 B  0dd31785a2713f1113ef2272472165c69d580473dae38d7b47568ac587795e70
#   $BASE/tokenizer.json                34363039 B  cb9140fae3ac5122c972d37adf83e1248471a38147ad76f8215c8872c6fd8322
#   $BASE/tokenizer.model                4241003 B  61a7b147390c64585d6c3543dd6fc636906c9af3865a5548f27f31aee1d4c8e2
#   $BASE/config.json                        435 B  e43a9f7692d3819886a82cb2097048258d444f123c67d37ec825f9345b019cf2
#   $BASE/preprocessor_config.json           394 B  9b36b57ebaf20f09bf4c22100ccc21877ea6bfe5aead0c00c59f8af8ccefacfc
#   $BASE/tokenizer_config.json            47240 B  7c3a247599e741bceba1a3fe0285aea88d1044dc1fad2caa1e48cdd9fd25f630
#   $BASE/special_tokens_map.json            636 B  baec30ea10906f16adb8c18af7a34023002c1746542612b8b41c9f09e1351351
#   --fp16 only:
#   $BASE/onnx/text_model_fp16.onnx    564862230 B  711da56ada0a4aa11c7dd3320df741081a3cae4f0ae1b5e5c6d5b294738d0eb0
#   $BASE/onnx/vision_model_fp16.onnx  186039516 B  a1959f7bd3993a607e48839f6d01e25b876fe76afda301b028b78eef68aabd95
#   where BASE = https://huggingface.co/onnx-community/siglip2-base-patch16-224-ONNX/resolve/main
#
# TARGET: ~/.cache/parcel/siglip2-b16  (override with PARCEL_SIGLIP2_DIR)
#   text_model_int8.onnx, vision_model_int8.onnx, tokenizer.json, tokenizer.model,
#   config.json, preprocessor_config.json, tokenizer_config.json,
#   special_tokens_map.json  (~420 MB total)
#   + text_model_fp16.onnx, vision_model_fp16.onnx with --fp16  (~1.14 GB total)
#
# USAGE:
#   scripts/fetch_siglip2.sh            # idempotent; verifies existing files
#   scripts/fetch_siglip2.sh --fp16    # ALSO fetch the CUDA fp16 encoders (+716 MB)
#   scripts/fetch_siglip2.sh --force   # re-download even if present
#   PARCEL_SIGLIP2_DIR=/some/dir scripts/fetch_siglip2.sh
# ---------------------------------------------------------------------------
set -euo pipefail

BASE_URL="${PARCEL_SIGLIP2_BASE_URL:-https://huggingface.co/onnx-community/siglip2-base-patch16-224-ONNX/resolve/main}"
DEST_DIR="${PARCEL_SIGLIP2_DIR:-$HOME/.cache/parcel/siglip2-b16}"
FORCE=0
FP16=0
for arg in "$@"; do
  case "$arg" in
    --force) FORCE=1 ;;
    --fp16) FP16=1 ;;
    -h|--help) sed -n '2,71p' "$0"; exit 0 ;;
    *) echo "fetch_siglip2: unknown arg: $arg" >&2; exit 2 ;;
  esac
done

# name  relpath-on-hub  expected_sha256   (relpath doubles as the local basename's dir)
FILES=(
  "text_model_int8.onnx|onnx/text_model_int8.onnx|3a0603d3a00c05a80a6ded4743c16aaac7b1e62cdcc7e362e7ce418659b96400"
  "vision_model_int8.onnx|onnx/vision_model_int8.onnx|0dd31785a2713f1113ef2272472165c69d580473dae38d7b47568ac587795e70"
  "tokenizer.json|tokenizer.json|cb9140fae3ac5122c972d37adf83e1248471a38147ad76f8215c8872c6fd8322"
  "tokenizer.model|tokenizer.model|61a7b147390c64585d6c3543dd6fc636906c9af3865a5548f27f31aee1d4c8e2"
  "config.json|config.json|e43a9f7692d3819886a82cb2097048258d444f123c67d37ec825f9345b019cf2"
  "preprocessor_config.json|preprocessor_config.json|9b36b57ebaf20f09bf4c22100ccc21877ea6bfe5aead0c00c59f8af8ccefacfc"
  "tokenizer_config.json|tokenizer_config.json|7c3a247599e741bceba1a3fe0285aea88d1044dc1fad2caa1e48cdd9fd25f630"
  "special_tokens_map.json|special_tokens_map.json|baec30ea10906f16adb8c18af7a34023002c1746542612b8b41c9f09e1351351"
)

# The CUDA fp16 encoders, appended only under --fp16. Both sha256 == the hub's
# LFS oid, cross-checked against the HF tree API (sizes 564862230 / 186039516)
# AND against the copies PG-1 measured on. Same repo, same export.
FP16_FILES=(
  "text_model_fp16.onnx|onnx/text_model_fp16.onnx|711da56ada0a4aa11c7dd3320df741081a3cae4f0ae1b5e5c6d5b294738d0eb0"
  "vision_model_fp16.onnx|onnx/vision_model_fp16.onnx|a1959f7bd3993a607e48839f6d01e25b876fe76afda301b028b78eef68aabd95"
)
if [[ "$FP16" -eq 1 ]]; then
  FILES+=("${FP16_FILES[@]}")
fi

log() { echo "fetch_siglip2: $*" >&2; }
die() { echo "fetch_siglip2: ERROR: $*" >&2; exit 1; }

# choose a downloader (curl preferred, wget fallback) — same order as the audio scripts.
DOWNLOADER=""
if command -v curl >/dev/null 2>&1; then DOWNLOADER="curl"
elif command -v wget >/dev/null 2>&1; then DOWNLOADER="wget"
else die "need curl or wget (neither found); no sudo required to install one"; fi
command -v sha256sum >/dev/null 2>&1 || die "need sha256sum"

download() {  # download URL DEST — writes DEST only on success
  local url="$1" dest="$2"
  case "$DOWNLOADER" in
    curl) curl --fail --location --retry 3 --retry-delay 2 --connect-timeout 20 \
            --progress-bar --output "$dest" "$url" ;;
    wget) wget --tries=3 --timeout=30 --output-document="$dest" "$url" ;;
  esac
}

sha_of() { sha256sum "$1" | awk '{print $1}'; }

mkdir -p "$DEST_DIR"
SUMMARY=()
for entry in "${FILES[@]}"; do
  IFS='|' read -r name rel expected <<<"$entry"
  url="$BASE_URL/$rel"
  dest="$DEST_DIR/$name"
  if [[ -s "$dest" && "$FORCE" -ne 1 ]]; then
    actual="$(sha_of "$dest")"
    if [[ "$actual" != "$expected" ]]; then
      die "$name already at $dest but sha256 mismatch
  expected $expected
  actual   $actual
Delete it (or --force) to re-download."
    fi
    log "$name already present + verified"
    SUMMARY+=("$name|present|$actual")
    continue
  fi
  log "downloading $name from $url"
  rm -f "$dest.part"
  download "$url" "$dest.part" || { rm -f "$dest.part"; die "$name download failed: $url"; }
  [[ -s "$dest.part" ]] || { rm -f "$dest.part"; die "$name download produced an empty file"; }
  actual="$(sha_of "$dest.part")"
  if [[ "$actual" != "$expected" ]]; then
    rm -f "$dest.part"
    die "$name sha256 mismatch — refusing a corrupt/unexpected file
  url      $url
  expected $expected
  actual   $actual"
  fi
  mv -f "$dest.part" "$dest"
  bytes="$(stat -c %s "$dest")"
  log "$name installed ($bytes bytes) sha256 $actual"
  SUMMARY+=("$name|downloaded|$actual")
done

echo
if [[ "$FP16" -eq 1 ]]; then
  echo "fetch_siglip2: SigLIP-2 int8 + fp16 ONNX landed in $DEST_DIR"
else
  echo "fetch_siglip2: SigLIP-2 int8 ONNX landed in $DEST_DIR"
fi
printf '  %-26s %-10s %s\n' "FILE" "STATUS" "SHA256"
for row in "${SUMMARY[@]}"; do
  IFS='|' read -r n s h <<<"$row"
  printf '  %-26s %-10s %s\n' "$n" "$s" "$h"
done
echo "fetch_siglip2: done. Grounding will pick up the real neural path on next run."
