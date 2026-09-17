#!/usr/bin/env python3
"""Plot anonymity entropy and end-to-end delay against the number of mix layers."""
import argparse
import json
import os
from collections import defaultdict

import numpy as np
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt


def load(paths):
    rows = []
    for p in paths:
        with open(p) as fh:
            rows.extend(json.load(fh))
    return [r for r in rows if "error" not in r]


def group(rows, key="layers"):
    g = defaultdict(list)
    for r in rows:
        g[r[key]].append(r)
    return dict(sorted(g.items()))


def agg(rows, field):
    v = [r[field] for r in rows]
    return float(np.mean(v)), float(np.std(v))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("json", nargs="+")
    ap.add_argument("--out", default="figures/entropy_delay.png")
    ap.add_argument("--title", default="")
    a = ap.parse_args()
    rows = load(a.json)
    g = group(rows)
    L = list(g.keys())
    Hm = [agg(g[k], "entropy_mean")[0] for k in L]
    Hs = [agg(g[k], "entropy_mean")[1] for k in L]
    Dm = [agg(g[k], "e2e_delay_mean")[0] for k in L]
    Ds = [agg(g[k], "e2e_delay_mean")[1] for k in L]
    Rm = [agg(g[k], "delivery_rate")[0] for k in L]
    Rs = [agg(g[k], "delivery_rate")[1] for k in L]
    Sm = [2 ** h for h in Hm]

    fig, ax = plt.subplots(1, 3, figsize=(13, 3.8))

    ax[0].errorbar(L, Hm, yerr=Hs, marker="o", capsize=4, color="#1f77b4")
    ax[0].set_xlabel("mix layers $L$")
    ax[0].set_ylabel("anonymity entropy (bits)")
    ax[0].set_title("Anonymity")
    ax[0].set_xticks(L)
    ax[0].grid(alpha=0.3)

    ax[1].errorbar(L, Dm, yerr=Ds, marker="s", capsize=4, color="#d62728", label="measured")
    ax[1].set_xlabel("mix layers $L$")
    ax[1].set_ylabel("end-to-end delay (s)")
    ax[1].set_title("Delay")
    ax[1].set_xticks(L)
    ax[1].grid(alpha=0.3)

    ax[2].errorbar(L, Rm, yerr=Rs, marker="^", capsize=4, color="#2ca02c")
    ax[2].set_xlabel("mix layers $L$")
    ax[2].set_ylabel("delivery rate")
    ax[2].set_ylim(0, 1.02)
    ax[2].set_title("Delivery")
    ax[2].set_xticks(L)
    ax[2].grid(alpha=0.3)

    if a.title:
        fig.suptitle(a.title, y=1.02)
    fig.tight_layout()
    os.makedirs(os.path.dirname(a.out) or ".", exist_ok=True)
    fig.savefig(a.out, dpi=160, bbox_inches="tight")
    print(f"wrote {a.out}")

    print(f"{'L':>3} {'H (bits)':>12} {'set':>9} {'delay (s)':>12} {'delivery':>10} {'runs':>5}")
    for k in L:
        h, hs = agg(g[k], "entropy_mean")
        d, ds = agg(g[k], "e2e_delay_mean")
        r, rs = agg(g[k], "delivery_rate")
        print(f"{k:>3} {h:>7.3f}+-{hs:<4.3f} {2**h:>9,.0f} {d:>7.2f}+-{ds:<4.2f} "
              f"{r:>6.3f}+-{rs:<4.3f} {len(g[k]):>5}")


if __name__ == "__main__":
    main()
