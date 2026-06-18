#!/usr/bin/env python3
"""fig3-2 (overhead) — PureTime 시간 오버헤드 vs 노드 부하(co-tenant 이벤트율).

기존 fig3(plot_overhead_ctxsw.py)는 victim '자기 이벤트율'만 sweep(노드 조용)해서, "함수가
한가하면 오버헤드 낮다"로만 읽힌다 — PureTime이 *필요한* 바쁜 멀티테넌트 노드를 안 보여줌.
이 figure는 victim 율을 현실값 하나로 고정하고 배경 co-tenant 부하를 0→N개로 sweep해 노드
전체 이벤트율을 올리며 victim의 지연 오버헤드가 어떻게 변하나를 본다.

코드 사실(분석): ring buffer가 전 CPU 공유 단일 맵(스핀락 1개, puretime.bpf.c:21-24)이라
노드가 바쁘면 victim 코어 reserve도 더 기다리는 결합 항이 *존재*하지만 크기는 측정해야 안다.
결과: 노드 33K→619K/s에도 victim median 오버헤드는 baseline 근처 flat, drop=0 → 그 결합 항이
실측상 무시할 수준. (측정 노이즈가 신호보다 커 평균 대신 median+IQR, 개별 점도 함께 표시.)
dropped>0 레벨은 PureTime이 못 버티는 한계 → 빨간 테두리.

Usage: python3 plot_overhead_nodeload.py --data experiments/data/overhead_nodeload/results.csv \
            --out experiments/figures [--format pdf]
"""
import argparse
import os
import numpy as np
import pandas as pd
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", required=True)
    ap.add_argument("--out", default="experiments/figures")
    ap.add_argument("--format", default="pdf")
    args = ap.parse_args()

    df = pd.read_csv(args.data)
    levels = []
    for bg, sub in df.groupby("bg_count"):
        ov = sub["overhead_pct"].values
        node = float(np.median(sub["node_ctxt_per_sec"].values))
        med = float(np.median(ov))
        lo = float(np.percentile(ov, 25))
        hi = float(np.percentile(ov, 75))
        drop = float(sub["dropped_events"].fillna(0).max()) if "dropped_events" in sub else 0
        levels.append(dict(bg=int(bg), node=node, med=med, lo=lo, hi=hi, ov=ov, drop=drop, n=len(ov)))
    levels.sort(key=lambda d: d["node"])
    node = np.array([L["node"] for L in levels]) / 1000.0
    med = np.array([L["med"] for L in levels])
    lo = np.array([L["lo"] for L in levels])
    hi = np.array([L["hi"] for L in levels])

    YTOP = 14.0
    fig, ax = plt.subplots(figsize=(5.6, 3.1))
    ax.axhline(0, color="#999", lw=0.7, zorder=0)
    base = med[0]
    ax.axhline(base, color="#90a4ae", lw=1.2, ls="--", zorder=1,
               label=f"victim-only baseline ({base:.1f}%)")
    # 개별 측정점 (노이즈 투명하게)
    for L, x in zip(levels, node):
        ax.scatter([x] * len(L["ov"]), L["ov"], s=14, color="#bbdefb", zorder=2, edgecolors="none")
    # median + IQR
    ax.errorbar(node, med, yerr=[med - lo, hi - med], fmt="o-", color="#1565c0", ms=6.5, lw=1.9,
                capsize=4, capthick=1.3, ecolor="#1565c0", zorder=4, label="median ± IQR")
    drew = False
    for L, x, y in zip(levels, node, med):
        if L["drop"] > 0:
            ax.scatter([x], [y], s=160, facecolors="none", edgecolors="#c62828", lw=2.0, zorder=5,
                       label=("drop > 0 (PureTime limit)" if not drew else None))
            drew = True
    for L, x, y in zip(levels, node, med):
        ax.annotate(f"{y:+.1f}%", (x, y), textcoords="offset points", xytext=(0, 13),
                    fontsize=9.5, ha="center", color="#0d47a1", fontweight="bold",
                    bbox=dict(boxstyle="round,pad=0.15", fc="white", ec="none", alpha=0.9))

    ax.set_ylim(-5, YTOP)
    n_clip = int(sum(int((L["ov"] > YTOP).sum()) for L in levels))
    if n_clip:
        ax.text(0.98, 0.03, f"({n_clip} outlier > {YTOP:.0f}% clipped)", transform=ax.transAxes,
                fontsize=7.5, ha="right", va="bottom", color="#888", style="italic")
    ax.set_xlabel("Node-wide event rate  (×1000 context-switches / sec)", fontsize=12)
    ax.set_ylabel("victim time overhead (%)", fontsize=12)
    ax.tick_params(labelsize=10.5)
    ax.legend(fontsize=9.5, framealpha=0.9, loc="upper right")
    fig.tight_layout()

    os.makedirs(args.out, exist_ok=True)
    p = os.path.join(args.out, f"overhead_nodeload.{args.format}")
    fig.savefig(p, dpi=200, bbox_inches="tight")
    print(f"Saved: {p}")
    print(f"{'bg':>3} {'node/s':>10} {'median':>8} {'IQR':>16} {'drop':>5} {'n':>3}")
    for L in levels:
        print(f"{L['bg']:>3} {L['node']:>10.0f} {L['med']:+7.2f}% [{L['lo']:+.1f},{L['hi']:+.1f}] {L['drop']:>5.0f} {L['n']:>3}")


if __name__ == "__main__":
    main()
