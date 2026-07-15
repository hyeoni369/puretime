#!/usr/bin/env python3
"""실험 1 (R-04): Attribution ablation — 귀속(누가 대기를 일으켰나)이 필요한 이유.

리뷰어 의심: "self-wait이 없다면 귀속 없이 전체 큐 대기를 몽땅 빼는 단순 방법(Blocked-Samples식)도
같은 결과를 낼 것". 이를 self-queueing이 실재하는 조건에서 직접 비교해 반박한다.

victim (self-queueing이 있는 현실적 조건):
  - float-mt   : FunctionBench float_operation의 2-worker 변형(멀티스레드 런타임 시나리오),
                 같은 코어 → sibling 간 self-wait. 노이즈 = stress-ng 3 workers.
  - uploader   : SeBS 8MB (단일 전송 — self-queueing 거의 없음 = 두 방법 일치, 정직한 대조군).
                 노이즈 = iperf3 -P4.
  - compression: SeBS store (자기 I/O 요청 다수 큐잉). 노이즈 = fio 1 job.

Figure A (attribution_ablation): noisy 4-bar — ①solo=1 ②noisy wall ③전체-대기 차감(no attribution)
  ④PureTime(attribution). no-attr은 self-wait까지 빼서 solo *아래*로 떨어지고(과소 추정 = 불가능),
  PureTime만 solo를 복원한다.
Figure B (attribution_solo_check): solo(노이즈 0, 정답=1.0) — no-attr은 노이즈가 없어도
  self-queueing을 제거해 0.02~0.4×로 오보고; PureTime은 1.00.

데이터: experiments/data/attribution/<victim>{,_noattr}.csv (exp_accuracy_by_type.sh 산출 페어).
Usage: python3 plot_r04_attribution.py [--out figures]
"""
import argparse
import os
import numpy as np
import pandas as pd
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt

D = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'data', 'attribution')

# (base name, resource_type, noisy cc, label) — Figure A(noisy 4-bar)용, accuracy 7 victim과 정렬
# CPU 4종은 2-worker 변형(멀티스레드 런타임 시나리오 → self-wait 존재); net 2종은 단일 전송
# (self-wait≈0 → 두 방법 일치 = 정직한 대조군); block은 fio 1 job.
V_NOISY = [
    ('floatmt', 'cpu', 3, 'float_op\n(FunctionBench)'),
    ('factorsmt', 'cpu', 3, 'factors\n(FaaSDom)'),
    ('sequentialmt', 'cpu', 3, 'sequential\n(ServerlessBench)'),
    ('aesmt', 'cpu', 3, 'aes\n(vSwarm)'),
    ('uploader8', 'network', 4, 'uploader\n(SeBS)'),
    ('s3_8', 'network', 4, 's3-dl-ul\n(FunctionBench)'),
    ('blk_fio1', 'block_io', 1, 'compression\n(SeBS)'),
]
# Figure B(solo-check)용 — (base, resource_type, label)
V_SOLO = [
    ('floatmt', 'cpu', 'float-mt (2-worker)\nFunctionBench'),
    ('up64', 'network', 'uploader (64 MB)\nSeBS'),
    ('blk_fio1', 'block_io', 'compression (store)\nSeBS'),
]


def load_pair(base, rt):
    a = pd.read_csv(f'{D}/{base}.csv')
    n = pd.read_csv(f'{D}/{base}_noattr.csv')
    for x in (a, n):
        x['resource_type'] = x.resource_type.astype(str).str.strip('"')
    m = a.merge(n, on=['cgroup_id', 'resource_type', 'container_count', 'iteration'],
                suffixes=('_a', '_n'))
    return m[m.resource_type == rt]


def noisy_stats(base, rt, cc):
    m = load_pair(base, rt)
    sbi = m[m.container_count == 0].groupby('iteration').t_e2e_ms_a.median()
    g = m[m.container_count == cc]
    wl, pt, na = [], [], []
    for _, x in g.iterrows():
        if x.iteration in sbi.index and sbi.loc[x.iteration] > 0:
            s = sbi.loc[x.iteration]
            wl.append(x.t_e2e_ms_a / s); pt.append(x.t_puretime_ms_a / s); na.append(x.t_puretime_ms_n / s)
    md = lambda z: float(np.median(z)) if z else float('nan')
    return md(wl), md(na), md(pt)


def solo_stats(base, rt):
    m = load_pair(base, rt)
    s = m[m.container_count == 0]
    return (float((s.t_puretime_ms_a / s.t_e2e_ms_a).median()),
            float((s.t_puretime_ms_n / s.t_e2e_ms_a).median()), len(s))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--out', default=os.path.join(os.path.dirname(os.path.abspath(__file__)), 'figures'))
    ap.add_argument('--format', default='pdf')
    args = ap.parse_args()
    os.makedirs(args.out, exist_ok=True)
    c_solo, c_noisy, c_all, c_pt = '#9aa0a6', '#d9534f', '#e8a33d', '#3a7ca5'

    # ---- Figure A: noisy 4-bar ----
    labels, wls, nas, pts = [], [], [], []
    for base, rt, cc, lab in V_NOISY:
        wl, na, pt = noisy_stats(base, rt, cc)
        labels.append(lab); wls.append(wl); nas.append(na); pts.append(pt)

    x = np.arange(len(labels)); w = 0.23
    figA, axA = plt.subplots(figsize=(17, 3.5))
    ymax = max(wls) * 1.15
    axA.axhspan(0, 1.0, color='#fce4e4', alpha=0.55, zorder=0)
    # (아래 1.0 미만 = 참값 과소추정 영역: 연분홍 밴드 + 점선으로 표시, 문구는 캡션에)
    axA.bar(x - 1.5 * w, [1] * len(labels), w, label='Solo (ground truth)', color=c_solo, edgecolor='white', lw=0.5, zorder=3)
    axA.bar(x - 0.5 * w, wls, w, label='Noisy (wall)', color=c_noisy, edgecolor='white', lw=0.5, zorder=3)
    axA.bar(x + 0.5 * w, nas, w, label='All-wait subtracted', color=c_all, edgecolor='white', lw=0.5, zorder=3)
    axA.bar(x + 1.5 * w, pts, w, label='PureTime', color=c_pt, edgecolor='white', lw=0.5, zorder=3)
    for i in range(len(labels)):
        # tie(값 같음)면 라벨을 좌우로 살짝 벌려 겹침 방지
        dodge = 4 if abs(nas[i] - pts[i]) < 0.05 else 0
        axA.annotate(f'{nas[i]:.2f}×', (x[i] + 0.5 * w, nas[i]), xytext=(-dodge, 3), textcoords='offset points',
                     ha='center', fontsize=10.5, color='#b06a00', fontweight='bold')
        axA.annotate(f'{pts[i]:.2f}×', (x[i] + 1.5 * w, pts[i]), xytext=(dodge, 3), textcoords='offset points',
                     ha='center', fontsize=10.5, color='#245a7d', fontweight='bold')
    axA.axhline(1, ls='--', color='#555', lw=1.3, alpha=0.8, zorder=2)
    axA.set_xticks(x); axA.set_xticklabels(labels, fontsize=12.5)
    axA.set_ylabel('Normalized\nmakespan (solo=1)', fontsize=14)
    axA.set_ylim(0, ymax)
    axA.tick_params(axis='y', labelsize=12)
    axA.legend(loc='upper left', fontsize=14, ncol=2, framealpha=0.95, columnspacing=1.0, handletextpad=0.5)
    axA.spines[['top', 'right']].set_visible(False)
    figA.tight_layout()
    pa = os.path.join(args.out, f'attribution_ablation.{args.format}')
    figA.savefig(pa, bbox_inches='tight'); print('saved:', pa)
    for lab, wl, na, pt in zip(labels, wls, nas, pts):
        print(f"  {lab.split(chr(10))[0]:24} wall={wl:.2f}x  noattr={na:.2f}x  PT={pt:.2f}x")

    # ---- Figure B: solo sanity check ----
    labels2, pts2, nas2 = [], [], []
    for base, rt, lab in V_SOLO:
        pt, na, n = solo_stats(base, rt)
        labels2.append(lab); pts2.append(pt); nas2.append(na)
    x2 = np.arange(len(labels2)); w2 = 0.32
    figB, axB = plt.subplots(figsize=(6.4, 3.2))
    axB.bar(x2 - w2 / 2, pts2, w2, label='PureTime (attribution)', color=c_pt, edgecolor='white', lw=0.5)
    axB.bar(x2 + w2 / 2, nas2, w2, label='All-wait subtracted (no attribution)', color=c_all, edgecolor='white', lw=0.5)
    axB.axhline(1.0, ls='--', color='#555', lw=1.3, alpha=0.85)
    axB.annotate('correct = 1.0 (zero noise → remove nothing)', (0.5, 1.115), xycoords=('axes fraction', 'data'),
                 ha='center', fontsize=8.5, color='#444')
    for i in range(len(labels2)):
        axB.annotate(f'{pts2[i]:.2f}', (x2[i] - w2 / 2, pts2[i]), xytext=(0, 3), textcoords='offset points',
                     ha='center', fontsize=9.5, color='#245a7d', fontweight='bold')
        axB.annotate(f'{nas2[i]:.2f}', (x2[i] + w2 / 2, nas2[i]), xytext=(0, 3), textcoords='offset points',
                     ha='center', fontsize=9.5, color='#b06a00', fontweight='bold')
    axB.set_xticks(x2); axB.set_xticklabels(labels2, fontsize=9.5)
    axB.set_ylabel('Reported noise-free time\n/ wall  (solo run)', fontsize=10.5)
    axB.set_ylim(0, 1.28)
    axB.tick_params(axis='y', labelsize=9.5)
    axB.legend(loc='lower left', fontsize=9, framealpha=0.95)
    axB.spines[['top', 'right']].set_visible(False)
    figB.tight_layout()
    pb = os.path.join(args.out, f'attribution_solo_check.{args.format}')
    figB.savefig(pb, bbox_inches='tight'); print('saved:', pb)
    for lab, pt, na in zip(labels2, pts2, nas2):
        print(f"  {lab.split(chr(10))[0]:24} PT={pt:.3f}  noattr={na:.3f}")


if __name__ == '__main__':
    main()
