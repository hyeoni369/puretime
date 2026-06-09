// SPDX-License-Identifier: (LGPL-2.1 OR BSD-2-Clause)
#ifndef __PURETIME_H
#define __PURETIME_H

#define TASK_COMM_LEN 16

/* Event types for all traced subsystems */
enum event_type {
    /* CPU Scheduling Events */
    EVENT_SCHED_ENQUEUE     = 0,
    EVENT_SCHED_SWITCH      = 2,

    /* Network TX Events */
    EVENT_NET_DEV_QUEUE     = 10,
    EVENT_NET_DEV_START_XMIT = 11,
    EVENT_NET_DEV_XMIT      = 12,

    /* Block I/O Events */
    EVENT_BLOCK_RQ_INSERT   = 20,
    EVENT_BLOCK_RQ_ISSUE    = 21,
    EVENT_BLOCK_RQ_COMPLETE = 22,

    /* Softirq Events */
    EVENT_SOFTIRQ_ENTRY     = 30,
    EVENT_SOFTIRQ_EXIT      = 31,

    /* Trace metadata (written once by the loader at shutdown) */
    EVENT_TRACE_SUMMARY     = 40,
};

/* Common header for all events */
struct event_header {
    __u64 timestamp_ns;      /* bpf_ktime_get_ns() */
    __u64 cgroup_id;         /* cgroup ID of the process/socket */
    __u32 cpu;               /* bpf_get_smp_processor_id() */
    __u32 event_type;        /* enum event_type */
};

/* Scheduler events: wakeup, wakeup_new, switch.
 * comm/prev_comm intentionally omitted (OPT-4): the makespan analyzer keys on tid,
 * not comm, so capturing it cost a per-event string read + JSON escape on the two
 * hottest hooks for nothing. Dropping it shrinks this record 88 -> 56 bytes. */
struct sched_event {
    struct event_header hdr;
    __s32 pid;               /* Process ID (tgid) */
    __s32 tid;               /* Thread ID (pid in kernel terms) */
    __u8 is_switch_in;       /* 1 = switched in, 0 = switched out */
    __u8 reserved[7];        /* Alignment padding (keeps prev_cgroup_id 8-aligned) */
    /* For sched_switch only: prev process info */
    __u64 prev_cgroup_id;    /* cgroup ID of prev process */
    __s32 prev_pid;
    __s32 prev_tid;
};

/* Network TX events */
struct net_event {
    struct event_header hdr;
    __u64 skb_addr;          /* sk_buff address for correlation */
    __u32 len;               /* Packet length */
    __u32 ifindex;           /* Interface index */
};

/* Block I/O events */
struct block_event {
    struct event_header hdr;
    __u64 request_addr;      /* Request address for correlation */
    __u32 dev;               /* Device number (dev_t) */
    __u32 nr_sector;         /* Number of sectors */
    __u64 sector;            /* Starting sector */
    char rwbs[8];            /* R/W/S flags as string */
};

/* Softirq events */
struct softirq_event {
    struct event_header hdr;
    __u32 vec;               /* Softirq vector number */
    __u32 reserved;          /* Alignment padding */
};

/* Trace summary: written once by the loader at shutdown so the analyzer can
 * reject an incomplete trace. Emitted as a JSONL line:
 *   {"event":"trace_summary","dropped_events":N}
 */
struct trace_summary_event {
    struct event_header hdr;   /* event_type = EVENT_TRACE_SUMMARY */
    __u64 dropped_events;      /* total ring-buffer reserve failures */
};

#endif /* __PURETIME_H */
