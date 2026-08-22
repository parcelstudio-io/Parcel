"""The deterministic privacy policy: a model PROPOSES, this DECIDES.

CARD P2-A, WORK ITEM 2. HLD §8.4, VERBATIM
==========================================

    A model may propose a memory fact; a deterministic privacy/validation
    policy decides whether it is stored.

That sentence is the whole reason this module is not a prompt. A policy written
into the system instruction is a *request*: it holds for as long as the model
feels like holding it, it cannot be tested, and the first jailbroken turn is
also the first turn in which the robot writes the owner's medication list into
a plaintext SQLite file it will later read back out loud. A policy written here
is a function of the text and nothing else — same input, same verdict, forever,
and a test can assert it.

THE CARD'S OWN LIST, AND THE ONE CATEGORY IT DOES NOT NAME
----------------------------------------------------------

The card says: *names, preferences, routines, places — yes; health, finances,
third-party secrets — ask first.* Those are :data:`KEEP_CATEGORIES` and
:data:`ASK_CATEGORIES` below.

Two additions, both declared in ``P2A_STATUS.md`` rather than smuggled:

1. **An unclassified fact ASKS.** The wave's standing rule is *ask over refuse*,
   and the fail-safe direction for a store the owner cannot see is to ask before
   keeping, never to keep silently. :data:`CATEGORY_OTHER` therefore lands in
   ``ask``, which costs one question and cannot cost a surprise.
2. **A credential is REFUSED, not asked about.** :data:`CATEGORY_SECRET` —
   passwords, PINs, card numbers, national ID numbers. This is the one
   disposition that says no, and it is not a behavioural fail-closed of the kind
   the wave loosened: it is a property of the *storage medium*. ``owner_facts``
   is plaintext, it is rendered into a hosted model's developer instruction at
   every session open, and the robot is built to say what it knows out loud.
   "Ask first" is not a meaningful protection for a value whose entire risk is
   that it exists in that file at all.

WHY KEYWORDS AND NOT A CLASSIFIER
---------------------------------

Because the verdict has to be *reproducible under audit*. A learned classifier
would make "why was this stored" a question with no answer an owner can check.
Every rule below is a word list plus the sentence that motivated it, and
:attr:`PolicyDecision.matched` reports which words fired — so a surprising
verdict is one grep away from an explanation.

The cost is honest and stated: this is a **narrow** classifier. It will call
some health facts ``other`` (which asks — safe) and it will not understand
paraphrase. It never fails *open* on the sensitive side by design: the
sensitive lists are checked FIRST, so "my sister's blood pressure medication"
is ``health``, not ``name``, even though it contains a relative.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

#: Categories the card admits without asking.
CATEGORY_NAME = "name"
CATEGORY_PREFERENCE = "preference"
CATEGORY_ROUTINE = "routine"
CATEGORY_PLACE = "place"

#: Categories the card says to ask about first.
CATEGORY_HEALTH = "health"
CATEGORY_FINANCE = "finance"
CATEGORY_THIRD_PARTY = "third_party_secret"

#: Everything the word lists did not recognise. Asks; see the module docstring.
CATEGORY_OTHER = "other"

#: The one refusal. See the module docstring for why it is not an "ask".
CATEGORY_SECRET = "secret"

CATEGORIES: frozenset[str] = frozenset(
    {
        CATEGORY_NAME,
        CATEGORY_PREFERENCE,
        CATEGORY_ROUTINE,
        CATEGORY_PLACE,
        CATEGORY_HEALTH,
        CATEGORY_FINANCE,
        CATEGORY_THIRD_PARTY,
        CATEGORY_OTHER,
        CATEGORY_SECRET,
    }
)

KEEP_CATEGORIES: frozenset[str] = frozenset(
    {CATEGORY_NAME, CATEGORY_PREFERENCE, CATEGORY_ROUTINE, CATEGORY_PLACE}
)
ASK_CATEGORIES: frozenset[str] = frozenset(
    {CATEGORY_HEALTH, CATEGORY_FINANCE, CATEGORY_THIRD_PARTY, CATEGORY_OTHER}
)
REFUSE_CATEGORIES: frozenset[str] = frozenset({CATEGORY_SECRET})

#: What the policy decided to do about the proposal.
DISPOSITION_KEEP = "keep"
DISPOSITION_ASK = "ask"
DISPOSITION_REFUSE = "refuse"
DISPOSITIONS: frozenset[str] = frozenset(
    {DISPOSITION_KEEP, DISPOSITION_ASK, DISPOSITION_REFUSE}
)

#: The consent state a row carries when it is written. ``pending`` rows exist on
#: disk — the ask is a *record*, not a discard — but never render and never
#: appear in an answer until the owner grants them.
CONSENT_GRANTED = "granted"
CONSENT_PENDING = "pending"
CONSENT_DENIED = "denied"
CONSENT_STATES: frozenset[str] = frozenset(
    {CONSENT_GRANTED, CONSENT_PENDING, CONSENT_DENIED}
)

#: The longest fact this policy will look at. A "fact" longer than this is a
#: transcript, and a transcript is what ``messages`` is for.
MAX_FACT_CHARS = 400


def _words(text: str) -> frozenset[str]:
    return frozenset(re.findall(r"[a-z0-9']+", text.lower()))


# --- the word lists, each with the sentence that put it there ------------------

#: Credentials. The refusal. Deliberately short: every entry is a thing whose
#: presence in a plaintext file read aloud by a robot is the harm.
SECRET_TERMS: frozenset[str] = frozenset(
    {
        "password",
        "passwords",
        "passcode",
        "passphrase",
        "pin",
        "otp",
        "2fa",
        "cvv",
        "ssn",
        "api",
        "apikey",
        "token",
        "credentials",
        "credential",
        "login",
    }
)

#: Health. "Ask first" in the card's own words.
HEALTH_TERMS: frozenset[str] = frozenset(
    {
        "medication",
        "medications",
        "meds",
        "prescription",
        "prescribed",
        "diagnosis",
        "diagnosed",
        "doctor",
        "physician",
        "therapist",
        "therapy",
        "surgery",
        "cancer",
        "diabetes",
        "diabetic",
        "depression",
        "depressed",
        "anxiety",
        "disorder",
        "illness",
        "disease",
        "symptom",
        "symptoms",
        "hospital",
        "clinic",
        "blood",
        "pressure",
        "insulin",
        "allergic",
        "allergy",
        "pregnant",
        "pregnancy",
        "hiv",
        "seizure",
        "seizures",
    }
)

#: Finances.
FINANCE_TERMS: frozenset[str] = frozenset(
    {
        "salary",
        "salaries",
        "income",
        "wage",
        "bank",
        "iban",
        "mortgage",
        "loan",
        "loans",
        "debt",
        "debts",
        "credit",
        "card",
        "account",
        "savings",
        "investment",
        "investments",
        "tax",
        "taxes",
        "bankrupt",
        "bankruptcy",
        "rent",
        "paycheck",
        "pension",
        "networth",
    }
)

#: Third-party secrets: something the owner told the robot ABOUT someone else,
#: in confidence. The marker is the confidence word, not the third party — "my
#: sister is called Hana" is a name and must stay one.
THIRD_PARTY_MARKERS: frozenset[str] = frozenset(
    {
        "secret",
        "secretly",
        "confidential",
        "confidence",
        "affair",
        "cheating",
        "fired",
        "divorce",
        "divorcing",
        "arrested",
        "rehab",
        "don't tell",
        "dont tell",
        "keep it between",
        "between us",
        "nobody knows",
        "no one knows",
    }
)

#: The relatives/people vocabulary that makes a third-party marker *about*
#: somebody else rather than about the owner.
THIRD_PARTY_SUBJECTS: frozenset[str] = frozenset(
    {
        "sister",
        "brother",
        "mother",
        "mom",
        "father",
        "dad",
        "wife",
        "husband",
        "partner",
        "friend",
        "cousin",
        "neighbour",
        "neighbor",
        "colleague",
        "boss",
        "roommate",
        "aunt",
        "uncle",
        "son",
        "daughter",
    }
)

#: Names. The card's first example is literally "my sister's name is …".
NAME_MARKERS: frozenset[str] = frozenset(
    {"name", "named", "called", "call"}
)
NAME_SUBJECTS: frozenset[str] = THIRD_PARTY_SUBJECTS | frozenset(
    {"cat", "dog", "pet", "robot", "me", "i", "my"}
)

#: Preferences. "A stated preference recalled unprompted" is probe row 2.
PREFERENCE_TERMS: frozenset[str] = frozenset(
    {
        "like",
        "likes",
        "liked",
        "love",
        "loves",
        "prefer",
        "prefers",
        "preferred",
        "preference",
        "favourite",
        "favorite",
        "hate",
        "hates",
        "dislike",
        "dislikes",
        "enjoy",
        "enjoys",
        "rather",
        "please",
        "annoys",
        "annoying",
    }
)

#: Routines. Time-of-day and cadence words: the shape of a habit.
ROUTINE_TERMS: frozenset[str] = frozenset(
    {
        "always",
        "usually",
        "every",
        "each",
        "morning",
        "mornings",
        "evening",
        "evenings",
        "night",
        "nights",
        "weekday",
        "weekdays",
        "weekend",
        "weekends",
        "monday",
        "tuesday",
        "wednesday",
        "thursday",
        "friday",
        "saturday",
        "sunday",
        "daily",
        "weekly",
        "routine",
        "habit",
        "schedule",
        "before",
        "after",
        "walks",
        "commute",
    }
)

#: Places. The spatial half of the owner model; the semantic map owns the
#: geometry, this owns the fact that the owner CALLS it that.
PLACE_TERMS: frozenset[str] = frozenset(
    {
        "lives",
        "live",
        "home",
        "house",
        "apartment",
        "flat",
        "street",
        "avenue",
        "road",
        "neighbourhood",
        "neighborhood",
        "city",
        "town",
        "office",
        "work",
        "park",
        "cafe",
        "coffee",
        "gym",
        "school",
        "campus",
        "building",
        "floor",
        "room",
        "kitchen",
        "bedroom",
        "garden",
        "yard",
        "desk",
    }
)


@dataclass(frozen=True)
class PolicyDecision:
    """What the policy decided, and enough of why to answer an owner.

    :attr:`consent` is what the store row gets. It is derived from
    :attr:`disposition` in exactly one place (:func:`decide`) so a caller cannot
    invent a fourth combination — a ``keep`` is always ``granted``, an ``ask``
    is always ``pending``, and a ``refuse`` never reaches the store at all.
    """

    category: str
    disposition: str
    consent: str
    reason: str
    matched: tuple[str, ...] = ()

    @property
    def storable(self) -> bool:
        """May a row be written at all? (``ask`` writes a PENDING row.)"""

        return self.disposition in {DISPOSITION_KEEP, DISPOSITION_ASK}

    @property
    def renderable(self) -> bool:
        """May this reach the model's developer instruction or an answer?"""

        return self.disposition == DISPOSITION_KEEP

    def as_dict(self) -> dict[str, object]:
        return {
            "category": self.category,
            "disposition": self.disposition,
            "consent": self.consent,
            "reason": self.reason,
            "matched": list(self.matched),
        }


_CONSENT_BY_DISPOSITION = {
    DISPOSITION_KEEP: CONSENT_GRANTED,
    DISPOSITION_ASK: CONSENT_PENDING,
    DISPOSITION_REFUSE: CONSENT_DENIED,
}


def _hit(terms: frozenset[str], words: frozenset[str]) -> tuple[str, ...]:
    return tuple(sorted(terms & words))


def _phrase_hit(markers: frozenset[str], text: str) -> tuple[str, ...]:
    lowered = text.lower()
    return tuple(sorted(m for m in markers if " " in m and m in lowered))


def classify(text: str) -> tuple[str, tuple[str, ...]]:
    """The category of one proposed fact, and the words that decided it.

    ORDER IS THE POLICY. Sensitive classes are tested before permissive ones, so
    a sentence that is both ("my sister's medication") lands on the cautious
    side. Reordering these blocks changes the guarantee, which is why they are
    written out longhand instead of iterated over a registry.
    """

    words = _words(text)

    secret = _hit(SECRET_TERMS, words)
    if secret:
        return CATEGORY_SECRET, secret

    health = _hit(HEALTH_TERMS, words)
    if health:
        return CATEGORY_HEALTH, health

    finance = _hit(FINANCE_TERMS, words)
    if finance:
        return CATEGORY_FINANCE, finance

    third_party = _hit(THIRD_PARTY_MARKERS, words) + _phrase_hit(THIRD_PARTY_MARKERS, text)
    if third_party and (_hit(THIRD_PARTY_SUBJECTS, words) or _phrase_hit(THIRD_PARTY_MARKERS, text)):
        return CATEGORY_THIRD_PARTY, tuple(sorted(set(third_party)))

    name = _hit(NAME_MARKERS, words)
    if name and _hit(NAME_SUBJECTS, words):
        return CATEGORY_NAME, tuple(sorted(set(name + _hit(NAME_SUBJECTS, words))))

    preference = _hit(PREFERENCE_TERMS, words)
    if preference:
        return CATEGORY_PREFERENCE, preference

    routine = _hit(ROUTINE_TERMS, words)
    if routine:
        return CATEGORY_ROUTINE, routine

    place = _hit(PLACE_TERMS, words)
    if place:
        return CATEGORY_PLACE, place

    return CATEGORY_OTHER, ()


def decide(text: str) -> PolicyDecision:
    """Classify one proposed fact and say what happens to it.

    The only function in this module a caller should need. Empty or oversized
    text is refused here rather than at the store, so every store row that
    exists went past this function.
    """

    clean = " ".join(str(text or "").split())
    if not clean:
        return PolicyDecision(
            category=CATEGORY_OTHER,
            disposition=DISPOSITION_REFUSE,
            consent=CONSENT_DENIED,
            reason="an empty fact is not a fact",
        )
    if len(clean) > MAX_FACT_CHARS:
        return PolicyDecision(
            category=CATEGORY_OTHER,
            disposition=DISPOSITION_REFUSE,
            consent=CONSENT_DENIED,
            reason=(
                f"a fact longer than {MAX_FACT_CHARS} characters is a transcript, "
                "and the conversation log already keeps those"
            ),
        )

    category, matched = classify(clean)
    if category in REFUSE_CATEGORIES:
        return PolicyDecision(
            category=category,
            disposition=DISPOSITION_REFUSE,
            consent=CONSENT_DENIED,
            reason=(
                "this looks like a credential, and the owner-fact store is a "
                "plaintext file the robot reads out loud; it is never the right "
                "place for one"
            ),
            matched=matched,
        )
    if category in ASK_CATEGORIES:
        reason = (
            f"{category.replace('_', ' ')} is something to ask about before keeping"
            if category != CATEGORY_OTHER
            else "nothing in this matches a category the owner has already agreed to keep"
        )
        return PolicyDecision(
            category=category,
            disposition=DISPOSITION_ASK,
            consent=CONSENT_PENDING,
            reason=reason,
            matched=matched,
        )
    return PolicyDecision(
        category=category,
        disposition=DISPOSITION_KEEP,
        consent=_CONSENT_BY_DISPOSITION[DISPOSITION_KEEP],
        reason=f"{category} facts are the ones the owner agreed the robot may keep",
        matched=matched,
    )


__all__ = [
    "ASK_CATEGORIES",
    "CATEGORIES",
    "CATEGORY_FINANCE",
    "CATEGORY_HEALTH",
    "CATEGORY_NAME",
    "CATEGORY_OTHER",
    "CATEGORY_PLACE",
    "CATEGORY_PREFERENCE",
    "CATEGORY_ROUTINE",
    "CATEGORY_SECRET",
    "CATEGORY_THIRD_PARTY",
    "CONSENT_DENIED",
    "CONSENT_GRANTED",
    "CONSENT_PENDING",
    "CONSENT_STATES",
    "DISPOSITIONS",
    "DISPOSITION_ASK",
    "DISPOSITION_KEEP",
    "DISPOSITION_REFUSE",
    "KEEP_CATEGORIES",
    "MAX_FACT_CHARS",
    "REFUSE_CATEGORIES",
    "PolicyDecision",
    "classify",
    "decide",
]
