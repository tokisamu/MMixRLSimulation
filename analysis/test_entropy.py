#!/usr/bin/env python3
"""Hand-checkable cases for the Algorithm 1 implementation in entropy.py.

Each case writes a synthetic event log in the simulator's format and checks the entropy
against a value derived by hand from Ben Guirat and Diaz, Algorithm 1.
"""
import os, sys, tempfile, math
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from entropy import compute

HDR = ("# anorl-mix event log\n"
       "# PARAM layers {L} mixdelay 5 transport route pktsize 1024 range 10 stop 100"
       " budget_client 10 budget_mix 2500 n 10 n_mix 2\n"
       "# MIXES 0 1\n")


def run(events, L=1, targets=10, burn=0.0, drain=0.0):
    with tempfile.NamedTemporaryFile("w", suffix=".log", delete=False) as fh:
        fh.write(HDR.format(L=L))
        fh.write(events)
        fh.write("# STATS originations 0 tx 0 rx 0\n")
        p = fh.name
    r = compute(p, n_targets=targets, burn=burn, drain=drain)
    os.unlink(p)
    return r


def approx(a, b, tol=1e-9):
    return abs(a - b) <= tol


fails = []

# Case 1: one mix, two messages both inside when the first leaves.
# Pool at A's departure is {A,B} so A takes 1/2 and B inherits the other 1/2.
# The distribution over outputs is (1/2, 1/2) and H = 1 bit exactly.
ev = ("ORIG 0 10.0 5 0 0\nORIG 1 10.0 6 0 0\n"
      "ARR 0 11.0 0 0\nARR 1 12.0 0 0\n"
      "DEP 0 20.0 0 0\nDELIV 0 20.0 0 10.0\n"
      "DEP 1 21.0 0 0\nDELIV 1 21.0 0 11.0\n")
r = run(ev)
ok = approx(r["entropy_mean"], 1.0, 1e-9) and r["n_outputs"] == 2
print(f"case 1  two-message pool          H={r['entropy_mean']:.6f} expect 1.000000  {'ok' if ok else 'FAIL'}")
if not ok: fails.append(1)

# Case 2: one mix, the target passes through alone -- no mixing, no anonymity.
ev = ("ORIG 0 10.0 5 0 0\nARR 0 11.0 0 0\nDEP 0 20.0 0 0\nDELIV 0 20.0 0 10.0\n"
      "ORIG 1 40.0 6 0 0\nARR 1 41.0 0 0\nDEP 1 50.0 0 0\nDELIV 1 50.0 0 10.0\n")
r = run(ev)
ok = approx(r["entropy_mean"], 0.0, 1e-9)
print(f"case 2  no overlap               H={r['entropy_mean']:.6f} expect 0.000000  {'ok' if ok else 'FAIL'}")
if not ok: fails.append(2)

# Case 3: one mix, four messages all inside together.  Each departure takes an even share
# of what is left: 1/4, then (3/4)/3 = 1/4, then (1/2)/2 = 1/4, then 1/4.  H = 2 bits.
ev = "".join(f"ORIG {i} 10.0 {5+i} 0 0\n" for i in range(4))
ev += "".join(f"ARR {i} {11.0+i} 0 0\n" for i in range(4))
ev += "".join(f"DEP {i} {20.0+i} 0 0\nDELIV {i} {20.0+i} 0 10.0\n" for i in range(4))
r = run(ev)
ok = approx(r["entropy_mean"], 2.0, 1e-9)
print(f"case 3  four-message pool        H={r['entropy_mean']:.6f} expect 2.000000  {'ok' if ok else 'FAIL'}")
if not ok: fails.append(3)

# Case 4: two mixes in series, two messages together at each.  The first mix splits the
# target evenly over the two, then the second mix splits again over the same two, so the
# result is still (1/2, 1/2) and H = 1 bit.  This checks that mass is carried across hops.
ev = ("ORIG 0 10.0 5 0 0\nORIG 1 10.0 6 0 0\n"
      "ARR 0 11.0 0 0\nARR 1 11.5 0 0\n"
      "DEP 0 20.0 0 0\nDEP 1 20.5 0 0\n"
      "ARR 0 21.0 1 1\nARR 1 21.5 1 1\n"
      "DEP 0 30.0 1 1\nDELIV 0 30.0 1 20.0\n"
      "DEP 1 30.5 1 1\nDELIV 1 30.5 1 20.5\n")
r = run(ev, L=2)
ok = approx(r["entropy_mean"], 1.0, 1e-9)
print(f"case 4  two hops, same pair      H={r['entropy_mean']:.6f} expect 1.000000  {'ok' if ok else 'FAIL'}")
if not ok: fails.append(4)

# Case 5: probability mass conservation when nothing is lost.
ok = approx(r["surviving_mass_mean"], 1.0, 1e-9)
print(f"case 5  mass conserved           m={r['surviving_mass_mean']:.6f} expect 1.000000  {'ok' if ok else 'FAIL'}")
if not ok: fails.append(5)

# Case 6: a lost message leaks mass.  Three messages enter, one never leaves the mix, so
# only 2/3 of the target's mass reaches an output; the conditional entropy over the two
# delivered outputs is 1 bit while the raw entropy is lower.
ev = ("ORIG 0 10.0 5 0 0\nORIG 1 10.0 6 0 0\nORIG 2 10.0 7 0 0\n"
      "ARR 0 11.0 0 0\nARR 1 11.5 0 0\nARR 2 12.0 0 0\n"
      "DEP 0 20.0 0 0\nDELIV 0 20.0 0 10.0\n"
      "DEP 1 21.0 0 0\nDELIV 1 21.0 0 11.0\n")
r = run(ev)
ok = approx(r["surviving_mass_mean"], 2.0 / 3.0, 1e-9) and approx(r["entropy_mean"], 1.0, 1e-9)
print(f"case 6  one message stuck        m={r['surviving_mass_mean']:.6f} expect 0.666667, "
      f"H={r['entropy_mean']:.6f} expect 1.000000  {'ok' if ok else 'FAIL'}")
if not ok: fails.append(6)

print()
print("all cases passed" if not fails else f"FAILED cases: {fails}")
sys.exit(1 if fails else 0)
