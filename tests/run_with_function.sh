#!/bin/bash
# PureTime eBPF Tracer Test Script
# Tests run queue, qdisc, and I/O scheduler latency capture
#
# Usage: sudo ./run_tests.sh [output_dir]

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PURETIME_DIR="$(dirname "$SCRIPT_DIR")"
PURETIME_BIN="$PURETIME_DIR/src/puretime"
ANALYZER="$SCRIPT_DIR/analyze_trace.py"
MAKESPAN="$SCRIPT_DIR/noise_free_makespan.py"

OUTPUT_DIR="${1:-/tmp/puretime_test_$(date +%Y%m%d_%H%M%S)}"
TEST_DURATION=30
RESULTS_FILE="$OUTPUT_DIR/test_results.txt"

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
CYAN='\033[0;36m'
NC='\033[0m'

log_info() {
    echo -e "${CYAN}[INFO]${NC} $1"
}

log_pass() {
    echo -e "${GREEN}[PASS]${NC} $1"
}

log_fail() {
    echo -e "${RED}[FAIL]${NC} $1"
}

log_warn() {
    echo -e "${YELLOW}[WARN]${NC} $1"
}

# Check prerequisites
check_prerequisites() {
    log_info "Checking prerequisites..."

    # Check root
    if [ "$EUID" -ne 0 ]; then
        log_fail "Must run as root"
        exit 1
    fi

    # Check puretime binary
    if [ ! -x "$PURETIME_BIN" ]; then
        log_fail "PureTime binary not found at $PURETIME_BIN"
        log_info "Please build it first: cd $PURETIME_DIR/src && make"
        exit 1
    fi

    # Check analyzer script
    if [ ! -f "$ANALYZER" ]; then
        log_fail "Analyzer script not found at $ANALYZER"
        exit 1
    fi

    # Check required tools
    local missing_tools=""
    for tool in docker; do
        if ! command -v $tool &> /dev/null; then
            missing_tools="$missing_tools $tool"
        fi
    done

    if [ -n "$missing_tools" ]; then
        log_warn "Missing tools:$missing_tools"
        log_warn "Some tests may be limited"
    fi

    # Build stress test Docker image
    build_stress_image

    log_pass "Prerequisites OK"
}

# Create output directory
setup_output() {
    mkdir -p "$OUTPUT_DIR"
    echo "PureTime Test Results" > "$RESULTS_FILE"
    echo "=====================" >> "$RESULTS_FILE"
    echo "Date: $(date)" >> "$RESULTS_FILE"
    echo "Output Directory: $OUTPUT_DIR" >> "$RESULTS_FILE"
    echo "" >> "$RESULTS_FILE"
    log_info "Output directory: $OUTPUT_DIR"
}

# Get latest trace file
get_latest_trace() {
    ls -t /var/log/puretime/trace_*.jsonl 2>/dev/null | head -1
}

# Docker stress test variables
GRAPH_BFS_IMAGE="graph-bfs"
NETWORK_UPLOADER_IMAGE="network-uploader"
COMPRESSION_IMAGE="compression"
CONTAINER_IDS=()
CONTAINER_CGROUP_IDS=()  # numeric cgroup_id (inode)

# Build Docker images
build_stress_image() {
    log_info "Building graph-bfs Docker image..."
    docker build -t "$GRAPH_BFS_IMAGE" "$PURETIME_DIR/funcs/graph-bfs" > /dev/null 2>&1
    log_pass "Docker image built: $GRAPH_BFS_IMAGE"

    log_info "Building network-uploader Docker image..."
    docker build -t "$NETWORK_UPLOADER_IMAGE" "$PURETIME_DIR/funcs/network-uploader" > /dev/null 2>&1
    log_pass "Docker image built: $NETWORK_UPLOADER_IMAGE"

    log_info "Building compression Docker image..."
    docker build -t "$COMPRESSION_IMAGE" "$PURETIME_DIR/funcs/compression" > /dev/null 2>&1
    log_pass "Docker image built: $COMPRESSION_IMAGE"
}

# Disable NIC offloads on physical interface for accurate qdisc measurement
disable_offloads() {
    local iface="$1"
    log_info "Disabling TSO/GSO/GRO on $iface..."
    ethtool -K "$iface" tso off gso off gro off 2>/dev/null || log_warn "Failed to disable offloads on $iface"
}

restore_offloads() {
    local iface="$1"
    log_info "Restoring TSO/GSO/GRO on $iface..."
    ethtool -K "$iface" tso on gso on gro on 2>/dev/null || true
}

# Start stress containers and collect cgroup IDs
start_cpu_stress_containers() {
    local count=20
    log_info "Starting $count graph-bfs containers..."

    CONTAINER_IDS=()
    CONTAINER_CGROUP_IDS=()

    for i in $(seq 1 $count); do
        local cid=$(docker run -d --cpuset-cpus=0 "$GRAPH_BFS_IMAGE")
        CONTAINER_IDS+=("$cid")

        # Extract cgroup v2 path and get inode (numeric cgroup_id)
        local pid=$(docker inspect --format '{{.State.Pid}}' "$cid")
        local cgroup_path=$(cat /proc/$pid/cgroup | grep -oP '0::/\K.*')
        local cgroup_id=$(stat -c %i "/sys/fs/cgroup/${cgroup_path}")
        CONTAINER_CGROUP_IDS+=("$cgroup_id")

        log_info "  Container $i: ${cid:0:12} -> cgroup_id: $cgroup_id"
    done
}

# Stop and remove stress containers
stop_cpu_stress_containers() {
    log_info "Stopping and removing stress containers..."
    for cid in "${CONTAINER_IDS[@]}"; do
        docker rm -f "$cid" > /dev/null 2>&1 || true
    done
    CONTAINER_IDS=()
    CONTAINER_CGROUP_IDS=()
}

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

# Start network containers and collect cgroup IDs
start_network_containers() {
    local count=8
    log_info "Starting $count network-uploader containers..."

    # Ensure test file exists
    create_testfile_by_downloading

    CONTAINER_IDS=()
    CONTAINER_CGROUP_IDS=()

    for i in $(seq 1 $count); do
        local cid=$(docker run --network=host -d \
            -v "$TESTFILE_PATH:$TESTFILE_PATH:ro" \
            "$NETWORK_UPLOADER_IMAGE")
        CONTAINER_IDS+=("$cid")

        local pid=$(docker inspect --format '{{.State.Pid}}' "$cid")
        local cgroup_path=$(cat /proc/$pid/cgroup | grep -oP '0::/\K.*')
        local cgroup_id=$(stat -c %i "/sys/fs/cgroup/${cgroup_path}")
        CONTAINER_CGROUP_IDS+=("$cgroup_id")

        log_info "  Container $i: ${cid:0:12} -> cgroup_id: $cgroup_id"
    done
}

# Stop and remove network containers
stop_network_containers() {
    log_info "Stopping and removing network containers..."
    for cid in "${CONTAINER_IDS[@]}"; do
        docker rm -f "$cid" > /dev/null 2>&1 || true
    done
    CONTAINER_IDS=()
    CONTAINER_CGROUP_IDS=()
}

# Start block I/O containers and collect cgroup IDs
start_block_io_containers() {
    local count=8
    log_info "Starting $count compression containers..."

    CONTAINER_IDS=()
    CONTAINER_CGROUP_IDS=()

    for i in $(seq 1 $count); do
        local cid=$(docker run -d "$COMPRESSION_IMAGE")
        CONTAINER_IDS+=("$cid")

        local pid=$(docker inspect --format '{{.State.Pid}}' "$cid")
        local cgroup_path=$(cat /proc/$pid/cgroup | grep -oP '0::/\K.*')
        local cgroup_id=$(stat -c %i "/sys/fs/cgroup/${cgroup_path}")
        CONTAINER_CGROUP_IDS+=("$cgroup_id")

        log_info "  Container $i: ${cid:0:12} -> cgroup_id: $cgroup_id"
    done
}

# Stop and remove block I/O containers
stop_block_io_containers() {
    log_info "Stopping and removing compression containers..."
    for cid in "${CONTAINER_IDS[@]}"; do
        docker rm -f "$cid" > /dev/null 2>&1 || true
    done
    CONTAINER_IDS=()
    CONTAINER_CGROUP_IDS=()
}

# Test 1: Run Queue Latency
test_runq_latency() {
    echo ""
    log_info "=== Test 1: Run Queue Latency ==="
    echo "" >> "$RESULTS_FILE"
    echo "Test 1: Run Queue Latency" >> "$RESULTS_FILE"
    echo "--------------------------" >> "$RESULTS_FILE"

    local trace_file="$OUTPUT_DIR/trace_runq.jsonl"

    # Start puretime
    log_info "Starting PureTime tracer..."
    $PURETIME_BIN -v -t $TEST_DURATION &
    local puretime_pid=$!
    sleep 2

    # Get trace file
    local actual_trace=$(get_latest_trace)
    log_info "Trace file: $actual_trace"

    # Generate CPU contention with graph-bfs containers
    log_info "Generating CPU contention with graph-bfs containers..."
    start_cpu_stress_containers

    # Save container cgroup IDs for later analysis
    for i in "${!CONTAINER_IDS[@]}"; do
        echo "${CONTAINER_CGROUP_IDS[$i]}" >> "$OUTPUT_DIR/container_cgroups_cpu.txt"
    done
    log_info "Container cgroup_ids saved to $OUTPUT_DIR/container_cgroups_cpu.txt"

    # Wait for puretime to finish
    wait $puretime_pid 2>/dev/null || true

    # Stop and remove stress containers
    stop_cpu_stress_containers

    # Copy trace file
    if [ -f "$actual_trace" ]; then
        cp "$actual_trace" "$trace_file"
    else
        log_fail "No trace file generated"
        echo "Result: FAIL - No trace file" >> "$RESULTS_FILE"
        return 1
    fi

    # Analyze results
    log_info "Analyzing run queue latency..."
    local enqueue_count=$(grep -c '"event":"sched_enqueue"' "$trace_file" 2>/dev/null || echo 0)
    local switch_count=$(grep -c '"event":"sched_switch"' "$trace_file" 2>/dev/null || echo 0)

    echo "  sched_enqueue events: $enqueue_count" | tee -a "$RESULTS_FILE"
    echo "  sched_switch events: $switch_count" | tee -a "$RESULTS_FILE"

    if [ "$enqueue_count" -gt 100 ] && [ "$switch_count" -gt 100 ]; then
        log_pass "Run queue events captured successfully"
        echo "Result: PASS" >> "$RESULTS_FILE"
        return 0
    else
        log_fail "Insufficient run queue events"
        echo "Result: FAIL - Insufficient events" >> "$RESULTS_FILE"
        return 1
    fi
}

# Test 2: Qdisc Latency (Network)
test_qdisc_latency() {
    echo ""
    log_info "=== Test 2: Qdisc Latency ==="
    echo "" >> "$RESULTS_FILE"
    echo "Test 2: Qdisc Latency" >> "$RESULTS_FILE"
    echo "---------------------" >> "$RESULTS_FILE"

    local trace_file="$OUTPUT_DIR/trace_qdisc.jsonl"

    # Detect network interface for MinIO traffic
    local iface=$(ip route get 165.194.27.225 2>/dev/null | awk '{print $5; exit}')
    if [ -z "$iface" ]; then
        iface=$(ip route get 8.8.8.8 2>/dev/null | awk '{print $5; exit}')
    fi
    log_info "Using network interface: $iface"

    # Disable offloads to see individual packets in qdisc
    disable_offloads "$iface"

    # Add bandwidth limit to cause Qdisc contention
    local tc_added=false
    if command -v tc &> /dev/null && [ -n "$iface" ]; then
        log_info "Adding bandwidth limit (10mbit) to cause Qdisc contention..."

        # 기존 qdisc 제거
        sudo tc qdisc del dev "$iface" root 2>/dev/null

        # htb를 root qdisc로 설정 (대역폭 제한용)
        sudo tc qdisc add dev "$iface" root handle 1: htb default 10

        # 10Mbps 클래스 생성
        sudo tc class add dev "$iface" parent 1: classid 1:10 htb rate 10mbit burst 15k

        # fq_codel을 leaf qdisc로 설정 (fair queueing용)
        sudo tc qdisc add dev "$iface" parent 1:10 handle 10: fq_codel
    fi

    # Start puretime
    log_info "Starting PureTime tracer..."
    $PURETIME_BIN -v -t $TEST_DURATION &
    local puretime_pid=$!
    sleep 2

    local actual_trace=$(get_latest_trace)
    log_info "Trace file: $actual_trace"

    # Generate network traffic with network-uploader containers
    log_info "Generating network traffic with network-uploader containers..."
    start_network_containers

    # Save container cgroup IDs
    > "$OUTPUT_DIR/container_cgroups_network.txt"
    for i in "${!CONTAINER_IDS[@]}"; do
        echo "${CONTAINER_CGROUP_IDS[$i]}" >> "$OUTPUT_DIR/container_cgroups_network.txt"
    done
    log_info "Container cgroup_ids saved to $OUTPUT_DIR/container_cgroups_network.txt"

    # Wait for puretime to finish
    wait $puretime_pid 2>/dev/null || true

    # Stop containers
    stop_network_containers

    # Remove bandwidth limit and restore offloads
    if [ "$tc_added" = true ]; then
        log_info "Removing bandwidth limit..."
        tc qdisc del dev "$iface" root 2>/dev/null || true
    fi
    restore_offloads "$iface"

    # Copy trace file
    if [ -f "$actual_trace" ]; then
        cp "$actual_trace" "$trace_file"
    else
        log_fail "No trace file generated"
        echo "Result: FAIL - No trace file" >> "$RESULTS_FILE"
        return 1
    fi

    # Analyze network events
    log_info "Analyzing qdisc latency..."
    local queue_count=$(grep -c '"event":"net_dev_queue"' "$trace_file" 2>/dev/null || echo 0)
    local start_xmit_count=$(grep -c '"event":"net_dev_start_xmit"' "$trace_file" 2>/dev/null || echo 0)
    local xmit_count=$(grep -c '"event":"net_dev_xmit"' "$trace_file" 2>/dev/null || echo 0)

    echo "  net_dev_queue events: $queue_count" | tee -a "$RESULTS_FILE"
    echo "  net_dev_start_xmit events: $start_xmit_count" | tee -a "$RESULTS_FILE"
    echo "  net_dev_xmit events: $xmit_count" | tee -a "$RESULTS_FILE"

    if [ "$queue_count" -gt 100 ] && [ "$xmit_count" -gt 100 ]; then
        log_pass "Qdisc events captured successfully"
        echo "Result: PASS" >> "$RESULTS_FILE"
        return 0
    else
        log_warn "Limited qdisc events (may need more traffic)"
        echo "Result: WARNING - Limited events" >> "$RESULTS_FILE"
        return 1
    fi
}

# Test 3: Block I/O Latency (with containers)
test_block_io_latency() {
    echo ""
    log_info "=== Test 3: Block I/O Latency ==="
    echo "" >> "$RESULTS_FILE"
    echo "Test 3: Block I/O Latency" >> "$RESULTS_FILE"
    echo "--------------------------" >> "$RESULTS_FILE"

    local trace_file="$OUTPUT_DIR/trace_block.jsonl"

    # Start puretime
    log_info "Starting PureTime tracer..."
    $PURETIME_BIN -v -t $TEST_DURATION &
    local puretime_pid=$!
    sleep 2

    local actual_trace=$(get_latest_trace)
    log_info "Trace file: $actual_trace"

    # Generate I/O contention with compression containers
    log_info "Generating I/O contention with compression containers..."
    start_block_io_containers

    # Save container cgroup IDs
    > "$OUTPUT_DIR/container_cgroups_block.txt"
    for i in "${!CONTAINER_IDS[@]}"; do
        echo "${CONTAINER_CGROUP_IDS[$i]}" >> "$OUTPUT_DIR/container_cgroups_block.txt"
    done
    log_info "Container cgroup_ids saved to $OUTPUT_DIR/container_cgroups_block.txt"

    # Wait for puretime to finish
    wait $puretime_pid 2>/dev/null || true

    # Stop containers
    stop_block_io_containers

    # Copy trace file
    if [ -f "$actual_trace" ]; then
        cp "$actual_trace" "$trace_file"
    else
        log_fail "No trace file generated"
        echo "Result: FAIL - No trace file" >> "$RESULTS_FILE"
        return 1
    fi

    # Analyze results
    log_info "Analyzing block I/O latency..."
    local insert_count=$(grep -c '"event":"block_rq_insert"' "$trace_file" 2>/dev/null || echo 0)
    local issue_count=$(grep -c '"event":"block_rq_issue"' "$trace_file" 2>/dev/null || echo 0)

    echo "  block_rq_insert events: $insert_count" | tee -a "$RESULTS_FILE"
    echo "  block_rq_issue events: $issue_count" | tee -a "$RESULTS_FILE"

    if [ "$issue_count" -gt 10 ]; then
        log_pass "Block I/O events captured successfully"
        echo "Result: PASS" >> "$RESULTS_FILE"
        return 0
    else
        log_warn "Limited block events (NVMe may bypass scheduler)"
        echo "Result: WARNING - Limited events (NVMe bypass possible)" >> "$RESULTS_FILE"
        return 1
    fi
}

# Print summary
print_summary() {
    echo ""
    echo "=========================================="
    echo "Test Summary"
    echo "=========================================="
    echo "Output directory: $OUTPUT_DIR"
    echo "Results file: $RESULTS_FILE"
    echo ""
    echo "Trace files:"
    ls -lh $OUTPUT_DIR/trace_*.jsonl 2>/dev/null || echo "  No trace files"
}

# Main execution
main() {
    check_prerequisites
    setup_output

    local runq_result=0
    local qdisc_result=0
    local io_result=0

    # # CPU Contention Test
    # test_runq_latency || runq_result=$?
    # local actual_trace=$(get_latest_trace)
    # python3 "$MAKESPAN" "$actual_trace" -c "$OUTPUT_DIR/container_cgroups_cpu.txt"

    # # Network Contention Test
    # test_qdisc_latency || qdisc_result=$?
    # actual_trace=$(get_latest_trace)
    # python3 "$MAKESPAN" "$actual_trace" -c "$OUTPUT_DIR/container_cgroups_network.txt"

    # Block I/O Contention Test
    test_block_io_latency || io_result=$?
    actual_trace=$(get_latest_trace)
    python3 "$MAKESPAN" "$actual_trace" -c "$OUTPUT_DIR/container_cgroups_block.txt"

    print_summary

    # Exit with error if all tests failed
    if [ $runq_result -ne 0 ] && [ $qdisc_result -ne 0 ] && [ $io_result -ne 0 ]; then
        exit 1
    fi
}

main "$@"
