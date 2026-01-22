#!/usr/bin/env python3
"""
PureTime Trace Analyzer
Parses JSONL output and calculates latency statistics for all event types.

Usage: python3 analyze_trace.py /var/log/puretime/trace_*.jsonl
"""

import json
import sys
import argparse
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Dict, List
import statistics


@dataclass
class LatencyStats:
    """Statistics container for latency measurements"""
    values: List[int] = field(default_factory=list)

    def add(self, value: int):
        self.values.append(value)

    @property
    def count(self) -> int:
        return len(self.values)

    @property
    def min_ns(self) -> int:
        return min(self.values) if self.values else 0

    @property
    def max_ns(self) -> int:
        return max(self.values) if self.values else 0

    @property
    def avg_ns(self) -> float:
        return statistics.mean(self.values) if self.values else 0

    @property
    def median_ns(self) -> float:
        return statistics.median(self.values) if self.values else 0

    def percentile(self, p: int) -> float:
        if not self.values:
            return 0
        sorted_vals = sorted(self.values)
        idx = int(len(sorted_vals) * p / 100)
        return sorted_vals[min(idx, len(sorted_vals) - 1)]

    @property
    def p50_ns(self) -> float:
        return self.percentile(50)

    @property
    def p95_ns(self) -> float:
        return self.percentile(95)

    @property
    def p99_ns(self) -> float:
        return self.percentile(99)

    def to_dict(self) -> dict:
        return {
            'count': self.count,
            'min_us': self.min_ns / 1000,
            'max_us': self.max_ns / 1000,
            'avg_us': self.avg_ns / 1000,
            'median_us': self.median_ns / 1000,
            'p50_us': self.p50_ns / 1000,
            'p95_us': self.p95_ns / 1000,
            'p99_us': self.p99_ns / 1000,
        }


class PureTimeAnalyzer:
    """Analyzer for PureTime trace files"""

    def __init__(self):
        # Pending events for correlation
        self.sched_enqueues: Dict[int, dict] = {}  # tid -> event
        self.net_queued: Dict[int, dict] = {}  # skb_addr -> event
        self.block_inserted: Dict[int, dict] = {}  # request_addr -> event
        self.block_issued: Dict[int, dict] = {}  # request_addr -> event

        # Statistics
        self.runq_latency = LatencyStats()
        self.qdisc_latency = LatencyStats()
        self.io_sched_latency = LatencyStats()
        self.io_total_latency = LatencyStats()

        # Event counts
        self.event_counts = defaultdict(int)

        # Correlation stats
        self.correlated_sched = 0
        self.uncorrelated_sched = 0
        self.correlated_net = 0
        self.uncorrelated_net = 0
        self.correlated_block = 0
        self.uncorrelated_block = 0

        # Per-process stats
        self.per_process_runq: Dict[str, LatencyStats] = defaultdict(LatencyStats)

    def process_event(self, event: dict):
        """Process a single event"""
        event_type = event.get('event', '')
        self.event_counts[event_type] += 1

        # Scheduler events
        if event_type == 'sched_enqueue':
            self._handle_sched_enqueue(event)
        elif event_type == 'sched_switch':
            self._handle_sched_switch(event)

        # Network events
        elif event_type == 'net_dev_queue':
            self._handle_net_queue(event)
        elif event_type == 'net_dev_xmit':
            self._handle_net_xmit(event)

        # Block events
        elif event_type == 'block_rq_insert':
            self._handle_block_insert(event)
        elif event_type == 'block_rq_issue':
            self._handle_block_issue(event)
        elif event_type == 'block_rq_complete':
            self._handle_block_complete(event)

    def _handle_sched_enqueue(self, event: dict):
        """Handle sched_enqueue events"""
        tid = event.get('tid')
        if tid is not None:
            self.sched_enqueues[tid] = event

    def _handle_sched_switch(self, event: dict):
        """Handle sched_switch event - correlate with enqueue"""
        tid = event.get('tid')
        if tid is None:
            return

        # Find matching enqueue for this tid
        enqueue = self.sched_enqueues.pop(tid, None)

        if enqueue:
            latency = event['timestamp_ns'] - enqueue['timestamp_ns']
            if latency >= 0:
                self.runq_latency.add(latency)
                self.correlated_sched += 1

                # Per-process tracking
                comm = event.get('comm', 'unknown')
                self.per_process_runq[comm].add(latency)
        else:
            self.uncorrelated_sched += 1

    def _handle_net_queue(self, event: dict):
        """Handle net_dev_queue event"""
        skb_addr = event.get('skb_addr')
        if skb_addr is not None:
            self.net_queued[skb_addr] = event

    def _handle_net_xmit(self, event: dict):
        """Handle net_dev_xmit event - correlate with queue"""
        skb_addr = event.get('skb_addr')
        if skb_addr is None:
            return

        queue_event = self.net_queued.pop(skb_addr, None)

        if queue_event:
            latency = event['timestamp_ns'] - queue_event['timestamp_ns']
            if latency >= 0:
                self.qdisc_latency.add(latency)
                self.correlated_net += 1
        else:
            self.uncorrelated_net += 1

    def _handle_block_insert(self, event: dict):
        """Handle block_rq_insert event"""
        req_addr = event.get('request_addr')
        if req_addr is not None:
            self.block_inserted[req_addr] = event

    def _handle_block_issue(self, event: dict):
        """Handle block_rq_issue event - correlate with insert"""
        req_addr = event.get('request_addr')
        if req_addr is None:
            return

        insert_event = self.block_inserted.get(req_addr)

        if insert_event:
            latency = event['timestamp_ns'] - insert_event['timestamp_ns']
            if latency >= 0:
                self.io_sched_latency.add(latency)
                self.correlated_block += 1
        else:
            self.uncorrelated_block += 1

        # Store for complete correlation
        self.block_issued[req_addr] = event

    def _handle_block_complete(self, event: dict):
        """Handle block_rq_complete event - calculate total latency"""
        req_addr = event.get('request_addr')
        if req_addr is None:
            return

        insert_event = self.block_inserted.pop(req_addr, None)
        self.block_issued.pop(req_addr, None)

        if insert_event:
            latency = event['timestamp_ns'] - insert_event['timestamp_ns']
            if latency >= 0:
                self.io_total_latency.add(latency)

    def analyze_file(self, filepath: str):
        """Process a JSONL trace file

        Note: Multi-CPU 환경에서 Ring Buffer의 이벤트 순서가 보장되지 않으므로
        timestamp 기준으로 정렬 후 처리해야 함
        """
        # 1. 모든 이벤트 읽기
        events = []
        with open(filepath, 'r') as f:
            for line_num, line in enumerate(f, 1):
                line = line.strip()
                if not line:
                    continue
                try:
                    events.append(json.loads(line))
                except json.JSONDecodeError as e:
                    print(f"Warning: Invalid JSON at line {line_num}: {e}",
                          file=sys.stderr)

        # 2. timestamp 기준 정렬 (Multi-CPU 환경에서 순서 보장)
        events.sort(key=lambda e: e.get('timestamp_ns', 0))

        # 3. 정렬된 이벤트 순차 처리
        for event in events:
            self.process_event(event)

    def print_summary(self):
        """Print analysis summary"""
        print("=" * 70)
        print("PureTime Trace Analysis Summary")
        print("=" * 70)

        # Event counts
        print("\n[Event Counts]")
        for event_type, count in sorted(self.event_counts.items()):
            print(f"  {event_type}: {count:,}")

        # Run Queue Latency
        print("\n[Run Queue Latency (sched_enqueue -> sched_switch)]")
        if self.runq_latency.count > 0:
            stats = self.runq_latency.to_dict()
            print(f"  Samples:    {stats['count']:,}")
            print(f"  Min:        {stats['min_us']:.2f} us")
            print(f"  Max:        {stats['max_us']:.2f} us")
            print(f"  Average:    {stats['avg_us']:.2f} us")
            print(f"  Median:     {stats['median_us']:.2f} us")
            print(f"  P95:        {stats['p95_us']:.2f} us")
            print(f"  P99:        {stats['p99_us']:.2f} us")
            total_sched = self.correlated_sched + self.uncorrelated_sched
            if total_sched > 0:
                corr_rate = self.correlated_sched / total_sched * 100
                print(f"  Correlation Rate: {corr_rate:.1f}%")
        else:
            print("  No correlated events")

        # Qdisc Latency
        print("\n[Qdisc Latency (net_dev_queue -> net_dev_xmit)]")
        if self.qdisc_latency.count > 0:
            stats = self.qdisc_latency.to_dict()
            print(f"  Samples:    {stats['count']:,}")
            print(f"  Min:        {stats['min_us']:.2f} us")
            print(f"  Max:        {stats['max_us']:.2f} us")
            print(f"  Average:    {stats['avg_us']:.2f} us")
            print(f"  Median:     {stats['median_us']:.2f} us")
            print(f"  P95:        {stats['p95_us']:.2f} us")
            print(f"  P99:        {stats['p99_us']:.2f} us")
            total_net = self.correlated_net + self.uncorrelated_net
            if total_net > 0:
                corr_rate = self.correlated_net / total_net * 100
                print(f"  Correlation Rate: {corr_rate:.1f}%")
        else:
            print("  No correlated events")

        # I/O Scheduler Latency
        print("\n[I/O Scheduler Latency (block_rq_insert -> block_rq_issue)]")
        if self.io_sched_latency.count > 0:
            stats = self.io_sched_latency.to_dict()
            print(f"  Samples:    {stats['count']:,}")
            print(f"  Min:        {stats['min_us']:.2f} us")
            print(f"  Max:        {stats['max_us']:.2f} us")
            print(f"  Average:    {stats['avg_us']:.2f} us")
            print(f"  Median:     {stats['median_us']:.2f} us")
            print(f"  P95:        {stats['p95_us']:.2f} us")
            print(f"  P99:        {stats['p99_us']:.2f} us")
            total_block = self.correlated_block + self.uncorrelated_block
            if total_block > 0:
                corr_rate = self.correlated_block / total_block * 100
                print(f"  Correlation Rate: {corr_rate:.1f}%")
        else:
            print("  No correlated events")

        # Total I/O Latency
        print("\n[Total I/O Latency (block_rq_insert -> block_rq_complete)]")
        if self.io_total_latency.count > 0:
            stats = self.io_total_latency.to_dict()
            print(f"  Samples:    {stats['count']:,}")
            print(f"  Min:        {stats['min_us']:.2f} us")
            print(f"  Max:        {stats['max_us']:.2f} us")
            print(f"  Average:    {stats['avg_us']:.2f} us")
            print(f"  P99:        {stats['p99_us']:.2f} us")
        else:
            print("  No correlated events")

        # Top processes by run queue latency
        if self.per_process_runq:
            print("\n[Top 10 Processes by Run Queue Latency (P99)]")
            sorted_procs = sorted(
                self.per_process_runq.items(),
                key=lambda x: x[1].p99_ns,
                reverse=True
            )[:10]
            for comm, stats in sorted_procs:
                print(f"  {comm}: P99={stats.p99_ns/1000:.2f}us, "
                      f"avg={stats.avg_ns/1000:.2f}us, n={stats.count}")

        print("\n" + "=" * 70)

    def export_json(self, filepath: str):
        """Export results as JSON"""
        results = {
            'event_counts': dict(self.event_counts),
            'runq_latency': self.runq_latency.to_dict() if self.runq_latency.count else None,
            'qdisc_latency': self.qdisc_latency.to_dict() if self.qdisc_latency.count else None,
            'io_sched_latency': self.io_sched_latency.to_dict() if self.io_sched_latency.count else None,
            'io_total_latency': self.io_total_latency.to_dict() if self.io_total_latency.count else None,
            'correlation': {
                'sched': {
                    'correlated': self.correlated_sched,
                    'uncorrelated': self.uncorrelated_sched,
                },
                'net': {
                    'correlated': self.correlated_net,
                    'uncorrelated': self.uncorrelated_net,
                },
                'block': {
                    'correlated': self.correlated_block,
                    'uncorrelated': self.uncorrelated_block,
                }
            }
        }

        with open(filepath, 'w') as f:
            json.dump(results, f, indent=2)
        print(f"Results exported to {filepath}")


def main():
    parser = argparse.ArgumentParser(
        description='Analyze PureTime eBPF trace files'
    )
    parser.add_argument(
        'trace_files',
        nargs='+',
        help='JSONL trace file(s) to analyze'
    )
    parser.add_argument(
        '-o', '--output',
        help='Export results to JSON file'
    )
    parser.add_argument(
        '-v', '--verbose',
        action='store_true',
        help='Verbose output'
    )

    args = parser.parse_args()

    analyzer = PureTimeAnalyzer()

    for filepath in args.trace_files:
        if args.verbose:
            print(f"Processing: {filepath}")
        analyzer.analyze_file(filepath)

    analyzer.print_summary()

    if args.output:
        analyzer.export_json(args.output)


if __name__ == '__main__':
    main()
