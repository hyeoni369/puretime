#!/usr/bin/env python3
"""Concurrent multi-resource victim — Experiment 2 (interval-merge / C3).

This is the ONE experiment whose victim is deliberately *concurrent* (the other
experiments use single-threaded victims, per PureTime's core makespan model). The
interval-merge claim (C3) is specifically about OVERLAPPING wait intervals, and
overlap only exists when a cgroup waits on two resources at the SAME wall-clock time.
A single thread serialises its resources (while it is preempted it is not also blocked
on I/O, and while it is blocked in a throttled write it is not runnable), so its CPU
wait and Block wait are largely disjoint → tiny overlap → nothing for the merge to fix.
Real pipelined serverless functions (ExCamera NSDI'17, Sprocket SoCC'18: decode→
process→encode→upload) ARE concurrent, so this victim runs CPU and I/O on separate
threads that are sized to finish together:

  cpu_worker   : grayscale a synthetic frame, CPU_ITERS times (register/L1-bound,
                 preempted under CPU stress → CPU wait).
  block_worker : buffered writes, NO fsync, BLOCK_ITERS times → the writeback drains
                 dirty pages as an async stream of block requests that queue at the I/O
                 scheduler (insert→issue, captured) under fio contention → Block wait.
                 A low vm.dirty_bytes (set by the harness) forces that writeback to
                 happen DURING the run.
  net_worker   : (optional) TCP uploads to MinIO → net-TX qdisc wait.

Because the workers run CONCURRENTLY and are balanced to end together, their waits
overlap in wall time. The cgroup-level union (interval-merge) counts the overlap once →
noise_free_merged ≈ solo (valid). Naive sum-of-waits counts it on every resource →
noise_free_naive falls well below solo (can go negative) — the over-subtraction the
merge exists to prevent.

Balance the two workers with CPU_ITERS / BLOCK_ITERS / GRAYSCALE_PASSES / CHUNK_KB so
that, UNDER the target stress mix, cpu_worker and block_worker take about the same wall
time (both on the critical path → merged stays ≈ solo, no off-path over-removal).

Env: CPU_ITERS, BLOCK_ITERS, GRAYSCALE_PASSES, CHUNK_KB, UPLOAD, NET_ITERS, FRAME_W/H.
(VIDEO_FRAMES, if set, is the default for both CPU_ITERS and BLOCK_ITERS.)
"""
import os
import time
import json
import threading
import numpy as np

FRAMES = int(os.environ.get("VIDEO_FRAMES", "4000"))
CPU_ITERS = int(os.environ.get("CPU_ITERS", str(FRAMES)))
BLOCK_ITERS = int(os.environ.get("BLOCK_ITERS", str(FRAMES)))
NET_ITERS = int(os.environ.get("NET_ITERS", "0"))
W = int(os.environ.get("FRAME_W", "640"))
H = int(os.environ.get("FRAME_H", "480"))
CPU_PASSES = int(os.environ.get("GRAYSCALE_PASSES", "3"))
CHUNK = int(os.environ.get("CHUNK_KB", "256")) * 1024
WORK = os.environ.get("WORK_DIR", "/tmp/video_test")
DO_UPLOAD = os.environ.get("UPLOAD", "0") != "0"
MINIO_ENDPOINT = os.environ.get("MINIO_ENDPOINT", "http://165.194.27.225:9000")
MINIO_AK = os.environ.get("MINIO_ACCESS_KEY", "minioadmincslab")
MINIO_SK = os.environ.get("MINIO_SECRET_KEY", "minioadmincslab")
BUCKET = os.environ.get("MINIO_BUCKET", "uploads")
COEF = np.array([0.114, 0.587, 0.299], dtype=np.float32)

# Per-thread CPU affinity (the crux of the overlap): the CPU worker is pinned to a core
# that the co-tenant stressor saturates (→ continuous CPU wait), while the I/O workers sit
# on a SEPARATE free core so they are NOT CPU-starved and can keep issuing requests that
# queue at the throttled qdisc / I/O scheduler (→ continuous Net/Block wait). One core can't
# do both: a CPU-contended core would starve the I/O thread, collapsing the I/O wait into an
# app-stall the analyzer can't attribute. With the two threads on two cores their waits run
# concurrently → at the cgroup level CPU wait ∩ I/O wait overlap (the unit-test scenario).
CPU_AFFINITY = os.environ.get("CPU_AFFINITY", "")
NET_AFFINITY = os.environ.get("NET_AFFINITY", "")
BLOCK_AFFINITY = os.environ.get("BLOCK_AFFINITY", "")


def _pin(aff):
    if aff:
        try:
            os.sched_setaffinity(0, {int(x) for x in aff.split(",")})
        except Exception:
            pass


def cpu_worker(base):
    _pin(CPU_AFFINITY)
    acc = 0.0
    for _ in range(CPU_ITERS):
        g = base
        for _ in range(CPU_PASSES):
            g = np.sqrt((base @ COEF) + 1.0)
        acc += float(g.sum())
    return acc


def block_worker(payload, pid):
    _pin(BLOCK_AFFINITY)
    # buffered writes, no fsync → async writeback queues at the I/O scheduler (block wait)
    fd = os.open(os.path.join(WORK, f"blk_{pid}.dat"),
                 os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o644)
    try:
        for _ in range(BLOCK_ITERS):
            os.write(fd, payload)
    finally:
        os.close(fd)


def net_worker(payload, pid):
    _pin(NET_AFFINITY)
    import boto3
    from botocore.client import Config
    s3 = boto3.client("s3", endpoint_url=MINIO_ENDPOINT,
                      aws_access_key_id=MINIO_AK, aws_secret_access_key=MINIO_SK,
                      config=Config(signature_version="s3v4", retries={"max_attempts": 1}),
                      region_name="us-east-1")
    for i in range(NET_ITERS):
        try:
            s3.put_object(Bucket=BUCKET, Key=f"n_{pid}_{i}", Body=payload)
        except Exception:
            pass


def main():
    os.makedirs(WORK, exist_ok=True)
    pid = os.getpid()
    base = np.random.RandomState(0).randint(0, 255, (H, W, 3), dtype=np.uint8).astype(np.float32)
    payload = os.urandom(CHUNK)

    threads = []
    if CPU_ITERS > 0:
        threads.append(threading.Thread(target=cpu_worker, args=(base,)))
    if BLOCK_ITERS > 0:
        threads.append(threading.Thread(target=block_worker, args=(payload, pid)))
    if DO_UPLOAD and NET_ITERS > 0:
        threads.append(threading.Thread(target=net_worker, args=(payload, pid)))

    t0 = time.perf_counter()
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    total_ms = (time.perf_counter() - t0) * 1000
    print(json.dumps({
        "cpu_iters": CPU_ITERS, "block_iters": BLOCK_ITERS, "net_iters": NET_ITERS,
        "passes": CPU_PASSES, "chunk_kb": CHUNK // 1024,
        "total_ms": round(total_ms, 1),
    }))


if __name__ == "__main__":
    main()
