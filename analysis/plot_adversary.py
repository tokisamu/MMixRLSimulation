#!/usr/bin/env python3
"""Honest-message outcomes against the fraction of participants the adversary controls."""
import argparse, json, os, sys
import numpy as np
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from entropy import parse_log


def stats_of(name, res):
    path = os.path.join(res, name + ".log")
    if not os.path.exists(path):
        return {}
    params, mixes, adv, orig, arr, dep, deliv, st, mal, comp = parse_log(path)
    return st


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("json", nargs="+")
    ap.add_argument("--out", default="figures/adversary.png")
    a = ap.parse_args()
    res = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "results")

    rows = []
    for p in a.json:
        rows.extend([r for r in json.load(open(p)) if "error" not in r])
    rows.sort(key=lambda r: r.get("adv_frac", 0.0))

    f = [r.get("adv_frac", 0.0) for r in rows]
    dl = [r["delivery_rate"] for r in rows]
    H = [r["entropy_mean"] for r in rows]
    dly = [r["e2e_delay_mean"] for r in rows]

    fig, ax = plt.subplots(1, 3, figsize=(13, 3.9))
    ax[0].plot(f, dl, marker="o", color="#d62728")
    ax[0].set_ylabel("honest delivery rate")
    ax[0].set_ylim(0, 1.05)
    ax[0].set_title("Delivery")
    ax[1].plot(f, H, marker="s", color="#1f77b4")
    ax[1].set_ylabel("anonymity entropy (bits)")
    ax[1].set_title("Anonymity")
    ax[2].plot(f, dly, marker="^", color="#2ca02c")
    ax[2].set_ylabel("end-to-end delay (s)")
    ax[2].set_title("Delay")
    for x in ax:
        x.set_xlabel("fraction of participants controlled by the adversary")
        x.set_xticks(f)
        x.grid(alpha=0.3)
    fig.tight_layout()
    fig.savefig(a.out, dpi=160, bbox_inches="tight")
    print(f"wrote {a.out}")

    print(f"{'f':>5} {'adv mixes':>10} {'honest deliv':>13} {'H (bits)':>10} "
          f"{'delay':>8} {'deferred':>10} {'adv drops':>10} {'adv orig':>10}")
    for r in rows:
        st = stats_of(r.get("scenario", r.get("log", "").replace(".log", "")), res)
        print(f"{r.get('adv_frac',0):>5.2f} {r.get('adv_mixes',0):>10d} "
              f"{r['delivery_rate']:>13.3f} {r['entropy_mean']:>10.3f} "
              f"{r['e2e_delay_mean']:>8.2f} {st.get('budget_deferred',0):>10d} "
              f"{st.get('adv_drop',0):>10d} {st.get('orig_adv',0):>10d}")


if __name__ == "__main__":
    main()
