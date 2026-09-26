#ifndef SENSOR_ASM_H
#define SENSOR_ASM_H

#include <stddef.h>
#include <stdint.h>

#ifdef __cplusplus
extern "C" {
#endif

/**
 * Fast x86_64 assembly routine to parse Intel ISH / ST VL53L1 Report 4.
 *
 * @param data           Pointer to raw HID report bytes
 * @param len            Length of data buffer
 * @param presence_out   Pointer to store raw int32 presence field (or NULL)
 * @param dist_out       Pointer to store raw uint8 distance field (or NULL)
 * @param dist_thresh    Distance threshold in decimeters (e.g., 24 for 2.4m)
 *
 * @return 1 if present (within range), 0 if absent, -1 if invalid, -2 if not report 4
 */
int asm_decode_report(const uint8_t *data, size_t len,
                      int32_t *presence_out, uint8_t *dist_out,
                      int32_t dist_thresh);

/**
 * Fast x86_64 assembly routine to read an integer from a sysfs file
 * using direct Linux syscalls (open, read, close) with zero libc overhead.
 */
int64_t asm_fast_read_sysfs_int(const char *path);

/**
 * Fast x86_64 assembly routine to atomically write content to tmp_path and rename.
 */
void asm_atomic_write_file(const char *tmp_path, const char *final_path,
                           const char *content, size_t len);

#ifdef __cplusplus
}
#endif

#endif /* SENSOR_ASM_H */
