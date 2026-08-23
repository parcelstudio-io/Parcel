"""Structural pins on the Orin's robot-LAN firewall — card HW-FW ``orin-firewall``.

``deploy/orin/nftables.conf`` is the load-bearing control for CVE-2026-27509
(unauthenticated CycloneDDS RCE on 192.168.123.0/24, no known patched version):
the firmware pin of ADR 0002 cannot be relied on, so the boundary is this file.
Nobody can run it here — no robot, no root, and applying a ruleset on a
development desktop is forbidden by the card — so what this module does is read
it the way ``nft`` would and assert the sentences the design commits to.

The parser below is a real tokenizer over the subset of the nft grammar the
ruleset uses (``define``, ``table``/``chain`` blocks, chain specs, rules with
``iifname``/``oifname``/``ip daddr``/``udp dport``/``tcp dport``/``ct state``/
``counter``/``comment``/``accept``/``drop``), not a regex sweep: brace depth is
tracked so an anonymous set ``{ 22, 80 }`` is never mistaken for a block, ``#``
inside a quoted string is not a comment, and ``$vars`` expand from the file's own
``define``s. It imports nothing from ``parcel_robot`` and needs no ``nft``.

One test does call ``nft -c -f`` when the binary exists. ``-c`` is check-only: it
parses and never loads. Unprivileged it stops at the netlink cache with
``Operation not permitted``, which is why that test asserts the absence of
``file:line:col`` diagnostics rather than a zero exit status — and why it cannot
speak for kernel-side validation (module presence, set types, jump targets).

Pre-registered rows: ``scrum/20260822/task_43/PREREGISTRATION.md`` P1-P16, N1.
"""

from __future__ import annotations

import re
import shutil
import subprocess
import tempfile
from dataclasses import dataclass, field
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
ORIN = REPO / "deploy" / "orin"
CONF = ORIN / "nftables.conf"
BRIDGE = ORIN / "nftables-bridge.conf"
LOCKDOWN = ORIN / "nftables-lockdown.conf"
CONTAINERS = ORIN / "containers.conf"
UNIT = ORIN / "nftables.service"
LOCKDOWN_UNIT = ORIN / "nftables-lockdown.service"

#: Every interface the ruleset knows about is one of these, and each is a
#: box-day read (B9 / Q-wire / B-con). A literal device name in a rule would
#: mean somebody hard-coded a guess.
IFACE_VARS = ("$rnic", "$lnic", "$wanif", "$lteif", "$conif", "$tsif")
PORT_VARS = ("$ddsports", "$livoxports", "$panelport", "$tsport")

#: Anything shaped like a Linux interface name. ``lo`` is the one literal the
#: ruleset is allowed to spell, because it is the same device on every box.
_IFACE_LITERAL = re.compile(
    r"^(?:eth|wlan|wwan|enp|eno|ens|enx|usb|tailscale|docker|br|veth)[0-9a-z.-]*$"
)

_VERDICTS = frozenset({"accept", "drop", "reject", "queue", "continue", "return", "jump", "goto"})
_BLOCK_HEADS = frozenset({"table", "chain", "set", "map", "flowtable"})


# --------------------------------------------------------------------------- #
# tokenizer
# --------------------------------------------------------------------------- #
@dataclass(frozen=True)
class Token:
    kind: str  # WORD | STRING | LBRACE | RBRACE | SEP
    text: str
    line: int


def tokenize(text: str) -> list[Token]:
    """nft source -> tokens. Comments dropped; quoted strings kept whole."""
    out: list[Token] = []
    line = 1
    i = 0
    n = len(text)
    word: list[str] = []

    def flush() -> None:
        if word:
            out.append(Token("WORD", "".join(word), line))
            word.clear()

    while i < n:
        ch = text[i]
        if ch == "#":
            flush()
            while i < n and text[i] != "\n":
                i += 1
            continue
        if ch == '"':
            flush()
            j = i + 1
            buf: list[str] = []
            while j < n and text[j] != '"':
                if text[j] == "\\" and j + 1 < n:
                    buf.append(text[j + 1])
                    j += 2
                    continue
                buf.append(text[j])
                j += 1
            if j >= n:
                raise ValueError(f"unterminated string at line {line}")
            out.append(Token("STRING", "".join(buf), line))
            i = j + 1
            continue
        if ch == "\n":
            flush()
            out.append(Token("SEP", "\n", line))
            line += 1
            i += 1
            continue
        if ch in " \t\r":
            flush()
            i += 1
            continue
        if ch in "{}":
            flush()
            out.append(Token("LBRACE" if ch == "{" else "RBRACE", ch, line))
            i += 1
            continue
        if ch in ";,":
            flush()
            out.append(Token("SEP" if ch == ";" else "WORD", ch, line))
            i += 1
            continue
        word.append(ch)
        i += 1
    flush()
    return out


# --------------------------------------------------------------------------- #
# model
# --------------------------------------------------------------------------- #
@dataclass(frozen=True)
class Rule:
    """One nft rule: its tokens as written, and with ``$vars`` expanded."""

    raw: tuple[str, ...]
    exp: tuple[str, ...]
    line: int

    @property
    def code(self) -> tuple[str, ...]:
        """The rule without ``comment "..."``. A comment is documentation, and
        matching on it would let prose satisfy a pin."""
        out: list[str] = []
        skip = False
        for tok in self.raw:
            if skip:
                skip = False
                continue
            if tok == "comment":
                skip = True
                continue
            out.append(tok)
        return tuple(out)

    @property
    def verdict(self) -> str | None:
        for tok in self.code:
            if tok in _VERDICTS:
                return tok
        return None

    def has(self, *seq: str) -> bool:
        """True when ``seq`` appears as consecutive tokens (as written)."""
        code = self.code
        k = len(seq)
        return any(code[i : i + k] == seq for i in range(len(code) - k + 1))

    def mentions(self, tok: str) -> bool:
        return tok in self.code

    def values_after(self, *keywords: str) -> frozenset[str] | None:
        """The value(s) a match keyword takes, e.g. ``values_after("ip", "saddr")``.

        ``None`` when the keyword is absent — which is what distinguishes an
        unqualified ssh accept from a source-narrowed one.
        """
        code = self.code
        k = len(keywords)
        for i in range(len(code) - k + 1):
            if code[i : i + k] != keywords:
                continue
            j = i + k
            if j < len(code) and code[j] == "!=":
                j += 1
            if j >= len(code):
                return None
            if code[j] != "{":
                return frozenset({code[j]})
            values = set()
            j += 1
            while j < len(code) and code[j] != "}":
                if code[j] != ",":
                    values.add(code[j])
                j += 1
            return frozenset(values)
        return None

    def iface(self, keyword: str) -> tuple[bool, frozenset[str]] | None:
        """``(negated, values)`` for ``iifname``/``oifname``/``iif``/``oif``."""
        code = self.code
        if keyword not in code:
            return None
        i = code.index(keyword) + 1
        negated = False
        if i < len(code) and code[i] == "!=":
            negated = True
            i += 1
        if i >= len(code):
            return None
        if code[i] != "{":
            return negated, frozenset({code[i]})
        values = set()
        i += 1
        while i < len(code) and code[i] != "}":
            if code[i] != ",":
                values.add(code[i])
            i += 1
        return negated, frozenset(values)


@dataclass(frozen=True)
class Chain:
    name: str
    ctype: str | None
    hook: str | None
    priority: str | None
    policy: str | None
    rules: tuple[Rule, ...]

    def accepts(self) -> tuple[Rule, ...]:
        return tuple(r for r in self.rules if r.verdict == "accept")


@dataclass(frozen=True)
class Table:
    family: str
    name: str
    chains: tuple[Chain, ...]

    def chain(self, name: str) -> Chain:
        for c in self.chains:
            if c.name == name:
                return c
        raise KeyError(f"table {self.family} {self.name} has no chain {name}")


@dataclass
class Ruleset:
    defines: dict[str, tuple[str, ...]] = field(default_factory=dict)
    tables: list[Table] = field(default_factory=list)
    #: top-level statements that are not blocks: ``table F N``, ``delete ...``,
    #: ``include "..."`` — in source order.
    top: list[tuple[str, ...]] = field(default_factory=list)

    def table(self, family: str, name: str) -> Table:
        for t in self.tables:
            if t.family == family and t.name == name:
                return t
        raise KeyError(f"no table {family} {name}")

    def all_rules(self) -> tuple[Rule, ...]:
        return tuple(r for t in self.tables for c in t.chains for r in c.rules)

    def includes(self) -> tuple[str, ...]:
        return tuple(s[1] for s in self.top if s and s[0] == "include" and len(s) > 1)


def _split(toks: list[Token], i: int, closing: bool) -> tuple[list[object], int]:
    """Statements until EOF (or the matching ``}``). Blocks nest."""
    stmts: list[object] = []
    cur: list[Token] = []
    while i < len(toks):
        t = toks[i]
        if t.kind == "RBRACE" and closing:
            if cur:
                stmts.append(cur)
            return stmts, i + 1
        if t.kind == "SEP":
            if cur:
                stmts.append(cur)
                cur = []
            i += 1
            continue
        if t.kind == "LBRACE":
            if cur and cur[0].text in _BLOCK_HEADS:
                body, i = _split(toks, i + 1, True)
                stmts.append((cur, body))
                cur = []
                continue
            # anonymous set: swallow to the matching brace, tokens included
            depth = 0
            while i < len(toks):
                tt = toks[i]
                if tt.kind == "LBRACE":
                    depth += 1
                elif tt.kind == "RBRACE":
                    depth -= 1
                if tt.kind != "SEP":
                    cur.append(tt)
                i += 1
                if depth == 0:
                    break
            continue
        cur.append(t)
        i += 1
    if cur:
        stmts.append(cur)
    return stmts, i


def _expand(raw: tuple[str, ...], defines: dict[str, tuple[str, ...]]) -> tuple[str, ...]:
    out: list[str] = []
    for tok in raw:
        if tok.startswith("$") and tok[1:] in defines:
            out.extend(defines[tok[1:]])
        else:
            out.append(tok)
    return tuple(out)


def parse(text: str, defines: dict[str, tuple[str, ...]] | None = None) -> Ruleset:
    """Parse an nft file. ``defines`` seeds variables from an including file."""
    rs = Ruleset(defines=dict(defines or {}))
    stmts, _ = _split(tokenize(text), 0, False)
    for stmt in stmts:
        if isinstance(stmt, tuple):  # (head tokens, body statements)
            head, body = stmt
            words = [t.text for t in head]
            if words[0] != "table" or len(words) < 3:
                continue
            rs.tables.append(_table(words[1], words[2], body, rs.defines))
            continue
        words = tuple(t.text for t in stmt)
        if words[0] == "define" and len(words) >= 3 and words[2] == "=":
            rs.defines[words[1]] = _expand(words[3:], rs.defines)
            continue
        rs.top.append(words)
    return rs


def _table(
    family: str, name: str, body: list[object], defines: dict[str, tuple[str, ...]]
) -> Table:
    chains: list[Chain] = []
    for stmt in body:
        if not isinstance(stmt, tuple):
            continue
        head, inner = stmt
        words = [t.text for t in head]
        if words[0] != "chain" or len(words) < 2:
            continue
        chains.append(_chain(words[1], inner, defines))
    return Table(family, name, tuple(chains))


def _chain(name: str, body: list[object], defines: dict[str, tuple[str, ...]]) -> Chain:
    ctype = hook = priority = policy = None
    rules: list[Rule] = []
    for stmt in body:
        if isinstance(stmt, tuple):  # nested block inside a chain: not our subset
            continue
        words = tuple(t.text for t in stmt)
        if words[0] == "type" and "hook" in words:
            ctype = words[1]
            hook = words[words.index("hook") + 1]
            if "priority" in words:
                priority = words[words.index("priority") + 1]
            continue
        if words[0] == "policy":
            policy = words[1]
            continue
        rules.append(Rule(words, _expand(words, defines), stmt[0].line))
    return Chain(name, ctype, hook, priority, policy, tuple(rules))


# --------------------------------------------------------------------------- #
# fixtures
# --------------------------------------------------------------------------- #
@pytest.fixture(scope="module")
def conf() -> Ruleset:
    return parse(CONF.read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def bridge() -> Ruleset:
    return parse(BRIDGE.read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def lockdown() -> Ruleset:
    return parse(LOCKDOWN.read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def containers(conf: Ruleset) -> Ruleset:
    """``containers.conf`` parsed with the parent file's ``define``s in scope."""
    return parse(CONTAINERS.read_text(encoding="utf-8"), defines=conf.defines)


def _ssh_accepts(rs: Ruleset) -> list[Rule]:
    return [r for r in rs.all_rules() if r.verdict == "accept" and r.has("tcp", "dport", "22")]


# --------------------------------------------------------------------------- #
# the tokenizer itself — a parser nobody has tested is not evidence
# --------------------------------------------------------------------------- #
def test_tokenizer_does_not_confuse_a_set_with_a_block() -> None:
    rs = parse(
        'define a = "e0"\n'
        "table inet t {\n"
        "  chain c {\n"
        "    type filter hook input priority 0; policy drop;\n"
        '    iifname { $a, "e1" } tcp dport { 22, 80 } counter accept comment "drop me"\n'
        "  }\n"
        "}\n"
    )
    chain = rs.table("inet", "t").chain("c")
    assert (chain.ctype, chain.hook, chain.priority, chain.policy) == (
        "filter",
        "input",
        "0",
        "drop",
    )
    assert len(chain.rules) == 1
    rule = chain.rules[0]
    # "drop me" is a comment string, not a verdict, and not three tokens.
    assert rule.verdict == "accept"
    assert rule.iface("iifname") == (False, frozenset({"$a", "e1"}))
    assert rule.exp[rule.raw.index("$a")] == "e0"


def test_tokenizer_ignores_hashes_inside_strings_and_keeps_ranges_whole() -> None:
    rs = parse(
        "define p = 7400-7500\n"
        "table inet t {\n"
        "  chain c {\n"
        '    udp dport $p counter drop comment "a # b"\n'
        "  }\n"
        "}\n"
    )
    rule = rs.table("inet", "t").chain("c").rules[0]
    assert rule.has("udp", "dport", "$p")
    assert rule.exp[rule.raw.index("$p")] == "7400-7500"
    assert "a # b" in rule.raw


# --------------------------------------------------------------------------- #
# P1-P16 — the pre-registered structural rows
# --------------------------------------------------------------------------- #
def test_p1_every_interface_is_a_variable_filled_by_a_box_day_read(conf: Ruleset) -> None:
    for var in IFACE_VARS + PORT_VARS:
        assert var[1:] in conf.defines, f"{var} is not defined in {CONF.name}"
    offenders = [
        (r.line, tok) for r in conf.all_rules() for tok in r.code if _IFACE_LITERAL.match(tok)
    ]
    assert offenders == [], f"hard-coded interface names in rules: {offenders}"


def test_p2_input_chain_defaults_to_drop(conf: Ruleset) -> None:
    chain = conf.table("inet", "parcel").chain("input")
    assert (chain.ctype, chain.hook, chain.priority, chain.policy) == (
        "filter",
        "input",
        "0",
        "drop",
    )


def test_p3_loopback_is_accepted_first(conf: Ruleset) -> None:
    first = conf.table("inet", "parcel").chain("input").rules[0]
    assert first.raw == ("iif", "lo", "accept"), first.raw


def test_p4_forward_policy_is_drop(conf: Ruleset) -> None:
    chain = conf.table("inet", "parcel").chain("forward")
    assert (chain.ctype, chain.hook, chain.priority) == ("filter", "forward", "0")
    assert chain.policy == "drop", "the robot LAN reaches the WAN the moment this stops saying drop"


def test_p5_nothing_is_forwarded_from_the_robot_nic(conf: Ruleset) -> None:
    chain = conf.table("inet", "parcel").chain("forward")
    assert chain.accepts() == (), f"forward accepts: {[r.raw for r in chain.accepts()]}"
    for rule in chain.rules:
        for var in IFACE_VARS:
            assert not rule.mentions(var), f"forward rule names {var}: {rule.raw}"


def test_p6_the_panel_port_is_loopback_only(conf: Ruleset) -> None:
    naming = [r for r in conf.all_rules() if r.mentions("$panelport")]
    assert naming, "no rule mentions $panelport"
    assert all(r.verdict == "drop" for r in naming), [r.raw for r in naming]
    guarded = [r for r in naming if r.iface("iifname") == (True, frozenset({"lo"}))]
    assert guarded, "the panel drop is not qualified `iifname != lo`"
    input_chain = conf.table("inet", "parcel").chain("input")
    idx = input_chain.rules.index(guarded[0])
    earlier = [r for r in input_chain.rules[:idx] if r.verdict == "accept"]
    assert earlier == [input_chain.rules[0]], "the panel drop must sit above every accept but lo"


def test_p7_ssh_survives_on_b_cons_cable_and_the_tailnet_and_nowhere_wide(conf: Ruleset) -> None:
    """Every shell the owner can reach, and every one they cannot open by accident.

    H1: B-con's cable may land on ``$rnic`` (research hw fact 18 puts both dock
    RJ45s on 192.168.123.0/24). The recorded answer is ONE single-host rule above
    the DDS accepts, never a widened set. F3: ADR 0002 item 4 is "remote access
    tailnet-only", so the carrier NIC gets no shell and the home LAN gets one
    only from private space.
    """
    input_rules = conf.table("inet", "parcel").chain("input").rules
    ssh = _ssh_accepts(conf)
    assert ssh, "no ssh accept at all — this locks the owner out of the box"
    for rule in ssh:
        assert rule in input_rules, rule.raw
        negated, ifaces = rule.iface("iifname")
        assert not negated, f"a negated ssh accept opens every other interface: {rule.raw}"
        assert "$lteif" not in ifaces, f"ADR 0002 item 4: the carrier NIC gets no shell: {rule.raw}"

    unqualified = [r for r in ssh if r.values_after("ip", "saddr") is None]
    assert len(unqualified) == 1, [r.raw for r in unqualified]
    _, ifaces = unqualified[0].iface("iifname")
    assert ifaces == frozenset({"$conif", "$tsif"}), ifaces
    assert "$rnic" not in ifaces, "the robot LAN must not get a wide-open shell"

    for rule in ssh:
        _, ifaces = rule.iface("iifname")
        if "$wanif" in ifaces:
            src = rule.values_after("ip", "saddr")
            assert (
                src is not None
                and {
                    "10.0.0.0/8",
                    "172.16.0.0/12",
                    "192.168.0.0/16",
                }
                <= src
            ), f"a shell on the home LAN must be narrowed to private space: {rule.raw}"

    # H1's escape hatch, if the owner ever uncomments it: one host, above DDS.
    on_robot = [r for r in ssh if "$rnic" in r.iface("iifname")[1]]
    assert len(on_robot) <= 1, [r.raw for r in on_robot]
    for rule in on_robot:
        src = rule.values_after("ip", "saddr")
        assert src and all(v.endswith("/32") for v in src), f"not a single host: {rule.raw}"
        dds = next(
            r for r in input_rules if r.verdict == "accept" and r.has("udp", "dport", "$ddsports")
        )
        assert input_rules.index(rule) < input_rules.index(dds), "the B-con rule sits below DDS"


def test_p8_inbound_dds_reaches_us_only_from_the_robot_nic(conf: Ruleset) -> None:
    dds = [r for r in conf.all_rules() if r.has("udp", "dport", "$ddsports")]
    for rule in (r for r in dds if r.verdict == "accept"):
        assert rule.iface("iifname") == (False, frozenset({"$rnic"})), rule.raw
    explicit = [
        r for r in dds if r.verdict == "drop" and r.iface("iifname") == (True, frozenset({"$rnic"}))
    ]
    assert explicit, "no counted drop for DDS arriving on a non-robot interface"


def test_p9_dds_multicast_never_leaves_the_robot_nic(conf: Ruleset) -> None:
    mcast = [r for r in conf.all_rules() if r.mentions("239.255.0.0/16")]
    assert mcast, "the SPDP multicast range is not confined anywhere"
    for rule in mcast:
        assert rule.verdict == "drop", rule.raw
        assert rule.iface("oifname") == (True, frozenset({"$rnic"})), rule.raw


def test_p10_unicast_dds_never_leaves_the_robot_nic(conf: Ruleset) -> None:
    out = conf.table("inet", "parcel").chain("output")
    confined = [
        r
        for r in out.rules
        if r.has("udp", "dport", "$ddsports")
        and r.verdict == "drop"
        and r.iface("oifname") == (True, frozenset({"$rnic"}))
    ]
    assert confined, "egress unicast DDS is unconfined (the stopgap's gap)"


def test_p11_livox_traffic_is_confined_to_its_own_nic(conf: Ruleset) -> None:
    livox = [r for r in conf.all_rules() if r.has("udp", "dport", "$livoxports")]
    accepts = [r for r in livox if r.verdict == "accept"]
    assert len(accepts) == 1, [r.raw for r in accepts]
    assert accepts[0].iface("iifname") == (False, frozenset({"$lnic"}))
    assert accepts[0] in conf.table("inet", "parcel").chain("input").rules
    egress = [
        r
        for r in conf.table("inet", "parcel").chain("output").rules
        if r.has("udp", "dport", "$livoxports")
        and r.verdict == "drop"
        and r.iface("oifname") == (True, frozenset({"$lnic"}))
    ]
    assert egress, "Livox control frames may leave over any interface"


def test_p12_the_ruleset_loads_before_the_interfaces_exist(conf: Ruleset) -> None:
    """``iif``/``oif`` resolve a device index at load time and FAIL when it is absent."""
    for rule in conf.all_rules():
        for i, tok in enumerate(rule.raw):
            if tok in ("iif", "oif"):
                assert rule.raw[i + 1] == "lo", f"{tok} on a non-lo device: {rule.raw}"


def test_p13_every_file_is_idempotent_and_never_flushes(
    conf: Ruleset, bridge: Ruleset, lockdown: Ruleset
) -> None:
    # Statements, not raw text: the file explains in a comment why it does not
    # flush, and a grep would read that explanation as the offence.
    for rs, family, name in (
        (conf, "inet", "parcel"),
        (bridge, "bridge", "parcel_l2"),
        (lockdown, "inet", "parcel_lockdown"),
    ):
        statements = list(rs.top) + [r.code for r in rs.all_rules()]
        assert not [s for s in statements if "flush" in s], "flush would take Docker's tables too"
        create = rs.top.index(("table", family, name))
        delete = rs.top.index(("delete", "table", family, name))
        assert create < delete, f"{family} {name}: create must precede delete"
        rs.table(family, name)  # and the block itself exists


def test_p14_bridged_frames_are_dropped_without_br_netfilter(
    conf: Ruleset, bridge: Ruleset
) -> None:
    """H2: the L2 half is a SEPARATE file, because ``nft -f`` is one atomic batch.

    A kernel without ``CONFIG_NF_TABLES_BRIDGE`` must cost us this table and
    nothing else — if it lived in the main file it would cost us the forwarding
    boundary and the Orin would boot with no rules at all.
    """
    with pytest.raises(KeyError):
        conf.table("bridge", "parcel_l2")
    chain = bridge.table("bridge", "parcel_l2").chain("forward")
    assert (chain.hook, chain.policy) == ("forward", "drop")
    assert chain.accepts() == ()
    for rule in bridge.all_rules():
        assert not [tok for tok in rule.code if tok.startswith("$")], (
            f"the bridge file must load on a box whose defines are unfilled: {rule.raw}"
        )


def test_p15_container_accepts_are_opt_in_and_scoped(conf: Ruleset, containers: Ruleset) -> None:
    assert conf.includes() == (), f"the main ruleset includes {conf.includes()}"
    assert "dockerif" in containers.defines
    accepts = [r for r in containers.all_rules() if r.verdict == "accept"]
    assert accepts, "containers.conf has no accepts, so it is pointless"
    for rule in accepts:
        scoped = [
            values
            for values in (
                rule.values_after("iifname"),
                rule.values_after("oifname"),
                rule.values_after("meta", "ibrname"),
                rule.values_after("meta", "obrname"),
            )
            if values and "$dockerif" in values
        ]
        assert scoped, f"container accept not scoped to $dockerif: {rule.raw}"
    for rule in containers.all_rules():
        assert not rule.mentions("$rnic"), rule.raw
        assert not rule.mentions("$lnic"), rule.raw
    # F5: container-to-container on one Docker bridge is BRIDGED traffic. It
    # meets `bridge parcel_l2 forward policy drop`, never `inet forward`, so an
    # inet-only opt-in file would leave the compose stubs unable to talk.
    l2 = containers.table("bridge", "parcel_l2").chain("forward")
    assert l2.accepts(), "no bridge-family accept: container-to-container stays dropped"
    for rule in l2.accepts():
        assert rule.values_after("meta", "ibrname") == frozenset({"$dockerif"}), rule.raw
        assert rule.values_after("meta", "obrname") == frozenset({"$dockerif"}), rule.raw


def test_p16_the_unit_persists_it_and_rolls_back_cleanly() -> None:
    lines = [ln.strip() for ln in UNIT.read_text(encoding="utf-8").splitlines()]
    body = [ln for ln in lines if ln and not ln.startswith("#")]
    before = [ln for ln in body if ln.startswith("Before=")]
    assert before and any("network-pre.target" in ln for ln in before)
    assert "DefaultDependencies=no" in body
    assert "WantedBy=sysinit.target" in body
    starts = [ln.split("=", 1)[1] for ln in body if ln.startswith("ExecStart=")]
    assert len(starts) == 3, starts
    assert " -c -f " in f" {starts[0]} ", "the unit loads without checking first"
    assert starts[0].rsplit(" ", 1)[-1] == starts[1].rsplit(" ", 1)[-1], "checks a different file"
    # H2: the bridge half is best-effort. `-` means a kernel that cannot take it
    # does not take the forwarding boundary down with it.
    assert starts[2].startswith("-"), f"the bridge load is not failure-tolerant: {starts[2]}"
    assert starts[2].endswith("nftables-bridge.conf"), starts[2]
    assert any(ln == "OnFailure=parcel-nftables-lockdown.service" for ln in body), (
        "no fallback: a failed load leaves the Orin with zero tables while the WAN comes up"
    )
    stops = " ".join(ln for ln in body if ln.startswith("ExecStop="))
    assert "delete table inet parcel" in stops
    assert "delete table bridge parcel_l2" in stops
    assert "flush ruleset" not in stops


def test_p16b_the_lockdown_unit_is_triggered_only_and_variable_free(lockdown: Ruleset) -> None:
    """H2's fallback: what holds when the real ruleset cannot be loaded at all."""
    body = [
        ln.strip()
        for ln in LOCKDOWN_UNIT.read_text(encoding="utf-8").splitlines()
        if ln.strip() and not ln.strip().startswith("#")
    ]
    assert "[Install]" not in body, "the fallback must not be enabled; OnFailure starts it"
    assert not [ln for ln in body if ln.startswith("WantedBy=")], body
    starts = [ln.split("=", 1)[1] for ln in body if ln.startswith("ExecStart=")]
    assert len(starts) == 1 and starts[0].endswith("nftables-lockdown.conf"), starts
    assert any(ln.startswith("Before=") and "network-pre.target" in ln for ln in body)

    fwd = lockdown.table("inet", "parcel_lockdown").chain("forward")
    assert (fwd.hook, fwd.policy) == ("forward", "drop"), "the fallback drops the sentence"
    assert fwd.accepts() == ()
    inp = lockdown.table("inet", "parcel_lockdown").chain("input")
    assert inp.policy == "drop"
    assert inp.rules[0].code == ("iif", "lo", "accept")
    assert any(r.has("ct", "state", "established", ",", "related") for r in inp.accepts())
    ssh = _ssh_accepts(lockdown)
    wide = [r for r in ssh if "!=" in r.code]
    assert len(wide) == 1, [r.raw for r in wide]
    assert wide[0].values_after("ip", "saddr") == frozenset({"192.168.123.0/24"}), wide[0].raw
    # R2-F1: a step-0.5-route-2 owner is INSIDE that /24, so the fallback cannot
    # reach them. The one sanctioned answer is the same single-host template as
    # nftables.conf — never a wider positive accept.
    narrow = [r for r in ssh if r not in wide]
    assert len(narrow) <= 1, [r.raw for r in narrow]
    for rule in narrow:
        src = rule.values_after("ip", "saddr")
        assert src and all(v.endswith("/32") for v in src), f"not a single host: {rule.raw}"
    for rule in lockdown.all_rules():
        assert not [tok for tok in rule.code if tok.startswith("$")], (
            f"a wrong define is one of the failures this file covers: {rule.raw}"
        )


# --------------------------------------------------------------------------- #
# P17-P19 — the three lockout-class sentences the first pass left unpinned
# (verifier seeds V3/V4/V5 all passed green against the original module)
# --------------------------------------------------------------------------- #
def test_p17_return_traffic_is_accepted_before_anything_is_dropped(conf: Ruleset) -> None:
    """Without this, every ssh accept is ``ct state new`` only and the shell dies
    the moment the handshake completes."""
    rules = conf.table("inet", "parcel").chain("input").rules
    established = [
        i
        for i, r in enumerate(rules)
        if r.verdict == "accept" and r.has("ct", "state", "established", ",", "related")
    ]
    assert established, "input never accepts return traffic"
    ssh = _ssh_accepts(conf)
    assert established[0] < min(rules.index(r) for r in ssh), "return traffic is accepted after ssh"


def test_p18_the_output_chain_does_not_default_to_drop(conf: Ruleset) -> None:
    """An outbound default-drop on a box reachable only over the network is how
    box day ends early: sshd's own replies would be dropped."""
    out = conf.table("inet", "parcel").chain("output")
    if out.policy != "accept":
        assert any(
            r.verdict == "accept" and r.has("ct", "state", "established", ",", "related")
            for r in out.rules
        ), "output is policy drop with no return-traffic accept: every reply dies"


def test_p19_ipv6_neighbour_discovery_and_mld_survive_the_default_drop(conf: Ruleset) -> None:
    icmpv6 = [r for r in conf.all_rules() if r.verdict == "accept" and "icmpv6" in r.code]
    assert icmpv6, "no ICMPv6 accept at all: an inet input drop is an IPv6 outage"
    types: set[str] = set()
    for rule in icmpv6:
        values = rule.values_after("icmpv6", "type")
        if values:
            types |= set(values)
    nd = {"nd-neighbor-solicit", "nd-neighbor-advert", "nd-router-solicit", "nd-router-advert"}
    assert nd <= types, f"missing ND types: {sorted(nd - types)}"
    mld = {"mld-listener-query", "mld-listener-report", "mld-listener-done", "mld2-listener-report"}
    assert mld <= types, f"missing MLD types: {sorted(mld - types)}"


# --------------------------------------------------------------------------- #
# N1 — nft's own parser, when the box has one
# --------------------------------------------------------------------------- #
#: A diagnostic line from nft's parser: ``<path>:<line>:<col>[-<col>]: Error: …``.
#: nft prints the path exactly as it was passed, so anchoring on a basename (as
#: the first pass did) makes this function incapable of returning anything —
#: verifier finding F1. Anchor on the passed path.
_NFT_DIAG = re.compile(r"^(?P<path>.+?):\d+:\d+(?:-\d+)?: Error: ")


def _nft_diagnostics(path: Path) -> list[str]:
    """Parse diagnostics ``nft -c -f`` reports against ``path``.

    ``-c`` is check-only and never loads. Unprivileged it stops at the netlink
    cache (``Operation not permitted``), so on this desktop the result is a
    SYNTAX verdict only: undefined ``$vars``, unknown hooks and bad CIDRs are
    caught, but anything needing the kernel cache (``ct state invalidd``, a
    missing chain type, a ``jump`` to nowhere) is not. Root on the Orin gets the
    rest — see ``deploy/orin/README.md`` §1.
    """
    # -c only. This module never builds an `nft -f` argv, on any host.
    proc = subprocess.run(
        [shutil.which("nft") or "nft", "-c", "-f", str(path)],
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )
    blob = f"{proc.stdout}\n{proc.stderr}"
    out = []
    for line in blob.splitlines():
        match = _NFT_DIAG.match(line)
        if match and match.group("path") == str(path):
            out.append(line)
    return out


@pytest.mark.skipif(shutil.which("nft") is None, reason="nft is not installed on this host")
def test_n1_nft_parses_every_ruleset_and_the_container_include() -> None:
    for ruleset in (CONF, BRIDGE, LOCKDOWN):
        assert _nft_diagnostics(ruleset) == [], ruleset.name
    # containers.conf borrows the parent's defines, so it is checked the way it
    # is used: through the include line, enabled in a copy outside the repo.
    with tempfile.TemporaryDirectory() as tmp:
        combined = Path(tmp) / "combined.conf"
        text = CONF.read_text(encoding="utf-8").replace(
            '# include "/etc/parcel/containers.conf"', f'include "{CONTAINERS}"'
        )
        assert "include " in text, "the opt-in include line is no longer in the ruleset"
        combined.write_text(text, encoding="utf-8")
        assert _nft_diagnostics(combined) == []


@pytest.mark.skipif(shutil.which("nft") is None, reason="nft is not installed on this host")
def test_n1_liveness_a_broken_copy_must_produce_a_diagnostic() -> None:
    """F1: a check that cannot fail is not a check. Seed a syntax error into a
    copy outside the repo and prove the reader sees it, at the right line."""
    with tempfile.TemporaryDirectory() as tmp:
        broken = Path(tmp) / "broken.conf"
        lines = CONF.read_text(encoding="utf-8").splitlines(keepends=True)
        i = next(k for k, ln in enumerate(lines) if "policy drop;" in ln)
        lines[i] = lines[i].replace("policy drop;", "policy dropp;")
        broken.write_text("".join(lines), encoding="utf-8")
        diagnostics = _nft_diagnostics(broken)
        assert diagnostics, "nft accepted `policy dropp` — the reader is blind"
        assert diagnostics[0].startswith(f"{broken}:{i + 1}:"), diagnostics
