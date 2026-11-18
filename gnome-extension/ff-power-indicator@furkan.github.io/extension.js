/* exported init, enable, disable */
const { Clutter, Gio, GLib, GObject, St } = imports.gi;
const Main = imports.ui.main;
const PanelMenu = imports.ui.panelMenu;
const PopupMenu = imports.ui.popupMenu;
const ByteArray = imports.byteArray;

const PRESENCE_CONF = GLib.build_filenamev([GLib.get_home_dir(), '.config', 'ff-power-manager', 'presence.json']);
const ONESHOT_100_FLAG = GLib.build_filenamev([GLib.get_home_dir(), '.config', 'ff-power-manager', 'oneshot_100']);
const FOCUSED_WIN_FILE = '/run/ff-power-manager/focused.json';
const LAST_SLEEP_FILE = '/var/lib/ff-power-manager/last_sleep.json';
// Even-pixel offsets align cleanly on 200% HiDPI scaling without subpixel blur
const OLED_OFFSETS_X = [-2, 0, 2];

function readFile(path) {
    try {
        let [ok, contents] = GLib.file_get_contents(path);
        if (ok) {
            if (typeof TextDecoder !== 'undefined') {
                return new TextDecoder('utf-8').decode(contents).trim();
            }
            return ByteArray.toString(contents).trim();
        }
    } catch (e) {}
    return null;
}

function discoverBatteryDir() {
    try {
        const dir = Gio.File.new_for_path('/sys/class/power_supply');
        const iter = dir.enumerate_children('standard::name', Gio.FileQueryInfoFlags.NONE, null);
        let info;
        while ((info = iter.next_file(null)) !== null) {
            const name = info.get_name();
            if (name.startsWith('BAT')) {
                return `/sys/class/power_supply/${name}`;
            }
        }
    } catch (_) {}
    return '/sys/class/power_supply/BAT0';
}

function discoverConservationNode() {
    try {
        const dir = Gio.File.new_for_path('/sys/bus/platform/drivers/ideapad_acpi');
        if (dir.query_exists(null)) {
            const iter = dir.enumerate_children('standard::name', Gio.FileQueryInfoFlags.NONE, null);
            let info;
            while ((info = iter.next_file(null)) !== null) {
                const candidate = `/sys/bus/platform/drivers/ideapad_acpi/${info.get_name()}/conservation_mode`;
                if (GLib.file_test(candidate, GLib.FileTest.EXISTS)) {
                    return { path: candidate, kind: 'lenovo' };
                }
            }
        }
    } catch (_) {}
    const batDir = discoverBatteryDir();
    const thresh = `${batDir}/charge_control_end_threshold`;
    if (GLib.file_test(thresh, GLib.FileTest.EXISTS)) {
        return { path: thresh, kind: 'threshold' };
    }
    return { path: null, kind: null };
}

function discoverLaptopTitle() {
    const vendor = readFile('/sys/class/dmi/id/sys_vendor') || '';
    const prod = readFile('/sys/class/dmi/id/product_version') || readFile('/sys/class/dmi/id/product_name') || 'Linux Laptop';
    const shortVendor = vendor.split(' ')[0];
    const title = prod.toLowerCase().includes(shortVendor.toLowerCase()) ? prod : `${shortVendor} ${prod}`.trim();
    return `${title} • Smart Power`;
}

function readPresenceConf() {
    try {
        const raw = readFile(PRESENCE_CONF);
        if (raw) {
            return JSON.parse(raw);
        }
    } catch (_) {}
    return {};
}

function updatePresenceConf(key, val) {
    try {
        const cfg = readPresenceConf();
        cfg[key] = val;
        GLib.file_set_contents(PRESENCE_CONF, JSON.stringify(cfg, null, 2) + '\n');
    } catch (e) {
        log(`[FF Power Indicator] Failed updating presence.json: ${e}`);
    }
}

function discoverUcsiDir() {
    try {
        const dir = Gio.File.new_for_path('/sys/class/power_supply');
        const iter = dir.enumerate_children('standard::name', Gio.FileQueryInfoFlags.NONE, null);
        let info;
        while ((info = iter.next_file(null)) !== null) {
            const nm = info.get_name();
            if (nm.includes('ucsi')) {
                return `/sys/class/power_supply/${nm}`;
            }
        }
    } catch (_) {}
    return null;
}

function queryMprisPlayerAsync(bus, name, callback) {
    bus.call(
        name,
        '/org/mpris/MediaPlayer2',
        'org.freedesktop.DBus.Properties',
        'GetAll',
        new GLib.Variant('(s)', ['org.mpris.MediaPlayer2.Player']),
        new GLib.VariantType('(a{sv})'),
        Gio.DBusCallFlags.NONE,
        300,
        null,
        (_conn, res) => {
            try {
                const reply = bus.call_finish(res);
                const props = reply.get_child_value(0);
                const statusV = props.lookup_value('PlaybackStatus', null);
                const metaV = props.lookup_value('Metadata', null);
                const status = statusV ? statusV.deep_unpack() : '';
                let title = '';
                let artist = '';
                if (metaV) {
                    const titleV = metaV.lookup_value('xesam:title', null);
                    const artistV = metaV.lookup_value('xesam:artist', null);
                    title = titleV ? String(titleV.deep_unpack()).trim() : '';
                    if (artistV) {
                        const aVal = artistV.deep_unpack();
                        artist = (Array.isArray(aVal) ? aVal.join(', ') : String(aVal || '')).trim();
                    }
                }
                if (title) {
                    callback({ name, status, title, artist });
                    return;
                }
            } catch (_) {}
            callback(null);
        }
    );
}

function refreshMediaInfoAsync(callback) {
    try {
        const bus = Gio.bus_get_sync(Gio.BusType.SESSION, null);
        bus.call(
            'org.freedesktop.DBus',
            '/org/freedesktop/DBus',
            'org.freedesktop.DBus',
            'ListNames',
            null,
            new GLib.VariantType('(as)'),
            Gio.DBusCallFlags.NONE,
            300,
            null,
            (_conn, res) => {
                try {
                    const out = bus.call_finish(res);
                    const names = out.get_child_value(0).deep_unpack().filter(n => n.startsWith('org.mpris.MediaPlayer2.'));
                    if (names.length === 0) {
                        callback(null);
                        return;
                    }
                    let pending = names.length;
                    let best = null;
                    for (const name of names) {
                        queryMprisPlayerAsync(bus, name, info => {
                            if (info) {
                                if (!best || info.status === 'Playing') {
                                    best = info;
                                }
                            }
                            pending--;
                            if (pending === 0) {
                                callback(best);
                            }
                        });
                    }
                } catch (_) {
                    callback(null);
                }
            }
        );
    } catch (_) {
        callback(null);
    }
}

function discoverHwmonByName(targets) {
    const found = {};
    try {
        const dir = Gio.File.new_for_path('/sys/class/hwmon');
        const iter = dir.enumerate_children('standard::name', Gio.FileQueryInfoFlags.NONE, null);
        let info;
        while ((info = iter.next_file(null)) !== null) {
            const hName = info.get_name();
            const devName = readFile(`/sys/class/hwmon/${hName}/name`);
            if (devName && targets.includes(devName)) {
                found[devName] = `/sys/class/hwmon/${hName}/temp1_input`;
            }
        }
    } catch (_) {}
    return found;
}

function discoverCpuTempPath(hwmonMap) {
    const candidates = [
        hwmonMap.coretemp,
        hwmonMap.k10temp,
        hwmonMap.zenpower,
        '/sys/class/thermal/thermal_zone1/temp',
        '/sys/class/thermal/thermal_zone2/temp',
        '/sys/class/thermal/thermal_zone3/temp',
        '/sys/class/thermal/thermal_zone0/temp',
    ].filter(Boolean);
    for (const p of candidates) {
        try {
            let txt = readFile(p);
            if (txt) {
                let deg = parseInt(txt, 10);
                if (deg > 10000 && deg < 110000) return p;
            }
        } catch (_) {}
    }
    return null;
}

function getCpuTemp(tempPath) {
    if (!tempPath) return '--°C';
    try {
        let txt = readFile(tempPath);
        if (txt) {
            let deg = parseInt(txt, 10);
            if (deg > 10000 && deg < 110000) return `${Math.round(deg / 1000)}°C`;
        }
    } catch (_) {}
    return '--°C';
}

function discoverGpuNodes() {
    try {
        const drm = Gio.File.new_for_path('/sys/class/drm');
        const iter = drm.enumerate_children('standard::name', Gio.FileQueryInfoFlags.NONE, null);
        let info;
        while ((info = iter.next_file(null)) !== null) {
            const name = info.get_name();
            if (!name.startsWith('card') || name.includes('-')) continue;
            const xe0 = `/sys/class/drm/${name}/device/tile0/gt0/freq0/act_freq`;
            const xe1 = `/sys/class/drm/${name}/device/tile0/gt1/freq0/act_freq`;
            if (GLib.file_test(xe0, GLib.FileTest.EXISTS)) {
                return { kind: 'xe', gt0: xe0, gt1: GLib.file_test(xe1, GLib.FileTest.EXISTS) ? xe1 : null };
            }
            const i915 = `/sys/class/drm/${name}/gt_cur_freq_mhz`;
            if (GLib.file_test(i915, GLib.FileTest.EXISTS)) {
                return { kind: 'i915', node: i915 };
            }
            const amd = `/sys/class/drm/${name}/device/pp_dpm_sclk`;
            if (GLib.file_test(amd, GLib.FileTest.EXISTS)) {
                return { kind: 'amd', node: amd };
            }
        }
    } catch (_) {}
    return { kind: 'none' };
}

function getGpuStr(gpuInfo) {
    if (!gpuInfo || gpuInfo.kind === 'none') return 'Auto';
    if (gpuInfo.kind === 'xe') {
        const g0 = readFile(gpuInfo.gt0) || '0';
        const g1 = gpuInfo.gt1 ? (readFile(gpuInfo.gt1) || '0') : null;
        return g1 !== null ? `${g0}/${g1} MHz` : `${g0} MHz`;
    }
    if (gpuInfo.kind === 'i915') {
        return `${readFile(gpuInfo.node) || '0'} MHz`;
    }
    if (gpuInfo.kind === 'amd') {
        const raw = readFile(gpuInfo.node) || '';
        const active = raw.split('\n').find(l => l.includes('*'));
        return active ? active.replace('*', '').trim() : 'Auto';
    }
    return 'Auto';
}

function getChargerAndThermals(hwmonMap, batDir, ucsiDir, onAc) {
    const nvmeRaw = hwmonMap.nvme ? parseInt(readFile(hwmonMap.nvme) || '0', 10) : 0;
    const wifiRaw = hwmonMap.iwlwifi_1 ? parseInt(readFile(hwmonMap.iwlwifi_1) || '0', 10) : 0;
    const nvmeStr = nvmeRaw > 1000 ? `${Math.round(nvmeRaw / 1000)}°C` : '--';
    const wifiStr = wifiRaw > 1000 ? `${Math.round(wifiRaw / 1000)}°C` : '--';

    const voltUv = parseInt(readFile(`${batDir}/voltage_now`) || '0', 10);
    const voltStr = voltUv > 1000000 ? `${(voltUv / 1e6).toFixed(1)}V` : '';

    let portStr = onAc ? 'AC' : 'Pil';
    if (ucsiDir && readFile(`${ucsiDir}/online`) === '1') {
        const utype = readFile(`${ucsiDir}/usb_type`) || 'PD';
        const pdTag = utype.includes('[PD') ? 'PD' : 'USB-C';
        portStr = `USB-C ${pdTag}`;
    }
    return `SSD: ${nvmeStr} • Wi-Fi: ${wifiStr} | ${portStr}${voltStr ? ' (' + voltStr + ')' : ''}`;
}

function getBatteryDetails(batDir, onAc) {
    const eNow = parseInt(readFile(`${batDir}/energy_now`) || readFile(`${batDir}/charge_now`) || '0', 10);
    const eFull = parseInt(readFile(`${batDir}/energy_full`) || readFile(`${batDir}/charge_full`) || '0', 10);
    const eDesign = parseInt(readFile(`${batDir}/energy_full_design`) || readFile(`${batDir}/charge_full_design`) || '0', 10);
    const pNow = parseInt(readFile(`${batDir}/power_now`) || '0', 10);
    const cycles = readFile(`${batDir}/cycle_count`) || '?';
    const status = readFile(`${batDir}/status`) || (onAc ? 'AC' : 'Discharging');

    let healthPct = eDesign > 0 && eFull > 0 ? Math.min(100, Math.round((eFull / eDesign) * 100)) : 100;
    let etaStr = onAc ? (status === 'Charging' ? 'Şarj oluyor' : 'Prizde (%80 Koruma)') : 'Hesaplanıyor';
    if (!onAc && pNow > 500000 && eNow > 0) {
        const hours = eNow / pNow;
        const h = Math.floor(hours);
        const m = Math.round((hours - h) * 60);
        etaStr = `${h}s ${m}dk kaldı`;
    }
    return { etaStr, healthPct, cycles };
}

let _lastRaplUj = null;
let _lastRaplTimeUs = null;
let _lastRaplWatts = null;

function getLiveWatts(batDir) {
    let powerUwh = readFile(`${batDir}/power_now`);
    if (powerUwh) {
        let w = parseInt(powerUwh, 10) / 1e6;
        if (w > 0.2) return w;
    }
    let coreTxt = readFile('/sys/class/powercap/intel-rapl:0:0/energy_uj') ||
                  readFile('/sys/class/powercap/intel-rapl:0/energy_uj');
    let uncoreTxt = readFile('/sys/class/powercap/intel-rapl:0:1/energy_uj') || '0';
    if (coreTxt) {
        let nowUj = parseInt(coreTxt, 10) + parseInt(uncoreTxt, 10);
        let nowUs = GLib.get_monotonic_time();
        if (!isNaN(nowUj) && nowUj > 0) {
            if (_lastRaplUj !== null && _lastRaplTimeUs !== null) {
                let dtSec = (nowUs - _lastRaplTimeUs) / 1e6;
                if (dtSec >= 0.4 && nowUj >= _lastRaplUj) {
                    let w = 1.80 + (nowUj - _lastRaplUj) / (dtSec * 1e6);
                    if (w > 0.2 && w < 180.0) {
                        _lastRaplWatts = w;
                    }
                    _lastRaplUj = nowUj;
                    _lastRaplTimeUs = nowUs;
                }
            } else {
                _lastRaplUj = nowUj;
                _lastRaplTimeUs = nowUs;
            }
            return _lastRaplWatts;
        }
    }
    return _lastRaplWatts;
}

const FFPowerIndicator = GObject.registerClass(
class FFPowerIndicator extends PanelMenu.Button {
    _init() {
        super._init(0.5, 'FF Power Indicator', false);

        this._box = new St.BoxLayout({
            style_class: 'panel-status-indicators-box',
            x_align: Clutter.ActorAlign.CENTER,
            y_align: Clutter.ActorAlign.CENTER,
        });

        this._label = new St.Label({
            text: '...',
            style_class: 'ff-power-label',
            y_align: Clutter.ActorAlign.CENTER,
        });

        this._box.add_child(this._label);
        this.add_child(this._box);

        this._oledStep = 0;
        this._oledTick = 0;
        this._panelBoxes = [
            Main.panel ? Main.panel._leftBox : null,
            Main.panel ? Main.panel._centerBox : null,
            Main.panel ? Main.panel._rightBox : null,
        ].filter(Boolean);

        this._notifSettings = new Gio.Settings({ schema_id: 'org.gnome.desktop.notifications' });
        this._colorSettings = new Gio.Settings({ schema_id: 'org.gnome.settings-daemon.plugins.color' });
        this._hwmonMap = discoverHwmonByName(['nvme', 'iwlwifi_1', 'coretemp', 'k10temp', 'zenpower']);
        this._cpuTempPath = discoverCpuTempPath(this._hwmonMap);
        this._ucsiDir = discoverUcsiDir();
        this._batDir = discoverBatteryDir();
        this._consInfo = discoverConservationNode();
        this._gpuInfo = discoverGpuNodes();
        this._laptopTitle = discoverLaptopTitle();
        this._cachedMedia = null;
        this._destroyed = false;
        this._focusDebounceId = 0;

        this._buildMenu();
        this._menuOpenSig = this.menu.connect('open-state-changed', (_menu, isOpen) => {
            if (isOpen) {
                this._updateTelemetry();
                this._updateMenuTelemetry();
            }
        });
        this._updateTelemetry();
        this._onFocusChanged();
        try {
            this._focusSig = global.display.connect('notify::focus-window', () => this._onFocusChanged());
        } catch (_) {
            this._focusSig = 0;
        }

        this._timerId = GLib.timeout_add_seconds(GLib.PRIORITY_DEFAULT, 3, () => {
            this._updateTelemetry();
            this._oledTick++;
            if (this._oledTick % 60 === 0) {
                this._applyOledPixelShift();
            }
            return GLib.SOURCE_CONTINUE;
        });
    }

    _onFocusChanged() {
        if (this._focusDebounceId) {
            GLib.source_remove(this._focusDebounceId);
            this._focusDebounceId = 0;
        }
        this._focusDebounceId = GLib.timeout_add(GLib.PRIORITY_DEFAULT, 150, () => {
            this._focusDebounceId = 0;
            try {
                const win = global.display.focus_window;
                const pid = win ? win.get_pid() : 0;
                const wmClass = win ? (win.get_wm_class() || '') : '';
                const payload = JSON.stringify({ pid, wm_class: wmClass, ts: Math.floor(Date.now() / 1000) }) + '\n';
                GLib.file_set_contents(FOCUSED_WIN_FILE, payload);
            } catch (_) {}
            return GLib.SOURCE_REMOVE;
        });
    }

    _applyOledPixelShift() {
        if (!this._panelBoxes) return;
        const dx = OLED_OFFSETS_X[this._oledStep % OLED_OFFSETS_X.length];
        this._oledStep++;
        for (const box of this._panelBoxes) {
            try {
                box.set_translation(dx, 0, 0);
            } catch (_) {}
        }
    }

    _buildMenu() {
        if (this.menu && this.menu.box) {
            this.menu.box.add_style_class_name('ff-power-menu');
        }
        let headerBoxItem = new PopupMenu.PopupBaseMenuItem({reactive: false, can_focus: false});
        let infoBox = new St.BoxLayout({vertical: true, x_expand: true, style: 'spacing: 2px;'});

        this._hdrLabel = new St.Label({
            text: 'FF Power Manager',
            style: 'font-weight: bold; font-size: 12px; color: #38bdf8;',
        });
        this._subHeaderLabel = new St.Label({
            text: this._laptopTitle,
            style: 'font-size: 10.5px; color: #cbd5e1;',
        });
        this._gpuBatLabel = new St.Label({
            text: 'GPU & Batarya yükleniyor...',
            style: 'font-size: 10.5px; color: #94a3b8;',
        });
        this._coreSavLabel = new St.Label({
            text: 'CPU & Tasarruf izleniyor...',
            style: 'font-size: 10.5px; color: #34d399;',
        });

        infoBox.add_child(this._hdrLabel);
        infoBox.add_child(this._subHeaderLabel);
        infoBox.add_child(this._gpuBatLabel);
        infoBox.add_child(this._coreSavLabel);
        headerBoxItem.add_child(infoBox);
        this.menu.addMenuItem(headerBoxItem);

        this.menu.addMenuItem(new PopupMenu.PopupSeparatorMenuItem());

        let mediaRowItem = new PopupMenu.PopupBaseMenuItem({reactive: false, can_focus: false});
        let mRow = new St.BoxLayout({x_expand: true, style: 'spacing: 6px;'});
        this._mediaLabel = new St.Label({
            text: 'Medya: Boşta',
            x_expand: true,
            y_align: Clutter.ActorAlign.CENTER,
            style: 'font-size: 11px; color: #f8fafc;',
        });
        let btnPrev = new St.Button({label: '⏮', style_class: 'mediamac-btn', reactive: true});
        btnPrev.connect('clicked', () => this._sendMediaCmd('Previous'));
        let btnPlay = new St.Button({label: '⏯', style_class: 'mediamac-btn', reactive: true});
        btnPlay.connect('clicked', () => this._sendMediaCmd('PlayPause'));
        let btnNext = new St.Button({label: '⏭', style_class: 'mediamac-btn', reactive: true});
        btnNext.connect('clicked', () => this._sendMediaCmd('Next'));
        mRow.add_child(this._mediaLabel);
        mRow.add_child(btnPrev);
        mRow.add_child(btnPlay);
        mRow.add_child(btnNext);
        mediaRowItem.add_child(mRow);
        this.menu.addMenuItem(mediaRowItem);

        this.menu.addMenuItem(new PopupMenu.PopupSeparatorMenuItem());

        let profilesItem = new PopupMenu.PopupBaseMenuItem({reactive: false, can_focus: false});
        let pGrid = new St.BoxLayout({vertical: true, x_expand: true, style: 'spacing: 4px;'});
        let pRow1 = new St.BoxLayout({x_expand: true, style: 'spacing: 6px;'});
        let pRow2 = new St.BoxLayout({x_expand: true, style: 'spacing: 6px;'});

        const addProfileBtn = (row, label, cmd) => {
            let btn = new St.Button({label, style_class: 'ff-grid-btn', x_expand: true, reactive: true});
            btn.connect('clicked', () => {
                this._runCmd(cmd);
                this.menu.close();
            });
            row.add_child(btn);
        };
        addProfileBtn(pRow1, 'Dengeli (Önerilen)', '/usr/local/bin/ffctl apply');
        addProfileBtn(pRow1, 'Yüksek Perf.', '/usr/local/bin/ffctl apply extreme_performance');
        addProfileBtn(pRow2, 'Maks. Batarya', '/usr/local/bin/ffctl apply max_battery');
        addProfileBtn(pRow2, 'Sessiz & Serin', '/usr/local/bin/ffctl apply cool_quiet');

        pGrid.add_child(pRow1);
        pGrid.add_child(pRow2);
        profilesItem.add_child(pGrid);
        this.menu.addMenuItem(profilesItem);
        this.menu.addMenuItem(new PopupMenu.PopupSeparatorMenuItem());

        if (this._consInfo && this._consInfo.path) {
            this._cmSwitch = new PopupMenu.PopupSwitchMenuItem('%80 Batarya Koruma Modu', false);
            this._cmSwitch.connect('toggled', (item, state) => {
                if (state && GLib.file_test(ONESHOT_100_FLAG, GLib.FileTest.EXISTS)) {
                    try { Gio.File.new_for_path(ONESHOT_100_FLAG).delete(null); } catch (_) {}
                }
                this._runCmd(`/usr/local/bin/ffctl conservation ${state ? 'on' : 'off'}`);
            });
            this.menu.addMenuItem(this._cmSwitch);

            this._oneshotSwitch = new PopupMenu.PopupSwitchMenuItem('1 Kerelik %100 Şarj (Sonra %80)', false);
            this._oneshotSwitch.connect('toggled', (item, state) => {
                try {
                    if (state) {
                        GLib.file_set_contents(ONESHOT_100_FLAG, '1\n');
                        this._runCmd('/usr/local/bin/ffctl conservation off');
                    } else {
                        if (GLib.file_test(ONESHOT_100_FLAG, GLib.FileTest.EXISTS)) {
                            Gio.File.new_for_path(ONESHOT_100_FLAG).delete(null);
                        }
                        this._runCmd('/usr/local/bin/ffctl conservation on');
                    }
                } catch (e) {
                    log(`[FF Power Indicator] Failed toggling oneshot_100: ${e}`);
                }
            });
            this.menu.addMenuItem(this._oneshotSwitch);
        }

        this._hzSwitch = new PopupMenu.PopupSwitchMenuItem('Pilde Akıllı Yenileme (60↔120 Hz ARR)', true);
        this._hzSwitch.connect('toggled', (item, state) => {
            updatePresenceConf('force_120hz_on_battery', state);
        });
        this.menu.addMenuItem(this._hzSwitch);

        this._oledDimSwitch = new PopupMenu.PopupSwitchMenuItem('OLED Boşta Karartma (15 sn)', true);
        this._oledDimSwitch.connect('toggled', (item, state) => {
            updatePresenceConf('oled_screen_care', state);
        });
        this.menu.addMenuItem(this._oledDimSwitch);

        this._focusSwitch = new PopupMenu.PopupSwitchMenuItem('Ders / Odak Modu (Sessiz + Göz)', false);
        this._focusSwitch.connect('toggled', (item, state) => {
            this._notifSettings.set_boolean('show-banners', !state);
            try { this._colorSettings.set_boolean('night-light-enabled', state); } catch (_) {}
            this._runCmd(state ? '/usr/local/bin/ffctl apply cool_quiet' : '/usr/local/bin/ffctl apply');
        });
        this.menu.addMenuItem(this._focusSwitch);

        this._tofSwitch = new PopupMenu.PopupSwitchMenuItem('ToF Varlık Sensörü (Radar)', true);
        this._tofSwitch.connect('toggled', (item, state) => {
            let act = state ? 'enable-now' : 'disable-now';
            this._runCmd(`sudo -n /usr/local/lib/ff-power-manager/ff-power-helper sensor-service ${act}`);
        });
        this.menu.addMenuItem(this._tofSwitch);

        this.menu.addMenuItem(new PopupMenu.PopupSeparatorMenuItem());

        let launchItem = new PopupMenu.PopupBaseMenuItem({reactive: false, can_focus: false});
        let launchRow = new St.BoxLayout({x_expand: true, style: 'spacing: 6px;'});
        let btnGui = new St.Button({label: 'Kontrol Merkezi (GUI)', style_class: 'ff-grid-btn', x_expand: true, reactive: true});
        btnGui.connect('clicked', () => {
            this._runCmd('/usr/local/bin/ff-power-manager');
            this.menu.close();
        });
        let btnTui = new St.Button({label: 'Terminal (ff-tui)', style_class: 'ff-grid-btn', x_expand: true, reactive: true});
        btnTui.connect('clicked', () => {
            this._runCmd('gnome-terminal -- /usr/local/bin/ff-tui');
            this.menu.close();
        });
        launchRow.add_child(btnGui);
        launchRow.add_child(btnTui);
        launchItem.add_child(launchRow);
        this.menu.addMenuItem(launchItem);
    }

    _sendMediaCmd(method) {
        if (!this._cachedMedia || !this._cachedMedia.name) return;
        try {
            const bus = Gio.bus_get_sync(Gio.BusType.SESSION, null);
            bus.call(
                this._cachedMedia.name,
                '/org/mpris/MediaPlayer2',
                'org.mpris.MediaPlayer2.Player',
                method,
                null,
                null,
                Gio.DBusCallFlags.NONE,
                300,
                null,
                () => {
                    refreshMediaInfoAsync(media => {
                        if (!this._destroyed) {
                            this._cachedMedia = media;
                            this._renderTopLabel();
                        }
                    });
                }
            );
        } catch (_) {}
    }

    _runCmd(cmd) {
        try {
            GLib.spawn_command_line_async(cmd);
        } catch (e) {
            log(`[FF Power Indicator] Error executing ${cmd}: ${e}`);
        }
    }

    _renderTopLabel(capStr, onAc, pwrStr, temp) {
        if (capStr !== undefined) {
            this._lastCapStr = capStr;
            this._lastOnAc = onAc;
            this._lastPwrStr = pwrStr;
            this._lastTemp = temp;
        }
        const c = this._lastCapStr || '100';
        const ac = this._lastOnAc || false;
        const pwr = this._lastPwrStr || '-- W';
        const t = this._lastTemp || '--°C';
        const media = this._cachedMedia;

        if (media && media.title) {
            let shortTitle = media.title.length > 20 ? media.title.substring(0, 18) + '…' : media.title;
            let statusIcon = media.status === 'Playing' ? '▶ ' : '⏸ ';
            this._label.text = `${statusIcon}${shortTitle} | ${pwr} • %${c}${ac ? ' AC' : ''} • ${t}`;
            if (this._mediaLabel) {
                let mTitle = media.title.length > 26 ? media.title.substring(0, 24) + '…' : media.title;
                this._mediaLabel.text = `${statusIcon}${mTitle}`;
            }
        } else {
            if (this._mediaLabel) {
                this._mediaLabel.text = 'Medya: Boşta';
            }
            this._label.text = `${pwr} • %${c}${ac ? ' AC' : ''} • ${t}`;
        }
    }

    _updateTelemetry() {
        let capStr = readFile(`${this._batDir}/capacity`) || '100';
        let acad = readFile('/sys/class/power_supply/ACAD/online') ||
                   readFile('/sys/class/power_supply/AC/online') ||
                   readFile('/sys/class/power_supply/ADP1/online');
        let onAc = (acad === '1');
        let watts = getLiveWatts(this._batDir);
        const temp = getCpuTemp(this._cpuTempPath);
        let pwrStr = (watts !== null && watts > 0.2) ? `${watts.toFixed(1)}W` : '-- W';

        this._renderTopLabel(capStr, onAc, pwrStr, temp);

        refreshMediaInfoAsync(media => {
            if (this._destroyed) return;
            this._cachedMedia = media;
            this._renderTopLabel();
        });

        if (this.menu.isOpen) {
            this._updateMenuTelemetry(onAc, pwrStr, temp);
        }
    }

    _updateMenuTelemetry(onAcArg, pwrArg, tempArg) {
        let onAc = onAcArg;
        if (onAc === undefined) {
            let acad = readFile('/sys/class/power_supply/ACAD/online') ||
                       readFile('/sys/class/power_supply/AC/online') ||
                       readFile('/sys/class/power_supply/ADP1/online');
            onAc = (acad === '1');
        }
        let pwrStr = pwrArg;
        if (pwrStr === undefined) {
            let watts = getLiveWatts(this._batDir);
            pwrStr = (watts !== null && watts > 0.2) ? `${watts.toFixed(1)}W` : '-- W';
        }
        let temp = tempArg !== undefined ? tempArg : getCpuTemp(this._cpuTempPath);

        if (this._cmSwitch && this._consInfo && this._consInfo.path) {
            let cm = readFile(this._consInfo.path);
            if (cm !== null) {
                this._cmSwitch.setToggleState(this._consInfo.kind === 'lenovo' ? cm === '1' : parseInt(cm, 10) <= 85);
            }
        }
        if (this._oneshotSwitch) {
            this._oneshotSwitch.setToggleState(GLib.file_test(ONESHOT_100_FLAG, GLib.FileTest.EXISTS));
        }

        const pCfg = readPresenceConf();
        this._hzSwitch.setToggleState(Boolean(pCfg.force_120hz_on_battery !== false));
        this._oledDimSwitch.setToggleState(Boolean(pCfg.oled_screen_care));
        this._focusSwitch.setToggleState(!this._notifSettings.get_boolean('show-banners'));

        let sensorStatus = readFile('/run/ff-power-manager/presence.state') || 'disabled';
        this._tofSwitch.setToggleState(sensorStatus !== 'disabled');

        let onlineCores = readFile('/sys/devices/system/cpu/online') || '--';
        let pMaxKhz = parseInt(readFile('/sys/devices/system/cpu/cpu0/cpufreq/scaling_max_freq') || '0', 10);
        let pMaxGhz = pMaxKhz > 0 ? (pMaxKhz / 1e6).toFixed(1) : '--';
        let activeMode = readFile('/run/ff-power-manager/power.mode') || (onAc ? 'ac' : 'battery');
        let ctx = readFile('/run/ff-power-manager/active.context') || 'normal';
        let hzLabel = (readFile('/run/ff-power-manager/refresh.rate') || '120 Hz').split(' ')[0];

        if (this._gpuBatLabel) {
            const gpuStr = getGpuStr(this._gpuInfo);
            const bat = getBatteryDetails(this._batDir, onAc);
            const therm = getChargerAndThermals(this._hwmonMap || {}, this._batDir, this._ucsiDir, onAc);
            this._gpuBatLabel.text = `GPU: ${gpuStr} • ${bat.etaStr} (%${bat.healthPct}) | ${therm}`;
        }

        if (this._coreSavLabel) {
            let ctxTag = ctx === 'cinema' ? ' • Sinema' : '';
            let savRaw = readFile('/run/ff-power-manager/savings.json');
            let sleepRaw = readFile(LAST_SLEEP_FILE);
            let sleepSuffix = '';
            if (sleepRaw) {
                try {
                    const sl = JSON.parse(sleepRaw);
                    if (typeof sl.avg_watts === 'number') {
                        sleepSuffix = ` • Uyku: ${sl.avg_watts.toFixed(2)}W`;
                    }
                } catch (_) {}
            }
            let savStr = `ARR + ToF aktif${sleepSuffix}`;
            if (savRaw) {
                try {
                    const sav = JSON.parse(savRaw);
                    const offMin = Math.round((sav.screen_off_sec || 0) / 60);
                    const wh = ((sav.wh_saved || 0)).toFixed(2);
                    savStr = `${offMin} dk ekran (~${wh} Wh)${sleepSuffix}`;
                } catch (_) {}
            }
            this._coreSavLabel.text = `CPU ${onlineCores} (${pMaxGhz} GHz) • ${activeMode} ${hzLabel}Hz${ctxTag} | ${savStr}`;
        }

        let dist = readFile('/run/ff-power-manager/sensor_telemetry.json');
        if (this._subHeaderLabel) {
            let tofLine = `${this._laptopTitle} | ${pwrStr} • ${temp}`;
            if (dist) {
                try {
                    let tel = JSON.parse(dist);
                    if (tel.active) {
                        tofLine = `ToF: ${tel.distance_cm} cm (${tel.state.toUpperCase()}) • ${pwrStr} • ${temp}`;
                    }
                } catch (e) {}
            }
            this._subHeaderLabel.text = tofLine;
        }
    }

    destroy() {
        this._destroyed = true;
        if (this._focusDebounceId) {
            GLib.source_remove(this._focusDebounceId);
            this._focusDebounceId = 0;
        }
        if (this._menuOpenSig && this.menu) {
            try {
                this.menu.disconnect(this._menuOpenSig);
            } catch (_) {}
            this._menuOpenSig = 0;
        }
        if (this._focusSig) {
            try {
                global.display.disconnect(this._focusSig);
            } catch (_) {}
            this._focusSig = 0;
        }
        if (this._timerId) {
            GLib.source_remove(this._timerId);
            this._timerId = 0;
        }
        if (this._panelBoxes) {
            for (const box of this._panelBoxes) {
                try {
                    box.set_translation(0, 0, 0);
                } catch (_) {}
            }
        }
        super.destroy();
    }
});

let _indicator = null;

function init() {
}

function enable() {
    _indicator = new FFPowerIndicator();
    Main.panel.addToStatusArea('ff-power-indicator', _indicator, 0, 'right');
}

function disable() {
    if (_indicator) {
        _indicator.destroy();
        _indicator = null;
    }
}
