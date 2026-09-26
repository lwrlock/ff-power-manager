/*
 * test_native.c - Rigorous Unit Tests for C & x86_64 Assembly Core
 */

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
    printf("[TEST] Testing asm_decode_report...\n");

    /* Test 1: NULL pointer */
    assert(asm_decode_report(NULL, 35, NULL, NULL, 24) == -1);

    /* Test 2: Length too short (< 31) */
    uint8_t short_buf[20] = {0};
    short_buf[0] = 4;
    assert(asm_decode_report(short_buf, 20, NULL, NULL, 24) == -1);

    /* Test 3: Not Report ID 4 */
    uint8_t wrong_id[35] = {0};
    wrong_id[0] = 2; /* Report ID 2 */
    assert(asm_decode_report(wrong_id, 35, NULL, NULL, 24) == -2);

    /* Test 4: Report ID 4, Presence = 1, Dist = 8 (0.8m <= 1.2m threshold) */
    uint8_t buf_pres[35] = {0};
    buf_pres[0] = 4;
    int32_t val_pres = 1;
    memcpy(&buf_pres[27], &val_pres, sizeof(int32_t));
    buf_pres[32] = 8;

    int32_t out_pres = 0;
    uint8_t out_dist = 0;
    int res = asm_decode_report(buf_pres, 35, &out_pres, &out_dist, 12);
    assert(res == 1);
    assert(out_pres == 1);
    assert(out_dist == 8);

    /* Test 5: Report ID 4, Presence = 0 (Explicit Absence) */
    uint8_t buf_abs[35] = {0};
    buf_abs[0] = 4;
    int32_t val_abs = 0;
    memcpy(&buf_abs[27], &val_abs, sizeof(int32_t));
    buf_abs[32] = 10;

    res = asm_decode_report(buf_abs, 35, &out_pres, &out_dist, 12);
    assert(res == 0);
    assert(out_pres == 0);
    assert(out_dist == 10);

    /* Test 6: Distance exceeds threshold (e.g., 16 dm = 1.6m > 12 = 1.2m) */
    uint8_t buf_far[35] = {0};
    buf_far[0] = 4;
    val_pres = 1;
    memcpy(&buf_far[27], &val_pres, sizeof(int32_t));
    buf_far[32] = 16; /* 1.6 meters */

    res = asm_decode_report(buf_far, 35, &out_pres, &out_dist, 12);
    assert(res == 0); /* User is beyond 1.2m threshold! */

    printf("[PASS] asm_decode_report passed all 6 test cases!\n");
}

static void test_asm_atomic_write(void) {
    printf("[TEST] Testing asm_atomic_write_file...\n");
    const char *tmp = "/tmp/test_fpm_state.tmp";
    const char *final = "/tmp/test_fpm_state.txt";
    const char *data = "present\n";

    asm_atomic_write_file(tmp, final, data, strlen(data));

    FILE *f = fopen(final, "r");
    assert(f != NULL);
    char buf[64] = {0};
    size_t n = fread(buf, 1, sizeof(buf) - 1, f);
    fclose(f);
    unlink(final);

    assert(n == strlen(data));
    assert(strcmp(buf, data) == 0);
    printf("[PASS] asm_atomic_write_file passed!\n");
}

static void test_asm_sysfs_read(void) {
    printf("[TEST] Testing asm_fast_read_sysfs_int...\n");
    const char *test_path = "/tmp/test_sysfs_num.txt";
    FILE *f = fopen(test_path, "w");
    assert(f != NULL);
    fprintf(f, " 42 \n");
    fclose(f);

    int64_t val = asm_fast_read_sysfs_int(test_path);
    unlink(test_path);
    assert(val == 42);

    /* Test non-existent file */
    assert(asm_fast_read_sysfs_int("/tmp/definitely_not_a_file_12345.txt") == -1);

    printf("[PASS] asm_fast_read_sysfs_int passed!\n");
}

int main(void) {
    printf("=========================================\n");
    printf(" Running Native C & Assembly Test Suite  \n");
    printf("=========================================\n");
    test_asm_decode_report();
    test_asm_atomic_write();
    test_asm_sysfs_read();
    printf("=========================================\n");
    printf(" ALL NATIVE UNIT TESTS PASSED (100%%)    \n");
    printf("=========================================\n");
    return 0;
}
