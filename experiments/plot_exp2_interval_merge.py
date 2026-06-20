#!/usr/bin/env python3
"""Experiment 2 (Mixed-noise + interval-merge ablation, C3).

A concurrent victim (CPU grayscale thread + sustained MinIO-upload thread, pinned to two
different cores so the threads run truly in parallel) is squeezed by co-tenant CPU and
network contention at the same time. At the cgroup level its CPU wait and its Net wait
then OVERLAP in wall-clock time. PureTime stores every wait as an interval set and
subtracts their UNION (interval-merge); the ablation `noise_free_naive` instead subtracts
the per-resource wait SUM. Where the waits overlap, the sum double-counts that overlap, so
naive over-subtracts:

  noise_free_merged = makespan − |cpu ∪ net|        (correct)
  noise_free_naive  = makespan − (|cpu| + |net|)     (double-counts cpu ∩ net)

As the overlap grows, `noise_free_naive` first falls below the true solo time (already
unphysical — a function can't beat its own solo run) and then even below zero (a *negative*
execution time, outright impossible) — while the interval-merge estimate stays ≈ solo
(efficiency ≈ 1). That gap is the whole point of C3.

Panel A — efficiency (noise_free / solo) vs the measured overlap ratio: merged stays on
          the solo=1 line; naive dives into the shaded "impossible (<0)" region.
Panel B — per CPU-stress-intensity level, solo (=1) vs merged vs naive bars.

Usage: python3 plot_exp2_interval_merge.py --data experiments/data/mixed_noise/results.csv \
            --out experiments/figures [--format pdf]
"""
import argparse
import os
import numpy as np
import pandas as pd
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt


def load(path):
    df = pd.read_csv(path)
    for c in ("stress", "condition"):
        df[c] = df[c].astype(str).str.strip('"')
    return df


def per_level(df):
    """For each sweep level (CSV 'frames' = CPU-stress intensity) return solo median and,
    for every stress run, merged/solo, naive/solo and the overlap ratio."""
    out = []
    for lv in sorted(df["frames"].unique()):
        sub = df[df["frames"] == lv]
        solo = sub[sub.condition == "solo"]["original_ms"].values
        st = sub[sub.condition == "stress"]
        if not len(solo) or not len(st):
            continue
        solo_med = float(np.median(solo))
        o = st["original_ms"].values
        m = st["noise_free_ms"].values
        n = st["noise_free_naive_ms"].values
        # double-counted overlap (ms) = naive-subtraction − merged-subtraction = merged − naive
        overlap_ratio = (m - n) / o
        out.append(dict(
            level=int(lv), solo=solo_med, n_runs=len(st),
            merged_eff=m / solo_med, naive_eff=n / solo_med,
            overlap=overlap_ratio,
            infl=float(np.median(o)) / solo_med,
        ))
    return out


def med_iqr(a):
    a = np.asarray(a, float)
    return np.median(a), np.percentile(a, 25), np.percentile(a, 75)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", required=True)
    ap.add_argument("--out", default="experiments/figures")
    ap.add_argument("--format", default="pdf")
    args = ap.parse_args()

    df = load(args.data)
    levels = per_level(df)
    if not levels:
        raise SystemExit("no usable rows")
    levels.sort(key=lambda L: np.median(L["overlap"]))  # x축(겹침) 단조 정렬

    os.makedirs(args.out, exist_ok=True)
    ov = np.concatenate([L["overlap"] for L in levels])
    me = np.concatenate([L["merged_eff"] for L in levels])
    na = np.concatenate([L["naive_eff"] for L in levels])
    order = np.argsort(ov)
    ov, me, na = ov[order], me[order], na[order]
    ymin = min(-0.1, float(na.min()) - 0.1)
    lv_ov = [np.median(L["overlap"]) * 100 for L in levels]
    lv_me = [np.median(L["merged_eff"]) for L in levels]
    lv_na = [np.median(L["naive_eff"]) for L in levels]
    k = np.argsort(lv_ov)

    # ---- fig7a: efficiency vs overlap ratio (scatter + trend) ----
    figA, axA = plt.subplots(figsize=(4.4, 3.0))
    axA.axhspan(ymin, 0.0, color="#ffcdd2", alpha=0.5, zorder=0)
    axA.text((float(ov.min()) + float(ov.max())) / 2 * 100, ymin * 0.5,
             "impossible: nf < 0\n(negative execution time)", fontsize=7.5, color="#b71c1c",
             ha="center", va="center", style="italic")
    axA.axhline(1.0, color="#37474f", lw=1.0, ls="--", label="solo (ideal = 1.0)")
    axA.scatter(ov * 100, na, s=16, color="#c62828", marker="s", label="naive (Σ waits)", zorder=3)
    axA.scatter(ov * 100, me, s=16, color="#1565c0", marker="^", label="interval-merge (∪ waits)", zorder=3)
    axA.plot(np.array(lv_ov)[k], np.array(lv_me)[k], color="#1565c0", lw=1.2, alpha=0.7)
    axA.plot(np.array(lv_ov)[k], np.array(lv_na)[k], color="#c62828", lw=1.2, alpha=0.7)
    axA.set_xlabel("Measured wait overlap (% of makespan)", fontsize=10)
    axA.set_ylabel("Efficiency  noise_free / solo", fontsize=10)
    axA.tick_params(labelsize=9)
    axA.set_ylim(ymin, 2.6)   # 위 여백 확보 → legend(upper right)가 데이터 위에 떠 안 가림
    axA.legend(fontsize=9.5, framealpha=0.95, loc="upper right")
    figA.tight_layout()
    pa = os.path.join(args.out, f"interval_merge_scatter.{args.format}")
    figA.savefig(pa, dpi=200, bbox_inches="tight"); print(f"Saved: {pa}")

    # ---- fig7b: per overlap level bars (solo / merged / naive) ----
    figB, axB = plt.subplots(figsize=(4.4, 3.0))
    x = np.arange(len(levels)); w = 0.27
    me_b = [med_iqr(L["merged_eff"]) for L in levels]
    na_b = [med_iqr(L["naive_eff"]) for L in levels]
    axB.bar(x - w, [1.0] * len(levels), w, color="#37474f", label="solo (=1)")
    axB.bar(x, [b[0] for b in me_b], w, color="#1565c0", label="interval-merge",
            yerr=[[b[0] - b[1] for b in me_b], [b[2] - b[0] for b in me_b]], capsize=2, error_kw=dict(lw=0.7))
    axB.bar(x + w, [b[0] for b in na_b], w, color="#c62828", label="naive",
            yerr=[[max(0, b[0] - b[1]) for b in na_b], [b[2] - b[0] for b in na_b]], capsize=2, error_kw=dict(lw=0.7))
    axB.axhline(0.0, color="k", lw=0.8); axB.axhline(1.0, color="#37474f", lw=0.8, ls="--")
    axB.set_xticks(x); axB.set_xticklabels([f"{int(np.median(L['overlap'])*100)}%" for L in levels], fontsize=9)
    axB.set_xlabel("Wait overlap (CPU-stress intensity ↑)", fontsize=10)
    axB.set_ylabel("Efficiency  noise_free / solo", fontsize=10)
    axB.tick_params(axis="y", labelsize=9)
    axB.set_ylim(top=2.15)   # legend 공간(위, 2줄)
    # 2줄(ncol=2) col-major 채움 순서 보정: 윗줄=solo·interval-merge, 아랫줄=naive
    h, l = axB.get_legend_handles_labels()
    o = [0, 2, 1]
    axB.legend([h[i] for i in o], [l[i] for i in o], fontsize=9.5,
               framealpha=0.95, loc="upper right", ncol=2)
    figB.tight_layout()
    pb = os.path.join(args.out, f"interval_merge_bars.{args.format}")
    figB.savefig(pb, dpi=200, bbox_inches="tight"); print(f"Saved: {pb}")
    print(f"{'overlap%':>8} {'infl×':>6} {'merged/solo':>12} {'naive/solo':>11} {'n':>3}")
    for L in levels:
        print(f"{np.median(L['overlap'])*100:8.0f} {L['infl']:6.1f} "
              f"{np.median(L['merged_eff']):12.2f} {np.median(L['naive_eff']):11.2f} {L['n_runs']:3d}")


if __name__ == "__main__":
    main()
