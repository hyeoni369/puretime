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

**Invariants the implementation must hold:** `noise_free ≤ wall_clock`; every `wait_* ≥ 0`; merged wait union `≤ Σ(intervals)` and `≤ wall_clock`; attribution sums to 100% (±ε); a trace with ring-buffer drops must be rejected, not silently measured.

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
There is **no automated unit-test suite yet** (no pytest, no `requirements.txt`). The contract specifies the Analyzer (interval-merge/attribution — pure functions) *should* be TDD'd with hand-crafted JSONL and hand-computed expected values; the eBPF capture is validated empirically (idle → wait≈0; single-resource load → only that resource's events). End-to-end orchestration lives in `tests/run_with_function.sh`, `tests/run_tests_with_benchmark.sh`, and `experiments/exp_*.sh`. Note: the README's `tests/run_tests.sh` is stale (the file no longer exists).

### Pre-requirements for valid measurement (non-obvious; see README)
- Disable NIC offloads: `ethtool -K <iface> tso off gso off gro off lro off`.
- Block scheduler must not be `[none]` (set `mq-deadline` or `bfq` via `/sys/block/<dev>/queue/scheduler`).
- Network victims need a MinIO server + an `uploads` bucket (network is **TX-only**, so use the upload path).

## Architecture: the three-stage pipeline

```
kernel eBPF (Tracer) --256MB ring buffer--> userspace Loader (JSONL) --file--> Python Analyzer (makespan)
   src/puretime.bpf.c                            src/puretime.c                   tests/noise_free_makespan.py
```

The whole system is glued by **`src/puretime.h`** — the binary contract shared by kernel and userspace. It defines the `event_type` enum and the per-subsystem structs (`sched_event`, `net_event`, `block_event`, `softirq_event`), all prefixed with a common `event_header` (`timestamp_ns`, `cgroup_id`, `cpu`, `event_type`). Changing a field here means touching all three stages.

**Tracer (`src/puretime.bpf.c`)** — 12 eBPF programs. Emits binary structs to the `events` ring buffer via `bpf_ringbuf_reserve/submit` (no JSON in the kernel). Hooks: `fentry/enqueue_task` + `tp_btf/sched_switch` (sched), `tp_btf/net_dev_{queue,start_xmit,xmit}`, `tp_btf/block_rq_{insert,issue,complete}`, `tp_btf/softirq_{entry,exit}`. cgroup attribution differs per subsystem and is the subtlest part:
- sched: walk `task → cgroups → dfl_cgrp → kn → id`.
- block/softirq: `bpf_get_current_cgroup_id()`.
- network: a socket runs in softirq context where the cgroup reads as root, so `fentry/tcp_sendmsg` (process context) records `socket → cgroup_id` into the `tracked_sockets` hash map, and the net hooks look it up there first, falling back to the socket read. `tcp_close` cleans the map.
- Filters: drops `cgroup_id ≤ 1` (root/idle); containers are cgroup level ≥ 2; softirq keeps only NET_TX/NET_RX/BLOCK vectors. On `sched_switch`, a preempted prev task (`prev_state==0`) also gets a synthesized `sched_enqueue`.

**Loader (`src/puretime.c`)** — libbpf userspace. `main()` opens/loads/attaches the generated skeleton, creates the output file `/var/log/puretime/trace_*.jsonl`, then `ring_buffer__poll(100ms)` in a loop until duration/SIGINT. `handle_event()` dispatches on `event_type` range and serializes each event to one JSONL line via the buffered `json_writer` (`src/json_writer.c`, 4KB buffer).

**Analyzer (`tests/noise_free_makespan.py`)** — two passes: (1) detect cgroups (count events, record first/last timestamp), (2) read all events, **sort by `timestamp_ns`** (ring-buffer ordering isn't guaranteed across CPUs), then process. Wait is computed identically for every resource by matching a *start* event to its *completion* by a correlation key, then charging the gap where **another** cgroup got serviced first:

| resource | start → complete | key | wait interval |
|---|---|---|---|
| CPU | `sched_enqueue` → `sched_switch` | tid | other cgroup switched-in on the same CPU between my enqueue and my switch |
| net | `net_dev_queue` → `net_dev_start_xmit` | skb_addr | other cgroup's packet dequeued in between |
| block | `block_rq_insert` → `block_rq_issue` | request_addr | other cgroup's request issued in between |
| softirq | `softirq_entry` → `softirq_exit` (per CPU) | cpu | duration split by per-cgroup event-count ratio into self/other |

Intervals are stored as `portion` interval sets so overlaps merge automatically. Final result per cgroup:
`noise_free_makespan = (last_ts − first_ts) − interval_sum(cpu ∪ net ∪ bio ∪ softirq_other)`.

**Data-flow gotchas when auditing/changing the Analyzer:** `net_dev_xmit` and `block_rq_complete` are emitted and written to JSONL but **not consumed** by `noise_free_makespan.py` (they feed the auxiliary `tests/analyze_trace.py`). `softirq_self` is computed and reported but **not** part of the subtracted union — only `softirq_other` is.

## Other directories
- `funcs/` — victim workloads (compression, graph-bfs, network-uploader, thumbnailer, udp-sender, video-processing).
- `experiments/` — experiment runners (`exp_accuracy_by_type.sh`, `exp_overhead_{time,resource}.sh`), figure generation (`plot_evaluation.py`), and its own (older) copy of `noise_free_makespan.py`. When fixing the Analyzer, check whether `experiments/noise_free_makespan.py` needs the same change.
- `libbpf/`, `bpftool/` — git submodules; `vmlinux/` — vendored per-arch `vmlinux.h` for CO-RE.
- Build env: `flake.nix` (Nix), `dev.dockerfile` + `.devcontainer/`.
