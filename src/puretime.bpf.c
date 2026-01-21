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

/* Ring buffer for events - 256MB */
struct {
    __uint(type, BPF_MAP_TYPE_RINGBUF);
    __uint(max_entries, 256 * 1024 * 1024);
} events SEC(".maps");

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

/* ============================================================
 * CPU Scheduling Tracepoints
 * ============================================================ */

SEC("fentry/enqueue_task")
int BPF_PROG(handle_enqueue_task, struct rq *rq, struct task_struct *p, int flags)
{
    struct sched_event *e;

    e = bpf_ringbuf_reserve(&events, sizeof(*e), 0);
    if (!e)
        return 0;

    e->hdr.timestamp_ns = bpf_ktime_get_ns();
    e->hdr.cgroup_id = get_task_cgroup_id(p);
    e->hdr.cpu = bpf_get_smp_processor_id();
    e->hdr.event_type = EVENT_SCHED_ENQUEUE;

    e->pid = BPF_CORE_READ(p, tgid);
    e->tid = BPF_CORE_READ(p, pid);
    bpf_probe_read_kernel_str(&e->comm, sizeof(e->comm), BPF_CORE_READ(p, comm));
    e->is_switch_in = 0;

    /* Clear prev fields (not used for enqueue) */
    e->prev_cgroup_id = 0;
    e->prev_pid = 0;
    e->prev_tid = 0;
    __builtin_memset(e->prev_comm, 0, sizeof(e->prev_comm));

    bpf_ringbuf_submit(e, 0);
    return 0;
}

SEC("tp_btf/sched_switch")
int BPF_PROG(handle_sched_switch, bool preempt,
             struct task_struct *prev, struct task_struct *next,
             unsigned int prev_state)
{
    struct sched_event *e;

    e = bpf_ringbuf_reserve(&events, sizeof(*e), 0);
    if (!e)
        return 0;

    e->hdr.timestamp_ns = bpf_ktime_get_ns();
    e->hdr.cgroup_id = get_task_cgroup_id(next);
    e->hdr.cpu = bpf_get_smp_processor_id();
    e->hdr.event_type = EVENT_SCHED_SWITCH;

    /* Next task (switching in) */
    e->pid = BPF_CORE_READ(next, tgid);
    e->tid = BPF_CORE_READ(next, pid);
    bpf_probe_read_kernel_str(&e->comm, sizeof(e->comm), BPF_CORE_READ(next, comm));
    e->is_switch_in = 1;

    /* Previous task (switching out) */
    e->prev_cgroup_id = get_task_cgroup_id(prev);
    e->prev_pid = BPF_CORE_READ(prev, tgid);
    e->prev_tid = BPF_CORE_READ(prev, pid);
    bpf_probe_read_kernel_str(&e->prev_comm, sizeof(e->prev_comm), BPF_CORE_READ(prev, comm));

    bpf_ringbuf_submit(e, 0);
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

    e = bpf_ringbuf_reserve(&events, sizeof(*e), 0);
    if (!e)
        return 0;

    e->hdr.timestamp_ns = bpf_ktime_get_ns();
    e->hdr.cpu = bpf_get_smp_processor_id();
    e->hdr.event_type = EVENT_NET_DEV_QUEUE;

    /* Get cgroup_id from socket if available */
    sk = BPF_CORE_READ(skb, sk);
    e->hdr.cgroup_id = get_cgroup_id_from_socket(sk);

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

    e = bpf_ringbuf_reserve(&events, sizeof(*e), 0);
    if (!e)
        return 0;

    e->hdr.timestamp_ns = bpf_ktime_get_ns();
    e->hdr.cpu = bpf_get_smp_processor_id();
    e->hdr.event_type = EVENT_NET_DEV_START_XMIT;

    sk = BPF_CORE_READ(skb, sk);
    e->hdr.cgroup_id = get_cgroup_id_from_socket(sk);

    e->skb_addr = (__u64)skb;
    e->len = BPF_CORE_READ(skb, len);
    e->ifindex = dev ? BPF_CORE_READ(dev, ifindex) : 0;

    bpf_ringbuf_submit(e, 0);
    return 0;
}

SEC("tp_btf/net_dev_xmit")
int BPF_PROG(handle_net_dev_xmit, struct sk_buff *skb, int rc,
             struct net_device *dev, unsigned int len)
{
    struct net_event *e;
    struct sock *sk;

    e = bpf_ringbuf_reserve(&events, sizeof(*e), 0);
    if (!e)
        return 0;

    e->hdr.timestamp_ns = bpf_ktime_get_ns();
    e->hdr.cpu = bpf_get_smp_processor_id();
    e->hdr.event_type = EVENT_NET_DEV_XMIT;

    sk = BPF_CORE_READ(skb, sk);
    e->hdr.cgroup_id = get_cgroup_id_from_socket(sk);

    e->skb_addr = (__u64)skb;
    e->len = len;
    e->ifindex = dev ? BPF_CORE_READ(dev, ifindex) : 0;

    bpf_ringbuf_submit(e, 0);
    return 0;
}

/* ============================================================
 * Block I/O Tracepoints
 * ============================================================ */

SEC("tp_btf/block_rq_insert")
int BPF_PROG(handle_block_rq_insert, struct request *rq)
{
    struct block_event *e;
    struct block_device *bdev;
    blk_opf_t cmd_flags;

    e = bpf_ringbuf_reserve(&events, sizeof(*e), 0);
    if (!e)
        return 0;

    e->hdr.timestamp_ns = bpf_ktime_get_ns();
    e->hdr.cgroup_id = bpf_get_current_cgroup_id();
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

    e = bpf_ringbuf_reserve(&events, sizeof(*e), 0);
    if (!e)
        return 0;

    e->hdr.timestamp_ns = bpf_ktime_get_ns();
    e->hdr.cgroup_id = bpf_get_current_cgroup_id();
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

SEC("tp_btf/block_rq_complete")
int BPF_PROG(handle_block_rq_complete, struct request *rq,
             blk_status_t error, unsigned int nr_bytes)
{
    struct block_event *e;
    struct block_device *bdev;
    blk_opf_t cmd_flags;

    e = bpf_ringbuf_reserve(&events, sizeof(*e), 0);
    if (!e)
        return 0;

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
    if (!e)
        return 0;

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
    if (!e)
        return 0;

    e->hdr.timestamp_ns = bpf_ktime_get_ns();
    e->hdr.cgroup_id = bpf_get_current_cgroup_id();
    e->hdr.cpu = bpf_get_smp_processor_id();
    e->hdr.event_type = EVENT_SOFTIRQ_EXIT;

    e->vec = vec;
    e->reserved = 0;

    bpf_ringbuf_submit(e, 0);
    return 0;
}
