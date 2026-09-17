#!/usr/bin/env python3
"""Write the job manifest: one line per simulation, indexed for a scheduler job array.

The grid and the job names are exactly those of run_attacks.py, so a result produced on the
cluster is interchangeable with one produced locally.  Jobs are ordered longest-first within
each seed, so array tasks with low indices are the expensive ones.
"""
import argparse, os, sys
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
import run_attacks as ra                                        # noqa: E402


def build(traces, layers, fracs, seeds, attacks):
    jobs, seen = [], set()
    for seed in seeds:
        batch = []
        for trace in traces:
            for L in layers:
                for attack in attacks:
                    for frac in fracs:
                        name = ra.job_name(trace, L, seed, attack, frac)
                        if name in seen:
                            continue
                        seen.add(name)
                        batch.append((trace, L, seed, attack, frac))
        batch.sort(key=lambda j: -ra.cost(j[0], j[1], j[3], j[4]))
        jobs.extend(batch)
    return jobs


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--traces", nargs="+", default=["march", "chain"])
    ap.add_argument("--layers", type=int, nargs="+", default=[3, 4, 5, 6])
    ap.add_argument("--fracs", type=float, nargs="+", default=[0.0, 0.1, 0.2, 0.3, 0.4])
    ap.add_argument("--seeds", type=int, nargs="+", default=[1, 2, 3])
    ap.add_argument("--attacks", nargs="+", default=["drop", "cmix"])
    ap.add_argument("--out", default=os.path.join(HERE, "jobs.tsv"))
    a = ap.parse_args()
    jobs = build(a.traces, a.layers, a.fracs, a.seeds, a.attacks)
    with open(a.out, "w") as fh:
        fh.write("index\ttrace\tlayers\tseed\tattack\tfrac\tname\n")
        for i, (t, L, s, atk, f) in enumerate(jobs):
            fh.write(f"{i}\t{t}\t{L}\t{s}\t{atk}\t{f}\t{ra.job_name(t, L, s, atk, f)}\n")
    print(f"wrote {a.out}: {len(jobs)} jobs")
