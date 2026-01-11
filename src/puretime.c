// SPDX-License-Identifier: (LGPL-2.1 OR BSD-2-Clause)
/* PureTime: Noise-Free Serverless Execution Time Measurement System
 * User-space loader for eBPF tracer
 */
#include <argp.h>
#include <signal.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <time.h>
#include <unistd.h>
#include <sys/stat.h>
#include <sys/resource.h>
#include <bpf/libbpf.h>
#include "puretime.h"
#include "puretime.skel.h"
#include "json_writer.h"

/* Environment configuration */
static struct env {
    bool verbose;
    int duration_sec;        /* -t option: run duration in seconds, 0 = infinite */
    char output_path[256];   /* Output file path */
} env = {
    .verbose = false,
    .duration_sec = 0,
};

/* Signal handling */
static volatile bool exiting = false;

static void sig_handler(int sig)
{
    exiting = true;
}

/* Argument parsing */
const char *argp_program_version = "puretime 1.0";
const char *argp_program_bug_address = "<puretime@example.com>";
const char argp_program_doc[] =
"PureTime - eBPF-based noisy neighbor interference tracer.\n"
"\n"
"Traces CPU scheduling, network TX, block I/O, and softirq events\n"
"to measure interference in serverless computing environments.\n"
"\n"
"USAGE: sudo ./puretime [-t <seconds>] [-v]\n";

static const struct argp_option opts[] = {
    { "time", 't', "SECONDS", 0, "Run for specified duration then exit" },
    { "verbose", 'v', NULL, 0, "Verbose debug output" },
    {},
};

static error_t parse_arg(int key, char *arg, struct argp_state *state)
{
    switch (key) {
    case 't':
        errno = 0;
        env.duration_sec = strtol(arg, NULL, 10);
        if (errno || env.duration_sec <= 0) {
            fprintf(stderr, "Invalid duration: %s\n", arg);
            argp_usage(state);
        }
        break;
    case 'v':
        env.verbose = true;
        break;
    case ARGP_KEY_ARG:
        argp_usage(state);
        break;
    default:
        return ARGP_ERR_UNKNOWN;
    }
    return 0;
}

static const struct argp argp = {
    .options = opts,
    .parser = parse_arg,
    .doc = argp_program_doc,
};

/* libbpf print callback */
static int libbpf_print_fn(enum libbpf_print_level level, const char *format, va_list args)
{
    if (level == LIBBPF_DEBUG && !env.verbose)
        return 0;
    return vfprintf(stderr, format, args);
}

/* Event type to string conversion */
static const char *event_type_str(int type)
{
    switch (type) {
    case EVENT_SCHED_WAKEUP:      return "sched_wakeup";
    case EVENT_SCHED_WAKEUP_NEW:  return "sched_wakeup_new";
    case EVENT_SCHED_SWITCH:      return "sched_switch";
    case EVENT_NET_DEV_QUEUE:     return "net_dev_queue";
    case EVENT_NET_DEV_START_XMIT: return "net_dev_start_xmit";
    case EVENT_NET_DEV_XMIT:      return "net_dev_xmit";
    case EVENT_BLOCK_RQ_INSERT:   return "block_rq_insert";
    case EVENT_BLOCK_RQ_ISSUE:    return "block_rq_issue";
    case EVENT_BLOCK_RQ_COMPLETE: return "block_rq_complete";
    case EVENT_SOFTIRQ_ENTRY:     return "softirq_entry";
    case EVENT_SOFTIRQ_EXIT:      return "softirq_exit";
    default:                      return "unknown";
    }
}

/* Ring buffer event handler */
static int handle_event(void *ctx, void *data, size_t data_sz)
{
    struct json_writer *jw = (struct json_writer *)ctx;
    const struct event_header *hdr = data;

    /* Start JSON object */
    json_writer_start_object(jw);

    /* Common fields */
    json_writer_add_string(jw, "event", event_type_str(hdr->event_type));
    json_writer_add_uint64(jw, "timestamp_ns", hdr->timestamp_ns);
    json_writer_add_uint64(jw, "cgroup_id", hdr->cgroup_id);
    json_writer_add_uint32(jw, "cpu", hdr->cpu);

    /* Event-specific fields */
    if (hdr->event_type <= EVENT_SCHED_SWITCH) {
        /* Scheduler events */
        const struct sched_event *e = data;
        json_writer_add_int32(jw, "pid", e->pid);
        json_writer_add_int32(jw, "tid", e->tid);
        json_writer_add_string(jw, "comm", e->comm);

        if (hdr->event_type == EVENT_SCHED_SWITCH) {
            json_writer_add_uint64(jw, "prev_cgroup_id", e->prev_cgroup_id);
            json_writer_add_int32(jw, "prev_pid", e->prev_pid);
            json_writer_add_int32(jw, "prev_tid", e->prev_tid);
            json_writer_add_string(jw, "prev_comm", e->prev_comm);
        }
    } else if (hdr->event_type >= EVENT_NET_DEV_QUEUE &&
               hdr->event_type <= EVENT_NET_DEV_XMIT) {
        /* Network events */
        const struct net_event *e = data;
        json_writer_add_uint64(jw, "skb_addr", e->skb_addr);
        json_writer_add_uint32(jw, "len", e->len);
        json_writer_add_uint32(jw, "ifindex", e->ifindex);
    } else if (hdr->event_type >= EVENT_BLOCK_RQ_INSERT &&
               hdr->event_type <= EVENT_BLOCK_RQ_COMPLETE) {
        /* Block I/O events */
        const struct block_event *e = data;
        json_writer_add_uint64(jw, "request_addr", e->request_addr);
        json_writer_add_uint32(jw, "dev", e->dev);
        json_writer_add_uint64(jw, "sector", e->sector);
        json_writer_add_uint32(jw, "nr_sector", e->nr_sector);
        json_writer_add_string(jw, "rwbs", (const char *)e->rwbs);
    } else if (hdr->event_type >= EVENT_SOFTIRQ_ENTRY) {
        /* Softirq events */
        const struct softirq_event *e = data;
        json_writer_add_uint32(jw, "vec", e->vec);
    }

    /* End JSON object and write line */
    json_writer_end_object(jw);

    return 0;
}

/* Setup output file with timestamp */
static int setup_output_file(void)
{
    time_t now;
    struct tm *tm_info;
    char filename[128];
    int ret;

    /* Create output directory if it doesn't exist */
    ret = mkdir("/var/log/puretime", 0755);
    if (ret < 0 && errno != EEXIST) {
        fprintf(stderr, "Failed to create /var/log/puretime: %s\n", strerror(errno));
        return -1;
    }

    /* Generate filename with timestamp */
    time(&now);
    tm_info = localtime(&now);
    strftime(filename, sizeof(filename),
             "/var/log/puretime/trace_%Y%m%d_%H%M%S.jsonl", tm_info);

    strncpy(env.output_path, filename, sizeof(env.output_path) - 1);
    env.output_path[sizeof(env.output_path) - 1] = '\0';

    return 0;
}

int main(int argc, char **argv)
{
    struct ring_buffer *rb = NULL;
    struct puretime_bpf *skel = NULL;
    struct json_writer *jw = NULL;
    time_t start_time;
    int err;

    /* Parse command line arguments */
    err = argp_parse(&argp, argc, argv, 0, NULL, NULL);
    if (err)
        return err;

    /* Set up libbpf errors and debug info callback */
    libbpf_set_print(libbpf_print_fn);

    /* Setup output file */
    err = setup_output_file();
    if (err) {
        fprintf(stderr, "Failed to setup output file\n");
        return 1;
    }

    /* Initialize JSON writer with batching (4KB buffer) */
    jw = json_writer_create(env.output_path, 4096);
    if (!jw) {
        fprintf(stderr, "Failed to create JSON writer for %s: %s\n",
                env.output_path, strerror(errno));
        return 1;
    }

    /* Setup signal handlers */
    signal(SIGINT, sig_handler);
    signal(SIGTERM, sig_handler);

    /* Open BPF skeleton */
    skel = puretime_bpf__open();
    if (!skel) {
        fprintf(stderr, "Failed to open BPF skeleton\n");
        err = 1;
        goto cleanup;
    }

    /* Load & verify BPF programs */
    err = puretime_bpf__load(skel);
    if (err) {
        fprintf(stderr, "Failed to load BPF skeleton: %d\n", err);
        goto cleanup;
    }

    /* Attach tracepoints */
    err = puretime_bpf__attach(skel);
    if (err) {
        fprintf(stderr, "Failed to attach BPF skeleton: %d\n", err);
        goto cleanup;
    }

    /* Set up ring buffer polling */
    rb = ring_buffer__new(bpf_map__fd(skel->maps.events), handle_event, jw, NULL);
    if (!rb) {
        err = -1;
        fprintf(stderr, "Failed to create ring buffer\n");
        goto cleanup;
    }

    if (env.verbose) {
        printf("PureTime tracer started\n");
        printf("Output: %s\n", env.output_path);
        if (env.duration_sec > 0)
            printf("Duration: %d seconds\n", env.duration_sec);
        else
            printf("Press Ctrl+C to stop\n");
        printf("Tracing...\n");
    }

    /* Record start time for duration check */
    start_time = time(NULL);

    /* Event processing loop */
    while (!exiting) {
        err = ring_buffer__poll(rb, 100 /* timeout, ms */);

        /* Check duration */
        if (env.duration_sec > 0 &&
            (time(NULL) - start_time) >= env.duration_sec) {
            if (env.verbose)
                printf("Duration reached, stopping...\n");
            break;
        }

        /* Ctrl-C will cause -EINTR */
        if (err == -EINTR) {
            err = 0;
            break;
        }
        if (err < 0) {
            fprintf(stderr, "Error polling ring buffer: %d\n", err);
            break;
        }
    }

    if (env.verbose)
        printf("Shutting down...\n");

cleanup:
    /* Flush remaining buffered data */
    if (jw) {
        json_writer_flush(jw);
        json_writer_destroy(jw);
    }

    ring_buffer__free(rb);
    puretime_bpf__destroy(skel);

    if (env.verbose && err >= 0)
        printf("Output saved to %s\n", env.output_path);

    return err < 0 ? -err : 0;
}
