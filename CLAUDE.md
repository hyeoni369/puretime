# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

PureTime is a research system (SoCC 2026 submission) that measures the **noise-free makespan** of serverless functions: it traces CPU-scheduling, network-TX, block-I/O, and softirq contention from kernel events via eBPF, attributes wait time to the co-tenant cgroups that caused it, and subtracts overlapping waits (via interval merge) to recover each cgroup's pure execution time — reference-free, from a single invocation.

## Project docs are the source of truth

Before doing project/experiment work, **read `docs/` first** — these define intent that the code alone does not:
- `docs/PureTime_*.pdf` — the paper (system design & implementation).
- `docs/claims-experiments-contract.md` — **single source of truth**: claims C1–C10 ↔ experiment mapping, priorities/status, implementation order, TDD layering, runtime invariants, scope/limitations, and the "experiment ↔ Claude Code" division of labor. Update its table as results land.
- `docs/puretime-experiment-design-final.md` — locked design of the 5 P0 experiments (method, victims, figures).

**Workflow rule (from the contract):** build the eBPF Tracer/Loader + Analyzer core *first*, then victims/harness/aggregation. Start work with an **audit** (correctness only, no style nits), keep **audit → human-classify → fix as three separate steps**, and don't fix everything in one pass. The `audit` branch is this audit phase.

**Invariants the implementation must hold:** `noise_free ≤ wall_clock`; every `wait_* ≥ 0`; merged wait union `≤ Σ(intervals)` and `≤ wall_clock`; attribution sums to 100% (±ε); a trace with ring-buffer drops must be rejected, not silently measured. *Enforced in code:* `_compute_results` asserts the first four; the loader emits a `trace_summary` trailer with the dropped-event count and the analyzer rejects (exit 2) any trace with `dropped_events > 0`.

**Scope (measured vs out of scope)** — see `docs/claims-experiments-contract.md` "Scope & Limitations":
- Removes **co-tenant** (container) contention only; **host/kernel/system (cgroup ≤ 1) CPU time is NOT removed** (treated as the function's real cost).
- CPU-wait model assumes **single-core pinning** (no cross-CPU migration tracking).
- **Network attribution is TCP-TX only**; **block attribution needs the io controller delegated to the container** (else falls back to current-cgroup).
- on-CPU IPC dilation (LLC/mem-bandwidth) is out of scope → noise stressors must be **register/L1-bound**, or the measured error absorbs dilation that PureTime cannot (and should not) remove.

## Build, run, analyze

```sh
# One-time: submodules (libbpf, bpftool) + system deps
git submodule update --init --recursive          # libbpf, bpftool; vmlinux/ is vendored
make install                                      # apt: libelf1 libelf-dev zlib1g-dev make clang llvm

make build                                        # -> make -C src; builds libbpf+bpftool, BPF obj, skeleton, links src/puretime
make -C src V=1                                   # verbose build (debug the Makefile pipeline)
make clean

# Run the tracer (REQUIRES root; writes JSONL). -t = duration in seconds, -v = verbose.
sudo src/puretime -v -t 10                        # -> /var/log/puretime/trace_YYYYMMDD_HHMMSS.jsonl

# Analyze a trace (Python). No requirements.txt — install manually:
pip install portion tqdm numpy pandas matplotlib
python3 tests/noise_free_makespan.py /var/log/puretime/trace_*.jsonl -j   # core: noise-free makespan, -j=JSON
python3 tests/analyze_trace.py       /var/log/puretime/trace_*.jsonl -o results.json   # latency percentiles
```

`noise_free_makespan.py` flags: `-m/--min-events N` (default 100), `-j/--json`, `-c/--cgroups-file <file>` (one cgroup id per line) to restrict analysis.

### Tests
Run `python3 tests/test_noise_free_makespan.py` — 9 assert-based unit tests (no pytest/`requirements.txt` beyond `portion`+`tqdm`): span-clamp/negative-makespan, ring-buffer-drop rejection (and `dropped_events=0` accepted), in-span CPU wait, CPU-3 leading-slice (and no phantom slice), block leading-slice (and no phantom slice), and the interval-merge-vs-naive ablation (merged valid vs naive over-removed). eBPF capture is validated empirically (idle → wait≈0; single-resource load → only that resource's events). End-to-end orchestration: `experiments/exp_*.sh` (accuracy `exp_accuracy_by_type.sh` + overhead `exp_overhead_{time,resource}.sh`). (옛 dev 러너 `tests/run_with_function.sh`·`run_tests_with_benchmark.sh`와 템플릿 CI/`dockerfile`은 stale로 삭제됨.)

### Pre-requirements for valid measurement (non-obvious; see README)
- Disable NIC offloads: `ethtool -K <iface> tso off gso off gro off lro off`.
- Block scheduler must not be `[none]` (set `mq-deadline` or `bfq` via `/sys/block/<dev>/queue/scheduler`).
- **Limit NCQ depth: `echo 2 > /sys/block/<dev>/device/queue_depth`** (restore to 32 after). At the default depth 32, NCQ dispatches many requests to the device at once so block contention hides in `issue→complete` device service time — which PureTime cannot see (`block_rq_complete` is `#if 0`), giving only ~39% removal. depth=2 serializes contention into the OS scheduler queue (`insert→issue`), which PureTime *does* measure → block removal rises to ~83–87% with `noise_free ≈ solo`. (depth=1 over-serializes and over-removes: `noise_free < solo`.) This is a measurement prerequisite analogous to disabling NIC offload; `exp_accuracy_by_type.sh` sets/restores it via `BLOCK_QUEUE_DEPTH` (default 2).
- Network victims need a MinIO server + an `uploads` bucket. Network attribution is **TCP-TX only** (sockets registered via `tcp_sendmsg`; UDP is not), so use a TCP upload path.
- Noise stressors should be **register/L1-bound** (out-of-scope IPC dilation otherwise inflates the measured error).

## Architecture: the three-stage pipeline

```
kernel eBPF (Tracer) --512MB ring buffer*--> userspace Loader (JSONL) --file--> Python Analyzer (makespan)
   (* 512MB is the high-load default; lower the events map to 32MB for the overhead experiment 4-1/실험5)
   src/puretime.bpf.c                            src/puretime.c                   tests/noise_free_makespan.py
```

The whole system is glued by **`src/puretime.h`** — the binary contract shared by kernel and userspace. It defines the `event_type` enum and the per-subsystem structs (`sched_event`, `net_event`, `block_event`, `softirq_event`), all prefixed with a common `event_header` (`timestamp_ns`, `cgroup_id`, `cpu`, `event_type`). Changing a field here means touching all three stages.

**Tracer (`src/puretime.bpf.c`)** — 8 active eBPF programs emitting binary structs to the `events` ring buffer via `bpf_ringbuf_reserve/submit` (no JSON in the kernel; a reserve failure bumps a per-CPU `dropped_events` counter). Hooks: `fentry/enqueue_task` + `tp_btf/sched_switch` (sched), `tp_btf/net_dev_{queue,start_xmit}`, `tp_btf/block_rq_{insert,issue}`, `tp_btf/softirq_{entry,exit}`, plus `fentry/tcp_sendmsg`+`tcp_close` (socket→cgroup tracking). `net_dev_xmit` and `block_rq_complete` are present but **disabled via `#if 0`** (never consumed by the analyzer; cuts ~1/3 of net & block event volume). cgroup attribution per subsystem:
- sched: walk `task → cgroups → dfl_cgrp → kn → id`.
- block: the originating blkcg via `rq → bio → bi_blkg → blkcg → css.cgroup → kn → id` (so buffered writeback submitted by a kworker is still attributed to the container), falling back to `bpf_get_current_cgroup_id()` for sync/direct I/O. **Requires the io controller delegated to the container cgroup.**
- softirq: `bpf_get_current_cgroup_id()`.
- network: `fentry/tcp_sendmsg` (process context) records `socket → cgroup_id` into the `tracked_sockets` hash map; net hooks look it up, falling back to the socket read. `tcp_close` cleans the map. **TCP-TX only** (UDP not registered).
- Filters: drops `cgroup_id ≤ 1` (root/idle); softirq keeps only NET_TX/NET_RX/BLOCK vectors. On `sched_switch`, a preempted prev (`prev_state==0`) also gets a synthesized `sched_enqueue`. `sched_event` no longer carries `comm`/`prev_comm` (removed to shrink the two hottest record types 88→56B).

**Loader (`src/puretime.c`)** — libbpf userspace. `main()` opens/loads/attaches the skeleton, creates `/var/log/puretime/trace_*.jsonl`, then `ring_buffer__poll(100ms)` until duration/SIGINT/first-drop. `handle_event()` serializes each event to one JSONL line via the buffered `json_writer` (`src/json_writer.c`, **4MB buffer** — amortizes write() syscalls so the single-threaded drain keeps the ring emptied). At shutdown it reads the per-CPU `dropped_events` map, appends a `{"event":"trace_summary","dropped_events":N}` trailer, and warns (and breaks early) if N>0.

**Analyzer (`tests/noise_free_makespan.py`)** — two passes: (1) detect cgroups (count events, record first/last timestamp), (2) read all events, **sort by `timestamp_ns`** (ring-buffer ordering isn't guaranteed across CPUs), then process. Wait is computed identically for every resource by matching a *start* event to its *completion* by a correlation key, then charging the gap where **another** cgroup got serviced first:

| resource | start → complete | key | wait interval |
|---|---|---|---|
| CPU | `sched_enqueue` → `sched_switch` | tid | other cgroup switched-in on the same CPU between my enqueue and my switch |
| net | `net_dev_queue` → `net_dev_start_xmit` | skb_addr | other cgroup's packet dequeued in between |
| block | `block_rq_insert` → `block_rq_issue` | request_addr | other cgroup's request issued in between |
| softirq | `softirq_entry` → `softirq_exit` (per CPU) | cpu | duration split by per-cgroup event-count ratio into self/other |

Intervals are stored as `portion` sets so overlaps merge automatically; the union is **clamped to the cgroup's `[first_ts,last_ts]` span** before subtraction (prevents out-of-span softirq_other from driving a negative makespan). CPU wait also counts the **leading slice** `[enqueue, next switch)` when a neighbor already held the core at the victim's enqueue. Final result per cgroup:
`noise_free_makespan = (last_ts − first_ts) − interval_sum((cpu ∪ net ∪ bio ∪ softirq_other) & span)`.
`_compute_results` asserts the runtime invariants and rejects (exit 2) any trace whose `trace_summary` trailer reports `dropped_events > 0`. It also emits a **naive (no-union) ablation** quantity `noise_free_naive` (per-resource waits summed without merge → can go negative) for the interval-merge comparison (C3 / exp 2-1). `softirq_self` is computed/reported but **not** subtracted (only `softirq_other` is).

**Two analyzer copies, keep in sync:** `tests/noise_free_makespan.py` (canonical; default output = human text, `-j` = detailed `_ns` JSON) and `experiments/noise_free_makespan.py` (identical logic + fixes, default output = jq-parseable JSON array consumed by `experiments/*.sh`). Apply every analyzer change to **both**.

## Other directories
- `funcs/` — victim workloads (float, compression, graph-bfs, network-uploader, thumbnailer, video-processing). **CPU victim/stressor = `float`** (register/L1-bound sqrt/sin/cos 루프 — graph-bfs는 메모리 바운드라 IPC dilation 누수 → 정확도 CPU 실험엔 부적합, graph-bfs는 오버헤드 실험용으로만). **Block victim = `compression`** (CPU+block 혼합; 순수 `dd`는 디스크 포화→seek dilation으로 부적합). (`udp-sender`는 UDP라 PureTime TCP-TX 범위 밖 → 삭제됨.)
- `experiments/` — experiment runners (`exp_accuracy_by_type.sh`, `exp_overhead_{time,resource}.sh`), figure generation (`plot_evaluation.py`), and its in-sync copy of `noise_free_makespan.py` (see the "two analyzer copies" note above — change both).
- `libbpf/`, `bpftool/` — git submodules; `vmlinux/` — vendored per-arch `vmlinux.h` for CO-RE.
- Build env: `flake.nix` (Nix), `dev.dockerfile` + `.devcontainer/`.
