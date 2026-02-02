#!/bin/bash
# =============================================================================
# PureTime Case Study: Canary Deployment False Alarm Detection
# =============================================================================
# 
# 목적: Canary 배포 시나리오에서 noisy neighbor로 인한 false positive alarm을
#       PureTime이 어떻게 방지하는지 시연
#
# 시나리오:
#   1. 기존 버전(v1)과 새 버전(v2)을 동시 배포 (실제로는 동일한 컨테이너)
#   2. v2에만 noisy neighbor 영향을 줌 (같은 CPU 코어에 배치)
#   3. 기존 모니터링: v2가 느리다고 판단 → False Alarm
#   4. PureTime: noise-free makespan으로 비교 → v1과 v2 성능 동일 확인
#
# Usage: sudo ./exp_canary.sh [output_dir]
# =============================================================================

set -e

# =============================================================================
# Configuration Variables (수정 가능)
# =============================================================================

# 각 버전별 실행 횟수
REQUESTS_PER_VERSION=30

# Noisy neighbor 컨테이너 수 (v2에만 적용)
NOISE_CONTAINERS=4

# Canary alerting threshold (v2가 v1보다 이 비율 이상 느리면 alarm)
ALERT_THRESHOLD_PERCENT=20

# PureTime 트레이싱 시간
TRACE_DURATION=180

# =============================================================================
# Path Configuration
# =============================================================================

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PURETIME_DIR="$(dirname "$SCRIPT_DIR")"
PURETIME_BIN="$PURETIME_DIR/src/puretime"
MAKESPAN_ANALYZER="$PURETIME_DIR/tests/noise_free_makespan.py"

OUTPUT_DIR="${1:-/tmp/puretime_canary_$(date +%Y%m%d_%H%M%S)}"
RESULTS_FILE="$OUTPUT_DIR/canary_results.csv"
ANALYSIS_FILE="$OUTPUT_DIR/canary_analysis.json"

# Docker image (v1과 v2는 실제로 동일 - 성능 차이 없음을 보여주기 위해)
WORKLOAD_IMAGE="graph-bfs"
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
    docker build -t "$WORKLOAD_IMAGE" "$PURETIME_DIR/funcs/$WORKLOAD_IMAGE" > /dev/null 2>&1
    
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
    echo "version,request_id,t_observed_ms,t_puretime_ms,cgroup_id" > "$RESULTS_FILE"
    log_info "Output directory: $OUTPUT_DIR"
}

get_latest_trace() {
    ls -t /var/log/puretime/trace_*.jsonl 2>/dev/null | head -1
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

# =============================================================================
# Noise Generator
# =============================================================================

declare -a NOISE_CONTAINER_IDS

start_noise_containers() {
    local count="$1"
    local cpu_core="$2"
    
    NOISE_CONTAINER_IDS=()
    
    if [ "$count" -eq 0 ]; then
        return
    fi
    
    log_info "Starting $count noise containers on CPU $cpu_core..."
    
    for i in $(seq 1 $count); do
        local cid=$(docker run -d --cpuset-cpus=$cpu_core alexeiled/stress-ng \
            --cpu 1 --cpu-load 80 --timeout 0 2>/dev/null || \
            docker run -d --cpuset-cpus=$cpu_core lorel/docker-stress-ng \
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
# Experiment Functions
# =============================================================================

run_version_request() {
    local version="$1"
    local request_id="$2"
    local cpu_core="$3"
    local trace_file="$4"
    local cgroup_file="$5"
    
    # Run container
    local cid=$(docker run -d --cpuset-cpus=$cpu_core "$WORKLOAD_IMAGE")
    
    # Get cgroup ID
    local pid=$(docker inspect --format '{{.State.Pid}}' "$cid")
    local cgroup_path=$(cat /proc/$pid/cgroup | grep -oP '0::/\K.*')
    local cgroup_id=$(stat -c %i "/sys/fs/cgroup/${cgroup_path}")
    
    # Save cgroup for PureTime analysis
    echo "$cgroup_id" >> "$cgroup_file"
    
    # Wait for completion
    docker wait "$cid" > /dev/null 2>&1 || true
    
    # Get observed execution time
    local t_observed=$(get_container_execution_time "$cid")
    
    # Get PureTime's noise-free makespan
    local single_cgroup_file="$OUTPUT_DIR/tmp_cgroup_${version}_${request_id}.txt"
    echo "$cgroup_id" > "$single_cgroup_file"
    
    local puretime_result=$(python3 "$MAKESPAN_ANALYZER" "$trace_file" -c "$single_cgroup_file" -j 2>/dev/null)
    local t_puretime=$(echo "$puretime_result" | grep -oP '"noise_free_makespan_ns"\s*:\s*\K[0-9]+' | head -1)
    t_puretime=$(echo "scale=2; ${t_puretime:-0} / 1000000" | bc)
    
    # Cleanup
    docker rm -f "$cid" > /dev/null 2>&1 || true
    rm -f "$single_cgroup_file"
    
    # Save results
    echo "$version,$request_id,$t_observed,$t_puretime,$cgroup_id" >> "$RESULTS_FILE"
    
    echo "$t_observed,$t_puretime"
}

# =============================================================================
# Analysis Functions
# =============================================================================

analyze_results() {
    log_info "Analyzing canary deployment results..."
    
    python3 << 'EOF'
import csv
import json
from collections import defaultdict
import statistics

# Load results
v1_data = {'observed': [], 'puretime': []}
v2_data = {'observed': [], 'puretime': []}

with open('RESULTS_FILE', 'r') as f:
    reader = csv.DictReader(f)
    for row in reader:
        version = row['version']
        observed = float(row['t_observed_ms'])
        puretime = float(row['t_puretime_ms'])
        
        if version == 'v1':
            v1_data['observed'].append(observed)
            v1_data['puretime'].append(puretime)
        else:
            v2_data['observed'].append(observed)
            v2_data['puretime'].append(puretime)

# Calculate statistics
v1_obs_avg = statistics.mean(v1_data['observed'])
v1_pure_avg = statistics.mean(v1_data['puretime'])
v2_obs_avg = statistics.mean(v2_data['observed'])
v2_pure_avg = statistics.mean(v2_data['puretime'])

# Calculate performance differences
diff_observed = ((v2_obs_avg - v1_obs_avg) / v1_obs_avg) * 100
diff_puretime = ((v2_pure_avg - v1_pure_avg) / v1_pure_avg) * 100

# Determine alerts
threshold = ALERT_THRESHOLD
alert_traditional = diff_observed > threshold
alert_puretime = diff_puretime > threshold

# Print results
print("\n" + "=" * 70)
print("Canary Deployment Analysis")
print("=" * 70)

print("\n[Version Comparison - Traditional Monitoring]")
print("-" * 70)
print(f"v1 Average Latency: {v1_obs_avg:.2f} ms")
print(f"v2 Average Latency: {v2_obs_avg:.2f} ms")
print(f"Difference: {diff_observed:+.2f}%")
print(f"Alert Threshold: {threshold}%")
print(f"ALERT STATUS: {'🚨 FALSE ALARM - Rollback triggered!' if alert_traditional else '✅ No alarm'}")

print("\n[Version Comparison - PureTime Monitoring]")
print("-" * 70)
print(f"v1 Noise-Free Latency: {v1_pure_avg:.2f} ms")
print(f"v2 Noise-Free Latency: {v2_pure_avg:.2f} ms")
print(f"Difference: {diff_puretime:+.2f}%")
print(f"Alert Threshold: {threshold}%")
print(f"ALERT STATUS: {'🚨 True alarm' if alert_puretime else '✅ No alarm - Correctly identified as same performance'}")

print("\n[Summary]")
print("-" * 70)
if alert_traditional and not alert_puretime:
    print("🎯 PureTime successfully prevented a FALSE ALARM!")
    print(f"   Traditional monitoring would have triggered an unnecessary rollback.")
    print(f"   The {diff_observed:.1f}% perceived slowdown was entirely due to noisy neighbors.")
else:
    print("Analysis complete.")

print("=" * 70)

# Save analysis to JSON
analysis = {
    'v1': {
        'observed_avg_ms': round(v1_obs_avg, 2),
        'observed_std_ms': round(statistics.stdev(v1_data['observed']) if len(v1_data['observed']) > 1 else 0, 2),
        'puretime_avg_ms': round(v1_pure_avg, 2),
        'puretime_std_ms': round(statistics.stdev(v1_data['puretime']) if len(v1_data['puretime']) > 1 else 0, 2),
    },
    'v2': {
        'observed_avg_ms': round(v2_obs_avg, 2),
        'observed_std_ms': round(statistics.stdev(v2_data['observed']) if len(v2_data['observed']) > 1 else 0, 2),
        'puretime_avg_ms': round(v2_pure_avg, 2),
        'puretime_std_ms': round(statistics.stdev(v2_data['puretime']) if len(v2_data['puretime']) > 1 else 0, 2),
    },
    'comparison': {
        'traditional': {
            'difference_percent': round(diff_observed, 2),
            'alert_triggered': alert_traditional,
        },
        'puretime': {
            'difference_percent': round(diff_puretime, 2),
            'alert_triggered': alert_puretime,
        },
        'threshold_percent': threshold,
        'false_alarm_prevented': alert_traditional and not alert_puretime,
    }
}

with open('ANALYSIS_FILE', 'w') as f:
    json.dump(analysis, f, indent=2)

print(f"\nAnalysis saved to: ANALYSIS_FILE")
EOF
    
    # Replace placeholders in the Python script
    sed -i "s|RESULTS_FILE|$RESULTS_FILE|g" /dev/stdin 2>/dev/null || true
    sed -i "s|ANALYSIS_FILE|$ANALYSIS_FILE|g" /dev/stdin 2>/dev/null || true
    sed -i "s|ALERT_THRESHOLD|$ALERT_THRESHOLD_PERCENT|g" /dev/stdin 2>/dev/null || true
}

run_analysis_script() {
    python3 << EOF
import csv
import json
from collections import defaultdict
import statistics

# Load results
v1_data = {'observed': [], 'puretime': []}
v2_data = {'observed': [], 'puretime': []}

with open('$RESULTS_FILE', 'r') as f:
    reader = csv.DictReader(f)
    for row in reader:
        version = row['version']
        observed = float(row['t_observed_ms'])
        puretime = float(row['t_puretime_ms'])
        
        if version == 'v1':
            v1_data['observed'].append(observed)
            v1_data['puretime'].append(puretime)
        else:
            v2_data['observed'].append(observed)
            v2_data['puretime'].append(puretime)

# Calculate statistics
v1_obs_avg = statistics.mean(v1_data['observed'])
v1_pure_avg = statistics.mean(v1_data['puretime'])
v2_obs_avg = statistics.mean(v2_data['observed'])
v2_pure_avg = statistics.mean(v2_data['puretime'])

# Calculate performance differences
diff_observed = ((v2_obs_avg - v1_obs_avg) / v1_obs_avg) * 100
diff_puretime = ((v2_pure_avg - v1_pure_avg) / v1_pure_avg) * 100

# Determine alerts
threshold = $ALERT_THRESHOLD_PERCENT
alert_traditional = diff_observed > threshold
alert_puretime = diff_puretime > threshold

# Print results
print("\n" + "=" * 70)
print("Canary Deployment Analysis")
print("=" * 70)

print("\n[Version Comparison - Traditional Monitoring]")
print("-" * 70)
print(f"v1 Average Latency: {v1_obs_avg:.2f} ms")
print(f"v2 Average Latency: {v2_obs_avg:.2f} ms")
print(f"Difference: {diff_observed:+.2f}%")
print(f"Alert Threshold: {threshold}%")
if alert_traditional:
    print("ALERT STATUS: FALSE ALARM - Rollback triggered!")
else:
    print("ALERT STATUS: No alarm")

print("\n[Version Comparison - PureTime Monitoring]")
print("-" * 70)
print(f"v1 Noise-Free Latency: {v1_pure_avg:.2f} ms")
print(f"v2 Noise-Free Latency: {v2_pure_avg:.2f} ms")
print(f"Difference: {diff_puretime:+.2f}%")
print(f"Alert Threshold: {threshold}%")
if alert_puretime:
    print("ALERT STATUS: True alarm")
else:
    print("ALERT STATUS: No alarm - Correctly identified as same performance")

print("\n[Summary]")
print("-" * 70)
if alert_traditional and not alert_puretime:
    print("PureTime successfully prevented a FALSE ALARM!")
    print(f"Traditional monitoring would have triggered an unnecessary rollback.")
    print(f"The {diff_observed:.1f}% perceived slowdown was entirely due to noisy neighbors.")
else:
    print("Analysis complete.")

print("=" * 70)

# Save analysis to JSON
analysis = {
    'v1': {
        'observed_avg_ms': round(v1_obs_avg, 2),
        'observed_std_ms': round(statistics.stdev(v1_data['observed']) if len(v1_data['observed']) > 1 else 0, 2),
        'puretime_avg_ms': round(v1_pure_avg, 2),
        'puretime_std_ms': round(statistics.stdev(v1_data['puretime']) if len(v1_data['puretime']) > 1 else 0, 2),
    },
    'v2': {
        'observed_avg_ms': round(v2_obs_avg, 2),
        'observed_std_ms': round(statistics.stdev(v2_data['observed']) if len(v2_data['observed']) > 1 else 0, 2),
        'puretime_avg_ms': round(v2_pure_avg, 2),
        'puretime_std_ms': round(statistics.stdev(v2_data['puretime']) if len(v2_data['puretime']) > 1 else 0, 2),
    },
    'comparison': {
        'traditional': {
            'difference_percent': round(diff_observed, 2),
            'alert_triggered': alert_traditional,
        },
        'puretime': {
            'difference_percent': round(diff_puretime, 2),
            'alert_triggered': alert_puretime,
        },
        'threshold_percent': threshold,
        'false_alarm_prevented': alert_traditional and not alert_puretime,
    }
}

with open('$ANALYSIS_FILE', 'w') as f:
    json.dump(analysis, f, indent=2)

print(f"\nAnalysis saved to: $ANALYSIS_FILE")
EOF
}

# =============================================================================
# Main Execution
# =============================================================================

main() {
    check_prerequisites
    setup_output
    
    log_info "Starting Canary Deployment False Alarm Experiment"
    log_info "================================================="
    log_info "Scenario: v1 (no noise) vs v2 (with noisy neighbors)"
    log_info "Both versions are identical code - only placement differs"
    log_info ""
    
    # Start PureTime
    log_info "Starting PureTime..."
    $PURETIME_BIN -t $TRACE_DURATION &
    local puretime_pid=$!
    sleep 2
    
    local trace_file=$(get_latest_trace)
    local v1_cgroup_file="$OUTPUT_DIR/cgroups_v1.txt"
    local v2_cgroup_file="$OUTPUT_DIR/cgroups_v2.txt"
    > "$v1_cgroup_file"
    > "$v2_cgroup_file"
    
    # Phase 1: Run v1 (baseline, no noise, CPU 1)
    log_info ""
    log_info "=== Phase 1: v1 (Stable version, CPU core 1, no noise) ==="
    for req_id in $(seq 1 $REQUESTS_PER_VERSION); do
        local result=$(run_version_request "v1" "$req_id" "1" "$trace_file" "$v1_cgroup_file")
        local t_obs=$(echo "$result" | cut -d',' -f1)
        local t_pure=$(echo "$result" | cut -d',' -f2)
        log_info "  Request $req_id: observed=${t_obs}ms, puretime=${t_pure}ms"
    done
    
    # Phase 2: Run v2 (canary, with noise, CPU 0)
    log_info ""
    log_info "=== Phase 2: v2 (Canary version, CPU core 0, with $NOISE_CONTAINERS noisy neighbors) ==="
    
    # Start noisy neighbors on same CPU as v2
    start_noise_containers "$NOISE_CONTAINERS" "0"
    sleep 2
    
    for req_id in $(seq 1 $REQUESTS_PER_VERSION); do
        local result=$(run_version_request "v2" "$req_id" "0" "$trace_file" "$v2_cgroup_file")
        local t_obs=$(echo "$result" | cut -d',' -f1)
        local t_pure=$(echo "$result" | cut -d',' -f2)
        log_info "  Request $req_id: observed=${t_obs}ms, puretime=${t_pure}ms"
    done
    
    # Cleanup
    stop_noise_containers
    
    # Stop PureTime
    kill $puretime_pid 2>/dev/null || true
    wait $puretime_pid 2>/dev/null || true
    
    # Analyze results
    run_analysis_script
    
    log_info ""
    log_info "================================================="
    log_info "Canary experiment completed!"
    log_info "Results saved to: $OUTPUT_DIR"
}

main "$@"
