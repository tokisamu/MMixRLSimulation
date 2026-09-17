#!/usr/bin/env python3
"""Table 2 of the paper: the four Amigo traces as radio graphs at 10 m, from the arrays.

The window is the 420 s the simulations use (60 s warm-up, 300 s measured, 60 s drain),
starting when the crowd leaves the staging area, exactly as gen_scenario.py re-bases time.
Area is the bounding box of all positions over the window; movement the mean speed over
nodes and seconds (the arrays are sampled once a second, in metres).  Degree, components,
hops and diameter are computed on the graph whose edges join nodes within the radio range,
sampled every --step seconds and averaged over the samples; hops are shortest-path lengths
over the connected node-mix pairs, the population of legs, with the mix sets of the given
seeds drawn as gen_scenario.py draws them.  "Longest wait" is, over the node-mix pairs, the
longest interval during which a pair is never in the same component (sampled every --step
seconds): the time a carried packet may have to wait for a partition to merge.  --whole uses
the entire trace after the staging area instead of the simulated window.
"""
import argparse, os, sys
import numpy as np
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(os.path.dirname(HERE), "scenarios"))
from gen_scenario import load_trace, staging_end                  # noqa: E402


def adjacency(pos, rng):
    d = np.linalg.norm(pos[:, None, :] - pos[None, :, :], axis=2)
    A = d <= rng
    np.fill_diagonal(A, False)
    return A


def hops(A):
    """All-pairs shortest-path lengths by breadth-first layering; inf where disconnected."""
    n = len(A)
    dist = np.full((n, n), np.inf)
    np.fill_diagonal(dist, 0.0)
    reach = np.eye(n, dtype=bool)
    Af = A.astype(np.float32)
    k = 0
    while True:
        k += 1
        nxt = (reach.astype(np.float32) @ Af) > 0
        new = nxt & ~reach
        if not new.any():
            return dist
        dist[new] = k
        reach |= new


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--traces", nargs="+", default=["march", "chain", "gather", "blockade1"])
    ap.add_argument("--range", type=float, default=10.0)
    ap.add_argument("--window", type=int, default=420)
    ap.add_argument("--step", type=int, default=5)
    ap.add_argument("--whole", action="store_true", help="the whole trace after staging, not the simulated window")
    ap.add_argument("--seeds", type=int, nargs="+", default=[1, 2, 3],
                    help="seeds whose mix sets (drawn as gen_scenario.py draws them) define the node-mix pairs")
    ap.add_argument("--mix-frac", type=float, default=0.10)
    a = ap.parse_args()
    print("| trace | area (m) | speed (m/s) | mean degree | hops per leg | diameter | components | node-mix pairs connected now | longest wait of a node-mix pair (s): max / p99 / median |")
    print("|---|---|---|---|---|---|---|---|---|")
    for tr in a.traces:
        arr = load_trace(tr)
        t0 = staging_end(arr)
        t1 = arr.shape[0] if a.whole else min(t0 + a.window, arr.shape[0])
        win = arr[t0:t1]
        ext = win.reshape(-1, 2).max(0) - win.reshape(-1, 2).min(0)
        speed = np.linalg.norm(win[1:] - win[:-1], axis=2).mean()
        n = arr.shape[1]
        n_mix = max(3, int(round(a.mix_frac * n)))
        # node-mix pairs of every seed, drawn exactly as gen_scenario.py draws the mix set
        legs = np.zeros((n, n), bool)
        for seed in a.seeds:
            mixes = np.random.default_rng(seed).permutation(n)[:n_mix]
            legs[:, mixes] = True
        np.fill_diagonal(legs, False)
        deg, hop, diam, conn = [], [], [], []
        same = []                                    # per sample: pairs in one component
        for t in range(0, t1 - t0, a.step):
            A = adjacency(win[t], a.range)
            D = hops(A)
            off = ~np.eye(len(A), dtype=bool)
            fin = np.isfinite(D) & off
            deg.append(A.sum(1).mean())
            hop.append(D[fin & legs].mean())
            diam.append(D[fin].max())
            conn.append(fin[legs].mean())
            same.append(fin | ~off)
        # components: count via the reachability matrix of each sample
        ncomp = []
        for S in same:
            seen = np.zeros(len(S), bool); c = 0
            for i in range(len(S)):
                if not seen[i]:
                    c += 1; seen |= S[i]
            ncomp.append(c)
        # longest interval without connectivity, per ordered pair, in seconds
        S = np.array(same)                                   # samples x n x n
        off = ~np.eye(S.shape[1], dtype=bool)
        longest = np.zeros((S.shape[1], S.shape[1]))
        run = np.zeros((S.shape[1], S.shape[1]))
        for k in range(S.shape[0]):
            run = np.where(S[k], 0.0, run + a.step)
            longest = np.maximum(longest, run)
        waits = longest[legs]
        print(f"| {tr} | {ext[0]:.0f} × {ext[1]:.0f} | {speed:.2f} | {np.mean(deg):.1f} | {np.mean(hop):.1f} | "
              f"{np.mean(diam):.0f} | {np.mean(ncomp):.1f} | {100*np.mean(conn):.0f}% | "
              f"{waits.max():.0f} / {np.percentile(waits, 99):.0f} / {np.median(waits):.0f} |")


if __name__ == "__main__":
    main()
