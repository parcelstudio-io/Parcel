# HW-FW `orin-firewall` — STATUS

**Card:** `README.md` · **Design:** `DESIGN.md` · **Registration:**
`PREREGISTRATION.md` (sha256 below) · **Executor:** Claude Opus, 2026-08-23,
wave 3b · **Verdict: COMPLETE.** **27 rows registered (P1-P16, N1, S1-S3,
R1-R7), 27 MET, 0 missed**; three declared deviations — two about how a row was
measured, one about a document's length. None about what a row asserts.

```
$ sha256sum scrum/20260822/task_43/{PREREGISTRATION,DESIGN}.md
80aeae189956a7c9f8e3f63265c75e056812145b57a60f69b1240a7df9250160  PREREGISTRATION.md
196478d2dd711edaec3fa4ae8e4f228ba819f16e2d4fa2bf52b9e6e22a11e152  DESIGN.md
```

Neither has been edited since it was written; the registration was complete
before the first row was measured.

## Headline

`docs/BOX_DAY.md` step B-fw used to say **"RULESET DOES NOT EXIST YET"** and
then asked the owner to type four `nft add` lines from a runbook cell. Those
rules lived in the kernel only, filtered inbound DDS not at all, and would have
been bypassed entirely by a bridge. The ruleset now exists
(`deploy/orin/nftables.conf`), persists across reboot (`nftables.service`),
closes all four gaps the HW-8 verifier listed, and is pinned by a 19-test
structural reader that needs no `nft` and no root. **Nothing was applied on this
desktop:** the only `nft` invocation used anywhere in this card is `nft -c`
(check-only), and `sudo` was never run.

The policy, one line per chain:

| Table / chain | Policy | What it says |
|---|---|---|
| `inet parcel` **input** | **drop** | `lo` first; the panel (8765) dropped on every non-`lo` interface above every accept; conntrack; ICMP/ICMPv6 incl. the four ND types; **ssh on `{$wanif,$lteif,$conif,$tsif}` and never on `$rnic`**; tailscale 41641; DHCPv4/v6 client; DDS 7400-7500 accepted only on `$rnic`; Livox 56100-56599 only on `$lnic`; a counted drop for DDS arriving anywhere else; a final counter |
| `inet parcel` **forward** | **drop** | one `counter` and **not one accept rule** — the robot LAN and the WAN are two worlds, whatever `ip_forward` says |
| `inet parcel` **output** | accept | `lo`; then four drops — 239.255.0.0/16 off `$rnic`, its IPv6 counterpart on the DDS ports, **unicast** DDS off `$rnic`, Livox control off `$lnic` |
| `bridge parcel_l2` **forward** | **drop** | one `counter`; the answer to bridged frames that skip `inet forward`, without touching `br_netfilter` globally |
| `containers.conf` (**not included**) | — | three accepts, each scoped to `$dockerif`, none naming `$rnic`/`$lnic`; enabling it is a dated owner decision |

## What changed

All new files; `deploy/orin/` did not exist before this card:

```
deploy/orin/nftables.conf       182 lines   df3b8bfc54a8806517232d240ebe5c03d12952849a5692a979f8f962d2416e21
deploy/orin/nftables.service     46 lines   ffdb79ce3686ce89ba697fa53a86b16773fa3cc04f1ed4418541ff02cfc34177
deploy/orin/containers.conf      35 lines   dbc5723c2207bdb55535fa0c763f8d53e5e6cf378c116c430cb3fde785e66e93
deploy/orin/README.md           132 lines   163dcfea645b9dae06416935357acb7b1939137ba600673406ab2d7a16d2490d
tests/test_hwfw_nftables.py     614 lines   8fb13c7cf5075ceb465f53f21348920974f19e511650b42bd704cebcc0dde122  (19 tests)
scrum/20260822/task_43/{DESIGN,PREREGISTRATION,HWFW_STATUS}.md
```

Edited: `docs/BOX_DAY.md`, **two hunks** (see D2) — the B-fw table row, and the
one bullet elsewhere that asserted the ruleset does not exist. Both carry an
`<!-- HW-FW -->` marker. `git status --porcelain` for this card is exactly:

```
?? deploy/orin/
?? docs/BOX_DAY.md          (HW-8's file, untracked in this wave; two hunks are mine)
?? scrum/20260822/task_43/
?? tests/test_hwfw_nftables.py
```

Nothing under `src/`, no ADR, no `deploy/compose.yaml`, no `deploy/docker/`,
no `docs/MOTION.md`.

## How it was verified

Every pytest ran through `~/.cache/parcel-guard/pytest_guard.sh --label hwfw`
with `env -u TMPDIR`, never `-n auto`. **9 guarded runs**, `guard.log:1163-1180`,
every START paired with an END, no rc 137. Pre-flight at first run: 230 GB
available, 0 pytest processes.

**Structural rows P1-P16** —
`env -u TMPDIR ~/.cache/parcel-guard/pytest_guard.sh --label hwfw .parcel/bin/python -m pytest tests/test_hwfw_nftables.py -q`
→ **19 passed in 0.23s** (17 pins + 2 tests of the tokenizer itself; a parser
nobody has tested is not evidence). All sixteen registered rows MET as written.

**N1 — `nft`'s own parser. MET.** `which nft` → `/usr/sbin/nft`, `nftables
v1.1.6`, so the row is LIVE, not SKIP. `nft -c -f deploy/orin/nftables.conf` →
**zero `deploy/orin/nftables.conf:<line>:<col>` diagnostics**; the only stderr
line is `netlink: Error: cache initialization failed: Operation not permitted`,
which is this user lacking `CAP_NET_ADMIN`, not a statement about the file. The
same for the enabled-include form (D1). Characterised before registering the
row: unprivileged `nft -c` **does** catch syntax errors, unknown identifiers
(`$undefinedvar`), unknown hooks and bad CIDRs — measured on four deliberate
mistakes — and **does not** reach anything that needs the kernel cache (module
presence, set types, jump targets). `nft -f` was never invoked; `nft add`,
`nft delete`, `nft flush`, `nft list` and `sudo` were never invoked.

**Seeds S1-S3 — RED on a scratch copy, never the working tree.**
`~/.cache/parcel-hwfw/scratch/` holds `tests/test_hwfw_nftables.py` +
`deploy/orin/`, sha256-identical to the tree at copy time (the test resolves the
ruleset from `Path(__file__).resolve().parents[1]`, so a scratch run reads the
scratch ruleset; verified by the control run below). Restored by sha256 after
each seed, `__pycache__` purged, control green either side.

| Seed | Edit to the scratch ruleset | Result |
|---|---|---|
| control | none | 19 passed |
| **S1** | `forward` chain `policy drop` → `policy accept` | **`test_p4_forward_policy_is_drop` FAILED**, 1 failed / 18 passed |
| **S2** | added `iifname $rnic oifname $wanif ct state established,related counter accept` to `forward` | **`test_p5_nothing_is_forwarded_from_the_robot_nic` FAILED**, 1 failed / 18 passed |
| **S3** | deleted the `iifname != $rnic udp dport $ddsports counter drop` rule | **`test_p8_inbound_dds_reaches_us_only_from_the_robot_nic` FAILED**, 1 failed / 18 passed |
| restore | byte-identical by sha256 | 19 passed |

**The finding inside S2:** `nft -c -f` on the *seeded* file returned **zero
diagnostics** — nft is perfectly happy to route the robot LAN onto Wi-Fi. Only
the structural test objects. That is the argument for this card having a test at
all, and it is what the verifier should reproduce first.

**Runbook rows R1-R7.** R1/R2/R3 MET (`grep -c 'DOES NOT EXIST YET'` → **0**;
the new row carries `nft -c -f`, `systemctl enable --now`, `nft list table inet
parcel`, the post-reboot re-check, the before-Q-link re-check, and the
second-shell rule). **R4 MET:** `wc -w < docs/BOX_DAY.md` → **2,494** against a
cap of 2,500 (2,491 before this card; the new row is 183 words against the old
row's 189). R5 MET: `.parcel/bin/ruff check` → *All checks passed*;
`ruff format --check` → *1 file already formatted*; `grep -c noqa` → **0**; no
line over 100 columns. R6 MET (the four paths above). R7 MET.

## What this does not prove

Not one packet is filtered by anything in this card until the owner runs
`nft -f` on the Orin. The rows prove the file says what the design says, that
nft's parser accepts it, and that the two load-bearing sentences cannot be
removed silently. They prove nothing about the L4T kernel (whether
`nf_tables_bridge` is even present — hence the check-before-load in the unit and
the README fallback), nothing about the real interface names (**every one is
UNCONFIRMED until B9 / Q-wire / B-con**), nothing about reboot behaviour on that
box, and nothing about the robot LAN being what the research says it is. A
firewall is also not authentication: pinning CycloneDDS itself to `$rnic`
(`CYCLONEDDS_URI` `<General><Interfaces>`) is the belt to this file's braces and
belongs to HW-2/HW-5.

## Deviations

* **D1 (N1's second half).** The row said "containers.conf prefixed with the
  main file's defines". `containers.conf` alone does not parse *by design* — it
  borrows `$wanif`/`$lteif` from its parent — so it was checked the way it is
  actually used: a copy of `nftables.conf` **outside the repo** with the opt-in
  `include` line enabled, pointing at the real `containers.conf`. Zero
  diagnostics. Stronger than the registered form; declared because it is not the
  registered form.
* **D2 (R1's command).** The row said `git diff -- docs/BOX_DAY.md` → one hunk.
  `docs/BOX_DAY.md` is **untracked** (`??`) — HW-8 created it in this same
  uncommitted wave — so that command is empty for any edit whatsoever. Measured
  instead by reconstructing the pre-edit file from the two verbatim passages
  captured before editing and diffing: the reconstruction reproduces the
  pre-edit `wc -w` of **2,491** exactly, and `diff -u` shows **exactly two
  hunks** (`@@ -67,7 +67,7 @@` and `@@ -174,9 +174,9 @@`). The registered
  threshold was one hunk; two are delivered, and the second is declared as a
  scope call, not an accident: the bullet under "Commands that do not exist yet"
  said `deploy/orin/nftables.conf` does not exist. Leaving it would have made the
  runbook contradict itself about this card's own deliverable. Both hunks are
  marked `<!-- HW-FW -->`.
* **D3 (DESIGN.md length).** 157 lines against a ≤ 150 target. The overage is
  the two tables — the ten variables with the box-day read that fills each, and
  the three product facts with their `file:symbol` — which are the part a
  verifier and an owner will actually use, and which prose would have made
  longer, not shorter.

## Owner-gated rows

Everything on the Orin. In order, from `deploy/orin/README.md`:

1. Fill the six interface `define`s from B9 / Q-wire / B-con.
2. `sudo nft -c -f deploy/orin/nftables.conf` — **check-only**. If it rejects
   `table bridge parcel_l2`, the L4T kernel has no `nf_tables_bridge`: comment
   that table out, record it, and treat the bridge hand-check as mandatory.
3. `sudo systemd-run --on-active=300 --unit=parcel-fw-rollback …` (the
   dead-man's switch), then `install` + `systemctl enable --now
   parcel-nftables`, then prove a **new** ssh connection works before cancelling
   the timer.
4. Save the §2 verification block to `hw/B_fw.txt`, and answer its four
   questions in writing (forward drop / ssh interface / no default route via
   `$rnic` / is anything bridged).
5. Re-check after the first reboot and again before Q-link.

## Handoffs

* **HO-FW-1 → HW-2 / HW-5 (or whoever owns the Orin's DDS config).** The
  ruleset confines DDS by port and interface; the belt is CycloneDDS itself
  bound to `$rnic` (`CYCLONEDDS_URI` → `<General><Interfaces>`).
  `control/unitree_sport.py:25-33` already takes `(domain_id, interface)` and
  `robot.yaml:128` still says `enp3s0` — on the Orin that placeholder becomes
  the same NIC this file calls `$rnic`. One name, two files, no cross-check
  today.
* **HO-FW-2 → the ticket owner (Q-con).** `$conif` is B-con's direct cable, and
  the input chain accepts ssh on it. If the spare RJ45 turns out to be
  **bridged** to 192.168.123.0/24, that accept faces the robot LAN. The support
  ticket's Q5d already asks the bridging question; the answer must reach
  `hw/B_fw.txt`, not just the ticket thread.
* **HO-FW-3 → the ADR 0001 / compose owner.** `forward policy drop` (and the
  `bridge` table) stops Docker bridge traffic on the Orin.
  `deploy/compose.yaml`'s `safety-control` is `network_mode: none` and needs
  nothing; the two stubs on `parcel_aux` do. `containers.conf` is written and
  parked, not enabled.
* **HO-FW-4 → the unknowns register (`task_39/UNKNOWNS_REGISTER.md`).** Q-wire's
  "blocks" column can now name what it blocks concretely: `$lnic` and the
  `$livoxports` confinement.

## What the verifier should look at first

1. **Reproduce S2.** Add a forward accept from `$rnic` to the scratch ruleset
   and run both `nft -c -f` (clean — nft does not care) and the test (`P5`
   reddens). If a weakened ruleset can pass this module, nothing else here
   matters.
2. **Read `chain input` for a lockout.** The accept set is
   `{$wanif, $lteif, $conif, $tsif}` on `tcp dport 22`. Ask whether an owner
   following `deploy/orin/README.md` §1 can be locked out of a box they can only
   reach over the network — the dead-man's timer is the answer I claim.
3. **Check the two `docs/BOX_DAY.md` hunks** against D2's reconstruction, and
   the word count (2,494 / 2,500).
4. **Challenge the `bridge parcel_l2` table** (DESIGN §e.1): is a second table
   in the bridge family the right call against `br_netfilter`, and is
   check-before-load enough to keep it from being a day-1 hazard?

---

# Correction pass — 2026-08-23 18:0x EDT

Against `~/.cache/parcel-verify/hwfw/VERDICT.md` (**HOLD**: H1, H2, F1-F5,
N1-N8). **All seven findings applied; the eight NOTEs applied or answered.**
22 further guarded runs (`guard.log:1181-1538`, every START paired, no rc 137);
tree read-only for git; `nft` used only as `-c -f`, only on files in
`deploy/orin/` and on copies under `/tmp`; no `sudo`, no `nft -f`, no `nft
add/delete/flush/list`, no interface or sysctl change.

**Test count: 19 → 24.** Rows: P1-P16 + **P16b, P17, P18, P19** + N1 (now with a
liveness proof) + 2 tokenizer self-tests.

## H1 — the lockout (`README.md` step 0.5)

The verifier is right and the rule-walk is right: research hardware fact 19 puts
the dog's external RJ45 **and both of the dock's** on 192.168.123.0/24, so
B-con's laptop cable can be a switch port behind the Orin's one robot NIC, and
the shipped ssh set excluded `$rnic`. A ruleset cannot decide that. A read can,
and it now happens **before** anything is loaded. `deploy/orin/README.md` §0.5,
verbatim in the load-bearing part:

> ```bash
> SSH_IF=$(ip route get ${SSH_CONNECTION%% *} | sed -n 's/.* dev \([^ ]*\).*/\1/p')
> echo "my shell arrives on: $SSH_IF"
> ss -ltnp | grep sshd
> grep -E '^define (rnic|conif|tsif|wanif)' deploy/orin/nftables.conf
> ```
>
> `$SSH_IF` **must** be one of `$conif` or `$tsif` — or `$wanif`, if you are on a
> private address. Then continue to §1.
>
> **If `$SSH_IF` is the same interface as `$rnic`: STOP.** […] The two recorded
> ways forward, in order of preference:
>
> 1. **Come in another way.** A USB-serial console (B-con route b), or bring the
>    tailnet up first and use `$tsif`. Nothing about the ruleset changes.
> 2. **Open one host on the robot LAN, deliberately and in writing.** Give the
>    laptop a static address, then uncomment the single rule in `nftables.conf`
>    marked *THE B-CON-ON-THE-ROBOT-LAN CASE* with that address:
>
>    ```
>    iifname $rnic ip saddr 192.168.123.99/32 tcp dport 22 ct state new counter accept
>    ```
>
>    It must stay **above** the DDS rules. Write in `hw/B_fw.txt`: the date, the
>    address, and the sentence *"the robot LAN has a shell to one host — an ADR
>    0002 item 4 deviation, removed when B-con is replaced by the tailnet or a
>    serial console."* Then remove it, and re-`reload`, the day that happens.
>
> Do **not** solve this by adding `$rnic` to the general ssh set, and do not solve
> it by setting `define conif` to the same name as `$rnic`: both give the whole
> robot LAN a shell. The structural test refuses any `$rnic` ssh accept that is
> not a single-host `/32`.

Also applied: README §0's `$rnic` rule is now **"the NIC whose address is
`192.168.123.18`"**, not "a 192.168.123.x address" (fact 19: more than one NIC
can match the loose rule); the ruleset's absolute *"$rnic deliberately is NOT:
the robot LAN gets no shell"* is replaced by the conditional plus the commented
single-host template; the B-fw row points at step 0.5 first.

## H2 — the boot failure mode, in three lines

1. **`nft -f` is one atomic batch**, so the bridge table moved out to
   `deploy/orin/nftables-bridge.conf` (variable-free) and is loaded by a third,
   `-`-prefixed `ExecStart=-` — a kernel with no `CONFIG_NF_TABLES_BRIDGE` now
   costs the L2 half and nothing else, instead of aborting the whole file.
2. `parcel-nftables.service` gains
   **`OnFailure=parcel-nftables-lockdown.service`**; that unit has **no
   `[Install]`** (nothing but `OnFailure` may start it) and loads
   `deploy/orin/nftables-lockdown.conf` — **variable-free** (a wrong `define` is
   one of the failures it covers) and address-based: `forward policy drop`,
   input = `lo` + established + `ip saddr != 192.168.123.0/24 tcp dport 22`,
   output drops 239.255.0.0/16. Degraded on purpose — DDS does not pass.
3. README §4's reboot re-check adds `systemctl is-failed parcel-nftables` and a
   `nft list table bridge parcel_l2`, and §2 adds "`parcel_lockdown` must NOT be
   loaded" plus the `zcat /proc/config.gz | grep NF_TABLES_BRIDGE` read.

## F1 — N1 could not fail; now it can, and it is proved

`_nft_diagnostics` anchored on `CONF.name` (a basename) while nft prints the
path **as passed** (absolute). Fixed: the reader matches
`^(?P<path>.+?):\d+:\d+(?:-\d+)?: Error: ` and compares the captured path with
the path it passed. **Liveness proof, now a test**
(`test_n1_liveness_a_broken_copy_must_produce_a_diagnostic`): it copies the
ruleset to a temp dir outside the repo, rewrites the first `policy drop;` to
`policy dropp;`, and asserts a diagnostic **at that line number** —

```
/tmp/tmp.OxRavUk2qd/broken.conf:77:45-49: Error: syntax error, unexpected string, expecting accept or drop or '$'
```

Deleting the fix reddens it. The row's docstring now states the limit the
verifier measured: unprivileged `-c` is a **syntax** verdict only (undefined
`$vars`, unknown hooks, bad CIDRs are caught; `ct state invalidd`, a missing
chain type and a `jump` to nowhere are not — root on the Orin gets those). N1
also now checks all three `.conf` files, not one.

## F2 — P17/P18/P19, and the seeds that prove them

| Seed on the scratch ruleset | Before | After |
|---|---|---|
| **V3** delete `ct state established,related accept` (every shell dies after the handshake) | 19 passed | **`test_p17_return_traffic_is_accepted_before_anything_is_dropped` FAILED** |
| **V4** `chain output` `policy accept` → `policy drop` (sshd's replies dropped) | 19 passed | **`test_p18_the_output_chain_does_not_default_to_drop` FAILED** |
| **V5** delete the `icmpv6 type` accept (IPv6 outage) | 19 passed | **`test_p19_ipv6_neighbour_discovery_and_mld_survive_the_default_drop` FAILED** |

P17 also pins the *ordering* (return traffic accepted before the ssh rule); P19
pins the four MLD types added for N1 as well as the four ND types.

## F3, F4, F5

* **F3.** The one ssh rule became two: `iifname { $conif, $tsif } tcp dport 22 ct
  state new accept`, and `iifname $wanif ip saddr { 10.0.0.0/8, 172.16.0.0/12,
  192.168.0.0/16 } tcp dport 22 …` as a **dated** day-1 deviation with its
  removal line in README §2 item 6. **`$lteif` is out of every ssh accept** (ADR
  0002 item 4: remote access tailnet-only); it keeps tailscale's 41641 and DHCP,
  which is what the tailnet actually needs. Seed **V6** (put `$lteif` back) →
  **P7 RED**.
* **F4.** The dead-man's switch now runs `systemctl disable --now
  parcel-nftables` (plus `stop parcel-nftables-lockdown` and the three table
  deletes), so a fired timer does not leave the next reboot to re-lock the box
  with nothing armed. README adds "the unit is then disabled — fix the defines
  and start again from (a)", that `systemctl stop parcel-fw-rollback` **without**
  `.timer` cancels nothing, and that on the serial-console route the
  second-shell proof is ssh later.
* **F5.** `containers.conf` gains
  `table bridge parcel_l2 { chain forward { meta ibrname $dockerif meta obrname
  $dockerif counter accept } }` — container-to-container on one Docker bridge is
  bridged, not routed, so an inet-only opt-in file would have left
  `deploy/compose.yaml`'s two `parcel_aux` stubs unable to talk. P15 extended;
  seed **F5a** (delete it) → **P15 RED**.

## NOTEs

N1 four MLD types added (and pinned by P19). N2 README §0 and §2 now say `$lnic`
is a Q-wire read *after* B-fw, and give the "edit + `nft -c -f` + `systemctl
reload`" line. N3 reworded everywhere: not a module — `CONFIG_NF_TABLES_BRIDGE`
compiled into `nf_tables`, read with `zcat /proc/config.gz`; the verifier's
confirmation that root `nft -c -f` *does* catch it is kept as the reason the
check runs first. N4 the participant-index arithmetic is a comment beside
`$ddsports`. N5 `iifname $rnic ip protocol igmp counter accept` added. N6 the
macvlan/ipvlan bypass and the IPv4-only assumption are stated in README §6. N7
no action (it is D2, already declared). N8 `ExecStop` kept — it is the rollback
path README §3 uses, and the shutdown-ordering behaviour matches Debian's own
`nftables.service`.

## Full seed battery, this pass (all on `~/.cache/parcel-hwfw/scratch`, restored by sha256)

| Seed | Reddens |
|---|---|
| S1 forward `policy drop`→`accept` | `test_p4` |
| S2 forward accept from `$rnic` | `test_p5` |
| S3 delete the inbound-DDS counter-drop | `test_p8` |
| V2 a wide ssh accept on `$rnic` | `test_p7` |
| V3 delete `ct state established,related accept` | `test_p17` |
| V4 output `policy accept`→`drop` | `test_p18` |
| V5 delete the ICMPv6 ND/MLD accept | `test_p19` |
| V6 `$lteif` back in the ssh set | `test_p7` |
| V7 a `/32` `$rnic` ssh accept **below** the DDS accept | `test_p7` |
| H2a drop the `-` from the bridge `ExecStart` | `test_p16` |
| H2b delete `OnFailure=` | `test_p16` |
| H2c give the lockdown unit an `[Install]` | `test_p16b` |
| H2d lockdown `forward policy drop`→`accept` | `test_p16b` |
| H2e lockdown ruleset uses a variable | `test_p16b` **and** `test_n1` |
| F5a delete the bridge-family container accept | `test_p15` |

Each: 1 failed / 23 passed; restored byte-identical; control **24 passed** either
side. H2e reddening N1 as well is the second, independent proof that F1's fix
made that row live.

## Files after the pass

```
deploy/orin/nftables.conf           203 lines  1844e720aa253e2fe630973d34b47b5c03f8bd92ed83024f80f04327e312583e
deploy/orin/nftables-bridge.conf     41 lines  a286c6e506d6cd5cbe3ea82846fafe18165f8c29ceb0d99041c01d30d67b119b
deploy/orin/nftables-lockdown.conf   46 lines  f55163a4a384d3df98ed46a351ff11b08b1a5320103a4ce722cb7f6193807d98
deploy/orin/nftables.service         64 lines  a5c782af02b562f1882700a6d1e67c8789cd701fa39f14378ae6c523faed4ecd
deploy/orin/nftables-lockdown.service 32 lines b05de49074c7683fcc1a27030d238ccd1e36d815c329cda972f60713449fddca
deploy/orin/containers.conf          50 lines  307b9695c9f0f63849bf474fe97a4e08bf16191c7e5a1942759e8f28b4569cb8
deploy/orin/README.md               231 lines  278a9d8f2aaaac5861818d50691738c629177a3d0e680312ad28d370883f6da2
tests/test_hwfw_nftables.py         841 lines  cead41f722bba49840e6923a2ed2fc438999f830e1f7c74e324455ffeafa5096
```

`docs/BOX_DAY.md`: still **two** hunks, both `<!-- HW-FW -->`; the B-fw row now
carries step 0.5, the three `nft -c -f` checks, the disabling dead-man, and
`systemctl is-failed`. **`wc -w` = 2,493 ≤ 2,500** (182 words against the old
row's 183). `DOES NOT EXIST YET` → 0.

`ruff check` → *All checks passed*; `ruff format --check` → *already formatted*;
`grep -c noqa` → 0; no line over 100 columns.

**`git status --porcelain` for this card, before and after the pass — identical:**

```
?? deploy/orin/
?? docs/BOX_DAY.md
?? scrum/20260822/task_43/
?? tests/test_hwfw_nftables.py
```

**`DESIGN.md` was edited in the same pass** (the batch-B rule for a design the
implementation moved): §(c) the two ssh rules and what `$lteif`/`$rnic` no longer
get; a new §(e.0) for the B-con lockout and step 0.5; §(e.1) rewritten around the
atomic-batch trap and the split file; §(f) the three `ExecStart` lines and the
`OnFailure` lockdown; §(h) the corrected mitigation list. 184 lines (was 157) —
D3's overage grows, for the reason D3 already gives.

## Still not proved

Everything in the first pass's "What this does not prove", plus: the lockdown
unit has never been triggered (no root, no systemd test on this host), `nft -c`
here remains syntax-only, and whether B-con's cable lands on `$rnic` is exactly
the question step 0.5 exists to ask on the day — this card makes both answers
safe, it does not know which one is true.

---

**Close — 2026-08-23 18:2x EDT.** Verifier FINAL = ACCEPT-WITH-NOTES; this line
records the docs-only follow-up. **R2-F1 (required) applied:** README §0.5 route 2
now says the lockdown fallback *cannot* reach a laptop that is inside
192.168.123.0/24 — "if `parcel-nftables` ever fails at boot, the serial console is
your only way in, at every boot until the main file loads — keep one to hand" —
and §2 item 5's "you still have a shell" is now qualified "**unless you took step
0.5 route 2, in which case lockdown has no shell for you; see §0.5**"
(`grep -n lockdown deploy/orin/README.md` → 74, 79, inside route 2). The optional
half was taken too: `nftables-lockdown.conf` carries the same commented
single-host template (address-based, so the file stays variable-free) and **P16b
now pins it `/32`-only** — seeded three ways on the scratch: the `/32` template
uncommented → **24 passed** (sanctioned), the same rule as a `/24` → **P16b RED**,
and with no `ip saddr` at all → **P16b RED**; restored by sha256, control 24
passed. **R2-N2** the unit's stale "missing `nf_tables_bridge` module" comment is
reworded (the main file no longer carries that table; the requirement is the
kernel config `CONFIG_NF_TABLES_BRIDGE`, read with `zcat /proc/config.gz`, and it
is the third `-`-prefixed line that meets it). **R2-N3** the conf header's `$rnic`
is now "the NIC whose address is 192.168.123.18", with the reason, and its
citation is **fact 19** — one numbering everywhere now, 1-based
(**18** = CVE-2026-27509, **19** = the robot-LAN address map; the card README's
"17/18" is the same two entries, 0-indexed). **R2-N4** §0.5 states the serial
case: `$SSH_CONNECTION` is empty there, which is the answer — no shell to lose,
skip the read, still fill `$conif`. **R2-N6, declared:** P16b, P17-P19, the N1
liveness test and seeds V2-V7 / H2a-e / F5a / R2-F1a-c are **post-registration
rows, taken from the verifier's findings** and measured as specified there; the
frozen `PREREGISTRATION.md` (sha `80aeae18…`) is unchanged. R2-N1, N5, N7 are
recorded, not taken: R2-N1 (v6/tailscale-ULA ssh in the fallback) and R2-N5 (a
`containers-bridge.conf` split) are the next editor's, and R2-N7 needs a boot.
**Verification:** `tests/test_hwfw_nftables.py` through the wrapper → **24
passed**; `nft -c -f` clean on all three `.conf` files; `ruff check` /
`format --check` clean, 0 `noqa`; `docs/BOX_DAY.md` **untouched in this pass**,
`wc -w` = **2,493** ≤ 2,500; `git status --porcelain` for this card unchanged
(`deploy/orin/`, `docs/BOX_DAY.md`, `scrum/20260822/task_43/`,
`tests/test_hwfw_nftables.py`). **HW-FW CLOSED.**
