# M1-0 GATEWAY — executor status (Opus) · 2026-08-24

**Card:** `IMPLEMENTATION_PLAN.md` row A1 — the co-located final governor +
native sole-writer gateway as its own process, against `bridge/protocol.py` V1
and `bridge/fake_sport.py`, bench only.
**Delivered:** `gateway/` (new top-level package, 10 deployable modules + 2
bench modules) and `tests/test_m1_0_gateway.py` — 135 tests: 134 in the default
gate, plus the ten-minute soak behind `-m slow`.
**Git:** read-only. Nothing staged, nothing committed. `gateway/` and the test
file are untracked.
**Not touched:** `src/parcel_robot/**`, `bridge/**` product files, `:8765`,
`/tmp/parcel_sim.sock`, `:8080`, `parcel_memory.sqlite3`.

## What exists

| file | what it owns |
|---|---|
| `gateway/ports.py` | the whole vendor surface, as a structural `Protocol`; validated sample copy. **No vendor SDK anywhere in the tree.** |
| `gateway/limits.py` | mirrored TTL/timing/speed constants, each with its source; `GovernorLimitsV1`; the three regimes mirroring `bridge/timing.py` |
| `gateway/catalog.py` | the versioned action allowlist (one admitted action: bounded base velocity), the named refusal list, pinned structure digest. **It is on the control path:** the governor clamps to the admitted action's bounds, and an axis the action does not declare is zeroed |
| `gateway/governor.py` | HLD §8.8 lattice `PASS<CLAMP<HOLD<STOP<LATCHED_STOP`; catalog admission then clamp to *that action's* declared bounds; **the X12 veto** — a shaped result larger in magnitude or sign-flipped is thrown away for a latched exact-zero stop |
| `gateway/audit.py` | the bounded ring: fixed capacity, drops counted, **no callback of any kind inside `record`** |
| `gateway/credentials.py` | `SO_PEERCRED` peer identity + writer allowlist + contract-hash equality = the one authenticated lease |
| `gateway/writer.py` | one vendor writer thread, one slot, latest-wins; stop-epoch and deadline re-checked on the writer thread immediately before the vendor call |
| `gateway/core.py` | boot epoch, restart-DISARMED, boot StopMove, lease, monotonic sequence fence, receiver-derived TTL + watchdog, freshness revalidation, stop dominance, stationary witness, latch-by-default |
| `gateway/server.py` | `AF_UNIX`/`SOCK_SEQPACKET`, socket mode `0600`, peer check before parsing, decoder faults ⇒ latched stop |
| `gateway/process.py`, `gateway/bench_client.py` | bench wiring and the SIGKILL subject (the only two modules that may reach the fake vendor) |

Runs on **real CPython 3.10.21** (`~/.local/bin/python3.10`): `py_compile`
clean, all ten deployable modules import, and the full process + bench client
were driven end-to-end on 3.10 (vendor log ends `move_applied … →
stop_move_succeeded`, audit `client_disconnected / stationary_confirmed True`).

## Invariants proven (frozen manifest `gateway_invariants_v1.json`)

Every GWI has named cases; `test_every_frozen_fault_seed_and_invariant_has_a_named_case_in_this_file`
fails if the mapping and the frozen manifests ever diverge.

| id | proven by |
|---|---|
| GWI-001 new epoch per boot, starts DISARMED | boot test; 4-boot epoch uniqueness; process restart |
| GWI-002 prior epoch never holds authority | acquire refused `boot_epoch_mismatch`; command ⇒ latched exact-zero stop |
| GWI-003 one writer; conflict stops+latches | second writer ⇒ `writer_conflict` latched stop; writer outside the allowlist refused |
| GWI-004 sequences increase across the whole boot | regressed command ⇒ latched stop; captured acquire cannot replay after client death |
| GWI-005 only a duration crosses the wire | field scan of `GatewayCommandV1`; expiry on the receiver's own clock; **the gateway's own watchdog thread fires with no tick from the test** |
| GWI-006 client loss ⇒ local StopMove, no auto-resume | in-process + the `SIGKILL` subprocess |
| GWI-007 lease loss / stale / out-of-order ⇒ stop | three separate cases + a frozen-stream case the fixture cannot produce |
| GWI-008 late Move across a stop epoch ⇒ compensating stop | `move_delay_s` crossing a client death; `move_no_reply` stall |
| GWI-009 version/bounds/frame/finite/hash fail closed | 8 malformed packet shapes at the decoder + the same bytes over the real socket |
| GWI-010 an ACK is never motion truth | ACK returns while the vendor call is still in flight; `ack_scope` cannot be forged |
| GWI-011 confirmation needs StopMove + a fresh later stationary sample | `stop_move_failure` ⇒ unconfirmed, latched, retried; the DTO itself refuses the impossible combination |
| GWI-012 evidence can be lost; control cannot change | full ring vs roomy ring produce byte-identical stop fields; failing exporter ⇒ nonzero evidence exit |

Beyond the manifest, proven here: the governor never originates or increases
motion (729-point sign/scale sweep plus a deliberately broken shaper that is
vetoed into a latched stop); arming alone commands nothing; the value that
reaches the vendor is the **clamped** one; a stop is never refused (from a
stranger or on a replayed sequence it is honoured **and** latches); an
unclassified cause latches by default; a peer outside the uid allowlist never
reaches the protocol layer.

## Fault table — every seed in `gateway_fault_seeds_v1.json`

| seed | fault | observed | phase after |
|---|---|---|---|
| GWF-001 | prior boot epoch | acquire rejected `boot_epoch_mismatch`, nothing moved; on a command ⇒ exact-zero stop | DISARMED / LATCHED |
| GWF-002 | duplicate / regressed sequence | `client_sequence_not_increasing`; exact-zero stop on the command path, refusal on reacquire | LATCHED |
| GWF-003 | bool / zero / over-cap TTL | refused at the DTO (0, 351, `True`, 1.5) | n/a |
| GWF-004 | NaN / inf / bool velocity | refused at the DTO | n/a |
| GWF-005 | wrong body frame | refused at the DTO | n/a |
| GWF-006 | contract hash mismatch | command ⇒ exact-zero stop; acquire ⇒ refusal | LATCHED |
| GWF-007 | `SIGKILL` client after nonzero | subprocess: last vendor action `stop_move_succeeded`, `stationary_confirmed=True`, state query reads `(0,0,0)`, replay refused | DISARMED |
| GWF-008 | delayed Move crosses a stop epoch | `late_move_completion_compensation` — the late Move is followed by a compensating StopMove | DISARMED |
| GWF-009 | Move applies then never replies | `vendor_write_stalled` from the watchdog while the writer thread is still wedged in the vendor call | LATCHED |
| GWF-010 | stale state | `state_stale`; StopMove succeeded, stillness **not** witnessable ⇒ honestly unconfirmed | LATCHED |
| GWF-011 | out-of-order state | `state_out_of_order` / `state_frozen` (see protocol question 8) | LATCHED |
| GWF-012 | Sport lease loss | `sport_lease_lost`, exact zero | DISARMED |
| GWF-013 | second writer | `writer_conflict`, exact zero, and the latched gateway re-arms for nobody | LATCHED |
| GWF-014 | StopMove failure | `stop_rpc_completed=False`, `stationary_confirmed=False`, `state_sequence=0`, ≥2 retries inside the stop budget | LATCHED |
| GWF-015 | gateway restart | new epoch, DISARMED, prior epoch refused; **and** a second core over a still-moving vendor zeroes it at boot | DISARMED |
| GWF-016 | oversize / overlong / unknown version | 8 shapes refused at the decoder; injected raw over the socket ⇒ exact-zero latched stop | LATCHED |
| GWF-017 | ACK misread as motion truth | ACK is `gateway_admission` and arrives while the vendor is still at zero | ARMED |
| GWF-018 | TTL reaches receiver-local expiry | `local_ttl_expired`, exact zero, **not** latched, no auto-resume | DISARMED |
| GWF-019 | evidence sink blocks / raises / loses | identical stop fields with a 2-record ring; hostile `__repr__` coerced not raised; failing exporter ⇒ exit code 2 | — |

**Headline rows are also driven over the wire, not only through the core API.**
The verifier lesson in this project's audit notes (a seed proves a guard, not an
integration) applies to this card too: TTL expiry, prior-boot-epoch command,
second-writer conflict, malformed bytes, a client-sent response kind, a full
move/stop session and the two subprocess cases all run through the real
`SOCK_SEQPACKET` server and the frozen DTOs, and assert the same postcondition
— vendor at exact zero, last vendor action a stop, no auto-resume.

**The card's loss-class list is also driven as one table**
(`test_every_loss_class_ends_with_the_vendor_at_exact_zero`, 15 in-process
classes + 2 subprocess): for each, the vendor is at exact `(0.0, 0.0, 0.0)`,
the **last** vendor action is a stop, no lease is held, and the next command is
refused.

## Deliberate divergences from `bridge/fake_gateway.py`

The fake is the N24 test double; this is the reference process. Where they
differ, this one is stricter, and each difference is a test:

1. **Boot StopMove.** A fresh core's first act is an exact-zero StopMove with a
   stationary witness, before any socket exists. The fake has none, so a
   restart over a moving vendor would leave it moving.
2. **A stop is never refused.** The fake refuses `explicit_stop` while
   disarmed. Here a stop from any admitted peer always reaches the vendor; it
   latches when it comes from a non-lease connection, a replayed sequence, or
   `emergency`.
3. **One vendor writer thread**, one slot, latest-wins — not a thread per Move
   — with the stop epoch and the deadline re-checked on that thread
   immediately before the vendor call, so **no Move is ever issued past its
   TTL**. Adds `vendor_write_stalled`, which is what actually catches GWF-009.
4. **Feedback rule.** The fake requires the state sequence to advance on every
   poll, which a real periodic stream polled at 50 Hz would fail. Here:
   regression ⇒ `state_out_of_order`; failure to advance within
   `state_timeout_s` ⇒ `state_frozen`; both latch.
5. **Authentication.** `SO_PEERCRED` + writer allowlist + hash equality, and a
   `0600` socket. The fake has no notion of a peer.
6. **Latch-by-default.** `_should_latch` names the eight recoverable causes;
   anything else — including a cause a future card adds — latches.

## Two scope notes on HLD §8.8

- **There is no comfort/slew shaper in M1-0.** §8.8 allows one but requires
  that it never weaken a ceiling and that "exact zero remains exact zero at the
  vendor write". Having none satisfies both trivially: the number the governor
  produced is the number the vendor is given. If a shaper is added later, the
  enforcement point already exists — `FinalGovernorV1._veto_only` runs after
  whatever shaping happens and throws away any result that grew or flipped sign.
- **`GatewayActionV1`'s "mutually exclusive with incompatible base motion"
  clause is not implemented** because the action path is not reachable (see
  protocol question 3). The catalog carries the `excludes_base_motion` /
  `requires_base_stationary` flags so the rule has somewhere to live.

## Soak

`test_a_ten_minute_soak_at_50hz_holds_the_ttl_contract` — the product's own
server behind a real `SOCK_SEQPACKET` socket, a client issuing a fresh
`GatewayCommandV1` every 20 ms for 600 s with `local_ttl_ms=350`, then silence
so the watchdog has to end it. Run on the delivered tree, `-m slow -s`:

| row | value |
|---|---|
| duration | 600.0 s, 50 Hz |
| commands sent / vendor writes applied | **30 000 / 30 000** |
| **TTL deadline violations** | **0** — no vendor write landed at or after its derived deadline |
| writes refused by the writer's last-instant gates | 0 |
| setpoints superseded in the one-slot mailbox | 0 |
| stops during the soak | **0** (the boot stop is the only entry in the stop sequence) |
| **command→vendor latency** | p50 **0.389 ms**, p95 **0.605 ms**, **p99 0.667 ms**, max 8.69 ms, mean 0.401 ms (n = 30 000) |
| watchdog wake interval (period 20 ms) | p50 20.13 ms, p95 20.20 ms, p99 **20.51 ms**, max 23.93 ms (n = 29 806) — i.e. **p99 scheduling jitter ≈ 0.51 ms** |
| stop after the last command | **0.341 s**, reason `local_ttl_expired`, vendor at exact zero |

"Command→vendor latency" is measured in one process, from the client's
`sendall` to the instant the vendor `Move` returned, so both stamps come from
one monotonic clock. An earlier identical run of the same soak, taken before
the catalog-clamp refactor, gave p99 0.698 ms / 0 violations / 0 stops — the
numbers above are the ones from the tree as delivered.

**Zero deadline violations is enforced, not just observed.** `gateway/writer.py`
re-checks the stop epoch and the receiver-derived deadline on the writer thread
immediately before the vendor call; either gate closing means no `Move` is
issued at all. The soak's assertion checks the applied timestamps independently.

**These are desktop numbers.** A 192-core x86 dev box inside a 40 GB pytest
cgroup, against a Python fake. `bridge/timing.py`'s 2.0 ms p99 scheduling-jitter
row is a *target-compute* budget and nothing here gates on it; the Orin's
numbers are unknown until box day.

**Handoff to the integrator:** the ten-minute soak is marked `slow` **and**
`load_sensitive`, so it is out of the commit tier and self-skips under machine
contention — but a nightly `-m slow` run will spend ~10 minutes on it. Set
`PARCEL_M1_0_SOAK_S` to shorten it there; the short soak
(`test_a_short_soak_at_50hz_holds_the_ttl_contract`, 5 s) carries the same
assertions in the default gate.

## Protocol questions (recorded, not changed — `bridge/` was not touched)

1. **V1 carries no credential, token or nonce.** Authentication here is
   composed from `SO_PEERCRED` + the writer allowlist + `GatewayHashesV1`
   equality. Replay *within a boot* is defeated by the sequence fence, but a
   same-uid process can acquire whenever the lease is free. A challenge/response
   needs a V2 message.
2. **`GatewayHelloV1` publishes `required_hashes`**, so a client learns them
   from the gateway and echoes them back. The hashes are a *compatibility
   identity*, not a secret (protocol.py says as much) — worth stating because
   this process leans on them for admission.
3. **`GatewayActionV1` does not exist in V1.** HLD §8.8 requires the
   allowlisted posture/gesture catalog; it is implemented gateway-side and is
   unreachable from the wire. Adding the message is a V2 decision.
4. **The gateway cannot push.** Every response is a reply. A watchdog-initiated
   stop (TTL expiry, lease loss, stale feedback) produces a `GatewayStopReportV1`
   the client never receives until it next queries state. For a product client
   that must know it lost authority, V2 needs either an unsolicited
   `stop_report` or a client-side heartbeat.
5. **`GatewayAckV1` has no disposition-detail field.** A clamped-but-accepted
   command is signalled by putting `"clamped"` in `reason`. V2 should carry the
   governor disposition explicitly.
6. **`GatewayStopReportV1.reason` is a 160-char free string.** Composite causes
   (`protocol_fault:<decoder message>`) are truncated. A typed cause enum plus a
   free-text detail would make the reports machine-classifiable.
7. **`GatewayStateV1.state_sequence` has minimum 1**, so a vendor that has
   published no sample cannot be represented; this process maps 0 → 1.
8. **Fixture behaviour, not contract:** `FakeSportServiceV1.state()` skips
   `_advance_state_locked()` whenever *either* `stale_state_by_s` or
   `out_of_order_state` is set, so both faults also freeze the sequence. After a
   healthy poll the seeded out-of-order value is `_sequence - 1`, which is not
   below the last *observed* value once a Move has advanced it — so GWF-011
   lands as `state_frozen` on the seeded path. A genuine regression is proven
   separately with a wrapper port (`state_out_of_order`).
9. **Fixture behaviour:** `stop_move` with `stop_move_failure` returns `False`
   **without zeroing** the velocity, so GWF-014 cannot claim "exact zero at the
   vendor". What is proven is exact-zero *commanded*, retried, honestly reported
   unconfirmed, and latched.

## Verification run

- `env -u TMPDIR ~/.cache/parcel-guard/pytest_guard.sh --label m1-0 .parcel/bin/python -m pytest tests/test_m1_0_gateway.py -m "not slow"` — **134 passed, ×3 consecutive runs on the delivered tree**, ~10.3 s each. Never `-n auto`; `ci_gate --tier` was not run (that is the integrator's).
- The soak above (`-m slow`), run twice — once mid-card and once on the final tree.
- `ruff check .` fingerprints: **zero** from `gateway/**` or
  `tests/test_m1_0_gateway.py`; **zero `noqa` in either.** (One unrelated new
  fingerprint exists in the tree from another session:
  `research/20260823/search-before-refuse/runtime_probe.py::F401` — not this
  card's, and `research/**` is outside its OWNS.)
- DEC ratchets re-run, not assumed: `tests/test_dec0_debt_ratchet.py` +
  `tests/test_decig2_import_ratchet.py` — 23 passed. `gateway/` is outside both
  scans (`DEC-0 SCOPED_DIRS = src/parcel_robot, scripts, tools`;
  `DEC-IG-2 SCAN_DIRS` has no `gateway`); `tests/` **is** in DEC-IG-2's scan and
  the new test file passes it.
- Neighbouring suites unchanged: `test_fake_sport_gateway.py`,
  `test_gateway_protocol_v1.py`, `test_gateway_process.py`,
  `test_hw1_py310_clean.py` — 71 passed.
- `tools/codebase_index.py --check` reports STALE, from other sessions' tracked
  changes: the index is built from `git ls-files` and this card added only
  untracked files.

## Does not prove

Nothing physical, and nothing about the product.

- **No robot, no vendor SDK, no firmware.** `FakeSportServiceV1` models the
  high-level effects the gateway must react to. It is not a Go2, and "exact zero
  at the vendor" here means "exact zero in the fake's state", not a standing dog.
- **No stopping distance and no stop envelope.** The TTL contract proven is the
  gateway's own deadline discipline. Braking latency, `localization_jump_m`,
  and the HLD §8.8 envelope terms remain `UNMEASURED` and box-day.
- **No independent operator stop.** The A5 row (≤ 0.5 m / ≤ 500 ms at 0.3 m/s)
  is untouched by this card.
- **Desktop timing only.** Latency and jitter are from a 192-core x86 dev box
  under a pytest cgroup. The Orin's numbers are unknown; the `bridge/timing.py`
  2.0 ms p99 scheduling-jitter target is a *target-compute* row and nothing here
  gates on it.
- **Not wired to `RobotRuntime`.** Deliberately: no `src/parcel_robot` change,
  no product caller. Until that card lands, no runtime seam reaches this
  process, and none of these guarantees are in the product's path.
- **Not a certification claim** (HLD §8.8's own words). It is a software
  isolation boundary that has been exercised against seeded faults.
- **`--sport vendor` is unimplemented** and refuses to start rather than
  serving without a vendor writer.
- **Peer authentication is untested against a genuinely different uid** — this
  session has one uid. The refusal path is exercised by pointing the policy at a
  uid the connecting process does not have, which drives the same code.
