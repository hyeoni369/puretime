#!/usr/bin/env python3
"""ServerlessBench sequential ALU (CPU register/L1 victim) — handler 제거.

원본: ServerlessBench Testcase2-Parallel-composition/sequential — 정수 ALU(+,-,*,/) 루프.
    for i in range(times): temp = a {+,-,*,/} b  (i%4로 연산 순환)
working set이 스칼라(a,b,temp)뿐 → register/L1 상주, LLC/메모리 대역폭 경합(= PureTime 범위
밖 IPC dilation) 없음. times로 solo time 조절. 출처: ServerlessBench (Yu et al., SoCC'20;
github.com/SJTU-IPADS/ServerlessBench, Mulan PSL v1)."""
import sys
import random
import time
import json


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


def main():
    times = int(sys.argv[1]) if len(sys.argv) > 1 else 10000000
    start = time.perf_counter()
    temp = alu(times)
    elapsed_ms = (time.perf_counter() - start) * 1000
    print(json.dumps({"elapsed_ms": round(elapsed_ms, 2), "result": temp}))


if __name__ == "__main__":
    main()
