"""Seeded-regression pytest plugin for the CI-gate self-test (model-off lane).

Mirrors ``scripts/mutation_panel.py``'s discipline: a regression is injected by
**monkeypatching a live object at runtime — never a committed source edit**. The
gate runner loads this plugin (``-p scripts.ci_selftest_seed``) only when it is
proving that a hard gate is not theatre, selecting the seed with the
``CI_GATE_SEED`` environment variable. In a normal run the env var is unset and
the plugin is inert.

Seeds
-----
``flag_off_drift``
    The Design-A model-OFF guarantee is that the SigLIP-2 string/alias fallback
    (weights absent / flag off) is byte-identical to the frozen pre-neural
    oracle. This seed drifts that fallback — ``SigLIP2Matcher.match`` returns a
    perturbed label — so every ``model-off byte-equal`` cell that compares the
    fallback to the oracle must go red. If it does, the model-off gate catches
    its class; if the suite stays green, the gate is blind and the self-test
    fails loudly.
"""

from __future__ import annotations

import dataclasses
import os
from typing import Any

_SEED = os.environ.get("CI_GATE_SEED", "").strip()

# Keep the started patcher alive for the whole session.
_ACTIVE: list[Any] = []


def _install_flag_off_drift() -> None:
    """Perturb the SigLIP-2 model-OFF fallback so byte-equality must fail."""

    from parcel_robot.instructnav import siglip

    original = siglip.SigLIP2Matcher.match

    def drifted(self, query, labels, *args, **kwargs):  # type: ignore[no-untyped-def]
        result = original(self, query, labels, *args, **kwargs)
        if result is None:
            return result
        try:
            return dataclasses.replace(result, label=f"{result.label}__DRIFT")
        except Exception:  # noqa: BLE001 - any drift that changes bytes is fine
            return result

    siglip.SigLIP2Matcher.match = drifted  # type: ignore[method-assign]
    _ACTIVE.append((siglip.SigLIP2Matcher, "match", original))


_SEEDS = {
    "flag_off_drift": _install_flag_off_drift,
}


def pytest_configure(config: object) -> None:  # pytest hook signature (config unused)
    del config
    installer = _SEEDS.get(_SEED)
    if installer is not None:
        installer()


def pytest_unconfigure(config: object) -> None:  # pytest hook signature (config unused)
    del config
    while _ACTIVE:
        target, attribute, original = _ACTIVE.pop()
        setattr(target, attribute, original)
