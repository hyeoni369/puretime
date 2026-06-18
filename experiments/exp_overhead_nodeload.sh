#!/usr/bin/env bash
# fig3-2 (overhead) — PureTime 시간 오버헤드 vs 노드 부하(co-tenant 이벤트율).
#
# 기존 fig3(exp_overhead_ctxsw.sh)는 victim 하나만 코어에 돌려 victim '자기 이벤트율'만 sweep
# → 노드가 조용할 때의 오버헤드(공유 ring 스핀락 경합 항=0). 그러나 PureTime이 *필요한* 상황은
# 노드가 바쁜(co-tenant 경쟁=노이즈) 멀티테넌트다. 여기선 victim 율을 현실값 하나로 고정하고
# 배경 부하 컨테이너(ctxsw-bench, victim과 *다른 코어*)를 0→N개로 sweep해 노드 전체 이벤트율을
# 올리며 PureTime ON/OFF victim 지연 차이를 측정한다. ring buffer가 전(全) CPU 공유 단일 맵
# (스핀락 1개, puretime.bpf.c:21-24)이라 노드가 바쁠수록 victim 코어의 reserve도 더 기다린다
# → 그 노드-부하 의존 항을 실측. (배경은 victim과 다른 코어 → CPU 쟁탈 노이즈 없이 노드 이벤트율만↑)
#
# PureTime은 SIGINT로 정상 종료시켜 trace_summary(dropped_events)를 확보하고, 각 run의 trace는
# 측정 직후 삭제한다(노드 부하 하에선 trace가 GB급으로 커져 디스크를 채우므로). dropped>0이면
# 그 부하 레벨은 PureTime이 못 버티는 영역 = figure에 한계선으로 표시.
#
# 사용법: sudo bash experiments/exp_overhead_nodeload.sh [출력디렉토리]
set +e
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PURETIME_DIR="$(dirname "$SCRIPT_DIR")"
OUTPUT_DIR="${1:-$PURETIME_DIR/experiments/data/overhead_nodeload}"
VICTIM_IMAGE="ctxsw-bench"
VICTIM_CORE="${VICTIM_CORE:-2}"        # victim 핀 코어 (코어0=drain용으로 비움)
BG_CORE_START="${BG_CORE_START:-4}"    # 배경 부하 컨테이너 시작 코어 (victim/drain 코어 회피)
ITERATIONS="${ITERATIONS:-6}"
VICTIM_COMPUTE="${VICTIM_COMPUTE:-4500}"     # victim 율 고정 (저율 ~28K/s, baseline 낮음)
VICTIM_ROUNDS="${VICTIM_ROUNDS:-60000}"      # ~4초
BG_SWEEP="${BG_SWEEP:-0 1 3 6 10}"     # 배경 컨테이너 수 = 노드 부하 레벨
BG_COMPUTE="${BG_COMPUTE:-2000}"       # 배경 율 (각 ~60K/s; trace 작게 유지하려 0=순수핑퐁 대신 완만)
BG_ROUNDS="${BG_ROUNDS:-2000000000}"   # 측정 내내 살아있게 충분히 큼

mkdir -p "$OUTPUT_DIR" 2>/dev/null || { echo "출력 디렉토리 생성 실패: $OUTPUT_DIR"; exit 1; }
RESULTS="$OUTPUT_DIR/results.csv"

# CPU 터보 off (측정 분산 감소), EXIT 트랩으로 복원 + 배경/puretime/docker 정리
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

DOCKER_BUILDKIT=0 docker build -t "$VICTIM_IMAGE" "$PURETIME_DIR/funcs/ctxsw-bench" >/dev/null 2>&1 \
    || { echo "victim 빌드 실패"; exit 1; }

PURETIME_BIN="$PURETIME_DIR/src/puretime" VICTIM_CORE="$VICTIM_CORE" BG_CORE_START="$BG_CORE_START" \
ITERATIONS="$ITERATIONS" VICTIM_COMPUTE="$VICTIM_COMPUTE" VICTIM_ROUNDS="$VICTIM_ROUNDS" \
BG_SWEEP="$BG_SWEEP" BG_COMPUTE="$BG_COMPUTE" BG_ROUNDS="$BG_ROUNDS" RESULTS="$RESULTS" python3 - <<'PY'
import os, subprocess, json, time, csv, statistics as st, sys, signal, glob, re
VC=os.environ["VICTIM_CORE"]; BGC0=int(os.environ["BG_CORE_START"])
K=int(os.environ["ITERATIONS"]); BIN=os.environ["PURETIME_BIN"]; RESULTS=os.environ["RESULTS"]
VCOMPUTE=os.environ["VICTIM_COMPUTE"]; VROUNDS=os.environ["VICTIM_ROUNDS"]
BG_SWEEP=[int(x) for x in os.environ["BG_SWEEP"].split()]
BGCOMPUTE=os.environ["BG_COMPUTE"]; BGROUNDS=os.environ["BG_ROUNDS"]
TRACEDIR="/var/log/puretime"

def read_ctxt():
    for line in open("/proc/stat"):
        if line.startswith("ctxt"): return int(line.split()[1])
    return 0

def run_victim():
    cid=subprocess.check_output(["docker","create",f"--cpuset-cpus={VC}",
        "-e",f"COMPUTE_PER_ROUND={VCOMPUTE}","-e",f"ROUNDS={VROUNDS}","ctxsw-bench"]).decode().strip()
    subprocess.run(["docker","start",cid],stdout=subprocess.DEVNULL)
    subprocess.run(["docker","wait",cid],stdout=subprocess.DEVNULL)
    logs=subprocess.check_output(["docker","logs",cid],stderr=subprocess.DEVNULL).decode()
    subprocess.run(["docker","rm","-f",cid],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
    for line in logs.splitlines():
        try:
            d=json.loads(line)
            if "elapsed_ms" in d: return d
        except: pass

def start_bg(n):
    ids=[]
    for j in range(n):
        core=BGC0+j
        cid=subprocess.check_output(["docker","run","-d",f"--cpuset-cpus={core}",
            "-e",f"COMPUTE_PER_ROUND={BGCOMPUTE}","-e",f"ROUNDS={BGROUNDS}","ctxsw-bench"]).decode().strip()
        ids.append(cid)
    return ids

def stop_bg(ids):
    for cid in ids:
        subprocess.run(["docker","rm","-f",cid],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)

def with_pt():
    """PureTime ON으로 victim 측정. SIGINT 정상종료로 trace_summary(dropped) 확보 후 trace 삭제."""
    before=set(glob.glob(f"{TRACEDIR}/trace_*.jsonl"))
    pt=subprocess.Popen([BIN,"-t","120"],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
    time.sleep(2); d=run_victim(); time.sleep(0.3)
    pt.send_signal(signal.SIGINT)            # 정상 종료 → ring 비우고 trace_summary flush
    try: pt.wait(timeout=90)
    except: subprocess.run(["pkill","-9","-x","puretime"]); time.sleep(1)
    dropped=None
    for tf in set(glob.glob(f"{TRACEDIR}/trace_*.jsonl"))-before:
        try:
            last=subprocess.check_output(["tail","-c","200",tf]).decode("utf-8","ignore")
            m=re.search(r'"dropped_events":(\d+)',last)
            if m: dropped=int(m.group(1))
        except: pass
        try: os.remove(tf)                   # 디스크 보호: 측정 직후 즉시 삭제
        except: pass
    time.sleep(0.3); return d,dropped

f=open(RESULTS,"w",newline=""); wr=csv.writer(f)
wr.writerow(["bg_count","node_ctxt_per_sec","victim_switch_rate","iteration",
             "without_ms","with_ms","overhead_pct","dropped_events"]); f.flush()
for bg in BG_SWEEP:
    ids=start_bg(bg); time.sleep(2)   # 배경 안정화
    run_victim(); time.sleep(0.3)     # warmup
    ovs=[]; nrates=[]; drops=[]
    for i in range(K):
        c0=read_ctxt(); t0=time.time()
        # counterbalance: 홀짝 순서 교대 (잔여 드리프트 bias 상쇄)
        if i%2==0: wo=run_victim(); time.sleep(0.2); w,drop=with_pt()
        else:      w,drop=with_pt();     time.sleep(0.2); wo=run_victim()
        c1=read_ctxt(); t1=time.time()
        node_rate=(c1-c0)/(t1-t0) if t1>t0 else 0
        if wo and w and wo["elapsed_ms"]>0:
            ov=(w["elapsed_ms"]-wo["elapsed_ms"])/wo["elapsed_ms"]*100
            ovs.append(ov); nrates.append(node_rate)
            if drop is not None: drops.append(drop)
            wr.writerow([bg,round(node_rate),wo["switch_rate_per_sec"],i+1,
                         wo["elapsed_ms"],w["elapsed_ms"],round(ov,3),
                         drop if drop is not None else ""]); f.flush()
        time.sleep(0.2)
    stop_bg(ids); time.sleep(1)
    if ovs:
        dmax=max(drops) if drops else "?"
        sys.stderr.write(f"  bg={bg:2d} node~{round(st.mean(nrates)):>9}/s → "
                         f"overhead {st.mean(ovs):+.2f}% (neg {sum(1 for x in ovs if x<0)}/{len(ovs)}, "
                         f"max_drop {dmax})\n")
f.close()
PY
echo "실험(node-load overhead) 완료: $RESULTS ($(grep -c , "$RESULTS") rows)"
