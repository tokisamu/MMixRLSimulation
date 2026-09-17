#!/usr/bin/env python3
"""Build an AnoRL mix-network scenario from an Amigo mobility trace.

Reads the raw Amigo arrays (T, N, 2) and writes three files that the ns-3 side consumes:

  <name>.ns2mobility   ns-2 movement trace, one setdest per node per second, read by
                       ns3::Ns2MobilityHelper.  Time is re-based so that t=0 in the
                       simulation is the first second after the crowd leaves the staging
                       area, because the first ~630 s of every Amigo trace has all 250
                       nodes inside a 7 m square and is not a mobile ad-hoc network.
  <name>.scn           line-oriented scenario for the C++ side: roles, budgets, and the
                       exact (time, src, path) message list.
  <name>.json          the same data for tooling.

Nothing in this directory writes outside anorl-mixsim/.
"""
import argparse
import json
import os
import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
AMIGO = os.environ.get("ANORL_AMIGO", os.path.join(ROOT, "amigo_copy"))


def load_trace(model):
    path = os.path.join(AMIGO, f"{model}_node250_0.npy")
    return np.load(path)


def staging_end(arr, thresh=20.0):
    """First sample at which the crowd's bounding box exceeds `thresh` metres."""
    ext = (arr.max(axis=1) - arr.min(axis=1)).max(axis=1)
    idx = int(np.argmax(ext > thresh)) if (ext > thresh).any() else 0
    return idx


def write_mobility(arr, t0, t1, path):
    """ns-2 trace at 1 s resolution, re-based to t0."""
    n = arr.shape[1]
    with open(path, "w") as fh:
        p0 = arr[t0]
        for i in range(n):
            fh.write(f"$node_({i}) set X_ {p0[i,0]:.3f}\n")
            fh.write(f"$node_({i}) set Y_ {p0[i,1]:.3f}\n")
            fh.write(f"$node_({i}) set Z_ 0.0\n")
        for t in range(t0, t1 - 1):
            pa, pb = arr[t], arr[t + 1]
            d = np.linalg.norm(pb - pa, axis=1)
            rt = t - t0
            for i in range(n):
                speed = max(d[i], 0.001)          # 1 s samples, so speed == distance
                fh.write(f'$ns_ at {rt}.0 "$node_({i}) setdest '
                         f'{pb[i,0]:.3f} {pb[i,1]:.3f} {speed:.4f}"\n')
    return path


def build(model, mix_frac, layers, rate_per_min, duration, warmup, seed,
          budget_client, budget_mult, outdir, name=None, adv_frac=0.0):
    # Three independent streams so that changing one knob does not perturb the others:
    # the mix set and the (time, sender) workload are identical across layer counts,
    # and only the paths change.  Comparisons across L are then paired.
    rng_role = np.random.default_rng(seed)
    rng_load = np.random.default_rng(seed + 10_000)
    rng_path = np.random.default_rng(seed + 20_000 + layers)
    rng_adv = np.random.default_rng(seed + 30_000)
    arr = load_trace(model)
    t0 = staging_end(arr)
    T = arr.shape[0]
    n = arr.shape[1]
    t1 = min(T, t0 + warmup + duration + 60)
    if t1 - t0 < warmup + duration:
        raise SystemExit(f"trace too short: have {t1-t0}s after staging, need {warmup+duration}s")

    n_mix = max(layers, int(round(mix_frac * n)))
    perm = rng_role.permutation(n)
    mixes = sorted(int(x) for x in perm[:n_mix])
    clients = sorted(int(x) for x in perm[n_mix:])
    mix_set = set(mixes)

    # The adversary controls a fraction of the participants, drawn independently of the
    # mix assignment, so about adv_frac of the mixes are adversarial too.
    n_adv = int(round(adv_frac * n))
    adversaries = sorted(int(x) for x in rng_adv.choice(n, size=n_adv, replace=False)) \
        if n_adv else []
    adv_set = set(adversaries)
    adv_mixes = [m for m in mixes if m in adv_set]
    honest_mixes = [m for m in mixes if m not in adv_set]

    # Budgets, in tokens per slot of 60 s.  A client may originate `budget_client`
    # messages per minute; a mix holds n times that, which is the parameter the paper
    # calls the budget ratio a.
    budget_mix = budget_client * budget_mult

    # Workload: every participant originates at `rate_per_min` per minute over the
    # measurement window, each with a freshly drawn random path of `layers` distinct mixes.
    msgs = []
    mid = 0
    lam = rate_per_min / 60.0
    for src in range(n):
        if src in adv_set:
            continue                      # adversaries do not carry honest traffic
        t = warmup + rng_load.exponential(1.0 / lam)
        while t < warmup + duration:
            path = rng_path.choice(mixes, size=layers, replace=False)
            msgs.append(dict(t=round(float(t), 3), src=int(src),
                             path=[int(x) for x in path], mid=mid))
            mid += 1
            t += rng_load.exponential(1.0 / lam)

    # The adversary spends every token it holds.  An adversarial client floods on random
    # paths.  An adversarial mix holds the far larger mix budget and aims all of it at one
    # fixed sequence of honest mixes, so that those mixes spend their own budget forwarding
    # its traffic and have none left for honest messages.  Adversarial mixes take disjoint
    # sequences so that they paralyse as many distinct mixes as their budgets allow.
    targets = {}
    if adv_mixes and honest_mixes:
        pool = list(rng_adv.permutation(honest_mixes))
        cursor = 0
        for a in adv_mixes:
            seq = []
            for _ in range(layers):
                if cursor >= len(pool):        # more adversarial capacity than mixes to
                    pool = list(rng_adv.permutation(honest_mixes))   # attack: start over
                    cursor = 0
                cand = pool[cursor]; cursor += 1
                if cand not in seq:
                    seq.append(cand)
            while len(seq) < layers:           # pad if the pool is smaller than `layers`
                seq.append(honest_mixes[len(seq) % len(honest_mixes)])
            targets[a] = seq

    n_slots = int(np.ceil((warmup + duration) / 60.0))
    for a in adversaries:
        is_mix = a in mix_set
        budget = (budget_client * budget_mult) if is_mix else budget_client
        for slot in range(n_slots):
            lo = max(slot * 60.0, warmup)
            hi = min((slot + 1) * 60.0, warmup + duration)
            if hi <= lo:
                continue
            times = np.sort(rng_adv.uniform(lo, hi, budget))
            for t in times:
                if is_mix:
                    path = [int(x) for x in targets[a]]
                else:
                    path = [int(x) for x in rng_adv.choice(mixes, size=layers, replace=False)]
                msgs.append(dict(t=round(float(t), 3), src=int(a), path=path, mid=int(mid)))
                mid += 1
    msgs.sort(key=lambda m: m["t"])
    for k, m in enumerate(msgs):
        m["mid"] = k

    name = name or f"{model}_L{layers}_r{rate_per_min}"
    os.makedirs(outdir, exist_ok=True)
    mob = os.path.join(outdir, name + ".ns2mobility")
    write_mobility(arr, t0, t1, mob)

    doc = dict(model=model, n=n, n_mix=n_mix, mix_frac=mix_frac, layers=layers,
               rate_per_min=rate_per_min, duration=duration, warmup=warmup, seed=seed,
               staging_end=t0, trace_len=t1 - t0, adv_frac=adv_frac,
               budget_client=budget_client, budget_mix=budget_mix,
               mixes=mixes, clients=clients,
               adversaries=[int(x) for x in adversaries],
               adv_mixes=[int(x) for x in adv_mixes],
               adv_targets={str(int(k)): [int(x) for x in v] for k, v in targets.items()},
               messages=len(msgs), workload=msgs)
    with open(os.path.join(outdir, name + ".json"), "w") as fh:
        json.dump(doc, fh)

    with open(os.path.join(outdir, name + ".scn"), "w") as fh:
        fh.write(f"N {n}\nMODEL {model}\nLAYERS {layers}\n")
        fh.write(f"WARMUP {warmup}\nDURATION {duration}\nSEED {seed}\n")
        fh.write(f"BUDGET_CLIENT {budget_client}\nBUDGET_MIX {budget_mix}\n")
        fh.write("MIXES " + " ".join(str(x) for x in mixes) + "\n")
        if adversaries:
            fh.write("ADV " + " ".join(str(x) for x in adversaries) + "\n")
        for m in msgs:
            fh.write(f"MSG {m['t']:.3f} {m['src']} {m['mid']} "
                     + " ".join(str(x) for x in m["path"]) + "\n")

    print(f"{name}: n={n} mixes={n_mix} layers={layers} messages={len(msgs)} "
          f"window={duration}s (trace t0={t0}) budget client={budget_client} "
          f"mix={budget_mix} adversaries={len(adversaries)} "
          f"(of which mixes: {len(adv_mixes)}) targeted mixes={len(set(sum(targets.values(), [])))}")
    return name


def build_attack(model, mix_frac, layers, rate_per_min, duration, warmup, seed,
                 budget_client, budget_mult, outdir, name, attack, frac):
    """Scenario for the separated attack experiments.

    Two attacks are modelled one at a time, so that their effects can be told apart.

      drop   A fraction `frac` of all participants are droppers, drawn from the non-mixes
             so that every mix stays honest.  A dropper discards every honest message it
             receives and sends nothing.
      cmix   A fraction `frac` of the mixes are corrupted.  A corrupted mix refuses every
             honest message addressed to it, relays honest traffic addressed elsewhere
             normally, and spends its whole mix budget originating traffic along one fixed
             sequence of honest mixes; corrupted mixes take disjoint sequences.

    The design is paired.  A participant's honest messages depend only on the seed, the
    participant and the layer count, never on which other participants are adversarial,
    so every honest participant sends exactly the same messages at every ratio and in both
    experiments.  The adversary sets are nested: the droppers or corrupted mixes at a
    ratio include those at every smaller ratio.  frac = 0 is therefore one control shared
    by both experiments.
    """
    if attack not in ("drop", "cmix"):
        raise SystemExit(f"unknown attack {attack!r}")
    arr = load_trace(model)
    t0 = staging_end(arr)
    T, n = arr.shape[0], arr.shape[1]
    t1 = min(T, t0 + warmup + duration + 60)
    if t1 - t0 < warmup + duration:
        raise SystemExit(f"trace too short: have {t1-t0}s after staging, need {warmup+duration}s")

    n_mix = max(layers, int(round(mix_frac * n)))
    perm = np.random.default_rng(seed).permutation(n)
    mixes = sorted(int(x) for x in perm[:n_mix])
    non_mixes = sorted(int(x) for x in perm[n_mix:])
    budget_mix = budget_client * budget_mult

    def round_half_up(x):
        return int(np.floor(x + 0.5))

    droppers, cmixes = [], []
    if attack == "drop":
        order = [int(x) for x in np.random.default_rng(seed + 40_000).permutation(non_mixes)]
        droppers = sorted(order[:round_half_up(frac * n)])
    else:
        order = [int(x) for x in np.random.default_rng(seed + 50_000).permutation(mixes)]
        cmixes = sorted(order[:round_half_up(frac * n_mix)])
    adversary = set(droppers) | set(cmixes)

    lam = rate_per_min / 60.0
    msgs = []
    for src in range(n):
        if src in adversary:
            continue
        r_time = np.random.default_rng([seed, 10_000, src])
        r_path = np.random.default_rng([seed, 20_000, layers, src])
        t = warmup + r_time.exponential(1.0 / lam)
        while t < warmup + duration:
            path = r_path.choice(mixes, size=layers, replace=False)
            msgs.append(dict(t=round(float(t), 3), src=int(src),
                             path=[int(x) for x in path], mid=0))
            t += r_time.exponential(1.0 / lam)

    honest_mixes = [m for m in mixes if m not in set(cmixes)]
    targets = {}
    if cmixes:
        if len(honest_mixes) < layers:
            raise SystemExit("fewer honest mixes than layers: no sequence can be formed")
        r_tgt = np.random.default_rng(seed + 60_000 + layers)
        pool = [int(x) for x in r_tgt.permutation(honest_mixes)]
        cursor = 0
        for a in cmixes:
            seq = []
            while len(seq) < layers:
                if cursor >= len(pool):          # more capacity than honest mixes: the
                    pool = [int(x) for x in r_tgt.permutation(honest_mixes)]   # sequences
                    cursor = 0                   # necessarily start to overlap
                c = pool[cursor]
                cursor += 1
                if c not in seq:
                    seq.append(c)
            targets[a] = seq
        n_slots = int(np.ceil((warmup + duration) / 60.0))
        for a in cmixes:
            r_flood = np.random.default_rng([seed, 70_000, layers, a])
            for slot in range(n_slots):
                lo = max(slot * 60.0, warmup)
                hi = min((slot + 1) * 60.0, warmup + duration)
                if hi <= lo:
                    continue
                for t in np.sort(r_flood.uniform(lo, hi, budget_mix)):
                    msgs.append(dict(t=round(float(t), 3), src=int(a),
                                     path=list(targets[a]), mid=0))

    msgs.sort(key=lambda m: (m["t"], m["src"]))
    for k, m in enumerate(msgs):
        m["mid"] = k

    os.makedirs(outdir, exist_ok=True)
    write_mobility(arr, t0, t1, os.path.join(outdir, name + ".ns2mobility"))
    covered = sorted(set(x for v in targets.values() for x in v))
    doc = dict(model=model, n=n, n_mix=n_mix, mix_frac=mix_frac, layers=layers,
               rate_per_min=rate_per_min, duration=duration, warmup=warmup, seed=seed,
               staging_end=t0, trace_len=t1 - t0, attack=attack, attack_frac=frac,
               budget_client=budget_client, budget_mix=budget_mix, mixes=mixes,
               droppers=droppers, cmixes=cmixes,
               cmix_targets={str(k): v for k, v in targets.items()},
               targeted_honest_mixes=covered, honest_mixes=len(honest_mixes),
               honest_messages=sum(1 for m in msgs if m["src"] not in adversary),
               messages=len(msgs), workload=msgs)
    with open(os.path.join(outdir, name + ".json"), "w") as fh:
        json.dump(doc, fh)
    with open(os.path.join(outdir, name + ".scn"), "w") as fh:
        fh.write(f"N {n}\nMODEL {model}\nLAYERS {layers}\n")
        fh.write(f"WARMUP {warmup}\nDURATION {duration}\nSEED {seed}\n")
        fh.write(f"BUDGET_CLIENT {budget_client}\nBUDGET_MIX {budget_mix}\n")
        fh.write("MIXES " + " ".join(str(x) for x in mixes) + "\n")
        if droppers:
            fh.write("DROPPER " + " ".join(str(x) for x in droppers) + "\n")
        if cmixes:
            fh.write("CMIX " + " ".join(str(x) for x in cmixes) + "\n")
        for m in msgs:
            fh.write(f"MSG {m['t']:.3f} {m['src']} {m['mid']} "
                     + " ".join(str(x) for x in m["path"]) + "\n")
    print(f"{name}: attack={attack} frac={frac} droppers={len(droppers)} "
          f"corrupted mixes={len(cmixes)} honest mixes targeted={len(covered)}/{len(honest_mixes)} "
          f"honest msgs={doc['honest_messages']} total msgs={len(msgs)}")
    return name


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--model", default="blockade1",
                    choices=["march", "gather", "chain", "blockade1"])
    ap.add_argument("--mix-frac", type=float, default=0.10)
    ap.add_argument("--layers", type=int, default=3)
    ap.add_argument("--rate", type=float, default=10.0, help="messages per participant per minute")
    ap.add_argument("--duration", type=int, default=300)
    ap.add_argument("--warmup", type=int, default=30)
    ap.add_argument("--seed", type=int, default=1)
    ap.add_argument("--budget-client", type=int, default=10, help="tokens per 60 s slot")
    ap.add_argument("--budget-mult", type=int, default=250, help="mix budget = n x client budget")
    ap.add_argument("--out", default=HERE)
    ap.add_argument("--name", default=None)
    ap.add_argument("--adv-frac", type=float, default=0.0,
                    help="fraction of participants controlled by the adversary")
    ap.add_argument("--attack", choices=["none", "drop", "cmix"], default="none",
                    help="separated attack experiment; overrides --adv-frac")
    ap.add_argument("--attack-frac", type=float, default=0.0,
                    help="droppers as a fraction of participants, or corrupted mixes "
                         "as a fraction of mixes")
    a = ap.parse_args()
    if a.attack != "none":
        build_attack(a.model, a.mix_frac, a.layers, a.rate, a.duration, a.warmup,
                     a.seed, a.budget_client, a.budget_mult, a.out,
                     a.name or f"atk_{a.model}_L{a.layers}", a.attack, a.attack_frac)
    else:
        build(a.model, a.mix_frac, a.layers, a.rate, a.duration, a.warmup, a.seed,
              a.budget_client, a.budget_mult, a.out, a.name, a.adv_frac)
