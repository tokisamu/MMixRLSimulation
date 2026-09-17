#!/usr/bin/env python3
"""Run exactly one job of the manifest.  Meant to be called once per scheduler array task.

    python3 run_one.py --index $SLURM_ARRAY_TASK_ID

Generates the scenario, runs ns-3, analyses the event log and writes the result file, using
the same code path as the local driver.  Exits non-zero if the job did not produce a result,
so the scheduler records it as failed and it can be resubmitted by index.
"""
import argparse, csv, os, sys, time
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
import run_attacks as ra                                        # noqa: E402


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--index", type=int, required=True)
    ap.add_argument("--manifest", default=os.path.join(HERE, "jobs.tsv"))
    ap.add_argument("--duration", type=int, default=300)
    ap.add_argument("--warmup", type=int, default=60)
    ap.add_argument("--drain", type=int, default=60)
    ap.add_argument("--range", type=float, default=10.0)
    ap.add_argument("--carry", type=int, default=120)
    ap.add_argument("--timeout", type=int, default=23 * 3600)
    a = ap.parse_args()

    rows = list(csv.DictReader(open(a.manifest), delimiter="\t"))
    if not 0 <= a.index < len(rows):
        sys.exit(f"index {a.index} outside the manifest (0..{len(rows)-1})")
    r = rows[a.index]
    job = (r["trace"], int(r["layers"]), int(r["seed"]), r["attack"], float(r["frac"]))
    os.makedirs(ra.SCN, exist_ok=True)
    os.makedirs(ra.OUT, exist_ok=True)

    def progress(kind, name, wall):
        print(f"{time.strftime('%Y-%m-%d %H:%M:%S')} {kind} {name} {wall/60:.1f} min", flush=True)

    print(f"task {a.index}: {r['name']} on {os.uname().nodename}", flush=True)
    name, msg = ra.run_job(job, a, progress)
    print(f"{name}: {msg}", flush=True)
    if msg not in ("ok", "cached"):
        sys.exit(1)


if __name__ == "__main__":
    main()
