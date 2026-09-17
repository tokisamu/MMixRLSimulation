#!/usr/bin/env python3
"""Drive the AnoRL mix simulator over a parameter grid and collect the metrics.

Generates any scenario that is missing, runs ns-3 with a bounded number of workers, then
runs the entropy analysis over every event log and writes one JSON table.
"""
import argparse
import itertools
import json
import os
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor

HERE = os.path.dirname(os.path.abspath(__file__))
SCN = os.path.join(HERE, "scenarios")
RES = os.path.join(HERE, "results")
BIN = os.path.expanduser(
    os.environ.get("ANORL_BIN", "~/ns3/ns-3.48/build/scratch/ns3.48-anorl-mix-optimized"))
sys.path.insert(0, os.path.join(HERE, "analysis"))
from entropy import compute                                   # noqa: E402


def scenario_name(model, layers, rate, seed, adv=0.0):
    tag = f"_a{int(round(adv*100)):02d}" if adv > 0 else ""
    return f"{model}_L{layers}_r{int(rate)}_s{seed}{tag}"


def ensure_scenario(model, layers, rate, duration, warmup, seed, mix_frac,
                    budget_client, budget_mult, adv=0.0):
    name = scenario_name(model, layers, rate, seed, adv)
    scn = os.path.join(SCN, name + ".scn")
    if os.path.exists(scn):
        return name
    cmd = [sys.executable, os.path.join(SCN, "gen_scenario.py"),
           "--model", model, "--layers", str(layers), "--rate", str(rate),
           "--duration", str(duration), "--warmup", str(warmup), "--seed", str(seed),
           "--mix-frac", str(mix_frac), "--budget-client", str(budget_client),
           "--budget-mult", str(budget_mult), "--adv-frac", str(adv),
           "--out", SCN, "--name", name]
    subprocess.run(cmd, check=True, capture_output=True)
    return name


def run_one(job):
    name, stop, transport, mixdelay, pktsize, rng, seed, carry, carrygap, guard, grace = job
    log = os.path.join(RES, name + ".log")
    if os.path.exists(log) and os.path.getsize(log) > 0:
        # only reuse a log from a run that actually finished; a truncated one is a
        # killed or crashed run and must not be silently analysed
        with open(log, "rb") as fh:
            fh.seek(max(0, os.path.getsize(log) - 4096))
            if b"# STATS" in fh.read():
                return name, "cached"
        os.remove(log)
    cmd = [BIN, f"--scn={os.path.join(SCN, name + '.scn')}",
           f"--mob={os.path.join(SCN, name + '.ns2mobility')}",
           f"--out={log}", f"--transport={transport}", f"--mixdelay={mixdelay}",
           f"--pktsize={pktsize}", f"--range={rng}", f"--stop={stop}", f"--seed={seed}",
           f"--carry={carry}", f"--carrygap={carrygap}", f"--guard={guard}", f"--grace={grace}"]
    t0 = time.time()
    p = subprocess.run(cmd, capture_output=True, text=True)
    if p.returncode != 0:
        return name, f"FAILED: {p.stderr.strip()[:300]}"
    return name, f"{time.time() - t0:.0f}s  {p.stdout.strip().splitlines()[-1]}"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--model", default="chain")
    ap.add_argument("--layers", type=int, nargs="+", default=[3, 4, 5, 6])
    ap.add_argument("--rate", type=float, nargs="+", default=[10.0])
    ap.add_argument("--seeds", type=int, nargs="+", default=[1])
    ap.add_argument("--duration", type=int, default=300)
    ap.add_argument("--warmup", type=int, default=60)
    ap.add_argument("--drain", type=int, default=60)
    ap.add_argument("--mix-frac", type=float, default=0.10)
    ap.add_argument("--budget-client", type=int, default=10)
    ap.add_argument("--budget-mult", type=int, default=250)
    ap.add_argument("--mixdelay", type=float, default=5.0)
    ap.add_argument("--pktsize", type=int, default=1024)
    ap.add_argument("--range", type=float, default=10.0)
    ap.add_argument("--transport", default="route")
    ap.add_argument("--adv-frac", type=float, nargs="+", default=[0.0],
                    help="fractions of participants controlled by the adversary")
    ap.add_argument("--carry", type=int, default=20,
                    help="store-carry-forward retries when no route exists")
    ap.add_argument("--carrygap", type=float, default=1.0,
                    help="seconds between store-carry-forward retries")
    ap.add_argument("--guard", type=float, default=0.0,
                    help="seconds at the end of a slot in which nobody originates")
    ap.add_argument("--grace", type=float, default=0.0,
                    help="seconds a spend stays valid past the end of its own slot")
    ap.add_argument("--jobs", type=int, default=3)
    ap.add_argument("--targets", type=int, default=200)
    ap.add_argument("--out", default=os.path.join(RES, "sweep.json"))
    a = ap.parse_args()

    os.makedirs(RES, exist_ok=True)
    jobs = []
    for L, r, s, adv in itertools.product(a.layers, a.rate, a.seeds, a.adv_frac):
        name = ensure_scenario(a.model, L, r, a.duration, a.warmup, s, a.mix_frac,
                               a.budget_client, a.budget_mult, adv)
        stop = a.warmup + a.duration + a.drain
        jobs.append((name, stop, a.transport, a.mixdelay, a.pktsize, a.range, s,
                     a.carry, a.carrygap, a.guard, a.grace))

    print(f"{len(jobs)} runs, {a.jobs} at a time")
    with ThreadPoolExecutor(max_workers=a.jobs) as ex:
        for name, msg in ex.map(run_one, jobs):
            print(f"  {name}: {msg}")

    rows = []
    for (name, *_rest) in jobs:
        log = os.path.join(RES, name + ".log")
        if not os.path.exists(log):
            continue
        r = compute(log, n_targets=a.targets, seed=1)
        r["scenario"] = name
        r["model"] = a.model
        rows.append(r)
        if "error" in r:
            print(f"  {name}: {r['error']}")
        else:
            print(f"  {name}: L={r['layers']} H={r['entropy_mean']:.3f} "
                  f"delay={r['e2e_delay_mean']:.2f}s delivery={r['delivery_rate']:.3f}")
    with open(a.out, "w") as fh:
        json.dump(rows, fh, indent=2)
    print(f"wrote {a.out}")


if __name__ == "__main__":
    main()
