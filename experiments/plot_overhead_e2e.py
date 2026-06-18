#!/usr/bin/env python3
"""fig overhead-e2e: PureTime ON/OFF 실제 victim e2e 실행시간 비교.

overhead=(with-without)/without 의 *비율*은 오버헤드가 측정 노이즈보다 작아 부호가 음/양 섞인다
(HPDC 리뷰어가 '음수 오버헤드'를 지적). 그 방향성 표현을 없애기 위해, overhead%를 계산하지 않고
with/without 실행시간을 직접 비교한다: victim별 PureTime OFF/ON 실행시간(OFF=100%로 정규화) +
95% CI + paired t-test. 두 시간이 통계적으로 구별되지 않으면(CI 겹침, p>0.05) 오버헤드는 무시
가능 — 음수라는 단어 없이 "두 시간이 같다"로 정직하게 입증. (절댓값은 노이즈를 양수로 둔갑시켜 금지.)

Usage: python3 plot_overhead_e2e.py --data experiments/data/overhead_e2e/results.csv \
            --out experiments/figures [--format pdf]
"""
import argparse
import os
import numpy as np
import pandas as pd
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
try:
    from scipy import stats
    HAVE_SCIPY = True
except ImportError:
    HAVE_SCIPY = False

VLABEL = {"cpu": "CPU\n(float)", "block": "Block I/O\n(compression)", "net": "Network\n(uploader)"}
ORDER = ["cpu", "block", "net"]


def ci95(a):
    a = np.asarray(a, float)
    n = len(a)
    return 1.96 * a.std(ddof=1) / np.sqrt(n) if n > 1 else 0.0


def paired_p(w, wo):
    """paired t-test p-value (scipy 없으면 정규근사)."""
    if HAVE_SCIPY:
        return float(stats.ttest_rel(np.asarray(w, float), np.asarray(wo, float)).pvalue)
    d = np.asarray(w, float) - np.asarray(wo, float)
    n = len(d)
    if n < 2 or d.std(ddof=1) == 0:
        return float("nan")
    t = d.mean() / (d.std(ddof=1) / np.sqrt(n))
    from math import erf, sqrt
    return float(2 * (1 - 0.5 * (1 + erf(abs(t) / sqrt(2)))))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", required=True)
    ap.add_argument("--out", default="experiments/figures")
    ap.add_argument("--format", default="pdf")
    args = ap.parse_args()

    df = pd.read_csv(args.data)
    df["victim"] = df["victim"].astype(str).str.strip('"')
    vics = [v for v in ORDER if v in df["victim"].unique()]

    fig, ax = plt.subplots(figsize=(5.4, 3.2))
    x = np.arange(len(vics))
    w = 0.34
    for i, v in enumerate(vics):
        sub = df[df["victim"] == v]
        wo = sub["without_ms"].values
        wi = sub["with_ms"].values
        base = wo.mean()
        wo_n = wo / base * 100
        wi_n = wi / base * 100
        ax.bar(x[i] - w / 2, [wo_n.mean()], w, color="#9ecae1", edgecolor="black", lw=0.6, zorder=3,
               yerr=ci95(wo_n), capsize=4, error_kw=dict(lw=1.2),
               label="PureTime OFF" if i == 0 else None)
        ax.bar(x[i] + w / 2, [wi_n.mean()], w, color="#3182bd", edgecolor="black", lw=0.6, zorder=3,
               yerr=ci95(wi_n), capsize=4, error_kw=dict(lw=1.2),
               label="PureTime ON" if i == 0 else None)
        # p-value 라벨은 figure에서 생략(본문/캡션에 paired t-test로 보고). 콘솔 요약에는 아래에 출력.

    ax.axhline(100, color="#333", lw=1.0, ls="--", zorder=1)
    ax.set_xticks(x)
    ax.set_xticklabels([VLABEL[v] for v in vics], fontsize=10.5)
    ax.set_ylabel("Execution time\n(% of PureTime-OFF)", fontsize=11.5)
    ax.tick_params(axis="y", labelsize=10)
    ax.set_ylim(70, 130)   # 100%가 중앙, ON/OFF 차이는 60%p 범위 안에서 미미하게
    ax.legend(fontsize=9.5, loc="upper center", ncol=2, framealpha=0.92)
    fig.tight_layout()

    os.makedirs(args.out, exist_ok=True)
    p_out = os.path.join(args.out, f"fig_overhead_e2e.{args.format}")
    fig.savefig(p_out, dpi=200, bbox_inches="tight")
    print(f"Saved: {p_out}  (scipy={HAVE_SCIPY})")
    print(f"{'victim':>6} {'OFF(ms)':>9} {'ON(ms)':>9} {'ON/OFF':>7} {'paired-p':>9} {'verdict':>10}")
    for v in vics:
        sub = df[df["victim"] == v]
        wo = sub["without_ms"].values
        wi = sub["with_ms"].values
        pv = paired_p(wi, wo)
        verdict = "n.s." if (np.isnan(pv) or pv > 0.05) else "differs"
        print(f"{v:>6} {wo.mean():>9.1f} {wi.mean():>9.1f} {wi.mean()/wo.mean():>7.4f} {pv:>9.3f} {verdict:>10}")


if __name__ == "__main__":
    main()
