#!/usr/bin/env bash
# fetch_owlv2.sh — download the OWLv2 open-vocabulary DETECTOR (google/owlv2-base-
# patch16-ensemble) as an int8 ONNX export plus its CLIP tokenizer / preprocessor
# config into the cache dir the detection adapter probes. NO SUDO, NO torch: this
# mirrors scripts/fetch_siglip2.sh (curl/wget fallback, .part staging, sha256-gated,
# idempotent) — the exact no-torch/no-sudo pattern the SigLIP-2 int8 ONNX path proved.
# The model runs under `onnxruntime` (already in .parcel, CPU-only), never
# torch/transformers/PIL.
#
# ---------------------------------------------------------------------------
# LICENSE: **Apache-2.0** (clean product license).
#   Upstream model google/owlv2-base-patch16-ensemble is Apache-2.0 (verified via
#   the HuggingFace model card: license=apache-2.0). The ONNX export
#   onnx-community/owlv2-base-patch16-ensemble-ONNX declares
#   base_model:google/owlv2-base-patch16-ensemble (tags: transformers.js, onnx,
#   owlv2, zero-shot-object-detection) and the transformers.js/Optimum export
#   tooling is Apache-2.0/MIT — so the whole artifact is Apache-2.0, product-safe.
#   This is the license-clean sibling of the SigLIP onnx-community int8 pattern and
#   is DELIBERATELY chosen over the faster YOLO-World/YOLOE family, which is
#   AGPL/Ultralytics-licensed (a product-license risk we do NOT adopt).
#
# SOURCE (Apache-2.0 export, ONNX Runtime-compatible):
#   https://huggingface.co/onnx-community/owlv2-base-patch16-ensemble-ONNX
#
# WHAT OWLv2 IS: an open-vocabulary (zero-shot) object detector. Given free-text
#   query phrases + an image it emits, per candidate box, a logit per text query;
#   sigmoid(logit) is the query<->box score and pred_boxes carry the box geometry.
#   A single fused ONNX takes (input_ids, attention_mask, pixel_values) and returns
#   (logits, pred_boxes) — no post-processing model, box decoding is done in numpy.
#
# VARIANT CHOICE — int8 (model_int8.onnx, 163 MB):
#   onnxruntime here is CPU-only (providers: CPU + Azure; NO CUDAExecutionProvider),
#   and VRAM is already claimed by Gemma (llama.cpp ~15 GB) + Fish, so the pick is
#   CPU/RAM-driven, not GPU:
#     * fp32 model.onnx is 614 MB — the accuracy reference, but heavy.
#     * fp16 (307 MB) is a POOR CPU choice: x86 CPUs lack native fp16 matmul, so
#       ORT up-casts fp16->fp32 at runtime (no speedup) — fp16 pays off only on GPU,
#       which onnxruntime cannot reach here.
#     * int8 QDQ (163 MB) runs on ORT's native int8 CPU kernels and keeps the
#       footprint small alongside Gemma+Fish. Detection is OFF the 10 Hz path
#       (a discrete grounding-time query), so the int8 CPU latency is acceptable.
#   model_int8.onnx == model_quantized.onnx == model_uint8.onnx by content on this
#   export (identical sha) — we pin the explicit int8 name.
#
# EXACT URLs + sha256 (LFS oid == file sha256 for the big model, confirmed via the
# CDN X-Linked-ETag; computed blob sha for the small JSON) — pinned so a re-run
# refuses a corrupt/unexpected file:
#   $BASE/onnx/model_int8.onnx        163173570 B  e9cc288738a96a5a9b730801f622b2e1a531ed2a93d02dd1227a4d35fd9690c6
#   $BASE/tokenizer.json               3642208 B  e277946093d72c7748281a6a344d6c79a5226c48954d6797dc36984aea23ac60
#   $BASE/config.json                      544 B  9222fb235dd16154d94e7bdc7f4d8b0c0bf696eba9f68fd260da6733fd18f731
#   $BASE/preprocessor_config.json         425 B  cf3e396635b797ee1a464e1b2836e98748f8edac19e89aaa2c93b55ac15b0064
#   $BASE/tokenizer_config.json            960 B  bf011c6d421981c3102428c6390472e83d8c097653262b15573ff10af44348ee
#   $BASE/special_tokens_map.json          576 B  c4dbb96da703fb38f10ccf0490df2fd476811c5a3e71b7e0189cffeed3224e25
#   where BASE = https://huggingface.co/onnx-community/owlv2-base-patch16-ensemble-ONNX/resolve/main
#
# TARGET: ~/.cache/parcel/owlv2-b16  (override with PARCEL_OWLV2_DIR)
#   model_int8.onnx, tokenizer.json, config.json, preprocessor_config.json,
#   tokenizer_config.json, special_tokens_map.json  (~167 MB total)
#
# USAGE:
#   scripts/fetch_owlv2.sh            # idempotent; verifies existing files
#   scripts/fetch_owlv2.sh --force   # re-download even if present
#   PARCEL_OWLV2_DIR=/some/dir scripts/fetch_owlv2.sh
# ---------------------------------------------------------------------------
set -euo pipefail

BASE_URL="${PARCEL_OWLV2_BASE_URL:-https://huggingface.co/onnx-community/owlv2-base-patch16-ensemble-ONNX/resolve/main}"
DEST_DIR="${PARCEL_OWLV2_DIR:-$HOME/.cache/parcel/owlv2-b16}"
FORCE=0
for arg in "$@"; do
  case "$arg" in
    --force) FORCE=1 ;;
    -h|--help) sed -n '2,70p' "$0"; exit 0 ;;
    *) echo "fetch_owlv2: unknown arg: $arg" >&2; exit 2 ;;
  esac
done

# name  relpath-on-hub  expected_sha256
FILES=(
  "model_int8.onnx|onnx/model_int8.onnx|e9cc288738a96a5a9b730801f622b2e1a531ed2a93d02dd1227a4d35fd9690c6"
  "tokenizer.json|tokenizer.json|e277946093d72c7748281a6a344d6c79a5226c48954d6797dc36984aea23ac60"
  "config.json|config.json|9222fb235dd16154d94e7bdc7f4d8b0c0bf696eba9f68fd260da6733fd18f731"
  "preprocessor_config.json|preprocessor_config.json|cf3e396635b797ee1a464e1b2836e98748f8edac19e89aaa2c93b55ac15b0064"
  "tokenizer_config.json|tokenizer_config.json|bf011c6d421981c3102428c6390472e83d8c097653262b15573ff10af44348ee"
  "special_tokens_map.json|special_tokens_map.json|c4dbb96da703fb38f10ccf0490df2fd476811c5a3e71b7e0189cffeed3224e25"
)

log() { echo "fetch_owlv2: $*" >&2; }
die() { echo "fetch_owlv2: ERROR: $*" >&2; exit 1; }

# choose a downloader (curl preferred, wget fallback) — same order as the audio/siglip scripts.
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
echo "fetch_owlv2: OWLv2 int8 ONNX (Apache-2.0) landed in $DEST_DIR"
printf '  %-26s %-10s %s\n' "FILE" "STATUS" "SHA256"
for row in "${SUMMARY[@]}"; do
  IFS='|' read -r n s h <<<"$row"
  printf '  %-26s %-10s %s\n' "$n" "$s" "$h"
done
echo "fetch_owlv2: done. The detection adapter picks up the real open-vocab path on next run."
