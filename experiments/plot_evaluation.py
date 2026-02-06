#!/usr/bin/env python3
"""
PureTime Evaluation Figure Generator
=====================================
Generates publication-quality figures for PureTime paper evaluation section.

Expected CSV files (place in same directory or specify paths):
  1. accuracy_results.csv   - Noise removal accuracy experiment
  2. overhead_time.csv      - Execution time overhead experiment
  3. overhead_resource.csv  - Resource consumption overhead experiment

Usage:
  python plot_evaluation.py [--data-dir ./data] [--output-dir ./figures] [--format pdf]
"""

import argparse
import os
import sys
import warnings
from pathlib import Path

import matplotlib as mpl
import matplotlib.pyplot as plt
import matplotlib.ticker as mticker
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
    "xtick.minor.width": 0.5,
    "ytick.minor.width": 0.5,
    "savefig.dpi": 300,
    "savefig.bbox": "tight",
    "savefig.pad_inches": 0.05,
    "figure.dpi": 150,
    "axes.grid": True,
    "grid.alpha": 0.3,
    "axes.axisbelow": True,
}

# Color palette (colorblind-friendly, publication-suitable)
COLORS = {
    "baseline":   "#2166ac",  # blue
    "noisy":      "#d6604d",  # red
    "puretime":   "#4daf4a",  # green
    "cpu":        "#1b9e77",  # teal
    "network":    "#d95f02",  # orange
    "blkio":      "#7570b3",  # purple
    "with_pt":    "#d6604d",  # red
    "without_pt": "#2166ac",  # blue
    "overhead":   "#e7298a",  # pink
}

HATCHES = {
    "baseline": "",
    "noisy": "//",
    "puretime": "\\\\",
    "cpu": "",
    "network": "//",
    "blkio": "\\\\",
}

NOISE_TYPE_LABELS = {
    "cpu": "CPU",
    "network": "Network TX",
    "blkio": "Block I/O",
    "net": "Network TX",
    "bio": "Block I/O",
}


def apply_style():
    """Apply publication-quality matplotlib style."""
    mpl.rcParams.update(STYLE_CONFIG)


def save_figure(fig, output_dir, name, fmt="pdf"):
    """Save figure in specified format."""
    path = Path(output_dir) / f"{name}.{fmt}"
    fig.savefig(path, format=fmt, dpi=300, bbox_inches="tight", pad_inches=0.05)
    print(f"  Saved: {path}")
    plt.close(fig)
    return str(path)


# ============================================================================
# Figure 1: Noise Removal Accuracy — Baseline Comparison (Bar Chart)
# ============================================================================
def fig_accuracy_baseline(df_acc, output_dir, fmt="pdf"):
    """
    Bar chart comparing execution times across three conditions:
      - Baseline (isolated, container_count=0)
      - Noisy (with interference, container_count>0, t_e2e_ms)
      - PureTime (noise-free estimate, container_count>0, t_puretime_ms)
    Grouped by noise type (CPU, Network, Block I/O).
    """
    print("\n[Figure 1] Noise Removal Accuracy — Baseline Comparison")

    # Separate baseline (no interference) and noisy runs
    df_baseline = df_acc[df_acc["container_count"] == 0].copy()
    df_noisy = df_acc[df_acc["container_count"] > 0].copy()

    if df_baseline.empty:
        print("  WARNING: No baseline data (container_count=0). "
              "Using minimum container_count as proxy.")
        min_cc = df_acc["container_count"].min()
        df_baseline = df_acc[df_acc["container_count"] == min_cc].copy()
        df_noisy = df_acc[df_acc["container_count"] > min_cc].copy()

    if df_noisy.empty:
        print("  ERROR: Insufficient data for baseline comparison. Skipping.")
        return None

    noise_types = sorted(df_noisy["resource_type"].unique())

    # Compute statistics
    stats = []
    for nt in noise_types:
        label = NOISE_TYPE_LABELS.get(nt, nt.upper())
        bl = df_baseline[df_baseline["resource_type"] == nt]["t_e2e_ms"]
        noisy = df_noisy[df_noisy["resource_type"] == nt]["t_e2e_ms"]
        pt = df_noisy[df_noisy["resource_type"] == nt]["t_puretime_ms"]

        # If baseline doesn't have per-type data, use all baseline
        if bl.empty:
            bl = df_baseline["t_e2e_ms"]

        stats.append({
            "type": label,
            "baseline_mean": bl.mean(),
            "baseline_ci": 1.96 * bl.std() / np.sqrt(len(bl)) if len(bl) > 1 else 0,
            "noisy_mean": noisy.mean(),
            "noisy_ci": 1.96 * noisy.std() / np.sqrt(len(noisy)) if len(noisy) > 1 else 0,
            "puretime_mean": pt.mean(),
            "puretime_ci": 1.96 * pt.std() / np.sqrt(len(pt)) if len(pt) > 1 else 0,
        })

    df_stats = pd.DataFrame(stats)
    print(df_stats.to_string(index=False))

    # Plot
    x = np.arange(len(df_stats))
    width = 0.25
    fig, ax = plt.subplots(figsize=(3.5, 2.6))

    bars_bl = ax.bar(x - width, df_stats["baseline_mean"], width,
                     yerr=df_stats["baseline_ci"], capsize=3,
                     color=COLORS["baseline"], edgecolor="black", linewidth=0.6,
                     label="Baseline (Isolated)", zorder=3)
    bars_ny = ax.bar(x, df_stats["noisy_mean"], width,
                     yerr=df_stats["noisy_ci"], capsize=3,
                     color=COLORS["noisy"], edgecolor="black", linewidth=0.6,
                     hatch="//", label="Noisy (w/ Interference)", zorder=3)
    bars_pt = ax.bar(x + width, df_stats["puretime_mean"], width,
                     yerr=df_stats["puretime_ci"], capsize=3,
                     color=COLORS["puretime"], edgecolor="black", linewidth=0.6,
                     hatch="\\\\", label="PureTime (Noise-Free)", zorder=3)

    ax.set_xlabel("Noise Type")
    ax.set_ylabel("Execution Time (ms)")
    ax.set_xticks(x)
    ax.set_xticklabels(df_stats["type"])
    ax.legend(framealpha=0.9, edgecolor="gray", loc="upper left", fontsize=7)
    ax.set_ylim(bottom=0)

    # Add percentage error annotations
    for i, row in df_stats.iterrows():
        if row["baseline_mean"] > 0:
            err = abs(row["puretime_mean"] - row["baseline_mean"]) / row["baseline_mean"] * 100
            ax.annotate(f"{err:.1f}%",
                        xy=(i + width, row["puretime_mean"]),
                        xytext=(0, 8), textcoords="offset points",
                        ha="center", va="bottom", fontsize=6.5, color="green",
                        fontweight="bold")

    fig.tight_layout()
    return save_figure(fig, output_dir, "fig1_accuracy_baseline", fmt)


# ============================================================================
# Figure 2: Noise Removal Accuracy — By Noise Type (Detailed Breakdown)
# ============================================================================
def fig_accuracy_by_type(df_acc, output_dir, fmt="pdf"):
    """
    Per-noise-type accuracy: shows how much of each noise component
    PureTime correctly identified. Stacked bar or grouped comparison.
    """
    print("\n[Figure 2] Noise Removal Accuracy — By Noise Type Breakdown")

    df_noisy = df_acc[df_acc["container_count"] > 0].copy()
    if df_noisy.empty:
        print("  ERROR: No noisy data. Skipping.")
        return None

    noise_types = sorted(df_noisy["resource_type"].unique())

    # Noise component columns
    noise_cols = [c for c in ["t_noise_cpu", "t_noise_net", "t_noise_bio"]
                  if c in df_noisy.columns]

    if not noise_cols:
        print("  WARNING: No noise component columns found. Skipping breakdown.")
        return None

    # Per-type statistics
    stats = []
    for nt in noise_types:
        subset = df_noisy[df_noisy["resource_type"] == nt]
        row = {"type": NOISE_TYPE_LABELS.get(nt, nt.upper())}
        row["total_noise_mean"] = (subset["t_e2e_ms"] - subset["t_puretime_ms"]).mean()
        row["total_noise_ci"] = 1.96 * (subset["t_e2e_ms"] - subset["t_puretime_ms"]).std() / np.sqrt(len(subset)) if len(subset) > 1 else 0

        for col in noise_cols:
            short = col.replace("t_noise_", "")
            row[f"{short}_mean"] = subset[col].mean()
            row[f"{short}_ci"] = 1.96 * subset[col].std() / np.sqrt(len(subset)) if len(subset) > 1 else 0

        stats.append(row)

    df_stats = pd.DataFrame(stats)
    print(df_stats.to_string(index=False))

    # Stacked bar chart of noise components
    x = np.arange(len(df_stats))
    fig, ax = plt.subplots(figsize=(3.5, 2.6))

    component_colors = {"cpu": COLORS["cpu"], "net": COLORS["network"], "bio": COLORS["blkio"]}
    component_labels = {"cpu": "CPU Wait", "net": "Network Wait", "bio": "Block I/O Wait"}

    bottom = np.zeros(len(df_stats))
    for col in noise_cols:
        short = col.replace("t_noise_", "")
        vals = df_stats[f"{short}_mean"].values
        ax.bar(x, vals, 0.5, bottom=bottom,
               color=component_colors.get(short, "gray"),
               edgecolor="black", linewidth=0.5,
               label=component_labels.get(short, short.upper()),
               zorder=3)
        bottom += vals

    # Overlay total noise marker
    ax.scatter(x, df_stats["total_noise_mean"], marker="D", s=30,
               color="black", zorder=4, label="Total Noise Removed")

    ax.set_xlabel("Injected Noise Type")
    ax.set_ylabel("Measured Noise (ms)")
    ax.set_xticks(x)
    ax.set_xticklabels(df_stats["type"])
    ax.legend(framealpha=0.9, edgecolor="gray", fontsize=7, loc="upper left")
    ax.set_ylim(bottom=0)

    fig.tight_layout()
    return save_figure(fig, output_dir, "fig2_accuracy_by_type", fmt)


# ============================================================================
# Figure 3: Noise Removal Accuracy — By Noise Intensity (Line Plot)
# ============================================================================
def fig_accuracy_by_intensity(df_acc, output_dir, fmt="pdf"):
    """
    Line plot: accuracy (error % vs baseline) as a function of
    interference intensity (container_count).
    """
    print("\n[Figure 3] Noise Removal Accuracy — By Noise Intensity")

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
    intensities = sorted(df_noisy["container_count"].unique())

    fig, axes = plt.subplots(1, 2, figsize=(7, 2.8), constrained_layout=True)

    # --- Left: Execution time vs intensity ---
    ax1 = axes[0]
    for nt in noise_types:
        label = NOISE_TYPE_LABELS.get(nt, nt.upper())
        bl_mean = df_baseline[df_baseline["resource_type"] == nt]["t_e2e_ms"].mean()
        if np.isnan(bl_mean):
            bl_mean = df_baseline["t_e2e_ms"].mean()

        means_noisy, means_pt = [], []
        cis_noisy, cis_pt = [], []
        for cc in intensities:
            sub = df_noisy[(df_noisy["resource_type"] == nt) & (df_noisy["container_count"] == cc)]
            if sub.empty:
                means_noisy.append(np.nan)
                means_pt.append(np.nan)
                cis_noisy.append(0)
                cis_pt.append(0)
                continue
            means_noisy.append(sub["t_e2e_ms"].mean())
            means_pt.append(sub["t_puretime_ms"].mean())
            n = len(sub)
            cis_noisy.append(1.96 * sub["t_e2e_ms"].std() / np.sqrt(n) if n > 1 else 0)
            cis_pt.append(1.96 * sub["t_puretime_ms"].std() / np.sqrt(n) if n > 1 else 0)

        color = {"cpu": COLORS["cpu"], "network": COLORS["network"],
                 "net": COLORS["network"], "blkio": COLORS["blkio"],
                 "bio": COLORS["blkio"]}.get(nt, "gray")

        ax1.errorbar(intensities, means_noisy, yerr=cis_noisy,
                     fmt="o--", color=color, alpha=0.5, capsize=2,
                     label=f"{label} (Noisy)", markersize=4)
        ax1.errorbar(intensities, means_pt, yerr=cis_pt,
                     fmt="s-", color=color, capsize=2,
                     label=f"{label} (PureTime)", markersize=4)

    # Baseline reference line
    ax1.axhline(y=df_baseline["t_e2e_ms"].mean(), color="gray", linestyle=":",
                linewidth=1, label="Baseline", zorder=1)
    ax1.set_xlabel("Number of Interfering Containers")
    ax1.set_ylabel("Execution Time (ms)")
    ax1.set_xticks(intensities)
    ax1.legend(fontsize=6, framealpha=0.9, edgecolor="gray", ncol=1)

    # --- Right: Error percentage vs intensity ---
    ax2 = axes[1]
    for nt in noise_types:
        label = NOISE_TYPE_LABELS.get(nt, nt.upper())
        bl_mean = df_baseline[df_baseline["resource_type"] == nt]["t_e2e_ms"].mean()
        if np.isnan(bl_mean):
            bl_mean = df_baseline["t_e2e_ms"].mean()

        errors = []
        for cc in intensities:
            sub = df_noisy[(df_noisy["resource_type"] == nt) & (df_noisy["container_count"] == cc)]
            if sub.empty or bl_mean == 0:
                errors.append(np.nan)
                continue
            err = abs(sub["t_puretime_ms"].mean() - bl_mean) / bl_mean * 100
            errors.append(err)

        color = {"cpu": COLORS["cpu"], "network": COLORS["network"],
                 "net": COLORS["network"], "blkio": COLORS["blkio"],
                 "bio": COLORS["blkio"]}.get(nt, "gray")
        ax2.plot(intensities, errors, "s-", color=color, label=label, markersize=4)

    ax2.set_xlabel("Number of Interfering Containers")
    ax2.set_ylabel("PureTime Error (%)")
    ax2.set_xticks(intensities)
    ax2.axhline(y=0, color="gray", linestyle=":", linewidth=0.8, zorder=1)
    ax2.legend(fontsize=7, framealpha=0.9, edgecolor="gray")

    fig.tight_layout()
    return save_figure(fig, output_dir, "fig3_accuracy_by_intensity", fmt)


# ============================================================================
# Figure 4: System Overhead — Execution Time (Box Plot + Bar)
# ============================================================================
def fig_overhead_time(df_time, output_dir, fmt="pdf"):
    """
    Execution time overhead: compares runs with and without PureTime.
    Shows both distribution (boxplot) and mean overhead percentage.
    """
    print("\n[Figure 4] System Overhead — Execution Time")

    # Parse with_puretime as boolean if needed
    if df_time["with_puretime"].dtype == object:
        df_time["with_puretime"] = df_time["with_puretime"].map(
            {"True": True, "False": False, "true": True, "false": False,
             "1": True, "0": False, 1: True, 0: False})

    df_with = df_time[df_time["with_puretime"] == True]
    df_without = df_time[df_time["with_puretime"] == False]

    if df_with.empty or df_without.empty:
        print("  ERROR: Missing with/without PureTime data. Skipping.")
        return None

    noise_types = sorted(df_time["resource_type"].unique())

    fig, axes = plt.subplots(1, 2, figsize=(7, 2.8), constrained_layout=True)

    # --- Left: Box plot of execution time distributions ---
    ax1 = axes[0]
    positions = []
    labels = []
    data_boxes = []
    box_colors = []

    for i, nt in enumerate(noise_types):
        label = NOISE_TYPE_LABELS.get(nt, nt.upper())
        w = df_with[df_with["resource_type"] == nt]["t_e2e_ms"]
        wo = df_without[df_without["resource_type"] == nt]["t_e2e_ms"]

        pos_wo = i * 3
        pos_w = i * 3 + 1
        data_boxes.append(wo.values)
        data_boxes.append(w.values)
        positions.extend([pos_wo, pos_w])
        box_colors.extend([COLORS["without_pt"], COLORS["with_pt"]])
        labels.append((i * 3 + 0.5, label))

    bp = ax1.boxplot(data_boxes, positions=positions, widths=0.7,
                     patch_artist=True, showfliers=False,
                     medianprops=dict(color="black", linewidth=1))

    for patch, color in zip(bp["boxes"], box_colors):
        patch.set_facecolor(color)
        patch.set_edgecolor("black")
        patch.set_linewidth(0.6)
        patch.set_alpha(0.8)

    ax1.set_xticks([l[0] for l in labels])
    ax1.set_xticklabels([l[1] for l in labels])
    ax1.set_ylabel("Execution Time (ms)")
    ax1.set_xlabel("Noise Type")

    legend_elements = [
        Patch(facecolor=COLORS["without_pt"], edgecolor="black", label="Without PureTime"),
        Patch(facecolor=COLORS["with_pt"], edgecolor="black", label="With PureTime"),
    ]
    ax1.legend(handles=legend_elements, fontsize=7, framealpha=0.9, edgecolor="gray")

    # --- Right: Overhead percentage bar ---
    ax2 = axes[1]
    overhead_pcts = []
    type_labels = []

    for nt in noise_types:
        label = NOISE_TYPE_LABELS.get(nt, nt.upper())
        mean_with = df_with[df_with["resource_type"] == nt]["t_e2e_ms"].mean()
        mean_without = df_without[df_without["resource_type"] == nt]["t_e2e_ms"].mean()
        if mean_without > 0:
            overhead = (mean_with - mean_without) / mean_without * 100
        else:
            overhead = 0
        overhead_pcts.append(overhead)
        type_labels.append(label)

    # Overall overhead
    overall_with = df_with["t_e2e_ms"].mean()
    overall_without = df_without["t_e2e_ms"].mean()
    overall_overhead = (overall_with - overall_without) / overall_without * 100 if overall_without > 0 else 0
    overhead_pcts.append(overall_overhead)
    type_labels.append("Overall")

    x = np.arange(len(type_labels))
    colors = [COLORS["overhead"]] * (len(type_labels) - 1) + ["#636363"]
    bars = ax2.bar(x, overhead_pcts, 0.5, color=colors,
                   edgecolor="black", linewidth=0.6, zorder=3)

    # Annotate values
    for bar, val in zip(bars, overhead_pcts):
        ax2.text(bar.get_x() + bar.get_width() / 2, bar.get_height() + 0.2,
                 f"{val:.2f}%", ha="center", va="bottom", fontsize=7, fontweight="bold")

    ax2.set_xlabel("Noise Type")
    ax2.set_ylabel("Execution Time Overhead (%)")
    ax2.set_xticks(x)
    ax2.set_xticklabels(type_labels)
    ax2.axhline(y=0, color="gray", linestyle="-", linewidth=0.5)

    fig.tight_layout()
    return save_figure(fig, output_dir, "fig4_overhead_time", fmt)


# ============================================================================
# Figure 5: System Overhead — Resource Consumption (Time Series)
# ============================================================================
def fig_overhead_resource(df_res, output_dir, fmt="pdf"):
    """
    Resource consumption over time: CPU% and Memory (MB) with/without PureTime.
    """
    print("\n[Figure 5] System Overhead — Resource Consumption")

    if "timestamp" in df_res.columns:
        df_res["timestamp"] = pd.to_numeric(df_res["timestamp"], errors="coerce")
        df_res = df_res.sort_values("timestamp")

    fig, axes = plt.subplots(1, 2, figsize=(7, 2.8), constrained_layout=True)

    # --- Left: CPU usage ---
    ax1 = axes[0]
    if "cpu_percent" in df_res.columns:
        # Group by noise type
        noise_types = sorted(df_res["resource_type"].unique())
        for nt in noise_types:
            label = NOISE_TYPE_LABELS.get(nt, nt.upper())
            sub = df_res[df_res["resource_type"] == nt]

            # If we have iteration-based grouping, average across iterations
            if "iteration" in sub.columns:
                grouped = sub.groupby("timestamp")["cpu_percent"].agg(["mean", "std"]).reset_index()
                color = {"cpu": COLORS["cpu"], "network": COLORS["network"],
                         "net": COLORS["network"], "blkio": COLORS["blkio"],
                         "bio": COLORS["blkio"]}.get(nt, "gray")
                ax1.plot(grouped["timestamp"] - grouped["timestamp"].min(),
                         grouped["mean"], "-", color=color, label=label, linewidth=1)
                ax1.fill_between(grouped["timestamp"] - grouped["timestamp"].min(),
                                 grouped["mean"] - grouped["std"],
                                 grouped["mean"] + grouped["std"],
                                 alpha=0.15, color=color)
            else:
                ax1.plot(sub["timestamp"] - sub["timestamp"].min(),
                         sub["cpu_percent"], "-", label=label, linewidth=1)

        ax1.set_xlabel("Time (s)")
        ax1.set_ylabel("CPU Usage (%)")
        ax1.legend(fontsize=7, framealpha=0.9, edgecolor="gray")

    if "cpu_ratio_system" in df_res.columns:
        # Also show PureTime's share of system CPU
        overall_ratio = df_res["cpu_ratio_system"].mean()
        ax1.set_title(f"PureTime CPU Share: {overall_ratio:.2f}%", fontsize=8)

    # --- Right: Memory usage ---
    ax2 = axes[1]
    if "memory_mb" in df_res.columns:
        noise_types = sorted(df_res["resource_type"].unique())
        for nt in noise_types:
            label = NOISE_TYPE_LABELS.get(nt, nt.upper())
            sub = df_res[df_res["resource_type"] == nt]

            if "iteration" in sub.columns:
                grouped = sub.groupby("timestamp")["memory_mb"].agg(["mean", "std"]).reset_index()
                color = {"cpu": COLORS["cpu"], "network": COLORS["network"],
                         "net": COLORS["network"], "blkio": COLORS["blkio"],
                         "bio": COLORS["blkio"]}.get(nt, "gray")
                ax2.plot(grouped["timestamp"] - grouped["timestamp"].min(),
                         grouped["mean"], "-", color=color, label=label, linewidth=1)
                ax2.fill_between(grouped["timestamp"] - grouped["timestamp"].min(),
                                 grouped["mean"] - grouped["std"],
                                 grouped["mean"] + grouped["std"],
                                 alpha=0.15, color=color)
            else:
                ax2.plot(sub["timestamp"] - sub["timestamp"].min(),
                         sub["memory_mb"], "-", label=label, linewidth=1)

        ax2.set_xlabel("Time (s)")
        ax2.set_ylabel("Memory Usage (MB)")
        ax2.legend(fontsize=7, framealpha=0.9, edgecolor="gray")

    if "mem_ratio_system" in df_res.columns:
        overall_mem_ratio = df_res["mem_ratio_system"].mean()
        ax2.set_title(f"PureTime Memory Share: {overall_mem_ratio:.2f}%", fontsize=8)

    fig.tight_layout()
    return save_figure(fig, output_dir, "fig5_overhead_resource", fmt)


# ============================================================================
# Figure 6: Summary Table — Overall Accuracy & Overhead (as figure)
# ============================================================================
def fig_summary_table(df_acc, df_time, df_res, output_dir, fmt="pdf"):
    """
    Summary table rendered as a figure: key metrics at a glance.
    """
    print("\n[Figure 6] Summary Table")

    rows = []

    # --- Accuracy metrics ---
    if df_acc is not None:
        df_baseline = df_acc[df_acc["container_count"] == 0]
        df_noisy = df_acc[df_acc["container_count"] > 0]

        if df_baseline.empty:
            min_cc = df_acc["container_count"].min()
            df_baseline = df_acc[df_acc["container_count"] == min_cc]
            df_noisy = df_acc[df_acc["container_count"] > min_cc]

        if not df_noisy.empty:
            for nt in sorted(df_noisy["resource_type"].unique()):
                label = NOISE_TYPE_LABELS.get(nt, nt.upper())
                bl = df_baseline[df_baseline["resource_type"] == nt]["t_e2e_ms"].mean()
                if np.isnan(bl):
                    bl = df_baseline["t_e2e_ms"].mean()
                pt = df_noisy[df_noisy["resource_type"] == nt]["t_puretime_ms"].mean()
                noisy = df_noisy[df_noisy["resource_type"] == nt]["t_e2e_ms"].mean()
                err = abs(pt - bl) / bl * 100 if bl > 0 else np.nan
                noise_added = (noisy - bl) / bl * 100 if bl > 0 else np.nan

                rows.append([
                    label,
                    f"{bl:.2f}",
                    f"{noisy:.2f} (+{noise_added:.1f}%)",
                    f"{pt:.2f}",
                    f"{err:.2f}%"
                ])

    # --- Overhead metrics ---
    if df_time is not None:
        if df_time["with_puretime"].dtype == object:
            df_time["with_puretime"] = df_time["with_puretime"].map(
                {"True": True, "False": False, "true": True, "false": False,
                 "1": True, "0": False, 1: True, 0: False})
        mean_with = df_time[df_time["with_puretime"] == True]["t_e2e_ms"].mean()
        mean_without = df_time[df_time["with_puretime"] == False]["t_e2e_ms"].mean()
        overhead_pct = (mean_with - mean_without) / mean_without * 100 if mean_without > 0 else 0
        rows.append(["Time Overhead", f"{mean_without:.2f}", "—",
                      f"{mean_with:.2f}", f"+{overhead_pct:.2f}%"])

    if df_res is not None:
        if "cpu_ratio_system" in df_res.columns:
            cpu_r = df_res["cpu_ratio_system"].mean()
            rows.append(["CPU Overhead", "—", "—", "—", f"{cpu_r:.2f}%"])
        if "mem_ratio_system" in df_res.columns:
            mem_r = df_res["mem_ratio_system"].mean()
            rows.append(["Memory Overhead", "—", "—", "—", f"{mem_r:.2f}%"])

    if not rows:
        print("  No data available for summary table. Skipping.")
        return None

    col_labels = ["Metric", "Baseline (ms)", "Noisy (ms)", "PureTime (ms)", "Error / Overhead"]

    fig, ax = plt.subplots(figsize=(6, 0.3 * (len(rows) + 1.5)))
    ax.axis("off")

    table = ax.table(cellText=rows, colLabels=col_labels,
                     cellLoc="center", loc="center",
                     colColours=["#d4e6f1"] * len(col_labels))
    table.auto_set_font_size(False)
    table.set_fontsize(8)
    table.scale(1, 1.4)

    # Style header
    for j in range(len(col_labels)):
        table[0, j].set_text_props(fontweight="bold")

    fig.tight_layout()
    return save_figure(fig, output_dir, "fig6_summary_table", fmt)


# ============================================================================
# Main
# ============================================================================
def main():
    parser = argparse.ArgumentParser(description="PureTime Evaluation Figure Generator")
    parser.add_argument("--data-dir", type=str, default="./data",
                        help="Directory containing CSV files")
    parser.add_argument("--output-dir", type=str, default="./figures",
                        help="Directory to save figures")
    parser.add_argument("--format", type=str, default="pdf",
                        choices=["pdf", "png", "svg", "eps"],
                        help="Output figure format (default: pdf)")
    args = parser.parse_args()

    apply_style()

    data_dir = Path(args.data_dir)
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    fmt = args.format

    print("=" * 60)
    print("PureTime Evaluation Figure Generator")
    print(f"  Data dir:   {data_dir.resolve()}")
    print(f"  Output dir: {output_dir.resolve()}")
    print(f"  Format:     {fmt}")
    print("=" * 60)

    # --- Load CSVs ---
    csv_files = {
        "accuracy": ["accuracy_results.csv", "exp_accuracy.csv", "accuracy.csv"],
        "overhead_time": ["overhead_time.csv", "exp_overhead_time.csv", "overhead_time_results.csv"],
        "overhead_resource": ["overhead_resource.csv", "exp_overhead_resource.csv", "overhead_resource_results.csv"],
    }

    def load_csv(key):
        for fname in csv_files[key]:
            path = data_dir / fname
            if path.exists():
                print(f"\n  Loading {key}: {path}")
                df = pd.read_csv(path)
                print(f"    Shape: {df.shape}, Columns: {list(df.columns)}")
                return df
        print(f"\n  WARNING: No CSV found for '{key}'. Tried: {csv_files[key]}")
        return None

    df_acc = load_csv("accuracy")
    df_time = load_csv("overhead_time")
    df_res = load_csv("overhead_resource")

    if df_acc is None and df_time is None and df_res is None:
        print("\n  ERROR: No data files found. Please check --data-dir path.")
        print(f"  Expected CSV files in: {data_dir.resolve()}")
        print("  Expected filenames:")
        for k, fnames in csv_files.items():
            print(f"    {k}: {fnames}")
        sys.exit(1)

    # --- Generate figures ---
    generated = []

    if df_acc is not None:
        f1 = fig_accuracy_baseline(df_acc, output_dir, fmt)
        f2 = fig_accuracy_by_type(df_acc, output_dir, fmt)
        f3 = fig_accuracy_by_intensity(df_acc, output_dir, fmt)
        generated.extend([f for f in [f1, f2, f3] if f])

    if df_time is not None:
        f4 = fig_overhead_time(df_time, output_dir, fmt)
        if f4:
            generated.append(f4)

    if df_res is not None:
        f5 = fig_overhead_resource(df_res, output_dir, fmt)
        if f5:
            generated.append(f5)

    f6 = fig_summary_table(df_acc, df_time, df_res, output_dir, fmt)
    if f6:
        generated.append(f6)

    print("\n" + "=" * 60)
    print(f"Done! Generated {len(generated)} figure(s):")
    for f in generated:
        print(f"  • {f}")
    print("=" * 60)


if __name__ == "__main__":
    main()