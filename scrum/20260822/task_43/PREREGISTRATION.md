# HW-FW `orin-firewall` — PREREGISTRATION

Written **before** any row was measured. Rows are measured exactly as written;
a miss is a miss. Design: `DESIGN.md` (same folder). Card:
`README.md` §Work + §Definition of done.

**`nft` presence, checked first (this is a registration input, not a row):**
`which nft` → `/usr/sbin/nft`; `nft --version` → `nftables v1.1.6 (Commodore
Bullmoose #7)`. So row **N1 is LIVE, not SKIP**. Measured before registering
it, so the row is honest about what it can prove: as an unprivileged user
`nft -c -f` completes the **parse** and then fails at `netlink: Error: cache
initialization failed: Operation not permitted` (rc 1) — it never touches the
kernel ruleset and it never loads anything. A syntax/identifier error is
printed *before* that line as `<file>:<line>:<col>-<col>: Error: …`. N1
therefore asserts **zero `<file>:line:col` diagnostics**, and explicitly does
NOT claim kernel-side validation (set types, module presence, `jump` targets).
**No `nft -f`, no `sudo`, no network change is run on this desktop at any
point.** ~~SKIP-with-reason~~ does not apply.

All commands run from the repo root with `TMPDIR` unset. Pytest goes through
`~/.cache/parcel-guard/pytest_guard.sh --label hwfw`, never `-n auto`.

## Structural rows — `deploy/orin/nftables.conf` through the tokenizer

Command for P1–P16 (one run):
`env -u TMPDIR ~/.cache/parcel-guard/pytest_guard.sh --label hwfw .parcel/bin/python -m pytest tests/test_hwfw_nftables.py -q`

| # | Row | Threshold |
|---|---|---|
| P1 | the ten `define`s exist and are the only interface-specific text | `rnic lnic wanif lteif conif tsif ddsports livoxports panelport tsport` all defined; no rule token contains a bare interface-looking literal other than `lo` |
| P2 | `inet parcel` `input` chain | `type filter hook input priority 0; policy drop` |
| P3 | loopback is the first accept in `input` | the first rule of `input` is `iif lo accept` |
| P4 | **forward policy drop** | `inet parcel` `forward`: `type filter hook forward priority 0; policy drop` |
| P5 | **no rule forwards from `$rnic` to anything** | the `forward` chain has **zero** rules with an `accept` verdict, and no rule in it mentions `$rnic`/`$wanif`/`$lteif`/`$lnic` |
| P6 | the panel port is loopback-only | every rule naming `$panelport` is a `drop`; at least one is qualified `iifname != "lo"`; no `accept` anywhere in the file names `$panelport` |
| P7 | SSH is accepted on WAN, tailnet and B-con's cable | exactly one `accept` rule with `tcp dport 22`; its `iifname` set contains `$wanif`, `$lteif`, `$conif`, `$tsif`; it does **not** contain `$rnic`; it is in `input` |
| P8 | inbound DDS | every `accept` naming `$ddsports` in `input` is qualified `iifname $rnic`; **and** an explicit `iifname != $rnic … $ddsports … drop` rule exists (the counter that names the event) |
| P9 | DDS multicast confined to `$rnic` | every rule naming `239.255.0.0/16` is a `drop` qualified `oifname != $rnic`; ≥ 1 such rule exists |
| P10 | unicast DDS confined to `$rnic` | an `output` rule `oifname != $rnic … udp dport $ddsports … drop` exists |
| P11 | Livox confined to `$lnic` both ways | the only `accept` naming `$livoxports` is `iifname $lnic` (input); an `output` rule drops `$livoxports` off `oifname != $lnic` |
| P12 | the ruleset can load before the interfaces exist | every interface match uses `iifname`/`oifname`; the only `iif`/`oif` tokens in the file are `iif lo` / `oif lo` |
| P13 | idempotent, and never destructive | the file contains no `flush ruleset`; for each of the two tables the `table … / delete table … / table … {` preamble is present, in that order |
| P14 | the bridging answer exists | `table bridge parcel_l2` has a `forward` chain, `policy drop`, zero `accept` rules |
| P15 | the container accepts are opt-in and scoped | `deploy/orin/nftables.conf` has **no** active `include` statement; `deploy/orin/containers.conf` exists, every `accept` in it is qualified by `$dockerif` on `iifname` or `oifname`, and no rule in it mentions `$rnic` or `$lnic` |
| P16 | the unit persists it and rolls back cleanly | `deploy/orin/nftables.service`: `Before=` contains `network-pre.target`; `DefaultDependencies=no`; two `ExecStart=` lines, the first `nft -c -f`, the second `nft -f`, same path; `ExecStop` deletes `table inet parcel` and `table bridge parcel_l2` and contains no `flush ruleset`; `WantedBy=sysinit.target` |

| # | Row | Command | Threshold |
|---|---|---|---|
| N1 | `nft` agrees the file parses | `nft -c -f deploy/orin/nftables.conf 2>&1` (check-only; never `-f`, never `sudo`) | **zero** lines matching `^deploy/orin/nftables\.conf:[0-9]+:` ; the only stderr line is the unprivileged `cache initialization failed`. Same for `deploy/orin/containers.conf` prefixed with the main file's defines |

## Seeds — the guards are proved RED on a scratch copy, never the tree

Scratch: `rsync -a tests/test_hwfw_nftables.py deploy/orin/ → ~/.cache/parcel-hwfw/scratch/` preserving the `tests/` + `deploy/orin/` layout; the test resolves the conf from `Path(__file__).resolve().parents[1]`, so the scratch copy is what a scratch run reads. Restore by sha256 after each seed; `__pycache__` purged.

| # | Seed | Expected |
|---|---|---|
| S1 | in the scratch conf, `forward` chain `policy drop` → `policy accept` | **P4 fails**; the run is RED. Restore → green |
| S2 | in the scratch conf, add `iifname $rnic oifname $wanif ct state established,related counter accept` to the `forward` chain | **P5 fails**; the run is RED. Restore → green |
| S3 | in the scratch conf, delete the `iifname != $rnic udp dport $ddsports counter drop` rule | **P8 fails** (the second half — the explicit inbound-DDS counter) |

## Runbook + hygiene rows

| # | Row | Command | Threshold |
|---|---|---|---|
| R1 | the B-fw row of `docs/BOX_DAY.md` is replaced, and is the only row this card touches | `git diff -- docs/BOX_DAY.md` | exactly one hunk; it is the B-fw table row; it carries an `<!-- HW-FW -->` marker |
| R2 | B-fw no longer promises a file that does not exist | `grep -c 'DOES NOT EXIST YET' docs/BOX_DAY.md` | `0` |
| R3 | B-fw carries apply, verify, reboot re-check, and keeps the shell | the row's text | contains `nft -c -f`, `nft -f`, `nft list ruleset`, a reboot re-check, and the second-shell/rollback-timer instruction |
| R4 | the runbook stays inside its word cap | `wc -w < docs/BOX_DAY.md` | ≤ **2500** (it stood at 2,495 before this card) |
| R5 | ruff adds nothing | `.parcel/bin/ruff check tests/test_hwfw_nftables.py` (and `ruff format --check`) | zero findings; zero `noqa` in the file |
| R6 | OWNS respected | `git status --porcelain` | the only paths this card added/changed are `deploy/orin/*`, `tests/test_hwfw_nftables.py`, `docs/BOX_DAY.md`, `scrum/20260822/task_43/*` |
| R7 | nothing was applied on this desktop | the session's command ledger | no `nft -f`, no `nft add/delete/flush`, no `sudo`, no `ip`/`systemctl` write; `nft list ruleset` never run |

## What these rows cannot prove

No packet is filtered by anything in this card until the owner runs `nft -f` on
the Orin. The rows prove the file says what the design says, that `nft`'s parser
accepts it, and that the guards fail when the two load-bearing sentences are
removed. They prove nothing about the L4T kernel's modules, the real interface
names (every one is UNCONFIRMED until B9/Q-wire/B-con), whether the ruleset
survives a reboot on that box, or whether the robot LAN is what we believe it is.
