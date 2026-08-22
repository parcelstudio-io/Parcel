"""The owner model — facts the dog keeps, with consent.

CARD P2-A. HLD §8.4's "Owner profile" tier, which was designed and never built:

    | Owner profile | Preferred formation side, name, accessibility preferences
    | Explicit/consented facts with confidence, edit, export, and delete |

Four modules, and the split is the design:

* :mod:`.policy` — the deterministic privacy policy. A model may PROPOSE a
  fact; this DECIDES whether it may be kept. Swapping the model must not be
  able to change the rules, which is why they are not in a prompt.
* :mod:`.guard` — the refusal that stops the distiller learning from the 256
  executor-written rows card R27 measured in the owner's store. The quarantine
  itself is the owner's action; this is the thing that will not proceed without
  it.
* :mod:`.distiller` — proposers (offline-deterministic and language-model) plus
  the pipeline that runs guard → propose → decide → write.
* :mod:`.notes` — rows to ``owner_notes`` lines, with the consent filter living
  in the renderer so a forgetful caller is filtered anyway.

The table itself lives in :mod:`parcel_robot.memory` beside ``messages``,
because it is the same store and card R27's owner-store isolation guard is on
that constructor. There is no second database and no second set of rules about
which file may be opened.
"""

from __future__ import annotations

from .distiller import (
    DeterministicFactProposer,
    DistillationReport,
    DistilledFact,
    FactCandidate,
    LanguageModelFactProposer,
    OwnerFactDistiller,
    distil_session,
    distil_turns,
)
from .guard import (
    QUARANTINE_COMMAND,
    SYNTHETIC_ID_RANGE,
    SyntheticRowsUnquarantined,
    SyntheticSurvey,
    assert_store_is_distillable,
    survey,
)
from .notes import known_facts_answer, owner_notes_from_facts
from .policy import (
    CONSENT_DENIED,
    CONSENT_GRANTED,
    CONSENT_PENDING,
    DISPOSITION_ASK,
    DISPOSITION_KEEP,
    DISPOSITION_REFUSE,
    PolicyDecision,
    classify,
    decide,
)

__all__ = [
    "CONSENT_DENIED",
    "CONSENT_GRANTED",
    "CONSENT_PENDING",
    "DISPOSITION_ASK",
    "DISPOSITION_KEEP",
    "DISPOSITION_REFUSE",
    "QUARANTINE_COMMAND",
    "SYNTHETIC_ID_RANGE",
    "DeterministicFactProposer",
    "DistillationReport",
    "DistilledFact",
    "FactCandidate",
    "LanguageModelFactProposer",
    "OwnerFactDistiller",
    "PolicyDecision",
    "SyntheticRowsUnquarantined",
    "SyntheticSurvey",
    "assert_store_is_distillable",
    "classify",
    "decide",
    "distil_session",
    "distil_turns",
    "known_facts_answer",
    "owner_notes_from_facts",
    "survey",
]
