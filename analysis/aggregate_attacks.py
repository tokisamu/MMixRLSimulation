#!/usr/bin/env python3
"""Average the separated attack experiments over seeds and plot them.

Reads results/attacks/*.result.json.  For each (attack, trace, layers, ratio) cell it reports
the mean and standard deviation over the seeds that have finished, and says how many that
is, so a partially finished grid is never mistaken for a complete one.
"""
import argparse, glob, json, math, os
from collections import defaultdict
import numpy as np
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RES = os.environ.get("ANORL_OUT", os.path.join(HERE, "results", "attacks"))
FIG = os.path.join(HERE, "figures")
LSTYLE = {3: ("#1f77b4", "o"), 4: ("#ff7f0e", "s"), 5: ("#2ca02c", "^"), 6: ("#d62728", "D")}


def load():
    rows = []
    for p in glob.glob(os.path.join(RES, "*.result.json")):
        try:
            rows.append(json.load(open(p)))
        except Exception:
            pass
    return rows


def cells(rows):
    """(attack, trace, L, frac) -> list of rows; the shared control joins both attacks."""
    g = defaultdict(list)
    for r in rows:
        key_frac = float(r["frac"])
        attacks = ["drop", "cmix"] if r["attack"] == "none" else [r["attack"]]
        for atk in attacks:
            g[(atk, r["trace"], int(r["layers"]), key_frac)].append(r)
    return g


def stat(rs, field):
    v = [float(r[field]) for r in rs
         if r.get(field) is not None and not (isinstance(r[field], float) and math.isnan(r[field]))]
    if not v:
        return float("nan"), float("nan"), 0
    return float(np.mean(v)), float(np.std(v)), len(v)


def table(g, attack, trace, fracs, layers):
    lines = []
    lines.append(f"\n{attack.upper()} on {trace}")
    lines.append(f"{'L':>2} {'ratio':>5} {'runs':>4} {'delivery':>16} {'entropy (bits)':>18} {'delay (s)':>16}")
    for L in layers:
        for f in fracs:
            rs = g.get((attack, trace, L, f), [])
            if not rs:
                lines.append(f"{L:>2} {f:>5.1f} {0:>4}   (not run yet)")
                continue
            d = stat(rs, "delivery_e2e")
            h = stat(rs, "entropy_mean")
            t = stat(rs, "e2e_delay_mean")
            hs = f"{h[0]:7.3f}+-{h[1]:5.3f}" if h[2] else "      n/a      "
            ts = f"{t[0]:6.2f}+-{t[1]:5.2f}" if t[2] else "     n/a      "
            lines.append(f"{L:>2} {f:>5.1f} {len(rs):>4} {d[0]:7.3f}+-{d[1]:5.3f} {hs:>18} {ts:>16}")
    return "\n".join(lines)


def plot(g, attack, trace, fracs, layers, out):
    fig, ax = plt.subplots(1, 3, figsize=(13, 3.9))
    for L in layers:
        col, mk = LSTYLE.get(L, ("#333", "x"))
        xs, D, Ds, H, Hs, T, Ts = [], [], [], [], [], [], []
        for f in fracs:
            rs = g.get((attack, trace, L, f), [])
            if not rs:
                continue
            xs.append(f)
            d = stat(rs, "delivery_e2e"); D.append(d[0]); Ds.append(d[1])
            h = stat(rs, "entropy_mean"); H.append(h[0]); Hs.append(h[1])
            t = stat(rs, "e2e_delay_mean"); T.append(t[0]); Ts.append(t[1])
        if not xs:
            continue
        lab = f"L={L}"
        ax[0].errorbar(xs, D, yerr=Ds, marker=mk, color=col, capsize=3, label=lab)
        ax[1].errorbar(xs, H, yerr=Hs, marker=mk, color=col, capsize=3, label=lab)
        ax[2].errorbar(xs, T, yerr=Ts, marker=mk, color=col, capsize=3, label=lab)
    xlabel = ("fraction of participants that drop" if attack == "drop"
              else "fraction of mixes that are corrupted")
    ax[0].set_ylabel("honest delivery rate"); ax[0].set_ylim(0, 1.05); ax[0].set_title("Delivery")
    ax[1].set_ylabel("anonymity entropy (bits)"); ax[1].set_title("Anonymity")
    ax[2].set_ylabel("end-to-end delay (s)"); ax[2].set_title("Delay")
    for x in ax:
        x.set_xlabel(xlabel)
        x.set_xticks(fracs)
        x.grid(alpha=0.3)
        x.legend(fontsize=8)
    fig.tight_layout()
    fig.savefig(out, dpi=160, bbox_inches="tight")
    plt.close(fig)
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--fracs", type=float, nargs="+", default=[0.0, 0.1, 0.2, 0.3, 0.4])
    ap.add_argument("--layers", type=int, nargs="+", default=[3, 4, 5, 6])
    ap.add_argument("--traces", nargs="+", default=["march", "chain"])
    ap.add_argument("--no-plots", action="store_true")
    ap.add_argument("--figdir", default=FIG, help="where to write the figures")
    a = ap.parse_args()
    rows = load()
    builds = sorted(set((str(r.get("ns3_binary")), str(r.get("numpy_version")),
                         str(r.get("python_version"))) for r in rows))
    if len(builds) > 1:
        print("WARNING: these results come from more than one build; averaging them mixes")
        print("         machines whose random draws differ, which breaks the paired design:")
        for b in builds:
            n = sum(1 for r in rows if (str(r.get("ns3_binary")), str(r.get("numpy_version")),
                                        str(r.get("python_version"))) == b)
            print("         %4d runs  ns-3 %s, numpy %s, python %s" % ((n,) + b))
    g = cells(rows)
    print(f"{len(rows)} finished runs found in {RES}")
    for attack in ("drop", "cmix"):
        for trace in a.traces:
            print(table(g, attack, trace, a.fracs, a.layers))
            if not a.no_plots:
                os.makedirs(a.figdir, exist_ok=True)
                out = plot(g, attack, trace, a.fracs, a.layers,
                           os.path.join(a.figdir, f"attack_{attack}_{trace}.png"))
                print(f"  figure: {out}")
    with open(os.path.join(RES, "summary.json"), "w") as fh:
        summ = {}
        for (atk, tr, L, f), rs in g.items():
            summ[f"{atk}|{tr}|{L}|{f}"] = dict(
                runs=len(rs),
                delivery=stat(rs, "delivery_e2e")[:2],
                entropy=stat(rs, "entropy_mean")[:2],
                delay=stat(rs, "e2e_delay_mean")[:2])
        json.dump(summ, fh, indent=2)


if __name__ == "__main__":
    main()
