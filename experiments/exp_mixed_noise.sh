#!/bin/bash
# =============================================================================
# 실험 2: Mixed-noise + interval-merge (C3)
# =============================================================================
# victim = video-processing (generate → OpenCV grayscale → MinIO upload): CPU+Block+Net-TX.
# 여러 자원 stressor를 동시에 켜고(STRESS 부분집합), 자원 wait이 겹칠 때 interval-merge가
# 이중차감을 막는지 검증. 분석기는 noise_free(merged union)와 noise_free_naive(sum, 겹침
# 이중차감→over-subtract)를 둘 다 출력. 영상 크기(FRAMES)로 겹침 비율 조절.
#
# ⚠ WIP (2026-06-16): 실험 2 미완성. 알게 된 것:
#   - net-TX 경합은 throttle 포화 시 TCP 혼잡 백오프(소켓버퍼, qdisc 이전 = PureTime 범위 밖)라
#     wait_net≈0 → interval-merge에 기여 못 함 → STRESS 기본을 cpu+block으로 피벗.
#   - 남은 일: (a) CPU+Block 파일럿에서 merged<naive(겹침 이중차감)가 유의하게 나오는지 실증,
#     (b) 안 나오면 GRAYSCALE_PASSES/FRAMES로 CPU·Block 겹침 튜닝, (c) plotter.
#   - set -e는 stress run의 fallible 명령(pkill 등)에서 조기종료 유발 → set +e로 변경.
# =============================================================================
set +e

FRAMES_LEVELS=(${FRAMES_LEVELS:-150 300 600 1000})
# interval-merge는 견고하게 포착되는 자원의 겹침으로 실증한다. net-TX 경합은 throttle 포화 시
# TCP 혼잡 백오프(소켓버퍼, qdisc 이전 = 범위 밖)라 wait_net≈0 → merge에 기여 못 함(실측 확인).
# 따라서 STRESS 기본 = cpu+block (grayscale 단계에서 CPU-wait↔Block-wait이 async writeback으로 겹침).
STRESS="${STRESS:-cpu block}"            # 동시에 켤 자원 부분집합
GRAYSCALE_PASSES="${GRAYSCALE_PASSES:-5}"  # grayscale 반복 → CPU+Block을 makespan 지배로
ITERATIONS="${ITERATIONS:-10}"
CPU_STRESS_WORKERS="${CPU_STRESS_WORKERS:-3}"
NET_STRESS_FLOWS="${NET_STRESS_FLOWS:-4}"
BIO_STRESS_JOBS="${BIO_STRESS_JOBS:-4}"
BLOCK_QUEUE_DEPTH="${BLOCK_QUEUE_DEPTH:-2}"
CPU_PIN_CORE=2
FRAME_W=640
FRAME_H=480
TRACE_DURATION=180

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PURETIME_DIR="$(dirname "$SCRIPT_DIR")"
PURETIME_BIN="$PURETIME_DIR/src/puretime"
MAKESPAN="$SCRIPT_DIR/noise_free_makespan.py"
OUTPUT_DIR="${1:-/tmp/puretime_exp2_$(date +%Y%m%d_%H%M%S)}"
RESULTS_FILE="$OUTPUT_DIR/results.csv"
VIDEO_IMAGE="video-processing"
MINIO_IP="165.194.27.225"
HDD_MOUNT="/mnt/hdd/tmp"

RED='\033[0;31m'; GREEN='\033[0;32m'; CYAN='\033[0;36m'; NC='\033[0m'
log_info() { echo -e "${CYAN}[INFO]${NC} $1" >&2; }
log_fail() { echo -e "${RED}[FAIL]${NC} $1" >&2; }

CID=""; CGID=""; BLOCK_DEVICE=""; ORIG_SCHED=""; ORIG_QD=""; NET_IFACE=""

check_prereq() {
    [ "$EUID" -ne 0 ] && { log_fail "root 필요"; exit 1; }
    [ -x "$PURETIME_BIN" ] || { log_fail "puretime 없음"; exit 1; }
    log_info "video 이미지 빌드..."
    docker build -t "$VIDEO_IMAGE" "$PURETIME_DIR/funcs/video-processing" >/dev/null 2>&1
    log_info "prereq OK (STRESS=$STRESS)"
}

setup_output() {
    mkdir -p "$OUTPUT_DIR"
    [ -f "$RESULTS_FILE" ] || echo "frames,stress,condition,iteration,original_ms,noise_free_ms,noise_free_naive_ms,wait_cpu,wait_net,wait_bio" > "$RESULTS_FILE"
    log_info "Output: $OUTPUT_DIR"
}
get_latest_trace() { ls -t /var/log/puretime/trace_*.jsonl 2>/dev/null | head -1; }

# ---- block scheduler/queue_depth (실험1과 동일 전제) ----
setup_block() {
    BLOCK_DEVICE=$(df "$HDD_MOUNT" 2>/dev/null | tail -1 | awk '{print $1}' | sed 's|/dev/||; s/[0-9]*$//')
    local sp="/sys/block/$BLOCK_DEVICE/queue/scheduler"
    [ -f "$sp" ] && { ORIG_SCHED=$(grep -oP '\[\K[^\]]+' "$sp"); [ "$ORIG_SCHED" != bfq ] && echo bfq > "$sp" 2>/dev/null || true; }
    local qp="/sys/block/$BLOCK_DEVICE/device/queue_depth"
    [ -f "$qp" ] && { ORIG_QD=$(cat "$qp"); echo "$BLOCK_QUEUE_DEPTH" > "$qp" 2>/dev/null || true; }
}
restore_block() {
    [ -n "$BLOCK_DEVICE" ] && [ -n "$ORIG_SCHED" ] && [ "$ORIG_SCHED" != bfq ] && echo "$ORIG_SCHED" > "/sys/block/$BLOCK_DEVICE/queue/scheduler" 2>/dev/null || true
    [ -n "$BLOCK_DEVICE" ] && [ -n "$ORIG_QD" ] && echo "$ORIG_QD" > "/sys/block/$BLOCK_DEVICE/device/queue_depth" 2>/dev/null || true
}
setup_net_throttle() {
    NET_IFACE=$(ip route get $MINIO_IP 2>/dev/null | awk '{print $5; exit}')
    [ -z "$NET_IFACE" ] && NET_IFACE=$(ip route get 8.8.8.8 2>/dev/null | awk '{print $5; exit}')
    ethtool -K "$NET_IFACE" tso off gso off gro off 2>/dev/null || true
    tc qdisc del dev "$NET_IFACE" root 2>/dev/null || true
    tc qdisc add dev "$NET_IFACE" root handle 1: htb default 10
    tc class add dev "$NET_IFACE" parent 1: classid 1:10 htb rate 10mbit burst 15k
    tc qdisc add dev "$NET_IFACE" parent 1:10 handle 10: fq_codel
}
restore_net_throttle() {
    [ -n "$NET_IFACE" ] && { tc qdisc del dev "$NET_IFACE" root 2>/dev/null || true; ethtool -K "$NET_IFACE" tso on gso on gro on 2>/dev/null || true; }
}

start_stressors() {  # $1=stress set
    local s="$1"
    if [[ " $s " == *" cpu "* ]]; then
        for w in $(seq 1 "$CPU_STRESS_WORKERS"); do
            mkdir -p "/sys/fs/cgroup/pt_m_cpu_$w"
            bash -c "echo \$\$ > /sys/fs/cgroup/pt_m_cpu_$w/cgroup.procs; exec stress-ng --cpu 1 --cpu-method float --taskset $CPU_PIN_CORE --cpu-load 100 -t $TRACE_DURATION" >/dev/null 2>&1 &
        done
    fi
    if [[ " $s " == *" net "* ]]; then
        setup_net_throttle
        mkdir -p /sys/fs/cgroup/pt_m_net
        bash -c "echo \$\$ > /sys/fs/cgroup/pt_m_net/cgroup.procs; exec iperf3 -c $MINIO_IP -t $TRACE_DURATION -P $NET_STRESS_FLOWS" >/dev/null 2>&1 &
    fi
    if [[ " $s " == *" block "* ]]; then
        mkdir -p /sys/fs/cgroup/pt_m_blk
        bash -c "echo \$\$ > /sys/fs/cgroup/pt_m_blk/cgroup.procs; exec fio --name=mblkstress --directory=$HDD_MOUNT --rw=write --bs=1M --size=256M --numjobs=$BIO_STRESS_JOBS --time_based --runtime=$TRACE_DURATION --fsync=8 --direct=0 --group_reporting" >/dev/null 2>&1 &
    fi
    sleep 1
}
stop_stressors() {
    pkill -9 -f "stress-ng" 2>/dev/null || true
    pkill -9 -f "iperf3 -c" 2>/dev/null || true
    pkill -9 -f "fio --name=mblkstress" 2>/dev/null || true
    for d in /sys/fs/cgroup/pt_m_cpu_* /sys/fs/cgroup/pt_m_net /sys/fs/cgroup/pt_m_blk; do [ -d "$d" ] && rmdir "$d" 2>/dev/null || true; done
    rm -f "$HDD_MOUNT"/mblkstress* 2>/dev/null || true
    restore_net_throttle
}

start_victim() {  # $1=frames
    CID=$(docker run -d --cpuset-cpus=$CPU_PIN_CORE -v "$HDD_MOUNT":/tmp/video_test \
        -e VIDEO_FRAMES="$1" -e FRAME_W=$FRAME_W -e FRAME_H=$FRAME_H \
        -e UPLOAD=0 -e GRAYSCALE_PASSES="$GRAYSCALE_PASSES" "$VIDEO_IMAGE")
    local pid=$(docker inspect --format '{{.State.Pid}}' "$CID")
    local cg=$(cat /proc/$pid/cgroup | grep -oP '0::/\K.*')
    CGID=$(stat -c %i "/sys/fs/cgroup/${cg}")
}

run_one() {  # $1=frames $2=cond(solo|stress) $3=iter
    local frames="$1" cond="$2" iter="$3"
    local cgfile="$OUTPUT_DIR/cgroups_${frames}_${cond}_${iter}.txt"
    setup_block
    $PURETIME_BIN -v -t $TRACE_DURATION & local pt=$!; sleep 2
    local trace=$(get_latest_trace)
    [ "$cond" = stress ] && start_stressors "$STRESS"
    start_victim "$frames"
    echo "$CGID" > "$cgfile"
    docker wait "$CID" >/dev/null 2>&1 || true
    [ "$cond" = stress ] && stop_stressors
    kill $pt 2>/dev/null || true; wait $pt 2>/dev/null || true
    local res; res=$(python3 "$MAKESPAN" "$trace" -c "$cgfile" 2>/dev/null || echo "[]")
    echo "$res" | jq -r --arg f "$frames" --arg s "$STRESS" --arg c "$cond" --arg it "$iter" '
        .[] | [($f|tonumber),$s,$c,($it|tonumber),
               (.original_makespan/1000000),(.noise_free_makespan/1000000),(.noise_free_naive/1000000),
               (.wait_cpu/1000000),(.wait_net/1000000),(.wait_bio/1000000)] | @csv' >> "$RESULTS_FILE"
    docker rm -f "$CID" >/dev/null 2>&1 || true
    restore_block
}

main() {
    check_prereq; setup_output
    for frames in "${FRAMES_LEVELS[@]}"; do
        log_info "=== frames=$frames (stress=$STRESS) ==="
        for iter in $(seq 1 $ITERATIONS); do
            run_one "$frames" solo "$iter";   sleep 3
            run_one "$frames" stress "$iter"; sleep 5
        done
    done
    log_info "실험2 완료: $RESULTS_FILE"
}
main "$@"
