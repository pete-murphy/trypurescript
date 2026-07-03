#!/usr/bin/env python3
"""Render mem-report/report.html from mem-report/results.json.

Self-contained output: inline CSS + inline SVG, no npm, no CDN, no network.
"""
import json
import os

HERE = os.path.dirname(os.path.abspath(__file__))
RESULTS = os.path.join(HERE, "results.json")
OUT = os.path.join(HERE, "report.html")

M3G_MB = 3 * 1024          # -M3G cap
DROPLET_MB = 3891          # droplet RAM (3.8 GiB)

SCENARIOS = ["full", "trim-current", "trim-cannot-run"]
LABELS = {
    "full": "full (untrimmed 77.6.0)",
    "trim-current": "trim-current (branch HEAD)",
    "trim-cannot-run": "trim-cannot-run",
}


def direct_deps(scenario):
    lock = json.load(open(os.path.join(HERE, "scenarios", scenario, "spago.lock")))
    return len(lock["workspace"]["packages"]["try-purescript-server"]["core"]["dependencies"])


def load():
    runs = json.load(open(RESULTS))
    by = {}
    for r in runs:
        by[(r["scenario"], r["mode"], r["maxheap"])] = r
    return runs, by


def get(by, scen, mode, heap):
    return by.get((scen, mode, heap))


def mb(r, key="max_live_mb"):
    return r.get(key) if r else None


def modules_of(by, scen):
    for mode, heap in [("cold", "8G"), ("warm", "8G"), ("warm", "3G"), ("cold", "3G")]:
        r = get(by, scen, mode, heap)
        if r:
            for k in ("modules_compiled", "sparks"):
                if r.get(k):
                    return r[k]
    return None


def bar_chart(by):
    """Grouped bars: per scenario, cold & warm maxLive (MB) from the -M8G runs."""
    w, h = 760, 420
    ml, mr, mt, mbot = 70, 20, 30, 60
    plot_w, plot_h = w - ml - mr, h - mt - mbot
    vals = []
    for s in SCENARIOS:
        for mode in ("cold", "warm"):
            r = get(by, s, mode, "8G")
            vals.append(mb(r) or 0)
    ymax = max(vals + [DROPLET_MB]) * 1.15
    def y(v):
        return mt + plot_h - (v / ymax) * plot_h

    group_w = plot_w / len(SCENARIOS)
    bar_w = group_w * 0.28
    colors = {"cold": "#4e79a7", "warm": "#e15759"}
    parts = []
    parts.append(f'<svg viewBox="0 0 {w} {h}" font-family="system-ui,sans-serif" font-size="13">')
    # y gridlines
    step = 500
    v = 0
    while v <= ymax:
        yy = y(v)
        parts.append(f'<line x1="{ml}" y1="{yy:.1f}" x2="{w-mr}" y2="{yy:.1f}" stroke="#eee"/>')
        parts.append(f'<text x="{ml-8}" y="{yy+4:.1f}" text-anchor="end" fill="#666" font-size="11">{v:,}</text>')
        v += step
    # reference lines
    for val, label, color in [(M3G_MB, f"-M3G cap ({M3G_MB:,} MiB)", "#b07d02"),
                              (DROPLET_MB, f"droplet RAM ({DROPLET_MB:,} MiB)", "#762a83")]:
        yy = y(val)
        parts.append(f'<line x1="{ml}" y1="{yy:.1f}" x2="{w-mr}" y2="{yy:.1f}" '
                     f'stroke="{color}" stroke-dasharray="6 4" stroke-width="1.5"/>')
        parts.append(f'<text x="{w-mr}" y="{yy-5:.1f}" text-anchor="end" fill="{color}" font-size="11">{label}</text>')
    # bars
    for i, s in enumerate(SCENARIOS):
        cx = ml + group_w * (i + 0.5)
        for j, mode in enumerate(("cold", "warm")):
            r = get(by, s, mode, "8G")
            v = mb(r)
            x = cx + (j - 1) * bar_w + (bar_w * 0.1) * (2 * j - 1)
            if v:
                yy = y(v)
                parts.append(f'<rect x="{x:.1f}" y="{yy:.1f}" width="{bar_w:.1f}" '
                             f'height="{mt+plot_h-yy:.1f}" fill="{colors[mode]}"/>')
                parts.append(f'<text x="{x+bar_w/2:.1f}" y="{yy-5:.1f}" text-anchor="middle" '
                             f'font-size="11" fill="#333">{v:,}</text>')
            else:
                # missing / died run: hatched bar at cap height
                yy = y(M3G_MB)
                parts.append(f'<rect x="{x:.1f}" y="{yy:.1f}" width="{bar_w:.1f}" '
                             f'height="{mt+plot_h-yy:.1f}" fill="url(#hatch)" stroke="{colors[mode]}"/>')
                parts.append(f'<text x="{x+bar_w/2:.1f}" y="{yy-5:.1f}" text-anchor="middle" '
                             f'font-size="11" fill="#333">died</text>')
        label = LABELS[s].split(" (")[0]
        parts.append(f'<text x="{cx:.1f}" y="{h-mbot+20}" text-anchor="middle">{label}</text>')
        # -M3G warm verdict badge
        r3 = get(by, s, "warm", "3G")
        if r3:
            ok = r3["outcome"] == "ok"
            badge = "survives -M3G warm" if ok else "dies at -M3G warm"
            color = "#2a9d3a" if ok else "#c0392b"
            parts.append(f'<text x="{cx:.1f}" y="{h-mbot+38}" text-anchor="middle" '
                         f'font-size="11" fill="{color}">{badge}</text>')
    # legend
    lx = ml + 10
    for mode in ("cold", "warm"):
        parts.append(f'<rect x="{lx}" y="{mt-18}" width="14" height="14" fill="{colors[mode]}"/>')
        parts.append(f'<text x="{lx+20}" y="{mt-6}">{mode} maxLive (MiB, -M8G)</text>')
        lx += 190
    parts.append('<defs><pattern id="hatch" width="6" height="6" patternTransform="rotate(45)" '
                 'patternUnits="userSpaceOnUse"><line x1="0" y1="0" x2="0" y2="6" '
                 'stroke="#c0392b" stroke-width="2"/></pattern></defs>')
    parts.append('</svg>')
    return "\n".join(parts)


def majors_trace(scenario, mode, heap="8G"):
    """(elapsed_s, live_MiB) for each major GC from the run's -S trace, if present."""
    path = f"/tmp/mem-report-{scenario}-{mode}-{heap}.S"
    if not os.path.exists(path):
        return None
    pts = []
    for line in open(path, errors="replace"):
        if "Gen:  1" not in line:
            continue
        f = line.split()
        try:
            pts.append((float(f[6]), int(f[2]) / 1048576.0))
        except (ValueError, IndexError):
            continue
    return pts or None


def line_chart():
    """Live-over-time (major GCs only), cold vs warm per scenario. The shape is
    the intuition behind 'warm is the worst case': cold peaks early and
    declines; warm climbs to a plateau and stays there until the first request."""
    series = []
    colors = {"full": "#4e79a7", "trim-current": "#e15759", "trim-cannot-run": "#59a14f"}
    for s in SCENARIOS:
        for mode, dash in [("cold", "5 4"), ("warm", "")]:
            pts = majors_trace(s, mode)
            if pts:
                series.append((s, mode, dash, pts))
    if not series:
        return ""
    w, h = 760, 320
    ml, mr, mt, mbot = 70, 20, 16, 40
    plot_w, plot_h = w - ml - mr, h - mt - mbot
    xmax = max(p[0] for _, _, _, pts in series for p in pts) * 1.03
    ymax = max(p[1] for _, _, _, pts in series for p in pts) * 1.1

    def x(v): return ml + (v / xmax) * plot_w
    def y(v): return mt + plot_h - (v / ymax) * plot_h

    parts = [f'<svg viewBox="0 0 {w} {h}" font-family="system-ui,sans-serif" font-size="12">']
    v = 0
    while v <= ymax:
        parts.append(f'<line x1="{ml}" y1="{y(v):.1f}" x2="{w-mr}" y2="{y(v):.1f}" stroke="#eee"/>')
        parts.append(f'<text x="{ml-8}" y="{y(v)+4:.1f}" text-anchor="end" fill="#666" font-size="10">{v:,}</text>')
        v += 1024
    for t in range(0, int(xmax) + 1, 60):
        parts.append(f'<text x="{x(t):.1f}" y="{h-mbot+16}" text-anchor="middle" fill="#666" font-size="10">{t}s</text>')
    for s, mode, dash, pts in series:
        d = " ".join(f"{'M' if i == 0 else 'L'}{x(px):.1f},{y(py):.1f}" for i, (px, py) in enumerate(pts))
        dash_attr = f' stroke-dasharray="{dash}"' if dash else ""
        parts.append(f'<path d="{d}" fill="none" stroke="{colors[s]}" stroke-width="1.8"{dash_attr}/>')
    lx = ml + 8
    for s in SCENARIOS:
        parts.append(f'<rect x="{lx}" y="{mt}" width="12" height="12" fill="{colors[s]}"/>')
        parts.append(f'<text x="{lx+16}" y="{mt+10}">{s}</text>')
        lx += 150
    parts.append(f'<text x="{lx}" y="{mt+10}" fill="#666">dashed = cold, solid = warm (-M8G runs)</text>')
    parts.append('</svg>')
    return ('<h2>Live heap over time (major GCs only)</h2>'
            '<p class="note">Post-collection live bytes at each major GC, from the -S traces of the -M8G runs. '
            'Cold boots peak early during typechecking and decline; warm boots climb while deserialising '
            'externs and plateau at their peak until the first request. MiB vs elapsed seconds.</p>'
            + "\n".join(parts))


def fmt(v, suffix=""):
    return f"{v:,}{suffix}" if v is not None else "—"


def table(by):
    rows = []
    for s in SCENARIOS:
        cold = get(by, s, "cold", "8G")
        warm = get(by, s, "warm", "8G")
        w3 = get(by, s, "warm", "3G")
        c3 = get(by, s, "cold", "3G")
        surv = None
        if w3:
            surv = w3["outcome"] == "ok" and w3.get("compile_ok")
        rows.append(
            "<tr>"
            f"<td>{LABELS[s]}</td>"
            f"<td class='num'>{fmt(direct_deps(s))}</td>"
            f"<td class='num'>{fmt(modules_of(by, s))}</td>"
            f"<td class='num'>{fmt(mb(cold))}</td>"
            f"<td class='num'>{fmt(mb(warm))}</td>"
            f"<td class='num'>{fmt(mb(w3, 'mem_in_use_mib')) if w3 and w3['outcome']=='ok' else 'died'}</td>"
            f"<td class='num'>{fmt(cold and cold.get('boot_seconds'), ' s')}</td>"
            f"<td class='num'>{fmt(warm and warm.get('boot_seconds'), ' s')}</td>"
            f"<td class='{ 'ok' if surv else 'bad'}'>{'&#10003;' if surv else '&#10007; heap exhausted'}</td>"
            + (f"<td class='num'>{'ok, ' + fmt(mb(c3)) + ' MiB' if c3['outcome']=='ok' else 'died'}</td>" if c3 else "<td class='num'>—</td>")
            + "</tr>"
        )
    return "\n".join(rows)


def summary(by):
    verdicts = []
    for s in SCENARIOS:
        w3 = get(by, s, "warm", "3G")
        if w3:
            verdicts.append(f"<b>{s}</b> {'fits' if w3['outcome']=='ok' else 'does <b>not</b> fit'}")
    return ", ".join(verdicts)


def main():
    runs, by = load()
    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>trypurescript peak-heap comparison: full vs trim-current vs trim-cannot-run</title>
<style>
  body {{ font-family: system-ui, sans-serif; max-width: 860px; margin: 2rem auto; padding: 0 1rem; color: #222; }}
  h1 {{ font-size: 1.4rem; }}
  table {{ border-collapse: collapse; width: 100%; font-size: 0.85rem; }}
  th, td {{ border: 1px solid #ddd; padding: 6px 8px; text-align: left; }}
  th {{ background: #f5f5f5; }}
  td.num {{ text-align: right; font-variant-numeric: tabular-nums; }}
  td.ok {{ color: #2a9d3a; font-weight: 600; }}
  td.bad {{ color: #c0392b; font-weight: 600; }}
  code, pre {{ background: #f6f6f6; border-radius: 4px; }}
  pre {{ padding: 10px; overflow-x: auto; font-size: 0.8rem; }}
  .note {{ color: #555; font-size: 0.85rem; }}
</style>
</head>
<body>
<h1>trypurescript server peak heap: three package-set scenarios</h1>
<p>
Peak heap (<code>maxLive</code> = &ldquo;bytes maximum residency&rdquo; from <code>+RTS -s</code>)
of the trypurescript server booting three package sets, each measured
<b>cold</b> (no <code>staging/.psci_modules/</code> cache) and <b>warm</b> (cache present
from the same scenario's cold boot). Warm boot is the memory-worst case:
deserialising per-module <code>externs.cbor</code> files loses the sharing the
typechecker's in-memory structures have. All runs: same release binary
(GHC&nbsp;9.2.5), <code>+RTS -N2 -A128m -M&lt;cap&gt; -S</code>, one successful
<code>/compile</code> before clean SIGINT exit; local Apple-silicon hardware
(droplet boot times will be slower; memory numbers transfer).
Production (<code>deploy/start</code>) runs with <code>-M3G</code> on a 3.8&nbsp;GiB droplet, so
&ldquo;warm maxLive &lt; 3,072&nbsp;MiB&rdquo; is the go/no-go line. Verdict: {summary(by)} under
<code>-M3G</code> warm.
</p>

{bar_chart(by)}

<table>
<tr>
  <th>scenario</th><th>packages</th><th>modules</th>
  <th>cold maxLive (MiB)</th><th>warm maxLive (MiB)</th>
  <th>RTS footprint @ -M3G warm (MiB)</th>
  <th>boot cold</th><th>boot warm</th>
  <th>survives -M3G warm?</th><th>cold @ -M3G</th>
</tr>
{table(by)}
</table>
<p class="note">packages = direct dependencies in <code>spago.lock</code> (this project lists the
full flattened set as direct deps). modules = compiled module count (from cold-boot
&ldquo;[ N of M ] Compiling&rdquo; output, cross-checked against <code>SPARKS</code> in the RTS summary).
RTS footprint = &ldquo;total memory in use&rdquo; at exit. Boot = launch &rarr; port accepting, at -M8G.</p>

{line_chart()}

<h2>How to reproduce</h2>
<pre>
# from the repo root, branch mem-report (needs stack-built server binary + spago 1.x)
for scen in trim-current trim-cannot-run full; do
  mem-report/measure.sh "$scen" cold 8G   # also populates .psci_modules for the warm runs
  mem-report/measure.sh "$scen" warm 8G
  mem-report/measure.sh "$scen" warm 3G
  rm -rf staging/.psci_modules            # never reuse a cache across scenarios
done
python3 mem-report/make_report.py
</pre>
<p class="note">Scenario package sets live in <code>mem-report/scenarios/&lt;name&gt;/spago.{{yaml,lock}}</code>.
<code>trim-cannot-run</code> = the full set minus the 148-package &ldquo;cannot run in the
playground&rdquo; closure (<code>mem-report/cannot-run.json</code>, regenerable via
<code>make_cannot_run_yaml.py</code>). Raw per-run data: <code>mem-report/results.json</code>.</p>
</body>
</html>
"""
    with open(OUT, "w") as f:
        f.write(html)
    print(f"wrote {OUT} ({len(runs)} runs)")


if __name__ == "__main__":
    main()
