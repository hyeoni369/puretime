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
    for tool in stress-ng fio tc python3; do
        if ! command -v $tool &> /dev/null; then
            missing_tools="$missing_tools $tool"
        fi
    done

    if [ -n "$missing_tools" ]; then
        log_warn "Missing tools:$missing_tools"
        log_warn "Some tests may be limited"
    fi

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

    # Generate CPU contention with stress-ng
    if command -v stress-ng &> /dev/null; then
        log_info "Generating CPU contention with stress-ng..."
        stress-ng --cpu $(nproc) --cpu-load 100 --timeout ${TEST_DURATION}s &
        local stress_pid=$!

        # Add competing workloads
        for i in $(seq 1 10); do
            (
                for j in $(seq 1 100); do
                    echo "scale=100; 4*a(1)" | bc -l > /dev/null 2>&1
                done
            ) &
        done
    else
        log_warn "stress-ng not available, using dd for CPU load"
        for i in $(seq 1 $(nproc)); do
            dd if=/dev/zero of=/dev/null bs=1 count=10000000 2>/dev/null &
        done
    fi

    # Wait for puretime to finish
    wait $puretime_pid 2>/dev/null || true
    wait $stress_pid 2>/dev/null || true

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
    local wakeup_count=$(grep -c '"event":"sched_wakeup"' "$trace_file" 2>/dev/null || echo 0)
    local switch_count=$(grep -c '"event":"sched_switch"' "$trace_file" 2>/dev/null || echo 0)

    echo "  sched_wakeup events: $wakeup_count" | tee -a "$RESULTS_FILE"
    echo "  sched_switch events: $switch_count" | tee -a "$RESULTS_FILE"

    if [ "$wakeup_count" -gt 100 ] && [ "$switch_count" -gt 100 ]; then
        log_pass "Run queue events captured successfully"
        echo "Result: PASS" >> "$RESULTS_FILE"
        return 0
    else
        log_fail "Insufficient run queue events"
        echo "Result: FAIL - Insufficient events" >> "$RESULTS_FILE"
        return 1
    fi
}

# Test 2: Qdisc Latency
test_qdisc_latency() {
    echo ""
    log_info "=== Test 2: Qdisc Latency ==="
    echo "" >> "$RESULTS_FILE"
    echo "Test 2: Qdisc Latency" >> "$RESULTS_FILE"
    echo "---------------------" >> "$RESULTS_FILE"

    local trace_file="$OUTPUT_DIR/trace_qdisc.jsonl"

    # Detect network interface
    local iface=$(ip route get 8.8.8.8 2>/dev/null | awk '{print $5; exit}')
    if [ -z "$iface" ]; then
        iface="lo"
    fi
    log_info "Using network interface: $iface"

    # Add network delay if tc is available and not loopback
    local netem_added=false
    if command -v tc &> /dev/null && [ "$iface" != "lo" ]; then
        log_info "Adding 50ms network delay via tc netem..."
        tc qdisc add dev $iface root netem delay 50ms 10ms 2>/dev/null && netem_added=true || true
    fi

    # Start puretime
    log_info "Starting PureTime tracer..."
    $PURETIME_BIN -v -t $TEST_DURATION &
    local puretime_pid=$!
    sleep 2

    local actual_trace=$(get_latest_trace)
    log_info "Trace file: $actual_trace"

    # Generate network traffic
    log_info "Generating network traffic..."

    # Loopback traffic
    nc -l -p 12345 > /dev/null 2>&1 &
    local nc_pid=$!
    for i in $(seq 1 200); do
        echo "test packet $i" | nc -q 0 127.0.0.1 12345 2>/dev/null &
    done

    # External traffic (ping)
    for i in $(seq 1 30); do
        ping -c 1 -W 1 8.8.8.8 > /dev/null 2>&1 &
    done

    # Wait for puretime
    wait $puretime_pid 2>/dev/null || true
    kill $nc_pid 2>/dev/null || true

    # Remove netem qdisc
    if [ "$netem_added" = true ]; then
        log_info "Removing network delay..."
        tc qdisc del dev $iface root 2>/dev/null || true
    fi

    # Copy trace file
    if [ -f "$actual_trace" ]; then
        cp "$actual_trace" "$trace_file"
    else
        log_fail "No trace file generated"
        echo "Result: FAIL - No trace file" >> "$RESULTS_FILE"
        return 1
    fi

    # Analyze results
    log_info "Analyzing qdisc latency..."
    local queue_count=$(grep -c '"event":"net_dev_queue"' "$trace_file" 2>/dev/null || echo 0)
    local xmit_count=$(grep -c '"event":"net_dev_xmit"' "$trace_file" 2>/dev/null || echo 0)

    echo "  net_dev_queue events: $queue_count" | tee -a "$RESULTS_FILE"
    echo "  net_dev_xmit events: $xmit_count" | tee -a "$RESULTS_FILE"

    if [ "$queue_count" -gt 10 ] && [ "$xmit_count" -gt 10 ]; then
        log_pass "Qdisc events captured successfully"
        echo "Result: PASS" >> "$RESULTS_FILE"
        return 0
    else
        log_warn "Limited qdisc events (may need more traffic)"
        echo "Result: WARNING - Limited events" >> "$RESULTS_FILE"
        return 1
    fi
}

# Test 3: I/O Scheduler Latency
test_io_sched_latency() {
    echo ""
    log_info "=== Test 3: I/O Scheduler Latency ==="
    echo "" >> "$RESULTS_FILE"
    echo "Test 3: I/O Scheduler Latency" >> "$RESULTS_FILE"
    echo "------------------------------" >> "$RESULTS_FILE"

    local trace_file="$OUTPUT_DIR/trace_block.jsonl"
    local test_dir="/tmp/puretime_io_test"

    mkdir -p "$test_dir"

    # Start puretime
    log_info "Starting PureTime tracer..."
    $PURETIME_BIN -v -t $TEST_DURATION &
    local puretime_pid=$!
    sleep 2

    local actual_trace=$(get_latest_trace)
    log_info "Trace file: $actual_trace"

    # Generate I/O workload
    log_info "Generating I/O workload..."

    if command -v fio &> /dev/null; then
        fio --name=test --directory=$test_dir --rw=randrw --bs=4k \
            --size=50M --numjobs=4 --runtime=$((TEST_DURATION - 5))s \
            --time_based --ioengine=sync --direct=1 --quiet &
        local fio_pid=$!
    else
        log_warn "fio not available, using dd"
        for i in $(seq 1 5); do
            dd if=/dev/zero of=$test_dir/test_$i.bin bs=1M count=20 \
               conv=fdatasync 2>/dev/null &
        done
    fi

    # Wait for puretime
    wait $puretime_pid 2>/dev/null || true
    wait $fio_pid 2>/dev/null || true

    # Cleanup test files
    rm -rf "$test_dir"

    # Copy trace file
    if [ -f "$actual_trace" ]; then
        cp "$actual_trace" "$trace_file"
    else
        log_fail "No trace file generated"
        echo "Result: FAIL - No trace file" >> "$RESULTS_FILE"
        return 1
    fi

    # Analyze results
    log_info "Analyzing I/O scheduler latency..."
    local insert_count=$(grep -c '"event":"block_rq_insert"' "$trace_file" 2>/dev/null || echo 0)
    local issue_count=$(grep -c '"event":"block_rq_issue"' "$trace_file" 2>/dev/null || echo 0)
    local complete_count=$(grep -c '"event":"block_rq_complete"' "$trace_file" 2>/dev/null || echo 0)

    echo "  block_rq_insert events: $insert_count" | tee -a "$RESULTS_FILE"
    echo "  block_rq_issue events: $issue_count" | tee -a "$RESULTS_FILE"
    echo "  block_rq_complete events: $complete_count" | tee -a "$RESULTS_FILE"

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

# Run Python analyzer on all traces
run_analysis() {
    echo ""
    log_info "=== Running Full Analysis ==="
    echo "" >> "$RESULTS_FILE"
    echo "Full Analysis" >> "$RESULTS_FILE"
    echo "-------------" >> "$RESULTS_FILE"

    # Combine all trace files
    cat $OUTPUT_DIR/trace_*.jsonl > $OUTPUT_DIR/combined_trace.jsonl 2>/dev/null || true

    if [ -f "$OUTPUT_DIR/combined_trace.jsonl" ] && [ -s "$OUTPUT_DIR/combined_trace.jsonl" ]; then
        log_info "Running Python analyzer..."
        python3 "$ANALYZER" "$OUTPUT_DIR/combined_trace.jsonl" \
            -o "$OUTPUT_DIR/analysis_results.json" 2>&1 | tee -a "$RESULTS_FILE"
    else
        log_warn "No trace data to analyze"
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
    echo ""
    echo "To re-analyze traces:"
    echo "  python3 $ANALYZER $OUTPUT_DIR/combined_trace.jsonl"
}

# Main execution
main() {
    check_prerequisites
    setup_output

    local runq_result=0
    local qdisc_result=0
    local io_result=0

    test_runq_latency || runq_result=$?
    test_qdisc_latency || qdisc_result=$?
    test_io_sched_latency || io_result=$?

    run_analysis
    print_summary

    # Exit with error if all tests failed
    if [ $runq_result -ne 0 ] && [ $qdisc_result -ne 0 ] && [ $io_result -ne 0 ]; then
        exit 1
    fi
}

main "$@"
