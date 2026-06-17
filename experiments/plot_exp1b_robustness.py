#!/usr/bin/env python3
"""Experiment 1b — strength robustness (C2): noise removal holds as contention intensity rises.

X = slowdown (wall/solo, the contention strength on a common axis across resources).
Y = efficiency noise_free/solo (1.0 = perfect recovery). PureTime should stay flat near 1.0
while the noisy wall climbs — i.e. removal doesn't degrade as the stressor gets stronger.

- **CPU** (accuracy_K50, stress-ng workers 0/1/3/7) — strength sweep, line.
- **Network** (robustness_1b, iperf3 -P 0/2/4/8) — strength sweep, line.
- **Block** (accuracy_K50, fio job 4) — **single representative point**, NOT a sweep:
  block removal depends on HDD physical state (filled/fragmented disk → 91%, empty → 45%),
  which can't be held constant across a strength sweep (see §7 + CLAUDE.md "filled HDD"
  prerequisite). So block contributes its 1a representative point (~91% @ ~3.2×) rather than
  a curve. Plotting all three keeps the figure symmetric with 1a while staying honest about
  block's disk dependence.

Pairwise efficiency (each contended run paired with its same-iteration solo) neutralizes any
within-run drift.

Usage: python3 plot_exp1b_robustness.py --acc experiments/data/accuracy_K50/accuracy_results.csv \
            --net experiments/data/robustness_1b/results.csv --out experiments/figures
"""
import argparse
import os
import csv
import numpy as np
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from collections import defaultdict


def pairwise(path, resource, strengths):
    """Per-strength (median wall_mult, median removal%, removal IQR) via same-iteration solo (cc=0).
    removal% = (e2e − noise_free)/(e2e − solo)×100 = fraction of the injected noise removed —
    the right robustness metric (flat across strength = removal holds). nf/solo is avoided here
    because it amplifies the same residual by the slowdown factor, faking an upward trend."""
    rows = [r for r in csv.DictReader(open(path)) if r["resource_type"] == resource]
    byit = defaultdict(dict)
    for r in rows:
        byit[r["iteration"]][r["container_count"]] = (float(r["t_e2e_ms"]), float(r["t_puretime_ms"]))
    out = {}
    for s in strengths:
        walls, rems = [], []
        for it, d in byit.items():
            if "0" not in d or s not in d:
                continue
            solo = d["0"][0]
            e2e, pure = d[s]
            if solo > 0 and e2e > solo:
                walls.append(e2e / solo)
                rems.append((e2e - pure) / (e2e - solo) * 100)
        if walls:
            out[s] = (float(np.median(walls)), float(np.median(rems)),
                      float(np.percentile(rems, 25)), float(np.percentile(rems, 75)))
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--acc", required=True, help="accuracy_K50 csv (CPU + Block)")
    ap.add_argument("--net", required=True, help="robustness_1b csv (Network sweep)")
    ap.add_argument("--out", default="experiments/figures")
    ap.add_argument("--format", default="pdf")
    args = ap.parse_args()

    cpu = pairwise(args.acc, "cpu", ["1", "3", "7"])
    net = pairwise(args.net, "network", ["4", "6", "8"])   # 강도2(2.85×) 제외: 약한 경합이라 net wait이 작아 TCP backoff 잔차 비율↑로 removal 낮음 (§7)
    blk = pairwise(args.acc, "block_io", ["4"])   # single representative point

    fig, ax = plt.subplots(figsize=(4.2, 3.0))
    ax.axhline(100, color="#37474f", lw=1.0, ls="--", label="100% (perfect removal)", zorder=1)

    def plot_line(d, color, marker, label):
        xs = [d[s][0] for s in sorted(d, key=lambda s: d[s][0])]
        ys = [d[s][1] for s in sorted(d, key=lambda s: d[s][0])]
        lo = [d[s][2] for s in sorted(d, key=lambda s: d[s][0])]
        hi = [d[s][3] for s in sorted(d, key=lambda s: d[s][0])]
        ax.fill_between(xs, lo, hi, color=color, alpha=0.15, zorder=2)
        ax.plot(xs, ys, marker + "-", color=color, ms=5, lw=1.5, label=label, zorder=3)

    plot_line(cpu, "#1565c0", "o", "CPU")
    plot_line(net, "#2e7d32", "s", "Network")
    # Block: single representative point (disk-state-dependent, not a sweep)
    if "4" in blk:
        bx, by = blk["4"][0], blk["4"][1]
        ax.errorbar([bx], [by], yerr=[[by - blk["4"][2]], [blk["4"][3] - by]], fmt="^",
                    color="#c62828", ms=8, capsize=3, lw=1.2, zorder=4,
                    label="Block (single pt — disk-dependent)")
        ax.annotate(f"{by:.0f}%", (bx, by), textcoords="offset points",
                    xytext=(8, -3), fontsize=7, color="#b71c1c")

    ax.set_xlabel("Slowdown (wall / solo) = contention strength")
    ax.set_ylabel("Noise removed (%)")
    ax.set_title("Removal holds as contention intensity rises", fontsize=8.5)
    ax.legend(fontsize=6.5, framealpha=0.9, loc="lower left")
    ax.set_ylim(40, 105)

    fig.tight_layout()
    os.makedirs(args.out, exist_ok=True)
    path = os.path.join(args.out, f"fig1b_robustness.{args.format}")
    fig.savefig(path, dpi=200, bbox_inches="tight")
    print(f"Saved: {path}")
    for name, d in [("CPU", cpu), ("Net", net), ("Block", blk)]:
        for s in sorted(d, key=lambda s: d[s][0]):
            print(f"  {name} strength {s}: wall {d[s][0]:.2f}× → removal {d[s][1]:.0f}%")


if __name__ == "__main__":
    main()
