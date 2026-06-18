#!/usr/bin/env python3
"""
PureTime Evaluation Figure Generator (v3)
==========================================
Generates publication-quality figures for PureTime paper evaluation section.

Figures:
  Fig 1: Noise Removal Accuracy — Baseline Comparison (bar chart)
  Fig 2: Noise Source Identification — Per-resource ratio time series
  Fig 3: System Overhead — Execution Time (box plot)
  Fig 4: System Overhead — Resource Consumption (PureTime process metrics)

Expected CSV files:
  1. accuracy_results.csv   - cgroup_id,resource_type,container_count,iteration,
                              t_e2e_ms,t_puretime_ms,t_noise_cpu,t_noise_net,t_noise_bio
  2. overhead_time.csv      - cgroup_id,resource_type,container_count,iteration,
                              t_e2e_ms,with_puretime
  3. overhead_resource.csv  - timestamp,resource_type,container_count,iteration,
                              cpu_percent,memory_mb,cpu_ratio_system,mem_ratio_system

Usage:
  python plot_evaluation_v3.py [--data-dir ./data] [--output-dir ./figures] [--format pdf]
"""

import argparse
import os
import sys
import warnings
from pathlib import Path

import matplotlib as mpl
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from matplotlib.patches import Patch

warnings.filterwarnings("ignore", category=FutureWarning)

# ============================================================================
# Global Style Configuration (IEEE / ACM publication style)
# ============================================================================
STYLE_CONFIG = {
    "font.family": "serif",
    "font.serif": ["Times New Roman", "DejaVu Serif", "serif"],
    "font.size": 9,
    "axes.titlesize": 10,
    "axes.labelsize": 9,
    "xtick.labelsize": 8,
    "ytick.labelsize": 8,
    "legend.fontsize": 8,
    "figure.titlesize": 11,
    "axes.linewidth": 0.8,
    "grid.linewidth": 0.4,
    "lines.linewidth": 1.2,
    "lines.markersize": 5,
    "xtick.major.width": 0.8,
    "ytick.major.width": 0.8,
    "savefig.dpi": 300,
    "savefig.bbox": "tight",
    "savefig.pad_inches": 0.05,
    "figure.dpi": 150,
    "axes.grid": True,
    "grid.alpha": 0.3,
    "axes.axisbelow": True,
}

COLORS = {
    "baseline":   "#bab0ac",
    "noisy":      "#e15759",
    "puretime":   "#4e79a7",
    "cpu":        "#1b9e77",
    "network":    "#d95f02",
    "blkio":      "#7570b3",
    "with_pt":    "#d6604d",
    "without_pt": "#2166ac",
}

# Comprehensive label map: raw CSV values -> display labels
NOISE_TYPE_LABELS = {
    "cpu": "CPU", "CPU": "CPU",
    "network": "Network TX", "Network TX": "Network TX", "net": "Network TX",
    "blkio": "Block I/O", "Block I/O": "Block I/O", "bio": "Block I/O",
    "BLOCK_IO": "Block I/O", "block_io": "Block I/O",
}

NOISE_TYPE_COLORS = {
    "cpu": "#1b9e77", "CPU": "#1b9e77",
    "network": "#d95f02", "Network TX": "#d95f02", "net": "#d95f02",
    "blkio": "#7570b3", "Block I/O": "#7570b3", "bio": "#7570b3",
    "BLOCK_IO": "#7570b3", "block_io": "#7570b3",
}


def apply_style():
    mpl.rcParams.update(STYLE_CONFIG)


def save_figure(fig, output_dir, name, fmt="pdf"):
    path = Path(output_dir) / f"{name}.{fmt}"
    fig.savefig(path, format=fmt, dpi=300, bbox_inches="tight", pad_inches=0.05)
    print(f"  Saved: {path}")
    plt.close(fig)
    return str(path)


def get_label(nt):
    return NOISE_TYPE_LABELS.get(nt, nt)


def get_color(nt):
    return NOISE_TYPE_COLORS.get(nt, "gray")


# ============================================================================
# Figure 1: Noise Removal Accuracy — Baseline Comparison
# ============================================================================
def fig_accuracy_baseline(df_acc, output_dir, fmt="pdf"):
    """
    Grouped bar chart: Baseline vs Noisy vs PureTime per noise type.
    Annotation = Noise Removal Efficiency = (Noisy - PureTime) / (Noisy - Baseline) * 100
    """
    print("\n[Figure 1] Noise Removal Accuracy — Baseline Comparison")

    df_baseline = df_acc[df_acc["container_count"] == 0].copy()
    df_noisy = df_acc[df_acc["container_count"] > 0].copy()

    if df_baseline.empty:
        min_cc = df_acc["container_count"].min()
        df_baseline = df_acc[df_acc["container_count"] == min_cc].copy()
        df_noisy = df_acc[df_acc["container_count"] > min_cc].copy()

    if df_noisy.empty:
        print("  ERROR: Insufficient data. Skipping.")
        return None

    noise_types = sorted(df_noisy["resource_type"].unique())

    stats = []
    for nt in noise_types:
        label = get_label(nt)
        bl_df = df_baseline[df_baseline["resource_type"] == nt]
        if bl_df.empty:
            bl_df = df_baseline
        noisy_df = df_noisy[df_noisy["resource_type"] == nt]
        bl = bl_df["t_e2e_ms"]
        noisy = noisy_df["t_e2e_ms"]
        pt = noisy_df["t_puretime_ms"]

        bl_mean, noisy_mean, pt_mean = bl.mean(), noisy.mean(), pt.mean()

        # Efficiency = PAIRWISE per-invocation: each noisy run vs the solo of the SAME iteration
        # (= "각 호출의 solo를 G.T."). Robust to baseline drift (e.g. HDD wear over a block run
        # makes the aggregate-mean baseline non-stationary → spurious ~100%); the per-pair median
        # neutralizes it. For non-drifting resources (CPU/Net) pairwise ≈ aggregate.
        solo_by_iter = bl_df.groupby("iteration")["t_e2e_ms"].median()
        per_pair = []
        for _, r in noisy_df.iterrows():
            it = r["iteration"]
            if it in solo_by_iter.index:
                solo_i = solo_by_iter.loc[it]
                e_i, pt_i = r["t_e2e_ms"], r["t_puretime_ms"]
                if e_i > solo_i:
                    per_pair.append((e_i - pt_i) / (e_i - solo_i) * 100)
        if per_pair:
            efficiency = float(np.median(per_pair))
        else:
            total_noise = noisy_mean - bl_mean
            efficiency = (noisy_mean - pt_mean) / total_noise * 100 if total_noise > 0 else 0

        n_bl, n_noisy, n_pt = len(bl), len(noisy), len(pt)
        stats.append({
            "type": label,
            "baseline_mean": bl_mean,
            "baseline_ci": 1.96 * bl.std() / np.sqrt(n_bl) if n_bl > 1 else 0,
            "noisy_mean": noisy_mean,
            "noisy_ci": 1.96 * noisy.std() / np.sqrt(n_noisy) if n_noisy > 1 else 0,
            "puretime_mean": pt_mean,
            "puretime_ci": 1.96 * pt.std() / np.sqrt(n_pt) if n_pt > 1 else 0,
            "efficiency": efficiency,
        })

    df_stats = pd.DataFrame(stats)
    print(df_stats.to_string(index=False))

    x = np.arange(len(df_stats)) * 1.25   # 그룹 간격 넓게
    width = 0.34
    fig, ax = plt.subplots(figsize=(5.6, 3.0))

    ax.bar(x - width, df_stats["baseline_mean"], width,
           yerr=df_stats["baseline_ci"], capsize=3,
           color=COLORS["baseline"], edgecolor="black", linewidth=0.6,
           label="Baseline (Isolated)", zorder=3)
    ax.bar(x, df_stats["noisy_mean"], width,
           yerr=df_stats["noisy_ci"], capsize=3,
           color=COLORS["noisy"], edgecolor="black", linewidth=0.6,
           label="Noisy (w/ Interference)", zorder=3)
    ax.bar(x + width, df_stats["puretime_mean"], width,
           yerr=df_stats["puretime_ci"], capsize=3,
           color=COLORS["puretime"], edgecolor="black", linewidth=0.6,
           label="PureTime (Noise-Free)", zorder=3)

    ax.set_xlabel("Noise Type")
    ax.set_ylabel("Execution Time (ms)")
    ax.set_xticks(x)
    ax.set_xticklabels(df_stats["type"])
    ax.legend(framealpha=0.9, edgecolor="gray", loc="upper left", fontsize=7)
    ax.set_ylim(0, df_stats["noisy_mean"].max() * 1.28)   # 위쪽 여백 ↑

    for i, row in df_stats.iterrows():
        # PureTime 막대 위에 efficiency 라벨. 키 큰 Noisy 막대와 안 겹치게 흰 배경 박스 + 진한 색.
        ax.annotate(f"{row['efficiency']:.1f}%",
                    xy=(i * 1.25 + width, row["puretime_mean"]),   # x 간격 1.25 반영(PureTime 막대 정렬)
                    xytext=(0, 9), textcoords="offset points",
                    ha="center", va="bottom", fontsize=9, fontweight="bold",
                    color="#0d47a1", zorder=6,
                    bbox=dict(boxstyle="round,pad=0.2", fc="white", ec="#0d47a1", lw=0.8, alpha=0.95))

    fig.tight_layout()
    return save_figure(fig, output_dir, "fig1_accuracy_baseline", fmt)


# ============================================================================
# Figure 2: Noise Source Identification — Per-iteration ratio time series
# ============================================================================
def fig_noise_source_identification(df_acc, output_dir, fmt="pdf"):
    """
    Per-resource subplot: scatter dots + rolling mean for dominant component,
    thin scatter for non-dominant. Avoids solid-wall effect with dense data.
    y = t_noise_{resource} / (t_noise_cpu + t_noise_net + t_noise_bio) * 100
    """
    print("\n[Figure 2] Noise Source Identification — Per-Iteration Ratio")

    df_noisy = df_acc[df_acc["container_count"] > 0].copy()
    if df_noisy.empty:
        print("  ERROR: No noisy data. Skipping.")
        return None

    noise_cols = [c for c in ["t_noise_cpu", "t_noise_net", "t_noise_bio"]
                  if c in df_noisy.columns]
    if not noise_cols:
        print("  WARNING: No noise component columns. Skipping.")
        return None

    df_noisy["t_noise_total"] = df_noisy[noise_cols].sum(axis=1)

    col_to_short = {"t_noise_cpu": "cpu", "t_noise_net": "net", "t_noise_bio": "bio"}
    short_to_label = {"cpu": "CPU", "net": "Network TX", "bio": "Block I/O"}
    short_to_color = {"cpu": COLORS["cpu"], "net": COLORS["network"], "bio": COLORS["blkio"]}

    for col in noise_cols:
        short = col_to_short[col]
        df_noisy[f"ratio_{short}"] = np.where(
            df_noisy["t_noise_total"] > 0,
            df_noisy[col] / df_noisy["t_noise_total"] * 100,
            0
        )

    noise_types = sorted(df_noisy["resource_type"].unique())
    nt_to_dominant_short = {}
    for nt in noise_types:
        lbl = get_label(nt).lower()
        if "cpu" in lbl:
            nt_to_dominant_short[nt] = "cpu"
        elif "network" in lbl:
            nt_to_dominant_short[nt] = "net"
        elif "block" in lbl or "blk" in lbl or "bio" in lbl:
            nt_to_dominant_short[nt] = "bio"

    n_types = len(noise_types)
    fig, axes = plt.subplots(1, n_types, figsize=(2.5 * n_types, 1.6),
                             constrained_layout=True, sharey=True)
    if n_types == 1:
        axes = [axes]

    ratio_shorts = [col_to_short[c] for c in noise_cols]

    for idx, nt in enumerate(noise_types):
        ax = axes[idx]
        label = get_label(nt)
        subset = df_noisy[df_noisy["resource_type"] == nt].copy()

        if "iteration" in subset.columns:
            subset = subset.sort_values("iteration")
            x_vals = subset["iteration"].values
            x_label = "Iteration"
        else:
            subset = subset.reset_index(drop=True)
            x_vals = subset.index.values
            x_label = "Run"

        dom_short = nt_to_dominant_short.get(nt)

        # --- Dominant component: scatter dots + rolling mean + ±std band ---
        if dom_short:
            dom_color = short_to_color[dom_short]
            dom_label = short_to_label[dom_short]
            y_dom = subset[f"ratio_{dom_short}"].values

            # Small scatter dots (no connecting line)
            ax.scatter(x_vals, y_dom, s=6, color=dom_color, alpha=0.35,
                       edgecolors="none", zorder=3, label=dom_label)

            # Rolling mean (window = 10% of data, min 5)
            win = max(5, len(y_dom) // 10)
            y_series = pd.Series(y_dom)
            y_rolling = y_series.rolling(window=win, center=True, min_periods=1).mean()
            y_std = y_series.rolling(window=win, center=True, min_periods=1).std().fillna(0)

            ax.plot(x_vals, y_rolling, color=dom_color, linewidth=1.5,
                    zorder=4)
            ax.fill_between(x_vals, y_rolling - y_std, y_rolling + y_std,
                            color=dom_color, alpha=0.15, zorder=2)

            # Stats annotation
            mean_r = np.mean(y_dom)
            std_r = np.std(y_dom)
            ax.text(0.95, 0.05,
                    f"μ={mean_r:.1f}%, σ={std_r:.1f}",
                    transform=ax.transAxes, ha="right", va="bottom",
                    fontsize=7, fontweight="bold", color=dom_color,
                    bbox=dict(boxstyle="round,pad=0.3", facecolor="white",
                              edgecolor=dom_color, alpha=0.9))

        # --- Non-dominant components: tiny dots only ---
        for short in ratio_shorts:
            if short == dom_short:
                continue
            color = short_to_color[short]
            comp_label = short_to_label[short]
            y_vals = subset[f"ratio_{short}"].values
            ax.scatter(x_vals, y_vals, s=3, color=color, alpha=0.25,
                       edgecolors="none", zorder=2, label=comp_label)

        ax.set_xlabel(x_label)
        if idx == 0:
            ax.set_ylabel("Noise Ratio (%)")
        ax.set_title(f"Injected: {label}", fontsize=9, fontweight="bold")
        ax.set_ylim(-5, 105)

        if idx == n_types - 1:
            ax.legend(fontsize=6, framealpha=0.9, edgecolor="gray",
                      loc="center right", markerscale=2)

    return save_figure(fig, output_dir, "fig2_noise_source_id", fmt)


# ============================================================================
# Figure 3: System Overhead — Execution Time (Box Plot)
# ============================================================================
def fig_overhead_time(df_time, output_dir, fmt="pdf"):
    """
    Box plot comparing execution time with vs without PureTime.
    Per-type overhead annotation + overall overhead badge.
    """
    print("\n[Figure 3] System Overhead — Execution Time")

    if df_time["with_puretime"].dtype == object:
        df_time["with_puretime"] = df_time["with_puretime"].map(
            {"True": True, "False": False, "true": True, "false": False,
             "1": True, "0": False, 1: True, 0: False})

    df_with = df_time[df_time["with_puretime"] == True]
    df_without = df_time[df_time["with_puretime"] == False]

    if df_with.empty or df_without.empty:
        print("  ERROR: Missing data. Skipping.")
        return None

    noise_types = sorted(df_time["resource_type"].unique())
    fig, ax = plt.subplots(figsize=(3.5, 2.6))

    positions, labels, data_boxes, box_colors = [], [], [], []

    for i, nt in enumerate(noise_types):
        label = get_label(nt)
        w = df_with[df_with["resource_type"] == nt]["t_e2e_ms"]
        wo = df_without[df_without["resource_type"] == nt]["t_e2e_ms"]

        pos_wo, pos_w = i * 3, i * 3 + 1
        data_boxes.extend([wo.values, w.values])
        positions.extend([pos_wo, pos_w])
        box_colors.extend([COLORS["without_pt"], COLORS["with_pt"]])
        labels.append((i * 3 + 0.5, label))

        overhead_pct = (w.mean() - wo.mean()) / wo.mean() * 100 if wo.mean() > 0 else 0
        y_max = max(w.max(), wo.max()) if len(w) > 0 and len(wo) > 0 else 0
        ax.text(i * 3 + 0.5, y_max * 1.05,
                f"{overhead_pct:+.2f}%", ha="center", va="bottom",
                fontsize=6.5, fontweight="bold",
                color="#2e7d32" if abs(overhead_pct) < 5 else "#d32f2f")

    bp = ax.boxplot(data_boxes, positions=positions, widths=0.7,
                     patch_artist=True, showfliers=False,
                     medianprops=dict(color="black", linewidth=1))
    for patch, color in zip(bp["boxes"], box_colors):
        patch.set_facecolor(color)
        patch.set_edgecolor("black")
        patch.set_linewidth(0.6)
        patch.set_alpha(0.8)

    ax.set_xticks([l[0] for l in labels])
    ax.set_xticklabels([l[1] for l in labels])
    ax.set_ylabel("Execution Time (ms)")
    ax.set_xlabel("Noise Type")

    legend_elements = [
        Patch(facecolor=COLORS["without_pt"], edgecolor="black", label="Without PureTime"),
        Patch(facecolor=COLORS["with_pt"], edgecolor="black", label="With PureTime"),
    ]
    ax.legend(handles=legend_elements, fontsize=7, framealpha=0.9, edgecolor="gray")

    overall_with = df_with["t_e2e_ms"].mean()
    overall_without = df_without["t_e2e_ms"].mean()
    overall_oh = (overall_with - overall_without) / overall_without * 100 if overall_without > 0 else 0
    ax.text(0.98, 0.02, f"Overall Overhead: {overall_oh:+.2f}%",
            transform=ax.transAxes, ha="right", va="bottom", fontsize=7.5,
            fontweight="bold",
            bbox=dict(boxstyle="round,pad=0.4", facecolor="#e8f5e9",
                      edgecolor="#2e7d32", alpha=0.9))

    fig.tight_layout()
    return save_figure(fig, output_dir, "fig3_overhead_time", fmt)


# ============================================================================
# Figure 4: System Overhead — Resource Consumption
# ============================================================================
def fig_overhead_resource(df_res, output_dir, fmt="pdf"):
    """
    1×3 horizontal layout spanning full 2-column paper width.
    Each column = one noise type workload.
    Left y-axis: CPU%. Right y-axis: Memory MB. Title = noise type.
    """
    print("\n[Figure 4] System Overhead — Resource Consumption (PureTime Process)")

    df = df_res.copy()
    if "timestamp" in df.columns:
        df["timestamp"] = pd.to_numeric(df["timestamp"], errors="coerce")

    noise_types = sorted(df["resource_type"].unique())
    n = len(noise_types)

    fig, axes = plt.subplots(1, n, figsize=(7.16, 2.4),
                             constrained_layout=True)
    if n == 1:
        axes = [axes]

    C_CPU = "#2166ac"
    C_MEM = "#b2182b"

    for i, nt in enumerate(noise_types):
        ax = axes[i]
        sub = df[df["resource_type"] == nt].copy()
        if sub.empty:
            continue

        # ---- Aggregate per timestamp, use sequential index as x ----
        sub = sub.sort_values("timestamp")
        multi = "iteration" in sub.columns and sub["iteration"].nunique() > 1

        if multi:
            g = sub.groupby("timestamp").agg(
                cpu_m=("cpu_percent", "mean"), cpu_s=("cpu_percent", "std"),
                mem_m=("memory_mb", "mean"),   mem_s=("memory_mb", "std"),
            ).reset_index()
            g["cpu_s"] = g["cpu_s"].fillna(0)
            g["mem_s"] = g["mem_s"].fillna(0)
        else:
            g = sub.rename(columns={"cpu_percent": "cpu_m", "memory_mb": "mem_m"})
            g["cpu_s"] = 0.0
            g["mem_s"] = 0.0

        g = g.reset_index(drop=True)
        t = g.index.values

        # ---- CPU% (left y-axis) ----
        ax.plot(t, g["cpu_m"], color=C_CPU, linewidth=0.8)
        if multi:
            ax.fill_between(t, g["cpu_m"] - g["cpu_s"], g["cpu_m"] + g["cpu_s"],
                            color=C_CPU, alpha=0.15)
        ax.set_ylim(0, 15)
        ax.tick_params(axis="y", labelcolor=C_CPU, labelsize=6)

        # ---- Memory MB (right y-axis) ----
        ax2 = ax.twinx()
        ax2.plot(t, g["mem_m"], color=C_MEM, linewidth=0.8, linestyle="--")
        if multi:
            ax2.fill_between(t, g["mem_m"] - g["mem_s"], g["mem_m"] + g["mem_s"],
                             color=C_MEM, alpha=0.10)
        ax2.set_ylim(0, 1024)
        ax2.tick_params(axis="y", labelcolor=C_MEM, labelsize=6)

        # ---- Title = noise type ----
        ax.set_title(get_label(nt), fontsize=9, fontweight="bold",
                     color=get_color(nt))

        # ---- x-axis ----
        ax.set_xlim(-0.5, len(t) - 0.5)
        ax.set_xlabel("Measurement Point", fontsize=10)
        ax.tick_params(axis="x", labelsize=6)

        # ---- y-axis labels only on edges ----
        if i == 0:
            ax.set_ylabel("CPU (%)", color=C_CPU, fontsize=10)
        else:
            ax.set_ylabel("")
        if i == n - 1:
            ax2.set_ylabel("Memory (MB)", color=C_MEM, fontsize=10)
        else:
            ax2.set_ylabel("")

        # ---- Stats annotation (2-line, inside plot) ----
        cpu_avg = g["cpu_m"].mean()
        mem_avg = g["mem_m"].mean()
        line1 = f"CPU: {cpu_avg:.2f}%"
        line2 = f"Mem: {mem_avg:.1f} MB"
        if "cpu_ratio_system" in sub.columns:
            line1 += f" ({sub['cpu_ratio_system'].mean():.2f}%)"
        if "mem_ratio_system" in sub.columns:
            line2 += f" ({sub['mem_ratio_system'].mean():.2f}%)"
        ax.text(0.97, 0.95, f"{line1}\n{line2}",
                transform=ax.transAxes, ha="right", va="top", fontsize=8,
                bbox=dict(boxstyle="round,pad=0.2", fc="white",
                          ec="gray", alpha=0.85))

    # ---- Shared legend (bottom of first subplot) ----
    from matplotlib.lines import Line2D
    legend_items = [
        Line2D([0], [0], color=C_CPU, linewidth=1.0, label="CPU (%)"),
        Line2D([0], [0], color=C_MEM, linewidth=1.0, linestyle="--",
               label="Memory (MB)"),
    ]
    axes[0].legend(handles=legend_items, fontsize=6, ncol=1,
                   loc="lower left", framealpha=0.9, edgecolor="gray")

    return save_figure(fig, output_dir, "fig4_overhead_resource", fmt)


# ============================================================================
# Main
# ============================================================================
def main():
    parser = argparse.ArgumentParser(description="PureTime Evaluation Figure Generator v3")
    parser.add_argument("--data-dir", type=str, default="./data")
    parser.add_argument("--output-dir", type=str, default="./figures")
    parser.add_argument("--format", type=str, default="pdf",
                        choices=["pdf", "png", "svg", "eps"])
    args = parser.parse_args()

    apply_style()

    data_dir = Path(args.data_dir)
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    fmt = args.format

    print("=" * 60)
    print("PureTime Evaluation Figure Generator (v3)")
    print(f"  Data dir:   {data_dir.resolve()}")
    print(f"  Output dir: {output_dir.resolve()}")
    print(f"  Format:     {fmt}")
    print("=" * 60)

    csv_files = {
        "accuracy": ["accuracy_results.csv", "exp_accuracy.csv", "accuracy.csv"],
        "overhead_time": ["overhead_time.csv", "exp_overhead_time.csv"],
        "overhead_resource": ["overhead_resource.csv", "exp_overhead_resource.csv"],
    }

    def load_csv(key):
        for fname in csv_files[key]:
            path = data_dir / fname
            if path.exists():
                print(f"\n  Loading {key}: {path}")
                df = pd.read_csv(path)
                print(f"    Shape: {df.shape}, Columns: {list(df.columns)}")
                return df
        print(f"\n  WARNING: No CSV found for '{key}'.")
        return None

    df_acc = load_csv("accuracy")
    df_time = load_csv("overhead_time")
    df_res = load_csv("overhead_resource")

    if df_acc is None and df_time is None and df_res is None:
        print("\n  ERROR: No data files found.")
        sys.exit(1)

    generated = []

    if df_acc is not None:
        f1 = fig_accuracy_baseline(df_acc, output_dir, fmt)
        f2 = fig_noise_source_identification(df_acc, output_dir, fmt)
        generated.extend([f for f in [f1, f2] if f])

    # fig3 (time overhead) is DEPRECATED here: the graph-bfs w/vs w/o box-plot produced
    # negative overhead (signal < measurement noise). fig3 is now the event-rate vs overhead
    # curve from plot_overhead_ctxsw.py (exp_overhead_ctxsw.sh data). Keep fig_overhead_time()
    # for reference but do not regenerate fig3 here (would clobber the curve). See contract C7.
    if df_time is not None and os.environ.get("PLOT_LEGACY_FIG3"):
        f3 = fig_overhead_time(df_time, output_dir, fmt)
        if f3:
            generated.append(f3)

    # fig4 (resource overhead) is now the bar-summary from plot_overhead_resource.py (% of node).
    # Keep this old CPU%-timeseries plot for reference but gate it so it doesn't clobber the new fig4.
    if df_res is not None and os.environ.get("PLOT_LEGACY_FIG4"):
        f4 = fig_overhead_resource(df_res, output_dir, fmt)
        if f4:
            generated.append(f4)

    print("\n" + "=" * 60)
    print(f"Done! Generated {len(generated)} figure(s):")
    for f in generated:
        print(f"  • {f}")
    print("=" * 60)


if __name__ == "__main__":
    main()