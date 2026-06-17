#!/usr/bin/env bash
# 실험 5 (overhead) — PureTime 시간 오버헤드 vs 커널 이벤트율 (fig3).
#
# 측정 난점: PureTime의 시간 오버헤드는 <1%로 매우 낮아, victim을 부하와 같은 코어에서
#   경쟁시키면 CPU 몫 변동(±15~33%)이 신호를 묻고(음수 오버헤드 아티팩트), 경쟁을 없애면
#   추적할 이벤트가 사라져 오버헤드가 0이 된다. 해결책 = ctxsw-bench victim:
#   부모-자식이 pipe로 핑퐁하며 sched_switch를 *결정적으로* 생성하되, 같은 코어에서 협력적으로
#   번갈아 실행 → CPU 쟁탈(경쟁 노이즈) 없이 이벤트율만 제어. PureTime 오버헤드는 추적 이벤트
#   수에 비례하므로, 이벤트율(COMPUTE_PER_ROUND 손잡이)을 sweep하면 노이즈 없는 단조-양수
#   "이벤트율 vs 오버헤드" 곡선이 나온다 (fig3, plot_overhead_ctxsw.py).
#
# 동일 워크로드를 PureTime ON/OFF로 K회 측정(순서 counterbalance), victim self-reported
#   elapsed_ms(perf_counter)로 비교. 측정 동안 CPU 터보(boost) off로 주파수 변동 억제.
#
# 사용법: sudo bash experiments/exp_overhead_ctxsw.sh [출력디렉토리]
set +e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PURETIME_DIR="$(dirname "$SCRIPT_DIR")"
OUTPUT_DIR="${1:-$PURETIME_DIR/experiments/data/overhead_ctxsw}"
VICTIM_IMAGE="ctxsw-bench"
CORE="${CORE:-2}"                 # victim(부모+자식)을 핀할 코어. 코어0은 OS/PureTime drain용으로 비움.
ITERATIONS="${ITERATIONS:-15}"
# 이벤트율 sweep: "COMPUTE:ROUNDS" 쌍. COMPUTE_PER_ROUND↑ → switch율↓(이벤트율↓). ROUNDS는
#   각 점의 victim 실행시간을 ~1.5~2.5s로 맞추려 조절. 측정 가능 구간(~28K~720K switch/s)에 집중.
SWEEP="${SWEEP:-0:400000 300:180000 800:120000 2000:80000 4500:45000}"

mkdir -p "$OUTPUT_DIR" 2>/dev/null || { echo "출력 디렉토리 생성 실패: $OUTPUT_DIR"; exit 1; }
RESULTS="$OUTPUT_DIR/results.csv"

# CPU 터보 off (측정 분산 감소), EXIT 트랩으로 복원
ORIG_BOOST=""
if [ -w /sys/devices/system/cpu/cpufreq/boost ]; then
    ORIG_BOOST=$(cat /sys/devices/system/cpu/cpufreq/boost)
    echo 0 > /sys/devices/system/cpu/cpufreq/boost 2>/dev/null
fi
restore() {
    [ -n "$ORIG_BOOST" ] && echo "$ORIG_BOOST" > /sys/devices/system/cpu/cpufreq/boost 2>/dev/null
    pkill -9 -x puretime 2>/dev/null
    docker ps -aq | xargs -r docker rm -f >/dev/null 2>&1
}
trap restore EXIT INT TERM

# victim 빌드
DOCKER_BUILDKIT=0 docker build -t "$VICTIM_IMAGE" "$PURETIME_DIR/funcs/ctxsw-bench" >/dev/null 2>&1 \
    || { echo "victim 빌드 실패"; exit 1; }

PURETIME_BIN="$PURETIME_DIR/src/puretime" CORE="$CORE" ITERATIONS="$ITERATIONS" \
SWEEP="$SWEEP" RESULTS="$RESULTS" python3 - <<'PY'
import os, subprocess, json, time, csv, statistics as st, sys
CORE=os.environ["CORE"]; K=int(os.environ["ITERATIONS"])
BIN=os.environ["PURETIME_BIN"]; RESULTS=os.environ["RESULTS"]
SWEEP=[tuple(map(int,p.split(":"))) for p in os.environ["SWEEP"].split()]

def run_victim(compute, rounds):
    cid=subprocess.check_output(["docker","create",f"--cpuset-cpus={CORE}",
        "-e",f"COMPUTE_PER_ROUND={compute}","-e",f"ROUNDS={rounds}","ctxsw-bench"]).decode().strip()
    subprocess.run(["docker","start",cid],stdout=subprocess.DEVNULL)
    subprocess.run(["docker","wait",cid],stdout=subprocess.DEVNULL)
    logs=subprocess.check_output(["docker","logs",cid],stderr=subprocess.DEVNULL).decode()
    subprocess.run(["docker","rm","-f",cid],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
    for line in logs.splitlines():
        try:
            d=json.loads(line)
            if "elapsed_ms" in d: return d
        except: pass

def with_pt(compute, rounds):
    pt=subprocess.Popen([BIN,"-t","120"],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
    time.sleep(2); d=run_victim(compute,rounds); time.sleep(0.3); pt.terminate()
    try: pt.wait(timeout=5)
    except: subprocess.run(["pkill","-9","-x","puretime"])
    time.sleep(0.3); return d

f=open(RESULTS,"w",newline=""); wr=csv.writer(f)
wr.writerow(["compute","rounds","iteration","switch_rate","without_ms","with_ms","overhead_pct"]); f.flush()
for compute,rounds in SWEEP:
    run_victim(compute,rounds); time.sleep(0.3)   # warmup
    ovs=[]
    for i in range(K):
        # counterbalance: 홀수 iter without→with, 짝수 with→without (잔여 드리프트 bias 상쇄)
        if i%2==0: wo=run_victim(compute,rounds); time.sleep(0.2); w=with_pt(compute,rounds)
        else:      w=with_pt(compute,rounds);     time.sleep(0.2); wo=run_victim(compute,rounds)
        if wo and w and wo["elapsed_ms"]>0:
            ov=(w["elapsed_ms"]-wo["elapsed_ms"])/wo["elapsed_ms"]*100; ovs.append(ov)
            wr.writerow([compute,rounds,i+1,wo["switch_rate_per_sec"],
                         wo["elapsed_ms"],w["elapsed_ms"],round(ov,3)]); f.flush()
        time.sleep(0.2)
    if ovs:
        sys.stderr.write(f"  COMPUTE={compute} switch~{wo['switch_rate_per_sec']}/s "
                         f"→ overhead {st.mean(ovs):+.2f}% (neg {sum(1 for x in ovs if x<0)}/{len(ovs)})\n")
f.close()
PY

echo "실험5(ctxsw overhead) 완료: $RESULTS ($(grep -c , "$RESULTS") rows)"
