#!/usr/bin/env python3
"""Build the evaluation figures of the paper, as PDFs, from the result files.

  fig_layers.pdf   anonymity, delay and delivery against the number of mixes, four traces
                   (cluster controls of the attack grid: same build, three seeds)
  fig_load.pdf     anonymity and delay against the offered client rate, chain, three mixes
  fig_slot.pdf     legs lost against the time of the spend within its slot, four traces
  fig_drop.pdf     the dropper experiment          (via analysis/plot_attacks.py)
  fig_cmix.pdf     the corrupted-mix experiment    (via analysis/plot_attacks.py)

Every input is only read.
"""
import argparse, glob, json, os, subprocess, sys, shutil
from collections import defaultdict
import numpy as np
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

HERE = os.path.dirname(os.path.abspath(__file__))
SIM = os.path.dirname(HERE)
REPO = os.path.dirname(SIM)
sys.path.insert(0, HERE)
from entropy import parse_log                                     # noqa: E402

plt.rcParams.update({"font.size": 9, "axes.titlesize": 10, "axes.labelsize": 9,
                     "legend.fontsize": 8, "xtick.labelsize": 8, "ytick.labelsize": 8,
                     "pdf.fonttype": 42})
TRACES = ["march", "chain", "gather", "blockade1"]
LABEL = {"march": "march", "chain": "chain", "gather": "gather", "blockade1": "blockade"}
STYLE = {"march": ("#2ca02c", "^"), "chain": ("#1f77b4", "o"), "gather": ("#9467bd", "D"),
         "blockade1": ("#d62728", "s")}


def load_results(folders):
    rows = []
    for f in folders:
        rows += [json.load(open(p)) for p in glob.glob(os.path.join(f, "**", "*.result.json"), recursive=True)]
    return rows


def ms(rs, k):
    v = [r[k] for r in rs if isinstance(r.get(k), (int, float)) and not np.isnan(r[k])]
    return (np.mean(v), np.std(v)) if v else (np.nan, np.nan)


def fig_layers(rows, out):
    ctl = [r for r in rows if r["attack"] == "none"]
    g = defaultdict(list)
    for r in ctl:
        g[(r["trace"], int(r["layers"]))].append(r)
    Ls = [3, 4, 5, 6]
    fig, ax = plt.subplots(1, 3, figsize=(10.2, 2.9))
    for tr in TRACES:
        col, mk = STYLE[tr]
        for j, (k, lab) in enumerate((("entropy_mean", "anonymity entropy (bits)"),
                                       ("e2e_delay_mean", "end-to-end delay (s)"),
                                       ("delivery_e2e", "delivery rate"))):
            m = [ms(g[(tr, L)], k) for L in Ls]
            ax[j].errorbar(Ls, [x[0] for x in m], yerr=[x[1] for x in m], marker=mk, color=col,
                           capsize=3, lw=1.4, ms=4.5, label=LABEL[tr])
            ax[j].set_ylabel(lab)
    ax[2].set_ylim(0, 1.03)
    for a in ax:
        a.set_xticks(Ls); a.set_xlabel("path length $h$ (mixes)"); a.grid(alpha=0.3)
    ax[1].legend(loc="upper left")
    fig.tight_layout()
    fig.savefig(out, bbox_inches="tight"); plt.close(fig)


def fig_load(out):
    rows = json.load(open(os.path.join(SIM, "results", "sweep_load.json")))
    rows += [r for r in json.load(open(os.path.join(SIM, "results", "sweep_chain.json"))) if r["layers"] == 3]
    by = defaultdict(list)
    for r in rows:
        by[int(r["scenario"].split("_r")[1].split("_")[0])].append(r)
    rates = sorted(by)
    H = [ms(by[k], "entropy_mean") for k in rates]
    D = [ms(by[k], "e2e_delay_mean") for k in rates]
    fig, ax = plt.subplots(2, 1, figsize=(3.4, 4.0), sharex=True)
    ax[0].errorbar(rates, [h[0] for h in H], yerr=[h[1] for h in H], marker="o", color="#1f77b4", capsize=3, lw=1.4, ms=4.5)
    ax[0].set_ylabel("anonymity entropy (bits)")
    ax[1].errorbar(rates, [d[0] for d in D], yerr=[d[1] for d in D], marker="s", color="#1f77b4", capsize=3, lw=1.4, ms=4.5)
    ax[1].axhline(15.0, ls="--", color="#888", lw=1)
    ax[1].set_ylabel("end-to-end delay (s)")
    ax[1].set_xlabel("messages per participant per minute")
    for a in ax:
        a.set_xscale("log"); a.set_xticks(rates); a.set_xticklabels([str(k) for k in rates])
        a.xaxis.set_minor_locator(matplotlib.ticker.NullLocator()); a.grid(alpha=0.3)
        a.axvline(10, ls=":", color="#2ca02c", lw=1)
    fig.tight_layout()
    fig.savefig(out, bbox_inches="tight"); plt.close(fig)


def fig_slot(out):
    SLOT, BINS = 60.0, 6
    fig, ax = plt.subplots(figsize=(3.4, 2.6))
    for tr in ["chain", "march", "gather", "blockade1"]:
        f = os.path.join(SIM, "results", f"{tr}_L3_r10_s1.log")
        if not os.path.exists(f):
            print("missing", f); continue
        params, mixes, adv, orig, arr, dep, deliv, st, mal, comp = parse_log(f)
        L = int(params.get("layers", 3)); seen = set((m, h) for (t, m, n, h) in arr)
        tot = np.zeros(BINS); lost = np.zeros(BINS)
        for (t, m, n, h) in orig:
            if h >= L: continue
            b = min(int((t % SLOT) / SLOT * BINS), BINS - 1); tot[b] += 1
            if (m, h) not in seen: lost[b] += 1
        x = (np.arange(BINS) + 0.5) * SLOT / BINS
        col, mk = STYLE[tr]
        ax.plot(x, 100 * lost / np.maximum(tot, 1), marker=mk, color=col, lw=1.4, ms=4.5, label=LABEL[tr])
    ax.set_xlabel("time of the token spend within its 60 s slot (s)")
    ax.set_ylabel("legs lost before the mix (%)")
    ax.grid(alpha=0.3); ax.legend()
    fig.tight_layout()
    fig.savefig(out, bbox_inches="tight"); plt.close(fig)


def fig_attacks(outdir):
    tmp = os.path.join(outdir, "_attack_tmp")
    subprocess.run([sys.executable, os.path.join(HERE, "plot_attacks.py"),
                    "--results", os.path.join(REPO, "attacks"), os.path.join(REPO, "resultsgb"),
                    "--out", tmp], check=True, stdout=subprocess.DEVNULL)
    shutil.copy(os.path.join(tmp, "attack_drop.pdf"), os.path.join(outdir, "fig_drop.pdf"))
    shutil.copy(os.path.join(tmp, "attack_cmix.pdf"), os.path.join(outdir, "fig_cmix.pdf"))
    shutil.copy(os.path.join(tmp, "attack_summary.csv"), os.path.join(outdir, "attack_summary.csv"))
    shutil.rmtree(tmp)


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=os.path.join(REPO, "paper-latex", "figures"))
    a = ap.parse_args()
    os.makedirs(a.out, exist_ok=True)
    rows = load_results([os.path.join(REPO, "attacks"), os.path.join(REPO, "resultsgb")])
    fig_layers(rows, os.path.join(a.out, "fig_layers.pdf"))
    fig_load(os.path.join(a.out, "fig_load.pdf"))
    fig_slot(os.path.join(a.out, "fig_slot.pdf"))
    fig_attacks(a.out)
    for f in sorted(os.listdir(a.out)):
        print("wrote", os.path.join(a.out, f))
