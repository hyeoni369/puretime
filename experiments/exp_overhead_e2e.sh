#!/usr/bin/env bash
# overhead-e2e: PureTime 시간 오버헤드 — 실제 victim with/without e2e (Clover식, 절댓값 없이 부호+CI).
#
# 각 victim(float=CPU, compression=block I/O, network-uploader=net)을 solo로 PureTime ON/OFF K회
# 측정. e2e = victim self-report elapsed_ms(docker stdout json). counterbalance(홀짝 순서 교대)로
# 드리프트 상쇄. overhead=(with-without)/without*100 — *절댓값 없이* 부호 그대로 기록(음수는
# "오버헤드 < 측정 노이즈"의 정직한 증거; 분석에서 부호+95% CI/등가성으로 "≈0" 입증).
# PureTime은 SIGINT 정상종료로 dropped_events 확보 + 매 run trace 즉시 삭제(solo라 작지만 안전).
#
# 사용법: sudo bash experiments/exp_overhead_e2e.sh [출력디렉토리]
set +e
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PURETIME_DIR="$(dirname "$SCRIPT_DIR")"
OUTPUT_DIR="${1:-$PURETIME_DIR/experiments/data/overhead_e2e}"
ITERATIONS="${ITERATIONS:-30}"
CPU_CORE="${CPU_CORE:-2}"           # CPU victim 핀 코어 (코어0=drain용 비움)
TESTFILE="${TESTFILE:-/data/tmp.bin}"
HDD_MOUNT="${HDD_MOUNT:-/mnt/hdd/tmp}"
VICTIMS_SEL="${VICTIMS_SEL:-float_op factors sequential aes uploader s3 compression}"   # accuracy 7 victim (부분 실행용)

mkdir -p "$OUTPUT_DIR" 2>/dev/null || { echo "출력 디렉토리 생성 실패: $OUTPUT_DIR"; exit 1; }
RESULTS="$OUTPUT_DIR/results.csv"

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

for img in float factors sequential aes network-uploader s3-download-upload compression; do
    DOCKER_BUILDKIT=0 docker build -t "$img" "$PURETIME_DIR/funcs/$img" >/dev/null 2>&1 \
        || { echo "victim 빌드 실패: $img"; exit 1; }
done

PURETIME_BIN="$PURETIME_DIR/src/puretime" ITERATIONS="$ITERATIONS" CPU_CORE="$CPU_CORE" \
TESTFILE="$TESTFILE" HDD_MOUNT="$HDD_MOUNT" VICTIMS_SEL="$VICTIMS_SEL" RESULTS="$RESULTS" python3 - <<'PY'
import os, subprocess, json, time, csv, statistics as st, sys, signal, glob, re
K=int(os.environ["ITERATIONS"]); BIN=os.environ["PURETIME_BIN"]; RESULTS=os.environ["RESULTS"]
CORE=os.environ["CPU_CORE"]; TF=os.environ["TESTFILE"]; HDD=os.environ["HDD_MOUNT"]
SEL=set(os.environ["VICTIMS_SEL"].split())
TRACEDIR="/var/log/puretime"
ALL=[
  ("float_op",    "float",              ["--cpuset-cpus=%s" % CORE], "elapsed_ms"),
  ("factors",     "factors",            ["--cpuset-cpus=%s" % CORE], "elapsed_ms"),
  ("sequential",  "sequential",         ["--cpuset-cpus=%s" % CORE], "elapsed_ms"),
  ("aes",         "aes",                ["--cpuset-cpus=%s" % CORE], "elapsed_ms"),
  ("uploader",    "network-uploader",   ["--network=host", "-v", "%s:%s:ro" % (TF, TF)], "elapsed_ms"),
  ("s3",          "s3-download-upload", ["--network=host"], "elapsed_ms"),
  ("compression", "compression",        ["-v", "%s:/tmp" % HDD], "total_elapsed_ms"),
]
VICTIMS=[v for v in ALL if v[0] in SEL]

def run_victim(opts, image, field):
    try:
        out=subprocess.check_output(["docker","run","--rm"]+opts+[image], stderr=subprocess.DEVNULL).decode()
    except subprocess.CalledProcessError:
        return None
    for line in reversed(out.splitlines()):
        line=line.strip()
        if not line.startswith("{"): continue
        try: d=json.loads(line)
        except: continue
        if field in d: return float(d[field])
    return None

def with_pt(opts, image, field):
    before=set(glob.glob(f"{TRACEDIR}/trace_*.jsonl"))
    pt=subprocess.Popen([BIN,"-t","180"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    time.sleep(2); ms=run_victim(opts, image, field); time.sleep(0.3)
    pt.send_signal(signal.SIGINT)
    try: pt.wait(timeout=60)
    except: subprocess.run(["pkill","-9","-x","puretime"]); time.sleep(1)
    dropped=None
    for tf in set(glob.glob(f"{TRACEDIR}/trace_*.jsonl"))-before:
        try:
            last=subprocess.check_output(["tail","-c","200",tf]).decode("utf-8","ignore")
            m=re.search(r'"dropped_events":(\d+)', last)
            if m: dropped=int(m.group(1))
        except: pass
        try: os.remove(tf)
        except: pass
    time.sleep(0.3); return ms, dropped

f=open(RESULTS,"w",newline=""); wr=csv.writer(f)
wr.writerow(["victim","iteration","without_ms","with_ms","overhead_pct","dropped_events"]); f.flush()
for vkey, image, opts, field in VICTIMS:
    run_victim(opts, image, field); time.sleep(0.3)   # warmup
    ovs=[]
    for i in range(K):
        # counterbalance: 홀짝 순서 교대 (드리프트 bias 상쇄)
        if i%2==0: wo=run_victim(opts,image,field); time.sleep(0.2); w,drop=with_pt(opts,image,field)
        else:      w,drop=with_pt(opts,image,field); time.sleep(0.2); wo=run_victim(opts,image,field)
        if wo and w and wo>0:
            ov=(w-wo)/wo*100; ovs.append(ov)
            wr.writerow([vkey,i+1,round(wo,2),round(w,2),round(ov,3),
                         drop if drop is not None else ""]); f.flush()
        time.sleep(0.3)
    if ovs:
        sys.stderr.write(f"  {vkey:6s} overhead mean {st.mean(ovs):+.2f}% median {st.median(ovs):+.2f}% "
                         f"(n={len(ovs)}, neg {sum(1 for x in ovs if x<0)})\n")
f.close()
PY
echo "완료: $RESULTS ($(grep -c , "$RESULTS") rows)"
