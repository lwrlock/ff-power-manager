"""Lenovo 83JK / Intel ISH human-presence backend."""
from __future__ import annotations

import errno
import fcntl
import glob
import math
import os
import pathlib
import select
import signal
import statistics
import sys
import time
from collections import deque

from .core import RUN_DIR, STATE_FILE, load_sensor_config

REPORT_ID = 4
FEATURE_LEN = 256
TARGET_HID_ID = 'HID_ID=001F:00008087:00000AC2'
_running = True

IOC_NRBITS = 8
IOC_TYPEBITS = 8
IOC_SIZEBITS = 14
IOC_NRSHIFT = 0
IOC_TYPESHIFT = IOC_NRSHIFT + IOC_NRBITS
IOC_SIZESHIFT = IOC_TYPESHIFT + IOC_TYPEBITS
IOC_DIRSHIFT = IOC_SIZESHIFT + IOC_SIZEBITS
IOC_WRITE = 1
IOC_READ = 2


def _IOC(direction, type_, nr, size):
    return ((direction << IOC_DIRSHIFT) | (type_ << IOC_TYPESHIFT) |
            (nr << IOC_NRSHIFT) | (size << IOC_SIZESHIFT))


def _get_feature_ioctl(length):
    return _IOC(IOC_READ | IOC_WRITE, ord('H'), 0x07, length)


def _set_feature_ioctl(length):
    return _IOC(IOC_READ | IOC_WRITE, ord('H'), 0x06, length)


def locate_hidraw() -> str | None:
    for devdir in sorted(glob.glob('/sys/bus/hid/devices/*')):
        try:
            uevent = pathlib.Path(devdir, 'uevent').read_text(errors='ignore')
        except Exception:
            continue
        if TARGET_HID_ID not in uevent:
            continue
        nodes = sorted(glob.glob(os.path.join(devdir, 'hidraw', 'hidraw*')))
        if nodes:
            return '/dev/' + os.path.basename(nodes[0])
    return None


def get_feature(fd: int) -> bytearray:
    buf = bytearray(FEATURE_LEN)
    buf[0] = REPORT_ID
    ret = fcntl.ioctl(fd, _get_feature_ioctl(FEATURE_LEN), buf, True)
    if not isinstance(ret, int) or ret <= 0:
        raise RuntimeError('Feature Report 4 okunamadı')
    return buf


def set_feature(fd: int, buf: bytearray) -> None:
    ret = fcntl.ioctl(fd, _set_feature_ioctl(len(buf)), buf, True)
    if not isinstance(ret, int) or ret <= 0:
        raise RuntimeError('Feature Report 4 yazılamadı')


def validate_sensor(buf: bytearray) -> None:
    if len(buf) < 16 or buf[0] != REPORT_ID:
        raise RuntimeError('Beklenmeyen Intel ISH Report 4 formatı')
    raw = bytes(buf)
    if (b'V\x00L\x005\x003\x00L\x001\x00' not in raw and
            b'S\x00T\x00_\x00M\x00I\x00C\x00R\x00O\x00' not in raw):
        raise RuntimeError('Beklenen ST VL53L1 HOD sensör imzası bulunamadı')
    if buf[1] not in (1, 2, 3) or buf[4] not in (1, 2, 3, 4, 5, 6):
        raise RuntimeError('Reporting/power state alanları beklenen aralıkta değil')


def enable_sensor(fd: int) -> bytearray:
    original = get_feature(fd)
    validate_sensor(original)
    enabled = bytearray(original)
    enabled[1] = 2  # ALL_EVENTS
    enabled[4] = 2  # D0_FULL_POWER
    set_feature(fd, enabled)
    verify = get_feature(fd)
    if verify[1] != 2 or verify[4] != 2:
        raise RuntimeError('Firmware D0 + ALL_EVENTS durumunu kabul etmedi')
    return original


def disable_sensor(fd: int, original: bytearray | None = None) -> None:
    try:
        if original is not None:
            set_feature(fd, original)
            return
        current = get_feature(fd)
        validate_sensor(current)
        current[1] = 1  # NO_EVENTS
        current[4] = 6  # D4_POWER_OFF
        set_feature(fd, current)
    except Exception as exc:
        print(f'FPM sensor: restore warning: {exc}', file=sys.stderr, flush=True)


def publish(state: str) -> None:
    RUN_DIR.mkdir(mode=0o755, parents=True, exist_ok=True)
    try:
        old = STATE_FILE.read_text().strip()
    except Exception:
        old = None
    if old == state:
        return
    tmp = RUN_DIR / '.presence.state.tmp'
    tmp.write_text(state + '\n')
    os.chmod(tmp, 0o644)
    tmp.replace(STATE_FILE)
    print(f'FPM sensor: {state}', flush=True)


def adaptive_silence_timeout(base: float, intervals) -> float:
    """Return a conservative silence threshold from recent Report 4 cadence.

    The Lenovo firmware occasionally leaves multi-second gaps even while the
    user is still present. A fixed short timeout therefore causes state
    flapping. The configured value is a floor; recent cadence can only make
    the timeout longer, never shorter.
    """
    vals = sorted(float(x) for x in intervals if 0.05 <= float(x) <= 20.0)
    if len(vals) < 4:
        return base
    median = statistics.median(vals)
    p90 = vals[max(0, min(len(vals) - 1, math.ceil(len(vals) * 0.90) - 1))]
    return min(60.0, max(base, median * 4.0, p90 * 2.0))


def decode_report_4(data: bytes, threshold: int = 12) -> tuple[bool | None, int | None]:
    """Decode Report 4 from ST VL53L1 / Intel ISH.
    Returns (is_present, distance_raw).
    - Offset 27..30: 0x0544 Human Presence (int32: 1 = present, 0 = absent)
    - Offset 32: 0x04b1 Distance (uint8: <= 12 corresponds to 1.2m normal desk range)
    """
    if len(data) < 31 or data[0] != REPORT_ID:
        return None, None
    try:
        presence_raw = int.from_bytes(data[27:31], 'little', signed=True)
        distance_raw = data[32] if len(data) > 32 else None
        if presence_raw == 1:
            # If distance exceeds 1.2m (12 dm), user is beyond normal desk range!
            if distance_raw is not None and distance_raw > threshold:
                return False, distance_raw
            return True, distance_raw
        if presence_raw == 0:
            return False, distance_raw
        # Fallback if presence byte is not standard 0/1: check distance (<= 12 is <= 1.2m)
        if distance_raw is not None and 0 < distance_raw <= threshold:
            return True, distance_raw
        if distance_raw is not None and distance_raw > threshold:
            return False, distance_raw
        return True, distance_raw
    except Exception:
        return None, None


def _stop(*_):
    global _running
    _running = False


def run_daemon() -> None:
    path = locate_hidraw()
    if not path:
        raise RuntimeError('Intel ISH 8087:0AC2 hidraw bulunamadı')

    cfg = load_sensor_config()
    silence_floor = float(cfg.get('silence_timeout', 30.0))
    silence_floor = max(10.0, min(90.0, silence_floor))
    confirm_reports = int(cfg.get('present_confirm_reports', 1))
    confirm_reports = max(1, min(5, confirm_reports))
    confirm_window = float(cfg.get('present_confirm_window', 6.0))
    confirm_window = max(1.0, min(15.0, confirm_window))

    fd = os.open(path, os.O_RDWR | os.O_NONBLOCK)
    original = None
    publish('unknown')
    try:
        original = enable_sensor(fd)
        print(
            'FPM sensor: active on '
            f'{path}; silence-floor={silence_floor:.1f}s; '
            f'present-confirm={confirm_reports} reports/{confirm_window:.1f}s',
            flush=True,
        )
        state = 'unknown'
        last_report = None
        previous_report = None
        intervals = deque(maxlen=32)
        candidate_start = None
        candidate_reports = 0
        initial_deadline = time.monotonic() + max(10.0, silence_floor + 4.0)

        while _running:
            now = time.monotonic()
            if state == 'present' and last_report is not None:
                silence = adaptive_silence_timeout(silence_floor, intervals)
                timeout = max(0.0, last_report + silence - now)
            elif candidate_reports > 0 and candidate_start is not None:
                timeout = max(0.0, candidate_start + confirm_window - now)
            elif state == 'unknown':
                timeout = max(0.0, initial_deadline - now)
            else:
                timeout = None

            try:
                ready, _, _ = select.select([fd], [], [], timeout)
            except InterruptedError:
                continue
            if not _running:
                break

            if not ready:
                now = time.monotonic()
                if state == 'present' and last_report is not None:
                    silence = adaptive_silence_timeout(silence_floor, intervals)
                    if now >= last_report + silence:
                        state = 'absent'
                        candidate_start = None
                        candidate_reports = 0
                        publish(state)
                elif candidate_reports > 0:
                    candidate_start = None
                    candidate_reports = 0
                elif state == 'unknown' and now >= initial_deadline:
                    state = 'absent'
                    publish(state)
                continue

            try:
                data = os.read(fd, 4096)
            except BlockingIOError:
                continue
            except OSError as exc:
                if exc.errno in (errno.ENODEV, errno.EIO):
                    raise RuntimeError('Intel ISH aygıtı kayboldu') from exc
                raise

            if not data or data[0] != REPORT_ID:
                continue

            now = time.monotonic()
            if previous_report is not None:
                gap = now - previous_report
                if 0.05 <= gap <= 20.0:
                    intervals.append(gap)
            previous_report = now
            last_report = now

            data_present, distance = decode_report_4(data)

            # If the sensor explicitly reports absence (or distance > 2.4m):
            if data_present is False:
                if state != 'absent':
                    state = 'absent'
                    candidate_start = None
                    candidate_reports = 0
                    publish(state)
                continue

            # Human presence confirmed (data_present is True or packet arrived)
            if state == 'present':
                continue

            # Instant wake-on-approach if confirm_reports is 1
            if candidate_start is None or now - candidate_start > confirm_window:
                candidate_start = now
                candidate_reports = 1
            else:
                candidate_reports += 1

            if candidate_reports >= confirm_reports:
                state = 'present'
                candidate_start = None
                candidate_reports = 0
                publish(state)
    finally:
        if original is not None:
            disable_sensor(fd, original)
        try:
            os.close(fd)
        except Exception:
            pass
        publish('disabled')


def disable_only() -> int:
    path = locate_hidraw()
    if not path:
        publish('disabled')
        return 0
    fd = os.open(path, os.O_RDWR)
    try:
        disable_sensor(fd)
    finally:
        os.close(fd)
    publish('disabled')
    return 0


def inspect_reports(seconds: float = 15.0) -> int:
    path = locate_hidraw()
    if not path:
        print('Intel ISH bulunamadı', file=sys.stderr)
        return 2
    fd = os.open(path, os.O_RDWR | os.O_NONBLOCK)
    original = None
    try:
        original = enable_sensor(fd)
        end = time.monotonic() + seconds
        while time.monotonic() < end:
            ready, _, _ = select.select([fd], [], [], 1.0)
            if not ready:
                print('... silence ...', flush=True)
                continue
            data = os.read(fd, 4096)
            if data and data[0] == REPORT_ID:
                print(' '.join(f'{x:02x}' for x in data), flush=True)
    finally:
        if original is not None:
            disable_sensor(fd, original)
        os.close(fd)
    return 0


signal.signal(signal.SIGTERM, _stop)
signal.signal(signal.SIGINT, _stop)


def main(argv=None):
    argv = argv if argv is not None else sys.argv[1:]
    if '--disable' in argv:
        return disable_only()
    if '--inspect' in argv:
        idx = argv.index('--inspect')
        seconds = float(argv[idx + 1]) if idx + 1 < len(argv) else 15.0
        return inspect_reports(seconds)
    try:
        run_daemon()
        return 0
    except Exception as exc:
        print(f'FPM sensor fatal: {exc}', file=sys.stderr, flush=True)
        publish('error')
        return 3


if __name__ == '__main__':
    raise SystemExit(main())
