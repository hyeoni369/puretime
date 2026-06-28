#!/usr/bin/env python3
"""정확도 figure (정규화 단일 plot) — 실제 서버리스 함수 victim 7종.

각 victim의 solo makespan을 1로 정규화 → Baseline(1) / Noisy / PureTime grouped bar를
한 plot에 (페이지 상단 full-width). removal% = pairwise efficiency(각 noisy를 같은 iteration의
solo로 나눠 HDD drift 보정; CPU/Net은 aggregate와 거의 동일).

데이터: experiments/data/accuracy_7victim/<victim>.csv (CPU4 + net2, K=50 본실험) +
        experiments/data/accuracy_K50/results.csv 의 block_io (compression store, filled-disk valid).
victim별 solo/noisy container_count는 (cc) 열 참조.
"""
import os
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

D = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'data')
V = [
    (f'{D}/accuracy_7victim/cpu_float.csv', 'cpu', 3, 'float_op\n(FunctionBench)'),
    (f'{D}/accuracy_7victim/cpu_factors.csv', 'cpu', 3, 'factors\n(FaaSDom)'),
    (f'{D}/accuracy_7victim/cpu_sequential.csv', 'cpu', 3, 'sequential\n(ServerlessBench)'),
    (f'{D}/accuracy_7victim/cpu_aes.csv', 'cpu', 3, 'aes\n(vSwarm)'),
    (f'{D}/accuracy_7victim/net_uploader.csv', 'network', 4, 'uploader\n(SeBS)'),
    (f'{D}/accuracy_7victim/net_s3.csv', 'network', 4, 's3-dl-ul\n(FunctionBench)'),
    (f'{D}/accuracy_K50/results.csv', 'block_io', 4, 'compression\n(SeBS)'),
]


def stats(path, rt, cc):
    df = pd.read_csv(path)
    df['resource_type'] = df.resource_type.astype(str).str.strip('"')
    r = df[df.resource_type == rt]
    bl = r[r.container_count == 0]
    noisy = r[r.container_count == cc]
    se = bl.t_e2e_ms.median()
    ce = noisy.t_e2e_ms.median()
    cp = noisy.t_puretime_ms.median()
    sbi = bl.groupby('iteration').t_e2e_ms.median()
    pp = [(x.t_e2e_ms - x.t_puretime_ms) / (x.t_e2e_ms - sbi.loc[x.iteration]) * 100
          for _, x in noisy.iterrows()
          if x.iteration in sbi.index and x.t_e2e_ms > sbi.loc[x.iteration]]
    eff = np.median(pp) if pp else float('nan')
    return ce / se, cp / se, eff


def main():
    labels = [v[3] for v in V]
    noisy_n, pt_n, effs = [], [], []
    for path, rt, cc, _ in V:
        nn, pn, e = stats(path, rt, cc)
        noisy_n.append(nn); pt_n.append(pn); effs.append(e)

    x = np.arange(len(V)); w = 0.28
    c_bl, c_no, c_pt = '#9aa0a6', '#d9534f', '#3a7ca5'
    fig, ax = plt.subplots(figsize=(17, 3.5))
    ax.bar(x - w, [1] * len(V), w, label='Baseline (solo)', color=c_bl, edgecolor='white', linewidth=0.5)
    ax.bar(x,     noisy_n,       w, label='Noisy',          color=c_no, edgecolor='white', linewidth=0.5)
    ax.bar(x + w, pt_n,          w, label='PureTime',       color=c_pt, edgecolor='white', linewidth=0.5)
    for i in range(len(V)):
        ax.annotate(f"{effs[i]:.0f}%", (x[i] + w, pt_n[i]), xytext=(0, 4),
                    textcoords='offset points', ha='center', fontsize=14, color=c_pt, fontweight='bold')
    ax.axhline(1, ls='--', color='#555', lw=1.4, alpha=0.7)
    ax.set_xticks(x)
    ax.set_xticklabels(labels, fontsize=14)
    ax.set_ylabel('Normalized\nmakespan (solo=1)', fontsize=15)
    ax.set_ylim(0, max(noisy_n) * 1.12)
    ax.tick_params(axis='y', labelsize=13)
    ax.legend(loc='upper left', fontsize=14, ncol=3, frameon=True, columnspacing=1.0, handletextpad=0.5)
    ax.spines[['top', 'right']].set_visible(False)
    plt.tight_layout()
    out = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'figures', 'accuracy_normalized.pdf')
    plt.savefig(out, bbox_inches='tight')
    print('saved:', out)
    for l, nn, pn, e in zip(labels, noisy_n, pt_n, effs):
        print(f"{l.split(chr(10))[0]:14} noisy={nn:.2f}x  pt={pn:.2f}x  removed={e:.0f}%")


if __name__ == "__main__":
    main()
