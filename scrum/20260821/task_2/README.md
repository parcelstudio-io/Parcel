# Task 2 — R23: limits that refuse (fail-closed SafetyLimits)

**Executor:** Claude Opus (agent) · **Auditor:** Fable (deferred)
**Trigger:** full-audit CONFIRMED-PARTIAL major (§Safety-2): `robot.yaml`
velocity limits are not fail-closed. `ConfigStore.safety_limits()` does bare
`float()` with no finiteness/range check and `SafetyLimits` has no
validation, so **NaN silently disables the velocity clamp in BOTH
enforcement sites** (`abs(v) > NaN` is always False — arbiter and
SafetySupervisor alike), and inf/zero/negative are accepted without
complaint. PARTIAL only because the shipped config is digest-pinned; any
operator `--config` path (accepted by `web_panel.py`) is exposed. The repo's
own doctrine — stated in `realtime/config.py` and applied strictly to the
realtime block and the safety section — says this loader must refuse.

## Work

1. **Validate at the boundary:** `SafetyLimits.__post_init__` (or the
   loader, executor's call — pin whichever in test) refuses non-finite
   (NaN/inf), non-positive, and non-numeric velocity/accel limits with a
   named, actionable error naming the offending key and value. Same
   treatment for any sibling numeric safety key that currently coerces
   bare.
2. **Audit the whole numeric config surface** for the same class: walk
   every `float()`/`int()` coercion reachable from a config load, list them
   in the status doc with verdicts (guarded / now guarded / benign), and
   fix every safety-relevant one. The deliverable is the enumeration, not
   just the one fix.
3. **Defense in depth at the comparison sites:** the arbiter and supervisor
   clamps should not silently pass on a non-finite limit even if validation
   is bypassed — make the comparison fail-closed (a non-finite limit clamps
   to zero / refuses the command) and pin it.
4. **The doctrine test:** one test asserting that every documented
   fail-closed loader in the repo (realtime config, robot.yaml safety block,
   velocity limits) refuses a malformed value — so the next numeric key
   added without validation reddens.

OWNS: `config.py`, `safety.py`, `core/arbiter.py` (fail-closed comparison
only — no threshold changes), tests, `R23_STATUS.md`.
MUST NOT TOUCH: `configs/robot.yaml` itself (digest-pinned — validation
must pass on it unchanged; if it does not, that is a card-stopping
finding), yield/person-stop thresholds, realtime package, evals. Standard
house rules.

## Definition of done

Gate green INCLUDING hard-safety (the frozen nav baseline must not move —
if validation changes any effective limit on the shipped config, stop and
report); ≥8 seeds RED (NaN accepted again at each site; inf; zero;
negative; the comparison-site fail-open restored; the doctrine test
deleted). Live proof: a scratch config with `max_vx: .nan` is REFUSED at
launch with a clear message rather than producing an unclamped robot.
`R23_STATUS.md` standard register with the full coercion enumeration.
