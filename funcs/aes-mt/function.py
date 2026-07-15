#!/usr/bin/env python3
"""vSwarm aes — multi-worker variant (funcs/aes와 동일 pyaes AES-CTR).

R-04 attribution ablation용 (funcs/float-mt와 동일 패턴): WORKERS(기본 2)개 프로세스가
rounds를 반씩 나눠 같은 코어에서 실행 → sibling 간 self-wait. 총 연산량 동일.
출처: vSwarm (Ustiugov et al., ASPLOS'21) + 워커 분할.
"""
import pyaes
import sys
import os
import time
import json
import multiprocessing as mp

KEY = b'6368616e676520746869732070617373'  # vSwarm 기본 키 (32 bytes)


def aes_ctr_encrypt(plaintext):
    counter = pyaes.Counter(initial_value=0)
    aes = pyaes.AESModeOfOperationCTR(KEY, counter=counter)
    return aes.encrypt(plaintext)


def worker(size, rounds, q):
    pt = b'A' * size
    total = 0
    for _ in range(rounds):
        total += len(aes_ctr_encrypt(pt))
    q.put(total)


def main():
    size = int(sys.argv[1]) if len(sys.argv) > 1 else 16384
    rounds = int(sys.argv[2]) if len(sys.argv) > 2 else 40
    workers = int(os.environ.get("WORKERS", "2"))
    start = time.perf_counter()
    q = mp.Queue()
    procs = [mp.Process(target=worker, args=(size, rounds // workers, q)) for _ in range(workers)]
    for p in procs:
        p.start()
    total = sum(q.get() for _ in procs)
    for p in procs:
        p.join()
    elapsed_ms = (time.perf_counter() - start) * 1000
    print(json.dumps({"elapsed_ms": round(elapsed_ms, 2), "size": size, "rounds": rounds, "bytes": total, "workers": workers}))


if __name__ == "__main__":
    main()
