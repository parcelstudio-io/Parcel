"""WALK_WITH_ME_V1 — frozen companion integration scenario pack (K8).

Seeded walk-with-me scripts spanning follow, wait, orbit, sidewalk/lamppost,
pause/resume, barge-in stub, and absent-target honesty. Generator is pure;
runner executes stub or headless harness hooks. Attribution reuses
instructnav FailureClass / AttributionLayer where applicable.
"""

from evals.walk_with_me.generator import (
    FREEZE_SEED,
    PACK_ID,
    ScriptSpec,
    generate_frozen_pack,
    load_frozen_manifest,
    matrix_digest,
    write_frozen_manifest,
)

__all__ = [
    "FREEZE_SEED",
    "PACK_ID",
    "ScriptSpec",
    "generate_frozen_pack",
    "load_frozen_manifest",
    "matrix_digest",
    "write_frozen_manifest",
]
