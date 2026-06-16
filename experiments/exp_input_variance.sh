#!/bin/bash
# =============================================================================
# 실험 3: Input-variance — 입력에 따라 연산량이 변하는 함수에서 PureTime 정확도 (C5)
# =============================================================================
# victim:
#   - float        : sqrt/sin/cos 루프, 입력 = iters (CMD 인자)
#   - face-detect  : opencv Haar 검출 + 건당 sentiment, 입력 = 얼굴 수 (NUM_FACES env)
# 고정 register/L1 CPU stress(별도 cgroup, victim과 같은 코어 핀) 하에서, 입력별로
#   solo(무경합) / e2e(경합) / noise-free(PureTime) 를 측정. solo와 stress를 iteration마다
#   interleave (block 실험에서 배운 drift-robust 측정).
# =============================================================================
set -e

# ===== Config =====
FLOAT_ITERS=(${FLOAT_ITERS:-2000000 5000000 10000000 20000000 35000000 50000000})
FACE_LEVELS=(${FACE_LEVELS:-0 1 5 10 15 30})
CPU_STRESS_WORKERS="${CPU_STRESS_WORKERS:-3}"   # 고정 stress 강도 (register/L1 별도 cgroup)
ITERATIONS="${ITERATIONS:-20}"
VICTIMS="${VICTIMS:-float face}"                 # 둘 다 / 하나만 (float|face)
CPU_PIN_CORE=2
TRACE_DURATION=180

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PURETIME_DIR="$(dirname "$SCRIPT_DIR")"
PURETIME_BIN="$PURETIME_DIR/src/puretime"
MAKESPAN="$SCRIPT_DIR/noise_free_makespan.py"
OUTPUT_DIR="${1:-/tmp/puretime_exp3_$(date +%Y%m%d_%H%M%S)}"
RESULTS_FILE="$OUTPUT_DIR/results.csv"

FLOAT_IMAGE="float"
FACE_IMAGE="face-detect"

RED='\033[0;31m'; GREEN='\033[0;32m'; CYAN='\033[0;36m'; NC='\033[0m'
log_info() { echo -e "${CYAN}[INFO]${NC} $1" >&2; }
log_fail() { echo -e "${RED}[FAIL]${NC} $1" >&2; }

CID=""; CGID=""

check_prereq() {
    [ "$EUID" -ne 0 ] && { log_fail "root 필요"; exit 1; }
    [ -x "$PURETIME_BIN" ] || { log_fail "puretime 바이너리 없음: $PURETIME_BIN"; exit 1; }
    [ -f "$MAKESPAN" ] || { log_fail "analyzer 없음: $MAKESPAN"; exit 1; }
    log_info "Docker 이미지 빌드..."
    docker build -t "$FLOAT_IMAGE" "$PURETIME_DIR/funcs/float" >/dev/null 2>&1
    docker build -t "$FACE_IMAGE" "$PURETIME_DIR/funcs/face-detect" >/dev/null 2>&1
    log_info "prereq OK"
}

setup_output() {
    mkdir -p "$OUTPUT_DIR"
    if [ ! -f "$RESULTS_FILE" ]; then
        echo "victim,input_level,condition,iteration,t_e2e_ms,t_puretime_ms,t_noise_cpu" > "$RESULTS_FILE"
    else
        log_info "기존 결과에 append: $RESULTS_FILE"
    fi
    log_info "Output: $OUTPUT_DIR"
}

get_latest_trace() { ls -t /var/log/puretime/trace_*.jsonl 2>/dev/null | head -1; }

# victim 컨테이너 실행(입력 주입) + cgroup id (전역 CID, CGID)
start_victim() {
    local victim="$1" input="$2"
    local opt="--cpuset-cpus=$CPU_PIN_CORE"
    if [ "$victim" = "float" ]; then
        CID=$(docker run -d $opt "$FLOAT_IMAGE" python function.py "$input" 1)
    else
        CID=$(docker run -d $opt -e NUM_FACES="$input" "$FACE_IMAGE")
    fi
    local pid=$(docker inspect --format '{{.State.Pid}}' "$CID")
    local cgpath=$(cat /proc/$pid/cgroup | grep -oP '0::/\K.*')
    CGID=$(stat -c %i "/sys/fs/cgroup/${cgpath}")
}

# 한 측정: cond=solo(무경합) 또는 stress(CPU 경합)
run_one() {
    local victim="$1" input="$2" cond="$3" iter="$4"
    local cgfile="$OUTPUT_DIR/cgroups_${victim}_${input}_${cond}_${iter}.txt"
    local stress_cg="/sys/fs/cgroup/pt_e3stress"

    $PURETIME_BIN -v -t $TRACE_DURATION &
    local pt_pid=$!
    sleep 2
    local trace=$(get_latest_trace)

    if [ "$cond" = "stress" ]; then
        for w in $(seq 1 "$CPU_STRESS_WORKERS"); do
            mkdir -p "${stress_cg}_$w"
            bash -c "echo \$\$ > ${stress_cg}_$w/cgroup.procs; exec stress-ng --cpu 1 --cpu-method float --taskset $CPU_PIN_CORE --cpu-load 100 -t $TRACE_DURATION" >/dev/null 2>&1 &
        done
        sleep 1
    fi

    start_victim "$victim" "$input"
    echo "$CGID" > "$cgfile"
    docker wait "$CID" >/dev/null 2>&1 || true

    [ "$cond" = "stress" ] && { pkill -9 -f "stress-ng" 2>/dev/null || true; }
    kill $pt_pid 2>/dev/null || true; wait $pt_pid 2>/dev/null || true

    local res
    res=$(python3 "$MAKESPAN" "$trace" -c "$cgfile" 2>/dev/null || echo "[]")
    echo "$res" | jq -r --arg v "$victim" --arg in "$input" --arg c "$cond" --arg it "$iter" '
        .[] | [$v,($in|tonumber),$c,($it|tonumber),
               (.original_makespan/1000000),(.noise_free_makespan/1000000),(.wait_cpu/1000000)] | @csv' >> "$RESULTS_FILE"

    docker rm -f "$CID" >/dev/null 2>&1 || true
    if [ "$cond" = "stress" ]; then
        for w in $(seq 1 "$CPU_STRESS_WORKERS"); do rmdir "${stress_cg}_$w" 2>/dev/null || true; done
    fi
}

sweep_victim() {
    local victim="$1"; shift
    local levels=("$@")
    log_info "=== $victim input sweep (${levels[*]}) ==="
    for input in "${levels[@]}"; do
        for iter in $(seq 1 $ITERATIONS); do
            run_one "$victim" "$input" solo "$iter";   sleep 3
            run_one "$victim" "$input" stress "$iter"; sleep 5
        done
    done
}

main() {
    check_prereq
    setup_output
    if [[ " $VICTIMS " == *" float "* ]]; then sweep_victim float "${FLOAT_ITERS[@]}"; fi
    if [[ " $VICTIMS " == *" face "* ]];  then sweep_victim face  "${FACE_LEVELS[@]}"; fi
    log_info "실험3 완료: $RESULTS_FILE"
}
main "$@"
