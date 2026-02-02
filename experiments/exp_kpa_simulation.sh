#!/bin/bash
# =============================================================================
# PureTime Case Study: KPA Concurrency-based Autoscaling Simulation
# =============================================================================
# 
# 목적: Noisy Neighbor가 KPA의 Concurrency 기반 스케일링 결정에 미치는 영향 분석
#
# 배경:
#   KPA (Knative Pod Autoscaler)는 Little's Law 기반으로 동작:
#     Concurrency = RPS × Latency
#   
#   Noisy Neighbor로 인해 Latency가 부풀려지면:
#     - KPA가 "부하 증가"로 오인
#     - 불필요한 Pod scale-out 발생
#     - Over-provisioning으로 인한 비용 낭비
#
# 시뮬레이션:
#   1. 고정된 RPS로 요청 전송
#   2. T_contention (실제 측정) vs T_puretime (노이즈 제거) 비교
#   3. 각각의 Latency로 Concurrency 계산
#   4. KPA의 scaling 결정 시뮬레이션
#
# Usage: sudo ./exp_kpa_simulation.sh [output_dir]
# =============================================================================

set -e

# =============================================================================
# Configuration Variables (수정 가능)
# =============================================================================

# 시뮬레이션 파라미터
TARGET_RPS_VALUES=(1 5 10 20)           # 테스트할 RPS 값들
NOISE_CONTAINER_COUNTS=(0 2 4 8)        # Noisy neighbor 컨테이너 수

# KPA 파라미터 (Knative 기본값)
TARGET_CONCURRENCY=100                   # KPA target concurrency
STABLE_WINDOW_SECONDS=60                # Stable window for scaling decisions
MAX_SCALE_UP_RATE=1000                  # Maximum scale up rate (1000%)

# 시뮬레이션 시간
REQUESTS_PER_SCENARIO=50                # 각 시나리오당 요청 수
TRACE_DURATION=300                      # PureTime 트레이싱 시간

# =============================================================================
# Path Configuration
# =============================================================================

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PURETIME_DIR="$(dirname "$SCRIPT_DIR")"
PURETIME_BIN="$PURETIME_DIR/src/puretime"
MAKESPAN_ANALYZER="$SCRIPT_DIR/noise_free_makespan.py"

OUTPUT_DIR="${1:-/tmp/puretime_kpa_sim_$(date +%Y%m%d_%H%M%S)}"
RESULTS_FILE="$OUTPUT_DIR/kpa_simulation.csv"
ANALYSIS_FILE="$OUTPUT_DIR/kpa_analysis.json"

# Docker images
GRAPH_BFS_IMAGE="graph-bfs"
STRESS_IMAGE="stress-ng"

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
    
    # Build Docker images
    log_info "Building Docker images..."
    docker build -t "$GRAPH_BFS_IMAGE" "$PURETIME_DIR/funcs/graph-bfs" > /dev/null 2>&1
    
    # stress-ng for background noise
    if ! docker images | grep -q stress-ng; then
        log_info "Pulling stress-ng image..."
        docker pull alexeiled/stress-ng > /dev/null 2>&1 || \
            docker pull lorel/docker-stress-ng > /dev/null 2>&1
    fi
    
    log_pass "Prerequisites OK"
}

setup_output() {
    mkdir -p "$OUTPUT_DIR"
    echo "rps,noise_containers,request_id,t_contention_ms,t_puretime_ms,concurrency_observed,concurrency_puretime,kpa_decision_observed,kpa_decision_puretime" > "$RESULTS_FILE"
    log_info "Output directory: $OUTPUT_DIR"
}

get_latest_trace() {
    ls -t /var/log/puretime/trace_*.jsonl 2>/dev/null | head -1
}

# =============================================================================
# Noise Generator (Background stress containers)
# =============================================================================

declare -a NOISE_CONTAINER_IDS

start_noise_containers() {
    local count="$1"
    NOISE_CONTAINER_IDS=()
    
    if [ "$count" -eq 0 ]; then
        return
    fi
    
    log_info "Starting $count noise containers..."
    
    for i in $(seq 1 $count); do
        # CPU stress on same core as function
        local cid=$(docker run -d --cpuset-cpus=0 alexeiled/stress-ng \
            --cpu 1 --cpu-load 80 --timeout 0 2>/dev/null || \
            docker run -d --cpuset-cpus=0 lorel/docker-stress-ng \
            --cpu 1 --cpu-load 80 --timeout 0 2>/dev/null)
        NOISE_CONTAINER_IDS+=("$cid")
    done
}

stop_noise_containers() {
    for cid in "${NOISE_CONTAINER_IDS[@]}"; do
        docker rm -f "$cid" > /dev/null 2>&1 || true
    done
    NOISE_CONTAINER_IDS=()
}

# =============================================================================
# Function Container Management
# =============================================================================

declare -a CONTAINER_IDS
declare -a CONTAINER_CGROUP_IDS

run_function_container() {
    local cid=$(docker run -d --cpuset-cpus=0 "$GRAPH_BFS_IMAGE")
    CONTAINER_IDS+=("$cid")
    
    # cgroup ID 추출
    local pid=$(docker inspect --format '{{.State.Pid}}' "$cid")
    local cgroup_path=$(cat /proc/$pid/cgroup | grep -oP '0::/\K.*')
    local cgroup_id=$(stat -c %i "/sys/fs/cgroup/${cgroup_path}")
    CONTAINER_CGROUP_IDS+=("$cgroup_id")
    
    echo "$cid"
}

get_container_execution_time() {
    local cid="$1"
    local log=$(docker logs "$cid" 2>/dev/null)
    
    local elapsed=$(echo "$log" | grep -oP '"elapsed_ms"\s*:\s*\K[0-9.]+' | head -1)
    if [ -z "$elapsed" ]; then
        elapsed=$(echo "$log" | grep -oP '"total_elapsed_ms"\s*:\s*\K[0-9.]+' | head -1)
    fi
    
    echo "${elapsed:-0}"
}

cleanup_function_containers() {
    for cid in "${CONTAINER_IDS[@]}"; do
        docker rm -f "$cid" > /dev/null 2>&1 || true
    done
    CONTAINER_IDS=()
    CONTAINER_CGROUP_IDS=()
}

# =============================================================================
# KPA Scaling Decision Simulation
# =============================================================================

calculate_concurrency() {
    # Concurrency = RPS × Latency (in seconds)
    local rps="$1"
    local latency_ms="$2"
    
    echo "scale=2; $rps * $latency_ms / 1000" | bc
}

simulate_kpa_decision() {
    # KPA scaling decision based on observed concurrency vs target
    # Returns: scale-out, stable, scale-in
    local concurrency="$1"
    
    # KPA scales when concurrency exceeds target
    local ratio=$(echo "scale=2; $concurrency / $TARGET_CONCURRENCY" | bc)
    
    if (( $(echo "$ratio > 1.1" | bc -l) )); then
        echo "scale-out"
    elif (( $(echo "$ratio < 0.9" | bc -l) )); then
        echo "scale-in"
    else
        echo "stable"
    fi
}

calculate_desired_replicas() {
    # KPA desired replicas = ceil(concurrency / target_concurrency)
    local concurrency="$1"
    
    local replicas=$(echo "scale=0; ($concurrency + $TARGET_CONCURRENCY - 1) / $TARGET_CONCURRENCY" | bc)
    if [ "$replicas" -lt 1 ]; then
        replicas=1
    fi
    echo "$replicas"
}

# =============================================================================
# Main Experiment Loop
# =============================================================================

run_kpa_scenario() {
    local rps="$1"
    local noise_count="$2"
    
    log_info "=== RPS=$rps, Noise containers=$noise_count ==="
    
    # Start noise containers
    start_noise_containers "$noise_count"
    sleep 2  # Let noise stabilize
    
    # Start PureTime
    $PURETIME_BIN -t $TRACE_DURATION &
    local puretime_pid=$!
    sleep 2
    
    local trace_file=$(get_latest_trace)
    local cgroup_file="$OUTPUT_DIR/cgroups_rps${rps}_noise${noise_count}.txt"
    
    CONTAINER_IDS=()
    CONTAINER_CGROUP_IDS=()
    
    # Calculate inter-request delay for target RPS
    local delay_ms=$(echo "scale=0; 1000 / $rps" | bc)
    
    # Send requests at specified RPS
    for req_id in $(seq 1 $REQUESTS_PER_SCENARIO); do
        # Run function container
        local cid=$(run_function_container)
        
        # Wait for completion
        docker wait "$cid" > /dev/null 2>&1 || true
        
        # Get execution time
        local t_contention=$(get_container_execution_time "$cid")
        
        # Save cgroup for PureTime analysis
        echo "${CONTAINER_CGROUP_IDS[-1]}" >> "$cgroup_file"
        
        # Inter-request delay to maintain RPS
        sleep $(echo "scale=3; $delay_ms / 1000" | bc)
    done
    
    # Stop PureTime
    kill $puretime_pid 2>/dev/null || true
    wait $puretime_pid 2>/dev/null || true
    
    # Analyze each request with PureTime
    local req_id=0
    for cid in "${CONTAINER_IDS[@]}"; do
        req_id=$((req_id + 1))
        
        local t_contention=$(get_container_execution_time "$cid")
        
        # Get PureTime's noise-free makespan for this container
        local single_cgroup_file="$OUTPUT_DIR/tmp_cgroup.txt"
        echo "${CONTAINER_CGROUP_IDS[$((req_id-1))]}" > "$single_cgroup_file"
        
        local puretime_result=$(python3 "$MAKESPAN_ANALYZER" "$trace_file" -c "$single_cgroup_file" -j 2>/dev/null)
        local t_puretime=$(echo "$puretime_result" | grep -oP '"noise_free_makespan_ns"\s*:\s*\K[0-9]+' | head -1)
        t_puretime=$(echo "scale=2; ${t_puretime:-0} / 1000000" | bc)
        
        # Calculate concurrency for both
        local conc_observed=$(calculate_concurrency "$rps" "$t_contention")
        local conc_puretime=$(calculate_concurrency "$rps" "$t_puretime")
        
        # Simulate KPA decisions
        local kpa_observed=$(simulate_kpa_decision "$conc_observed")
        local kpa_puretime=$(simulate_kpa_decision "$conc_puretime")
        
        # Save results
        echo "$rps,$noise_count,$req_id,$t_contention,$t_puretime,$conc_observed,$conc_puretime,$kpa_observed,$kpa_puretime" >> "$RESULTS_FILE"
    done
    
    # Cleanup
    cleanup_function_containers
    stop_noise_containers
    rm -f "$OUTPUT_DIR/tmp_cgroup.txt"
    
    log_info "Completed scenario RPS=$rps, Noise=$noise_count"
}

# =============================================================================
# Analysis Functions
# =============================================================================

generate_analysis() {
    log_info "Generating analysis..."
    
    python3 << EOF
import csv
import json
from collections import defaultdict

results = []
with open('$RESULTS_FILE', 'r') as f:
    reader = csv.DictReader(f)
    for row in reader:
        results.append(row)

# Group by (rps, noise_containers)
analysis = defaultdict(lambda: {
    't_contention': [],
    't_puretime': [],
    'conc_observed': [],
    'conc_puretime': [],
    'kpa_observed': defaultdict(int),
    'kpa_puretime': defaultdict(int),
})

for r in results:
    key = (int(r['rps']), int(r['noise_containers']))
    analysis[key]['t_contention'].append(float(r['t_contention_ms']))
    analysis[key]['t_puretime'].append(float(r['t_puretime_ms']))
    analysis[key]['conc_observed'].append(float(r['concurrency_observed']))
    analysis[key]['conc_puretime'].append(float(r['concurrency_puretime']))
    analysis[key]['kpa_observed'][r['kpa_decision_observed']] += 1
    analysis[key]['kpa_puretime'][r['kpa_decision_puretime']] += 1

# Calculate summary statistics
summary = []
for (rps, noise), data in sorted(analysis.items()):
    avg_t_cont = sum(data['t_contention']) / len(data['t_contention'])
    avg_t_pure = sum(data['t_puretime']) / len(data['t_puretime'])
    avg_conc_obs = sum(data['conc_observed']) / len(data['conc_observed'])
    avg_conc_pure = sum(data['conc_puretime']) / len(data['conc_puretime'])
    
    # Calculate over-provisioning rate (scale-out decisions that wouldn't happen with PureTime)
    false_scaleouts = data['kpa_observed']['scale-out'] - data['kpa_puretime']['scale-out']
    total_decisions = len(data['t_contention'])
    overprov_rate = max(0, false_scaleouts) / total_decisions * 100
    
    summary.append({
        'rps': rps,
        'noise_containers': noise,
        'avg_t_contention_ms': round(avg_t_cont, 2),
        'avg_t_puretime_ms': round(avg_t_pure, 2),
        'avg_concurrency_observed': round(avg_conc_obs, 2),
        'avg_concurrency_puretime': round(avg_conc_pure, 2),
        'kpa_decisions_observed': dict(data['kpa_observed']),
        'kpa_decisions_puretime': dict(data['kpa_puretime']),
        'false_scaleout_count': max(0, false_scaleouts),
        'over_provisioning_rate_pct': round(overprov_rate, 2),
    })

with open('$ANALYSIS_FILE', 'w') as f:
    json.dump(summary, f, indent=2)

print("\n" + "=" * 70)
print("KPA Simulation Analysis Summary")
print("=" * 70)
print(f"{'RPS':>5} {'Noise':>6} {'T_cont':>10} {'T_pure':>10} {'Conc_obs':>10} {'Conc_pure':>10} {'OverProv':>10}")
print("-" * 70)
for s in summary:
    print(f"{s['rps']:>5} {s['noise_containers']:>6} {s['avg_t_contention_ms']:>10.1f} {s['avg_t_puretime_ms']:>10.1f} "
          f"{s['avg_concurrency_observed']:>10.2f} {s['avg_concurrency_puretime']:>10.2f} {s['over_provisioning_rate_pct']:>9.1f}%")

# Overall over-provisioning prevention
total_false = sum(s['false_scaleout_count'] for s in summary)
total_decisions = sum(len(analysis[k]['t_contention']) for k in analysis)
overall_prevention = total_false / total_decisions * 100 if total_decisions > 0 else 0

print("-" * 70)
print(f"Total false scale-out prevented by PureTime: {total_false} decisions")
print(f"Overall over-provisioning prevention rate: {overall_prevention:.1f}%")
print("=" * 70)
EOF
}

# =============================================================================
# Main Execution
# =============================================================================

main() {
    check_prerequisites
    setup_output
    
    log_info "Starting KPA Autoscaling Simulation"
    log_info "===================================="
    log_info "RPS values: ${TARGET_RPS_VALUES[*]}"
    log_info "Noise levels: ${NOISE_CONTAINER_COUNTS[*]}"
    log_info "Target concurrency: $TARGET_CONCURRENCY"
    log_info ""
    
    for rps in "${TARGET_RPS_VALUES[@]}"; do
        for noise in "${NOISE_CONTAINER_COUNTS[@]}"; do
            run_kpa_scenario "$rps" "$noise"
        done
    done
    
    generate_analysis
    
    log_info ""
    log_info "===================================="
    log_info "Simulation completed!"
    log_info "Results saved to: $RESULTS_FILE"
    log_info "Analysis saved to: $ANALYSIS_FILE"
}

main "$@"
