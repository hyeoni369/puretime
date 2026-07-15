#!/usr/bin/env python3
"""FunctionBench float_operation — multi-worker variant (funcs/float와 동일 루프).

R-04 attribution ablation용: 실제 서버리스 런타임은 흔히 멀티스레드/멀티워커(gunicorn worker,
Node libuv pool, 파이프라인 스레드)다. WORKERS(기본 2)개 프로세스가 N을 1/WORKERS씩 나눠
같은 코어(컨테이너 cpuset)에서 돈다 → 총 연산량은 funcs/float와 동일하지만, 한 워커가 실행되는
동안 다른 워커는 *자기 cgroup* 뒤에서 runnable 대기(self-wait)한다.
- attribution ON  : sibling 대기는 같은 cgroup → 노이즈 아님 → noise-free = wall (정확)
- attribution OFF : 큐 대기 전부 차감 → 항상 한 워커가 대기 중이므로 noise-free ≈ 0 (파탄)
인자: N(총 반복) [rounds]. env WORKERS(기본 2).
출처: FunctionBench float_operation (Kim & Lee, SoCC'19) + 워커 분할.
"""
import sys
import os
import math
import time
import json
import multiprocessing as mp


def float_operation(N):
    acc = 0.0
    for i in range(N):
        sin_i = math.sin(i)
        cos_i = math.cos(i)
        sqrt_i = math.sqrt(i)
        acc += sin_i + cos_i + sqrt_i   # dead-code guard (원본은 결과 미사용)
    return acc


def worker(N, rounds, q):
    acc = 0.0
    for _ in range(rounds):
        acc += float_operation(N)
    q.put(acc)


def main():
    N = int(sys.argv[1]) if len(sys.argv) > 1 else 3_000_000
    rounds = int(sys.argv[2]) if len(sys.argv) > 2 else 1
    workers = int(os.environ.get("WORKERS", "2"))
    start = time.perf_counter()
    q = mp.Queue()
    procs = [mp.Process(target=worker, args=(N // workers, rounds, q)) for _ in range(workers)]
    for p in procs:
        p.start()
    acc = sum(q.get() for _ in procs)
    for p in procs:
        p.join()
    elapsed_ms = (time.perf_counter() - start) * 1000
    print(json.dumps({"elapsed_ms": round(elapsed_ms, 2), "acc": acc, "workers": workers}))


if __name__ == "__main__":
    main()
