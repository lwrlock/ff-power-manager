/*
 * sensor_asm.s - High-Performance x86_64 Assembly Core for FF Power Manager
 * Handcrafted assembly routines for ST VL53L1 HID Report 4 parsing,
 * direct Linux syscalls, and low-latency sysfs operations.
 *
 * ST VL53L1 / Intel ISH Report 4 Layout (Len=35 bytes):
 *   Offset 00     : Report ID (0x04)
 *   Offset 27..28 : Distance in millimeters (uint16_t little-endian)
 *   Offset 31     : Signal Confidence / Quality percentage (0..100%)
 *   Offset 32     : Presence Flag (uint8_t: 1 = detected, 0 = absent)
 *
 * ABI: System V AMD64 ABI
 * Registers: rdi (arg1), rsi (arg2), rdx (arg3), rcx (arg4), r8 (arg5)
 * Return: rax / eax
 */

.text
.global asm_decode_report
.type asm_decode_report, @function

/*
 * int asm_decode_report(const uint8_t *data, size_t len,
 *                       int32_t *presence_out, uint16_t *dist_mm_out,
 *                       int32_t dist_thresh_mm)
 *
 * Arguments:
 *   rdi: data pointer
 *   rsi: length of data buffer (must be >= 33)
 *   rdx: pointer to store raw presence flag (int32_t*) or NULL
 *   rcx: pointer to store raw distance in mm (uint16_t*) or NULL
 *   r8d: distance threshold in mm (e.g. 1200 for 1.2m desk range)
 *
 * Returns:
 *   1  : User Present (Presence==1 and dist_mm <= threshold)
 *   0  : User Absent (Presence==0 or dist_mm > threshold)
 *  -1  : Invalid packet / too short (< 33 bytes)
 *  -2  : Not Report ID 4
 */
asm_decode_report:
    /* Check NULL pointer */
    testq   %rdi, %rdi
    jz      .L_err_invalid

    /* Check minimum report length (at least 33 bytes) */
    cmpq    $33, %rsi
    jb      .L_err_invalid

    /* Check Report ID == 4 */
    cmpb    $4, (%rdi)
    jne     .L_err_not_report4

    /* Extract 16-bit little-endian distance in mm at offset 27 */
    movzwl  27(%rdi), %eax

    /* Store distance in mm if pointer provided */
    testq   %rcx, %rcx
    jz      .L_check_presence_flag
    movw    %ax, (%rcx)

.L_check_presence_flag:
    /* Extract presence byte at offset 32 */
    movzbl  32(%rdi), %r9d

    /* Store presence if pointer provided */
    testq   %rdx, %rdx
    jz      .L_decide
    movl    %r9d, (%rdx)

.L_decide:
    /* If distance threshold is <= 0, default to 1200 mm (1.2 meters) */
    testl   %r8d, %r8d
    jg      .L_thresh_ok
    movl    $1200, %r8d

.L_thresh_ok:
    /* If presence flag is 0, user is absent */
    testl   %r9d, %r9d
    jz      .L_return_absent

    /* If presence flag is 1, check distance against threshold */
    /* If dist_mm > 0 and dist_mm > threshold -> away/absent */
    testl   %eax, %eax
    jz      .L_return_present
    cmpl    %r8d, %eax
    ja      .L_return_absent

.L_return_present:
    movl    $1, %eax
    ret

.L_return_absent:
    xorl    %eax, %eax
    ret

.L_err_invalid:
    movl    $-1, %eax
    ret

.L_err_not_report4:
    movl    $-2, %eax
    ret

.size asm_decode_report, .-asm_decode_report


/*
 * int64_t asm_fast_read_sysfs_int(const char *path)
 *
 * Reads a single integer from a sysfs file using raw Linux syscalls
 * (sys_open, sys_read, sys_close) with zero libc buffer overhead.
 */
.global asm_fast_read_sysfs_int
.type asm_fast_read_sysfs_int, @function
asm_fast_read_sysfs_int:
    pushq   %rbp
    movq    %rsp, %rbp
    subq    $64, %rsp               /* 64 bytes local buffer */

    /* sys_open(path, O_RDONLY=0, 0) */
    movl    $2, %eax                /* SYS_open */
    xorl    %esi, %esi              /* O_RDONLY */
    xorl    %edx, %edx
    syscall

    testl   %eax, %eax
    js      .L_read_fail
    movl    %eax, %r8d              /* r8d = fd */

    /* sys_read(fd, buf, 63) */
    xorl    %eax, %eax              /* SYS_read = 0 */
    movl    %r8d, %edi
    leaq    -64(%rbp), %rsi
    movl    $63, %edx
    syscall

    testq   %rax, %rax
    jle     .L_close_and_fail
    movq    %rax, %r9               /* bytes read */

    /* sys_close(fd) */
    movl    $3, %eax                /* SYS_close */
    movl    %r8d, %edi
    syscall

    /* Null terminate buffer */
    leaq    -64(%rbp), %rsi
    movb    $0, (%rsi, %r9)

    /* Parse integer in %rsi: skip whitespace, parse digits */
    xorq    %rax, %rax              /* accumulator */
    xorl    %ecx, %ecx              /* sign flag: 0=pos, 1=neg */

.L_skip_ws:
    movzbl  (%rsi), %edx
    testb   %dl, %dl
    jz      .L_parse_done
    cmpb    $' ', %dl
    je      .L_next_ws
    cmpb    $'\t', %dl
    je      .L_next_ws
    cmpb    $'\n', %dl
    je      .L_next_ws
    cmpb    $'\r', %dl
    je      .L_next_ws
    jmp     .L_check_sign

.L_next_ws:
    incq    %rsi
    jmp     .L_skip_ws

.L_check_sign:
    cmpb    $'-', %dl
    jne     .L_digits_loop
    movl    $1, %ecx
    incq    %rsi

.L_digits_loop:
    movzbl  (%rsi), %edx
    subb    $'0', %dl
    cmpb    $9, %dl
    ja      .L_parse_finish

    imulq   $10, %rax, %rax
    movzbl  %dl, %edx
    addq    %rdx, %rax
    incq    %rsi
    jmp     .L_digits_loop

.L_parse_finish:
    testl   %ecx, %ecx
    jz      .L_parse_done
    negq    %rax

.L_parse_done:
    leave
    ret

.L_close_and_fail:
    movl    $3, %eax                /* SYS_close */
    movl    %r8d, %edi
    syscall

.L_read_fail:
    movq    $-1, %rax
    leave
    ret

.size asm_fast_read_sysfs_int, .-asm_fast_read_sysfs_int

/*
 * void asm_atomic_write_file(const char *tmp_path, const char *final_path,
 *                            const char *content, size_t len)
 */
.global asm_atomic_write_file
.type asm_atomic_write_file, @function
asm_atomic_write_file:
    pushq   %rbp
    movq    %rsp, %rbp
    pushq   %r12
    pushq   %r13
    pushq   %r14
    pushq   %r15

    movq    %rdi, %r12              /* tmp_path */
    movq    %rsi, %r13              /* final_path */
    movq    %rdx, %r14              /* content */
    movq    %rcx, %r15              /* len */

    /* SYS_open(tmp_path, O_WRONLY|O_CREAT|O_TRUNC = 01101, 0644 = 0x1a4) */
    movl    $2, %eax
    movq    %r12, %rdi
    movl    $01101, %esi
    movl    $0644, %edx
    syscall

    testl   %eax, %eax
    js      .L_atomic_done
    movl    %eax, %r8d              /* fd in r8d */

    /* SYS_write(fd, content, len) */
    movl    $1, %eax
    movl    %r8d, %edi
    movq    %r14, %rsi
    movq    %r15, %rdx
    syscall

    /* SYS_close(fd) */
    movl    $3, %eax
    movl    %r8d, %edi
    syscall

    /* SYS_rename(tmp_path, final_path) */
    movl    $82, %eax               /* SYS_rename */
    movq    %r12, %rdi
    movq    %r13, %rsi
    syscall

.L_atomic_done:
    popq    %r15
    popq    %r14
    popq    %r13
    popq    %r12
    leave
    ret

.size asm_atomic_write_file, .-asm_atomic_write_file
