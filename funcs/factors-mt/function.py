#!/usr/bin/env python3
"""FaaSDom factors — multi-worker variant (funcs/factors와 동일 trial-division).

R-04 attribution ablation용 (funcs/float-mt와 동일 패턴): WORKERS(기본 2)개 프로세스가
탐색 구간 [1, sqrt(n)]을 반씩 나눠 같은 코어에서 실행 → sibling 간 self-wait.
총 연산량은 funcs/factors와 동일. 출처: FaaSDom (Maissen et al., ICPE'20) + 워커 분할.
"""
import sys
import os
import math
import time
import json
import multiprocessing as mp


def factors_range(num, lo, hi):
    n_factors = []
    for i in range(lo, hi):
        if num % i == 0:
            n_factors.append(i)
            if num // i != i:
                n_factors.append(num // i)
    return n_factors


def worker(num, lo, hi, q):
    q.put(factors_range(num, lo, hi))


def main():
    n = int(sys.argv[1]) if len(sys.argv) > 1 else 2688834647444046
    workers = int(os.environ.get("WORKERS", "2"))
    end = math.floor(math.sqrt(n)) + 1
    step = max(1, (end - 1) // workers)
    bounds = [(1 + k * step, end if k == workers - 1 else 1 + (k + 1) * step) for k in range(workers)]
    start = time.perf_counter()
    q = mp.Queue()
    procs = [mp.Process(target=worker, args=(n, lo, hi, q)) for lo, hi in bounds]
    for p in procs:
        p.start()
    result = []
    for _ in procs:
        result.extend(q.get())
    for p in procs:
        p.join()
    result.sort()
    elapsed_ms = (time.perf_counter() - start) * 1000
    print(json.dumps({"elapsed_ms": round(elapsed_ms, 2), "n_factors": len(result), "workers": workers}))


if __name__ == "__main__":
    main()
