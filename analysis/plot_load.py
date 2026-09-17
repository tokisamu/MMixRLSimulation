#!/usr/bin/env python3
"""Plot anonymity entropy and delay against the offered client rate, at fixed layers."""
import argparse, json
import numpy as np
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("json", nargs="+")
    ap.add_argument("--layers", type=int, default=3)
    ap.add_argument("--budget", type=int, default=10)
    ap.add_argument("--out", default="figures/load_sweep_chain.png")
    a = ap.parse_args()

    rows = []
    for p in a.json:
        rows.extend(json.load(open(p)))
    rows = [r for r in rows if "error" not in r and r["layers"] == a.layers]
    by = {}
    for r in rows:
        rate = int(r["scenario"].split("_r")[1].split("_")[0])
        by.setdefault(rate, []).append(r)
    rates = sorted(by)
    H = [np.mean([x["entropy_mean"] for x in by[k]]) for k in rates]
    Hs = [np.std([x["entropy_mean"] for x in by[k]]) for k in rates]
    D = [np.mean([x["e2e_delay_mean"] for x in by[k]]) for k in rates]
    Ds = [np.std([x["e2e_delay_mean"] for x in by[k]]) for k in rates]
    mix_only = 5.0 * a.layers

    fig, ax = plt.subplots(1, 2, figsize=(9.5, 3.6))
    ax[0].errorbar(rates, H, yerr=Hs, marker="o", capsize=4, color="#1f77b4", label="chain")
    ax[0].set_ylabel("anonymity entropy (bits)")
    ax[0].set_title("Anonymity")
    ax[1].errorbar(rates, D, yerr=Ds, marker="s", capsize=4, color="#1f77b4", label="chain")
    ax[1].axvline(a.budget, ls=":", color="#2ca02c")
    ax[1].set_ylabel("end-to-end delay (s)")
    ax[1].set_title("Delay")
    for x in ax:
        x.set_xscale("log")
        x.set_xticks(rates)
        x.set_xticklabels([str(k) for k in rates])
        x.xaxis.set_minor_locator(matplotlib.ticker.NullLocator())
        x.set_xlabel("client rate (messages per participant per minute)")
        x.grid(alpha=0.3)
        x.legend(fontsize=9)
    fig.tight_layout()
    fig.savefig(a.out, dpi=160, bbox_inches="tight")
    print(f"wrote {a.out}")
    for k, h, d in zip(rates, H, D):
        print(f"  rate {k:>2}/min: H = {h:6.3f} bits (set {2**h:7,.0f})   delay = {d:6.2f} s")


if __name__ == "__main__":
    main()
