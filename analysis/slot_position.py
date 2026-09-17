#!/usr/bin/env python3
"""How the strict slot window loses packets as a function of position within the slot.

A spend is valid only inside the slot it was made in, so a leg started late in a slot has
less time to cross the mesh than one started early.  This bins originations by their offset
into the slot and reports what fraction of them never reached the mix they were addressed to.
"""
import argparse, os, sys
import numpy as np
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from entropy import parse_log


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("logs", nargs="+")
    ap.add_argument("--slot", type=float, default=60.0)
    ap.add_argument("--bins", type=int, default=6)
    a = ap.parse_args()
    for path in a.logs:
        params, mixes, adv, orig, arr, dep, deliv, stats, mal, complete = parse_log(path)
        if not complete:
            print(f"{os.path.basename(path)}: truncated, skipped")
            continue
        L = int(params.get("layers", 3))
        seen = set((m, h) for (t, m, n, h) in arr)
        edges = np.linspace(0, a.slot, a.bins + 1)
        tot = np.zeros(a.bins)
        lost = np.zeros(a.bins)
        for (t, m, n, h) in orig:
            if h >= L:
                continue                      # the final broadcast has no addressed mix
            b = min(int((t % a.slot) / a.slot * a.bins), a.bins - 1)
            tot[b] += 1
            if (m, h) not in seen:
                lost[b] += 1
        print(f"\n{os.path.basename(path)}  (slot {a.slot:.0f} s, {int(tot.sum())} legs)")
        for i in range(a.bins):
            if tot[i] == 0:
                continue
            left = a.slot - edges[i + 1]
            print(f"  offset {edges[i]:5.1f}-{edges[i+1]:5.1f}s into the slot "
                  f"({left:4.1f}s of token life left at the end of the bin): "
                  f"{int(tot[i]):6d} legs, {100*lost[i]/tot[i]:5.1f}% never arrived")


if __name__ == "__main__":
    main()
