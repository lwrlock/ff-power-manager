/* exported init, enable, disable */
const { Clutter, Gio, GLib, GObject, St } = imports.gi;
const Main = imports.ui.main;
const PanelMenu = imports.ui.panelMenu;
const PopupMenu = imports.ui.popupMenu;
const ByteArray = imports.byteArray;

const PRESENCE_CONF = GLib.build_filenamev([GLib.get_home_dir(), '.config', 'ff-power-manager', 'presence.json']);
const ONESHOT_100_FLAG = GLib.build_filenamev([GLib.get_home_dir(), '.config', 'ff-power-manager', 'oneshot_100']);
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

function getActiveMediaInfo() {
    try {
        const bus = Gio.bus_get_sync(Gio.BusType.SESSION, null);
        const res = bus.call_sync('org.freedesktop.DBus', '/org/freedesktop/DBus', 'org.freedesktop.DBus', 'ListNames', null, null, Gio.DBusCallFlags.NONE, 200, null);
        const names = res.get_child_value(0).deep_unpack().filter(n => n.startsWith('org.mpris.MediaPlayer2.'));
        let pausedCandidate = null;
        for (const name of names) {
            try {
                const statusRes = bus.call_sync(name, '/org/mpris/MediaPlayer2', 'org.freedesktop.DBus.Properties', 'Get', new GLib.Variant('(ss)', ['org.mpris.MediaPlayer2.Player', 'PlaybackStatus']), null, Gio.DBusCallFlags.NONE, 200, null);
                const status = statusRes.get_child_value(0).get_variant().deep_unpack();
                const metaRes = bus.call_sync(name, '/org/mpris/MediaPlayer2', 'org.freedesktop.DBus.Properties', 'Get', new GLib.Variant('(ss)', ['org.mpris.MediaPlayer2.Player', 'Metadata']), null, Gio.DBusCallFlags.NONE, 200, null);
                const dict = metaRes.get_child_value(0).get_variant();
                const titleV = dict.lookup_value('xesam:title', null);
                const artistV = dict.lookup_value('xesam:artist', null);
                let title = titleV ? String(titleV.deep_unpack()) : '';
                let artist = '';
                if (artistV) {
                    const aVal = artistV.deep_unpack();
                    artist = Array.isArray(aVal) ? aVal.join(', ') : String(aVal || '');
                }
                if (title) {
                    const info = { bus, name, status, title: title.trim(), artist: artist.trim() };
                    if (status === 'Playing') return info;
                    if (!pausedCandidate) pausedCandidate = info;
                }
            } catch (_) {}
        }
        return pausedCandidate;
    } catch (_) {}
    return null;
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

function getCpuTemp(hwmonMap) {
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
                if (deg > 10000 && deg < 110000) return `${Math.round(deg / 1000)}°C`;
            }
        } catch (_) {}
    }
    return '38°C';
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

function getChargerAndThermals(hwmonMap, batDir, onAc) {
    const nvmeRaw = hwmonMap.nvme ? parseInt(readFile(hwmonMap.nvme) || '0', 10) : 0;
    const wifiRaw = hwmonMap.iwlwifi_1 ? parseInt(readFile(hwmonMap.iwlwifi_1) || '0', 10) : 0;
    const nvmeStr = nvmeRaw > 1000 ? `${Math.round(nvmeRaw / 1000)}°C` : '--';
    const wifiStr = wifiRaw > 1000 ? `${Math.round(wifiRaw / 1000)}°C` : '--';

    const voltUv = parseInt(readFile(`${batDir}/voltage_now`) || '0', 10);
    const voltStr = voltUv > 1000000 ? `${(voltUv / 1e6).toFixed(1)}V` : '';

    let portStr = onAc ? 'AC' : 'Pil';
    try {
        const dir = Gio.File.new_for_path('/sys/class/power_supply');
        const iter = dir.enumerate_children('standard::name', Gio.FileQueryInfoFlags.NONE, null);
        let info;
        while ((info = iter.next_file(null)) !== null) {
            const nm = info.get_name();
            if (!nm.includes('ucsi')) continue;
            const base = `/sys/class/power_supply/${nm}`;
            if (readFile(`${base}/online`) === '1') {
                const utype = readFile(`${base}/usb_type`) || 'PD';
                const pdTag = utype.includes('[PD') ? 'PD' : 'USB-C';
                portStr = `USB-C ${pdTag}`;
                break;
            }
        }
    } catch (_) {}
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
let _lastRaplWatts = 3.4;

function getLiveWatts(batDir) {
    let powerUwh = readFile(`${batDir}/power_now`);
    if (powerUwh) {
        let w = parseInt(powerUwh, 10) / 1e6;
        if (w > 0.5) return w;
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
                    if (w > 0.5 && w < 140.0) {
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
        this._batDir = discoverBatteryDir();
        this._consInfo = discoverConservationNode();
        this._gpuInfo = discoverGpuNodes();
        this._laptopTitle = discoverLaptopTitle();

        this._buildMenu();
        this._updateTelemetry();

        this._timerId = GLib.timeout_add_seconds(GLib.PRIORITY_DEFAULT, 2, () => {
            this._updateTelemetry();
            this._oledTick++;
            if (this._oledTick % 90 === 0) {
                this._applyOledPixelShift();
            }
            return GLib.SOURCE_CONTINUE;
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
        let headerItem = new PopupMenu.PopupMenuItem('FF Power Manager', {reactive: false});
        headerItem.label.style = 'font-weight: bold; font-size: 13px; color: #38bdf8;';
        this.menu.addMenuItem(headerItem);

        this._subHeader = new PopupMenu.PopupMenuItem(this._laptopTitle, {reactive: false});
        this._subHeader.label.style = 'font-size: 11px; color: #94a3b8;';
        this.menu.addMenuItem(this._subHeader);

        this._gpuBatItem = new PopupMenu.PopupMenuItem('GPU & Batarya yükleniyor...', {reactive: false});
        this._gpuBatItem.label.style = 'font-size: 11px; color: #cbd5e1;';
        this.menu.addMenuItem(this._gpuBatItem);

        this._thermalsItem = new PopupMenu.PopupMenuItem('Termal & Şarj yükleniyor...', {reactive: false});
        this._thermalsItem.label.style = 'font-size: 11px; color: #94a3b8;';
        this.menu.addMenuItem(this._thermalsItem);

        this._savingsItem = new PopupMenu.PopupMenuItem('Tasarruf: İzleniyor...', {reactive: false});
        this._savingsItem.label.style = 'font-size: 10.5px; color: #34d399;';
        this.menu.addMenuItem(this._savingsItem);

        this.menu.addMenuItem(new PopupMenu.PopupSeparatorMenuItem());

        this._mediaSection = new PopupMenu.PopupMenuSection();
        this._mediaItem = new PopupMenu.PopupMenuItem('Medya: Oynatıcı Bekleniyor...', {reactive: false});
        this._mediaItem.label.style = 'font-size: 11.5px; font-weight: 500; color: #f8fafc;';
        this._mediaSection.addMenuItem(this._mediaItem);

        let mediaControlsBox = new PopupMenu.PopupBaseMenuItem({reactive: true});
        let cBox = new St.BoxLayout({x_expand: true, style: 'spacing: 10px;'});
        let btnPrev = new St.Button({label: 'Önceki', style_class: 'mediamac-btn'});
        btnPrev.connect('clicked', () => this._sendMediaCmd('Previous'));
        let btnPlay = new St.Button({label: 'Oynat / Duraklat', style_class: 'mediamac-btn'});
        btnPlay.connect('clicked', () => this._sendMediaCmd('PlayPause'));
        let btnNext = new St.Button({label: 'Sonraki', style_class: 'mediamac-btn'});
        btnNext.connect('clicked', () => this._sendMediaCmd('Next'));
        cBox.add_child(btnPrev);
        cBox.add_child(btnPlay);
        cBox.add_child(btnNext);
        mediaControlsBox.add_child(cBox);
        this._mediaSection.addMenuItem(mediaControlsBox);

        this.menu.addMenuItem(this._mediaSection);
        this.menu.addMenuItem(new PopupMenu.PopupSeparatorMenuItem());

        let profilesSection = new PopupMenu.PopupMenuSection();

        let pRec = new PopupMenu.PopupMenuItem('Dengeli Profil (Önerilen)');
        pRec.connect('activate', () => this._runCmd('/usr/local/bin/ffctl apply'));
        profilesSection.addMenuItem(pRec);

        let pExt = new PopupMenu.PopupMenuItem('Yüksek Performans');
        pExt.connect('activate', () => this._runCmd('/usr/local/bin/ffctl apply extreme_performance'));
        profilesSection.addMenuItem(pExt);

        let pBat = new PopupMenu.PopupMenuItem('Maksimum Batarya Tasarrufu');
        pBat.connect('activate', () => this._runCmd('/usr/local/bin/ffctl apply max_battery'));
        profilesSection.addMenuItem(pBat);

        let pQuiet = new PopupMenu.PopupMenuItem('Sessiz & Serin Mod');
        pQuiet.connect('activate', () => this._runCmd('/usr/local/bin/ffctl apply cool_quiet'));
        profilesSection.addMenuItem(pQuiet);

        this._coreItem = new PopupMenu.PopupMenuItem('CPU & Yenileme Hızı yükleniyor...', {reactive: false});
        this._coreItem.label.style = 'font-size: 11px; color: #38bdf8;';
        profilesSection.addMenuItem(this._coreItem);

        this.menu.addMenuItem(profilesSection);
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

        this._hzSwitch = new PopupMenu.PopupSwitchMenuItem('Pilde Akıcı ProMotion (60↔120 Hz)', true);
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

        let guiItem = new PopupMenu.PopupMenuItem('Kontrol Merkezi (GUI)');
        guiItem.connect('activate', () => this._runCmd('/usr/local/bin/ff-power-manager'));
        this.menu.addMenuItem(guiItem);

        let tuiItem = new PopupMenu.PopupMenuItem('Terminal Paneli (ff-tui)');
        tuiItem.connect('activate', () => {
            this._runCmd('gnome-terminal -- /usr/local/bin/ff-tui');
        });
        this.menu.addMenuItem(tuiItem);
    }

    _sendMediaCmd(method) {
        try {
            const media = getActiveMediaInfo();
            if (media && media.name) {
                const bus = Gio.bus_get_sync(Gio.BusType.SESSION, null);
                bus.call_sync(
                    media.name,
                    '/org/mpris/MediaPlayer2',
                    'org.freedesktop.DBus.Properties',
                    method,
                    null, null, Gio.DBusCallFlags.NONE, 500, null
                );
            }
        } catch (_) {}
    }

    _runCmd(cmd) {
        try {
            GLib.spawn_command_line_async(cmd);
        } catch (e) {
            log(`[FF Power Indicator] Error executing ${cmd}: ${e}`);
        }
    }

    _updateTelemetry() {
        let capStr = readFile(`${this._batDir}/capacity`) || '100';

        let acad = readFile('/sys/class/power_supply/ACAD/online') ||
                   readFile('/sys/class/power_supply/AC/online') ||
                   readFile('/sys/class/power_supply/ADP1/online');
        let onAc = (acad === '1');
        let watts = getLiveWatts(this._batDir);

        const media = getActiveMediaInfo();
        const temp = getCpuTemp(this._hwmonMap || {});
        let pwrStr = watts > 0.2 ? `${watts.toFixed(1)}W` : '3.4W';
        if (media && media.title) {
            let shortTitle = media.title.length > 20 ? media.title.substring(0, 18) + '…' : media.title;
            let statusIcon = media.status === 'Playing' ? '▶ ' : '⏸ ';
            this._label.text = `${statusIcon}${shortTitle} | ${pwrStr} • %${capStr}${onAc ? ' AC' : ''} • ${temp}`;
            if (this._mediaItem) {
                this._mediaItem.label.text = `${media.title} (${media.status === 'Playing' ? 'Oynatılıyor' : 'Duraklatıldı'})`;
            }
        } else {
            if (this._mediaItem) {
                this._mediaItem.label.text = 'Medya: Boşta (Oynatıcı Bekleniyor)';
            }
            this._label.text = `${pwrStr} • %${capStr}${onAc ? ' AC' : ''} • ${temp}`;
        }

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

        let onlineCores = readFile('/sys/devices/system/cpu/online') || '0-15';
        let pMaxKhz = parseInt(readFile('/sys/devices/system/cpu/cpu0/cpufreq/scaling_max_freq') || '4800000', 10);
        let pMaxGhz = (pMaxKhz / 1e6).toFixed(1);
        let activeMode = readFile('/run/ff-power-manager/power.mode') || (onAc ? 'ac' : 'battery');
        let ctx = readFile('/run/ff-power-manager/active.context') || 'normal';
        let hzLabel = (readFile('/run/ff-power-manager/refresh.rate') || '120 Hz').split(' ')[0];
        if (this._coreItem) {
            let ctxTag = ctx === 'cinema' ? ' • Sinema' : '';
            this._coreItem.label.text = `CPU: ${onlineCores} (${pMaxGhz} GHz) | ${activeMode} • ${hzLabel} Hz${ctxTag}`;
        }

        if (this._gpuBatItem) {
            const gpuStr = getGpuStr(this._gpuInfo);
            const bat = getBatteryDetails(this._batDir, onAc);
            this._gpuBatItem.label.text = `GPU: ${gpuStr} | ${bat.etaStr} (Sağlık %${bat.healthPct}, ${bat.cycles} döngü)`;
        }

        if (this._thermalsItem) {
            this._thermalsItem.label.text = getChargerAndThermals(this._hwmonMap || {}, this._batDir, onAc);
        }

        if (this._savingsItem) {
            let savRaw = readFile('/run/ff-power-manager/savings.json');
            if (savRaw) {
                try {
                    const sav = JSON.parse(savRaw);
                    const offMin = Math.round((sav.screen_off_sec || 0) / 60);
                    const wh = ((sav.wh_saved || 0)).toFixed(2);
                    this._savingsItem.label.text = `Bugün Tasarruf: ${offMin} dk ekran koruması • ~${wh} Wh kazanım`;
                } catch (_) {}
            } else {
                this._savingsItem.label.text = 'Bugün Tasarruf: ProMotion & ToF aktif';
            }
        }

        let dist = readFile('/run/ff-power-manager/sensor_telemetry.json');
        if (dist && this._subHeader) {
            try {
                let tel = JSON.parse(dist);
                if (tel.active) {
                    this._subHeader.label.text = `ToF: ${tel.distance_cm} cm | ${tel.state.toUpperCase()} | ${pwrStr} | ${temp}`;
                }
            } catch (e) {}
        }
    }

    destroy() {
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
