// SPDX-License-Identifier: (LGPL-2.1 OR BSD-2-Clause)
#ifndef __JSON_WRITER_H
#define __JSON_WRITER_H

#include <stdint.h>
#include <stddef.h>

struct json_writer;

/* Create a JSON writer with buffered output */
struct json_writer *json_writer_create(const char *filename, size_t buffer_size);

/* Destroy and close the writer */
void json_writer_destroy(struct json_writer *jw);

/* Flush buffer to file */
int json_writer_flush(struct json_writer *jw);

/* JSON object construction */
void json_writer_start_object(struct json_writer *jw);
void json_writer_end_object(struct json_writer *jw);

/* Add fields to current object */
void json_writer_add_string(struct json_writer *jw, const char *key, const char *value);
void json_writer_add_int32(struct json_writer *jw, const char *key, int32_t value);
void json_writer_add_uint32(struct json_writer *jw, const char *key, uint32_t value);
void json_writer_add_uint64(struct json_writer *jw, const char *key, uint64_t value);
void json_writer_add_int64(struct json_writer *jw, const char *key, int64_t value);

#endif /* __JSON_WRITER_H */
