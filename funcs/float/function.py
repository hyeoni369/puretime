#!/usr/bin/env python3
"""FunctionBench float_operation (CPU register/L1 victim) — handler 제거 + dead-code guard.

원본: FunctionBench cpu-memory/float_operation —
    for i in range(N): math.sin(i); math.cos(i); math.sqrt(i)
working set이 스칼라(i, sin_i/cos_i/sqrt_i)뿐이라 register/L1 상주 → LLC/메모리 대역폭 경합
(= PureTime 범위 밖 on-CPU IPC dilation)을 유발하지 않는다. (대조: graph-bfs/pagerank는
메모리 바운드라 컨텍스트 스위치 시 캐시가 쫓겨나 dilation 누수 → CPU victim으로 부적합.)
원본은 sin/cos/sqrt 결과를 미사용(dead code)이라, CPython/컴파일러 최적화에 견고하도록 acc
누적 guard만 더했다(연산량·프로파일 불변). 인자: N(반복=solo time knob) [rounds].
출처: FunctionBench (Kim & Lee, SoCC'19; github.com/kmu-bigdata/serverless-faas-workbench)."""
import sys
import math
import time
import json


def float_operation(N):
    acc = 0.0
    for i in range(N):
        sin_i = math.sin(i)
        cos_i = math.cos(i)
        sqrt_i = math.sqrt(i)
        acc += sin_i + cos_i + sqrt_i   # dead-code guard (원본은 결과 미사용)
    return acc


def main():
    N = int(sys.argv[1]) if len(sys.argv) > 1 else 5_000_000
    rounds = int(sys.argv[2]) if len(sys.argv) > 2 else 1
    start = time.perf_counter()
    acc = 0.0
    for _ in range(rounds):
        acc += float_operation(N)
    elapsed_ms = (time.perf_counter() - start) * 1000
    # self-report (overhead-e2e 실험이 docker stdout에서 파싱)
    print(json.dumps({"elapsed_ms": round(elapsed_ms, 2), "acc": acc}))


if __name__ == "__main__":
    main()
