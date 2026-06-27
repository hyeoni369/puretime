#!/usr/bin/env python3
"""FaaSDom factors (CPU register/L1 victim) — HTTP handler / /proc 읽기 제거.

원본: FaaSDom python_factors — trial-division 인수분해
    for i in range(1, floor(sqrt(num))+1): if num % i == 0: ...
working set이 스칼라(i, num) + 작은 divisor 리스트뿐 → register/L1 상주, LLC/메모리 대역폭
경합(= PureTime 범위 밖 IPC dilation) 없음. 시간 ∝ sqrt(n)이라 n으로 solo time 조절.
출처: FaaSDom (Maissen et al., ICPE'20; github.com/faas-benchmarking/faasdom)."""
import sys
import math
import time
import json


def factors(num):
    n_factors = []
    for i in range(1, math.floor(math.sqrt(num)) + 1):
        if num % i == 0:
            n_factors.append(i)
            if num // i != i:
                n_factors.append(num // i)
    n_factors.sort()
    return n_factors


def main():
    n = int(sys.argv[1]) if len(sys.argv) > 1 else 2688834647444046
    start = time.perf_counter()
    result = factors(n)
    elapsed_ms = (time.perf_counter() - start) * 1000
    print(json.dumps({"elapsed_ms": round(elapsed_ms, 2), "n_factors": len(result)}))


if __name__ == "__main__":
    main()
