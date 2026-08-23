# HW-FW `orin-firewall` — DESIGN

**Card:** `scrum/20260822/task_43/README.md` · **Design of record:**
`../WAVE3_HW_DESIGN_FABLE.md` §2.7, §3 (C0), §5.7, §7 B-fw/B-con/Q-wire, §7.3, §8 ·
**Runbook:** `docs/BOX_DAY.md` step B-fw · **Prior review:**
`~/.cache/parcel-verify/hw8/VERDICT.md` §(4) (the four gaps this card closes).

## (a) Purpose

192.168.123.0/24 is unauthenticated CycloneDDS domain 0 carrying
`rt/api/programming_actuator/request`, whose RCE (CVE-2026-27509, CVSS v4 8.5)
has **no known patched version** [research hw fact 18]. ADR 0002 item 4 makes
the firewall the control; the version pin is not. The Orin NX is the only host
with a foot in both worlds (design §3 C0), so the boundary is a file on the
Orin, checked in here, structurally tested on the desktop, and applied once on
box day before any WAN interface comes up. This card replaces five lines of
prose in a runbook with `deploy/orin/nftables.conf`.

## (b) Architecture fit — what this touches, and what it deliberately does not

No product code. The seam is **operational**: `deploy/orin/nftables.conf` →
`/etc/parcel/nftables.conf` → `parcel-nftables.service` → the kernel, read by
`docs/BOX_DAY.md` step B-fw (the only product-facing caller is the owner's
hand). The three product facts the policy must not break:

| Product fact | File:symbol | What the policy owes it |
|---|---|---|
| the panel binds loopback and refuses non-loopback `Host:` | `web_panel.py:750` (`--host` default `127.0.0.1`), `:734 _is_loopback_host`, `:769` refusal | keep 8765 reachable on `lo`, unreachable everywhere else — the ruleset agrees with the code instead of relaxing it |
| motion DDS is domain 0 on a named NIC | `config/robot.yaml:128-129` (`unitree_sport.interface: enp3s0`, `domain_id: 0`); `control/unitree_sport.py:25-33,47` binds that pair | DDS **in and out** on `$rnic` only; the NIC name here becomes `$rnic` on the Orin (codebase fact 26) |
| the Mid-360 is raw UDP, not DDS | `lidar/livox_udp.py:198-202` (cmd 56100 / push 56200 / point 56300 / imu 56400 / log 56500); host ports +1, sample host 192.168.1.5 (`capture/channels.py:1990-1991`) | a second port range on `$lnic`, never confused with DDS |

`deploy/compose.yaml` (`safety-control` is `network_mode: none`; the stubs sit
on a `parcel_aux` bridge) is READ ONLY here and is the reason the container
caveat below is a real decision rather than a footnote.

## (c) Interfaces as variables — every one is a box-day READ, none is a guess

`nftables.conf` opens with `define`s and nothing else is interface-specific.
The placeholder values are the conventional Orin/Ubuntu names, marked as
placeholders; the file is **wrong until B9/Q-wire/B-con fill them**.

| Variable | Placeholder | Filled by | Read |
|---|---|---|---|
| `$rnic` | `"eth0"` | **B9** | `ip -br a` — the NIC holding a `192.168.123.x` address (dock .18, head .161; research hw fact 19) |
| `$lnic` | `"eth1"` | **Q-wire** | `tcpdump -i <nic> udp port 56300`; may equal `$rnic` if the Mid-360 shares the robot LAN — then set both the same |
| `$wanif` | `"wlan0"` | **B9** | the Wi-Fi 6 NIC |
| `$lteif` | `"wwan0"` | **B9** | the 4G NIC; a name that never exists is inert, see below |
| `$conif` | `"eth1"` | **B-con** | the spare RJ45 carrying the direct laptop cable (Q-con is UNCONFIRMED; §(f)) |
| `$tsif` | `"tailscale0"` | owner | the tailnet interface (ADR 0002 item 4) |
| `$ddsports` | `7400-7500` | — | DDSI-RTPS domain 0 (`domain_id: 0`, `robot.yaml:129`) |
| `$livoxports` | `56100-56599` | — | `lidar/livox_udp.py:198-202` + host ports `+1` |
| `$panelport` | `8765` | — | `web_panel.py:751` |
| `$tsport` | `41641` | — | tailscale's direct-connection UDP port |

**Every interface match is `iifname`/`oifname`, never `iif`/`oif` (except
`lo`).** `iif` resolves a device index when the rule is loaded and the load
**fails** if the device does not exist; `iifname` compares a string. That is
what lets the unit load before `network-pre.target`, on a box with no 4G modem,
with a tailnet not yet up — the day-1 requirement "must pass before any WAN
interface comes up" is only true if the ruleset can load with no WAN present.

## (d) The policy, chain by chain

`table inet parcel` (v4+v6 in one table), preceded by the idempotent
`table … ; delete table … ; table … { … }` idiom. **No `flush ruleset`** — that
would delete Docker's and the distro's tables and is how a firewall file
becomes an outage.

* **`chain input` — `policy drop`.** `iif lo accept` first, so the panel keeps
  working on loopback; then `iifname != "lo" tcp dport $panelport drop`, placed
  *before* every accept so no later edit can expose 8765 by widening a rule;
  `ct state established,related accept`; `ct state invalid drop`; the ICMP/ICMPv6
  set including the four ND types (an `inet` input drop without ND is an IPv6
  outage, and the four MLD types with it); **two ssh accepts — `{ $conif, $tsif }`
  unqualified, and `$wanif` narrowed to RFC1918 as a dated day-1 deviation.
  `$lteif` gets none (ADR 0002 item 4 is tailnet-only) and `$rnic` gets none
  except the commented single-host rule of §(e.0)**; tailscale UDP; the DHCPv4/v6
  client replies (broadcast, so conntrack does not cover them, and a
  UDP-socket DHCP client on the WAN would otherwise stop renewing); DDS
  `$ddsports` accepted **only** on `$rnic`; IGMP on `$rnic`; Livox `$livoxports` only on `$lnic`;
  then `iifname != $rnic udp dport $ddsports counter drop`, deliberately
  redundant with the policy so that `nft list ruleset` shows a **named counter**
  when something speaks DDS at the Orin from the wrong side (verdict gap 2);
  a final bare `counter` so the default drop is measurable.
* **`chain forward` — `policy drop`, and not one accept rule.** This is the
  design's sentence (§5.7) and the verdict's read: the hook drops anything the
  kernel would route between any two interfaces, both directions, whatever
  `net.ipv4.ip_forward` says. Nothing in the first two hours forwards.
* **`chain output` — `policy accept`** (an outbound default-drop on a box we
  cannot reach is how box day ends early). `oif lo accept`, then four drops:
  `239.255.0.0/16` off `$rnic` (the stopgap's rule; CycloneDDS SPDP defaults to
  239.255.0.1), the IPv6 multicast counterpart restricted to `$ddsports`,
  **unicast** DDS off `$rnic`, and Livox control off `$lnic`. Confinement now
  holds in both directions, which the stopgap's egress-only rule did not.
* **`table bridge parcel_l2`, `chain forward` `policy drop`.** See §(e).

## (e) The three caveats, decided

0. **B-con may arrive on `$rnic` (the lockout).** Research hardware fact 19 puts
   the dog's external RJ45 *and both of the dock's* on 192.168.123.0/24, so the
   laptop cable of step B-con can be a switch port behind the Orin's one robot
   NIC — and then `policy drop` eats the owner's own next packet. A ruleset
   cannot decide this; a **read** can. `README.md` **step 0.5** reads the shell's
   interface (`ip route get $SSH_CONNECTION`) *before* `nft -f`, and if it is
   `$rnic` the recorded routes are (1) come in over serial or the tailnet, or (2)
   uncomment **one** single-host rule — `iifname $rnic ip saddr <laptop>/32 tcp
   dport 22 accept`, above the DDS rules, dated in `hw/B_fw.txt`, removed when
   B-con is. Widening the general set, or aliasing `$conif` to `$rnic`, gives the
   whole robot LAN a shell and the test refuses both.

1. **Bridging (verdict gap 3), and the atomic-batch trap.** If the image bridges the spare RJ45 with the
   robot LAN, bridged frames never reach the `inet forward` hook unless
   `br_netfilter` is loaded. Two ways out. **Rejected:** `sysctl
   net.bridge.bridge-nf-call-iptables=1` — it changes kernel behaviour globally
   for every table on the box (Docker's included) to fix one table's blind spot.
   **Taken:** a second table in the `bridge` family whose `forward` hook is
   `policy drop`. It sees bridged frames directly, needs no sysctl, and is inert
   on a box with no bridge. Locally-destined frames are input, not forward, so
   the Orin's own DDS across a bridged `$rnic` is untouched. Cost: the
   `nf_tables_bridge` module must exist — which is why the README and the B-fw
   row **check with `nft -c -f` (as root, on the Orin) before `nft -f`**, and
   why the fallback (comment the table out, record it, run the `ip -d link show
   type bridge` check by hand) is written down rather than discovered.
2. **Containers (verdict gap 4).** `forward policy drop` also drops Docker
   bridge traffic, so ADR 0001's compose stack will not run on the Orin under
   this file. That is **correct on day 1** and wrong later. The accepts
   therefore live in `deploy/orin/containers.conf`, which the main file does
   **not** include: adding it is a separate, dated owner decision taken when the
   stack actually lands, not a hole opened months early on the chance it is
   wanted. Every rule in it is qualified by `$dockerif` and none may name
   `$rnic` — pinned by the test.

## (f) Persistence — a dedicated unit, and something that holds when it fails

`parcel-nftables.service` runs `nft -c -f`, then `nft -f
/etc/parcel/nftables.conf`, then `-f` the bridge file with a `-` prefix;
`DefaultDependencies=no`, `Before=network-pre.target`, `WantedBy=sysinit.target`.
**Not** the distro's `/etc/nftables.conf`: the L4T/Unitree image may already own
that file, one path per owner keeps provenance readable, `systemctl disable --now`
is then a complete rollback, and `ExecStop` deletes **our two tables** rather
than flushing the ruleset. Runtime-only rules were the verdict's gap 1; the unit
is the answer, and the README's reboot re-check is the proof.

`OnFailure=parcel-nftables-lockdown.service` is the answer to the failure of
that answer: a **variable-free** ruleset (`nftables-lockdown.conf`) that
re-asserts `forward policy drop` and an input chain of `lo` + established +
ssh from anywhere that is not 192.168.123.0/24. Variable-free because a wrong
`define` is one of the failures it covers, and address-based because interface
names are exactly what cannot be trusted at that moment. It is a degraded state
— DDS does not pass, so the runtime cannot see the robot — and `systemctl
is-failed parcel-nftables` in README §4 is how the owner notices. Its one blind
spot is §(e.0) route 2: an owner whose laptop is *on* 192.168.123.0/24 is exactly
who this address-based rule excludes, so the fallback carries the same commented
single-host template and README §0.5 says plainly that otherwise the serial
console is the only way in at a failed boot.

## (g) Test strategy

`tests/test_hwfw_nftables.py` — stdlib only, no `parcel_robot` import, no `nft`
required: a tokenizer (comment strip, quoted strings, brace depth so anonymous
sets are not mistaken for blocks) → `define`s, tables, chains with
type/hook/priority/policy, rules as token tuples, plus `$var` expansion. The
pins are §(d) and §(e) read back as assertions (PREREGISTRATION rows P1–P16),
and one extra row runs `nft -c -f` when `nft` exists: unprivileged it completes
the **parse** and fails only at the netlink cache, so the row asserts *zero
`file:line:col` diagnostics* and says plainly that kernel-side validation is not
covered without `CAP_NET_ADMIN`. Seeds: forward policy `drop`→`accept` reddens
P4; a forward accept from `$rnic` reddens P5 — both on a scratch copy of
`deploy/orin/`, restored by sha256.

## (h) Risks, and what is UNCONFIRMED

* **Lockout** is the only way this card can hurt the owner. Mitigations, in the
  README: **step 0.5's pre-apply interface read** (§e.0); `nft -c -f` first; a
  `systemd-run --on-active` rollback timer armed *before* `nft -f` that
  `systemctl disable --now`s the unit rather than only deleting the tables (a
  delete alone leaves the next reboot to lock the box again with no timer);
  verification from a **second, new** shell; the timer cancelled only after that
  shell answers.
* **UNCONFIRMED until the box:** every interface name; whether `$conif` is the
  robot LAN bridged (Q-con — if it is, the SSH accept reaches the robot LAN and
  that is a recorded consequence, not an accident); whether the Mid-360 has its
  own NIC (Q-wire); whether tailscale is installed at all; whether
  `nf_tables_bridge` is present in the L4T kernel; whether `$lteif` exists.
* **Not covered:** anything above L4 (a filter is not authentication), the DDS
  configuration itself (pinning `CYCLONEDDS_URI` `<Interfaces>` to `$rnic` is
  the belt to this braces and belongs to HW-2/HW-5), the dog's own firewall, and
  MAC-level attacks from a device plugged into the robot LAN.
