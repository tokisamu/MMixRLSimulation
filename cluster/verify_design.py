#!/usr/bin/env python3
"""Check, with this machine's numpy, that the attack scenarios keep the properties the
analysis relies on.  Run once on the cluster before submitting.

  1. frac = 0 is one control shared by both attacks;
  2. every honest participant sends exactly the control's messages at every ratio;
  3. adversary sets are nested across ratios;
  4. no dropper is a mix;  5. every corrupted node is a mix;
  6. each flood sequence has L distinct honest mixes and never targets a corrupted one.
"""
import hashlib, json, os, sys, tempfile
here = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(os.path.dirname(here), "scenarios"))
import numpy as np                                                   # noqa: E402
import gen_scenario as g                                             # noqa: E402

if tuple(int(x) for x in np.__version__.split(".")[:2]) < (1, 17):
    sys.exit("numpy %s is too old: numpy.random.default_rng needs 1.17 or newer" % np.__version__)
tmp = tempfile.mkdtemp(prefix="anorl_verify_")
L, seed = 6, 1
def make(attack, frac):
    name = "v_%s_%s" % (attack, frac)
    g.build_attack("march", 0.10, L, 10.0, 300, 60, seed, 10, 250, tmp, name, attack, frac)
    return os.path.join(tmp, name)
paths = {(a, f): make(a, f) for a in ("drop", "cmix") for f in (0.0, 0.1, 0.4)}
sha = lambda p: hashlib.sha256(open(p + ".scn", "rb").read()).hexdigest()
ok = True
def check(label, cond):
    global ok
    print(("PASS  " if cond else "FAIL  ") + label)
    ok = ok and bool(cond)
check("1 shared control", sha(paths[("drop", 0.0)]) == sha(paths[("cmix", 0.0)]))
def honest(p):
    d = json.load(open(p + ".json")); adv = set(d["droppers"]) | set(d["cmixes"]); out = {}
    for m in d["workload"]:
        if m["src"] not in adv:
            out.setdefault(m["src"], []).append((m["t"], tuple(m["path"])))
    return out, adv, d
ctl, _, _ = honest(paths[("drop", 0.0)])
for key in [("drop", 0.1), ("drop", 0.4), ("cmix", 0.1), ("cmix", 0.4)]:
    h, adv, _ = honest(paths[key])
    check("2 paired workload %s %s" % key,
          all(h[s] == ctl.get(s) for s in h) and all(s in h for s in ctl if s not in adv))
J = lambda k: json.load(open(paths[k] + ".json"))
d1, d4 = set(J(("drop", 0.1))["droppers"]), set(J(("drop", 0.4))["droppers"])
c1, c4 = set(J(("cmix", 0.1))["cmixes"]), set(J(("cmix", 0.4))["cmixes"])
mixes = set(J(("drop", 0.0))["mixes"])
check("3 nested adversary sets", d1 <= d4 and c1 <= c4)
check("4 no dropper is a mix", not (d4 & mixes))
check("5 every corrupted node is a mix", c4 <= mixes)
tg = J(("cmix", 0.4))["cmix_targets"]
check("6 flood sequences valid", all(len(set(v)) == L for v in tg.values())
      and not (set(x for v in tg.values() for x in v) & c4))
for f in os.listdir(tmp):
    os.remove(os.path.join(tmp, f))
os.rmdir(tmp)
print("\nnumpy %s, python %s: %s" % (np.__version__, sys.version.split()[0],
      "ALL CHECKS PASS" if ok else "A CHECK FAILED, do not submit"))
sys.exit(0 if ok else 1)
