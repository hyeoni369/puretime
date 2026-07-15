#!/usr/bin/env python3
"""ServerlessBench sequential ALU — multi-worker variant (funcs/sequential와 동일 루프).

R-04 attribution ablation용 (funcs/float-mt와 동일 패턴): WORKERS(기본 2)개 프로세스가
times를 반씩 나눠 같은 코어에서 실행 → sibling 간 self-wait. 총 연산량 동일.
출처: ServerlessBench (Yu et al., SoCC'20) + 워커 분할.
"""
import sys
import os
import random
import time
import json
import multiprocessing as mp


def alu(times):
    a = random.randint(10, 100)
    b = random.randint(10, 100)
    temp = 0
    for i in range(times):
        if i % 4 == 0:
            temp = a + b
        elif i % 4 == 1:
            temp = a - b
        elif i % 4 == 2:
            temp = a * b
        else:
            temp = a / b
    return temp


def worker(times, q):
    q.put(alu(times))


def main():
    times = int(sys.argv[1]) if len(sys.argv) > 1 else 10000000
    workers = int(os.environ.get("WORKERS", "2"))
    start = time.perf_counter()
    q = mp.Queue()
    procs = [mp.Process(target=worker, args=(times // workers, q)) for _ in range(workers)]
    for p in procs:
        p.start()
    temp = [q.get() for _ in procs][-1]
    for p in procs:
        p.join()
    elapsed_ms = (time.perf_counter() - start) * 1000
    print(json.dumps({"elapsed_ms": round(elapsed_ms, 2), "result": temp, "workers": workers}))


if __name__ == "__main__":
    main()
