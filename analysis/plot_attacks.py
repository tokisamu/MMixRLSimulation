#!/usr/bin/env python3
"""Figures and a summary table for the separated attack experiments.

One figure per attack.  Rows are the mobility traces, columns are delivery, anonymity entropy
and delay; each line is a layer count, with the band showing one standard deviation over
seeds.  Entropy and delay describe only the messages that arrived, so they are shown only for
cells whose seeds together delivered at least --min-delivered honest messages; below that a
handful of survivors, typically those on the shortest routes, would pose as a trend.
Delivery is always shown, and the table keeps every raw value with its message count.

Several result folders can be given, for example one per cluster batch; they are searched
recursively.  Results of one trace must all come from one build, since averaging runs from
different builds would break the paired design.  The result folders are only read.
"""
import argparse, csv, glob, json, math, os
from collections import defaultdict
import numpy as np
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

FRACS = [0.0, 0.1, 0.2, 0.3, 0.4]
LAYERS = [3, 4, 5, 6]
TRACE_ORDER = ["march", "chain", "gather", "blockade1"]
TRACE_LABEL = {"blockade1": "blockade"}
METRICS = [("delivery_e2e", "Delivery rate"), ("entropy_mean", "Entropy (bits)"), ("e2e_delay_mean", "Delay (s)")]
XLABEL = {"drop": "Fraction of participants that drop messages", "cmix": "Fraction of corrupted mixes"}
MARKERS = {3: "o", 4: "s", 5: "^", 6: "D"}
CONDITIONAL = ("entropy_mean", "e2e_delay_mean")


def finite(x):
    return isinstance(x, (int, float)) and not math.isnan(x)


def build_of(r):
    return (r.get("ns3_binary"), r.get("numpy_version"), r.get("python_version"))


def load(folders):
    rows, seen = [], {}
    for folder in folders:
        paths = sorted(glob.glob(os.path.join(folder, "**", "*.result.json"), recursive=True))
        if not paths:
            raise SystemExit(f"no result files under {folder}")
        for p in paths:
            r = json.load(open(p))
            key = r.get("scenario") or os.path.basename(p)
            if key in seen:
                if json.dumps(seen[key], sort_keys=True, default=str) != json.dumps(r, sort_keys=True, default=str):
                    raise SystemExit(f"{key} appears in more than one folder with different contents")
                continue
            seen[key] = r
            rows.append(r)
    builds = defaultdict(set)
    for r in rows:
        builds[r["trace"]].add(build_of(r))
    for trace, b in builds.items():
        if len(b) > 1:
            raise SystemExit(f"trace {trace} mixes {len(b)} builds; refusing to average across them: {b}")
    if len(set().union(*builds.values())) > 1:
        print("note: traces come from different builds; each trace is averaged within its own build")
    cells = defaultdict(list)
    for r in rows:
        for atk in (["drop", "cmix"] if r["attack"] == "none" else [r["attack"]]):
            cells[(atk, r["trace"], int(r["layers"]), float(r["frac"]))].append(r)
    present = {r["trace"] for r in rows}
    traces = [t for t in TRACE_ORDER if t in present] + sorted(present - set(TRACE_ORDER))
    return rows, cells, traces


def summarise(rs, field):
    v = [r[field] for r in rs if finite(r.get(field))]
    return (float(np.mean(v)), float(np.std(v)), len(v)) if v else (float("nan"), float("nan"), 0)


def delivered_total(rs):
    return sum(int(r.get("messages_delivered") or 0) for r in rs)


def cell_value(rs, field, min_delivered):
    if field in CONDITIONAL and delivered_total(rs) < min_delivered:
        return float("nan"), float("nan"), 0
    return summarise(rs, field)


def figure(cells, attack, out_base, min_delivered, traces):
    colors = plt.cm.viridis(np.linspace(0.05, 0.8, len(LAYERS)))
    height = 3.2 * len(traces)
    fig, axes = plt.subplots(len(traces), len(METRICS), figsize=(11.5, height), sharex=True, sharey="col",
                             squeeze=False)
    for i, trace in enumerate(traces):
        for j, (field, title) in enumerate(METRICS):
            ax = axes[i, j]
            for c, L in zip(colors, LAYERS):
                m, s = [], []
                for f in FRACS:
                    mu, sd, _ = cell_value(cells.get((attack, trace, L, f), []), field, min_delivered)
                    m.append(mu); s.append(sd)
                m, s = np.array(m), np.array(s)
                lo, hi = m - s, m + s
                if field == "delivery_e2e":
                    lo, hi = np.clip(lo, 0, 1), np.clip(hi, 0, 1)
                else:
                    lo = np.clip(lo, 0, None)
                x = np.array(FRACS)
                ok = ~np.isnan(m)
                ax.plot(x, m, marker=MARKERS[L], color=c, lw=1.6, ms=5, label=f"h = {L}")   # NaN leaves a gap
                ax.fill_between(x, np.where(ok, lo, 0), np.where(ok, hi, 0), where=ok, color=c, alpha=0.15, lw=0)
            ax.grid(alpha=0.3)
            ax.set_xticks(FRACS)
            if i == 0:
                ax.set_title(title)
            if i == len(traces) - 1:
                ax.set_xlabel(XLABEL[attack])
            if field == "delivery_e2e":
                ax.set_ylim(-0.02, 1.02)
            elif field == "entropy_mean":
                ax.set_ylim(bottom=0)
        axes[i, 0].set_ylabel(TRACE_LABEL.get(trace, trace), fontsize=12, fontweight="bold")
    handles, labels = axes[0, 0].get_legend_handles_labels()
    fig.legend(handles, labels, loc="upper center", ncol=len(LAYERS), frameon=False,
               bbox_to_anchor=(0.5, 1 + 0.128 / height))
    fig.tight_layout(rect=(0, 0, 1, 1 - 0.32 / height))
    for ext in ("png", "pdf"):
        fig.savefig(f"{out_base}.{ext}", dpi=200, bbox_inches="tight")
    plt.close(fig)
    return [f"{out_base}.png", f"{out_base}.pdf"]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--results", required=True, nargs="+", help="one or more folders holding *.result.json files")
    ap.add_argument("--out", required=True, help="folder for the figures and the summary table")
    ap.add_argument("--traces", nargs="+", default=None, help="traces to draw, in row order (default: all present)")
    ap.add_argument("--min-delivered", type=int, default=60,
                    help="honest messages a cell's seeds must deliver in total before its entropy and delay are plotted")
    a = ap.parse_args()
    rows, cells, present = load(a.results)
    traces = a.traces or present
    missing = [t for t in traces if t not in present]
    if missing:
        raise SystemExit(f"no results for trace(s) {missing}; present: {present}")
    os.makedirs(a.out, exist_ok=True)
    written = []
    for attack in ("drop", "cmix"):
        written += figure(cells, attack, os.path.join(a.out, f"attack_{attack}"), a.min_delivered, traces)
    table = os.path.join(a.out, "attack_summary.csv")
    hidden = []
    with open(table, "w", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["attack", "trace", "layers", "ratio", "runs", "delivered_total", "delivery_mean", "delivery_std",
                    "entropy_mean", "entropy_std", "entropy_runs", "delay_mean", "delay_std", "entropy_delay_plotted"])
        for attack in ("drop", "cmix"):
            for trace in traces:
                for L in LAYERS:
                    for f in FRACS:
                        rs = cells.get((attack, trace, L, f), [])
                        d, h, t = summarise(rs, "delivery_e2e"), summarise(rs, "entropy_mean"), summarise(rs, "e2e_delay_mean")
                        fmt = lambda x: "" if math.isnan(x) else f"{x:.4f}"
                        n = delivered_total(rs)
                        shown = "yes" if n >= a.min_delivered else "no"
                        w.writerow([attack, trace, L, f, len(rs), n, fmt(d[0]), fmt(d[1]), fmt(h[0]), fmt(h[1]), h[2],
                                    fmt(t[0]), fmt(t[1]), shown])
                        if shown == "no" and not (attack == "cmix" and f == 0.0):
                            hidden.append(f"{attack} {trace} L={L} ratio={f}: {n} messages delivered over {len(rs)} seeds")
    written.append(table)
    print(f"{len(rows)} results read from {', '.join(a.results)}; traces drawn: {', '.join(traces)}")
    print(f"entropy and delay not plotted, fewer than {a.min_delivered} messages delivered in the cell:")
    for h in hidden:
        print("   ", h)
    for p in written:
        print("wrote", p)


if __name__ == "__main__":
    main()
