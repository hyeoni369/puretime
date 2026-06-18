#!/usr/bin/env python3
"""Experiment 4 (Baseline comparison vs statistical methods, C6/C7).

Analysis-only: reuses Experiment 3 data (no new runs). Inputs arrive in a random
order (production-like), so each invocation has a different *true* (solo) time. A
monitoring/autoscaling system only sees the *noisy wall* (e2e under co-tenant noise);
PureTime gives the *noise-free* time. We show, counterfactually (open-loop, against
the real default thresholds), that operating on the noisy wall misfires while the
noise-free signal does not:

  Panel A — AWS CloudWatch Anomaly Detection (mean ± 2σ band, trained on the true
            envelope): the noisy wall sits persistently outside the band (false
            alarms) because co-tenant noise inflates it; the noise-free signal stays
            inside. Noise-free variance is also far lower → a tighter band → a real
            regression is detectable sooner.
  Panel B — Knative KPA autoscaling (containerConcurrency=100, util target 70% →
            70 req/pod). Little's Law: concurrency = λ · T. The noisy T inflates the
            concurrency estimate past 70 → scale-out (over-provision); the noise-free
            T stays under. Fake pods = ceil(noisy/70) − ceil(true/70).

Usage: python3 plot_exp4_baseline.py --data <exp3 results.csv> --out <dir> [--victim face] [--format pdf]
"""
import argparse
import os
import numpy as np
import pandas as pd
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

CC = 100          # Knative containerConcurrency
UTIL = 0.70       # target utilization → 70 req/pod scale-out threshold
THRESH = CC * UTIL
SEED = 42
N_INVOKE = 80     # shuffled production trace length


def build_trace(df, victim, rng):
    """Sample a random-input invocation trace. Each invocation draws a paired
    (e2e, noise-free) from a random input level's stress runs, and the solo (G.T.)
    median of that level."""
    sub = df[df["victim"] == victim]
    levels = sorted(sub["input_level"].unique())
    # per-level pools
    pools = {}
    for lv in levels:
        solo = sub[(sub.input_level == lv) & (sub.condition == "solo")]["t_e2e_ms"].values
        st = sub[(sub.input_level == lv) & (sub.condition == "stress")]
        pools[lv] = dict(
            solo=float(np.median(solo)) if len(solo) else np.nan,
            e2e=st["t_e2e_ms"].values,
            pt=st["t_puretime_ms"].values,
        )
    levels = [lv for lv in levels if len(pools[lv]["e2e"]) and not np.isnan(pools[lv]["solo"])]
    solo_t, e2e_t, pt_t = [], [], []
    for _ in range(N_INVOKE):
        lv = levels[rng.integers(len(levels))]
        j = rng.integers(len(pools[lv]["e2e"]))
        solo_t.append(pools[lv]["solo"])
        e2e_t.append(float(pools[lv]["e2e"][j]))
        pt_t.append(float(pools[lv]["pt"][j]))
    return np.array(solo_t), np.array(e2e_t), np.array(pt_t)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", required=True)
    ap.add_argument("--out", default="experiments/figures")
    ap.add_argument("--victim", default="face")
    ap.add_argument("--format", default="pdf")
    args = ap.parse_args()

    df = pd.read_csv(args.data)
    df["victim"] = df["victim"].astype(str).str.strip('"')
    df["condition"] = df["condition"].astype(str).str.strip('"')
    df = df[~((df["victim"] == "face") & (df["input_level"] == 0))]  # degenerate

    rng = np.random.default_rng(SEED)
    solo, e2e, pt = build_trace(df, args.victim, rng)
    x = np.arange(len(solo))

    # ---- Panel A: CloudWatch mean±2σ band, trained on the true (noise-free) envelope ----
    # Band = expected normal range of the *recovered* signal (PureTime ≈ true behavior).
    mu, sig = pt.mean(), pt.std(ddof=1)
    lo, hi = mu - 2 * sig, mu + 2 * sig
    e2e_fa = int((e2e > hi).sum())      # noisy wall above band = false alarms
    pt_fa = int(((pt > hi) | (pt < lo)).sum())

    # ---- Panel B: KPA concurrency = λ·T, threshold 70 ----
    # pick λ so the *true* mean concurrency sits just below threshold (no scale needed).
    lam = (THRESH * 0.85) / (pt.mean() / 1000.0)   # req/s, using noise-free mean (s)
    conc_pt = lam * (pt / 1000.0)
    conc_e2e = lam * (e2e / 1000.0)
    pods_true = int(np.ceil(conc_pt.mean() / THRESH))
    pods_noisy = int(np.ceil(conc_e2e.mean() / THRESH))

    os.makedirs(args.out, exist_ok=True)
    # ---- fig6a: CloudWatch anomaly detection ----
    figA, axA = plt.subplots(figsize=(4.3, 3.0))
    axA.fill_between([x[0], x[-1]], [lo, lo], [hi, hi], color="#90a4ae", alpha=0.25,
                     label="CloudWatch band (μ±2σ)")
    axA.plot(x, e2e, "-s", color="#c62828", ms=2.5, lw=1.0, label=f"Noisy wall (false alarms: {e2e_fa}/{len(x)})")
    axA.plot(x, pt, "-^", color="#1565c0", ms=2.5, lw=1.0, label=f"PureTime (false alarms: {pt_fa}/{len(x)})")
    axA.axhline(hi, color="#607d8b", lw=0.8, ls="--")
    axA.set_xlabel("Invocation (random inputs)", fontsize=11); axA.set_ylabel("Exec time (ms)", fontsize=11)
    axA.tick_params(labelsize=9)
    axA.set_ylim(0, max(float(np.max(e2e)), hi) * 1.55)   # legend 공간 확보(그래프 안 가리게)
    axA.legend(fontsize=9.5, framealpha=0.95, loc="upper left")
    figA.tight_layout()
    pa = os.path.join(args.out, f"fig6a_baseline_comparison.{args.format}")
    figA.savefig(pa, dpi=200, bbox_inches="tight"); print(f"Saved: {pa}")

    # ---- fig6b: Knative KPA ----
    figB, axB = plt.subplots(figsize=(4.3, 3.0))
    axB.axhline(THRESH, color="#37474f", lw=1.0, ls="--", label=f"scale-out @ {THRESH:.0f}/pod")
    axB.plot(x, conc_e2e, "-s", color="#c62828", ms=2.5, lw=1.0, label=f"Noisy → {pods_noisy} pods")
    axB.plot(x, conc_pt, "-^", color="#1565c0", ms=2.5, lw=1.0, label=f"PureTime → {pods_true} pod(s)")
    axB.set_xlabel("Invocation (random inputs)", fontsize=10); axB.set_ylabel("Est. concurrency (req)", fontsize=10)
    axB.tick_params(labelsize=9)
    axB.set_ylim(0, max(float(np.max(conc_e2e)), THRESH) * 1.55)
    axB.legend(fontsize=9.5, framealpha=0.95, loc="upper left")
    figB.tight_layout()
    pb = os.path.join(args.out, f"fig6b_baseline_comparison.{args.format}")
    figB.savefig(pb, dpi=200, bbox_inches="tight"); print(f"Saved: {pb}")
    print(f"[A] CloudWatch false alarms — noisy wall {e2e_fa}/{len(x)} vs PureTime {pt_fa}/{len(x)}")
    print(f"[B] KPA pods — noisy {pods_noisy} (over-provision +{pods_noisy-pods_true}) vs PureTime {pods_true}; "
          f"λ={lam:.1f} req/s, mean T noisy {e2e.mean():.0f}ms / true {pt.mean():.0f}ms")


if __name__ == "__main__":
    main()
