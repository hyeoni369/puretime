#!/usr/bin/env python3
"""Experiment 5 (overhead) — fig4 (MAIN overhead figure): PureTime's node-resource footprint.

오버헤드 섹션의 *메인* figure. 시간 오버헤드는 별도 userspace 프로세스(loader)가 ring buffer를
비워 함수 critical path엔 가벼운 커널 훅만 남아 노이즈 이하(<1%) → fig3 이벤트율 곡선이 보조.
실제 비용은 PureTime 프로세스가 멀티테넌트 노드(24 cores / 94 GB RAM)에서 차지하는 자원:
한 figure에 CPU(victim 3종, 노드 코어 대비)와 Memory(RSS, 노드 RAM 대비, ring buffer 분해)를
같은 "% of node" 축에 나란히 → 둘 다 0.1% 미만. (제목/캡션은 논문 캡션으로, figure엔 없음.)

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
XLAB = {"cpu": "CPU\n(float)", "network": "CPU\n(net)", "block_io": "CPU\n(block)"}
C_CPU = "#4e79a7"     # muted blue (Tableau)
C_MEM = "#7b3f99"     # muted purple (ring buffer)
C_MEM2 = "#c9aed6"    # light purple (base)
LBL_FS = 12
TICK_FS = 10.5
BAR_FS = 11.5
REF_FS = 9.5


def load(path):
    rows = list(csv.DictReader(open(path)))
    d = defaultdict(lambda: {"cpu_node": [], "mem_node": [], "mem_mb": []})
    for r in rows:
        v = r["resource_type"]
        d[v]["cpu_node"].append(float(r["cpu_ratio_system"]))
        d[v]["mem_node"].append(float(r["mem_ratio_system"]))
        d[v]["mem_mb"].append(float(r["memory_mb"]))
    return d


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", required=True)
    ap.add_argument("--out", default="experiments/figures")
    ap.add_argument("--format", default="pdf")
    args = ap.parse_args()
    d = load(args.data)

    fig, ax = plt.subplots(figsize=(5.6, 3.4))
    # CPU 3 victim (노드 코어 %)
    cpu_node = [float(np.mean(d[v]["cpu_node"])) for v in VICTIMS]
    xs_cpu = [0, 1, 2]
    ax.bar(xs_cpu, cpu_node, width=0.66, color=C_CPU, edgecolor="black", lw=0.6, zorder=3)
    for x, v in zip(xs_cpu, cpu_node):
        ax.annotate(f"{v:.3f}%", (x, v), textcoords="offset points", xytext=(0, 4),
                    ha="center", fontsize=BAR_FS, fontweight="bold", color="#2c4a6e")

    # Memory (노드 RAM %) — ring buffer 분해 stacked
    x_mem = 3.6
    mem_node = float(np.mean([m for v in VICTIMS for m in d[v]["mem_node"]]))
    mem_mb = float(np.mean([m for v in VICTIMS for m in d[v]["mem_mb"]]))
    rb_node = mem_node * RING_BUFFER_MB / mem_mb
    base_node = mem_node - rb_node
    ax.bar([x_mem], [rb_node], width=0.66, color=C_MEM, edgecolor="black", lw=0.6, zorder=3,
           label=f"ring buffer ({RING_BUFFER_MB} MB, tunable)")
    ax.bar([x_mem], [base_node], width=0.66, bottom=[rb_node], color=C_MEM2, edgecolor="black",
           lw=0.6, zorder=3, label="loader + libbpf + maps")
    ax.annotate(f"{mem_node:.3f}%\n({mem_mb:.0f} MB)", (x_mem, mem_node), textcoords="offset points",
                xytext=(0, 4), ha="center", fontsize=BAR_FS, fontweight="bold", color="#5e2a7e")

    ax.set_xticks(xs_cpu + [x_mem])
    ax.set_xticklabels([XLAB[v] for v in VICTIMS] + ["Memory\n(RSS)"], fontsize=TICK_FS)
    ax.set_ylabel("Footprint  (% of node)", fontsize=LBL_FS)
    ax.set_ylim(0, 0.35); ax.set_xlim(-0.6, 4.3); ax.yaxis.set_major_formatter(PCT)
    ax.tick_params(axis="y", labelsize=TICK_FS)
    ax.axvline(2.8, color="#9e9e9e", ls=":", lw=1.0, zorder=1)   # CPU | Memory 구분
    ax.axhline(0.15, color="#c62828", lw=1.2, ls="--", zorder=2)
    ax.text(0.05, 0.155, "0.15% of node", color="#c62828", fontsize=REF_FS, ha="left", va="bottom")
    ax.grid(axis="y", ls=":", alpha=0.4, zorder=0)
    ax.legend(fontsize=11, framealpha=0.95, loc="upper right")
    fig.tight_layout()
    os.makedirs(args.out, exist_ok=True)
    p = os.path.join(args.out, f"overhead_resource.{args.format}")
    fig.savefig(p, dpi=200, bbox_inches="tight")
    print(f"Saved: {p}")
    for v in VICTIMS:
        print(f"  {v:>8}: CPU {np.mean(d[v]['cpu_node']):.3f}% of node, RSS {np.mean(d[v]['mem_node']):.3f}% of node")


if __name__ == "__main__":
    main()
