#!/usr/bin/env python3
"""
PureTime Experiment Results Visualization

모든 실험 결과를 Grouped Bar Chart로 시각화
- 페이지를 최대한 차지하도록 설계
- 결과가 좋아보이도록 시각적 강조

Usage:
    python3 plot_results.py <experiment_type> <results_file> [--output <output_dir>]
    
    experiment_type: by_type | by_intensity | kpa
"""

import argparse
import csv
import json
import matplotlib.pyplot as plt
import matplotlib.patches as mpatches
import numpy as np
from collections import defaultdict
import statistics
import os


# =============================================================================
# Style Configuration (논문용 스타일)
# =============================================================================

plt.rcParams.update({
    'font.family': 'serif',
    'font.serif': ['Times New Roman', 'DejaVu Serif'],
    'font.size': 11,
    'axes.labelsize': 12,
    'axes.titlesize': 13,
    'legend.fontsize': 10,
    'xtick.labelsize': 10,
    'ytick.labelsize': 10,
    'figure.dpi': 150,
    'savefig.dpi': 300,
    'savefig.bbox': 'tight',
})

# 색상 팔레트 (논문에 적합한 색상)
COLORS = {
    'isolated': '#808080',      # Gray - baseline
    'contention': '#D62728',    # Red - with noise
    'puretime': '#2CA02C',      # Green - PureTime (noise removed)
    'efficiency': '#1F77B4',    # Blue - efficiency metric
}


# =============================================================================
# Data Loading
# =============================================================================

def load_csv(filepath):
    """CSV 파일 로드"""
    results = []
    with open(filepath, 'r') as f:
        reader = csv.DictReader(f)
        for row in reader:
            results.append(row)
    return results


def load_json(filepath):
    """JSON 파일 로드"""
    with open(filepath, 'r') as f:
        return json.load(f)


# =============================================================================
# Noise Type Accuracy Visualization
# =============================================================================

def plot_accuracy_by_type(results_file, output_dir):
    """
    노이즈 유형별 정확도 Grouped Bar Chart
    - X축: 노이즈 유형 (CPU, Network, Block I/O)
    - Y축: 실행 시간 (ms)
    - 3개 막대: T_isolated (baseline), T_contention, T_puretime
    """
    results = load_csv(results_file)
    
    # Group by noise type
    by_type = defaultdict(lambda: {'contention': [], 'puretime': []})
    baselines = {}
    
    for r in results:
        noise_type = r['noise_type']
        count = int(r['container_count'])
        
        if count == 1:
            # Baseline (Solo)
            if noise_type not in baselines:
                baselines[noise_type] = []
            baselines[noise_type].append(float(r['t_contention_ms']))
        else:
            by_type[noise_type]['contention'].append(float(r['t_contention_ms']))
            by_type[noise_type]['puretime'].append(float(r['t_puretime_ms']))
    
    # Calculate averages and stdev
    noise_types = ['cpu', 'network', 'block_io']
    type_labels = ['CPU', 'Network', 'Block I/O']
    
    t_isolated = []
    t_contention = []
    t_puretime = []
    t_contention_err = []
    t_puretime_err = []
    
    for nt in noise_types:
        if nt in baselines:
            t_isolated.append(statistics.mean(baselines[nt]))
        else:
            t_isolated.append(0)
        
        if nt in by_type:
            t_contention.append(statistics.mean(by_type[nt]['contention']))
            t_puretime.append(statistics.mean(by_type[nt]['puretime']))
            t_contention_err.append(statistics.stdev(by_type[nt]['contention']) if len(by_type[nt]['contention']) > 1 else 0)
            t_puretime_err.append(statistics.stdev(by_type[nt]['puretime']) if len(by_type[nt]['puretime']) > 1 else 0)
        else:
            t_contention.append(0)
            t_puretime.append(0)
            t_contention_err.append(0)
            t_puretime_err.append(0)
    
    # Create figure (넓게 설정하여 페이지 차지)
    fig, ax = plt.subplots(figsize=(10, 6))
    
    x = np.arange(len(noise_types))
    width = 0.25
    
    # Grouped bars
    bars1 = ax.bar(x - width, t_isolated, width, label='$T_{isolated}$ (Solo baseline)', 
                   color=COLORS['isolated'], edgecolor='black', linewidth=0.5)
    bars2 = ax.bar(x, t_contention, width, yerr=t_contention_err, capsize=3,
                   label='$T_{contention}$ (With noise)', 
                   color=COLORS['contention'], edgecolor='black', linewidth=0.5)
    bars3 = ax.bar(x + width, t_puretime, width, yerr=t_puretime_err, capsize=3,
                   label='$T_{puretime}$ (Noise removed)', 
                   color=COLORS['puretime'], edgecolor='black', linewidth=0.5)
    
    # Calculate and annotate efficiency
    for i, (iso, cont, pure) in enumerate(zip(t_isolated, t_contention, t_puretime)):
        if cont > iso and cont > 0:
            gt_noise = cont - iso
            removed = cont - pure
            efficiency = (removed / gt_noise) * 100
            
            # Efficiency 화살표와 라벨
            ax.annotate(f'{efficiency:.1f}%', 
                       xy=(i + width, pure), 
                       xytext=(i + width + 0.15, pure + (cont - pure) * 0.3),
                       fontsize=9, fontweight='bold', color=COLORS['efficiency'],
                       arrowprops=dict(arrowstyle='->', color=COLORS['efficiency'], lw=1.5))
    
    ax.set_ylabel('Execution Time (ms)')
    ax.set_xlabel('Contention Type')
    ax.set_xticks(x)
    ax.set_xticklabels(type_labels)
    ax.legend(loc='upper right')
    ax.set_ylim(bottom=0)
    
    # Grid for readability
    ax.yaxis.grid(True, linestyle='--', alpha=0.7)
    ax.set_axisbelow(True)
    
    plt.tight_layout()
    
    output_path = os.path.join(output_dir, 'accuracy_by_type.pdf')
    plt.savefig(output_path)
    plt.savefig(output_path.replace('.pdf', '.png'))
    print(f"Saved: {output_path}")
    
    return fig


def plot_accuracy_by_intensity(results_file, output_dir):
    """
    노이즈 강도별 정확도 Grouped Bar Chart
    - X축: 컨테이너 수 (1, 2, 4, 8, 16)
    - Y축: 실행 시간 (ms)
    - 3개 막대: T_isolated (baseline), T_contention, T_puretime
    """
    results = load_csv(results_file)
    
    # Group by container count
    by_count = defaultdict(lambda: {'contention': [], 'puretime': []})
    
    for r in results:
        count = int(r['container_count'])
        by_count[count]['contention'].append(float(r['t_contention_ms']))
        by_count[count]['puretime'].append(float(r['t_puretime_ms']))
    
    # Sort by container count
    counts = sorted(by_count.keys())
    
    # Baseline is count=1
    baseline = statistics.mean(by_count[1]['contention']) if 1 in by_count else 0
    
    t_isolated = [baseline] * len(counts)
    t_contention = [statistics.mean(by_count[c]['contention']) for c in counts]
    t_puretime = [statistics.mean(by_count[c]['puretime']) for c in counts]
    t_contention_err = [statistics.stdev(by_count[c]['contention']) if len(by_count[c]['contention']) > 1 else 0 for c in counts]
    t_puretime_err = [statistics.stdev(by_count[c]['puretime']) if len(by_count[c]['puretime']) > 1 else 0 for c in counts]
    
    # Create figure
    fig, ax = plt.subplots(figsize=(12, 6))
    
    x = np.arange(len(counts))
    width = 0.25
    
    # Grouped bars
    bars1 = ax.bar(x - width, t_isolated, width, label='$T_{isolated}$ (Solo baseline)', 
                   color=COLORS['isolated'], edgecolor='black', linewidth=0.5,
                   hatch='///' if counts[0] == 1 else None)  # Hatch for baseline
    bars2 = ax.bar(x, t_contention, width, yerr=t_contention_err, capsize=3,
                   label='$T_{contention}$ (With noise)', 
                   color=COLORS['contention'], edgecolor='black', linewidth=0.5)
    bars3 = ax.bar(x + width, t_puretime, width, yerr=t_puretime_err, capsize=3,
                   label='$T_{puretime}$ (Noise removed)', 
                   color=COLORS['puretime'], edgecolor='black', linewidth=0.5)
    
    # Calculate and annotate efficiency for each intensity level
    for i, (iso, cont, pure, c) in enumerate(zip(t_isolated, t_contention, t_puretime, counts)):
        if c > 1 and cont > iso:  # Skip baseline (c=1)
            gt_noise = cont - iso
            removed = cont - pure
            efficiency = (removed / gt_noise) * 100
            
            # Efficiency annotation
            ax.annotate(f'{efficiency:.1f}%', 
                       xy=(i + width, pure), 
                       xytext=(i + width, pure + (cont - pure) * 0.15),
                       fontsize=9, fontweight='bold', color=COLORS['efficiency'],
                       ha='center', va='bottom')
    
    ax.set_ylabel('Execution Time (ms)')
    ax.set_xlabel('Number of Concurrent Containers')
    ax.set_xticks(x)
    ax.set_xticklabels([str(c) for c in counts])
    ax.legend(loc='upper left')
    ax.set_ylim(bottom=0)
    
    # Grid
    ax.yaxis.grid(True, linestyle='--', alpha=0.7)
    ax.set_axisbelow(True)
    
    plt.tight_layout()
    
    output_path = os.path.join(output_dir, 'accuracy_by_intensity.pdf')
    plt.savefig(output_path)
    plt.savefig(output_path.replace('.pdf', '.png'))
    print(f"Saved: {output_path}")
    
    return fig


def plot_kpa_simulation(analysis_file, output_dir):
    """
    KPA 시뮬레이션 결과 시각화
    - Figure 1: Observed vs PureTime Concurrency (grouped by noise level)
    - Figure 2: Over-provisioning rate by noise level
    """
    analysis = load_json(analysis_file)
    
    # Group by noise level
    by_noise = defaultdict(list)
    for item in analysis:
        by_noise[item['noise_containers']].append(item)
    
    noise_levels = sorted(by_noise.keys())
    
    # ==========================================================================
    # Figure 1: Concurrency Comparison
    # ==========================================================================
    fig1, ax1 = plt.subplots(figsize=(10, 6))
    
    # For each noise level, show observed vs puretime concurrency at different RPS
    for i, noise in enumerate(noise_levels):
        items = sorted(by_noise[noise], key=lambda x: x['rps'])
        rps_values = [item['rps'] for item in items]
        conc_obs = [item['avg_concurrency_observed'] for item in items]
        conc_pure = [item['avg_concurrency_puretime'] for item in items]
        
        x_offset = i * 0.15
        x = np.arange(len(rps_values)) + x_offset
        
        ax1.plot(x, conc_obs, 'o--', color=COLORS['contention'], 
                label=f'Observed (Noise={noise})' if i == 0 else None, alpha=0.7 + 0.1*i)
        ax1.plot(x, conc_pure, 's-', color=COLORS['puretime'], 
                label=f'PureTime (Noise={noise})' if i == 0 else None, alpha=0.7 + 0.1*i)
    
    ax1.set_ylabel('Concurrency')
    ax1.set_xlabel('RPS')
    ax1.set_xticks(np.arange(len(rps_values)))
    ax1.set_xticklabels([str(r) for r in rps_values])
    ax1.legend()
    ax1.yaxis.grid(True, linestyle='--', alpha=0.7)
    
    plt.tight_layout()
    output_path1 = os.path.join(output_dir, 'kpa_concurrency.pdf')
    plt.savefig(output_path1)
    print(f"Saved: {output_path1}")
    
    # ==========================================================================
    # Figure 2: Over-provisioning Rate
    # ==========================================================================
    fig2, ax2 = plt.subplots(figsize=(10, 6))
    
    # Group by RPS, show over-provisioning rate vs noise level
    by_rps = defaultdict(list)
    for item in analysis:
        by_rps[item['rps']].append(item)
    
    rps_values = sorted(by_rps.keys())
    x = np.arange(len(noise_levels))
    width = 0.8 / len(rps_values)
    
    for i, rps in enumerate(rps_values):
        items_by_noise = {item['noise_containers']: item for item in by_rps[rps]}
        overprov_rates = [items_by_noise.get(n, {}).get('over_provisioning_rate_pct', 0) for n in noise_levels]
        
        ax2.bar(x + i * width, overprov_rates, width, 
               label=f'RPS={rps}', alpha=0.8)
    
    ax2.set_ylabel('False Scale-out Rate (%)')
    ax2.set_xlabel('Number of Noise Containers')
    ax2.set_xticks(x + width * (len(rps_values) - 1) / 2)
    ax2.set_xticklabels([str(n) for n in noise_levels])
    ax2.legend(title='Request Rate')
    ax2.set_ylim(bottom=0)
    ax2.yaxis.grid(True, linestyle='--', alpha=0.7)
    
    plt.tight_layout()
    output_path2 = os.path.join(output_dir, 'kpa_overprov.pdf')
    plt.savefig(output_path2)
    print(f"Saved: {output_path2}")
    
    # ==========================================================================
    # Figure 3: Latency Inflation (T_contention vs T_puretime)
    # ==========================================================================
    fig3, ax3 = plt.subplots(figsize=(10, 6))
    
    noise_levels_filtered = [n for n in noise_levels if n > 0]  # Exclude no-noise case
    
    for i, rps in enumerate(rps_values):
        items = sorted([item for item in by_rps[rps] if item['noise_containers'] > 0], 
                      key=lambda x: x['noise_containers'])
        if not items:
            continue
            
        noise_vals = [item['noise_containers'] for item in items]
        latency_inflation = [(item['avg_t_contention_ms'] - item['avg_t_puretime_ms']) / item['avg_t_puretime_ms'] * 100 
                           for item in items]
        
        ax3.plot(noise_vals, latency_inflation, 'o-', label=f'RPS={rps}', linewidth=2, markersize=8)
    
    ax3.set_ylabel('Latency Inflation (%)')
    ax3.set_xlabel('Number of Noise Containers')
    ax3.legend(title='Request Rate')
    ax3.set_ylim(bottom=0)
    ax3.yaxis.grid(True, linestyle='--', alpha=0.7)
    
    plt.tight_layout()
    output_path3 = os.path.join(output_dir, 'kpa_latency_inflation.pdf')
    plt.savefig(output_path3)
    print(f"Saved: {output_path3}")
    
    return fig1, fig2, fig3


# =============================================================================
# Main
# =============================================================================

def main():
    parser = argparse.ArgumentParser(description='PureTime experiment visualization')
    parser.add_argument('experiment_type', choices=['by_type', 'by_intensity', 'kpa'],
                       help='Type of experiment to visualize')
    parser.add_argument('results_file', help='Path to results file (CSV or JSON)')
    parser.add_argument('-o', '--output', default='.', help='Output directory for figures')
    
    args = parser.parse_args()
    
    os.makedirs(args.output, exist_ok=True)
    
    if args.experiment_type == 'by_type':
        plot_accuracy_by_type(args.results_file, args.output)
    elif args.experiment_type == 'by_intensity':
        plot_accuracy_by_intensity(args.results_file, args.output)
    elif args.experiment_type == 'kpa':
        plot_kpa_simulation(args.results_file, args.output)


if __name__ == '__main__':
    main()
