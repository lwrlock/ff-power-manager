/*
 * sensor_asm.h - C Interface to Handcrafted x86_64 Assembly Core
 */

#ifndef SENSOR_ASM_H
#define SENSOR_ASM_H

#include <stdint.h>
#include <stddef.h>

#ifdef __cplusplus
extern "C" {
#endif

/*
 * Decode ST VL53L1 / Intel ISH HID Report 4 using optimized x86_64 assembly.
 *
 * Arguments:
 *   data:           Pointer to raw HID input buffer
 *   len:            Length of data buffer (must be >= 33)
 *   presence_out:   Stores raw presence flag (1=present, 0=absent) or NULL
 *   dist_mm_out:    Stores raw measured distance in mm (uint16_t) or NULL
 *   dist_thresh_mm: Distance threshold in millimeters (e.g., 1200 for 1.2m desk range)
 *
 * Returns:
 *   1  : User Present (presence==1 and dist_mm <= threshold)
 *   0  : User Absent (presence==0 or dist_mm > threshold)
 *  -1  : Invalid packet / buffer too short (< 33 bytes)
 *  -2  : Not Report ID 4
 */
int asm_decode_report(const uint8_t *data, size_t len,
                      int32_t *presence_out, uint16_t *dist_mm_out,
                      int32_t dist_thresh_mm);

int64_t asm_fast_read_sysfs_int(const char *path);

void asm_atomic_write_file(const char *tmp_path, const char *final_path,
                           const char *content, size_t len);

#ifdef __cplusplus
}
#endif

#endif /* SENSOR_ASM_H */
