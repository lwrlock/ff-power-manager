#ifndef _GNU_SOURCE
#define _GNU_SOURCE
#endif
#include <stdio.h>
#include <stdlib.h>
#include <stdint.h>
#include <stdbool.h>
#include <string.h>
#include <assert.h>
#include <unistd.h>

#include "sensor_asm.h"

static void test_asm_decode_report(void) {
    printf("[TEST] Testing asm_decode_report with ST VL53L1 mm layout...\n");

    /* 1. NULL pointer check */
    int res = asm_decode_report(NULL, 35, NULL, NULL, 1200);
    assert(res == -1);

    /* 2. Short packet check (< 33 bytes) */
    uint8_t short_buf[30] = {4};
    res = asm_decode_report(short_buf, 30, NULL, NULL, 1200);
    assert(res == -1);

    /* 3. Wrong Report ID */
    uint8_t wrong_id[35];
    memset(wrong_id, 0, sizeof(wrong_id));
    wrong_id[0] = 3;
    res = asm_decode_report(wrong_id, sizeof(wrong_id), NULL, NULL, 1200);
    assert(res == -2);

    /* 4. Valid Report 4, dist = 750 mm (75 cm), presence flag = 1 -> Present! */
    uint8_t buf_desk[35];
    memset(buf_desk, 0, sizeof(buf_desk));
    buf_desk[0] = 4;
    uint16_t dist750 = 750;
    memcpy(&buf_desk[27], &dist750, 2);
    buf_desk[31] = 100; /* 100% confidence */
    buf_desk[32] = 1;   /* presence = 1 */

    int32_t pres_flag = -1;
    uint16_t dist_out = 0;
    res = asm_decode_report(buf_desk, sizeof(buf_desk), &pres_flag, &dist_out, 1200);
    assert(res == 1);
    assert(pres_flag == 1);
    assert(dist_out == 750);

    /* 5. User stepped away: dist = 1500 mm (1.5m > 1.2m threshold) -> Absent! */
    uint8_t buf_away[35];
    memset(buf_away, 0, sizeof(buf_away));
    buf_away[0] = 4;
    uint16_t dist1500 = 1500;
    memcpy(&buf_away[27], &dist1500, 2);
    buf_away[31] = 50;
    buf_away[32] = 1;

    res = asm_decode_report(buf_away, sizeof(buf_away), &pres_flag, &dist_out, 1200);
    assert(res == 0);
    assert(pres_flag == 1);
    assert(dist_out == 1500);

    /* 6. Explicit absence (presence flag = 0) -> Absent! */
    uint8_t buf_none[35];
    memset(buf_none, 0, sizeof(buf_none));
    buf_none[0] = 4;
    buf_none[32] = 0;

    res = asm_decode_report(buf_none, sizeof(buf_none), &pres_flag, &dist_out, 1200);
    assert(res == 0);
    assert(pres_flag == 0);

    printf("[PASS] asm_decode_report passed all 6 test cases!\n");
}

static void test_asm_atomic_write(void) {
    printf("[TEST] Testing asm_atomic_write_file...\n");
    const char *tmp = "/tmp/test_asm_atomic.tmp";
    const char *final = "/tmp/test_asm_atomic.txt";
    const char *data = "ANTIGRAVITY_PRESENCE_TEST_OK\n";
    asm_atomic_write_file(tmp, final, data, strlen(data));

    FILE *f = fopen(final, "r");
    assert(f != NULL);
    char buf[64];
    size_t n = fread(buf, 1, sizeof(buf) - 1, f);
    fclose(f);
    buf[n] = '\0';
    assert(strcmp(buf, data) == 0);
    unlink(final);
    printf("[PASS] asm_atomic_write_file passed!\n");
}

static void test_asm_fast_read_sysfs(void) {
    printf("[TEST] Testing asm_fast_read_sysfs_int...\n");
    const char *test_path = "/tmp/test_asm_int.txt";
    FILE *f = fopen(test_path, "w");
    fprintf(f, "  123456\n");
    fclose(f);

    int64_t val = asm_fast_read_sysfs_int(test_path);
    assert(val == 123456);
    unlink(test_path);
    printf("[PASS] asm_fast_read_sysfs_int passed!\n");
}

int main(void) {
    printf("=========================================\n");
    printf(" Running Native C & Assembly Test Suite  \n");
    printf("=========================================\n");
    test_asm_decode_report();
    test_asm_atomic_write();
    test_asm_fast_read_sysfs();
    printf("=========================================\n");
    printf(" ALL NATIVE UNIT TESTS PASSED (100%%%%)    \n");
    printf("=========================================\n");
    return 0;
}
