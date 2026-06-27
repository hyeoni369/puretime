#!/usr/bin/env python3
"""FunctionBench iPerf3 (network TCP-TX victim) — handler 제거, forward(TX)만.

원본: FunctionBench network/iPerf3 — iperf3 -c로 sustained TCP throughput 측정.
forward(reverse=False) = client→server TX → PureTime net(TCP-TX, net_dev_queue→start_xmit)
측정 대상. reverse(-R)=RX는 PureTime 범위 밖이라 쓰지 않음. -t로 sustained 시간 제어 →
qdisc 큐에서 합성 net stressor(iperf3/병렬 업로드)와 경합. uploader(앱 업로드)와 대비되는
raw throughput net 프로파일. 출처: FunctionBench (Kim & Lee, SoCC'19)."""
import subprocess
import os
import time
import json


def main():
    server = os.environ.get('IPERF_SERVER', '165.194.27.225')
    port = os.environ.get('IPERF_PORT', '5201')
    # 고정 바이트 전송(-n): 경합 시 makespan이 늘어야 PureTime이 측정한다. 원본의 -t(시간 고정)는
    # 경합해도 throughput만 떨어지고 makespan은 불변이라 makespan-기반 측정엔 부적합 — 워크로드(TCP-TX)
    # 자체는 동일하고 종료 조건만 시간→바이트로 바꾼 것(uploader가 고정 데이터 업로드라 작동한 것과 동일).
    nbytes = os.environ.get('IPERF_BYTES', '5M')
    start = time.perf_counter()
    sp = subprocess.run(['iperf3', '-c', server, '-p', port, '-n', nbytes, '-Z', '-J'],
                        capture_output=True, text=True)
    elapsed_ms = (time.perf_counter() - start) * 1000
    send = 0.0
    try:
        send = json.loads(sp.stdout)['end']['sum_sent']['bits_per_second'] / 1e6 / 8
    except Exception:
        pass
    print(json.dumps({"elapsed_ms": round(elapsed_ms, 2), "send_mbit_s": round(send, 2)}))


if __name__ == "__main__":
    main()
