# `deploy/orin/` — the robot-LAN firewall

**Card:** HW-FW `orin-firewall` (`scrum/20260822/task_43/`) · **Design:**
`scrum/20260822/WAVE3_HW_DESIGN_FABLE.md` §5.7 · **Runbook step:** B-fw of
`docs/BOX_DAY.md` · **Policy:** ADR 0002 item 4.

192.168.123.0/24 is unauthenticated CycloneDDS domain 0. CVE-2026-27509
(unauthenticated RCE, CVSS v4 8.5) has **no known patched version**, so this
file — not the `>= V1.1.13` firmware pin — is the load-bearing control. The
Orin is the only host with a foot in both worlds.

| File | What it is |
|---|---|
| `nftables.conf` | the ruleset. Interface names are `define`s at the top; every one is a box-day read |
| `nftables-bridge.conf` | the L2 half, in its own file so a kernel that cannot take it does not take the L3 boundary down with it |
| `nftables.service` | systemd unit, loads both **before** `network-pre.target`, survives reboot |
| `nftables-lockdown.conf` + `.service` | the fallback: variable-free, `forward policy drop`, a shell from anywhere but the robot LAN. Started only by the main unit's `OnFailure=` |
| `containers.conf` | opt-in accepts for Docker, in both families. **Not** included by default |

**Never on the development desktop.** Nothing here is applied outside the
Orin; on the desktop the only supported command is `nft -c -f` (check-only,
loads nothing) and `tests/test_hwfw_nftables.py`, which needs no `nft` at all.

## 0. Fill the variables — the file is wrong until you do

| Variable | Read it from | How |
|---|---|---|
| `$rnic` | **B9** | `ip -br a` → the NIC whose address is **`192.168.123.18`** (the dock/Jetson, research hw fact 19) — **not merely "a 192.168.123.x address"**: the dog's external RJ45 and both of the dock's RJ45s sit on that /24, so more than one NIC may match the looser rule, and picking the wrong one is the lockout of step 0.5 |
| `$lnic` | **Q-wire** | `tcpdump -i <nic> udp port 56300` on each NIC in turn. Shares the robot LAN? set it to the same name as `$rnic`. **Q-wire is step 7 and B-fw is step 3**, so `$lnic` is still a placeholder when you apply: `tcpdump` reads frames via AF_PACKET, before netfilter, so Q-wire still works — but afterwards you must edit `$lnic`, re-run `sudo nft -c -f`, and `sudo systemctl reload parcel-nftables` |
| `$wanif`, `$lteif` | **B9** | `ip -br a` → Wi-Fi 6, 4G. No modem? leave `$lteif` as-is, an absent name matches nothing. **`$lteif` gets no ssh** (ADR 0002 item 4 is tailnet-only); `$wanif` gets ssh only from RFC1918 space, and that line is a dated day-1 deviation you remove once ssh over `$tsif` is proven |
| `$conif` | **B-con** | the spare RJ45 your laptop cable is on — **and it may not be a separate NIC at all.** Step 0.5 below is how you find out before it matters |
| `$tsif` | you | the tailnet interface, usually `tailscale0` |

## 0.5. Read which interface your shell is on — BEFORE you load anything

This is the step whose absence was the HOLD on the first version of this card,
and it takes ten seconds.

```bash
SSH_IF=$(ip route get ${SSH_CONNECTION%% *} | sed -n 's/.* dev \([^ ]*\).*/\1/p')
echo "my shell arrives on: $SSH_IF"
ss -ltnp | grep sshd
grep -E '^define (rnic|conif|tsif|wanif)' deploy/orin/nftables.conf
```

`$SSH_IF` **must** be one of `$conif` or `$tsif` — or `$wanif`, if you are on a
private address. Then continue to §1.

**On a serial console** `$SSH_CONNECTION` is empty and `ip route get` errors out.
That is the answer, not a problem: there is no shell to lose, so skip the read
and go to §1 — but still fill `$conif` for the cable you will use later.

**If `$SSH_IF` is the same interface as `$rnic`: STOP.** Research hardware fact
19 puts the dog's external RJ45 and both of the dock's RJ45s on
192.168.123.0/24, so a laptop cable into the spare port may well be a switch
port behind the Orin's one robot-LAN NIC. Loading the ruleset now drops your own
next packet. The two recorded ways forward, in order of preference:

1. **Come in another way.** A USB-serial console (B-con route b), or bring the
   tailnet up first and use `$tsif`. Nothing about the ruleset changes.
2. **Open one host on the robot LAN, deliberately and in writing.** Give the
   laptop a static address, then uncomment the single rule in `nftables.conf`
   marked *THE B-CON-ON-THE-ROBOT-LAN CASE* with that address:

   ```
   iifname $rnic ip saddr 192.168.123.99/32 tcp dport 22 ct state new counter accept
   ```

   It must stay **above** the DDS rules. Write in `hw/B_fw.txt`: the date, the
   address, and the sentence *"the robot LAN has a shell to one host — an ADR
   0002 item 4 deviation, removed when B-con is replaced by the tailnet or a
   serial console."* Then remove it, and re-`reload`, the day that happens.

   **In this configuration the lockdown fallback cannot reach you either: it
   accepts ssh only from *outside* 192.168.123.0/24, and your laptop is inside.**
   If `parcel-nftables` ever fails at boot, the serial console is your only way
   in, at every boot until the main file loads — keep one to hand. The blunt
   alternative is to uncomment the matching single-host rule in
   `nftables-lockdown.conf` (it carries the same `/32` template, for exactly this
   case) so the fallback knows about your laptop too.

Do **not** solve this by adding `$rnic` to the general ssh set, and do not solve
it by setting `define conif` to the same name as `$rnic`: both give the whole
robot LAN a shell. The structural test refuses any `$rnic` ssh accept that is
not a single-host `/32`.

## 1. Apply — with a way back, from the start

Do this **before any WAN interface comes up**, from the B-con shell, after
step 0.5, and open a **second** shell to the Orin first if you can.

```bash
# a. check the files against this kernel. A typo, or a kernel with no
#    CONFIG_NF_TABLES_BRIDGE, fails HERE, with nothing loaded.
sudo nft -c -f deploy/orin/nftables.conf
sudo nft -c -f deploy/orin/nftables-bridge.conf     # may fail; see §2
sudo nft -c -f deploy/orin/nftables-lockdown.conf

# b. arm a five-minute dead-man's switch BEFORE you load anything. It DISABLES
#    the unit as well as deleting the tables — deleting alone would let the next
#    reboot lock you out again, with no timer running.
sudo systemd-run --on-active=300 --unit=parcel-fw-rollback /bin/sh -c \
  'systemctl disable --now parcel-nftables; \
   systemctl stop parcel-nftables-lockdown; \
   for tbl in "inet parcel" "bridge parcel_l2" "inet parcel_lockdown"; do \
     nft delete table $tbl 2>/dev/null; done; true'

# c. install and load.
sudo install -D -m 0640 deploy/orin/nftables.conf           /etc/parcel/nftables.conf
sudo install -D -m 0640 deploy/orin/nftables-bridge.conf    /etc/parcel/nftables-bridge.conf
sudo install -D -m 0640 deploy/orin/nftables-lockdown.conf  /etc/parcel/nftables-lockdown.conf
sudo install -D -m 0644 deploy/orin/nftables.service \
     /etc/systemd/system/parcel-nftables.service
sudo install -D -m 0644 deploy/orin/nftables-lockdown.service \
     /etc/systemd/system/parcel-nftables-lockdown.service
sudo systemctl daemon-reload
sudo systemctl enable --now parcel-nftables

# d. from the SECOND shell — a NEW ssh connection, not the one you already
#    have (an existing session survives on `ct state established` and proves
#    nothing) — confirm you can still get in. Then, and only then:
sudo systemctl stop parcel-fw-rollback.timer
```

If step (d) fails, do nothing and wait: at the five-minute mark the timer
disables the unit and removes the tables, and the box comes back. **The unit is
then disabled** — fix the `define`s and start again from (a). Note that
`systemctl stop parcel-fw-rollback` **without** `.timer` stops the service, not
the timer, and cancels nothing.

On the serial-console route (B-con option b) there is no second ssh session to
prove: verify the ruleset from the console, then prove ssh separately once a
network path exists.

## 2. Verify — this is what goes in `hw/B_fw.txt`

```bash
{
  echo "== ruleset ==";        sudo nft list table inet parcel
                               sudo nft list table bridge parcel_l2
  echo "== lockdown? ==";      sudo nft list table inet parcel_lockdown 2>&1 | head -3
  echo "== unit ==";           systemctl is-enabled parcel-nftables; systemctl is-active parcel-nftables
                               systemctl is-failed parcel-nftables
  echo "== bridge support =="; zcat /proc/config.gz | grep -E 'NF_TABLES_BRIDGE|NETFILTER_FAMILY_BRIDGE'
  echo "== interfaces ==";     ip -br a
  echo "== routes ==";         ip route            # NO default route via $rnic
  echo "== bridges ==";        ip -d link show type bridge; bridge link
  echo "== forwarding ==";     sysctl net.ipv4.ip_forward
  echo "== panel ==";          ss -ltnp | grep -w 8765 || echo "panel not running (fine)"
} | tee ~/Parcel/hw/B_fw.txt
```

Read four things in that output and write the answer beside each:

1. `chain forward` says `policy drop` and has **no accept rule**.
2. `chain input` says `policy drop`, and the `tcp dport 22` accept lists the
   interface you are actually connected on.
3. `ip route` shows **no default route** via `$rnic`. The Mid-360 NIC is static
   (`192.168.1.5` in the driver's sample config) with **no gateway**.
4. `ip -d link show type bridge` — if the spare RJ45 is in a bridge with the
   robot LAN, say so out loud; the `bridge parcel_l2` table is what covers it,
   and if that table failed to load you have no L2 protection at all.

Two more things to write down:

5. **`parcel_lockdown` must NOT be loaded.** If it is, the real ruleset failed
   and the fallback took over: `systemctl status parcel-nftables` says why. The
   box is in a degraded state — DDS does not pass, so the runtime cannot see the
   robot — but the forwarding boundary holds and you still have a shell —
   **unless you took step 0.5 route 2, in which case lockdown has no shell for
   you; see §0.5.**
6. **The `$wanif` ssh line is dated.** It is an ADR 0002 item 4 deviation ("remote
   access tailnet-only"). Write the date you added it and delete it — then
   `sudo systemctl reload parcel-nftables` — once ssh over `$tsif` is proven.

**If `nft -c -f deploy/orin/nftables-bridge.conf` was rejected:** this kernel
does not have the bridge filter chain type. It is **not** a module on 5.10/5.15
— there is no `nf_tables_bridge.ko` to load; the chain type is compiled into
`nf_tables` under `CONFIG_NF_TABLES_BRIDGE` (which selects
`NETFILTER_FAMILY_BRIDGE`), and the direct read is the `zcat /proc/config.gz`
line above. The error you will see is `Error: Could not process rule: No such
file or directory`. Nothing needs changing: the unit loads that file with a
failure-tolerant `ExecStart=-`, so `inet parcel` stays up without it. Record the
rejection in `hw/B_fw.txt` and treat check 4 as **mandatory** rather than
informational — with no L2 table, a bridged spare RJ45 has no protection at all.

## 3. Roll back

```bash
sudo systemctl disable --now parcel-nftables           # ExecStop deletes both tables
sudo systemctl stop parcel-nftables-lockdown 2>/dev/null || true
sudo nft delete table inet parcel_lockdown 2>/dev/null || true
sudo nft list ruleset | head                           # confirm nothing of ours remains
```

That is the whole rollback. Nothing else on the box was modified — no sysctl,
no `/etc/nftables.conf`, no interface configuration.

## 4. Re-check after a reboot, and again before Q-link

The stopgap this file replaces lived only in the kernel and vanished on reboot.
The unit fixes that, and the check that proves it is:

```bash
sudo reboot
# then, back in:
systemctl is-active parcel-nftables            # active (exited)
systemctl is-failed parcel-nftables            # "active" — anything else means the
                                               # lockdown fallback is what is running
sudo nft list table inet parcel | head -3      # the table is there
sudo nft list table bridge parcel_l2 | head -3 # ...and the L2 half, or the recorded
                                               # CONFIG_NF_TABLES_BRIDGE rejection
sudo nft list table inet parcel | grep -c counter   # counters back at 0 = a fresh load
```

`nft -f` is one atomic kernel batch: a single bad line means the **whole** file
fails and nothing loads. `Before=network-pre.target` is ordering only —
NetworkManager still brings the WAN up. That is why the bridge half is a
separate, failure-tolerant load and why `OnFailure=parcel-nftables-lockdown`
exists: whatever else breaks, `forward policy drop` survives. `is-failed` is how
you notice.

Run the same three lines **again before step Q-link**, which is the first step
that deliberately sends traffic over the WAN.

## 5. Containers — opt-in, and dated

`forward policy drop` also drops Docker bridge traffic, so `deploy/compose.yaml`
will not run on the Orin until `containers.conf` is enabled. That is correct on
day 1. When ADR 0001's stack really lands, follow the header of
`containers.conf`, and write the date and reason in `hw/B_fw.txt`. Every accept
in that file is scoped to `$dockerif`; none may name `$rnic` or `$lnic`, and
`tests/test_hwfw_nftables.py` fails if one does.

## 6. What this does not do

It filters packets. It is not authentication, and it does not protect the robot
LAN from a device someone plugs into it. A container given the robot NIC
directly — macvlan or ipvlan on `$rnic` — bypasses **both** tables, because its
frames never traverse a bridge and are never routed by this host; do not do that
without re-reading this file. The robot LAN is assumed IPv4-only (the `$rnic`
DDS accept covers v4 and v6 either way). Pinning CycloneDDS itself to `$rnic`
(`CYCLONEDDS_URI` → `<General><Interfaces>`) is the belt to this file's braces
and belongs to the runtime's configuration, not here. The dog's own firmware is
untouched — Parcel never flashes it (ADR 0002 item 5).
