#!/usr/bin/env python3
"""Anonymity entropy of an AnoRL run, by the method of Ben Guirat and Diaz.

Reference: Iness Ben Guirat and Claudia Diaz, "Mixnet optimization methods",
Proceedings on Privacy Enhancing Technologies 2022(3):456-477, doi 10.56553/popets-2022-0081.

We reproduce their Algorithm 1 and their Equation (15).  A target *input* message m_t is
fixed; every message in the system carries a probability that it is the target; a mix that
releases a message hands it an even share of the probability mass currently in its pool,
which is exact for continuous-time mixes with exponential delays because all messages in
the pool are equally likely to be the next to leave.  The entropy of the resulting
distribution over the *outputs* is the anonymity of that target, in bits, un-normalised:

    H = - sum_i Pr_L[m_i = m_t] * log2( Pr_L[m_i = m_t] )                        (15)

Two deliberate deviations from the paper, both forced by the setting and both reported:

  * Their mixnet is stratified with L layers and every message crosses exactly one mix per
    layer.  AnoRL is free-route: a client draws a random sequence of L distinct mixes.  The
    per-mix update is unchanged, because it depends only on pool occupancy, and the output
    cut is still well defined because every message crosses exactly L mixes.
  * Their network never loses a message, so probability mass is conserved.  A mobile ad-hoc
    network loses messages, so mass leaks.  We report the surviving mass, and compute the
    entropy over the delivered outputs renormalised to one, which is the anonymity of a
    target conditioned on the adversary seeing it delivered.
"""
import argparse
import json
import math
import os
import random
import sys
from collections import defaultdict

import numpy as np


def parse_log(path):
    params, mixes = {}, []
    orig, arr, dep, deliv = [], [], [], []
    stats = {}
    malformed = 0
    adv = []
    with open(path) as fh:
        for line in fh:
            if line.startswith("#"):
                tok = line[1:].split()
                if tok and tok[0] == "PARAM":
                    for i in range(1, len(tok) - 1, 2):
                        params[tok[i]] = tok[i + 1]
                elif tok and tok[0] == "MIXES":
                    mixes = [int(x) for x in tok[1:]]
                elif tok and tok[0] == "ADV":
                    adv = [int(x) for x in tok[1:]]
                elif tok and tok[0] == "STATS":
                    for i in range(1, len(tok) - 1, 2):
                        stats[tok[i]] = int(tok[i + 1])
                continue
            t = line.split()
            if not t:
                continue
            try:
                if t[0] == "ORIG" and len(t) >= 6:
                    orig.append((float(t[2]), int(t[1]), int(t[3]), int(t[4])))
                elif t[0] == "ARR" and len(t) >= 5:
                    arr.append((float(t[2]), int(t[1]), int(t[3]), int(t[4])))
                elif t[0] == "DEP" and len(t) >= 5:
                    dep.append((float(t[2]), int(t[1]), int(t[3]), int(t[4])))
                elif t[0] == "DELIV" and len(t) >= 5:
                    deliv.append((float(t[2]), int(t[1]), int(t[3]), float(t[4])))
                else:
                    malformed += 1
            except ValueError:
                malformed += 1
    complete = stats != {}
    return params, mixes, adv, orig, arr, dep, deliv, stats, malformed, complete


def compute(path, n_targets=200, burn=0.25, drain=0.15, seed=1, verbose=False):
    params, mixes, adv, orig, arr, dep, deliv, stats, malformed, complete = parse_log(path)
    if not complete:
        return dict(error="event log is truncated: the run did not finish",
                    log=os.path.basename(path), malformed=malformed)
    layers = int(params.get("layers", 3))
    stop = float(params.get("stop", 0))
    rng = random.Random(seed)

    adv_set = set(adv)
    # A message the adversary originated gives it no cover: it knows its own traffic, so
    # such messages are excluded from every pool and from the candidate outputs.  A mix the
    # adversary controls does no mixing either, so probability passes through it unchanged
    # (Ben Guirat and Diaz, section 3.2).
    adv_msg = set(mid for (t, mid, node, hop) in orig if hop == 0 and node in adv_set)

    delivered = {mid: (t, d) for (t, mid, _node, d) in deliv}
    _honest_orig = set(mid for (t, mid, node, hop) in orig
                       if hop == 0 and node not in adv_set)
    _honest_deliv = set(mid for (_t, mid, _n, _d) in deliv if mid not in adv_msg)
    _e2e = (len(_honest_deliv & _honest_orig) / len(_honest_orig)) if _honest_orig else 0.0
    _base = dict(log=os.path.basename(path), layers=layers,
                 n=int(params.get('n', 0)), n_adversaries=len(adv_set),
                 honest_originated=len(_honest_orig),
                 messages_delivered=len(_honest_deliv), delivery_e2e=_e2e,
                 entropy_mean=float('nan'), e2e_delay_mean=float('nan'), stats=stats)
    first_arr = {}
    for (t, mid, _m, hop) in arr:
        if hop == 0 and mid not in first_arr and mid not in adv_msg:
            first_arr[mid] = t

    # A target must enter after the pools have filled and leave before the run ends,
    # otherwise its entropy measures the boundary and not the mixnet.
    t_lo, t_hi = burn * stop, (1.0 - drain) * stop
    eligible = [mid for mid, t in first_arr.items()
                if t_lo <= t <= t_hi and mid in delivered]
    if not eligible:
        return dict(_base, error="no eligible targets", n_eligible=0)
    eligible.sort()
    targets = eligible if len(eligible) <= n_targets else rng.sample(eligible, n_targets)
    targets.sort()
    tidx = {mid: j for j, mid in enumerate(targets)}
    K = len(targets)

    # Replay every mix event in time order.  Ties are broken arrivals-before-departures,
    # which is the order the simulator itself produced them.
    ev = []
    for (t, mid, node, hop) in arr:
        if mid not in adv_msg:
            ev.append((t, 0, mid, node, hop))
    for (t, mid, node, hop) in dep:
        if mid not in adv_msg:
            ev.append((t, 1, mid, node, hop))
    ev.sort(key=lambda e: (e[0], e[1]))

    pr = defaultdict(lambda: np.zeros(K))
    for mid in targets:
        pr[mid] = np.zeros(K)
        pr[mid][tidx[mid]] = 1.0
    pmix = defaultdict(lambda: np.zeros(K))
    pool = defaultdict(int)
    inside = defaultdict(set)

    for (t, kind, mid, node, hop) in ev:
        if node in adv_set:
            continue          # a corrupt mix does no mixing
        if kind == 0:
            pmix[node] += pr[mid]
            pool[node] += 1
            inside[node].add((mid, hop))
        else:
            if (mid, hop) not in inside[node]:
                continue                      # a departure with no matching arrival
            inside[node].discard((mid, hop))
            n = pool[node]
            if n <= 0:
                continue
            share = pmix[node] / n            # the pool includes the departing message
            pr[mid] = share
            pmix[node] = pmix[node] - share
            pool[node] = n - 1

    # Outputs: the messages the last mix broadcast.
    out_mids = [mid for (_t, mid, _n, _d) in deliv if mid not in adv_msg]
    if not out_mids:
        return dict(_base, error="no outputs", n_eligible=len(eligible))
    P = np.stack([pr[mid] for mid in out_mids])          # (n_out, K)

    mass = P.sum(axis=0)                                  # surviving mass per target
    H_raw = np.zeros(K)
    H_cond = np.zeros(K)
    for j in range(K):
        col = P[:, j]
        nz = col[col > 0]
        if nz.size:
            H_raw[j] = float(-(nz * np.log2(nz)).sum())
        m = mass[j]
        if m > 0:
            q = nz / m
            H_cond[j] = float(-(q * np.log2(q)).sum())

    e2e = np.array([d for (_t, mid, _n, d) in deliv if mid not in adv_msg])
    n_msg = len(first_arr) if first_arr else 0
    orig_msgs = len(set(m for (_t, m, _n, _h) in orig) - adv_msg)
    honest_orig = set(mid for (t, mid, node, hop) in orig
                      if hop == 0 and node not in adv_set)
    delivered_honest = set(out_mids)

    res = dict(
        log=os.path.basename(path),
        layers=layers,
        n=int(params.get("n", 0)),
        n_mix=int(params.get("n_mix", len(mixes))),
        mixdelay=float(params.get("mixdelay", 0)),
        transport=params.get("transport", ""),
        stop=stop,
        messages_originated=orig_msgs,
        messages_entered_mixnet=n_msg,
        messages_delivered=len(out_mids),
        honest_originated=len(honest_orig),
        delivery_e2e=(len(delivered_honest & honest_orig) / len(honest_orig)
                      if honest_orig else 0.0),
        delivery_rate=len(out_mids) / n_msg if n_msg else 0.0,
        n_targets=K,
        n_eligible_targets=len(eligible),
        n_outputs=len(out_mids),
        surviving_mass_mean=float(mass.mean()),
        entropy_mean=float(H_cond.mean()),
        entropy_median=float(np.median(H_cond)),
        entropy_q25=float(np.quantile(H_cond, 0.25)),
        entropy_q75=float(np.quantile(H_cond, 0.75)),
        entropy_min=float(H_cond.min()),
        entropy_max=float(H_cond.max()),
        entropy_raw_mean=float(H_raw.mean()),
        anonymity_set_mean=float(2 ** H_cond.mean()),
        e2e_delay_mean=float(e2e.mean()),
        e2e_delay_median=float(np.median(e2e)),
        e2e_delay_q95=float(np.quantile(e2e, 0.95)),
        mix_delay_expected=layers * float(params.get("mixdelay", 0)),
        stats=stats,
        malformed_lines=malformed,
        n_adversaries=len(adv_set),
        adv_frac=len(adv_set) / int(params.get('n', 1)) if params.get('n') else 0.0,
        adv_messages=len(adv_msg),
        adv_mixes=len([m for m in mixes if m in adv_set]),
    )
    if verbose:
        print(json.dumps(res, indent=2))
    return res


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("logs", nargs="+")
    ap.add_argument("--targets", type=int, default=200)
    ap.add_argument("--burn", type=float, default=0.25)
    ap.add_argument("--drain", type=float, default=0.15)
    ap.add_argument("--seed", type=int, default=1)
    ap.add_argument("--out", default=None)
    a = ap.parse_args()
    rows = []
    for p in a.logs:
        r = compute(p, a.targets, a.burn, a.drain, a.seed)
        rows.append(r)
        if "error" in r:
            print(f"{os.path.basename(p)}: {r['error']}")
        else:
            print(f"{r['log']}: L={r['layers']} H={r['entropy_mean']:.3f} bits "
                  f"(median {r['entropy_median']:.3f}, set {r['anonymity_set_mean']:.0f}) "
                  f"delay={r['e2e_delay_mean']:.2f}s delivery={r['delivery_rate']:.3f} "
                  f"targets={r['n_targets']} outputs={r['n_outputs']} "
                  f"mass={r['surviving_mass_mean']:.3f}")
    if a.out:
        with open(a.out, "w") as fh:
            json.dump(rows, fh, indent=2)
