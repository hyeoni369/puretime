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
#   - net은 잘 잡힌다(실측 정정). victim이 `--network=host`면 TX가 throttle 물리 iface qdisc에
#     올라가 wait_net 포착(net-only stress: wait_net 35s, removal ~90% — 실험1 89%와 일치).
#     [이전에 "net 범위 밖"으로 오진했던 건 하니스 버그였음: (1) bridge/NAT networking →
#     net_dev↔socket cgroup 연결 깨짐, (2) victim을 CPU-stress 코어에 핀 → 업로드 CPU 굶주림.
#     둘 다 수정(start_victim: --network=host + cpu가 stress일 때만 핀).]
#   - 남은 일(진짜 과제): 자원 wait이 *겹치는* 조합·victim 설정 찾기 → merged<naive 실증.
#     CPU 경합엔 victim을 포화 코어에 핀해야 하는데 그러면 net/block이 굶으니, 멀티자원 겹침은
#     gentle CPU 경합 또는 Net+Block 조합 등으로 설계 재고 필요. 그 뒤 풀런 + plotter.
#   - set -e는 stress run의 fallible 명령(pkill 등)에서 조기종료 유발 → set +e로 변경.
# =============================================================================
set +e

FRAMES_LEVELS=(${FRAMES_LEVELS:-150 300 600 1000})
# STRESS = 동시에 켤 자원 부분집합. net도 사용 가능(--network=host 전제). interval-merge는 이 중
# 둘 이상의 wait이 시간상 겹칠 때 의미 — 겹침 나오는 조합을 실측으로 찾는 중(WIP).
STRESS="${STRESS:-cpu block}"            # 기본값(잠정); net 포함 조합도 시도 예정
GRAYSCALE_PASSES="${GRAYSCALE_PASSES:-5}"  # grayscale 반복 → CPU+Block을 makespan 지배로
ITERATIONS="${ITERATIONS:-10}"
CPU_STRESS_WORKERS="${CPU_STRESS_WORKERS:-3}"
NET_STRESS_FLOWS="${NET_STRESS_FLOWS:-4}"
BIO_STRESS_JOBS="${BIO_STRESS_JOBS:-4}"
BLOCK_QUEUE_DEPTH="${BLOCK_QUEUE_DEPTH:-2}"
CPU_PIN_CORE="${CPU_PIN_CORE:-2}"   # stress-ng + victim의 cpu_worker가 경합하는 코어(→CPU wait)
IO_CORE="${IO_CORE:-5}"             # victim의 net/block_worker 전용 빈 코어(stress 없음 → CPU 안 굶주려
                                    #   send/write를 계속 발행 → qdisc/IO-scheduler 큐잉이 net/block wait으로 포착).
                                    #   두 워커가 다른 코어 → 한 cgroup의 CPU wait ∩ IO wait이 동시 발생(겹침).
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

CID=""; CGID=""; BLOCK_DEVICE=""; ORIG_SCHED=""; ORIG_QD=""; ORIG_DIRTY=""; NET_IFACE=""
DIRTY_BYTES="${DIRTY_BYTES:-16777216}"   # 16MB — writeback을 런 중 강제 (dense block wait)

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
    # writeback을 런 중에 강제: dirty_bytes를 낮춰 버퍼드 쓰기가 캐시에 머물지 않고 즉시
    # writeback(insert→issue 큐잉, 포착됨)되게 → dense block wait. (기본 dirty_ratio는 GB라
    # 수십 MB 쓰기는 캐시에 머물러 wait_bio=0이 됨.)
    ORIG_DIRTY=$(cat /proc/sys/vm/dirty_bytes 2>/dev/null)
    echo "$DIRTY_BYTES" > /proc/sys/vm/dirty_bytes 2>/dev/null || true
}
restore_block() {
    [ -n "$BLOCK_DEVICE" ] && [ -n "$ORIG_SCHED" ] && [ "$ORIG_SCHED" != bfq ] && echo "$ORIG_SCHED" > "/sys/block/$BLOCK_DEVICE/queue/scheduler" 2>/dev/null || true
    [ -n "$BLOCK_DEVICE" ] && [ -n "$ORIG_QD" ] && echo "$ORIG_QD" > "/sys/block/$BLOCK_DEVICE/device/queue_depth" 2>/dev/null || true
    # dirty_bytes 복원 (ORIG_DIRTY=0이면 dirty_ratio 모드로 복귀)
    [ -n "$ORIG_DIRTY" ] && echo "$ORIG_DIRTY" > /proc/sys/vm/dirty_bytes 2>/dev/null || true
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
    # --network=host: TX 패킷이 throttle 걸린 물리 iface qdisc에 직접 올라가 net wait이
    #   victim cgroup에 귀속된다(bridge/NAT면 net_dev↔socket cgroup 연결이 깨져 wait_net=0).
    # CPU 핀: cpu가 stress에 있을 때만(fully-saturated 코어에 핀하면 net/block 작업이 CPU 굶주림).
    # cpu_worker는 경합 코어(CPU_PIN_CORE)에, net/block_worker는 빈 IO_CORE에 스레드 affinity로 분리
    #   (victim 내부 os.sched_setaffinity) → 한 cgroup에서 CPU wait ∩ IO wait이 동시 발생(겹침).
    #   둘 다 포착되는 자원이라 merged≈solo(valid) + naive≪solo(겹침 이중차감) — interval-merge의 핵심 실증.
    local pin="" cpuaff="" netaff="" blkaff=""
    if [[ " $STRESS " == *" cpu "* ]]; then
        pin="--cpuset-cpus=$CPU_PIN_CORE,$IO_CORE"
        cpuaff="$CPU_PIN_CORE"; netaff="$IO_CORE"; blkaff="$IO_CORE"
    fi
    CID=$(docker run -d --network=host $pin -v "$HDD_MOUNT":/tmp/video_test \
        -e VIDEO_FRAMES="$1" -e FRAME_W=$FRAME_W -e FRAME_H=$FRAME_H \
        -e UPLOAD="${UPLOAD_VICTIM:-1}" \
        -e CPU_ITERS="${N_CPU:-3000}" -e BLOCK_ITERS="${N_BLOCK:-600}" -e NET_ITERS="${N_NET:-150}" \
        -e GRAYSCALE_PASSES="${GRAYSCALE_PASSES:-5}" \
        -e CPU_AFFINITY="$cpuaff" -e NET_AFFINITY="$netaff" -e BLOCK_AFFINITY="$blkaff" \
        -e CHUNK_KB="${CHUNK_KB:-256}" "$VIDEO_IMAGE")
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
    # 실험2 overlap sweep: 루프 변수 = CPU 경합 강도(stress-ng 워커 수). 강도↑ → cpu wait↑ →
    #   net wait(고정 ~60%)과의 겹침↑ → naive 이중차감 발산(merged는 solo 유지). CSV "frames" 열 = 강도.
    #   (SWEEP_CPU_STRESS=0으로 끄면 루프 변수는 단순 라벨, CPU_STRESS_WORKERS는 env 고정값 사용.)
    # BALANCE: 강도↑면 cpu_worker가 느려져 long pole이 되고 net wait이 critical-path 밖→과다제거.
    #   N_CPU ∝ 3/(강도+1)로 줄여 cpu_worker를 net_worker(~9s)와 항상 동시 종료시킨다(merged≈solo 유지).
    local BASE_NCPU="${N_CPU:-4500}"
    for frames in "${FRAMES_LEVELS[@]}"; do
        if [ "${SWEEP_CPU_STRESS:-1}" = 1 ]; then
            CPU_STRESS_WORKERS="$frames"
            N_CPU=$(( BASE_NCPU * 3 / (frames + 1) ))
        fi
        log_info "=== cpu_stress=$CPU_STRESS_WORKERS N_CPU=$N_CPU (sweep=$frames, stress=$STRESS) ==="
        for iter in $(seq 1 $ITERATIONS); do
            run_one "$frames" solo "$iter";   sleep 3
            run_one "$frames" stress "$iter"; sleep 5
        done
    done
    log_info "실험2 완료: $RESULTS_FILE"
}
main "$@"
