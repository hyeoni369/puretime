#!/usr/bin/env python3
"""Context-switch microbenchmark — PureTime overhead 측정용 (실험 5 / fig3).

오버헤드 실험의 딜레마: PureTime의 시간 오버헤드는 <1%로 매우 낮아서, victim을 부하와
같은 코어에서 경쟁시키면 CPU 몫 변동(±15~33%)이 그 신호를 묻고, 경쟁을 없애면 추적할
이벤트가 사라져 오버헤드가 0이 된다. 이 벤치마크는 그 둘을 분리한다:

  - 부모와 자식이 pipe로 핑퐁(write→read)하며 매 라운드 2번의 context switch를 *결정적으로*
    생성한다. 둘 다 같은 코어에 핀되지만 번갈아 실행(협력)이라 CPU 쟁탈(경쟁 노이즈)이 없다.
  - 따라서 sched_switch 이벤트만 일정하게 만들어지고, victim 실행시간은 안정적이다.
  - PureTime ON이면 매 switch마다 커널 훅(ring buffer write)이 돌아 victim이 느려진다.
    그 차이가 순수 오버헤드다 — 노이즈 없이.

`COMPUTE_PER_ROUND`로 라운드당 계산을 넣어 switch 빈도(=이벤트율)를 낮출 수 있다. 0이면
최대 이벤트율(순수 핑퐁), 크면 현실적인 낮은 이벤트율. 이 손잡이를 sweep하면 "이벤트율 vs
오버헤드" 곡선이 나온다 — 현실적 율에서 <1%, 높은 율에서 측정 가능한 양수.

Env: ROUNDS(핑퐁 횟수), COMPUTE_PER_ROUND(라운드당 정수 덧셈 수 = 이벤트율 손잡이).
출력: {elapsed_ms, rounds, switches=2*rounds, switch_rate_per_sec}.
"""
import os
import time
import json

ROUNDS = int(os.environ.get("ROUNDS", "200000"))
COMPUTE = int(os.environ.get("COMPUTE_PER_ROUND", "0"))


def spin(n):
    x = 0
    for _ in range(n):
        x += 1
    return x


def main():
    r1, w1 = os.pipe()   # parent → child
    r2, w2 = os.pipe()   # child → parent
    pid = os.fork()
    if pid == 0:                      # child
        os.close(w1)
        os.close(r2)
        while os.read(r1, 1):
            if COMPUTE:
                spin(COMPUTE)
            try:
                os.write(w2, b"x")
            except BrokenPipeError:
                break
        os._exit(0)
    else:                            # parent
        os.close(r1)
        os.close(w2)
        start = time.perf_counter()
        for _ in range(ROUNDS):
            os.write(w1, b"x")
            os.read(r2, 1)
        elapsed = (time.perf_counter() - start) * 1000
        os.close(w1)                 # EOF → 자식 루프 종료
        os.waitpid(pid, 0)
        rate = (ROUNDS * 2) / (elapsed / 1000) if elapsed > 0 else 0
        print(json.dumps({
            "elapsed_ms": round(elapsed, 2),
            "rounds": ROUNDS,
            "switches": ROUNDS * 2,
            "switch_rate_per_sec": round(rate),
            "compute_per_round": COMPUTE,
        }))


if __name__ == "__main__":
    main()
