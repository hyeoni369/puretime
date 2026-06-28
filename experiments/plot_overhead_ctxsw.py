#!/usr/bin/env python3
"""Experiment 5 (overhead) — fig3: PureTime time overhead vs kernel-event rate.

오버헤드 측정의 근본 난점: PureTime의 시간 오버헤드는 <1%로, victim을 부하와 같은 코어에서
경쟁시키면 CPU 몫 변동(±15~33%)이 그 신호를 묻고, 경쟁을 없애면 추적할 이벤트가 사라져
오버헤드가 0이 된다. 해결책(ctxsw-bench): 부모-자식 pipe 핑퐁으로 sched_switch를 *결정적으로*
생성하되 같은 코어에서 협력적으로 번갈아 실행 → CPU 경쟁(노이즈) 없이 이벤트율만 제어.

PureTime 오버헤드는 추적하는 이벤트 수에 비례하므로, 이벤트율(switch/s)을 sweep하면 오버헤드가
선형으로 증가하는 깨끗한 양수 곡선이 나온다. 현실적 서버리스 함수의 이벤트율(수천~수만 switch/s)
에서는 오버헤드가 낮고(<수%), 극단적 율에서도 곡선상 예측 가능 — "PureTime 오버헤드는 이벤트율에
선형 비례하며, 측정 가능 구간 전체에서 양수(노이즈 없음)".

Usage: python3 plot_overhead_ctxsw.py --data experiments/data/overhead_ctxsw/results.csv \
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
    # 이벤트율 레벨별 집계 (compute가 손잡이, switch_rate가 실측 x축)
    levels = []
    for compute, sub in df.groupby("compute"):
        ov = sub["overhead_pct"].values
        rate = np.median(sub["switch_rate"].values)
        m = float(np.mean(ov))
        ci = 1.96 * np.std(ov, ddof=1) / np.sqrt(len(ov)) if len(ov) > 1 else 0
        levels.append(dict(rate=rate, mean=m, ci=ci,
                           lo=float(np.percentile(ov, 25)), hi=float(np.percentile(ov, 75)),
                           n=len(ov)))
    levels.sort(key=lambda d: d["rate"])
    rates = np.array([L["rate"] for L in levels])
    means = np.array([L["mean"] for L in levels])
    cis = np.array([L["ci"] for L in levels])

    fig, ax = plt.subplots(figsize=(5.6, 3.1))

    ax.axhline(0, color="#999", lw=0.8, ls="-", zorder=0)
    # 오버헤드 점 + 95% CI 에러바
    ax.errorbar(rates / 1000, means, yerr=cis, fmt="o-", color="#1565c0",
                ms=6.5, lw=2.0, capsize=4, capthick=1.4, ecolor="#1565c0",
                label="PureTime overhead (mean ± 95% CI)")
    # 선형 추세 (원점 통과 가까운 비례 관계 강조)
    if len(rates) >= 2:
        coef = np.polyfit(rates, means, 1)
        xs = np.linspace(0, rates.max() * 1.05, 50)
        ax.plot(xs / 1000, np.polyval(coef, xs), "--", color="#90a4ae", lw=1.4,
                zorder=1, label=f"linear fit ({coef[0]*1e6:.2f}%/M-switch)")

    # 메인엔 최댓값(끝점)만 라벨 — 중간 점은 곡선/추세선이, 저이벤트율은 inset이 설명하므로 깔끔하게
    Lmax = levels[-1]
    ax.annotate(f"{Lmax['mean']:+.1f}%", (Lmax["rate"] / 1000, Lmax["mean"]),
                textcoords="offset points", xytext=(-6, 9), fontsize=11.5,
                fontweight="bold", color="#0d47a1", ha="right")

    ax.set_xlabel("Kernel-event rate (×1000 context-switches / sec)", fontsize=12.5)
    ax.set_ylabel("Time overhead (%)", fontsize=12.5)
    ax.tick_params(labelsize=11)
    ax.legend(fontsize=11.5, framealpha=0.9, loc="upper left")
    ax.set_ylim(bottom=min(-1, means.min() - 2))

    # 하단(<1.5%) 구간을 inset으로 확대 — 현실적 함수 이벤트율에서 오버헤드가 1.5% 미만임을 강조
    low = [L for L in levels if L["mean"] < 2.5]
    if len(low) >= 2:
        axins = ax.inset_axes([0.52, 0.11, 0.46, 0.45])
        lr = np.array([L["rate"] for L in low]); lm = np.array([L["mean"] for L in low])
        lc = np.array([L["ci"] for L in low])
        axins.axhline(0, color="#999", lw=0.7)
        axins.axhline(1.5, color="#c62828", lw=1.2, ls="--")
        axins.text(lr.min() / 1000, 1.5, " 1.5%", color="#c62828", fontsize=9, va="bottom", fontweight="bold")
        axins.errorbar(lr / 1000, lm, yerr=lc, fmt="o-", color="#1565c0", ms=5.5, lw=1.6,
                       capsize=3, capthick=1.2, ecolor="#1565c0")
        for L in low:
            axins.annotate(f"{L['mean']:+.2f}%", (L["rate"] / 1000, L["mean"]),
                           textcoords="offset points", xytext=(5, -12), fontsize=9, color="#0d47a1")
        axins.set_xlim(0, max(lr) / 1000 * 1.15)
        axins.set_ylim(-0.6, 2.6)
        axins.tick_params(labelsize=9)
        axins.set_title("low event rates (realistic functions)", fontsize=9.5)
        ax.indicate_inset_zoom(axins, edgecolor="#90a4ae", lw=1.0)

    fig.tight_layout()
    os.makedirs(args.out, exist_ok=True)
    path = os.path.join(args.out, f"overhead_eventrate.{args.format}")
    # [disabled] overhead_eventrate — sigconf 미참조(design fig3였으나 논문에서 제외)
    # fig.savefig(path, dpi=200, bbox_inches="tight")
    # print(f"Saved: {path}")
    print(f"{'switch/s':>10} {'overhead':>10} {'95%CI':>14} {'n':>3}")
    for L in levels:
        print(f"{L['rate']:>10.0f} {L['mean']:+9.2f}% [{L['mean']-L['ci']:+.2f},{L['mean']+L['ci']:+.2f}] {L['n']:>3}")


if __name__ == "__main__":
    main()
