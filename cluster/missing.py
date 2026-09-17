#!/usr/bin/env python3
"""List manifest jobs that have no finished result, as a SLURM array spec for resubmission.

    python3 cluster/missing.py [--out RESULTS_DIR]
    sbatch ... --array=<printed spec> cluster/task.slurm
"""
import argparse, csv, os, sys

def complete(log):
    if not os.path.exists(log) or os.path.getsize(log) == 0:
        return False
    with open(log, "rb") as fh:
        fh.seek(max(0, os.path.getsize(log) - 4096))
        return b"# STATS" in fh.read()

here = os.path.dirname(os.path.abspath(__file__))
root = os.environ.get("ANORL_ROOT", os.path.abspath(os.path.join(here, "..", "..")))
ap = argparse.ArgumentParser()
ap.add_argument("--manifest", default=os.path.join(here, "jobs.tsv"))
ap.add_argument("--out", default=os.environ.get("ANORL_OUT", os.path.join(root, "results", "attacks")))
a = ap.parse_args()
rows = list(csv.DictReader(open(a.manifest), delimiter="\t"))
missing = [int(r["index"]) for r in rows
           if not (os.path.exists(os.path.join(a.out, r["name"] + ".result.json"))
                   and complete(os.path.join(a.out, r["name"] + ".log")))]
done = len(rows) - len(missing)
print(f"{done}/{len(rows)} finished, {len(missing)} missing", file=sys.stderr)
spans, i = [], 0
while i < len(missing):
    j = i
    while j + 1 < len(missing) and missing[j + 1] == missing[j] + 1:
        j += 1
    spans.append(str(missing[i]) if i == j else "%d-%d" % (missing[i], missing[j]))
    i = j + 1
print(",".join(spans))
