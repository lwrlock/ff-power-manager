from .core import apply, load_config, on_battery_from_sysfs


def apply_current() -> str:
    mode = 'battery' if on_battery_from_sysfs() else 'ac'
    apply(mode, load_config())
    return mode


def main():
    mode = apply_current()
    print(f'FF Power Manager: applied {mode}', flush=True)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
