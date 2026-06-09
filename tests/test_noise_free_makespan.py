#!/usr/bin/env python3
"""Regression tests for noise_free_makespan analyzer correctness fixes.

Covers the audit findings that were fixed:
  - softirq_other / union not clamped to a cgroup's [first_ts,last_ts] -> negative makespan
  - invariant guards (noise_free >= 0, unique_wait <= makespan)
  - ring-buffer drop detection: a trace_summary trailer with dropped_events>0 is rejected

Runnable without pytest:  python3 tests/test_noise_free_makespan.py
"""
import json
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from noise_free_makespan import NoiseFreeAnalyzer  # noqa: E402


def _write(lines):
    f = tempfile.NamedTemporaryFile("w", suffix=".jsonl", delete=False)
    for obj in lines:
        f.write(json.dumps(obj) + "\n")
    f.close()
    return f.name


def test_softirq_out_of_span_does_not_go_negative():
    """A softirq window dominated by another cgroup, lying entirely outside the
    victim cgroup's lifetime, must NOT subtract time from the victim (clamp to span)."""
    trace = [
        # cgroup 100 lives in [1000, 1100] (makespan 100)
        {"event": "sched_enqueue", "timestamp_ns": 1000, "cgroup_id": 100, "cpu": 0, "tid": 1, "comm": "v"},
        {"event": "sched_switch", "timestamp_ns": 1100, "cgroup_id": 100, "cpu": 0, "tid": 1, "comm": "v",
         "prev_cgroup_id": 0, "prev_pid": 0, "prev_tid": 0, "prev_comm": "idle"},
        # softirq window [5000,6000) on cpu0, full of cgroup 200's block issues -> attributed to 200
        {"event": "softirq_entry", "timestamp_ns": 5000, "cgroup_id": 200, "cpu": 0, "vec": 4},
        {"event": "block_rq_issue", "timestamp_ns": 5200, "cgroup_id": 200, "cpu": 0, "request_addr": 11, "rwbs": "R"},
        {"event": "block_rq_issue", "timestamp_ns": 5500, "cgroup_id": 200, "cpu": 0, "request_addr": 12, "rwbs": "R"},
        {"event": "block_rq_issue", "timestamp_ns": 5800, "cgroup_id": 200, "cpu": 0, "request_addr": 13, "rwbs": "R"},
        {"event": "softirq_exit", "timestamp_ns": 6000, "cgroup_id": 200, "cpu": 0, "vec": 4},
    ]
    path = _write(trace)
    try:
        res = NoiseFreeAnalyzer(min_events=1).analyze_file(path, target_cgroups={100})
    finally:
        os.unlink(path)
    r = res[100]
    assert r.original_makespan == 100, r.original_makespan
    # Out-of-span softirq must be clamped away -> no wait subtracted, makespan unchanged.
    assert r.total_unique_wait == 0, r.total_unique_wait
    assert r.noise_free_makespan == 100, r.noise_free_makespan
    assert r.noise_free_makespan >= 0
    print("ok: softirq out-of-span clamped (noise_free=100, was -900 before fix)")


def test_in_span_cpu_wait_still_subtracted():
    """Sanity: a real in-span CPU wait (another cgroup grabbing the CPU) is still removed."""
    trace = [
        {"event": "sched_enqueue", "timestamp_ns": 1000, "cgroup_id": 100, "cpu": 0, "tid": 1, "comm": "v"},
        # another cgroup switches in at 1020 (steals the CPU)
        {"event": "sched_switch", "timestamp_ns": 1020, "cgroup_id": 200, "cpu": 0, "tid": 2, "comm": "n",
         "prev_cgroup_id": 100, "prev_pid": 1, "prev_tid": 1, "prev_comm": "v"},
        # victim finally switches in at 1080
        {"event": "sched_switch", "timestamp_ns": 1080, "cgroup_id": 100, "cpu": 0, "tid": 1, "comm": "v",
         "prev_cgroup_id": 200, "prev_pid": 2, "prev_tid": 2, "prev_comm": "n"},
    ]
    path = _write(trace)
    try:
        res = NoiseFreeAnalyzer(min_events=1).analyze_file(path, target_cgroups={100})
    finally:
        os.unlink(path)
    r = res[100]
    assert r.original_makespan == 80, r.original_makespan          # 1080 - 1000
    assert r.wait_cpu == 60, r.wait_cpu                            # [1020, 1080)
    assert r.noise_free_makespan == 20, r.noise_free_makespan
    print("ok: in-span CPU wait subtracted (noise_free=20)")


def test_dropped_events_trailer_rejected():
    """A trace_summary trailer reporting dropped events must reject the whole trace."""
    trace = [
        {"event": "sched_enqueue", "timestamp_ns": 1000, "cgroup_id": 100, "cpu": 0, "tid": 1, "comm": "v"},
        {"event": "sched_switch", "timestamp_ns": 1100, "cgroup_id": 100, "cpu": 0, "tid": 1, "comm": "v",
         "prev_cgroup_id": 0, "prev_pid": 0, "prev_tid": 0, "prev_comm": "idle"},
        {"event": "trace_summary", "dropped_events": 5},
    ]
    path = _write(trace)
    try:
        try:
            NoiseFreeAnalyzer(min_events=1).analyze_file(path, target_cgroups={100})
        except ValueError as e:
            assert "dropped" in str(e).lower(), str(e)
            print("ok: lossy trace rejected ->", str(e).split(";")[0])
            return
        raise AssertionError("expected ValueError on dropped-events trailer, got none")
    finally:
        os.unlink(path)


def test_zero_drops_trailer_ok():
    """A trace_summary trailer with dropped_events=0 must NOT reject."""
    trace = [
        {"event": "sched_enqueue", "timestamp_ns": 1000, "cgroup_id": 100, "cpu": 0, "tid": 1, "comm": "v"},
        {"event": "sched_switch", "timestamp_ns": 1100, "cgroup_id": 100, "cpu": 0, "tid": 1, "comm": "v",
         "prev_cgroup_id": 0, "prev_pid": 0, "prev_tid": 0, "prev_comm": "idle"},
        {"event": "trace_summary", "dropped_events": 0},
    ]
    path = _write(trace)
    try:
        res = NoiseFreeAnalyzer(min_events=1).analyze_file(path, target_cgroups={100})
    finally:
        os.unlink(path)
    assert res[100].noise_free_makespan == 100
    print("ok: dropped_events=0 trailer accepted")


def test_interval_merge_beats_naive_subtraction():
    """C3 ablation: when CPU and block waits OVERLAP in time, the merged union
    removes the overlap once, while naive per-resource subtraction double-removes it
    (and can drive noise_free negative). Proves the interval-merge advantage."""
    trace = [
        # victim cgroup 100, span [1000,1500] (makespan 500)
        # --- CPU wait [1100,1500): victim enqueued@1000, cg200 stole CPU@1100, victim ran@1500
        {"event": "sched_enqueue", "timestamp_ns": 1000, "cgroup_id": 100, "cpu": 0, "tid": 1},
        {"event": "sched_switch",  "timestamp_ns": 1100, "cgroup_id": 200, "cpu": 0, "tid": 2,
         "prev_cgroup_id": 100, "prev_pid": 1, "prev_tid": 1},
        {"event": "sched_switch",  "timestamp_ns": 1500, "cgroup_id": 100, "cpu": 0, "tid": 1,
         "prev_cgroup_id": 200, "prev_pid": 2, "prev_tid": 2},
        # --- BLOCK wait [1200,1500): victim insert@1050, cg200 issued@1200, victim issued@1500
        {"event": "block_rq_insert", "timestamp_ns": 1050, "cgroup_id": 100, "cpu": 0, "request_addr": 1, "rwbs": "R"},
        {"event": "block_rq_issue",  "timestamp_ns": 1200, "cgroup_id": 200, "cpu": 0, "request_addr": 2, "rwbs": "R"},
        {"event": "block_rq_issue",  "timestamp_ns": 1500, "cgroup_id": 100, "cpu": 0, "request_addr": 1, "rwbs": "R"},
    ]
    path = _write(trace)
    try:
        res = NoiseFreeAnalyzer(min_events=1).analyze_file(path, target_cgroups={100})
    finally:
        os.unlink(path)
    r = res[100]
    # cpu wait [1100,1500)=400, bio wait [1200,1500)=300; they overlap on [1200,1500)
    assert r.wait_cpu == 400, r.wait_cpu
    assert r.wait_bio == 300, r.wait_bio
    # merged union [1100,1500) = 400 (overlap removed once)
    assert r.total_unique_wait == 400, r.total_unique_wait
    # naive sum = 400+300 = 700 (overlap double-counted)
    assert r.naive_total_wait == 700, r.naive_total_wait
    assert r.naive_total_wait > r.total_unique_wait
    # merged makespan valid (500-400=100); naive over-removes to an impossible negative (500-700=-200)
    assert r.noise_free_makespan == 100, r.noise_free_makespan
    assert r.noise_free_naive == -200, r.noise_free_naive
    assert r.noise_free_naive < 0 < r.noise_free_makespan
    print(f"ok: merge vs naive — merged noise_free={r.noise_free_makespan} (valid), "
          f"naive={r.noise_free_naive} (over-removed, negative); overlap removed once")


if __name__ == "__main__":
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_") and callable(v)]
    for fn in fns:
        fn()
    print(f"\nALL {len(fns)} TESTS PASSED")
