/* exported init, enable, disable */
const { Clutter, Gio, GLib, GObject, St } = imports.gi;
const Main = imports.ui.main;
const PanelMenu = imports.ui.panelMenu;
const PopupMenu = imports.ui.popupMenu;
const ByteArray = imports.byteArray;

const CONSERVATION_NODE = '/sys/bus/platform/drivers/ideapad_acpi/VPC2004:00/conservation_mode';
const OLED_OFFSETS_X = [-2, -1, 0, 1, 2];
const OLED_OFFSETS_Y = [-1, 0, 1];

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

function getCpuTemp() {
    const paths = [
        '/sys/class/thermal/thermal_zone1/temp',
        '/sys/class/thermal/thermal_zone2/temp',
        '/sys/class/thermal/thermal_zone3/temp',
        '/sys/class/thermal/thermal_zone5/temp',
        '/sys/class/thermal/thermal_zone7/temp',
    ];
    for (const p of paths) {
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

let _lastRaplUj = null;
let _lastRaplTimeUs = null;
let _lastRaplWatts = 3.4;

function getLiveWatts(onAc) {
    let powerUwh = readFile('/sys/class/power_supply/BAT1/power_now') ||
                   readFile('/sys/class/power_supply/BAT0/power_now');
    if (powerUwh) {
        let w = parseInt(powerUwh, 10) / 1e6;
        if (w > 0.5) return w;
    }
    let coreTxt = readFile('/sys/class/powercap/intel-rapl:0:0/energy_uj');
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

        this._buildMenu();
        this._updateTelemetry();

        this._timerId = GLib.timeout_add_seconds(GLib.PRIORITY_DEFAULT, 2, () => {
            this._updateTelemetry();
            this._oledTick++;
            if (this._oledTick % 60 === 0) {
                this._applyOledPixelShift();
            }
            return GLib.SOURCE_CONTINUE;
        });
    }

    _applyOledPixelShift() {
        /* Disabled odd-pixel translation to prevent 200% HiDPI subpixel text blur on OLED */
        if (this._panelBoxes) {
            for (const box of this._panelBoxes) {
                try {
                    box.set_translation(0, 0, 0);
                } catch (_) {}
            }
        }
    }

    _buildMenu() {
        let headerItem = new PopupMenu.PopupMenuItem('FF Power Manager', {reactive: false});
        headerItem.label.style = 'font-weight: bold; font-size: 13px; color: #38bdf8;';
        this.menu.addMenuItem(headerItem);

        this._subHeader = new PopupMenu.PopupMenuItem('Lenovo IdeaPad Pro 5 • 2.8K OLED', {reactive: false});
        this._subHeader.label.style = 'font-size: 11px; color: #94a3b8;';
        this.menu.addMenuItem(this._subHeader);

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

        this._coreItem = new PopupMenu.PopupMenuItem('CPU: MacBook Hybrid (8/16 Core)', {reactive: false});
        this._coreItem.label.style = 'font-size: 11px; color: #34d399;';
        profilesSection.addMenuItem(this._coreItem);

        this.menu.addMenuItem(profilesSection);
        this.menu.addMenuItem(new PopupMenu.PopupSeparatorMenuItem());

        this._cmSwitch = new PopupMenu.PopupSwitchMenuItem('%80 Batarya Koruma Modu', false);
        this._cmSwitch.connect('toggled', (item, state) => {
            this._runCmd(`/usr/local/bin/ffctl conservation ${state ? 'on' : 'off'}`);
        });
        this.menu.addMenuItem(this._cmSwitch);

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
                    'org.mpris.MediaPlayer2.Player',
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
        let capStr = readFile('/sys/class/power_supply/BAT1/capacity') ||
                     readFile('/sys/class/power_supply/BAT0/capacity') || '100';

        let acad = readFile('/sys/class/power_supply/ACAD/online') ||
                   readFile('/sys/class/power_supply/AC/online');
        let onAc = (acad === '1');
        let watts = getLiveWatts(onAc);

        const media = getActiveMediaInfo();
        const temp = getCpuTemp();
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

        let cm = readFile(CONSERVATION_NODE);
        if (cm !== null) {
            this._cmSwitch.setToggleState(cm === '1');
        }

        let sensorStatus = readFile('/run/ff-power-manager/presence.state') || 'disabled';
        this._tofSwitch.setToggleState(sensorStatus !== 'disabled');

        let onlineCores = readFile('/sys/devices/system/cpu/online') || '0-15';
        let pMaxKhz = parseInt(readFile('/sys/devices/system/cpu/cpu0/cpufreq/scaling_max_freq') || '4800000', 10);
        let pMaxGhz = (pMaxKhz / 1e6).toFixed(1);
        if (this._coreItem) {
            if (onlineCores === '0-15') {
                this._coreItem.label.text = `CPU: 16/16 All-Core Boost (${pMaxGhz} GHz)`;
            } else {
                this._coreItem.label.text = `CPU: MacBook Hybrid 8/16 (${onlineCores} • ${pMaxGhz} GHz)`;
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
