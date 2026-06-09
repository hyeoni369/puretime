// SPDX-License-Identifier: GPL-2.0 OR BSD-3-Clause
/* PureTime: Noise-Free Serverless Execution Time Measurement System
 * eBPF Tracer for CPU scheduling, Network TX, Block I/O, and Softirq events
 */
#include "vmlinux.h"
#include <bpf/bpf_helpers.h>
#include <bpf/bpf_tracing.h>
#include <bpf/bpf_core_read.h>
#include "puretime.h"

char LICENSE[] SEC("license") = "Dual BSD/GPL";

/* Ring buffer for events - 512MB (high-load / contention-experiment default).
 * Sized generously so heavy multi-container noise runs do not drop events (a
 * dropped trace is rejected by the analyzer, which would waste the run). The
 * dropped_events counter still backstops any overflow.
 * NOTE: the ring buffer is the dominant RSS cost (libbpf double-maps the data
 * region -> ~1GB RSS at 512MB). For the OVERHEAD measurement (experiment 4-1 /
 * 실험 5) lower this to `32 * 1024 * 1024` (~70MB RSS) before building, since RSS
 * is exactly what that experiment reports. Must stay a power of two. */
struct {
    __uint(type, BPF_MAP_TYPE_RINGBUF);
    __uint(max_entries, 512 * 1024 * 1024);
} events SEC(".maps");

/* Hash map to track socket -> cgroup_id mapping
 * Used to resolve container cgroup_id in softirq context where
 * direct sk->sk_cgrp_data.cgroup lookup returns root cgroup
 */
struct {
    __uint(type, BPF_MAP_TYPE_HASH);
    __uint(max_entries, 10240);
    __type(key, __u64);      /* socket pointer */
    __type(value, __u64);    /* cgroup_id */
} tracked_sockets SEC(".maps");

/* Per-CPU counter of ring buffer reserve failures (dropped events).
 * The loader reads this at shutdown so an incomplete trace can be rejected
 * rather than silently measured.
 */
struct {
    __uint(type, BPF_MAP_TYPE_PERCPU_ARRAY);
    __uint(max_entries, 1);
    __type(key, __u32);
    __type(value, __u64);
} dropped_events SEC(".maps");

/* Bump the dropped-event counter on a ring buffer reserve failure */
static __always_inline void count_drop(void)
{
    __u32 key = 0;
    __u64 *cnt = bpf_map_lookup_elem(&dropped_events, &key);
    if (cnt)
        __sync_fetch_and_add(cnt, 1);
}

/* Softirq vector numbers to filter */
#define NET_TX_SOFTIRQ   1
#define NET_RX_SOFTIRQ   2
#define BLOCK_SOFTIRQ    4

/* Helper: Get cgroup ID from task_struct using CO-RE */
static __always_inline __u64 get_task_cgroup_id(struct task_struct *task)
{
    struct css_set *cgroups;
    struct cgroup *cgrp;
    struct kernfs_node *kn;

    cgroups = BPF_CORE_READ(task, cgroups);
    if (!cgroups)
        return 0;

    cgrp = BPF_CORE_READ(cgroups, dfl_cgrp);
    if (!cgrp)
        return 0;

    kn = BPF_CORE_READ(cgrp, kn);
    if (!kn)
        return 0;

    return BPF_CORE_READ(kn, id);
}

/* Helper: Get cgroup ID from socket's cgroup data */
static __always_inline __u64 get_cgroup_id_from_socket(struct sock *sk)
{
    if (!sk)
        return 0;

    /* Read cgroup from socket's cgroup data */
    struct cgroup *cgrp = BPF_CORE_READ(sk, sk_cgrp_data.cgroup);
    if (!cgrp)
        return 0;

    /* Get kernfs_node and read its id */
    struct kernfs_node *kn = BPF_CORE_READ(cgrp, kn);
    if (!kn)
        return 0;

    return BPF_CORE_READ(kn, id);
}

/* Helper: Check if task is in a container cgroup (level >= 2)
 * Cgroup hierarchy: root (level=0) -> system.slice (level=1) -> containers (level>=2)
 */
static __always_inline bool is_container_cgroup(struct task_struct *task)
{
    struct css_set *cgroups;
    struct cgroup *cgrp;

    cgroups = BPF_CORE_READ(task, cgroups);
    if (!cgroups)
        return false;

    cgrp = BPF_CORE_READ(cgroups, dfl_cgrp);
    if (!cgrp)
        return false;

    return BPF_CORE_READ(cgrp, level) >= 2;
}

/* ============================================================
 * CPU Scheduling Tracepoints
 * ============================================================ */

SEC("fentry/enqueue_task")
int BPF_PROG(handle_enqueue_task, struct rq *rq, struct task_struct *p, int flags)
{
    struct sched_event *e;
    __u64 cgroup_id;

    cgroup_id = get_task_cgroup_id(p);
    if (cgroup_id <= 1)
        return 0;  /* Ignore idle and root cgroups */

    e = bpf_ringbuf_reserve(&events, sizeof(*e), 0);
    if (!e) {
        count_drop();
        return 0;
    }

    e->hdr.timestamp_ns = bpf_ktime_get_ns();
    e->hdr.cgroup_id = cgroup_id;  /* reuse cached value (OPT-3: avoid 2nd cgroup walk) */
    e->hdr.cpu = bpf_get_smp_processor_id();
    e->hdr.event_type = EVENT_SCHED_ENQUEUE;

    e->pid = BPF_CORE_READ(p, tgid);
    e->tid = BPF_CORE_READ(p, pid);
    e->is_switch_in = 0;

    /* Clear prev fields (not used for enqueue) */
    e->prev_cgroup_id = 0;
    e->prev_pid = 0;
    e->prev_tid = 0;

    bpf_ringbuf_submit(e, 0);
    return 0;
}

SEC("tp_btf/sched_switch")
int BPF_PROG(handle_sched_switch, bool preempt,
             struct task_struct *prev, struct task_struct *next,
             unsigned int prev_state)
{
    struct sched_event *e;
    __u64 cgroup_id;

    cgroup_id = get_task_cgroup_id(next);
    if (cgroup_id <= 1)
        return 0;  /* Ignore idle and root cgroups */

    /* prev가 preempted (TASK_RUNNING) → run queue 재진입 이벤트 */
    if (prev_state == 0) {  /* TASK_RUNNING = 0 */
        e = bpf_ringbuf_reserve(&events, sizeof(*e), 0);
        if (!e) {
            count_drop();
            return 0;
        }

        e->hdr.timestamp_ns = bpf_ktime_get_ns();
        e->hdr.cgroup_id = cgroup_id;
        e->hdr.cpu = bpf_get_smp_processor_id();
        e->hdr.event_type = EVENT_SCHED_ENQUEUE;

        e->pid = BPF_CORE_READ(prev, tgid);
        e->tid = BPF_CORE_READ(prev, pid);
        e->is_switch_in = 0;

        e->prev_cgroup_id = 0;
        e->prev_pid = 0;
        e->prev_tid = 0;

        bpf_ringbuf_submit(e, 0);
    }
    
    /* next가 switch in → sched_switch 이벤트 */    
    e = bpf_ringbuf_reserve(&events, sizeof(*e), 0);
    if (!e) {
        count_drop();
        return 0;
    }

    e->hdr.timestamp_ns = bpf_ktime_get_ns();
    e->hdr.cgroup_id = cgroup_id;
    e->hdr.cpu = bpf_get_smp_processor_id();
    e->hdr.event_type = EVENT_SCHED_SWITCH;

    /* Next task (switching in) */
    e->pid = BPF_CORE_READ(next, tgid);
    e->tid = BPF_CORE_READ(next, pid);
    e->is_switch_in = 1;

    /* Previous task (switching out) */
    e->prev_cgroup_id = get_task_cgroup_id(prev);
    e->prev_pid = BPF_CORE_READ(prev, tgid);
    e->prev_tid = BPF_CORE_READ(prev, pid);

    bpf_ringbuf_submit(e, 0);
    
    return 0;
}

/* ============================================================
 * Socket Tracking for Container Network Attribution
 * ============================================================ */

/* Register socket -> cgroup_id mapping when container sends TCP data
 * This runs in process context where cgroup information is valid
 */
SEC("fentry/tcp_sendmsg")
int BPF_PROG(tcp_sendmsg_entry, struct sock *sk, struct msghdr *msg, size_t size)
{
    struct task_struct *task;
    __u64 cgroup_id;
    __u64 sk_ptr;

    /* Get current task */
    task = (struct task_struct *)bpf_get_current_task();

    /* Only track sockets from container processes */
    if (!is_container_cgroup(task))
        return 0;

    /* Get cgroup ID while we have valid process context */
    cgroup_id = get_task_cgroup_id(task);
    if (cgroup_id <= 1)
        return 0;  /* Skip root/system cgroups */

    /* Register socket -> cgroup mapping */
    sk_ptr = (__u64)sk;
    bpf_map_update_elem(&tracked_sockets, &sk_ptr, &cgroup_id, BPF_ANY);

    return 0;
}

/* Clean up socket mapping when TCP connection is closed
 * Prevents stale entries and potential socket pointer reuse issues
 */
SEC("fentry/tcp_close")
int BPF_PROG(tcp_close_entry, struct sock *sk, long timeout)
{
    __u64 sk_ptr = (__u64)sk;
    bpf_map_delete_elem(&tracked_sockets, &sk_ptr);
    return 0;
}

/* ============================================================
 * Network TX Tracepoints
 * ============================================================ */

SEC("tp_btf/net_dev_queue")
int BPF_PROG(handle_net_dev_queue, struct sk_buff *skb)
{
    struct net_event *e;
    struct sock *sk;
    struct net_device *dev;
    __u64 sk_ptr;
    __u64 *cgroup_id_ptr;
    __u64 cgroup_id;

    /* Get socket from skb */
    sk = BPF_CORE_READ(skb, sk);
    if (!sk)
        return 0;  /* No socket, cannot attribute */

    /* Try map lookup first (works in softirq context) */
    sk_ptr = (__u64)sk;
    cgroup_id_ptr = bpf_map_lookup_elem(&tracked_sockets, &sk_ptr);

    if (cgroup_id_ptr) {
        cgroup_id = *cgroup_id_ptr;
    } else {
        /* Fallback to direct socket cgroup read (may return root in softirq) */
        cgroup_id = get_cgroup_id_from_socket(sk);
    }

    /* Filter non-container events (root cgroup = 1) */
    if (cgroup_id <= 1)
        return 0;

    /* Reserve ring buffer entry */
    e = bpf_ringbuf_reserve(&events, sizeof(*e), 0);
    if (!e) {
        count_drop();
        return 0;
    }

    e->hdr.timestamp_ns = bpf_ktime_get_ns();
    e->hdr.cpu = bpf_get_smp_processor_id();
    e->hdr.event_type = EVENT_NET_DEV_QUEUE;
    e->hdr.cgroup_id = cgroup_id;

    e->skb_addr = (__u64)skb;
    e->len = BPF_CORE_READ(skb, len);

    dev = BPF_CORE_READ(skb, dev);
    e->ifindex = dev ? BPF_CORE_READ(dev, ifindex) : 0;

    bpf_ringbuf_submit(e, 0);
    return 0;
}

SEC("tp_btf/net_dev_start_xmit")
int BPF_PROG(handle_net_dev_start_xmit, const struct sk_buff *skb,
             const struct net_device *dev)
{
    struct net_event *e;
    struct sock *sk;
    __u64 sk_ptr;
    __u64 *cgroup_id_ptr;
    __u64 cgroup_id;

    /* Get socket from skb */
    sk = BPF_CORE_READ(skb, sk);
    if (!sk)
        return 0;

    /* Try map lookup first (works in softirq context) */
    sk_ptr = (__u64)sk;
    cgroup_id_ptr = bpf_map_lookup_elem(&tracked_sockets, &sk_ptr);

    if (cgroup_id_ptr) {
        cgroup_id = *cgroup_id_ptr;
    } else {
        cgroup_id = get_cgroup_id_from_socket(sk);
    }

    /* Filter non-container events */
    if (cgroup_id <= 1)
        return 0;

    e = bpf_ringbuf_reserve(&events, sizeof(*e), 0);
    if (!e) {
        count_drop();
        return 0;
    }

    e->hdr.timestamp_ns = bpf_ktime_get_ns();
    e->hdr.cpu = bpf_get_smp_processor_id();
    e->hdr.event_type = EVENT_NET_DEV_START_XMIT;
    e->hdr.cgroup_id = cgroup_id;

    e->skb_addr = (__u64)skb;
    e->len = BPF_CORE_READ(skb, len);
    e->ifindex = dev ? BPF_CORE_READ(dev, ifindex) : 0;

    bpf_ringbuf_submit(e, 0);
    return 0;
}

/* DISABLED (OPT-1): net_dev_xmit is never consumed by the analyzer, which uses
 * only net_dev_queue + net_dev_start_xmit. Disabled (not deleted) to cut ~1/3 of
 * net event volume with no accuracy loss. */
#if 0
SEC("tp_btf/net_dev_xmit")
int BPF_PROG(handle_net_dev_xmit, struct sk_buff *skb, int rc,
             struct net_device *dev, unsigned int len)
{
    struct net_event *e;
    struct sock *sk;
    __u64 sk_ptr;
    __u64 *cgroup_id_ptr;
    __u64 cgroup_id;

    /* Get socket from skb */
    sk = BPF_CORE_READ(skb, sk);
    if (!sk)
        return 0;

    /* Try map lookup first (works in softirq context) */
    sk_ptr = (__u64)sk;
    cgroup_id_ptr = bpf_map_lookup_elem(&tracked_sockets, &sk_ptr);

    if (cgroup_id_ptr) {
        cgroup_id = *cgroup_id_ptr;
    } else {
        cgroup_id = get_cgroup_id_from_socket(sk);
    }

    /* Filter non-container events */
    if (cgroup_id <= 1)
        return 0;

    e = bpf_ringbuf_reserve(&events, sizeof(*e), 0);
    if (!e) {
        count_drop();
        return 0;
    }

    e->hdr.timestamp_ns = bpf_ktime_get_ns();
    e->hdr.cpu = bpf_get_smp_processor_id();
    e->hdr.event_type = EVENT_NET_DEV_XMIT;
    e->hdr.cgroup_id = cgroup_id;

    e->skb_addr = (__u64)skb;
    e->len = len;
    e->ifindex = dev ? BPF_CORE_READ(dev, ifindex) : 0;

    bpf_ringbuf_submit(e, 0);
    return 0;
}
#endif  /* DISABLED net_dev_xmit (OPT-1) */

/* ============================================================
 * Block I/O Tracepoints
 * ============================================================ */

/* Helper: Get cgroup ID from a block request's owning blkcg.
 * For buffered writeback the submitting task is a kworker (root cgroup), but the
 * bio carries the originating cgroup's blkcg, so this attributes the I/O to the
 * container that issued it. Requires the io controller delegated to the container.
 */
static __always_inline __u64 get_rq_blkcg_cgroup_id(struct request *rq)
{
    struct cgroup *cgrp = BPF_CORE_READ(rq, bio, bi_blkg, blkcg, css.cgroup);
    if (!cgrp)
        return 0;
    return BPF_CORE_READ(cgrp, kn, id);
}

SEC("tp_btf/block_rq_insert")
int BPF_PROG(handle_block_rq_insert, struct request *rq)
{
    struct block_event *e;
    struct block_device *bdev;
    blk_opf_t cmd_flags;
    __u64 cgroup_id;

    /* Attribute by the request's owning blkcg (survives writeback-kworker
     * submission); fall back to current task for synchronous/direct I/O. */
    cgroup_id = get_rq_blkcg_cgroup_id(rq);
    if (cgroup_id <= 1)
        cgroup_id = bpf_get_current_cgroup_id();
    if (cgroup_id <= 1)
        return 0;  /* Ignore idle and root cgroups */

    e = bpf_ringbuf_reserve(&events, sizeof(*e), 0);
    if (!e) {
        count_drop();
        return 0;
    }

    e->hdr.timestamp_ns = bpf_ktime_get_ns();
    e->hdr.cgroup_id = cgroup_id;
    e->hdr.cpu = bpf_get_smp_processor_id();
    e->hdr.event_type = EVENT_BLOCK_RQ_INSERT;

    e->request_addr = (__u64)rq;

    bdev = BPF_CORE_READ(rq, part);
    e->dev = bdev ? BPF_CORE_READ(bdev, bd_dev) : 0;

    e->sector = BPF_CORE_READ(rq, __sector);
    e->nr_sector = BPF_CORE_READ(rq, __data_len) >> 9;

    /* Determine R/W from cmd_flags */
    cmd_flags = BPF_CORE_READ(rq, cmd_flags);
    if (cmd_flags & 1)  /* REQ_OP_WRITE */
        __builtin_memcpy(e->rwbs, "W", 2);
    else
        __builtin_memcpy(e->rwbs, "R", 2);

    bpf_ringbuf_submit(e, 0);
    return 0;
}

SEC("tp_btf/block_rq_issue")
int BPF_PROG(handle_block_rq_issue, struct request *rq)
{
    struct block_event *e;
    struct block_device *bdev;
    blk_opf_t cmd_flags;
    __u64 cgroup_id;

    /* Attribute by the request's owning blkcg (survives writeback-kworker
     * submission); fall back to current task for synchronous/direct I/O. */
    cgroup_id = get_rq_blkcg_cgroup_id(rq);
    if (cgroup_id <= 1)
        cgroup_id = bpf_get_current_cgroup_id();
    if (cgroup_id <= 1)
        return 0;  /* Ignore idle and root cgroups */

    e = bpf_ringbuf_reserve(&events, sizeof(*e), 0);
    if (!e) {
        count_drop();
        return 0;
    }

    e->hdr.timestamp_ns = bpf_ktime_get_ns();
    e->hdr.cgroup_id = cgroup_id;
    e->hdr.cpu = bpf_get_smp_processor_id();
    e->hdr.event_type = EVENT_BLOCK_RQ_ISSUE;

    e->request_addr = (__u64)rq;

    bdev = BPF_CORE_READ(rq, part);
    e->dev = bdev ? BPF_CORE_READ(bdev, bd_dev) : 0;

    e->sector = BPF_CORE_READ(rq, __sector);
    e->nr_sector = BPF_CORE_READ(rq, __data_len) >> 9;

    cmd_flags = BPF_CORE_READ(rq, cmd_flags);
    if (cmd_flags & 1)
        __builtin_memcpy(e->rwbs, "W", 2);
    else
        __builtin_memcpy(e->rwbs, "R", 2);

    bpf_ringbuf_submit(e, 0);
    return 0;
}

/* DISABLED (OPT-2): block_rq_complete is never consumed by the analyzer (it uses
 * only block_rq_insert + block_rq_issue) and is emitted without a cgroup filter,
 * making it the noisiest block hook. Disabled (not deleted) to cut block event
 * volume and reduce ring-buffer drop pressure. */
#if 0
SEC("tp_btf/block_rq_complete")
int BPF_PROG(handle_block_rq_complete, struct request *rq,
             blk_status_t error, unsigned int nr_bytes)
{
    struct block_event *e;
    struct block_device *bdev;
    blk_opf_t cmd_flags;

    e = bpf_ringbuf_reserve(&events, sizeof(*e), 0);
    if (!e) {
        count_drop();
        return 0;
    }

    e->hdr.timestamp_ns = bpf_ktime_get_ns();
    e->hdr.cgroup_id = bpf_get_current_cgroup_id();
    e->hdr.cpu = bpf_get_smp_processor_id();
    e->hdr.event_type = EVENT_BLOCK_RQ_COMPLETE;

    e->request_addr = (__u64)rq;

    bdev = BPF_CORE_READ(rq, part);
    e->dev = bdev ? BPF_CORE_READ(bdev, bd_dev) : 0;

    e->sector = BPF_CORE_READ(rq, __sector);
    e->nr_sector = nr_bytes >> 9;

    cmd_flags = BPF_CORE_READ(rq, cmd_flags);
    if (cmd_flags & 1)
        __builtin_memcpy(e->rwbs, "W", 2);
    else
        __builtin_memcpy(e->rwbs, "R", 2);

    bpf_ringbuf_submit(e, 0);
    return 0;
}
#endif  /* DISABLED block_rq_complete (OPT-2) */

/* ============================================================
 * Softirq Tracepoints
 * ============================================================ */

SEC("tp_btf/softirq_entry")
int BPF_PROG(handle_softirq_entry, unsigned int vec)
{
    struct softirq_event *e;

    /* Filter: only NET_TX, NET_RX, BLOCK softirqs */
    if (vec != NET_TX_SOFTIRQ && vec != NET_RX_SOFTIRQ && vec != BLOCK_SOFTIRQ)
        return 0;

    e = bpf_ringbuf_reserve(&events, sizeof(*e), 0);
    if (!e) {
        count_drop();
        return 0;
    }

    e->hdr.timestamp_ns = bpf_ktime_get_ns();
    e->hdr.cgroup_id = bpf_get_current_cgroup_id();
    e->hdr.cpu = bpf_get_smp_processor_id();
    e->hdr.event_type = EVENT_SOFTIRQ_ENTRY;

    e->vec = vec;
    e->reserved = 0;

    bpf_ringbuf_submit(e, 0);
    return 0;
}

SEC("tp_btf/softirq_exit")
int BPF_PROG(handle_softirq_exit, unsigned int vec)
{
    struct softirq_event *e;

    /* Filter: only NET_TX, NET_RX, BLOCK softirqs */
    if (vec != NET_TX_SOFTIRQ && vec != NET_RX_SOFTIRQ && vec != BLOCK_SOFTIRQ)
        return 0;

    e = bpf_ringbuf_reserve(&events, sizeof(*e), 0);
    if (!e) {
        count_drop();
        return 0;
    }

    e->hdr.timestamp_ns = bpf_ktime_get_ns();
    e->hdr.cgroup_id = bpf_get_current_cgroup_id();
    e->hdr.cpu = bpf_get_smp_processor_id();
    e->hdr.event_type = EVENT_SOFTIRQ_EXIT;

    e->vec = vec;
    e->reserved = 0;

    bpf_ringbuf_submit(e, 0);
    return 0;
}
