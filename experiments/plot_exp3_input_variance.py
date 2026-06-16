#!/usr/bin/env python3
"""Experiment 3 (Input-variance, C5) figure.

For each victim (float, face-detect), plot input level (x) vs:
  - solo (G.T., no stress)            — the true input-dependent makespan
  - e2e with stress (noisy wall)      — inflated by CPU contention
  - noise-free with stress (PureTime) — should track solo across all inputs

The point: PureTime's noise-free line follows the solo line at every input level,
while the noisy wall is inflated — i.e. PureTime recovers the input-dependent pure
time regardless of input, under noise.

Input CSV (results.csv): victim,input_level,condition,iteration,t_e2e_ms,t_puretime_ms,t_noise_cpu
Usage: python3 plot_exp3_input_variance.py --data <results.csv> --out <dir> [--format pdf]
"""
import argparse
import os
import numpy as np
import pandas as pd
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

VICTIM_LABEL = {"float": "float (sqrt/sin/cos, iters)", "face": "face-detect+sentiment (#faces)"}
COLORS = {"solo": "#2e7d32", "e2e": "#c62828", "pt": "#1565c0"}


def ci95(s):
    s = np.asarray(s, dtype=float)
    return 1.96 * s.std(ddof=1) / np.sqrt(len(s)) if len(s) > 1 else 0.0


def agg(df, victim, condition, value_col):
    """Per-input median + 95% CI for one victim/condition."""
    sub = df[(df["victim"] == victim) & (df["condition"] == condition)]
    xs, med, ci = [], [], []
    for lv in sorted(sub["input_level"].unique()):
        v = sub[sub["input_level"] == lv][value_col].values
        if len(v) == 0:
            continue
        xs.append(lv)
        med.append(float(np.median(v)))
        ci.append(ci95(v))
    return np.array(xs), np.array(med), np.array(ci)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", required=True)
    ap.add_argument("--out", default="experiments/figures")
    ap.add_argument("--format", default="pdf")
    args = ap.parse_args()

    df = pd.read_csv(args.data)
    df["victim"] = df["victim"].astype(str).str.strip('"')
    df["condition"] = df["condition"].astype(str).str.strip('"')
    # face N=0 = no faces = ~0 input compute → makespan reflects container/opencv-startup
    # overhead, not the input (it measures higher than N=1). Degenerate corner; exclude.
    n0 = (df["victim"] == "face") & (df["input_level"] == 0)
    if n0.any():
        print(f"Excluding {int(n0.sum())} face N=0 rows (degenerate: no compute → startup-overhead artifact)")
        df = df[~n0]
    victims = [v for v in ["float", "face"] if v in df["victim"].unique()]
    if not victims:
        print("No known victims in data."); return

    fig, axes = plt.subplots(1, len(victims), figsize=(3.4 * len(victims), 2.8), squeeze=False)
    for ax, victim in zip(axes[0], victims):
        # solo (G.T.): use t_e2e at condition=solo (≈ t_puretime, no noise)
        xs, solo, solo_ci = agg(df, victim, "solo", "t_e2e_ms")
        # stress: e2e (noisy wall) and noise-free (PureTime)
        xe, e2e, e2e_ci = agg(df, victim, "stress", "t_e2e_ms")
        xp, pt, pt_ci = agg(df, victim, "stress", "t_puretime_ms")

        ax.plot(xe, e2e, "-s", color=COLORS["e2e"], ms=4, lw=1.3, label="E2E w/ stress (noisy)")
        ax.fill_between(xe, e2e - e2e_ci, e2e + e2e_ci, color=COLORS["e2e"], alpha=0.15)
        ax.plot(xs, solo, "-o", color=COLORS["solo"], ms=4, lw=1.3, label="Solo (G.T.)")
        ax.fill_between(xs, solo - solo_ci, solo + solo_ci, color=COLORS["solo"], alpha=0.15)
        ax.plot(xp, pt, "--^", color=COLORS["pt"], ms=4, lw=1.3, label="PureTime (noise-free)")
        ax.fill_between(xp, pt - pt_ci, pt + pt_ci, color=COLORS["pt"], alpha=0.15)

        # report per-input recovery error (noise-free vs solo)
        solo_map = dict(zip(xs, solo))
        errs = [abs(p - solo_map[x]) / solo_map[x] * 100 for x, p in zip(xp, pt) if x in solo_map and solo_map[x] > 0]
        med_err = np.median(errs) if errs else float("nan")

        ax.set_title(f"{VICTIM_LABEL.get(victim, victim)}\nPureTime↔Solo median err {med_err:.1f}%", fontsize=8)
        ax.set_xlabel("Input level")
        ax.set_ylabel("Execution Time (ms)")
        ax.legend(fontsize=6.5, framealpha=0.9)
        ax.set_ylim(bottom=0)
        if victim == "float":
            ax.set_xscale("log")
        print(f"[{victim}] PureTime↔Solo recovery error: median {med_err:.1f}% over inputs {list(xs)}")

    fig.tight_layout()
    os.makedirs(args.out, exist_ok=True)
    path = os.path.join(args.out, f"fig5_input_variance.{args.format}")
    fig.savefig(path, dpi=200, bbox_inches="tight")
    print(f"Saved: {path}")


if __name__ == "__main__":
    main()
