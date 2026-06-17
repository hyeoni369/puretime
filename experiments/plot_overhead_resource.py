#!/usr/bin/env python3
"""Experiment 5 (overhead) — fig4 (MAIN overhead figure): PureTime's node-resource footprint.

오버헤드 섹션의 *메인* figure. PureTime의 시간 오버헤드는 별도 userspace 프로세스(loader)가
ring buffer를 비우므로 함수 critical path에는 가벼운 커널 훅만 남아 측정 노이즈 이하(<1%)다
(→ fig3 이벤트율 곡선이 그 스케일링을 보조로 보임). 따라서 *실제* 비용은 PureTime 프로세스가
멀티테넌트 노드에서 차지하는 자원이며, 이 figure가 그것을 요약한다.

멀티테넌트 노드(24 cores / 94 GB RAM) 대비:
  (a) CPU — 노드의 0.05~0.08% (= 한 코어의 1~2%; 이벤트율 따라 victim별 차이).
  (b) 메모리(RSS) — 노드의 ~0.08% (= ~71 MB), victim 무관 일정. ring buffer 크기가 지배
      (32 MB 측정 빌드; 512 MB 기본 → ~1 GB) → 조절 가능한 비용.
→ "PureTime online 비용은 노드 자원의 0.1% 미만."

(이전 fig4는 CPU% 시계열 스파이크를 raw로 그려 "파란 색칠"처럼 의미가 안 보였고, 작은 y축이라
오버헤드가 커 보였음 → 노드-자원 풀스케일 막대로 교체.)

Usage: python3 plot_overhead_resource.py --data experiments/data/overhead/overhead_resource.csv \
            --out experiments/figures [--format pdf]
"""
import argparse
import os
import csv
import numpy as np
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.ticker import FuncFormatter
from collections import defaultdict

PCT = FuncFormatter(lambda x, _: f"{x:.2f}%")

NODE_CORES = 24
NODE_RAM_GB = 94
RING_BUFFER_MB = 32
VICTIMS = ["cpu", "network", "block_io"]
LABELS = {"cpu": "CPU\n(float)", "network": "Network\n(upload)", "block_io": "Block\n(compress)"}
C_CPU = "#1565c0"
C_MEM = "#6a1b9a"


def load(path):
    rows = list(csv.DictReader(open(path)))
    d = defaultdict(lambda: {"cpu_pct": [], "cpu_node": [], "mem_mb": [], "mem_node": []})
    for r in rows:
        v = r["resource_type"]
        d[v]["cpu_pct"].append(float(r["cpu_percent"]))          # % of one core
        d[v]["cpu_node"].append(float(r["cpu_ratio_system"]))    # % of 24-core node
        d[v]["mem_mb"].append(float(r["memory_mb"]))
        d[v]["mem_node"].append(float(r["mem_ratio_system"]))    # % of node RAM
    return d


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", required=True)
    ap.add_argument("--out", default="experiments/figures")
    ap.add_argument("--format", default="pdf")
    args = ap.parse_args()

    d = load(args.data)
    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(6.8, 3.2), gridspec_kw={"width_ratios": [1.45, 1]})

    # ---- (a) CPU : % of node (24 cores), bar; label = % of one core ----
    xs = np.arange(len(VICTIMS))
    cpu_node = [float(np.mean(d[v]["cpu_node"])) for v in VICTIMS]
    cpu_core = [float(np.mean(d[v]["cpu_pct"])) for v in VICTIMS]
    ax1.bar(xs, cpu_node, width=0.6, color=C_CPU, alpha=0.9, zorder=3)
    for i in range(len(VICTIMS)):
        ax1.annotate(f"{cpu_node[i]:.3f}%\n({cpu_core[i]:.1f}% of 1 core)", (xs[i], cpu_node[i]),
                     textcoords="offset points", xytext=(0, 4), ha="center", fontsize=7,
                     color="#0d47a1")
    ax1.set_xticks(xs); ax1.set_xticklabels([LABELS[v] for v in VICTIMS], fontsize=8)
    ax1.set_ylabel("CPU usage", fontsize=9)
    ax1.set_title("(a) CPU overhead", fontsize=9.5)
    ax1.set_ylim(0, 0.3)
    ax1.yaxis.set_major_formatter(PCT)
    ax1.axhline(0.1, color="#c62828", lw=1.0, ls="--", zorder=2)
    ax1.text(len(VICTIMS) - 0.5, 0.108, "0.1% of node", color="#c62828", fontsize=6.5,
             ha="right", va="bottom")
    ax1.grid(axis="y", ls=":", alpha=0.4, zorder=0)

    # ---- (b) Memory : single bar, % of node RAM; label = MB ----
    mem_node = float(np.mean([m for v in VICTIMS for m in d[v]["mem_node"]]))
    mem_mb = float(np.mean([m for v in VICTIMS for m in d[v]["mem_mb"]]))
    ax2.bar([0], [mem_node], width=0.45, color=C_MEM, alpha=0.9, zorder=3)
    ax2.annotate(f"{mem_node:.3f}%\n({mem_mb:.0f} MB)", (0, mem_node),
                 textcoords="offset points", xytext=(0, 4), ha="center", fontsize=7.5,
                 color="#4a148c")
    ax2.set_xticks([0]); ax2.set_xticklabels(["all victims\n(constant)"], fontsize=8)
    ax2.set_ylabel("Memory RSS", fontsize=9)
    ax2.set_title("(b) Memory overhead", fontsize=9.5)
    ax2.set_ylim(0, 0.3)
    ax2.set_xlim(-0.6, 0.6)
    ax2.yaxis.set_major_formatter(PCT)
    ax2.axhline(0.1, color="#c62828", lw=1.0, ls="--", zorder=2)
    ax2.text(0.55, 0.108, "0.1% of node", color="#c62828", fontsize=6.5, ha="right", va="bottom")
    ax2.grid(axis="y", ls=":", alpha=0.4, zorder=0)

    fig.suptitle("PureTime online footprint: < 0.1% of node CPU & RAM", fontsize=11, y=1.01)
    fig.text(0.5, -0.04,
             f"Online tracer cost only (analyzer runs offline, off the critical path).  "
             f"Memory ∝ ring-buffer size: {RING_BUFFER_MB} MB measurement build (~71 MB RSS); "
             f"512 MB default → ~1 GB.",
             ha="center", fontsize=6.6, color="#607d8b", style="italic")
    fig.tight_layout()
    os.makedirs(args.out, exist_ok=True)
    path = os.path.join(args.out, f"fig4_overhead_resource.{args.format}")
    fig.savefig(path, dpi=200, bbox_inches="tight")
    print(f"Saved: {path}")
    for v in VICTIMS:
        print(f"  {v:>8}: CPU {np.mean(d[v]['cpu_node']):.3f}% of node "
              f"({np.mean(d[v]['cpu_pct']):.2f}% of 1 core), RSS {np.mean(d[v]['mem_mb']):.1f} MB "
              f"({np.mean(d[v]['mem_node']):.3f}% of node)")


if __name__ == "__main__":
    main()
