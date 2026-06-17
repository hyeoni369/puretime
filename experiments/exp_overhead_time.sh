#!/bin/bash
# =============================================================================
# PureTime Experiment: Tracing Overhead — (A) 지연 [DEPRECATED]
# =============================================================================
#
# ⚠️ DEPRECATED (2026-06-17): (A) 지연 오버헤드는 `exp_overhead_ctxsw.sh`로 대체됨.
#   이 방식(graph-bfs victim을 조용한/부하 환경에서 PureTime ON/OFF 절대시간 비교)은
#   PureTime 오버헤드가 <1%로 측정 노이즈보다 작아 **절반이 음수**로 나온다("PureTime을 켜면
#   더 빠르다?!" — HPDC 음수 논란). 부하를 같은 코어에서 경쟁시키면 victim CPU 몫 변동
#   (±15~33%)이 신호를 묻고, 경쟁을 없애면 이벤트가 사라져 0이 된다. 이 파일에는 그 과정에서
#   넣은 개선들(self-reported elapsed_ms, 터보 off, docker-create 배리어, counterbalance,
#   per-core 핀)이 남아 있으나, 근본 해결책은 **이벤트율을 x축으로 sweep**하는 ctxsw-bench다
#   (`exp_overhead_ctxsw.sh` + `plot_overhead_ctxsw.py` → fig3). contract C7 / design-final 실험5 참조.
#   (B) 자원 오버헤드는 `exp_overhead_resource.sh`(여전히 유효)에서 측정.
#
# 목적(옛): PureTime 트레이싱이 함수 실행 시간에 미치는 오버헤드 = T_with − T_without.
# Usage: sudo ./exp_overhead_time.sh [output_dir]
# =============================================================================

set -e

# =============================================================================
# Configuration Variables (수정 가능)
# =============================================================================

# 노이즈 유형별 실험 컨테이너 수 (고정값 - 유형별 비교가 목적)
CPU_CONTAINER_COUNTS=(1 5 8)
NET_CONTAINER_COUNTS=(1 5 8)
BIO_CONTAINER_COUNTS=(1 8 15)

# 반복 실험 횟수
ITERATIONS="${ITERATIONS:-20}"   # 오버헤드 ~1%를 안정적으로 잡으려 반복↑ (음수 노이즈 완화)

# PureTime 트레이싱 시간 (컨테이너 실행 완료까지 충분한 시간)
TRACE_DURATION=180

# =============================================================================
# Path Configuration
# =============================================================================

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PURETIME_DIR="$(dirname "$SCRIPT_DIR")"
PURETIME_BIN="$PURETIME_DIR/src/puretime"
MAKESPAN="$SCRIPT_DIR/noise_free_makespan.py"

OUTPUT_DIR="${1:-/tmp/puretime_exp_overhead_time_$(date +%Y%m%d_%H%M%S)}"
RESULTS_FILE="$OUTPUT_DIR/results.csv"

# Docker image names
GRAPH_BFS_IMAGE="graph-bfs"
NETWORK_UPLOADER_IMAGE="network-uploader"
COMPRESSION_IMAGE="compression"

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

log_info() { echo -e "${CYAN}[INFO]${NC} $1"; }
log_pass() { echo -e "${GREEN}[PASS]${NC} $1"; }
log_fail() { echo -e "${RED}[FAIL]${NC} $1"; }
log_warn() { echo -e "${YELLOW}[WARN]${NC} $1"; }

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
    docker build -t "$GRAPH_BFS_IMAGE" "$PURETIME_DIR/funcs/graph-bfs" > /dev/null 2>&1
    docker build -t "$NETWORK_UPLOADER_IMAGE" "$PURETIME_DIR/funcs/network-uploader" > /dev/null 2>&1
    docker build -t "$COMPRESSION_IMAGE" "$PURETIME_DIR/funcs/compression" > /dev/null 2>&1
    
    log_pass "Prerequisites OK"
}

setup_output() {
    mkdir -p "$OUTPUT_DIR"
    echo "cgroup_id,resource_type,container_count,iteration,t_e2e_ms,with_puretime" > "$RESULTS_FILE"
    log_info "Output directory: $OUTPUT_DIR"
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
    local percore="${4:-}"   # "percore"면 i번째 컨테이너를 코어 i에 핀(아래 설명)

    CONTAINER_IDS=()
    CONTAINER_CGROUP_IDS=()

    # 동시 시작 배리어: `docker run -d`를 count번 순차 실행하면 먼저 뜬 victim이 자원을 독점하다
    #   나중 것과 일부만 겹쳐, "동시 경쟁 정도"가 가변적이 된다. PureTime을 켜면 docker run이 살짝
    #   느려져 시작이 더 분산 → 경쟁↓ → self-timed elapsed_ms가 역설적으로 빨라짐(음수 오버헤드 아티팩트).
    #   먼저 모두 `docker create`(실행 X)한 뒤 한 번의 `docker start`로 거의 동시에 띄워 이 교란을 제거한다.
    # per-core 핀(CPU 실험): N개 victim을 한 코어에 몰면 스케줄링 경쟁(±15% 카오스)이 ~1% 오버헤드
    #   신호를 묻고 음수까지 만든다. 오버헤드는 "PureTime 트레이서가 주는 부하"이지 victim들끼리의
    #   CPU 쟁탈이 아니므로, 각 victim을 별도 코어(1..count)에 핀해 경쟁을 제거하고 "N개 함수 동시
    #   트레이싱 시 코어당 순수 오버헤드"를 깨끗이 측정한다(코어0은 OS/PureTime drain용으로 비움).
    for i in $(seq 1 $count); do
        local opts="$extra_opts"
        [ "$percore" = "percore" ] && opts="$extra_opts --cpuset-cpus=$i"
        CONTAINER_IDS+=("$(docker create $opts "$image")")
    done
    docker start "${CONTAINER_IDS[@]}" > /dev/null 2>&1

    # cgroup ID 추출 (best-effort). overhead_time은 victim self-reported elapsed_ms만 쓰고 cgroup_id는
    #   CSV에 기록만 하므로(makespan 분석 안 함), 짧은 victim이 inspect 전에 끝나(pid=0) 못 읽어도
    #   "na"로 두고 진행한다. set -e 하에서 죽지 않도록 모든 단계를 `|| true`로 보호.
    for cid in "${CONTAINER_IDS[@]}"; do
        local pid cgp cgroup_id="na"
        pid=$(docker inspect --format '{{.State.Pid}}' "$cid" 2>/dev/null || echo 0)
        if [ -n "$pid" ] && [ "$pid" != "0" ] && [ -r "/proc/$pid/cgroup" ]; then
            cgp=$(grep -oP '0::/\K.*' "/proc/$pid/cgroup" 2>/dev/null || true)
            [ -n "$cgp" ] && [ -e "/sys/fs/cgroup/${cgp}" ] && \
                cgroup_id=$(stat -c %i "/sys/fs/cgroup/${cgp}" 2>/dev/null || echo na)
        fi
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

# 컨테이너별 실행 시간 계산 (시작 ~ 종료)
declare -a CONTAINER_EXEC_TIMES

calculate_container_times() {
    # victim이 자체보고하는 순수 compute 시간(perf_counter 기반 `*elapsed_ms`)을 우선 사용한다.
    #   docker StartedAt→FinishedAt lifetime은 python 인터프리터 시작·import·컨테이너 teardown
    #   같은 가변 startup을 포함해 ~1% 오버헤드 신호를 묻어버린다(CV 27~59% → 절반이 음수로 보임).
    #   self-reported 시간은 그 startup을 배제해 측정 분산을 크게 줄인다. 못 읽으면 lifetime으로 fallback.
    CONTAINER_EXEC_TIMES=()
    for cid in "${CONTAINER_IDS[@]}"; do
        local elapsed=$(docker logs "$cid" 2>/dev/null \
            | grep -oE '"(total_)?elapsed_ms": *[0-9.]+' | grep -oE '[0-9.]+' | tail -1)
        if [ -z "$elapsed" ]; then
            local started_at=$(docker inspect --format '{{.State.StartedAt}}' "$cid")
            local finished_at=$(docker inspect --format '{{.State.FinishedAt}}' "$cid")
            elapsed=$(( $(date -d "$started_at" +%s%3N) ))
            elapsed=$(( $(date -d "$finished_at" +%s%3N) - elapsed ))
        fi
        CONTAINER_EXEC_TIMES+=("$(printf '%.0f' "$elapsed")")
    done
}

# 컨테이너별 실행 시간을 CSV에 저장
save_container_times() {
    local resource_type="$1"
    local count="$2"
    local iteration="$3"
    local with_puretime="${4}"
    for i in "${!CONTAINER_IDS[@]}"; do
        local cgroup_id="${CONTAINER_CGROUP_IDS[$i]}"
        local exec_time="${CONTAINER_EXEC_TIMES[$i]}"
        echo "$cgroup_id,$resource_type,$count,$iteration,$exec_time,$with_puretime" >> "$RESULTS_FILE"
    done
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
}

restore_io_scheduler() {
    if [ -n "$BLOCK_DEVICE" ] && [ -n "$ORIGINAL_SCHEDULER" ] && [ "$ORIGINAL_SCHEDULER" != "bfq" ]; then
        local sched_path="/sys/block/$BLOCK_DEVICE/queue/scheduler"
        echo "$ORIGINAL_SCHEDULER" > "$sched_path" 2>/dev/null || true
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
    local count="$1"
    local iteration="$2"
    local with_puretime="$3"
    
    log_info "CPU experiment: $count containers, iteration $iteration"
    
    # Start PureTime
    if [ "$with_puretime" = "true" ]; then
        $PURETIME_BIN -v -t $TRACE_DURATION &
        local puretime_pid=$!
    fi
    sleep 2
    
    # Start containers (CPU pinned to core 0)
    start_containers "$GRAPH_BFS_IMAGE" "$count" "" "percore"
    
    # Wait for all containers to complete
    wait_containers
    
    # Stop PureTime
    if [ "$with_puretime" = "true" ]; then
        kill $puretime_pid 2>/dev/null || true
        wait $puretime_pid 2>/dev/null || true
    fi

    # Calculate and save container execution times
    calculate_container_times
    save_container_times "cpu" "$count" "$iteration" "$with_puretime"

    # Cleanup
    stop_containers
}

run_network_experiment() {
    local count="$1"
    local iteration="$2"
    local with_puretime="$3"
    
    log_info "Network experiment: $count containers, iteration $iteration"
    
    ensure_testfile
    
    # Setup network throttle
    local iface=$(setup_network_throttle)
    
    # Start PureTime
    if [ "$with_puretime" = "true" ]; then
        $PURETIME_BIN -v -t $TRACE_DURATION &
        local puretime_pid=$!
    fi
    sleep 2
    
    # Start containers
    start_containers "$NETWORK_UPLOADER_IMAGE" "$count" "--network=host -v $TESTFILE_PATH:$TESTFILE_PATH:ro"
    
    # Wait for completion
    wait_containers
    
    # Stop PureTime
    if [ "$with_puretime" = "true" ]; then
        kill $puretime_pid 2>/dev/null || true
        wait $puretime_pid 2>/dev/null || true
    fi

    # Calculate and save container execution times
    calculate_container_times
    save_container_times "network" "$count" "$iteration" "$with_puretime"

    # Cleanup
    stop_containers
    teardown_network_throttle "$iface"
}

run_block_io_experiment() {
    local count="$1"
    local iteration="$2"
    local with_puretime="$3"

    log_info "Block I/O experiment: $count containers, iteration $iteration"
    
    # Setup I/O scheduler
    setup_io_scheduler
    
    # Start PureTime
    if [ "$with_puretime" = "true" ]; then
        $PURETIME_BIN -v -t $TRACE_DURATION &
        local puretime_pid=$!
    fi
    sleep 2
    
    # Start containers (with HDD mount)
    start_containers "$COMPRESSION_IMAGE" "$count" "-v $HDD_MOUNT:/tmp"
    
    # Wait for completion
    wait_containers
    
    # Stop PureTime
    if [ "$with_puretime" = "true" ]; then
        kill $puretime_pid 2>/dev/null || true
        wait $puretime_pid 2>/dev/null || true
    fi

    # Calculate and save container execution times
    calculate_container_times
    save_container_times "block_io" "$count" "$iteration" "$with_puretime"

    # Cleanup
    stop_containers
    restore_io_scheduler
}

# =============================================================================
# Main Execution
# =============================================================================

# CPU 터보(boost) 비활성화 — 터보가 코어 활동/열에 따라 주파수를 출렁이게 해 측정 분산을 키운다.
#   amd-pstate-epp(active)에선 scaling_max_freq 클램프는 HWP가 무시하지만(검증함), 시스템 전역
#   `cpufreq/boost` 노브는 먹는다 → 측정 동안 boost=0으로 base 주파수 고정, 끝나면 원복(EXIT 트랩).
#   (주 변동원은 사실 docker lifetime의 python startup이었고 self-reported elapsed_ms로 이미 제거됨.
#    boost off는 잔여 주파수 흔들림까지 줄이는 보조 장치.)
ORIG_BOOST=""
setup_freq_pin() {
    ORIG_BOOST=$(cat /sys/devices/system/cpu/cpufreq/boost 2>/dev/null)
    [ -z "$ORIG_BOOST" ] && { log_info "cpufreq/boost 제어 불가 — 터보 고정 건너뜀"; return; }
    echo 0 > /sys/devices/system/cpu/cpufreq/boost 2>/dev/null || true
    log_info "CPU 터보(boost) 비활성화 (측정 분산 감소; 원래값=$ORIG_BOOST)"
}
restore_freq_pin() {
    [ -z "$ORIG_BOOST" ] && return
    echo "$ORIG_BOOST" > /sys/devices/system/cpu/cpufreq/boost 2>/dev/null || true
    ORIG_BOOST=""
}

main() {
    # sudo rm -rf /tmp/puretime_* && sudo rm -rf /var/log/puretime

    check_prerequisites
    setup_output
    trap restore_freq_pin EXIT INT TERM
    setup_freq_pin
    
    log_info "Starting Noise Type Accuracy Experiments"
    log_info "========================================="
    
    # CPU Experiments
    log_info ""
    log_info "=== CPU Contention Experiments ==="
    for count in "${CPU_CONTAINER_COUNTS[@]}"; do
        for iter in $(seq 1 $ITERATIONS); do
            # counterbalancing: 홀수 iter는 without→with, 짝수는 with→without. 잔여 워밍업/드리프트
            #   bias가 두 조건에 균등 분배되어 상쇄된다(둘 중 한쪽만 항상 2번째라 빨라지는 효과 제거).
            if (( iter % 2 == 1 )); then
                run_cpu_experiment "$count" "$iter" "false"
                run_cpu_experiment "$count" "$iter" "true"
            else
                run_cpu_experiment "$count" "$iter" "true"
                run_cpu_experiment "$count" "$iter" "false"
            fi
        done
    done
    sleep 2

    # Network Experiments
    log_info ""
    log_info "=== Network Contention Experiments ==="
    for count in "${NET_CONTAINER_COUNTS[@]}"; do
        for iter in $(seq 1 $ITERATIONS); do
            if (( iter % 2 == 1 )); then
                run_network_experiment "$count" "$iter" "false"
                run_network_experiment "$count" "$iter" "true"
            else
                run_network_experiment "$count" "$iter" "true"
                run_network_experiment "$count" "$iter" "false"
            fi
        done
    done
    sleep 2
    
    # Block I/O Experiments
    log_info ""
    log_info "=== Block I/O Contention Experiments ==="
    for count in "${BIO_CONTAINER_COUNTS[@]}"; do
        for iter in $(seq 1 $ITERATIONS); do
            if (( iter % 2 == 1 )); then
                run_block_io_experiment "$count" "$iter" "false"
                run_block_io_experiment "$count" "$iter" "true"
            else
                run_block_io_experiment "$count" "$iter" "true"
                run_block_io_experiment "$count" "$iter" "false"
            fi
        done
    done
    sleep 2
    
    log_info ""
    log_info "========================================="
    log_info "Experiments completed!"
    log_info "Results saved to: $RESULTS_FILE"
}

main "$@"
