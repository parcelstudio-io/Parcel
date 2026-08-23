# Task 43 — HW-FW: `orin-firewall` — the robot LAN is a boundary the Orin enforces from a checked-in file

**Executor:** Claude Opus · **Verifier:** Fable · **Board:** `../TASK_BOARD.md`
(P0 rules + anti-crash rules; wave-3 COMMON brief). **Design:**
`../WAVE3_HW_DESIGN_FABLE.md` §2.7, §5.7, §7 B-fw, §7.3, §9. **Evidence:**
ADR 0002 item 4 (`scrum/20260805/task_1/adr/0002-firmware-pin.md`),
`research.json` hardware fact 17 (CVE-2026-27509: unauthenticated
CycloneDDS RCE on domain 0, no known fixed version) and 18 (dock
192.168.123.18, head 192.168.123.161), HW-8's `docs/BOX_DAY.md` B-fw (the
inline stopgap + its verifier's gaps: runtime-only, inbound DDS not
filtered, bridging bypasses `inet forward` without `br_netfilter`,
containers need accepts), `~/.cache/parcel-verify/hw8/VERDICT.md`.

## Why
192.168.123.0/24 is unauthenticated DDS with a known RCE class. The Orin is
the only host with a foot in both worlds. Today the only ruleset is five
lines of prose in a runbook; nothing is checked in, tested, or persistent.

## Work
1. `DESIGN.md` first: the interfaces (robot NIC `<rnic>` on 192.168.123.x;
   WAN = Wi-Fi/4G/second RJ45; the Mid-360 NIC if separate; tailnet
   interface), the policy (forward: default drop both ways; input: accept
   established, accept SSH + tailnet + the panel on 127.0.0.1 only, drop
   DDS ports from non-robot interfaces, rate-limit the rest; output: DDS
   multicast 239.255.0.0/16 and unicast DDS only on `<rnic>`; no default
   route on `<rnic>` — stated as a routing rule, not nft), persistence
   (`/etc/nftables.conf` include or a systemd unit — say which and why),
   the bridging/`br_netfilter` caveat and the container caveat as
   explicit decisions, what is UNCONFIRMED until Q-wire/Q-con.
2. `deploy/orin/nftables.conf` (the ruleset; interface names as variables
   `define rnic = "eth0"` at the top with a comment naming the B9 read
   that fills them), `deploy/orin/nftables.service` (or the include
   snippet), `deploy/orin/README.md` (apply / verify / roll back).
3. A structural test `tests/test_hwfw_nftables.py` that parses the file
   WITHOUT nft (pure Python tokenizer over the nft grammar subset you use)
   and pins: forward policy drop; no rule forwards from `<rnic>` to any
   other interface; DDS multicast confined to `<rnic>`; SSH and tailnet
   accepted on input; loopback accepted; the panel port only on lo; the
   variables defined; plus — if `nft` is installed on this box — `nft -c
   -f deploy/orin/nftables.conf` (check-only, never loads) as a second
   row, recorded as SKIP-with-reason if `nft` is absent. Seeds RED: drop
   the forward policy → red; add a forward accept from `<rnic>` → red.
4. `docs/BOX_DAY.md` B-fw row: replace "DOES NOT EXIST YET" with the apply
   command and the verify line (marked `<!-- HW-FW -->` comment; HW-8 is
   closed — you own that one row now).

OWNS: `deploy/orin/` (new), `tests/test_hwfw_*.py`, the B-fw row of
`docs/BOX_DAY.md`, `task_43/` docs. MUST NOT TOUCH: `deploy/compose.yaml`,
`deploy/docker/`, anything under `src/`, the ADRs, `docs/MOTION.md`.
Never apply a ruleset on this desktop (no `nft -f`, no `sudo`).

## Definition of done
Ruleset checked in with variables for the B9 reads; structural pins +
`nft -c` (or SKIP-with-reason); seeds RED; runbook row updated;
`HWFW_STATUS.md` with pre-registered rows.

## Hardware-compat (§e)
Class NEW, box-day-applied. Every interface name is a B9/Q-wire read; the
policy is venue-independent; nothing here runs on the desktop except the
check.
