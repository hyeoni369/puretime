#!/usr/bin/env python3
"""
Noise-Free Makespan Analyzer for PureTime

Analyzes eBPF trace data to calculate noise-free makespan by identifying
and removing wait times caused by other tenants (cgroups).

Wait 계산 원칙 (모든 타입 동일):
- CPU: 내 enqueue 이후 다른 프로세스 switch-in 시점 -> 내 switch-in 시점
- Network: 내 queue 이후 다른 패킷 dequeue 시점 -> 내 dequeue 시점
- Block I/O: 내 insert 이후 다른 요청 issue 시점 -> 내 issue 시점
"""

import argparse
import json
import sys
from collections import defaultdict
from dataclasses import dataclass, field
from bisect import bisect_left, bisect_right
from typing import Dict, List, Optional, Set, Tuple

import portion as P
from tqdm import tqdm


def interval_sum(interval: P.Interval) -> int:
    """portion Interval의 총 길이(나노초) 계산"""
    if interval.empty:
        return 0
    total = 0
    for atomic in interval:
        if atomic.lower != P.inf and atomic.upper != P.inf:
            total += atomic.upper - atomic.lower
    return total


@dataclass
class CgroupWaitIntervals:
    """cgroup별 Wait 구간을 portion Interval로 관리 (자동 overlap 제거)"""
    cpu: P.Interval = field(default_factory=P.empty)
    net: P.Interval = field(default_factory=P.empty)
    bio: P.Interval = field(default_factory=P.empty)
    softirq_other: P.Interval = field(default_factory=P.empty)
    softirq_self: P.Interval = field(default_factory=P.empty)

    def add_cpu_wait(self, start: int, end: int):
        self.cpu |= P.closedopen(start, end)

    def add_net_wait(self, start: int, end: int):
        self.net |= P.closedopen(start, end)

    def add_bio_wait(self, start: int, end: int):
        self.bio |= P.closedopen(start, end)

    def total_unique_wait(self) -> P.Interval:
        """모든 wait 타입의 union (overlap 자동 제거)"""
        return self.cpu | self.net | self.bio | self.softirq_other


@dataclass
class CgroupMakespanResult:
    """cgroup별 분석 결과"""
    cgroup_id: int
    original_makespan: int
    noise_free_makespan: int
    total_unique_wait: int
    wait_cpu: int
    wait_net: int
    wait_bio: int
    softirq_other: int
    softirq_self: int
    # Interval-merge ablation (C3): naive = sum of per-resource waits WITHOUT union,
    # so overlapping waits are double-subtracted. noise_free_naive can go negative.
    naive_total_wait: int = 0
    noise_free_naive: int = 0


# Pending 이벤트: 시작은 됐지만 아직 완료되지 않은 이벤트
@dataclass
class PendingEnqueue:
    timestamp_ns: int
    cgroup_id: int
    cpu: int
    tid: int


@dataclass
class PendingPacket:
    timestamp_ns: int
    cgroup_id: int
    skb_addr: int


@dataclass
class PendingBlockRequest:
    insert_timestamp_ns: int
    cgroup_id: int
    request_addr: int


@dataclass
class PendingSoftirq:
    entry_timestamp_ns: int
    vec: int
    cpu: int
    cgroup_event_counts: Dict[int, int] = field(default_factory=lambda: defaultdict(int))


class NoiseFreeAnalyzer:
    """Noise-Free Makespan 분석기"""

    def __init__(self, min_events: int = 100):
        self.min_events = min_events

        # Ring buffer 유실 카운트 (loader가 기록한 trace_summary trailer에서 읽음)
        self.dropped_events: int = 0

        # Pending 이벤트 추적
        self.pending_enqueues: Dict[int, PendingEnqueue] = {}  # tid -> PendingEnqueue
        self.pending_packets: Dict[int, PendingPacket] = {}  # skb_addr -> PendingPacket
        self.pending_block_requests: Dict[int, PendingBlockRequest] = {}  # request_addr
        self.pending_softirqs: Dict[int, PendingSoftirq] = {}  # cpu -> PendingSoftirq

        # Per-cgroup wait intervals (portion 라이브러리)
        self.cgroup_waits: Dict[int, CgroupWaitIntervals] = defaultdict(CgroupWaitIntervals)

        # CPU별 switch 히스토리 (CPU Wait 계산용) - (timestamp, event_dict) 튜플로 저장
        self.cpu_switch_history: Dict[int, List[Tuple[int, dict]]] = defaultdict(list)

        # Network dequeue 히스토리 (Network Wait 계산용) - (timestamp, event_dict) 튜플로 저장
        self.net_dequeue_history: List[Tuple[int, dict]] = []

        # Block issue 히스토리 (Block I/O Wait 계산용) - (timestamp, event_dict) 튜플로 저장
        self.block_issue_history: List[Tuple[int, dict]] = []

        # cgroup별 시간 범위
        self.cgroup_time_range: Dict[int, Tuple[int, int]] = {}

    def analyze_file(self, filepath: str, target_cgroups: Optional[Set[int]] = None) -> Dict[int, CgroupMakespanResult]:
        """트레이스 파일 분석

        Args:
            filepath: 트레이스 파일 경로
            target_cgroups: 분석할 cgroup ID 집합. None이면 자동 감지
        """
        # Pass 1: cgroup 자동 감지 및 시간 범위 수집
        cgroup_counts = self._detect_cgroups(filepath)

        # 불완전 trace 거부: ring buffer 유실이 있으면 makespan 계산을 하지 않는다.
        # (실시간 보정이 아니라, 더 큰 ring buffer로 재실행해야 한다는 신호)
        if self.dropped_events > 0:
            raise ValueError(
                f"Incomplete trace: {self.dropped_events} ring-buffer events were dropped "
                f"(buffer full). Re-run the tracer with a larger ring buffer; "
                f"makespan will NOT be computed on a lossy trace."
            )

        if target_cgroups is None:
            # 자동 감지 모드
            target_cgroups = {
                cg for cg, cnt in cgroup_counts.items()
                if cnt >= self.min_events and cg != 0 and cg != 1
            }

        if not target_cgroups:
            print(f"Warning: No cgroups found with >= {self.min_events} events", file=sys.stderr)
            return {}

        # Pass 2: Wait 계산
        self._calculate_waits(filepath, target_cgroups)

        # 결과 집계
        return self._compute_results(target_cgroups)

    def _detect_cgroups(self, filepath: str) -> Dict[int, int]:
        """Pass 1: 파일을 스캔하여 cgroup별 이벤트 수와 시간 범위 수집"""
        cgroup_counts: Dict[int, int] = defaultdict(int)

        with open(filepath, 'r') as f:
            lines = f.readlines()
            for line in tqdm(lines, desc="Detecting cgroups"):
                if not line.strip():
                    continue
                try:
                    event = json.loads(line)
                except json.JSONDecodeError:
                    continue

                # Loader가 마지막에 기록하는 유실 요약 trailer
                if event.get('event') == 'trace_summary':
                    self.dropped_events += int(event.get('dropped_events', 0))
                    continue

                cgroup_id = event.get('cgroup_id', 0)
                timestamp = event.get('timestamp_ns', 0)

                cgroup_counts[cgroup_id] += 1

                # 시간 범위 업데이트
                if cgroup_id not in self.cgroup_time_range:
                    self.cgroup_time_range[cgroup_id] = (timestamp, timestamp)
                else:
                    first, last = self.cgroup_time_range[cgroup_id]
                    self.cgroup_time_range[cgroup_id] = (min(first, timestamp), max(last, timestamp))

        return cgroup_counts

    def _calculate_waits(self, filepath: str, target_cgroups: Set[int]):
        """Pass 2: 이벤트를 순차적으로 처리하며 Wait 시간 계산

        Note: Multi-CPU 환경에서 Ring Buffer의 이벤트 순서가 보장되지 않으므로
        timestamp 기준으로 정렬 후 처리해야 함
        """
        # 1. 모든 이벤트 읽기
        events = []
        with open(filepath, 'r') as f:
            lines = f.readlines()
            for line in tqdm(lines, desc="Reading events"):
                if not line.strip():
                    continue
                try:
                    event = json.loads(line)
                except json.JSONDecodeError:
                    continue
                # trace_summary trailer는 Pass 1에서 이미 처리됨
                if event.get('event') == 'trace_summary':
                    continue
                events.append(event)

        # 2. timestamp 기준 정렬 (Multi-CPU 환경에서 순서 보장)
        events.sort(key=lambda e: e.get('timestamp_ns', 0))

        # 3. 정렬된 이벤트 순차 처리
        for event in tqdm(events, desc="Processing events"):
            event_type = event.get('event', '')

            # 스케줄러 이벤트
            if event_type == 'sched_enqueue':
                self._handle_enqueue(event, target_cgroups)
            elif event_type == 'sched_switch':
                self._handle_switch(event, target_cgroups)

            # 네트워크 이벤트
            elif event_type == 'net_dev_queue':
                self._handle_net_queue(event, target_cgroups)
            elif event_type == 'net_dev_start_xmit':
                self._handle_net_dequeue(event, target_cgroups)

            # Block I/O 이벤트
            elif event_type == 'block_rq_insert':
                self._handle_block_insert(event, target_cgroups)
            elif event_type == 'block_rq_issue':
                self._handle_block_issue(event, target_cgroups)

            # Softirq 이벤트
            elif event_type == 'softirq_entry':
                self._handle_softirq_entry(event, target_cgroups)
            elif event_type == 'softirq_exit':
                self._handle_softirq_exit(event, target_cgroups)

    def _handle_enqueue(self, event: dict, target_cgroups: Set[int]):
        """enqueue 이벤트: Pending에 저장"""
        tid = event.get('tid')
        if tid is None:
            return
        self.pending_enqueues[tid] = PendingEnqueue(
            timestamp_ns=event['timestamp_ns'],
            cgroup_id=event['cgroup_id'],
            cpu=event.get('cpu', 0),
            tid=tid
        )

    def _handle_switch(self, event: dict, target_cgroups: Set[int]):
        """switch 이벤트: 내 enqueue 이후 다른 프로세스가 먼저 switch-in한 구간 = Wait"""
        tid = event.get('tid')
        cgroup_id = event.get('cgroup_id')
        cpu = event.get('cpu', 0)
        timestamp = event['timestamp_ns']

        # 이 switch에 해당하는 enqueue 찾기
        enqueue = self.pending_enqueues.pop(tid, None)

        if enqueue and cgroup_id in target_cgroups:
            # 내 enqueue 이후, 내 switch 이전에 다른 cgroup이 switch-in한 구간 찾기
            my_enqueue_ts = enqueue.timestamp_ns
            history = self.cpu_switch_history[cpu]

            # Binary search로 범위 찾기: (my_enqueue_ts, timestamp)
            left = bisect_right(history, (my_enqueue_ts,))  # > my_enqueue_ts
            right = bisect_left(history, (timestamp,))      # < timestamp

            for i in range(left, right):
                other_switch_ts, hist_event = history[i]
                other_cgroup = hist_event['cgroup_id']

                # 다른 cgroup이 switch-in한 경우
                if other_cgroup != cgroup_id:
                    # Wait 구간: 다른 프로세스 switch-in 시점 ~ 내 switch-in 시점
                    self.cgroup_waits[cgroup_id].add_cpu_wait(other_switch_ts, timestamp)

        # 모든 switch를 CPU 히스토리에 기록 (다른 프로세스의 Wait 계산용)
        self.cpu_switch_history[cpu].append((timestamp, {
            'cgroup_id': cgroup_id,
            'tid': tid
        }))

    def _handle_net_queue(self, event: dict, target_cgroups: Set[int]):
        """net_dev_queue: Pending에 저장"""
        skb_addr = event.get('skb_addr')
        if skb_addr is None:
            return
        self.pending_packets[skb_addr] = PendingPacket(
            timestamp_ns=event['timestamp_ns'],
            cgroup_id=event['cgroup_id'],
            skb_addr=skb_addr
        )

    def _handle_net_dequeue(self, event: dict, target_cgroups: Set[int]):
        """net_dev_start_xmit: 내 queue 이후 다른 패킷이 먼저 dequeue된 구간 = Wait"""
        skb_addr = event.get('skb_addr')
        cgroup_id = event.get('cgroup_id')
        timestamp = event['timestamp_ns']

        # 이 dequeue에 해당하는 queue 이벤트 찾기
        my_packet = self.pending_packets.pop(skb_addr, None)

        if my_packet and my_packet.cgroup_id in target_cgroups:
            my_queue_ts = my_packet.timestamp_ns

            # Binary search로 범위 찾기: (my_queue_ts, timestamp)
            left = bisect_right(self.net_dequeue_history, (my_queue_ts,))  # > my_queue_ts
            right = bisect_left(self.net_dequeue_history, (timestamp,))    # < timestamp

            for i in range(left, right):
                other_dequeue_ts, hist_event = self.net_dequeue_history[i]
                other_cgroup = hist_event['cgroup_id']

                # 다른 cgroup 패킷이 dequeue된 경우
                if other_cgroup != my_packet.cgroup_id:
                    # Wait 구간: 다른 패킷 dequeue 시점 ~ 내 패킷 dequeue 시점
                    self.cgroup_waits[my_packet.cgroup_id].add_net_wait(other_dequeue_ts, timestamp)

        # 모든 dequeue를 히스토리에 기록
        self.net_dequeue_history.append((timestamp, {
            'cgroup_id': cgroup_id,
            'skb_addr': skb_addr
        }))

        # Softirq 구간 내 이벤트 기록
        cpu = event.get('cpu', 0)
        self._record_softirq_event(cgroup_id, cpu)

    def _handle_block_insert(self, event: dict, target_cgroups: Set[int]):
        """block_rq_insert: Pending에 저장"""
        req_addr = event.get('request_addr')
        if req_addr is None:
            return
        self.pending_block_requests[req_addr] = PendingBlockRequest(
            insert_timestamp_ns=event['timestamp_ns'],
            cgroup_id=event['cgroup_id'],
            request_addr=req_addr
        )

    def _handle_block_issue(self, event: dict, target_cgroups: Set[int]):
        """block_rq_issue: 내 insert 이후 다른 요청이 먼저 issue된 구간 = Wait"""
        req_addr = event.get('request_addr')
        cgroup_id = event.get('cgroup_id')
        timestamp = event['timestamp_ns']

        # 이 issue에 해당하는 insert 이벤트 찾기
        my_request = self.pending_block_requests.pop(req_addr, None)

        if my_request and my_request.cgroup_id in target_cgroups:
            my_insert_ts = my_request.insert_timestamp_ns

            # Binary search로 범위 찾기: (my_insert_ts, timestamp)
            left = bisect_right(self.block_issue_history, (my_insert_ts,))  # > my_insert_ts
            right = bisect_left(self.block_issue_history, (timestamp,))     # < timestamp

            for i in range(left, right):
                other_issue_ts, hist_event = self.block_issue_history[i]
                other_cgroup = hist_event['cgroup_id']

                # 다른 cgroup 요청이 issue된 경우
                if other_cgroup != my_request.cgroup_id:
                    # Wait 구간: 다른 요청 issue 시점 ~ 내 요청 issue 시점
                    self.cgroup_waits[my_request.cgroup_id].add_bio_wait(other_issue_ts, timestamp)

        # 모든 issue를 히스토리에 기록
        self.block_issue_history.append((timestamp, {
            'cgroup_id': cgroup_id,
            'request_addr': req_addr
        }))

        # Softirq 구간 내 이벤트 기록
        cpu = event.get('cpu', 0)
        self._record_softirq_event(cgroup_id, cpu)

    def _handle_softirq_entry(self, event: dict, target_cgroups: Set[int]):
        """softirq_entry: CPU별로 softirq 시작 기록"""
        cpu = event.get('cpu', 0)
        self.pending_softirqs[cpu] = PendingSoftirq(
            entry_timestamp_ns=event['timestamp_ns'],
            vec=event.get('vec', 0),
            cpu=cpu
        )

    def _handle_softirq_exit(self, event: dict, target_cgroups: Set[int]):
        """softirq_exit: softirq 구간 내 cgroup 비율로 wait 분배"""
        cpu = event.get('cpu', 0)
        exit_ts = event['timestamp_ns']

        softirq = self.pending_softirqs.pop(cpu, None)
        if not softirq:
            return

        duration = exit_ts - softirq.entry_timestamp_ns
        if duration <= 0:
            return

        total_events = sum(softirq.cgroup_event_counts.values())
        if total_events == 0:
            return

        # 각 target cgroup에 대해 softirq 시간 분배
        for cgroup_id in target_cgroups:
            my_count = softirq.cgroup_event_counts.get(cgroup_id, 0)
            other_count = total_events - my_count

            if my_count > 0:
                my_ratio = my_count / total_events
                self_duration = int(duration * my_ratio)
                self.cgroup_waits[cgroup_id].softirq_self |= P.closedopen(
                    softirq.entry_timestamp_ns,
                    softirq.entry_timestamp_ns + self_duration
                )

            if other_count > 0:
                other_ratio = other_count / total_events
                other_duration = int(duration * other_ratio)
                self.cgroup_waits[cgroup_id].softirq_other |= P.closedopen(
                    softirq.entry_timestamp_ns + (duration - other_duration),
                    exit_ts
                )

    def _record_softirq_event(self, cgroup_id: int, cpu: int):
        """softirq 구간 내에서 발생한 이벤트의 cgroup 기록"""
        if cpu in self.pending_softirqs:
            self.pending_softirqs[cpu].cgroup_event_counts[cgroup_id] += 1

    def _compute_results(self, target_cgroups: Set[int]) -> Dict[int, CgroupMakespanResult]:
        """결과 집계"""
        results = {}
        for cgroup_id in tqdm(target_cgroups, desc="Computing results for cgroups"):
            waits = self.cgroup_waits[cgroup_id]
            first_ts, last_ts = self.cgroup_time_range.get(cgroup_id, (0, 0))

            original_makespan = last_ts - first_ts

            # Wait 구간을 이 cgroup의 생존 구간 [first_ts, last_ts]와 교집합한다.
            # softirq_other는 softirq 창의 timestamp로 만들어져 이 cgroup 범위 밖에
            # 놓일 수 있으므로, span 밖 부분을 잘라내야 과다차감(음수 makespan)을 막는다.
            span = P.closedopen(first_ts, last_ts)
            all_wait = waits.total_unique_wait() & span
            unique_wait = interval_sum(all_wait)

            wait_cpu = interval_sum(waits.cpu & span)
            wait_net = interval_sum(waits.net & span)
            wait_bio = interval_sum(waits.bio & span)
            softirq_other = interval_sum(waits.softirq_other & span)
            softirq_self = interval_sum(waits.softirq_self & span)

            noise_free_makespan = original_makespan - unique_wait

            # Interval-merge ablation (C3 / exp 2-1): naive subtraction sums per-resource
            # waits WITHOUT the union, so overlapping waits are removed more than once.
            # This over-subtracts and can drive noise_free_naive negative -- the merge's
            # advantage. (NOT asserted: negative is the expected failure mode here.)
            naive_total_wait = wait_cpu + wait_net + wait_bio + softirq_other
            noise_free_naive = original_makespan - naive_total_wait

            # Invariant 가드 (contract 명시): 위반 시 조용히 틀린 값을 내지 말고 즉시 실패.
            assert original_makespan >= 0, (cgroup_id, original_makespan)
            assert 0 <= unique_wait <= original_makespan, \
                (cgroup_id, unique_wait, original_makespan)
            assert 0 <= noise_free_makespan <= original_makespan, \
                (cgroup_id, noise_free_makespan, original_makespan)
            assert min(wait_cpu, wait_net, wait_bio, softirq_other, softirq_self) >= 0, \
                (cgroup_id, wait_cpu, wait_net, wait_bio, softirq_other, softirq_self)

            results[cgroup_id] = CgroupMakespanResult(
                cgroup_id=cgroup_id,
                original_makespan=original_makespan,
                noise_free_makespan=noise_free_makespan,
                total_unique_wait=unique_wait,
                wait_cpu=wait_cpu,
                wait_net=wait_net,
                wait_bio=wait_bio,
                softirq_other=softirq_other,
                softirq_self=softirq_self,
                naive_total_wait=naive_total_wait,
                noise_free_naive=noise_free_naive,
            )
        return results


def format_ns(ns: int) -> str:
    """나노초를 읽기 쉬운 형식으로 변환"""
    if ns >= 1_000_000_000:
        return f"{ns / 1_000_000_000:.3f}s"
    elif ns >= 1_000_000:
        return f"{ns / 1_000_000:.3f}ms"
    elif ns >= 1_000:
        return f"{ns / 1_000:.3f}us"
    else:
        return f"{ns}ns"


def print_results(results: Dict[int, CgroupMakespanResult], output_json: bool = False):
    """분석 결과 출력"""
    if output_json:
        output = []
        for cgroup_id, result in sorted(results.items()):
            output.append({
                'cgroup_id': result.cgroup_id,
                'original_makespan_ns': result.original_makespan,
                'noise_free_makespan_ns': result.noise_free_makespan,
                'total_unique_wait_ns': result.total_unique_wait,
                'wait_cpu_ns': result.wait_cpu,
                'wait_net_ns': result.wait_net,
                'wait_bio_ns': result.wait_bio,
                'softirq_other_ns': result.softirq_other,
                'softirq_self_ns': result.softirq_self,
                'wait_percentage': (result.total_unique_wait / result.original_makespan * 100)
                    if result.original_makespan > 0 else 0,
                # Interval-merge ablation (C3): merged vs naive (no-union) subtraction
                'naive_total_wait_ns': result.naive_total_wait,
                'noise_free_naive_ns': result.noise_free_naive,
                'overlap_removed_ns': result.naive_total_wait - result.total_unique_wait,
            })
        print(json.dumps(output, indent=2))
    else:
        print("=" * 60)
        print("PureTime Noise-Free Makespan Analysis")
        print("=" * 60)

        for cgroup_id, result in sorted(results.items()):
            wait_pct = (result.total_unique_wait / result.original_makespan * 100) \
                if result.original_makespan > 0 else 0

            print(f"\n[Cgroup {cgroup_id}]")
            print(f"  Original Makespan:   {format_ns(result.original_makespan)}")
            print(f"  Noise-Free Makespan: {format_ns(result.noise_free_makespan)}")
            print(f"  Total Wait:          {format_ns(result.total_unique_wait)} ({wait_pct:.2f}%)")

        # total_original = sum(r.original_makespan for r in results.values())
        # total_noise_free = sum(r.noise_free_makespan for r in results.values())
        # print(f'Avg Original Makespan: {format_ns(total_original // len(results))}')
        # print(f'Avg Noise-Free Makespan: {format_ns(total_noise_free // len(results))} ')


def load_cgroups_from_file(filepath: str) -> Set[int]:
    """파일에서 cgroup ID 목록 읽기 (한 줄에 하나씩)"""
    cgroups = set()
    with open(filepath, 'r') as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith('#'):
                cgroups.add(int(line))
    return cgroups


def main():
    parser = argparse.ArgumentParser(
        description='Noise-Free Makespan Analyzer for PureTime traces'
    )
    parser.add_argument('trace_file', help='Path to JSON Lines trace file')
    parser.add_argument(
        '-m', '--min-events',
        type=int,
        default=100,
        help='Minimum events to consider a cgroup (default: 100)'
    )
    parser.add_argument(
        '-j', '--json',
        action='store_true',
        help='Output results in JSON format'
    )
    parser.add_argument(
        '-c', '--cgroups-file',
        type=str,
        help='Path to file containing cgroup IDs (one per line)'
    )

    args = parser.parse_args()

    # cgroup 목록 로드
    target_cgroups = None
    if args.cgroups_file:
        target_cgroups = load_cgroups_from_file(args.cgroups_file)

    analyzer = NoiseFreeAnalyzer(min_events=args.min_events)
    try:
        results = analyzer.analyze_file(args.trace_file, target_cgroups)
    except ValueError as e:
        # 불완전 trace 등 거부 사유 → 조용히 결과를 내지 않고 명확히 실패
        print(f"ERROR: {e}", file=sys.stderr)
        sys.exit(2)

    # 경고: 파일에 있지만 트레이스에서 결과가 없는 cgroup
    if target_cgroups:
        missing = target_cgroups - set(results.keys())
        for cg in missing:
            print(f"Warning: cgroup {cg} not found in trace", file=sys.stderr)

    if not results:
        print("No results to display", file=sys.stderr)
        sys.exit(1)

    print_results(results, output_json=args.json)


if __name__ == '__main__':
    main()
