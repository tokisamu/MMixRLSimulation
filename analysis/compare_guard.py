#!/usr/bin/env python3
"""Effect of the end-of-slot guard band: results with and against the archived baseline."""
import json, os, sys
from collections import defaultdict
import numpy as np

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RES = os.path.join(HERE, "results")


def load(path):
    rows = [r for r in json.load(open(path))
            if "error" not in r and "_r10_" in r.get("scenario", "")]
    g = defaultdict(list)
    for r in rows:
        g[r["layers"]].append(r)
    return g


def main():
    models = sys.argv[1:] or ["chain", "march", "blockade1"]
    for m in models:
        cur = os.path.join(RES, f"sweep_{m}.json")
        base = os.path.join(RES, "noguard", f"sweep_{m}.json")
        if not (os.path.exists(cur) and os.path.exists(base)):
            print(f"{m}: missing data, skipped")
            continue
        a, b = load(cur), load(base)
        print(f"\n=== {m}: no guard  ->  5 s guard ===")
        print(f"{'L':>2} {'H (bits)':>22} {'delay (s)':>22} {'delivery':>22}")
        for L in sorted(a):
            if L not in b:
                continue
            row = []
            for field in ("entropy_mean", "e2e_delay_mean", "delivery_rate"):
                x = np.mean([r[field] for r in b[L]])
                y = np.mean([r[field] for r in a[L]])
                row.append(f"{x:7.3f} -> {y:7.3f} ({y-x:+6.3f})")
            print(f"{L:>2} " + " ".join(row))


if __name__ == "__main__":
    main()
