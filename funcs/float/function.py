#!/usr/bin/env python3
"""float — register/L1-bound CPU benchmark (FunctionBench-style sqrt/sin/cos loop).

설계/contract 요구사항: CPU victim·stressor는 register/L1-bound 여야 한다.
working set이 FP 레지스터 + 소수의 지역변수뿐(큰 메모리 구조 없음)이라 L1에 상주 →
LLC/메모리 대역폭 경합(= PureTime 범위 밖 on-CPU IPC dilation)을 유발하지 않는다.
(대조: graph-bfs는 노드 100만개 인접리스트로 메모리 바운드 → 컨텍스트 스위치 시 캐시
쫓겨나 dilation 누수 → CPU victim/stressor로 부적합.)

인자: iters(반복 횟수, solo time knob) [rounds]. 고정 입력 → 결정적 solo time.
"""
import sys
import math
import time
import json


def main():
    iters = int(sys.argv[1]) if len(sys.argv) > 1 else 5_000_000
    rounds = int(sys.argv[2]) if len(sys.argv) > 2 else 1
    start = time.perf_counter()
    acc = 0.0
    for _ in range(rounds):
        x = 0.123456789
        for _ in range(iters):
            x = math.sqrt(abs(x) + 1.0)
            x += math.sin(x) * math.cos(x)
            acc += x
    elapsed_ms = (time.perf_counter() - start) * 1000
    # self-report (overhead-e2e 실험이 docker stdout에서 파싱); acc는 죽은코드 제거 방지용
    print(json.dumps({"elapsed_ms": round(elapsed_ms, 2), "acc": acc}))


if __name__ == "__main__":
    main()
