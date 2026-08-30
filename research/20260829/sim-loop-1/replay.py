"""LIT-1 replay — one JSONL hop log into one self-contained HTML timeline.

The "well-lit" part of the experiment: speech and movement on ONE axis, so a
reader can see that the robot was still walking while the owner was talking, and
exactly how long after the sentence landed the body turned.

Constraints this file honours, all of them binding:

* **self-contained** — no external assets, no CDN, no fonts, no images.  One
  ``<style>``, one ``<script>``, inline SVG.  It opens from a file:// URL on a
  machine with no network;
* **amendment L4** — the held-out scene is never named.  The renderer draws
  only names the log already passed the positive allowlist, and it applies the
  scenario's ``replay_labels`` (stand-in -> pretty) at DISPLAY time only, which
  is the one place the pretty names are allowed to exist;
* **amendment L10** — every hop keeps its provenance (``sim | fake | real |
  hosted | harness``) and the swap table is rendered, so nobody reads a fake
  row as a hosted one.

Usage
-----
``.parcel/bin/python research/20260829/sim-loop-1/replay.py <jsonl> --html out.html``
"""

from __future__ import annotations

import argparse
import html
import json
import math
from pathlib import Path

#: Provenance -> (label, colour).  Deliberately a small, fixed palette that
#: reads in both light and dark: the page sets its own background, so these are
#: chosen against a mid-dark panel and given a light-mode override in the CSS.
PROVENANCE = {
    "sim": ("sim (MuJoCo static city, via the live runtime)", "#4c8dff"),
    "fake": ("fake (scripted FakeRealtimeServer)", "#b07cf0"),
    "hosted": ("hosted (live Realtime lane, billed)", "#f0803c"),
    "real": ("real (hardware in the loop)", "#3cc98a"),
    "harness": ("harness (LIT-1's own bookkeeping)", "#8a93a5"),
}

#: Which hops become lanes on the timeline, in the order they are drawn.
LANES = (
    ("speech", "owner speech", ("owner_speech_start", "owner_speech_stop")),
    ("cue", "cue / intent", ("cue", "sim_state_trigger", "steering_decision", "re_issue")),
    ("receipt", "executive receipts", ("receipt",)),
    ("whisper", "Model B whisper", ("whisper_injection",)),
    (
        "voice",
        "voice",
        (
            "voice_turn",
            "voice_turn_refused",
            "narration_event",
            "voice_offer",
            "voice_session_open",
            "voice_session_arming",
            "voice_session_refused",
            "governor_snapshot",
        ),
    ),
    ("arrival", "arrival authority", ("arrival_authority", "await_terminal", "switch_latency")),
)


def load(path: Path) -> list[dict]:
    rows: list[dict] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            rows.append(json.loads(line))
        except ValueError:
            continue
    return sorted(rows, key=lambda row: float(row.get("t") or 0.0))


def _labels(rows: list[dict]) -> dict[str, str]:
    """The stand-in -> pretty display map, taken from the run header.

    This is the ONLY place the pretty names enter the artifact, and they enter
    it as *labels on a chart*, never as text handed to a runtime or a model.
    """

    for row in rows:
        if row.get("hop") == "run_header":
            return {
                str(key): str(value)
                for key, value in (row.get("alias_table") or {}).items()
            }
    return {}


def _pretty(text: str, labels: dict[str, str]) -> str:
    """Render stand-in names with their scenario label beside them.

    Not a replacement — an annotation.  Replacing "lamppost" with "door" would
    make the replay disagree with the JSONL it came from; showing
    "lamppost (the door)" keeps both true at once.
    """

    out = str(text)
    for pretty, standin in labels.items():
        if standin and standin in out:
            out = out.replace(standin, f"{standin} ({pretty})")
    return out


def _summary(row: dict, labels: dict[str, str]) -> str:
    hop = str(row.get("hop"))
    if hop == "receipt":
        return (
            f"{row.get('kind')} — action={row.get('action')} "
            f"state={row.get('state')} rev={row.get('plan_revision')} "
            f"detail={row.get('last_detail')}"
        )
    if hop in {"owner_speech_start", "owner_speech_stop"}:
        return _pretty(str(row.get("text") or ""), labels)
    if hop == "cue":
        return (
            f"intent={row.get('closed_intent') or '(none)'} "
            f"source={row.get('reasoning_source')} "
            f"amend_ok={row.get('goal_amend_ok')}"
        )
    if hop == "sim_state_trigger":
        return (
            f"trigger fired: {row.get('fired')} at "
            f"{float(row.get('progress') or 0):.1%} of the reference path"
        )
    if hop == "steering_decision":
        return f"{row.get('label')} — {row.get('reason')}"
    if hop == "re_issue":
        return f"re-issue: {_pretty(str(row.get('text') or ''), labels)}"
    if hop == "whisper_injection":
        return (
            f"plan-queue item {row.get('item_id')} "
            f"(replaces {row.get('supersedes') or '—'}), "
            f"~{row.get('approx_tokens')} tokens, billed={row.get('billed')}"
        )
    if hop == "voice_turn":
        return (
            f"heard: {_pretty(str(row.get('heard') or ''), labels)}<br>"
            f"said: {_pretty(str(row.get('spoken') or ''), labels)} "
            f"(TTFT {row.get('ttft_ms')} ms, billed={row.get('billed')})"
        )
    if hop == "voice_turn_refused":
        return f"REFUSED: {row.get('error')}"
    if hop == "narration_event":
        return (
            f"{'spoke' if row.get('taken') else 'floor taken'}: "
            f"{_pretty(str(row.get('spoken') or row.get('fact') or ''), labels)}"
        )
    if hop == "voice_offer":
        return f"robot offers: {_pretty(str(row.get('text') or ''), labels)}"
    if hop == "voice_session_open":
        return f"session {row.get('session_id')} (provider {row.get('provider_session_id')})"
    if hop == "voice_session_arming":
        return (
            f"arming: armed={row.get('armed')} code={row.get('code')} "
            f"reason={row.get('reason')}"
        )
    if hop == "voice_session_refused":
        return f"no session: {row.get('reason')} — {row.get('detail')}"
    if hop == "governor_snapshot":
        return f"governor: {json.dumps(row.get('snapshot'), default=str)[:400]}"
    if hop == "await_terminal":
        return f"terminal states: {row.get('states')}"
    if hop == "arrival_authority":
        if not row.get("scored"):
            return f"{row.get('goal')}: not scored ({row.get('reason')})"
        return (
            f"{row.get('goal')}: system={row.get('system_arrival')} "
            f"scorer={row.get('scorer_arrival')} "
            f"→ {row.get('authority_category')}"
        )
    if hop == "switch_latency":
        return (
            f"switch {row.get('switch_ms')} ms · cue→receipt "
            f"{row.get('cue_to_receipt_ms')} ms · first receipt "
            f"{row.get('first_receipt_kind')}"
        )
    return ""


def _lane_of(hop: str) -> str | None:
    for key, _label, hops in LANES:
        if hop in hops:
            return key
    return None


def render(rows: list[dict], *, title: str) -> str:
    labels = _labels(rows)
    header = next((row for row in rows if row.get("hop") == "run_header"), {})
    footer = next((row for row in rows if row.get("hop") == "run_footer"), {})
    motion = [row for row in rows if row.get("hop") == "motion"]
    events = [row for row in rows if _lane_of(str(row.get("hop"))) is not None]
    t_max = max((float(row.get("t") or 0.0) for row in rows), default=1.0) or 1.0

    speed_path, yaw_path = _motion_paths(motion, t_max)
    track_svg = _track_svg(motion)
    lane_rows = _lane_rows(events, labels, t_max)
    table_rows = _table_rows(events, labels)
    swap = header.get("swap_table") or []
    leaks = footer.get("name_scan_leaks") or []

    return _PAGE.format(
        title=html.escape(title),
        scenario=html.escape(str(header.get("scenario") or "?")),
        variant=html.escape(str(header.get("variant") or "base")),
        voice=html.escape(str(header.get("voice") or "?")),
        seed=html.escape(str(header.get("seed") or "?")),
        wall=html.escape(str(header.get("t_wall") or "")),
        duration=f"{t_max:.1f}",
        kinds=html.escape(json.dumps(footer.get("receipt_kinds") or [])),
        spend=html.escape(str(footer.get("spend_usd") if footer else "—")),
        legend="".join(
            f'<span class="chip"><i style="background:{colour}"></i>{html.escape(label)}</span>'
            for _key, (label, colour) in PROVENANCE.items()
        ),
        swap="".join(
            f"<tr><td>{html.escape(str(a))}</td><td>{html.escape(str(b))}</td>"
            f"<td>{html.escape(str(c))}</td></tr>"
            for a, b, c in (row for row in swap if len(row) == 3)
        )
        or '<tr><td colspan="3">no swap table in this log</td></tr>',
        leaks=(
            '<p class="ok">Name scan: no unadmitted place name reached this artifact.</p>'
            if not leaks
            else '<p class="warn">Name scan: '
            + html.escape(json.dumps(leaks))
            + " — redacted in place and counted.</p>"
        ),
        speed_path=speed_path,
        yaw_path=yaw_path,
        track=track_svg,
        lanes=lane_rows,
        table=table_rows,
        t_max=f"{t_max:.1f}",
    )


def _motion_paths(motion: list[dict], t_max: float) -> tuple[str, str]:
    if not motion:
        return ("", "")
    speeds = []
    yaws = []
    for row in motion:
        t = float(row.get("t") or 0.0)
        vx = float(row.get("vx") or 0.0)
        vy = float(row.get("vy") or 0.0)
        speeds.append((t, math.hypot(vx, vy)))
        yaws.append((t, abs(float(row.get("vyaw") or 0.0))))
    top_speed = max((v for _t, v in speeds), default=1.0) or 1.0
    top_yaw = max((v for _t, v in yaws), default=1.0) or 1.0

    def _path(points, top):
        return " ".join(
            f"{'M' if index == 0 else 'L'}{(t / t_max) * 1000:.2f},"
            f"{60 - (value / top) * 55:.2f}"
            for index, (t, value) in enumerate(points)
        )

    return (_path(speeds, top_speed), _path(yaws, top_yaw))


def _track_svg(motion: list[dict]) -> str:
    if not motion:
        return '<text x="10" y="20" fill="currentColor">no pose samples</text>'
    xs = [float(row.get("x") or 0.0) for row in motion]
    ys = [float(row.get("y") or 0.0) for row in motion]
    x0, x1 = min(xs), max(xs)
    y0, y1 = min(ys), max(ys)
    span = max(x1 - x0, y1 - y0, 1e-3)

    def _project(x: float, y: float) -> tuple[float, float]:
        return (10 + (x - x0) / span * 280, 290 - (y - y0) / span * 280)

    points = " ".join(
        f"{'M' if index == 0 else 'L'}{px:.1f},{py:.1f}"
        for index, (px, py) in enumerate(_project(x, y) for x, y in zip(xs, ys, strict=False))
    )
    sx, sy = _project(xs[0], ys[0])
    ex, ey = _project(xs[-1], ys[-1])
    return (
        f'<path d="{points}" fill="none" stroke="var(--sim)" stroke-width="2"/>'
        f'<circle cx="{sx:.1f}" cy="{sy:.1f}" r="5" fill="var(--ok)"/>'
        f'<circle cx="{ex:.1f}" cy="{ey:.1f}" r="5" fill="var(--warn)"/>'
        f'<text x="{sx + 8:.1f}" y="{sy:.1f}" fill="currentColor" font-size="11">start</text>'
        f'<text x="{ex + 8:.1f}" y="{ey:.1f}" fill="currentColor" font-size="11">end</text>'
    )


def _lane_rows(events: list[dict], labels: dict[str, str], t_max: float) -> str:
    out: list[str] = []
    for key, label, _hops in LANES:
        marks: list[str] = []
        for row in events:
            if _lane_of(str(row.get("hop"))) != key:
                continue
            t = float(row.get("t") or 0.0)
            provenance = str(row.get("provenance") or "harness")
            colour = PROVENANCE.get(provenance, PROVENANCE["harness"])[1]
            tip = html.escape(f"t={t:.3f}s · {row.get('hop')} · {_summary(row, labels)}")
            marks.append(
                f'<i class="mark" style="left:{(t / t_max) * 100:.3f}%;background:{colour}" '
                f'title="{tip}"></i>'
            )
        out.append(
            f'<div class="lane"><div class="lane-name">{html.escape(label)}</div>'
            f'<div class="lane-track">{"".join(marks)}</div></div>'
        )
    return "".join(out)


def _table_rows(events: list[dict], labels: dict[str, str]) -> str:
    out: list[str] = []
    for row in events:
        provenance = str(row.get("provenance") or "harness")
        colour = PROVENANCE.get(provenance, PROVENANCE["harness"])[1]
        summary = _summary(row, labels)
        out.append(
            f'<tr data-prov="{html.escape(provenance)}">'
            f'<td class="t">{float(row.get("t") or 0.0):.3f}</td>'
            f'<td><span class="dot" style="background:{colour}"></span>'
            f"{html.escape(provenance)}</td>"
            f'<td class="hop">{html.escape(str(row.get("hop")))}</td>'
            f"<td>{summary}</td></tr>"
        )
    return "".join(out)


_PAGE = """<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{title}</title>
<style>
  :root {{
    --bg:#ffffff; --fg:#16181d; --muted:#5b6270; --panel:#f4f6f9; --line:#dfe3ea;
    --sim:#2f6fd0; --fake:#8a4fd8; --hosted:#c85a1a; --ok:#1a8a5a; --warn:#c2410c;
  }}
  @media (prefers-color-scheme: dark) {{
    :root:not([data-theme="light"]) {{
      --bg:#12141a; --fg:#e6e9ef; --muted:#98a1b3; --panel:#1b1f27; --line:#2b313d;
      --sim:#4c8dff; --fake:#b07cf0; --hosted:#f0803c; --ok:#3cc98a; --warn:#f59e5b;
    }}
  }}
  :root[data-theme="dark"] {{
    --bg:#12141a; --fg:#e6e9ef; --muted:#98a1b3; --panel:#1b1f27; --line:#2b313d;
    --sim:#4c8dff; --fake:#b07cf0; --hosted:#f0803c; --ok:#3cc98a; --warn:#f59e5b;
  }}
  * {{ box-sizing:border-box; }}
  body {{ margin:0; background:var(--bg); color:var(--fg);
    font:14px/1.5 ui-sans-serif,system-ui,-apple-system,"Segoe UI",Roboto,sans-serif; }}
  main {{ max-width:1180px; margin:0 auto; padding:24px 20px 64px; }}
  h1 {{ font-size:20px; margin:0 0 4px; letter-spacing:-0.01em; }}
  h2 {{ font-size:15px; margin:32px 0 10px; letter-spacing:-0.01em; }}
  .sub {{ color:var(--muted); margin:0 0 18px; }}
  .meta {{ display:flex; flex-wrap:wrap; gap:8px 20px; margin:0 0 18px;
    padding:12px 14px; background:var(--panel); border:1px solid var(--line);
    border-radius:8px; }}
  .meta div {{ font-size:13px; }}
  .meta b {{ color:var(--muted); font-weight:500; }}
  .chip {{ display:inline-flex; align-items:center; gap:6px; margin-right:14px;
    font-size:12px; color:var(--muted); }}
  .chip i {{ width:10px; height:10px; border-radius:3px; display:inline-block; }}
  .lane {{ display:flex; align-items:center; gap:10px; margin:0 0 6px; }}
  .lane-name {{ width:150px; flex:0 0 150px; text-align:right; font-size:12px;
    color:var(--muted); }}
  .lane-track {{ position:relative; flex:1; height:20px; background:var(--panel);
    border:1px solid var(--line); border-radius:4px; }}
  .mark {{ position:absolute; top:3px; width:4px; height:12px; border-radius:2px;
    transform:translateX(-2px); cursor:help; }}
  .mark:hover {{ height:18px; top:0; width:6px; }}
  .axis {{ display:flex; justify-content:space-between; margin:2px 0 0 160px;
    font-size:11px; color:var(--muted); }}
  .charts {{ display:flex; flex-wrap:wrap; gap:20px; align-items:flex-start; }}
  .chart {{ flex:1 1 420px; min-width:300px; }}
  .chart svg {{ width:100%; height:auto; display:block; background:var(--panel);
    border:1px solid var(--line); border-radius:6px; }}
  .scroll {{ overflow-x:auto; }}
  table {{ border-collapse:collapse; width:100%; font-size:13px; }}
  th, td {{ text-align:left; padding:6px 10px; border-bottom:1px solid var(--line);
    vertical-align:top; }}
  th {{ color:var(--muted); font-weight:500; font-size:12px; position:sticky; top:0;
    background:var(--bg); }}
  td.t {{ font-variant-numeric:tabular-nums; color:var(--muted); white-space:nowrap; }}
  td.hop {{ font-family:ui-monospace,SFMono-Regular,Menlo,monospace; font-size:12px; }}
  .dot {{ width:8px; height:8px; border-radius:50%; display:inline-block;
    margin-right:6px; }}
  .ok {{ color:var(--ok); }}
  .warn {{ color:var(--warn); }}
  .note {{ color:var(--muted); font-size:12px; max-width:70ch; }}
</style></head><body><main>
<h1>{title}</h1>
<p class="sub">Speech and movement on one axis. Every mark is one hop from the run's
JSONL; hover a mark for its verbatim fields.</p>

<div class="meta">
  <div><b>scenario</b> {scenario}</div>
  <div><b>variant</b> {variant}</div>
  <div><b>voice</b> {voice}</div>
  <div><b>seed</b> {seed}</div>
  <div><b>started</b> {wall}</div>
  <div><b>duration</b> {duration}s</div>
  <div><b>$ this run</b> {spend}</div>
</div>
<p class="note"><b>receipt KIND sequence:</b> <code>{kinds}</code></p>
<div>{legend}</div>

<h2>Timeline</h2>
{lanes}
<div class="axis"><span>0 s</span><span>{t_max} s</span></div>

<h2>Body</h2>
<div class="charts">
  <div class="chart">
    <svg viewBox="0 0 1000 70" preserveAspectRatio="none" role="img"
         aria-label="commanded speed over time">
      <path d="{speed_path}" fill="none" stroke="var(--sim)" stroke-width="2"
            vector-effect="non-scaling-stroke"/>
    </svg>
    <p class="note">commanded speed |(vx, vy)| on the body lane, normalised</p>
  </div>
  <div class="chart">
    <svg viewBox="0 0 1000 70" preserveAspectRatio="none" role="img"
         aria-label="commanded yaw rate over time">
      <path d="{yaw_path}" fill="none" stroke="var(--fake)" stroke-width="2"
            vector-effect="non-scaling-stroke"/>
    </svg>
    <p class="note">commanded |vyaw|, normalised — the turn predicate's input</p>
  </div>
  <div class="chart" style="flex:0 0 320px">
    <svg viewBox="0 0 300 300" role="img" aria-label="ground track">{track}</svg>
    <p class="note">ground track (x, y), start green, end amber</p>
  </div>
</div>

<h2>Every hop</h2>
<div class="scroll">
<table><thead><tr><th>t (s)</th><th>provenance</th><th>hop</th><th>what</th></tr></thead>
<tbody>{table}</tbody></table>
</div>

<h2>Provenance and the real-swap table</h2>
<div class="scroll">
<table><thead><tr><th>hop</th><th>what ran here</th><th>what replaces it</th></tr></thead>
<tbody>{swap}</tbody></table>
</div>
{leaks}
<p class="note">Tier: sim harness with real-swappable hops. Place names are the
scenario's stand-ins; the pretty label in parentheses is a display annotation
only and was never handed to the runtime or to any model.</p>
</main></body></html>
"""


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="LIT-1 — JSONL to an HTML timeline")
    parser.add_argument("jsonl")
    parser.add_argument("--html", required=True)
    parser.add_argument("--title", default="")
    args = parser.parse_args(argv)

    source = Path(args.jsonl)
    rows = load(source)
    if not rows:
        raise SystemExit(f"no rows in {source}")
    title = args.title or f"LIT-1 replay — {source.stem}"
    output = Path(args.html)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(render(rows, title=title), encoding="utf-8")
    size = output.stat().st_size
    print(f"wrote {output} ({size / 1024:.1f} KiB, {len(rows)} rows)")
    if size > 2 * 1024 * 1024:
        print("WARNING: over the 2 MB artifact bar")
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
