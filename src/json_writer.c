// SPDX-License-Identifier: (LGPL-2.1 OR BSD-2-Clause)
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <inttypes.h>
#include "json_writer.h"

struct json_writer {
    FILE *fp;
    char *buffer;
    size_t buffer_size;
    size_t buffer_pos;
    int field_count;  /* Track fields in current object */
};

struct json_writer *json_writer_create(const char *filename, size_t buffer_size)
{
    struct json_writer *jw = calloc(1, sizeof(*jw));
    if (!jw)
        return NULL;

    jw->fp = fopen(filename, "w");
    if (!jw->fp) {
        free(jw);
        return NULL;
    }

    jw->buffer = malloc(buffer_size);
    if (!jw->buffer) {
        fclose(jw->fp);
        free(jw);
        return NULL;
    }

    jw->buffer_size = buffer_size;
    jw->buffer_pos = 0;
    jw->field_count = 0;

    return jw;
}

void json_writer_destroy(struct json_writer *jw)
{
    if (!jw)
        return;

    json_writer_flush(jw);
    fclose(jw->fp);
    free(jw->buffer);
    free(jw);
}

int json_writer_flush(struct json_writer *jw)
{
    if (!jw || jw->buffer_pos == 0)
        return 0;

    size_t written = fwrite(jw->buffer, 1, jw->buffer_pos, jw->fp);
    if (written != jw->buffer_pos)
        return -1;
    jw->buffer_pos = 0;
    fflush(jw->fp);
    return 0;
}

static void jw_write(struct json_writer *jw, const char *data, size_t len)
{
    /* Check if we need to flush */
    if (jw->buffer_pos + len >= jw->buffer_size) {
        json_writer_flush(jw);
    }

    /* If data is larger than buffer, write directly */
    if (len >= jw->buffer_size) {
        fwrite(data, 1, len, jw->fp);
        return;
    }

    memcpy(jw->buffer + jw->buffer_pos, data, len);
    jw->buffer_pos += len;
}

void json_writer_start_object(struct json_writer *jw)
{
    jw_write(jw, "{", 1);
    jw->field_count = 0;
}

void json_writer_end_object(struct json_writer *jw)
{
    jw_write(jw, "}\n", 2);  /* Newline for JSON Lines format */
}

/* Escape special characters in JSON string */
static void jw_write_escaped_string(struct json_writer *jw, const char *str)
{
    char buf[8];
    const char *p = str;

    jw_write(jw, "\"", 1);
    while (*p) {
        switch (*p) {
        case '"':
            jw_write(jw, "\\\"", 2);
            break;
        case '\\':
            jw_write(jw, "\\\\", 2);
            break;
        case '\n':
            jw_write(jw, "\\n", 2);
            break;
        case '\r':
            jw_write(jw, "\\r", 2);
            break;
        case '\t':
            jw_write(jw, "\\t", 2);
            break;
        default:
            if ((unsigned char)*p < 32) {
                snprintf(buf, sizeof(buf), "\\u%04x", (unsigned char)*p);
                jw_write(jw, buf, 6);
            } else {
                jw_write(jw, p, 1);
            }
            break;
        }
        p++;
    }
    jw_write(jw, "\"", 1);
}

void json_writer_add_string(struct json_writer *jw, const char *key, const char *value)
{
    if (jw->field_count > 0)
        jw_write(jw, ",", 1);

    jw_write(jw, "\"", 1);
    jw_write(jw, key, strlen(key));
    jw_write(jw, "\":", 2);

    if (value) {
        jw_write_escaped_string(jw, value);
    } else {
        jw_write(jw, "\"\"", 2);
    }

    jw->field_count++;
}

void json_writer_add_int32(struct json_writer *jw, const char *key, int32_t value)
{
    char buf[64];
    int len;

    if (jw->field_count > 0)
        jw_write(jw, ",", 1);

    len = snprintf(buf, sizeof(buf), "\"%s\":%" PRId32, key, value);
    jw_write(jw, buf, len);
    jw->field_count++;
}

void json_writer_add_uint32(struct json_writer *jw, const char *key, uint32_t value)
{
    char buf[64];
    int len;

    if (jw->field_count > 0)
        jw_write(jw, ",", 1);

    len = snprintf(buf, sizeof(buf), "\"%s\":%" PRIu32, key, value);
    jw_write(jw, buf, len);
    jw->field_count++;
}

void json_writer_add_uint64(struct json_writer *jw, const char *key, uint64_t value)
{
    char buf[64];
    int len;

    if (jw->field_count > 0)
        jw_write(jw, ",", 1);

    len = snprintf(buf, sizeof(buf), "\"%s\":%" PRIu64, key, value);
    jw_write(jw, buf, len);
    jw->field_count++;
}

void json_writer_add_int64(struct json_writer *jw, const char *key, int64_t value)
{
    char buf[64];
    int len;

    if (jw->field_count > 0)
        jw_write(jw, ",", 1);

    len = snprintf(buf, sizeof(buf), "\"%s\":%" PRId64, key, value);
    jw_write(jw, buf, len);
    jw->field_count++;
}
