#!/usr/bin/env python3
"""
PureTime Metrics Computation

정확도 계산 방식 (문서 기준):
    Ground Truth Noise = T_contention - T_isolated
    Removed Noise      = T_contention - T_puretime
    Efficiency         = (Removed Noise / Ground Truth Noise) × 100%

Usage:
    python3 compute_metrics.py results.csv [--output metrics.json]
"""

import argparse
import csv
import json
import sys
from collections import defaultdict
from dataclasses import dataclass
from typing import Dict, List, Optional
import statistics


@dataclass
class ExperimentResult:
    noise_type: str
    container_count: int
    iteration: int
    t_contention_ms: float
    t_puretime_ms: float


@dataclass
class AccuracyMetrics:
    noise_type: str
    container_count: int
    
    # Raw measurements (averaged over iterations)
    t_isolated_ms: float      # Solo (count=1) baseline
    t_contention_ms: float    # With contention
    t_puretime_ms: float      # PureTime's noise-free makespan
    
    # Computed metrics
    ground_truth_noise_ms: float   # T_contention - T_isolated
    removed_noise_ms: float        # T_contention - T_puretime
    remaining_noise_ms: float      # T_puretime - T_isolated
    noise_removal_efficiency: float  # (Removed / GT) × 100%
    
    # Standard deviations
    t_contention_std: float
    t_puretime_std: float
    
    # Sample count
    n_samples: int


def load_results(filepath: str) -> List[ExperimentResult]:
    """CSV 결과 파일 로드"""
    results = []
    with open(filepath, 'r') as f:
        reader = csv.DictReader(f)
        for row in reader:
            results.append(ExperimentResult(
                noise_type=row['noise_type'],
                container_count=int(row['container_count']),
                iteration=int(row['iteration']),
                t_contention_ms=float(row['t_contention_ms']),
                t_puretime_ms=float(row['t_puretime_ms']),
            ))
    return results


def compute_metrics(results: List[ExperimentResult]) -> List[AccuracyMetrics]:
    """
    노이즈 제거 정확도 메트릭 계산
    
    각 (noise_type, container_count) 조합에 대해:
    1. Solo (count=1)를 baseline (T_isolated)으로 사용
    2. Noise Removal Efficiency 계산
    """
    # Group by (noise_type, container_count)
    grouped: Dict[tuple, List[ExperimentResult]] = defaultdict(list)
    for r in results:
        grouped[(r.noise_type, r.container_count)].append(r)
    
    # Find baselines (count=1 for each noise type)
    baselines: Dict[str, float] = {}
    for (noise_type, count), group in grouped.items():
        if count == 1:
            # Solo baseline: average T_contention (which equals T_isolated when no contention)
            baselines[noise_type] = statistics.mean([r.t_contention_ms for r in group])
    
    # Compute metrics for each group
    metrics_list = []
    for (noise_type, count), group in sorted(grouped.items()):
        if count == 1:
            # Solo baseline은 참조용으로만 저장
            t_isolated = baselines[noise_type]
            metrics_list.append(AccuracyMetrics(
                noise_type=noise_type,
                container_count=count,
                t_isolated_ms=t_isolated,
                t_contention_ms=t_isolated,
                t_puretime_ms=statistics.mean([r.t_puretime_ms for r in group]),
                ground_truth_noise_ms=0,
                removed_noise_ms=0,
                remaining_noise_ms=0,
                noise_removal_efficiency=100.0,  # No noise to remove
                t_contention_std=statistics.stdev([r.t_contention_ms for r in group]) if len(group) > 1 else 0,
                t_puretime_std=statistics.stdev([r.t_puretime_ms for r in group]) if len(group) > 1 else 0,
                n_samples=len(group),
            ))
            continue
        
        t_isolated = baselines.get(noise_type, 0)
        if t_isolated == 0:
            print(f"Warning: No baseline found for {noise_type}", file=sys.stderr)
            continue
        
        # Average over iterations
        t_contention_list = [r.t_contention_ms for r in group]
        t_puretime_list = [r.t_puretime_ms for r in group]
        
        t_contention = statistics.mean(t_contention_list)
        t_puretime = statistics.mean(t_puretime_list)
        
        # Noise Removal Efficiency 계산
        ground_truth_noise = t_contention - t_isolated
        removed_noise = t_contention - t_puretime
        remaining_noise = t_puretime - t_isolated
        
        if ground_truth_noise > 0:
            efficiency = (removed_noise / ground_truth_noise) * 100
        else:
            efficiency = 100.0  # No noise detected
        
        metrics_list.append(AccuracyMetrics(
            noise_type=noise_type,
            container_count=count,
            t_isolated_ms=t_isolated,
            t_contention_ms=t_contention,
            t_puretime_ms=t_puretime,
            ground_truth_noise_ms=ground_truth_noise,
            removed_noise_ms=removed_noise,
            remaining_noise_ms=remaining_noise,
            noise_removal_efficiency=efficiency,
            t_contention_std=statistics.stdev(t_contention_list) if len(t_contention_list) > 1 else 0,
            t_puretime_std=statistics.stdev(t_puretime_list) if len(t_puretime_list) > 1 else 0,
            n_samples=len(group),
        ))
    
    return metrics_list


def print_summary(metrics_list: List[AccuracyMetrics]):
    """결과 요약 출력"""
    print("=" * 80)
    print("PureTime Noise Removal Accuracy Analysis")
    print("=" * 80)
    
    # Group by noise type
    by_type: Dict[str, List[AccuracyMetrics]] = defaultdict(list)
    for m in metrics_list:
        by_type[m.noise_type].append(m)
    
    for noise_type in ['cpu', 'network', 'block_io']:
        if noise_type not in by_type:
            continue
        
        print(f"\n[{noise_type.upper()} Contention]")
        print("-" * 70)
        print(f"{'Containers':>10} {'T_isolated':>12} {'T_contention':>14} {'T_puretime':>12} {'Efficiency':>12}")
        print(f"{'':>10} {'(ms)':>12} {'(ms)':>14} {'(ms)':>12} {'(%)':>12}")
        print("-" * 70)
        
        for m in sorted(by_type[noise_type], key=lambda x: x.container_count):
            if m.container_count == 1:
                print(f"{m.container_count:>10} {m.t_isolated_ms:>12.2f} {'(baseline)':>14} {m.t_puretime_ms:>12.2f} {'N/A':>12}")
            else:
                print(f"{m.container_count:>10} {m.t_isolated_ms:>12.2f} {m.t_contention_ms:>14.2f} {m.t_puretime_ms:>12.2f} {m.noise_removal_efficiency:>11.2f}%")
        
        # Average efficiency (excluding baseline)
        efficiencies = [m.noise_removal_efficiency for m in by_type[noise_type] if m.container_count > 1]
        if efficiencies:
            avg_eff = statistics.mean(efficiencies)
            print("-" * 70)
            print(f"{'Average':>10} {'':<12} {'':<14} {'':<12} {avg_eff:>11.2f}%")
    
    # Overall summary
    all_efficiencies = [m.noise_removal_efficiency for m in metrics_list if m.container_count > 1]
    if all_efficiencies:
        print("\n" + "=" * 80)
        print(f"Overall Noise Removal Efficiency: {statistics.mean(all_efficiencies):.2f}%")
        print("=" * 80)


def export_json(metrics_list: List[AccuracyMetrics], filepath: str):
    """결과를 JSON으로 내보내기"""
    output = []
    for m in metrics_list:
        output.append({
            'noise_type': m.noise_type,
            'container_count': m.container_count,
            't_isolated_ms': round(m.t_isolated_ms, 2),
            't_contention_ms': round(m.t_contention_ms, 2),
            't_puretime_ms': round(m.t_puretime_ms, 2),
            'ground_truth_noise_ms': round(m.ground_truth_noise_ms, 2),
            'removed_noise_ms': round(m.removed_noise_ms, 2),
            'remaining_noise_ms': round(m.remaining_noise_ms, 2),
            'noise_removal_efficiency': round(m.noise_removal_efficiency, 2),
            't_contention_std': round(m.t_contention_std, 2),
            't_puretime_std': round(m.t_puretime_std, 2),
            'n_samples': m.n_samples,
        })
    
    with open(filepath, 'w') as f:
        json.dump(output, f, indent=2)
    print(f"\nResults exported to: {filepath}")


def export_latex_table(metrics_list: List[AccuracyMetrics], filepath: str):
    """LaTeX 테이블 생성"""
    lines = [
        r"\begin{table}[t]",
        r"\centering",
        r"\caption{Noise Removal Accuracy by Contention Type}",
        r"\label{tab:accuracy_by_type}",
        r"\begin{tabular}{llrrrr}",
        r"\toprule",
        r"Type & Containers & $T_{isolated}$ & $T_{contention}$ & $T_{puretime}$ & Efficiency \\",
        r" & & (ms) & (ms) & (ms) & (\%) \\",
        r"\midrule",
    ]
    
    by_type: Dict[str, List[AccuracyMetrics]] = defaultdict(list)
    for m in metrics_list:
        by_type[m.noise_type].append(m)
    
    for i, noise_type in enumerate(['cpu', 'network', 'block_io']):
        if noise_type not in by_type:
            continue
        
        type_label = {'cpu': 'CPU', 'network': 'Network', 'block_io': 'Block I/O'}[noise_type]
        
        for j, m in enumerate(sorted(by_type[noise_type], key=lambda x: x.container_count)):
            if m.container_count == 1:
                continue  # Skip baseline rows in table
            
            row_type = type_label if j == 1 else ""  # Only show type on first data row
            eff_str = f"{m.noise_removal_efficiency:.1f}"
            
            lines.append(
                f"{row_type} & {m.container_count} & {m.t_isolated_ms:.1f} & "
                f"{m.t_contention_ms:.1f} & {m.t_puretime_ms:.1f} & {eff_str} \\\\"
            )
        
        if i < 2:  # Add midrule between types
            lines.append(r"\midrule")
    
    lines.extend([
        r"\bottomrule",
        r"\end{tabular}",
        r"\end{table}",
    ])
    
    with open(filepath, 'w') as f:
        f.write('\n'.join(lines))
    print(f"LaTeX table exported to: {filepath}")


def main():
    parser = argparse.ArgumentParser(
        description='Compute PureTime noise removal accuracy metrics'
    )
    parser.add_argument('results_file', help='CSV file with experiment results')
    parser.add_argument('-o', '--output', help='Output JSON file for metrics')
    parser.add_argument('--latex', help='Output LaTeX table file')
    
    args = parser.parse_args()
    
    results = load_results(args.results_file)
    metrics = compute_metrics(results)
    
    print_summary(metrics)
    
    if args.output:
        export_json(metrics, args.output)
    
    if args.latex:
        export_latex_table(metrics, args.latex)


if __name__ == '__main__':
    main()
