/*
 * sensor_native.c - High-Performance Native Linux Daemon for Lenovo ToF Sensor
 * Links with sensor_asm.s for x86_64 assembly acceleration.
 *
 * Implements direct HID raw ioctl feature management, zero-copy packet reading,
 * sub-millisecond presence detection with 2.4m distance threshold, and instant wake.
 */

#ifndef _GNU_SOURCE
#define _GNU_SOURCE
#endif
#include <stdio.h>
#include <stdlib.h>
#include <stdint.h>
#include <stdbool.h>
#include <string.h>
#include <unistd.h>
#include <fcntl.h>
#include <errno.h>
#include <signal.h>
#include <time.h>
#include <dirent.h>
#include <sys/ioctl.h>
#include <sys/stat.h>
#include <sys/select.h>
#include <linux/hidraw.h>

#include "sensor_asm.h"

#define REPORT_ID           4
#define FEATURE_BUF_LEN     256
#define TARGET_HID_ID       "HID_ID=001F:00008087:00000AC2"
#define RUN_DIR             "/run/ff-power-manager"
#define STATE_FILE          "/run/ff-power-manager/presence.state"
#define TMP_STATE_FILE      "/run/ff-power-manager/.presence.state.tmp"
#define TELEMETRY_FILE      "/run/ff-power-manager/sensor_telemetry.json"
#define TMP_TELEMETRY_FILE  "/run/ff-power-manager/.sensor_telemetry.tmp"
#define SENSOR_CONFIG_PATH  "/etc/ff-power-manager/sensor.json"

static volatile sig_atomic_t g_running = 1;

static void handle_signal(int sig) {
    (void)sig;
    g_running = 0;
}

static double get_monotonic_time(void) {
    struct timespec ts;
    clock_gettime(CLOCK_MONOTONIC, &ts);
    return (double)ts.tv_sec + (double)ts.tv_nsec / 1e9;
}

static void publish_state(const char *state) {
    mkdir(RUN_DIR, 0755);
    size_t len = strlen(state);
    char buf[64];
    if (len + 2 < sizeof(buf)) {
        memcpy(buf, state, len);
        buf[len] = '\n';
        buf[len + 1] = '\0';
        asm_atomic_write_file(TMP_STATE_FILE, STATE_FILE, buf, len + 1);
    }
    printf("FPM native sensor: %s\n", state);
    fflush(stdout);
}

static void publish_telemetry(const char *state, int distance_cm, int threshold_cm,
                              uint64_t packet_count, double last_sec_ago, const char *device) {
    mkdir(RUN_DIR, 0755);
    char json[512];
    int n = snprintf(json, sizeof(json),
        "{\n"
        "  \"state\": \"%s\",\n"
        "  \"distance_cm\": %d,\n"
        "  \"threshold_cm\": %d,\n"
        "  \"packet_count\": %llu,\n"
        "  \"last_packet_sec_ago\": %.2f,\n"
        "  \"device\": \"%s\",\n"
        "  \"active\": %s\n"
        "}\n",
        state, distance_cm, threshold_cm, (unsigned long long)packet_count,
        last_sec_ago, device ? device : "unknown",
        (strcmp(state, "disabled") != 0 && strcmp(state, "error") != 0) ? "true" : "false");
    if (n > 0 && n < (int)sizeof(json)) {
        asm_atomic_write_file(TMP_TELEMETRY_FILE, TELEMETRY_FILE, json, (size_t)n);
    }
}

static char *locate_hidraw_device(void) {
    static char path[512];
    DIR *d = opendir("/sys/bus/hid/devices");
    if (!d) return NULL;

    struct dirent *entry;
    while ((entry = readdir(d)) != NULL) {
        if (entry->d_name[0] == '.') continue;

        char uevent_path[512];
        snprintf(uevent_path, sizeof(uevent_path), "/sys/bus/hid/devices/%s/uevent", entry->d_name);
        FILE *f = fopen(uevent_path, "r");
        if (!f) continue;

        char line[256];
        bool found = false;
        while (fgets(line, sizeof(line), f)) {
            if (strstr(line, TARGET_HID_ID)) {
                found = true;
                break;
            }
        }
        fclose(f);

        if (found) {
            char hidraw_dir[512];
            snprintf(hidraw_dir, sizeof(hidraw_dir), "/sys/bus/hid/devices/%s/hidraw", entry->d_name);
            DIR *hd = opendir(hidraw_dir);
            if (hd) {
                struct dirent *he;
                while ((he = readdir(hd)) != NULL) {
                    if (strncmp(he->d_name, "hidraw", 6) == 0) {
                        snprintf(path, sizeof(path), "/dev/%s", he->d_name);
                        closedir(hd);
                        closedir(d);
                        return path;
                    }
                }
                closedir(hd);
            }
        }
    }
    closedir(d);
    return NULL;
}

static bool enable_sensor(int fd, uint8_t *original_buf) {
    uint8_t buf[FEATURE_BUF_LEN];
    memset(buf, 0, sizeof(buf));
    buf[0] = REPORT_ID;

    if (ioctl(fd, HIDIOCGFEATURE(FEATURE_BUF_LEN), buf) < 0) {
        perror("HIDIOCGFEATURE failed");
        return false;
    }

    if (buf[0] != REPORT_ID) {
        fprintf(stderr, "Invalid report ID returned: %d\n", buf[0]);
        return false;
    }

    memcpy(original_buf, buf, FEATURE_BUF_LEN);

    /* Modify feature report: ALL_EVENTS (2) and D0_FULL_POWER (2) */
    buf[1] = 2; /* All events */
    buf[4] = 2; /* D0 full power */

    if (ioctl(fd, HIDIOCSFEATURE(FEATURE_BUF_LEN), buf) < 0) {
        perror("HIDIOCSFEATURE failed");
        return false;
    }

    /* Verify configuration was applied */
    uint8_t verify[FEATURE_BUF_LEN];
    memset(verify, 0, sizeof(verify));
    verify[0] = REPORT_ID;
    if (ioctl(fd, HIDIOCGFEATURE(FEATURE_BUF_LEN), verify) >= 0) {
        if (verify[1] != 2 || verify[4] != 2) {
            fprintf(stderr, "Warning: Firmware did not retain D0/ALL_EVENTS state\n");
        }
    }
    return true;
}

static void disable_sensor(int fd, const uint8_t *original_buf) {
    uint8_t buf[FEATURE_BUF_LEN];
    if (original_buf) {
        memcpy(buf, original_buf, FEATURE_BUF_LEN);
    } else {
        memset(buf, 0, sizeof(buf));
        buf[0] = REPORT_ID;
        if (ioctl(fd, HIDIOCGFEATURE(FEATURE_BUF_LEN), buf) >= 0) {
            buf[1] = 1; /* NO_EVENTS */
            buf[4] = 6; /* D4_POWER_OFF */
        }
    }
    ioctl(fd, HIDIOCSFEATURE(FEATURE_BUF_LEN), buf);
}

typedef struct {
    double silence_timeout;
    int present_confirm_reports;
    double present_confirm_window;
    int distance_threshold;
} SensorConfig;

static void load_config(SensorConfig *cfg) {
    cfg->silence_timeout = 30.0;
    cfg->present_confirm_reports = 1;
    cfg->present_confirm_window = 6.0;
    cfg->distance_threshold = 12; /* 1.2 meters (Normal desk range) */

    FILE *f = fopen(SENSOR_CONFIG_PATH, "r");
    if (!f) return;

    char buf[1024];
    size_t n = fread(buf, 1, sizeof(buf) - 1, f);
    fclose(f);
    buf[n] = '\0';

    char *p = strstr(buf, "\"silence_timeout\"");
    if (p) {
        double val = 0.0;
        if (sscanf(p, "\"silence_timeout\"%*[^0-9]%lf", &val) == 1 && val >= 5.0 && val <= 120.0) {
            cfg->silence_timeout = val;
        }
    }

    p = strstr(buf, "\"present_confirm_reports\"");
    if (p) {
        int val = 0;
        if (sscanf(p, "\"present_confirm_reports\"%*[^0-9]%d", &val) == 1 && val >= 1 && val <= 5) {
            cfg->present_confirm_reports = val;
        }
    }

    p = strstr(buf, "\"present_confirm_window\"");
    if (p) {
        double val = 0.0;
        if (sscanf(p, "\"present_confirm_window\"%*[^0-9]%lf", &val) == 1 && val >= 1.0 && val <= 20.0) {
            cfg->present_confirm_window = val;
        }
    }

    p = strstr(buf, "\"distance_threshold\"");
    if (p) {
        int val = 0;
        if (sscanf(p, "\"distance_threshold\"%*[^0-9]%d", &val) == 1 && val >= 5 && val <= 50) {
            cfg->distance_threshold = val;
        }
    }
}

static int inspect_mode(const char *dev_path, double duration_sec) {
    int fd = open(dev_path, O_RDWR | O_NONBLOCK);
    if (fd < 0) {
        perror("Failed to open device");
        return 1;
    }

    uint8_t orig[FEATURE_BUF_LEN];
    if (!enable_sensor(fd, orig)) {
        close(fd);
        return 1;
    }

    printf("Inspecting ToF reports on %s for %.1f seconds...\n", dev_path, duration_sec);
    double end_time = get_monotonic_time() + duration_sec;
    uint8_t read_buf[256];

    while (get_monotonic_time() < end_time && g_running) {
        fd_set fds;
        FD_ZERO(&fds);
        FD_SET(fd, &fds);
        struct timeval tv = { .tv_sec = 1, .tv_usec = 0 };

        int sel = select(fd + 1, &fds, NULL, NULL, &tv);
        if (sel <= 0) {
            printf("... silence ...\n");
            continue;
        }

        ssize_t n = read(fd, read_buf, sizeof(read_buf));
        if (n <= 0) continue;

        if (read_buf[0] == REPORT_ID) {
            int32_t pres_flag = 0;
            uint16_t dist_mm = 0;
            int res = asm_decode_report(read_buf, n, &pres_flag, &dist_mm, 1200);
            printf("Report 4 (len=%zd): PresenceFlag=%d Dist=%u mm (%.1f cm) -> Result=%s\n",
                   n, pres_flag, dist_mm, (double)dist_mm / 10.0,
                   (res == 1 ? "PRESENT" : (res == 0 ? "ABSENT" : "INVALID")));
        }
    }

    disable_sensor(fd, orig);
    close(fd);
    return 0;
}

int main(int argc, char *argv[]) {
    if (argc > 1 && strcmp(argv[1], "--help") == 0) {
        printf("Usage: ff-presence-sensor [OPTIONS]\n"
               "Lenovo ToF Human Presence Sensor Native Daemon (C / x86_64 ASM)\n\n"
               "Options:\n"
               "  --inspect [sec]    Inspect and print live sensor reports\n"
               "  --disable          Put sensor into low-power D4 off mode and exit\n"
               "  --help             Show this help message\n");
        return 0;
    }

    signal(SIGINT, handle_signal);
    signal(SIGTERM, handle_signal);
    signal(SIGHUP, handle_signal);

    char *dev_path = locate_hidraw_device();
    if (!dev_path) {
        fprintf(stderr, "Error: Intel ISH 8087:0AC2 hidraw device not found\n");
        publish_state("error");
        return 1;
    }

    if (argc > 1 && strcmp(argv[1], "--disable") == 0) {
        int fd = open(dev_path, O_RDWR);
        if (fd >= 0) {
            disable_sensor(fd, NULL);
            close(fd);
        }
        publish_state("disabled");
        return 0;
    }

    if (argc > 1 && strcmp(argv[1], "--inspect") == 0) {
        double sec = 10.0;
        if (argc > 2) sec = atof(argv[2]);
        return inspect_mode(dev_path, sec > 0 ? sec : 10.0);
    }

    SensorConfig cfg;
    load_config(&cfg);

    int fd = open(dev_path, O_RDWR | O_NONBLOCK);
    if (fd < 0) {
        perror("Failed to open hidraw device");
        publish_state("error");
        return 1;
    }

    uint8_t orig_features[FEATURE_BUF_LEN];
    if (!enable_sensor(fd, orig_features)) {
        close(fd);
        publish_state("error");
        return 1;
    }

    printf("FPM native sensor: active on %s (silence_floor=%.1fs, confirm=%d, dist_thresh=%dm)\n",
           dev_path, cfg.silence_timeout, cfg.present_confirm_reports, cfg.distance_threshold / 10);
    fflush(stdout);

    publish_state("unknown");

    const char *current_state = "unknown";
    double last_report_time = 0.0;
    double candidate_start = 0.0;
    int candidate_reports = 0;
    double initial_deadline = get_monotonic_time() + cfg.silence_timeout;
    uint64_t packet_count = 0;
    int current_distance_cm = 0;

    publish_telemetry(current_state, 0, cfg.distance_threshold * 10, 0, 0.0, dev_path);

    uint8_t read_buf[512];

    while (g_running) {
        double now = get_monotonic_time();
        double timeout_sec = 1.0;

        if (strcmp(current_state, "present") == 0 && last_report_time > 0.0) {
            timeout_sec = (last_report_time + cfg.silence_timeout) - now;
            if (timeout_sec < 0.0) timeout_sec = 0.0;
        } else if (candidate_reports > 0 && candidate_start > 0.0) {
            timeout_sec = (candidate_start + cfg.present_confirm_window) - now;
            if (timeout_sec < 0.0) timeout_sec = 0.0;
        } else if (strcmp(current_state, "unknown") == 0) {
            timeout_sec = initial_deadline - now;
            if (timeout_sec < 0.0) timeout_sec = 0.0;
        } else {
            timeout_sec = 2.0;
        }

        struct timeval tv;
        tv.tv_sec = (time_t)timeout_sec;
        tv.tv_usec = (suseconds_t)((timeout_sec - (double)tv.tv_sec) * 1e6);

        fd_set fds;
        FD_ZERO(&fds);
        FD_SET(fd, &fds);

        int ready = select(fd + 1, &fds, NULL, NULL, &tv);
        if (!g_running) break;

        now = get_monotonic_time();

        if (ready <= 0) {
            /* Timeout occurred: Silence check */
            if (strcmp(current_state, "present") == 0 && last_report_time > 0.0) {
                if (now >= last_report_time + cfg.silence_timeout) {
                    current_state = "absent";
                    candidate_start = 0.0;
                    candidate_reports = 0;
                    publish_state(current_state);
                    publish_telemetry(current_state, current_distance_cm, cfg.distance_threshold * 10, packet_count, now - last_report_time, dev_path);
                }
            } else if (candidate_reports > 0 && candidate_start > 0.0) {
                if (now > candidate_start + cfg.present_confirm_window) {
                    candidate_start = 0.0;
                    candidate_reports = 0;
                }
            } else if (strcmp(current_state, "unknown") == 0 && now >= initial_deadline) {
                current_state = "absent";
                publish_state(current_state);
                publish_telemetry(current_state, current_distance_cm, cfg.distance_threshold * 10, packet_count, now - last_report_time, dev_path);
            }
            continue;
        }

        ssize_t n = read(fd, read_buf, sizeof(read_buf));
        if (n < 0) {
            if (errno == EAGAIN || errno == EWOULDBLOCK) continue;
            if (errno == ENODEV || errno == EIO) {
                fprintf(stderr, "Sensor device disconnected\n");
                break;
            }
            continue;
        }

        if (n < 1 || read_buf[0] != REPORT_ID) {
            continue;
        }

        last_report_time = now;
        packet_count++;

        int32_t presence_flag = 0;
        uint16_t dist_mm = 0;
        int eval = asm_decode_report(read_buf, (size_t)n, &presence_flag, &dist_mm, cfg.distance_threshold * 100);

        if (dist_mm > 0) {
            current_distance_cm = (int)(dist_mm / 10);
        }

        /* Sensor explicitly signaled user absence or user moved beyond 1.2m */
        if (eval == 0) {
            if (strcmp(current_state, "absent") != 0) {
                current_state = "absent";
                candidate_start = 0.0;
                candidate_reports = 0;
                publish_state(current_state);
            }
            publish_telemetry(current_state, current_distance_cm, cfg.distance_threshold * 10, packet_count, 0.0, dev_path);
            continue;
        }

        /* User is present within 1.2m */
        if (strcmp(current_state, "present") == 0) {
            publish_telemetry(current_state, current_distance_cm, cfg.distance_threshold * 10, packet_count, 0.0, dev_path);
            continue;
        }

        /* Instant wake-on-approach */
        if (candidate_start <= 0.0 || (now - candidate_start > cfg.present_confirm_window)) {
            candidate_start = now;
            candidate_reports = 1;
        } else {
            candidate_reports++;
        }

        if (candidate_reports >= cfg.present_confirm_reports) {
            current_state = "present";
            candidate_start = 0.0;
            candidate_reports = 0;
            publish_state(current_state);
        }
        publish_telemetry(current_state, current_distance_cm, cfg.distance_threshold * 10, packet_count, 0.0, dev_path);
    }

    disable_sensor(fd, orig_features);
    close(fd);
    publish_state("disabled");
    publish_telemetry("disabled", 0, cfg.distance_threshold * 10, packet_count, 0.0, dev_path);
    return 0;
}
