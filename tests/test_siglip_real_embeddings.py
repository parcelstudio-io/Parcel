"""A1/A2 — real SigLIP-2 text embeddings behind the SigLIP2Matcher seam.

Weights are ABSENT on CI (torch/transformers not installed), so the real neural
path is exercised through a **synthetic** :class:`SyntheticEmbedder` injected into
the matcher — same seam a real ``google/siglip2-base-patch16`` load fills. Two
properties are pinned:

* **fallback-equals-today** — with no embedder the matcher is byte-identical to
  the pre-neural char-hash/string stub (the frozen-baseline contract);
* **real path suppresses the cross-class false positives** — with an available
  embedder, ``"streetlight"`` grounds to a lamppost by MEANING and refuses a
  tree, deleting the substring coincidences Wave 2 left open.

The real-weight versions of the synonym cells are marked skip-if-weights-absent
and honestly deferred (U25 / SIGLIP_REAL_STATUS.md).
"""

from __future__ import annotations

import math
from typing import ClassVar

import pytest

from parcel_robot.instructnav.grounding import GrounderV2, GroundingOutcome
from parcel_robot.instructnav.siglip import (
    DEFAULT_WEIGHTS,
    SIGLIP2_MATCH_THRESHOLD,
    EmbeddingMatch,
    SigLIP2Matcher,
    calibrate_threshold,
)

WEIGHTS_PRESENT = SigLIP2Matcher().available


# ---------------------------------------------------------------------------
# Synthetic embedder — semantic clustering by class, deterministic.
# ---------------------------------------------------------------------------


class SyntheticEmbedder:
    """Emulates SigLIP-2's semantic clustering without weights.

    Every word maps to a class axis (same class → cosine ≈ 0.98, cross-class →
    ≈ 0.02), so a real neural cosine gate separates them cleanly. Crucially the
    synonym map contains words that are NOT in the curated alias table
    (``streetlamp``) — grounding them proves MEANING, not an alias row.
    """

    dim = 8
    _CLASS_OF: ClassVar[dict[str, str]] = {
        "streetlight": "lamp",
        "streetlamp": "lamp",
        "street lamp": "lamp",
        "lamppost": "lamp",
        "lamp post": "lamp",
        "street light": "lamp",
        "lamp": "lamp",
        "tree": "tree",
        "trees": "tree",
        "street tree": "tree",
        "big tree": "tree",
        "bench": "bench",
        "seat": "bench",
        "park bench": "bench",
        "bench seat": "bench",
        "planter": "planter",
        "plant pot": "planter",
        "flower box": "planter",
    }
    _AXES: ClassVar[dict[str, int]] = {"lamp": 0, "tree": 1, "bench": 2, "planter": 3, "_other": 4}

    def _cls(self, text: str) -> str:
        return self._CLASS_OF.get(" ".join(str(text).lower().split()), "_other")

    def embed_text(self, text: str) -> tuple[float, ...]:
        v = [0.0] * self.dim
        v[self._AXES[self._cls(text)]] = 1.0
        # Deterministic tiny jitter on a shared background axis: identical-class
        # words land close (≈0.98) but not exactly 1.0, mimicking real spread.
        v[self.dim - 1] = 0.15 * ((sum(ord(c) for c in str(text)) % 7) / 7.0)
        norm = math.sqrt(sum(x * x for x in v)) or 1.0
        return tuple(x / norm for x in v)

    def embed_image(self, image: object) -> tuple[float, ...]:
        return self.embed_text(str(image))


def _real_matcher() -> SigLIP2Matcher:
    return SigLIP2Matcher(embedder=SyntheticEmbedder(), real_threshold=SIGLIP2_MATCH_THRESHOLD)


# ---------------------------------------------------------------------------
# fallback-equals-today (the frozen-baseline contract)
# ---------------------------------------------------------------------------


def _pre_neural_stub_match(query: str, labels: list[str]) -> EmbeddingMatch | None:
    """The exact pre-neural string fallback, reimplemented as the oracle."""

    def norm(value: str) -> str:
        return "".join(ch for ch in value.lower() if ch.isalnum())

    if not labels:
        return None
    norm_q = norm(query)
    for label in labels:
        if norm_q and (norm(label) in norm_q or norm_q in norm(label)):
            return EmbeddingMatch(label=label, score=1.0, source="string_fallback")
    return None


BATTERY = [
    ("bench", ["lamppost", "bench"]),
    ("streetlight", ["lamppost", "bench"]),
    ("tree", ["lamppost"]),
    ("seat", ["bench", "tree"]),
    ("the bench", ["bench"]),
    ("streetlamp", ["lamppost"]),
    ("", ["bench"]),
    ("bench", []),
    ("lamp", ["lamppost"]),
    ("planter", ["plant pot"]),
]


@pytest.mark.parametrize("query,labels", BATTERY)
def test_weights_absent_match_is_byte_identical_to_pre_neural_stub(query, labels):
    matcher = SigLIP2Matcher(weights_dir="/tmp/parcel-missing-siglip")
    assert not matcher.available
    assert matcher.match(query, labels) == _pre_neural_stub_match(query, labels)


def test_weights_absent_probe_and_embed_are_off():
    matcher = SigLIP2Matcher(weights_dir="/tmp/parcel-missing-siglip")
    assert not matcher.available
    assert matcher.embed_text("tree") is None
    assert matcher.embed_image(object()) is None


def test_weights_absent_still_has_the_cross_class_substring_fp():
    """Documents WHY the gate is load-bearing: absent weights keep the FP."""

    matcher = SigLIP2Matcher(weights_dir="/tmp/parcel-missing-siglip")
    # "streetlight" ⊃ "tree" ("s-tree-tlight") — the substring coincidence still
    # fires on the bare class label, which is the whole Wave-2 defect.
    hit = matcher.match("streetlight", ["tree"])
    assert hit is not None and hit.source == "string_fallback"


# ---------------------------------------------------------------------------
# Real path (synthetic embedder) — cross-class FP suppression + synonyms
# ---------------------------------------------------------------------------


def test_real_path_is_available_when_embedder_injected():
    matcher = _real_matcher()
    assert matcher.available
    emb = matcher.embed_text("lamppost")
    assert emb is not None
    assert abs(math.sqrt(sum(x * x for x in emb)) - 1.0) < 1e-6  # L2-normalized


def test_real_path_grounds_synonym_by_meaning_not_alias():
    matcher = _real_matcher()
    # "streetlamp" is NOT in the curated alias table — only meaning grounds it.
    hit = matcher.match("streetlamp", ["lamppost"])
    assert hit is not None and hit.source == "siglip2"
    assert hit.label == "lamppost"


def test_real_path_rejects_cross_class_false_positives():
    matcher = _real_matcher()
    # The two Wave-2 false_arrivals, at the matcher level:
    assert matcher.match("streetlight", ["tree"]) is None  # B-05: streetlight → tree
    assert matcher.match("tree", ["streetlight"]) is None  # D-15: tree → lamppost(alias)
    assert matcher.match("big tree", ["lamppost"]) is None  # audit: "big tree" → lamppost


def test_real_path_picks_the_right_class_among_distractors():
    matcher = _real_matcher()
    hit = matcher.match("streetlight", ["tree", "lamppost", "bench"])
    assert hit is not None and hit.label == "lamppost" and hit.source == "siglip2"


# ---------------------------------------------------------------------------
# A2 — GrounderV2 real-embedding wiring (substring rescue deleted)
# ---------------------------------------------------------------------------


def _detection(class_id: str) -> dict:
    return {"id": class_id, "class_id": class_id, "score": 0.9, "distance_m": 3.0}


def test_grounder_real_path_refuses_cross_class_tree_for_streetlight():
    grounder = GrounderV2(matcher=_real_matcher())
    result = grounder.ground("streetlight", detections=[_detection("tree")], robot_xy=(0.0, 0.0))
    assert result.outcome == GroundingOutcome.UNSEEN


def test_grounder_real_path_resolves_streetlight_to_lamppost():
    grounder = GrounderV2(matcher=_real_matcher())
    result = grounder.ground(
        "streetlight", detections=[_detection("lamppost")], robot_xy=(0.0, 0.0)
    )
    assert result.outcome == GroundingOutcome.RESOLVED
    assert result.candidate is not None and result.candidate["class_id"] == "lamppost"


def test_grounder_weights_absent_still_accepts_via_string_rescue():
    """The gate is real: with no weights the string rescue is intact (unchanged)."""

    grounder = GrounderV2(matcher=SigLIP2Matcher(weights_dir="/nonexistent/siglip"))
    result = grounder.ground("bench", detections=[_detection("bench")], robot_xy=(0.0, 0.0))
    assert result.outcome == GroundingOutcome.RESOLVED


# ---------------------------------------------------------------------------
# A2 — semantic_map._matches real-embedding wiring
# ---------------------------------------------------------------------------


def test_semantic_map_matches_real_path_deletes_cross_class(monkeypatch):
    from parcel_robot.navigation import semantic_map

    monkeypatch.setattr(semantic_map, "_SIGLIP_INIT", True)
    monkeypatch.setattr(semantic_map, "_SIGLIP_MATCHER", _real_matcher())

    # Weights-absent (today) would return True here via "tree" ⊂ "streetlight"
    # alias of lamppost. Real path refuses it.
    assert semantic_map._matches("streetlight", "tree", ["trees", "street tree"]) is False
    assert semantic_map._matches("tree", "lamppost", ["streetlight", "street light"]) is False
    # And still grounds the true synonym.
    assert semantic_map._matches("streetlight", "lamppost", ["streetlight"]) is True


def test_semantic_map_matches_weights_absent_keeps_alias_acceptance(monkeypatch):
    from parcel_robot.navigation import semantic_map

    # Force the (default) weights-absent matcher.
    monkeypatch.setattr(semantic_map, "_SIGLIP_INIT", False)
    monkeypatch.setattr(semantic_map, "_SIGLIP_MATCHER", None)
    # Exact alias acceptance survives on both paths (streetlight IS a lamppost alias).
    assert semantic_map._matches("streetlight", "lamppost", []) is True


# ---------------------------------------------------------------------------
# Threshold calibration harness (FAR/TAR) — machinery on the synthetic fixture
# ---------------------------------------------------------------------------

PRESENT_PAIRS = [
    ("streetlight", "lamppost"),
    ("streetlamp", "lamppost"),
    ("seat", "bench"),
    ("big tree", "tree"),
    ("plant pot", "planter"),
]
ABSENT_PAIRS = [
    ("streetlight", "tree"),
    ("tree", "lamppost"),
    ("big tree", "lamppost"),
    ("seat", "planter"),
    ("planter", "bench"),
]


def test_calibration_separates_present_from_absent_on_fixture():
    result = calibrate_threshold(SyntheticEmbedder(), PRESENT_PAIRS, ABSENT_PAIRS)
    # Clean separation: every present cosine above every absent cosine.
    assert result["present_cos_min"] > result["absent_cos_max"]
    thr = result["threshold"]
    # The chosen operating point admits every synonym and refuses every cross-class.
    assert result["youden_j"] == 1.0
    assert result["absent_cos_max"] < thr <= result["present_cos_min"]


# ---------------------------------------------------------------------------
# Env-gate: landing the weights must NOT flip the path on by itself
# ---------------------------------------------------------------------------


def test_onnx_path_is_opt_in_even_when_weights_present(monkeypatch):
    """Weights on disk + env switch OFF => still the byte-identical fallback.

    This is the lever that keeps the whole suite / 10 Hz mission path off the
    ~28 ms/query neural model unless a run explicitly asks for it.
    """

    from parcel_robot.instructnav import siglip2_onnx

    monkeypatch.delenv("PARCEL_SIGLIP2_ONNX", raising=False)
    assert siglip2_onnx.onnx_enabled() is False
    matcher = SigLIP2Matcher()  # probes the real cache dir; env off => no load
    assert matcher.available is False
    assert matcher.embed_text("tree") is None
    # ...and the pre-neural substring defect is intact (proves it IS the fallback)
    hit = matcher.match("streetlight", ["tree"])
    assert hit is not None and hit.source == "string_fallback"


# ---------------------------------------------------------------------------
# Real-weight cells — run only under PARCEL_SIGLIP2_ONNX=1 with the int8 ONNX
# encoders present (scripts/fetch_siglip2.sh). Operating point: thr 0.90 (real
# calibration; see SIGLIP_REAL_STATUS.md "ONNX real-weight run").
# ---------------------------------------------------------------------------


@pytest.mark.skipif(not WEIGHTS_PRESENT, reason=f"SigLIP-2 ONNX not enabled/present at {DEFAULT_WEIGHTS} (U25)")
@pytest.mark.parametrize(
    "query,right,wrong",
    [
        # STRONG synonyms — cosine clears 0.90 (streetlight/lamppost 0.962, the/tree 0.965).
        ("streetlight", "lamppost", "tree"),
        ("streetlamp", "lamppost", "tree"),
        ("the tree", "tree", "lamppost"),
    ],
)
def test_real_weights_synonym_grounds_right_class(query, right, wrong):
    matcher = SigLIP2Matcher()
    assert matcher.available
    hit = matcher.match(query, [wrong, right])
    assert hit is not None and hit.label == right and hit.source == "siglip2"


@pytest.mark.skipif(not WEIGHTS_PRESENT, reason=f"SigLIP-2 ONNX not enabled/present at {DEFAULT_WEIGHTS} (U25)")
def test_real_weights_kills_the_two_cross_class_false_arrivals():
    """The Wave-2 false_arrival pairs, on the REAL int8 ONNX cosine (thr 0.90)."""

    matcher = SigLIP2Matcher()
    assert matcher.available
    # B-05: "streetlight" must NOT commit a tree (cos 0.869 < 0.90).
    assert matcher.match("streetlight", ["tree"]) is None
    # D-15: "tree" must NOT commit a lamppost via its streetlight alias (cos 0.872 < 0.90).
    assert matcher.match("tree", ["lamppost"]) is None
    assert matcher.match("tree", ["streetlight"]) is None
    # ...but the real synonym still grounds among distractors.
    hit = matcher.match("streetlight", ["tree", "lamppost", "bench"])
    assert hit is not None and hit.label == "lamppost"


@pytest.mark.skipif(not WEIGHTS_PRESENT, reason=f"SigLIP-2 ONNX not enabled/present at {DEFAULT_WEIGHTS} (U25)")
def test_real_weights_embed_text_is_unit_norm_768d():
    matcher = SigLIP2Matcher()
    emb = matcher.embed_text("a red fire hydrant on the sidewalk")
    assert emb is not None and len(emb) == 768
    assert abs(math.sqrt(sum(x * x for x in emb)) - 1.0) < 1e-4
