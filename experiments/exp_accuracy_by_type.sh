#!/bin/bash
# =============================================================================
# PureTime Experiment: Noise Removal Accuracy by Contention Type
# =============================================================================
# 
# 목적: CPU, Network, Block I/O 각 노이즈 유형별로 PureTime의 노이즈 제거 정확도 측정
#       (노이즈 강도는 고정, 유형별 차이만 비교)
#
# 정확도 계산 방식:
#   Ground Truth Noise = T_contention - T_isolated
#   Removed Noise      = T_contention - T_puretime
#   Efficiency         = (Removed Noise / Ground Truth Noise) × 100%
#
# Usage: sudo ./exp_accuracy_by_type.sh [output_dir]
# =============================================================================

set -e

# =============================================================================
# Configuration Variables (수정 가능)
# =============================================================================

# CPU noise = stress-ng CPU worker 수(register/L1 --cpu-method float, victim과 같은 코어). 0=solo(GT 기준).
# (이전엔 graph-bfs 컨테이너 N개 상호경합 = 약함+메모리 dilation. victim은 항상 float 1개; stressor만 stress-ng.)
# 강도 배열은 env로 override 가능(fig 1b 강도 sweep용). 예: NET_FLOWS_SWEEP="0 2 4 8"
CPU_STRESS_WORKERS=(${CPU_WORKERS_SWEEP:-0 1 3 7})
# Block noise = fio 동시 job 수 (같은 디바이스 $HDD_MOUNT에 연속 버퍼드+fsync 쓰기 stressor). 0=solo(GT 기준).
# (이전엔 compression 컨테이너 N개 상호경합=약함. victim은 항상 compression 1개; stressor만 fio.)
BIO_STRESS_JOBS=(${BIO_JOBS_SWEEP:-0 4})

# Network noise = iperf3 stressor 강도(병렬 TCP flow 수, -P). 0=solo(stressor 없음, GT 기준).
# (이전엔 업로더 컨테이너 수였음. victim은 항상 uploader 1개; 노이즈만 iperf3로 교체.)
# 강도 sweep상 -P 4(≈5 flow)가 sweet spot(removal ~88%). iperf3 서버가 $MINIO_IP:5201에 떠 있어야 함.
NET_STRESS_FLOWS=(${NET_FLOWS_SWEEP:-0 4})

# 반복 실험 횟수 (설계 K=50; 파일럿은 ITERATIONS=2 등 env로 오버라이드)
ITERATIONS="${ITERATIONS:-50}"

# PureTime 트레이싱 시간 (컨테이너 실행 완료까지 충분한 시간)
TRACE_DURATION=180

# =============================================================================
# Path Configuration
# =============================================================================

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PURETIME_DIR="$(dirname "$SCRIPT_DIR")"
PURETIME_BIN="$PURETIME_DIR/src/puretime"
MAKESPAN="$SCRIPT_DIR/noise_free_makespan.py"

OUTPUT_DIR="${1:-/tmp/puretime_exp_type_$(date +%Y%m%d_%H%M%S)}"
RESULTS_FILE="$OUTPUT_DIR/results.csv"

# Docker image names
FLOAT_IMAGE="float"                 # CPU victim/stressor = register/L1-bound (설계 요구; graph-bfs 대체)
GRAPH_BFS_IMAGE="graph-bfs"         # (오버헤드 실험용으로만 유지; 정확도 CPU 실험엔 미사용)
NETWORK_UPLOADER_IMAGE="network-uploader"
COMPRESSION_IMAGE="compression"

# CPU 실험 핀 코어 (설계: core 0 제외 → 비-0 단일 코어에 victim+stressor 핀)
CPU_PIN_CORE=2

# Network/Block I/O 설정
TESTFILE_PATH="/data/tmp.bin"
MINIO_IP="165.194.27.225"
MINIO_ENDPOINT="http://$MINIO_IP:9000"
HDD_MOUNT="/mnt/hdd/tmp"

# =============================================================================
# Colors for output
# =============================================================================
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
CYAN='\033[0;36m'
NC='\033[0m'

# 로그는 stderr로 — $(setup_network_throttle) 같은 함수 출력 캡처에 로그가 섞이지 않도록.
log_info() { echo -e "${CYAN}[INFO]${NC} $1" >&2; }
log_pass() { echo -e "${GREEN}[PASS]${NC} $1" >&2; }
log_fail() { echo -e "${RED}[FAIL]${NC} $1" >&2; }
log_warn() { echo -e "${YELLOW}[WARN]${NC} $1" >&2; }

# =============================================================================
# Helper Functions
# =============================================================================

check_prerequisites() {
    log_info "Checking prerequisites..."
    
    if [ "$EUID" -ne 0 ]; then
        log_fail "Must run as root"
        exit 1
    fi
    
    if [ ! -x "$PURETIME_BIN" ]; then
        log_fail "PureTime binary not found at $PURETIME_BIN"
        exit 1
    fi
    
    if [ ! -f "$MAKESPAN" ]; then
        log_fail "Makespan analyzer not found at $MAKESPAN"
        exit 1
    fi
    
    # Build Docker images if needed
    log_info "Building Docker images..."
    docker build -t "$FLOAT_IMAGE" "$PURETIME_DIR/funcs/float" > /dev/null 2>&1
    docker build -t "$GRAPH_BFS_IMAGE" "$PURETIME_DIR/funcs/graph-bfs" > /dev/null 2>&1
    docker build -t "$NETWORK_UPLOADER_IMAGE" "$PURETIME_DIR/funcs/network-uploader" > /dev/null 2>&1
    docker build -t "$COMPRESSION_IMAGE" "$PURETIME_DIR/funcs/compression" > /dev/null 2>&1
    
    log_pass "Prerequisites OK"
}

setup_output() {
    mkdir -p "$OUTPUT_DIR"
    # 기존 CSV가 있으면 헤더를 덮어쓰지 않고 append (자원별 부분 재실행 지원)
    if [ ! -f "$RESULTS_FILE" ]; then
        echo "cgroup_id,resource_type,container_count,iteration,t_e2e_ms,t_puretime_ms,t_noise_cpu,t_noise_net,t_noise_bio" > "$RESULTS_FILE"
    else
        log_info "기존 결과에 append: $RESULTS_FILE ($(($(wc -l < "$RESULTS_FILE") - 1)) rows)"
    fi
    log_info "Output directory: $OUTPUT_DIR"
}

# JSON 결과를 CSV로 변환하여 저장
save_puretime_results() {
    local json_result="$1"
    local resource_type="$2"
    local count="$3"
    local iteration="$4"

    echo "$json_result" | jq -r --arg type "$resource_type" --arg cnt "$count" --arg iter "$iteration" '
        .[] | [
            .cgroup_id,
            $type,
            ($cnt | tonumber),
            ($iter | tonumber),
            (.original_makespan / 1000000),
            (.noise_free_makespan / 1000000),
            (.wait_cpu / 1000000),
            (.wait_net / 1000000),
            (.wait_bio / 1000000)
        ] | @csv
    ' >> "$RESULTS_FILE"
}

get_latest_trace() {
    ls -t /var/log/puretime/trace_*.jsonl 2>/dev/null | head -1
}

# =============================================================================
# Container Management Functions
# =============================================================================

# 컨테이너 실행 및 cgroup ID 수집 (run_with_function.sh 패턴)
declare -a CONTAINER_IDS
declare -a CONTAINER_CGROUP_IDS

start_containers() {
    local image="$1"
    local count="$2"
    local extra_opts="$3"
    
    CONTAINER_IDS=()
    CONTAINER_CGROUP_IDS=()
    
    for i in $(seq 1 $count); do
        local cid=$(docker run -d $extra_opts "$image")
        CONTAINER_IDS+=("$cid")
        
        # cgroup ID 추출 (run_with_function.sh 방식)
        local pid=$(docker inspect --format '{{.State.Pid}}' "$cid")
        local cgroup_path=$(cat /proc/$pid/cgroup | grep -oP '0::/\K.*')
        local cgroup_id=$(stat -c %i "/sys/fs/cgroup/${cgroup_path}")
        CONTAINER_CGROUP_IDS+=("$cgroup_id")
    done
}

wait_containers() {
    for cid in "${CONTAINER_IDS[@]}"; do
        docker wait "$cid" > /dev/null 2>&1 || true
    done
}

stop_containers() {
    for cid in "${CONTAINER_IDS[@]}"; do
        docker rm -f "$cid" > /dev/null 2>&1 || true
    done
    CONTAINER_IDS=()
    CONTAINER_CGROUP_IDS=()
}

save_cgroup_ids() {
    local filepath="$1"
    > "$filepath"
    for cgroup_id in "${CONTAINER_CGROUP_IDS[@]}"; do
        echo "$cgroup_id" >> "$filepath"
    done
}

# =============================================================================
# Network Configuration (run_with_function.sh 참조)
# =============================================================================

setup_network_throttle() {
    local iface=$(ip route get $MINIO_IP 2>/dev/null | awk '{print $5; exit}')
    if [ -z "$iface" ]; then
        iface=$(ip route get 8.8.8.8 2>/dev/null | awk '{print $5; exit}')
    fi
    
    log_info "Setting up network throttle on $iface..."
    
    # Disable offloads
    ethtool -K "$iface" tso off gso off gro off 2>/dev/null || true
    
    # Add bandwidth limit
    tc qdisc del dev "$iface" root 2>/dev/null || true  # 기존 qdisc 제거
    tc qdisc add dev "$iface" root handle 1: htb default 10  # htb를 root qdisc로 설정 (대역폭 제한용)
    tc class add dev "$iface" parent 1: classid 1:10 htb rate 10mbit burst 15k  # 10Mbps 클래스 생성
    tc qdisc add dev "$iface" parent 1:10 handle 10: fq_codel  # fq_codel을 leaf qdisc로 설정 (fair queueing용)
    
    echo "$iface"
}

teardown_network_throttle() {
    local iface="$1"
    log_info "Removing network throttle..."
    tc qdisc del dev "$iface" root 2>/dev/null || true
    ethtool -K "$iface" tso on gso on gro on 2>/dev/null || true
}

# =============================================================================
# Block I/O Configuration
# =============================================================================

BLOCK_DEVICE=""
ORIGINAL_SCHEDULER=""
ORIGINAL_QUEUE_DEPTH=""
# block 측정 전제조건: NCQ depth를 낮춰 경합을 OS 큐(insert→issue)로 노출.
# depth=2 → noise_free가 solo를 복원(K=30 store-victim removal~92%, nf/solo 1.17); depth=1은 완전직렬화로 과다제거(nf<solo);
# depth=32(기본)은 경합이 디바이스 내부(issue→complete)에 숨어 과소포착(removal~39%).
BLOCK_QUEUE_DEPTH="${BLOCK_QUEUE_DEPTH:-2}"

setup_io_scheduler() {
    local docker_root=$(docker info --format '{{.DockerRootDir}}' 2>/dev/null || echo "/var/lib/docker")
    local mount_point=$(df "$docker_root" 2>/dev/null | tail -1 | awk '{print $1}')
    BLOCK_DEVICE=$(basename "$mount_point" | sed 's/[0-9]*$//' | sed 's/p[0-9]*$//')
    
    if [ -z "$BLOCK_DEVICE" ]; then
        BLOCK_DEVICE=$(lsblk -d -n -o NAME,TYPE | grep disk | head -1 | awk '{print $1}')
    fi
    
    local sched_path="/sys/block/$BLOCK_DEVICE/queue/scheduler"
    if [ -f "$sched_path" ]; then
        ORIGINAL_SCHEDULER=$(cat "$sched_path" | grep -oP '\[\K[^\]]+')
        if [ "$ORIGINAL_SCHEDULER" != "bfq" ]; then
            log_info "Setting I/O scheduler to BFQ on $BLOCK_DEVICE..."
            echo bfq > "$sched_path" 2>/dev/null || true
        fi
    fi

    # NCQ queue_depth 제한 (block 경합을 큐잉 층으로 노출; 위 BLOCK_QUEUE_DEPTH 주석 참조)
    local qd_path="/sys/block/$BLOCK_DEVICE/device/queue_depth"
    if [ -f "$qd_path" ]; then
        ORIGINAL_QUEUE_DEPTH=$(cat "$qd_path" 2>/dev/null)
        if [ -n "$ORIGINAL_QUEUE_DEPTH" ] && [ "$ORIGINAL_QUEUE_DEPTH" != "$BLOCK_QUEUE_DEPTH" ]; then
            log_info "Limiting NCQ queue_depth $ORIGINAL_QUEUE_DEPTH->$BLOCK_QUEUE_DEPTH on $BLOCK_DEVICE..."
            echo "$BLOCK_QUEUE_DEPTH" > "$qd_path" 2>/dev/null || true
        fi
    fi
}

restore_io_scheduler() {
    if [ -n "$BLOCK_DEVICE" ] && [ -n "$ORIGINAL_SCHEDULER" ] && [ "$ORIGINAL_SCHEDULER" != "bfq" ]; then
        local sched_path="/sys/block/$BLOCK_DEVICE/queue/scheduler"
        echo "$ORIGINAL_SCHEDULER" > "$sched_path" 2>/dev/null || true
    fi
    # queue_depth 복원
    if [ -n "$BLOCK_DEVICE" ] && [ -n "$ORIGINAL_QUEUE_DEPTH" ]; then
        local qd_path="/sys/block/$BLOCK_DEVICE/device/queue_depth"
        echo "$ORIGINAL_QUEUE_DEPTH" > "$qd_path" 2>/dev/null || true
    fi
}

# =============================================================================
# Test file for network upload
# =============================================================================

# Test file for network upload
TESTFILE_PATH="/data/tmp.bin"
SMALL_FILE_URL="https://github.com/STEllAR-GROUP/hpx/archive/refs/tags/1.4.0.zip"
# LARGE_FILE_URL="https://download.pytorch.org/models/resnet50-19c8e357.pth"

# Create test file for network upload
create_testfile_by_downloading() {
    log_info "Downloading test file..."
    curl -L -o "$TESTFILE_PATH" "$SMALL_FILE_URL"
    log_pass "Test file created: $TESTFILE_PATH"
}

ensure_testfile() {
    if [ ! -f "$TESTFILE_PATH" ]; then
        mkdir -p "$(dirname $TESTFILE_PATH)"
        create_testfile_by_downloading
    fi
}

# =============================================================================
# Experiment Functions
# =============================================================================

run_cpu_experiment() {
    # $1 = stress-ng CPU worker 수(stressor 강도). 0이면 solo(노이즈 없음, GT 기준).
    # victim은 항상 float 컨테이너 1개(실제 함수); 노이즈는 별도 cgroup의 호스트 stress-ng
    # (register/L1-bound --cpu-method float → IPC dilation 누수 차단), victim과 같은 코어에 연속 핀.
    local workers="$1"
    local iteration="$2"

    log_info "CPU experiment: stress-ng --cpu $workers (float method), iteration $iteration"

    local cgroup_file="$OUTPUT_DIR/cgroups_cpu_${workers}_${iteration}.txt"
    local stress_cg="/sys/fs/cgroup/pt_cpustress"

    # Start PureTime
    $PURETIME_BIN -v -t $TRACE_DURATION &
    local puretime_pid=$!
    sleep 2

    local trace_file=$(get_latest_trace)

    # CPU stressor: 호스트 stress-ng, register/L1-bound, victim과 같은 코어($CPU_PIN_CORE)에 핀, 연속.
    # 강도 = N개의 *별도 cgroup*(각 1 worker). per-cgroup 공정성이라 victim+N = (N+1)-way → 1/(N+1)
    # → 2×/4×/8× scale (한 cgroup에 N worker면 cgroup 공정성으로 ~2×에 고정되므로 분리 필수).
    if [ "$workers" -gt 0 ]; then
        for w in $(seq 1 "$workers"); do
            mkdir -p "${stress_cg}_$w"
            bash -c "echo \$\$ > ${stress_cg}_$w/cgroup.procs; exec stress-ng --cpu 1 --cpu-method float --taskset $CPU_PIN_CORE --cpu-load 100 -t $TRACE_DURATION" > /dev/null 2>&1 &
        done
        sleep 1   # stressor 램프업 후 victim 시작
    fi

    # victim: 실제 float 함수 컨테이너 1개, 같은 코어에 핀
    start_containers "${CPU_VICTIM_IMAGE:-$FLOAT_IMAGE}" 1 "--cpuset-cpus=$CPU_PIN_CORE"
    save_cgroup_ids "$cgroup_file"
    wait_containers

    # stressor + PureTime 종료
    pkill -9 -f "stress-ng" 2>/dev/null || true
    kill $puretime_pid 2>/dev/null || true
    wait $puretime_pid 2>/dev/null || true

    local puretime_result=$(python3 "$MAKESPAN" "$trace_file" -c "$cgroup_file")
    save_puretime_results "$puretime_result" "cpu" "$workers" "$iteration"

    stop_containers
    for w in $(seq 1 "$workers"); do rmdir "${stress_cg}_$w" 2>/dev/null || true; done
}

run_network_experiment() {
    # $1 = iperf3 stressor 강도(-P, 병렬 TCP flow 수). 0이면 solo(노이즈 없음, GT 기준).
    # victim은 항상 uploader 컨테이너 1개; 노이즈는 별도 cgroup의 호스트 iperf3(분석 대상 아님).
    local flows="$1"
    local iteration="$2"

    log_info "Network experiment: iperf3 -P $flows stressor, iteration $iteration"

    ensure_testfile
    local cgroup_file="$OUTPUT_DIR/cgroups_net_${flows}_${iteration}.txt"
    # stressor cgroup은 반드시 level>=2여야 tracer의 tcp_sendmsg 등록(is_container_cgroup)이 잡는다.
    local stress_cg="/sys/fs/cgroup/pt_netstress/s"

    # Setup network throttle
    local iface=$(setup_network_throttle)

    # Start PureTime
    $PURETIME_BIN -v -t $TRACE_DURATION &
    local puretime_pid=$!
    sleep 2

    local trace_file=$(get_latest_trace)

    # Start the network stressor: 호스트 iperf3 -P $flows (별도 level-2 cgroup), 원격 서버로 TCP 송신.
    # iperf3 서버가 $MINIO_IP:5201에 떠 있어야 함. UDP(-u) 금지(PureTime은 TCP-TX만 귀속).
    local stress_pid=""
    if [ "$flows" -gt 0 ]; then
        mkdir -p "$stress_cg"
        bash -c "echo \$\$ > $stress_cg/cgroup.procs; exec iperf3 -c $MINIO_IP -P $flows -t $TRACE_DURATION" > /dev/null 2>&1 &
        stress_pid=$!
        sleep 2   # 노이즈가 먼저 램프업한 뒤 victim 시작
    fi

    # Start the victim: 실제 측정 대상 uploader 컨테이너 1개
    start_containers "${NET_VICTIM_IMAGE:-$NETWORK_UPLOADER_IMAGE}" 1 "--network=host -v $TESTFILE_PATH:$TESTFILE_PATH:ro"
    save_cgroup_ids "$cgroup_file"

    # Wait for the victim to finish
    wait_containers

    # Stop stressor + PureTime
    if [ -n "$stress_pid" ]; then
        kill "$stress_pid" 2>/dev/null || true
        pkill -9 -f "iperf3 -c $MINIO_IP" 2>/dev/null || true
    fi
    kill $puretime_pid 2>/dev/null || true
    wait $puretime_pid 2>/dev/null || true

    # Analyze (victim cgroup만)
    local puretime_result=$(python3 "$MAKESPAN" "$trace_file" -c "$cgroup_file")

    # Save results to CSV (container_count 열 = iperf3 -P flows)
    save_puretime_results "$puretime_result" "network" "$flows" "$iteration"

    # Cleanup
    stop_containers
    teardown_network_throttle "$iface"
    rmdir "$stress_cg" 2>/dev/null || true
    rmdir /sys/fs/cgroup/pt_netstress 2>/dev/null || true
}

run_block_io_experiment() {
    # $1 = fio 동시 job 수(stressor 강도). 0이면 solo(노이즈 없음, GT 기준).
    # victim은 항상 compression 컨테이너 1개(실제 함수); 노이즈는 별도 cgroup의 호스트 fio
    # (같은 디바이스 $HDD_MOUNT에 연속 버퍼드+fsync 쓰기, BFQ에서 victim과 경합). blkcg로 fio cgroup에 귀속.
    local jobs="$1"
    local iteration="$2"

    log_info "Block I/O experiment: fio --numjobs $jobs, iteration $iteration"

    local cgroup_file="$OUTPUT_DIR/cgroups_bio_${jobs}_${iteration}.txt"
    local stress_cg="/sys/fs/cgroup/pt_blkstress"

    setup_io_scheduler

    $PURETIME_BIN -v -t $TRACE_DURATION &
    local puretime_pid=$!
    sleep 2

    local trace_file=$(get_latest_trace)

    # Block stressor: 호스트 fio, 같은 디바이스에 연속 쓰기, 별도 cgroup(root io 위임 → blkcg 귀속).
    local stress_pid=""
    if [ "$jobs" -gt 0 ]; then
        mkdir -p "$stress_cg"
        bash -c "echo \$\$ > $stress_cg/cgroup.procs; exec fio --name=blkstress --directory=$HDD_MOUNT --rw=write --bs=1M --size=256M --numjobs=$jobs --time_based --runtime=$TRACE_DURATION --fsync=8 --direct=0 --group_reporting" > /dev/null 2>&1 &
        stress_pid=$!
        sleep 1
    fi

    # victim: 실제 compression 함수 컨테이너 1개 (HDD 마운트)
    # BLOCK_VICTIM_ENV로 모드/파라미터 override 가능 (A: -e COMPRESS_METHOD=raw_block -e IO_OPS=...,
    # B: -e COMPRESS_METHOD=stored -e FILE_SIZE_MB=...). 미설정 시 Dockerfile 기본(store 100MB).
    start_containers "${BLOCK_VICTIM_IMAGE:-$COMPRESSION_IMAGE}" 1 "-v $HDD_MOUNT:/tmp ${BLOCK_VICTIM_ENV:-}"
    save_cgroup_ids "$cgroup_file"
    wait_containers

    if [ -n "$stress_pid" ]; then
        kill "$stress_pid" 2>/dev/null || true
        pkill -9 -f "fio --name=blkstress" 2>/dev/null || true
    fi
    kill $puretime_pid 2>/dev/null || true
    wait $puretime_pid 2>/dev/null || true

    local puretime_result=$(python3 "$MAKESPAN" "$trace_file" -c "$cgroup_file")
    save_puretime_results "$puretime_result" "block_io" "$jobs" "$iteration"

    stop_containers
    rm -f "$HDD_MOUNT"/blkstress* 2>/dev/null
    rmdir "$stress_cg" 2>/dev/null || true
    restore_io_scheduler
}

# =============================================================================
# Main Execution
# =============================================================================

main() {
    # sudo rm -rf /tmp/puretime_* && sudo rm -rf /var/log/puretime

    check_prerequisites
    setup_output
    
    log_info "Starting Noise Type Accuracy Experiments"
    log_info "========================================="

    # RESOURCES 환경변수로 실행할 자원 선택 (기본=전부). 예: RESOURCES=block
    local RESOURCES="${RESOURCES:-cpu network block}"
    log_info "Resources to run: $RESOURCES"

    # CPU Experiments
    if [[ " $RESOURCES " == *" cpu "* ]]; then
    log_info ""
    log_info "=== CPU Contention Experiments ==="
    for workers in "${CPU_STRESS_WORKERS[@]}"; do
        for iter in $(seq 1 $ITERATIONS); do
            run_cpu_experiment "$workers" "$iter"
            sleep 10
        done
    done
    fi

    # Network Experiments
    if [[ " $RESOURCES " == *" network "* ]]; then
    log_info ""
    log_info "=== Network Contention Experiments ==="
    for flows in "${NET_STRESS_FLOWS[@]}"; do
        for iter in $(seq 1 $ITERATIONS); do
            run_network_experiment "$flows" "$iter"
            sleep 10
        done
    done
    fi

    # Block I/O Experiments
    if [[ " $RESOURCES " == *" block "* ]]; then
    log_info ""
    log_info "=== Block I/O Contention Experiments ==="
    # iter 바깥 / jobs 안쪽으로 interleave: solo(0)와 contended(4)를 iteration마다 번갈아 측정해
    # 각 contended run이 동시대 solo와 짝지어지도록 한다. (block=disk라 solo baseline이 시간에
    # 따라 drift(fragmentation/thermal)하므로, solo 전체→contended 전체 순서면 그 사이 누적된
    # degrade가 가짜 과다제거를 만든다. interleave로 drift에 강건하게.)
    for iter in $(seq 1 $ITERATIONS); do
        for jobs in "${BIO_STRESS_JOBS[@]}"; do
            run_block_io_experiment "$jobs" "$iter"
            sleep 10
        done
    done
    fi
    
    log_info ""
    log_info "========================================="
    log_info "Experiments completed!"
    log_info "Results saved to: $RESULTS_FILE"
    log_info ""
    log_info "To compute accuracy metrics:"
    log_info "  python3 $SCRIPT_DIR/analysis/compute_metrics.py $RESULTS_FILE"
}

main "$@"
