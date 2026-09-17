#!/usr/bin/env python3
"""Reproduce a published entropy figure with our own analysis code.

Ben Guirat and Diaz (PoPETs 2022) report mean entropy for a stratified mixnet with L
layers of W continuous-time mixes, Poisson client traffic of total rate lambda_U, and an
end-to-end latency budget D_e2e split by their Equation (17):

    mu = ( D_e2e - (tau + delta) * (L + 1) ) / L,      tau + delta = 50 ms.

This script simulates that mixnet directly, writes the event log in the format our ns-3
simulator emits, and runs analysis/entropy.py over it.  If our Algorithm 1 implementation
is right, the mean entropy reproduces their published value for the same configuration.
The mixnet here is deliberately theirs, not ours: stratified, lossless and static.
"""
import argparse
import heapq
import os
import sys
import tempfile

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from entropy import compute                                   # noqa: E402


def simulate(L, W, lam_u, e2e, seed=1, horizon=400.0, tau=0.05, out=None):
    mu = (e2e - tau * (L + 1)) / L
    if mu <= 0:
        raise SystemExit(f"latency budget {e2e}s too small for L={L}")
    rng = np.random.default_rng(seed)

    # message arrival times, Poisson of rate lam_u
    n_msg = int(lam_u * horizon)
    times = np.sort(rng.uniform(0, horizon, n_msg))
    # mix ids: layer l, index w  ->  l * W + w
    paths = rng.integers(0, W, size=(n_msg, L)) + np.arange(L) * W
    delays = rng.exponential(mu, size=(n_msg, L))

    lines = ["# anorl-mix event log",
             f"# PARAM layers {L} mixdelay {mu:.6f} transport stratified pktsize 0"
             f" range 0 stop {horizon} budget_client 0 budget_mix 0 n {L*W} n_mix {L*W}",
             "# MIXES " + " ".join(str(i) for i in range(L * W))]

    # event queue: (time, kind, mid, hop);  kind 0 = arrive, 1 = depart
    ev = []
    for i in range(n_msg):
        lines.append(f"ORIG {i} {times[i]:.6f} 0 0 {paths[i,0]}")
        heapq.heappush(ev, (times[i] + tau, 0, i, 0))
    while ev:
        t, kind, mid, hop = heapq.heappop(ev)
        mix = int(paths[mid, hop])
        if kind == 0:
            lines.append(f"ARR {mid} {t:.6f} {mix} {hop}")
            heapq.heappush(ev, (t + delays[mid, hop], 1, mid, hop))
        else:
            lines.append(f"DEP {mid} {t:.6f} {mix} {hop}")
            if hop + 1 < L:
                heapq.heappush(ev, (t + tau, 0, mid, hop + 1))
            else:
                lines.append(f"DELIV {mid} {t:.6f} {mix} {t - times[mid]:.6f}")

    path = out or tempfile.NamedTemporaryFile(suffix=".log", delete=False).name
    with open(path, "w") as fh:
        fh.write("\n".join(lines) + "\n")
        fh.write("# STATS originations %d tx 0 rx 0\n" % n_msg)
    return path, mu


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--layers", type=int, default=3)
    ap.add_argument("--width", type=int, default=50)
    ap.add_argument("--lambda-u", type=float, default=10.0)
    ap.add_argument("--e2e", type=float, default=1.0)
    ap.add_argument("--horizon", type=float, default=400.0)
    ap.add_argument("--targets", type=int, default=200)
    ap.add_argument("--seeds", type=int, nargs="+", default=[1, 2, 3])
    ap.add_argument("--expect", type=float, default=None)
    a = ap.parse_args()

    vals = []
    for s in a.seeds:
        p, mu = simulate(a.layers, a.width, a.lambda_u, a.e2e, seed=s, horizon=a.horizon)
        r = compute(p, n_targets=a.targets, burn=0.25, drain=0.15, seed=1)
        os.unlink(p)
        vals.append(r["entropy_mean"])
        print(f"  seed {s}: H = {r['entropy_mean']:.3f} bits  "
              f"(median {r['entropy_median']:.3f}, targets {r['n_targets']}, "
              f"outputs {r['n_outputs']}, mu = {mu:.4f}s, mass {r['surviving_mass_mean']:.3f})")
    m, sd = float(np.mean(vals)), float(np.std(vals))
    print(f"L={a.layers} W={a.width} lambda_U={a.lambda_u} D_e2e={a.e2e}s "
          f"-> H = {m:.3f} +/- {sd:.3f} bits")
    if a.expect is not None:
        print(f"published value {a.expect:.3f} bits, difference {m - a.expect:+.3f}")
