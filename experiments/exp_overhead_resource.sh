#!/bin/bash
# =============================================================================
# PureTime Experiment: Resource Usage Measurement
# =============================================================================
#
# 목적: PureTime 프로세스 자체의 리소스 사용량 측정
#
# 측정 항목:
#   [유저스페이스]
#   - CPU 사용률 (%) - 순간 사용률
#   - 메모리 사용량 (MB)
#
# Usage: sudo ./exp_overhead_resource.sh [output_dir]
# =============================================================================

set -e

# =============================================================================
# Configuration Variables (수정 가능)
# =============================================================================

# 노이즈 유형별 실험 컨테이너 수 (고정값 - 유형별 비교가 목적)
CPU_CONTAINER_COUNTS=(1 2 4)
NET_CONTAINER_COUNTS=(1 2 4)
BIO_CONTAINER_COUNTS=(1 5 10)

# 반복 실험 횟수
ITERATIONS=50

# PureTime 트레이싱 시간 (컨테이너 실행 완료까지 충분한 시간)
TRACE_DURATION=180

# =============================================================================
# Path Configuration
# =============================================================================

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PURETIME_DIR="$(dirname "$SCRIPT_DIR")"
PURETIME_BIN="$PURETIME_DIR/src/puretime"

OUTPUT_DIR="${1:-/tmp/puretime_exp_resource_$(date +%Y%m%d_%H%M%S)}"

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
# Resource Monitoring Variables
# =============================================================================

RESOURCE_FILE=""
MONITOR_INTERVAL=1  # 초
MONITOR_PID=""

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

    # Build Docker images if needed
    log_info "Building Docker images..."
    docker build -t "$GRAPH_BFS_IMAGE" "$PURETIME_DIR/funcs/graph-bfs" > /dev/null 2>&1
    docker build -t "$NETWORK_UPLOADER_IMAGE" "$PURETIME_DIR/funcs/network-uploader" > /dev/null 2>&1
    docker build -t "$COMPRESSION_IMAGE" "$PURETIME_DIR/funcs/compression" > /dev/null 2>&1
    
    log_pass "Prerequisites OK"
}

setup_output() {
    mkdir -p "$OUTPUT_DIR"
    RESOURCE_FILE="$OUTPUT_DIR/resource_usage.csv"
    echo "timestamp,resource_type,container_count,iteration,cpu_percent,memory_mb,cpu_ratio_system,mem_ratio_system" > "$RESOURCE_FILE"
    log_info "Output directory: $OUTPUT_DIR"
}

# =============================================================================
# Resource Monitoring Functions
# =============================================================================

start_resource_monitor() {
    local resource_type="$1"
    local count="$2"
    local iteration="$3"

    (
        local prev_utime=0
        local prev_stime=0
        local prev_time=0
        local is_first=1
        local hz=$(getconf CLK_TCK)  # 시스템 실제 HZ 값 (100, 250, 1000 등)

        while true; do
            local timestamp=$(date +%s.%N)
            local pt_pid=$(pgrep -x "puretime" | head -1)

            if [ -n "$pt_pid" ] && [ -d "/proc/$pt_pid" ]; then
                # /proc/[pid]/stat에서 CPU 시간 읽기 (utime, stime)
                local stat_line=$(cat /proc/$pt_pid/stat 2>/dev/null)
                if [ -n "$stat_line" ]; then
                    local utime=$(echo "$stat_line" | awk '{print $14}')
                    local stime=$(echo "$stat_line" | awk '{print $15}')
                    local curr_time=$(date +%s%N)

                    # 순간 CPU 사용률 계산 (이전 측정과의 차이)
                    local cpu=0
                    if [ "$prev_time" -ne 0 ]; then
                        local delta_utime=$((utime - prev_utime))
                        local delta_stime=$((stime - prev_stime))
                        local delta_time=$((curr_time - prev_time))
                        # clock ticks to nanoseconds (using actual system HZ)
                        local cpu_time_ns=$(( (delta_utime + delta_stime) * 1000000000 / hz ))
                        if [ "$delta_time" -gt 0 ]; then
                            cpu=$(awk "BEGIN {printf \"%.2f\", $cpu_time_ns / $delta_time * 100}")
                        fi
                    fi

                    prev_utime=$utime
                    prev_stime=$stime
                    prev_time=$curr_time

                    # 메모리 사용량 (MB) - RSS
                    local mem=$(ps -o rss= -p $pt_pid 2>/dev/null | awk '{print $1/1024}')

                    # 시스템 대비 비율 계산
                    local total_cpu=$(nproc)
                    local total_mem=$(free -m | awk '/Mem:/ {print $2}')
                    local cpu_ratio=$(awk "BEGIN {printf \"%.4f\", $cpu / ($total_cpu * 100) * 100}")
                    local mem_ratio=$(awk "BEGIN {printf \"%.4f\", ${mem:-0} / $total_mem * 100}")

                    # 첫 번째 측정은 기준점이므로 스킵, 이후 0% CPU도 정상 기록
                    if [ "$is_first" -eq 1 ]; then
                        is_first=0
                    elif [ -n "$mem" ]; then
                        echo "$timestamp,$resource_type,$count,$iteration,$cpu,$mem,$cpu_ratio,$mem_ratio" >> "$RESOURCE_FILE"
                    fi
                fi
            fi
            sleep $MONITOR_INTERVAL
        done
    ) &
    MONITOR_PID=$!
}

stop_resource_monitor() {
    if [ -n "$MONITOR_PID" ]; then
        kill $MONITOR_PID 2>/dev/null || true
        wait $MONITOR_PID 2>/dev/null || true
        MONITOR_PID=""
    fi
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

    log_info "CPU experiment: $count containers, iteration $iteration"

    # Start PureTime
    $PURETIME_BIN -v -t $TRACE_DURATION &
    local puretime_pid=$!
    sleep 2

    # Start resource monitoring
    start_resource_monitor "cpu" "$count" "$iteration"

    # Start containers (CPU pinned to core 0)
    start_containers "$GRAPH_BFS_IMAGE" "$count" "--cpuset-cpus=0"

    # Wait for all containers to complete
    wait_containers

    # Stop resource monitoring
    stop_resource_monitor

    # Stop PureTime
    kill $puretime_pid 2>/dev/null || true
    wait $puretime_pid 2>/dev/null || true

    # Cleanup
    stop_containers
}

run_network_experiment() {
    local count="$1"
    local iteration="$2"

    log_info "Network experiment: $count containers, iteration $iteration"

    ensure_testfile

    # Setup network throttle
    local iface=$(setup_network_throttle)

    # Start PureTime
    $PURETIME_BIN -v -t $TRACE_DURATION &
    local puretime_pid=$!
    sleep 2

    # Start resource monitoring
    start_resource_monitor "network" "$count" "$iteration"

    # Start containers
    start_containers "$NETWORK_UPLOADER_IMAGE" "$count" "--network=host -v $TESTFILE_PATH:$TESTFILE_PATH:ro"

    # Wait for completion
    wait_containers

    # Stop resource monitoring
    stop_resource_monitor

    # Stop PureTime
    kill $puretime_pid 2>/dev/null || true
    wait $puretime_pid 2>/dev/null || true

    # Cleanup
    stop_containers
    teardown_network_throttle "$iface"
}

run_block_io_experiment() {
    local count="$1"
    local iteration="$2"

    log_info "Block I/O experiment: $count containers, iteration $iteration"

    # Setup I/O scheduler
    setup_io_scheduler

    # Start PureTime
    $PURETIME_BIN -v -t $TRACE_DURATION &
    local puretime_pid=$!
    sleep 2

    # Start resource monitoring
    start_resource_monitor "block_io" "$count" "$iteration"

    # Start containers (with HDD mount)
    start_containers "$COMPRESSION_IMAGE" "$count" "-v $HDD_MOUNT:/tmp"

    # Wait for completion
    wait_containers

    # Stop resource monitoring
    stop_resource_monitor

    # Stop PureTime
    kill $puretime_pid 2>/dev/null || true
    wait $puretime_pid 2>/dev/null || true

    # Cleanup
    stop_containers
    restore_io_scheduler
}

# =============================================================================
# Main Execution
# =============================================================================

main() {
    # sudo rm -rf /tmp/puretime_* && sudo rm -rf /var/log/puretime

    check_prerequisites
    setup_output

    log_info "Starting PureTime Resource Usage Experiments"
    log_info "============================================="

    # CPU Experiments
    log_info ""
    log_info "=== CPU Contention Experiments ==="
    for count in "${CPU_CONTAINER_COUNTS[@]}"; do
        for iter in $(seq 1 $ITERATIONS); do
            run_cpu_experiment "$count" "$iter"
        done
    done
    sleep 2

    # Network Experiments
    log_info ""
    log_info "=== Network Contention Experiments ==="
    for count in "${NET_CONTAINER_COUNTS[@]}"; do
        for iter in $(seq 1 $ITERATIONS); do
            run_network_experiment "$count" "$iter"
        done
    done
    sleep 2

    # Block I/O Experiments
    log_info ""
    log_info "=== Block I/O Contention Experiments ==="
    for count in "${BIO_CONTAINER_COUNTS[@]}"; do
        for iter in $(seq 1 $ITERATIONS); do
            run_block_io_experiment "$count" "$iter"
        done
    done
    sleep 2

    log_info ""
    log_info "============================================="
    log_info "Experiments completed!"
    log_info "Resource usage saved to: $RESOURCE_FILE"
}

main "$@"
