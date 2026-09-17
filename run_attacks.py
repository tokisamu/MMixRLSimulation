#!/usr/bin/env python3
"""Separated attack experiments: droppers, and corrupted mixes.

Grid: {chain, march} x layers {3,4,5,6} x ratio {0,0.1,0.2,0.3,0.4} x seeds {1,2,3}, for two
attacks.  frac = 0 is one control shared by both attacks, so the grid is 24 controls plus
96 dropper runs plus 96 corrupted-mix runs, 216 simulations.

Each worker generates its scenario, runs ns-3, analyses the event log and writes a result
file, all before taking the next job, so results accumulate as the run proceeds and a
crash or interruption loses at most the jobs in flight.  Rerunning resumes: a job whose
result file exists and whose event log carries the end-of-run marker is skipped.
"""
import argparse, json, os, subprocess, sys, time, threading
from concurrent.futures import ThreadPoolExecutor, as_completed

HERE = os.path.dirname(os.path.abspath(__file__))
SCN = os.environ.get("ANORL_SCN", os.path.join(HERE, "scenarios", "attacks"))
OUT = os.environ.get("ANORL_OUT", os.path.join(HERE, "results", "attacks"))
BIN = os.path.expanduser(os.environ.get(
    "ANORL_BIN", "~/ns3/ns-3.48/build/scratch/ns3.48-anorl-mix-optimized"))
sys.path.insert(0, os.path.join(HERE, "analysis"))
from entropy import compute                                       # noqa: E402

LOCK = threading.Lock()


def job_name(trace, L, seed, attack, frac):
    if frac == 0:
        return f"atk_{trace}_L{L}_s{seed}_ctl"
    return f"atk_{trace}_L{L}_s{seed}_{attack}{int(round(frac * 100)):02d}"


def log_complete(path):
    if not os.path.exists(path) or os.path.getsize(path) == 0:
        return False
    with open(path, "rb") as fh:
        fh.seek(max(0, os.path.getsize(path) - 4096))
        return b"# STATS" in fh.read()


def legacy_matches(log, want):
    """A result written before run settings were recorded.  Accept it only if its own event
    log shows the same simulated length and radio range.  The carry budget was not logged;
    every such result came from a launch that used the default."""
    try:
        with open(log) as fh:
            for _ in range(5):
                line = fh.readline()
                if line.startswith("# PARAM"):
                    tok = line.split()[2:]
                    p = dict(zip(tok[0::2], tok[1::2]))
                    stop = want["warmup"] + want["duration"] + want["drain"]
                    return (abs(float(p.get("stop", -1)) - stop) < 1e-6
                            and abs(float(p.get("range", -1)) - float(want["range"])) < 1e-6)
    except Exception:
        return False
    return False


def cost(trace, L, attack, frac):
    """Rough relative cost, used only to schedule the longest jobs first."""
    hops = 20.0 if trace == "chain" else 1.6
    msgs = 12500 + (45000 * frac / 0.1 if attack == "cmix" else 0)
    return msgs * (L + 1) * hops


def run_job(job, args, progress):
    trace, L, seed, attack, frac = job
    name = job_name(trace, L, seed, attack, frac)
    log = os.path.join(OUT, name + ".log")
    res = os.path.join(OUT, name + ".result.json")
    want = {k: getattr(args, k) for k in ("duration", "warmup", "drain", "range", "carry")}
    if os.path.exists(res) and log_complete(log):
        try:
            prior = json.load(open(res))
        except Exception:
            prior = None                           # unreadable: rerun
        made_with = prior.get("run_params") if isinstance(prior, dict) else None
        legacy = (isinstance(prior, dict) and "run_params" not in prior
                  and legacy_matches(log, want))
        if made_with == want or legacy:
            progress("skip", name, 0.0)
            return name, "cached"
        for stale in (res, log):                   # made with other settings: rerun
            try:
                os.remove(stale)
            except OSError:
                pass

    t0 = time.time()
    scn = os.path.join(SCN, name + ".scn")
    meta_path = os.path.join(SCN, name + ".json")
    if os.path.exists(scn) and os.path.exists(meta_path):
        try:
            m = json.load(open(meta_path))
            fresh = (m.get("duration") == args.duration and m.get("warmup") == args.warmup)
        except Exception:
            fresh = False
        if not fresh:                              # a scenario built for other durations
            for ext in (".scn", ".json", ".ns2mobility"):
                try:
                    os.remove(os.path.join(SCN, name + ext))
                except OSError:
                    pass
    if not os.path.exists(scn):
        gen = [sys.executable, os.path.join(HERE, "scenarios", "gen_scenario.py"),
               "--model", trace, "--layers", str(L), "--rate", "10",
               "--duration", str(args.duration), "--warmup", str(args.warmup),
               "--seed", str(seed), "--attack", attack if frac > 0 else "drop",
               "--attack-frac", str(frac), "--out", SCN, "--name", name]
        try:
            g = subprocess.run(gen, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                               universal_newlines=True)
        except OSError as e:
            progress("fail", name, time.time() - t0)
            return name, f"GENERATE FAILED: cannot launch {sys.executable}: {e}"
        if g.returncode != 0:
            progress("fail", name, time.time() - t0)
            return name, f"GENERATE FAILED: {g.stderr.strip()[-300:]}"

    stop = args.warmup + args.duration + args.drain
    sim = [BIN, f"--scn={scn}", f"--mob={os.path.join(SCN, name + '.ns2mobility')}",
           f"--out={log}", "--transport=route", "--mixdelay=5", "--pktsize=1024",
           f"--range={args.range}", f"--stop={stop}", f"--seed={seed}",
           f"--carry={args.carry}", "--carrygap=1.0", "--guard=0", "--grace=0"]
    try:
        p = subprocess.run(sim, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                           universal_newlines=True, timeout=args.timeout)
    except subprocess.TimeoutExpired:
        progress("fail", name, time.time() - t0)
        return name, f"TIMED OUT after {args.timeout} s"
    except OSError as e:                          # a wrong ANORL_BIN, or a binary that
        progress("fail", name, time.time() - t0)  # cannot execute on this node
        return name, f"SIMULATION FAILED: cannot launch {BIN}: {e}"
    if p.returncode != 0 or not log_complete(log):
        progress("fail", name, time.time() - t0)
        return name, f"SIMULATION FAILED rc={p.returncode}: {p.stderr.strip()[-300:]}"

    try:
        r = compute(log, n_targets=200, seed=1)
    except Exception as e:                       # keep the log; record why it failed
        progress("fail", name, time.time() - t0)
        return name, f"ANALYSIS FAILED: {e!r}"
    import platform
    import numpy as _np
    r.update(python_version=platform.python_version(), numpy_version=_np.__version__,
             host=platform.node(), ns3_binary=os.path.basename(BIN), run_params=want)
    r.update(trace=trace, layers=L, seed=seed, attack=attack if frac > 0 else "none",
             frac=frac, scenario=name, wall_seconds=round(time.time() - t0, 1))
    meta = json.load(open(os.path.join(SCN, name + ".json")))
    r.update(droppers=len(meta.get("droppers", [])), cmixes=len(meta.get("cmixes", [])),
             targeted_honest_mixes=len(meta.get("targeted_honest_mixes", [])),
             honest_mixes=meta.get("honest_mixes"))
    tmp = res + ".tmp"
    with open(tmp, "w") as fh:
        json.dump(r, fh, indent=2, default=str)
    os.replace(tmp, res)
    # the scenario is regenerable bit for bit, so its bulky files need not be kept
    for ext in (".scn", ".ns2mobility"):
        try:
            os.remove(os.path.join(SCN, name + ext))
        except OSError:
            pass
    progress("done", name, time.time() - t0)
    return name, "ok"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--traces", nargs="+", default=["march", "chain"])
    ap.add_argument("--layers", type=int, nargs="+", default=[3, 4, 5, 6])
    ap.add_argument("--fracs", type=float, nargs="+", default=[0.0, 0.1, 0.2, 0.3, 0.4])
    ap.add_argument("--seeds", type=int, nargs="+", default=[1, 2, 3])
    ap.add_argument("--attacks", nargs="+", default=["drop", "cmix"])
    ap.add_argument("--jobs", type=int, default=8)
    ap.add_argument("--duration", type=int, default=300)
    ap.add_argument("--warmup", type=int, default=60)
    ap.add_argument("--drain", type=int, default=60)
    ap.add_argument("--range", type=float, default=10.0)
    ap.add_argument("--carry", type=int, default=120)
    ap.add_argument("--timeout", type=int, default=6 * 3600)
    a = ap.parse_args()
    os.makedirs(SCN, exist_ok=True)
    os.makedirs(OUT, exist_ok=True)

    jobs, seen = [], set()
    for seed in a.seeds:
        batch = []
        for trace in a.traces:
            for L in a.layers:
                for attack in a.attacks:
                    for frac in a.fracs:
                        key = job_name(trace, L, seed, attack, frac)
                        if key in seen:
                            continue            # the frac = 0 control is shared
                        seen.add(key)
                        batch.append((trace, L, seed, attack, frac))
        # complete every seed before starting the next, longest jobs first within a seed,
        # so a full single-seed picture exists early and stragglers do not pile up at the end
        batch.sort(key=lambda j: -cost(j[0], j[1], j[3], j[4]))
        jobs.extend(batch)

    total = len(jobs)
    state = dict(done=0, fail=0, skip=0, started=time.time(), walls=[])
    prog = os.path.join(OUT, "progress.txt")

    def progress(kind, name, wall):
        with LOCK:
            state[kind] += 1
            if kind == "done":
                state["walls"].append(wall)
            finished = state["done"] + state["fail"] + state["skip"]
            elapsed = time.time() - state["started"]
            remaining = total - finished
            eta = ""
            if state["done"]:
                rate = state["done"] / elapsed if elapsed > 0 else 0
                if rate > 0:
                    eta = f"  eta {remaining / rate / 3600:.1f} h"
            line = (f"{time.strftime('%H:%M:%S')} {finished}/{total} "
                    f"(done {state['done']}, cached {state['skip']}, failed {state['fail']})"
                    f"  elapsed {elapsed/3600:.2f} h{eta}  last: {kind} {name} {wall/60:.1f} min")
            with open(prog, "a") as fh:
                fh.write(line + "\n")
            print(line, flush=True)

    with open(prog, "a") as fh:
        fh.write(f"\n=== start {time.strftime('%Y-%m-%d %H:%M:%S')}: {total} jobs, "
                 f"{a.jobs} workers ===\n")
    with ThreadPoolExecutor(max_workers=a.jobs) as ex:
        futs = [ex.submit(run_job, j, a, progress) for j in jobs]
        for f in as_completed(futs):
            try:
                name, msg = f.result()
                if msg not in ("ok", "cached"):
                    print(f"  {name}: {msg}", flush=True)
            except Exception as e:                          # never let one job stop the rest
                print(f"  job raised: {e!r}", flush=True)
    with open(prog, "a") as fh:
        fh.write(f"=== finished {time.strftime('%Y-%m-%d %H:%M:%S')} ===\n")
    open(os.path.join(OUT, "ALL_DONE"), "w").write(time.strftime("%Y-%m-%d %H:%M:%S\n"))


if __name__ == "__main__":
    main()
