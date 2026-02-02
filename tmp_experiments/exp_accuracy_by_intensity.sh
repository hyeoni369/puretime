#!/bin/bash
# =============================================================================
# PureTime Experiment: Noise Removal Accuracy by Contention Intensity
# =============================================================================
# 
# 목적: 노이즈 강도(동시 실행 컨테이너 수)에 따른 PureTime의 노이즈 제거 정확도 변화 측정
#       (노이즈 유형은 CPU로 고정, 강도별 변화만 비교)
#
# 정확도 계산 방식:
#   Ground Truth Noise = T_contention - T_isolated
#   Removed Noise      = T_contention - T_puretime
#   Efficiency         = (Removed Noise / Ground Truth Noise) × 100%
#
# Usage: sudo ./exp_accuracy_by_intensity.sh [output_dir]
# =============================================================================

set -e

# =============================================================================
# Configuration Variables (수정 가능)
# =============================================================================

# 노이즈 강도별 컨테이너 수 배열 (1은 Solo baseline)
CONTAINER_COUNTS=(1 2 4 8 16)

# 반복 실험 횟수
ITERATIONS=10

# PureTime 트레이싱 시간 (컨테이너 실행 완료까지 충분한 시간)
TRACE_DURATION=180

# =============================================================================
# Path Configuration
# =============================================================================

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PURETIME_DIR="$(dirname "$SCRIPT_DIR")"
PURETIME_BIN="$PURETIME_DIR/src/puretime"
MAKESPAN_ANALYZER="$PURETIME_DIR/tests/noise_free_makespan.py"

OUTPUT_DIR="${1:-/tmp/puretime_exp_intensity_$(date +%Y%m%d_%H%M%S)}"
RESULTS_FILE="$OUTPUT_DIR/results.csv"

# Docker image name (CPU-bound workload for intensity test)
GRAPH_BFS_IMAGE="graph-bfs"

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
    
    if [ ! -f "$MAKESPAN_ANALYZER" ]; then
        log_fail "Makespan analyzer not found at $MAKESPAN_ANALYZER"
        exit 1
    fi
    
    # Build Docker image if needed
    log_info "Building Docker image..."
    docker build -t "$GRAPH_BFS_IMAGE" "$PURETIME_DIR/funcs/graph-bfs" > /dev/null 2>&1
    
    log_pass "Prerequisites OK"
}

setup_output() {
    mkdir -p "$OUTPUT_DIR"
    echo "container_count,iteration,t_contention_ms,t_puretime_ms,cgroup_ids" > "$RESULTS_FILE"
    log_info "Output directory: $OUTPUT_DIR"
}

get_latest_trace() {
    ls -t /var/log/puretime/trace_*.jsonl 2>/dev/null | head -1
}

# =============================================================================
# Container Management Functions (run_with_function.sh 패턴)
# =============================================================================

declare -a CONTAINER_IDS
declare -a CONTAINER_CGROUP_IDS

start_containers() {
    local count="$1"
    local extra_opts="$2"
    
    CONTAINER_IDS=()
    CONTAINER_CGROUP_IDS=()
    
    for i in $(seq 1 $count); do
        local cid=$(docker run -d $extra_opts "$GRAPH_BFS_IMAGE")
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

get_container_execution_time() {
    local cid="$1"
    local log=$(docker logs "$cid" 2>/dev/null)
    
    # elapsed_ms 또는 total_elapsed_ms 필드 추출
    local elapsed=$(echo "$log" | grep -oP '"elapsed_ms"\s*:\s*\K[0-9.]+' | head -1)
    if [ -z "$elapsed" ]; then
        elapsed=$(echo "$log" | grep -oP '"total_elapsed_ms"\s*:\s*\K[0-9.]+' | head -1)
    fi
    
    echo "${elapsed:-0}"
}

save_cgroup_ids() {
    local filepath="$1"
    > "$filepath"
    for cgroup_id in "${CONTAINER_CGROUP_IDS[@]}"; do
        echo "$cgroup_id" >> "$filepath"
    done
}

# =============================================================================
# Experiment Function
# =============================================================================

run_experiment() {
    local count="$1"
    local iteration="$2"
    
    log_info "Intensity experiment: $count containers, iteration $iteration"
    
    local cgroup_file="$OUTPUT_DIR/cgroups_${count}_${iteration}.txt"
    
    # Start PureTime
    $PURETIME_BIN -t $TRACE_DURATION &
    local puretime_pid=$!
    sleep 2
    
    local trace_file=$(get_latest_trace)
    
    # Start containers (CPU pinned to core 0 for consistent contention)
    start_containers "$count" "--cpuset-cpus=0"
    save_cgroup_ids "$cgroup_file"
    
    # Wait for all containers to complete
    wait_containers
    
    # Get execution times from container logs (average of all containers)
    local total_time=0
    for cid in "${CONTAINER_IDS[@]}"; do
        local t=$(get_container_execution_time "$cid")
        total_time=$(echo "$total_time + $t" | bc)
    done
    local avg_time=$(echo "scale=2; $total_time / $count" | bc)
    
    # Stop PureTime
    kill $puretime_pid 2>/dev/null || true
    wait $puretime_pid 2>/dev/null || true
    
    # Analyze with PureTime
    local puretime_result=$(python3 "$MAKESPAN_ANALYZER" "$trace_file" -c "$cgroup_file" -j 2>/dev/null)
    local t_puretime=$(echo "$puretime_result" | grep -oP '"noise_free_makespan_ns"\s*:\s*\K[0-9]+' | head -1)
    t_puretime=$(echo "scale=2; ${t_puretime:-0} / 1000000" | bc)  # ns -> ms
    
    # Cleanup
    stop_containers
    
    # Save results
    local cgroup_list=$(IFS=';'; echo "${CONTAINER_CGROUP_IDS[*]}")
    echo "$count,$iteration,$avg_time,$t_puretime,$cgroup_list" >> "$RESULTS_FILE"
    
    log_info "  T_contention=${avg_time}ms, T_puretime=${t_puretime}ms"
}

# =============================================================================
# Main Execution
# =============================================================================

main() {
    check_prerequisites
    setup_output
    
    log_info "Starting Noise Intensity Accuracy Experiments"
    log_info "============================================="
    log_info "Container counts: ${CONTAINER_COUNTS[*]}"
    log_info "Iterations per count: $ITERATIONS"
    log_info ""
    
    for count in "${CONTAINER_COUNTS[@]}"; do
        log_info "=== Testing with $count container(s) ==="
        for iter in $(seq 1 $ITERATIONS); do
            run_experiment "$count" "$iter"
        done
        log_info ""
    done
    
    log_info "============================================="
    log_info "Experiments completed!"
    log_info "Results saved to: $RESULTS_FILE"
    log_info ""
    log_info "To compute accuracy metrics:"
    log_info "  python3 $SCRIPT_DIR/analysis/compute_metrics_intensity.py $RESULTS_FILE"
}

main "$@"
