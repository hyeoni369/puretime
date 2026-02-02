#!/bin/bash
# =============================================================================
# PureTime Experiment: System Overhead Measurement
# =============================================================================
# 
# 목적: PureTime eBPF 프로그램이 시스템에 미치는 오버헤드 측정
#
# 측정 항목:
#   1. 실행 시간 지연: PureTime on/off 상태에서 동일 워크로드 실행 시간 비교
#   2. 자원 소비량: CPU 사용률, 메모리 사용량
#
# Usage: sudo ./exp_overhead.sh [output_dir]
# =============================================================================

set -e

# =============================================================================
# Configuration Variables (수정 가능)
# =============================================================================

# 측정 반복 횟수
ITERATIONS=20

# 테스트 워크로드 목록
WORKLOADS=("graph-bfs" "network-uploader" "compression")

# PureTime 트레이싱 시간
TRACE_DURATION=60

# 자원 모니터링 간격 (초)
MONITOR_INTERVAL=1

# =============================================================================
# Path Configuration
# =============================================================================

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PURETIME_DIR="$(dirname "$SCRIPT_DIR")"
PURETIME_BIN="$PURETIME_DIR/src/puretime"

OUTPUT_DIR="${1:-/tmp/puretime_overhead_$(date +%Y%m%d_%H%M%S)}"
LATENCY_FILE="$OUTPUT_DIR/latency_overhead.csv"
RESOURCE_FILE="$OUTPUT_DIR/resource_overhead.csv"

# Network/Block I/O 설정
TESTFILE_PATH="/data/tmp.bin"
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
    
    # Build Docker images
    log_info "Building Docker images..."
    for workload in "${WORKLOADS[@]}"; do
        docker build -t "$workload" "$PURETIME_DIR/funcs/$workload" > /dev/null 2>&1
    done
    
    log_pass "Prerequisites OK"
}

setup_output() {
    mkdir -p "$OUTPUT_DIR"
    echo "workload,puretime_enabled,iteration,execution_time_ms" > "$LATENCY_FILE"
    echo "timestamp,puretime_enabled,cpu_percent,memory_mb" > "$RESOURCE_FILE"
    log_info "Output directory: $OUTPUT_DIR"
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

get_docker_opts() {
    local workload="$1"
    
    case "$workload" in
        "graph-bfs")
            echo "--cpuset-cpus=0"
            ;;
        "network-uploader")
            echo "--network=host -v $TESTFILE_PATH:$TESTFILE_PATH:ro"
            ;;
        "compression")
            echo "-v $HDD_MOUNT:/tmp"
            ;;
        *)
            echo ""
            ;;
    esac
}

# =============================================================================
# Resource Monitoring
# =============================================================================

MONITOR_PID=""

start_resource_monitor() {
    local puretime_enabled="$1"
    
    (
        while true; do
            local timestamp=$(date +%s.%N)
            
            # CPU 사용률 (system-wide)
            local cpu=$(top -bn1 | grep "Cpu(s)" | awk '{print $2}' | cut -d'%' -f1)
            
            # PureTime 프로세스 메모리 (있는 경우)
            local mem=0
            if [ "$puretime_enabled" = "true" ]; then
                local pt_pid=$(pgrep -f "puretime" | head -1)
                if [ -n "$pt_pid" ]; then
                    mem=$(ps -o rss= -p $pt_pid 2>/dev/null | awk '{print $1/1024}')
                fi
            fi
            
            echo "$timestamp,$puretime_enabled,$cpu,$mem" >> "$RESOURCE_FILE"
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
# Experiment Functions
# =============================================================================

run_workload_without_puretime() {
    local workload="$1"
    local iteration="$2"
    
    local opts=$(get_docker_opts "$workload")
    local cid=$(docker run -d $opts "$workload")
    docker wait "$cid" > /dev/null 2>&1 || true
    
    local exec_time=$(get_container_execution_time "$cid")
    docker rm -f "$cid" > /dev/null 2>&1 || true
    
    echo "$workload,false,$iteration,$exec_time" >> "$LATENCY_FILE"
    echo "$exec_time"
}

run_workload_with_puretime() {
    local workload="$1"
    local iteration="$2"
    
    # Start PureTime
    $PURETIME_BIN -t $TRACE_DURATION &
    local puretime_pid=$!
    sleep 2
    
    local opts=$(get_docker_opts "$workload")
    local cid=$(docker run -d $opts "$workload")
    docker wait "$cid" > /dev/null 2>&1 || true
    
    local exec_time=$(get_container_execution_time "$cid")
    docker rm -f "$cid" > /dev/null 2>&1 || true
    
    # Stop PureTime
    kill $puretime_pid 2>/dev/null || true
    wait $puretime_pid 2>/dev/null || true
    
    echo "$workload,true,$iteration,$exec_time" >> "$LATENCY_FILE"
    echo "$exec_time"
}

# =============================================================================
# Analysis Functions
# =============================================================================

analyze_results() {
    log_info "Analyzing results..."
    
    python3 << EOF
import csv
from collections import defaultdict
import statistics

# Load latency data
latencies = defaultdict(lambda: {'with': [], 'without': []})
with open('$LATENCY_FILE', 'r') as f:
    reader = csv.DictReader(f)
    for row in reader:
        workload = row['workload']
        enabled = row['puretime_enabled'] == 'true'
        time_ms = float(row['execution_time_ms'])
        
        if enabled:
            latencies[workload]['with'].append(time_ms)
        else:
            latencies[workload]['without'].append(time_ms)

# Load resource data
resources = {'with': [], 'without': []}
with open('$RESOURCE_FILE', 'r') as f:
    reader = csv.DictReader(f)
    for row in reader:
        enabled = row['puretime_enabled'] == 'true'
        cpu = float(row['cpu_percent']) if row['cpu_percent'] else 0
        mem = float(row['memory_mb']) if row['memory_mb'] else 0
        
        if enabled:
            resources['with'].append({'cpu': cpu, 'mem': mem})
        else:
            resources['without'].append({'cpu': cpu, 'mem': mem})

# Print summary
print("\n" + "=" * 70)
print("PureTime Overhead Analysis")
print("=" * 70)

print("\n[Latency Overhead]")
print("-" * 70)
print(f"{'Workload':<20} {'Without (ms)':<15} {'With (ms)':<15} {'Overhead':<15}")
print("-" * 70)

total_without = []
total_with = []

for workload in sorted(latencies.keys()):
    data = latencies[workload]
    avg_without = statistics.mean(data['without']) if data['without'] else 0
    avg_with = statistics.mean(data['with']) if data['with'] else 0
    overhead_pct = ((avg_with - avg_without) / avg_without * 100) if avg_without > 0 else 0
    
    total_without.extend(data['without'])
    total_with.extend(data['with'])
    
    print(f"{workload:<20} {avg_without:<15.2f} {avg_with:<15.2f} {overhead_pct:>+.2f}%")

# Overall average
overall_without = statistics.mean(total_without) if total_without else 0
overall_with = statistics.mean(total_with) if total_with else 0
overall_overhead = ((overall_with - overall_without) / overall_without * 100) if overall_without > 0 else 0

print("-" * 70)
print(f"{'Overall':<20} {overall_without:<15.2f} {overall_with:<15.2f} {overall_overhead:>+.2f}%")

print("\n[Resource Overhead]")
print("-" * 70)

if resources['with']:
    avg_cpu_with = statistics.mean([r['cpu'] for r in resources['with']])
    avg_mem_with = statistics.mean([r['mem'] for r in resources['with'] if r['mem'] > 0])
    print(f"PureTime CPU Usage: {avg_cpu_with:.2f}%")
    print(f"PureTime Memory Usage: {avg_mem_with:.2f} MB")
else:
    print("No resource data with PureTime enabled")

print("=" * 70)

# Save summary to JSON
import json
summary = {
    'latency_overhead': {
        'by_workload': {},
        'overall_percent': round(overall_overhead, 2)
    },
    'resource_overhead': {}
}

for workload in latencies.keys():
    data = latencies[workload]
    avg_without = statistics.mean(data['without']) if data['without'] else 0
    avg_with = statistics.mean(data['with']) if data['with'] else 0
    overhead_pct = ((avg_with - avg_without) / avg_without * 100) if avg_without > 0 else 0
    
    summary['latency_overhead']['by_workload'][workload] = {
        'without_ms': round(avg_without, 2),
        'with_ms': round(avg_with, 2),
        'overhead_percent': round(overhead_pct, 2)
    }

if resources['with']:
    summary['resource_overhead'] = {
        'cpu_percent': round(avg_cpu_with, 2),
        'memory_mb': round(avg_mem_with, 2)
    }

with open('$OUTPUT_DIR/summary.json', 'w') as f:
    json.dump(summary, f, indent=2)

print(f"\nSummary saved to: $OUTPUT_DIR/summary.json")
EOF
}

# =============================================================================
# Main Execution
# =============================================================================

main() {
    check_prerequisites
    setup_output
    
    log_info "Starting Overhead Measurement Experiments"
    log_info "=========================================="
    log_info "Workloads: ${WORKLOADS[*]}"
    log_info "Iterations: $ITERATIONS"
    log_info ""
    
    # Phase 1: Run without PureTime
    log_info "=== Phase 1: Without PureTime ==="
    start_resource_monitor "false"
    
    for workload in "${WORKLOADS[@]}"; do
        log_info "Testing $workload..."
        for iter in $(seq 1 $ITERATIONS); do
            local time=$(run_workload_without_puretime "$workload" "$iter")
            log_info "  Iteration $iter: ${time}ms"
        done
    done
    
    stop_resource_monitor
    sleep 5  # Cool down
    
    # Phase 2: Run with PureTime
    log_info ""
    log_info "=== Phase 2: With PureTime ==="
    start_resource_monitor "true"
    
    for workload in "${WORKLOADS[@]}"; do
        log_info "Testing $workload..."
        for iter in $(seq 1 $ITERATIONS); do
            local time=$(run_workload_with_puretime "$workload" "$iter")
            log_info "  Iteration $iter: ${time}ms"
        done
    done
    
    stop_resource_monitor
    
    # Analyze results
    analyze_results
    
    log_info ""
    log_info "=========================================="
    log_info "Overhead measurement completed!"
    log_info "Results saved to: $OUTPUT_DIR"
}

main "$@"
