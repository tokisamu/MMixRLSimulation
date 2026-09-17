#!/usr/bin/env python3
"""Compare anonymity, delay and delivery across mobility traces."""
import argparse, json
from collections import defaultdict
import numpy as np
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

STYLE = {"chain": ("#1f77b4", "o", "chain"),
         "blockade1": ("#d62728", "s", "blockade"),
         "march": ("#2ca02c", "^", "march"),
         "gather": ("#9467bd", "D", "gather")}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("json", nargs="+")
    ap.add_argument("--out", default="figures/compare_traces.png")
    a = ap.parse_args()

    series = {}
    for p in a.json:
        for r in json.load(open(p)):
            if "error" in r or "_r10_" not in r["scenario"]:
                continue
            series.setdefault(r["model"], defaultdict(list))[r["layers"]].append(r)

    fig, ax = plt.subplots(1, 3, figsize=(13, 3.9))
    for model, g in series.items():
        col, mk, lab = STYLE.get(model, ("#333", "^", model))
        L = sorted(g)
        for i, field in enumerate(["entropy_mean", "e2e_delay_mean", "delivery_rate"]):
            m = [np.mean([x[field] for x in g[k]]) for k in L]
            s = [np.std([x[field] for x in g[k]]) for k in L]
            ax[i].errorbar(L, m, yerr=s, marker=mk, capsize=4, color=col, label=lab)
    ax[0].set_ylabel("anonymity entropy (bits)")
    ax[0].set_title("Anonymity")
    ax[1].set_ylabel("end-to-end delay (s)")
    ax[1].set_title("Delay")
    ax[2].set_ylabel("delivery rate")
    ax[2].set_ylim(0, 1.05)
    ax[2].set_title("Delivery")
    for x in ax:
        x.set_xlabel("mix layers $L$")
        x.set_xticks(sorted(next(iter(series.values())).keys()))
        x.grid(alpha=0.3)
        x.legend(fontsize=9)
    fig.tight_layout()
    fig.savefig(a.out, dpi=160, bbox_inches="tight")
    print(f"wrote {a.out}")


if __name__ == "__main__":
    main()
