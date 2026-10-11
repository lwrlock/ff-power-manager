import Clutter from 'gi://Clutter';
import Gio from 'gi://Gio';
import GLib from 'gi://GLib';
import GObject from 'gi://GObject';
import St from 'gi://St';
import * as Main from 'resource:///org/gnome/shell/ui/main.js';
import * as PanelMenu from 'resource:///org/gnome/shell/ui/panelMenu.js';
import * as PopupMenu from 'resource:///org/gnome/shell/ui/popupMenu.js';
import { Extension } from 'resource:///org/gnome/shell/extensions/extension.js';

const CONSERVATION_NODE = '/sys/bus/platform/drivers/ideapad_acpi/VPC2004:00/conservation_mode';

function readFile(path) {
    try {
        let [ok, contents] = GLib.file_get_contents(path);
        if (ok) {
            return new TextDecoder('utf-8').decode(contents).trim();
        }
    } catch (e) {}
    return null;
}

function getActiveMediaInfo() {
    try {
        const bus = Gio.bus_get_sync(Gio.BusType.SESSION, null);
        const res = bus.call_sync('org.freedesktop.DBus', '/org/freedesktop/DBus', 'org.freedesktop.DBus', 'ListNames', null, null, Gio.DBusCallFlags.NONE, 200, null);
        const names = res.get_child_value(0).deepUnpack().filter(n => n.startsWith('org.mpris.MediaPlayer2.'));
        let pausedCandidate = null;
        for (const name of names) {
            try {
                const statusRes = bus.call_sync(name, '/org/mpris/MediaPlayer2', 'org.freedesktop.DBus.Properties', 'Get', new GLib.Variant('(ss)', ['org.mpris.MediaPlayer2.Player', 'PlaybackStatus']), null, Gio.DBusCallFlags.NONE, 200, null);
                const status = statusRes.get_child_value(0).get_variant().deepUnpack();
                const metaRes = bus.call_sync(name, '/org/mpris/MediaPlayer2', 'org.freedesktop.DBus.Properties', 'Get', new GLib.Variant('(ss)', ['org.mpris.MediaPlayer2.Player', 'Metadata']), null, Gio.DBusCallFlags.NONE, 200, null);
                const dict = metaRes.get_child_value(0).get_variant();
                const titleV = dict.lookup_value('xesam:title', null);
                const artistV = dict.lookup_value('xesam:artist', null);
                let title = titleV ? String(titleV.deepUnpack()) : '';
                let artist = '';
                if (artistV) {
                    const aVal = artistV.deepUnpack();
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

        this._buildMenu();
        this._updateTelemetry();

        // Update telemetry every 2 seconds
        this._timerId = GLib.timeout_add_seconds(GLib.PRIORITY_DEFAULT, 2, () => {
            this._updateTelemetry();
            return GLib.SOURCE_CONTINUE;
        });
    }

    _buildMenu() {
        // Title Header
        let headerItem = new PopupMenu.PopupMenuItem('Sistem & Güç Denetimi', {reactive: false});
        headerItem.label.style = 'font-weight: bold; font-size: 13px; color: #38bdf8;';
        this.menu.addMenuItem(headerItem);

        this._subHeader = new PopupMenu.PopupMenuItem('Lenovo IdeaPad Pro 5 • 2.8K OLED', {reactive: false});
        this._subHeader.label.style = 'font-size: 11px; color: #94a3b8;';
        this.menu.addMenuItem(this._subHeader);

        this.menu.addMenuItem(new PopupMenu.PopupSeparatorMenuItem());

        // Now Playing Section in Menu
        this._mediaSection = new PopupMenu.PopupMenuSection();
        this._mediaItem = new PopupMenu.PopupMenuItem('Medya: Oynatıcı Bekleniyor...', {reactive: false});
        this._mediaItem.label.style = 'font-size: 11.5px; font-weight: 500; color: #f8fafc;';
        this._mediaSection.addMenuItem(this._mediaItem);

        let mediaControlsBox = new PopupMenu.PopupBaseMenuItem({reactive: true});
        let cBox = new St.BoxLayout({spacing: 10, x_expand: true});
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

        // Quick Profiles (Zero Emojis)
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

        this.menu.addMenuItem(profilesSection);
        this.menu.addMenuItem(new PopupMenu.PopupSeparatorMenuItem());

        // Toggles
        this._cmSwitch = new PopupMenu.PopupSwitchMenuItem('%80 Batarya Koruma Modu', false);
        this._cmSwitch.connect('toggled', (item, state) => {
            this._runCmd(`/usr/local/bin/ffctl conservation ${state ? 'on' : 'off'}`);
        });
        this.menu.addMenuItem(this._cmSwitch);

        this._tofSwitch = new PopupMenu.PopupSwitchMenuItem('ToF Varlık Sensörü (Radar)', true);
        this._tofSwitch.connect('toggled', (item, state) => {
            let act = state ? 'enable-now' : 'disable-now';
            this._runCmd(`/usr/local/lib/ff-power-manager/ff-power-helper sensor-service ${act}`);
        });
        this.menu.addMenuItem(this._tofSwitch);

        this.menu.addMenuItem(new PopupMenu.PopupSeparatorMenuItem());

        // Launchers
        let guiItem = new PopupMenu.PopupMenuItem('Kontrol Merkezi (GUI)');
        guiItem.connect('activate', () => this._runCmd('ff-power-manager'));
        this.menu.addMenuItem(guiItem);

        let tuiItem = new PopupMenu.PopupMenuItem('Terminal Paneli (ff-tui)');
        tuiItem.connect('activate', () => {
            this._runCmd('blackbox-terminal -e /usr/local/bin/ff-tui || gnome-terminal -- /usr/local/bin/ff-tui || ptyxis -e /usr/local/bin/ff-tui');
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
                    null, null, Gio.DBusCallFlags.NONE, 500, null,
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
        // Read power draw
        let powerUwh = readFile('/sys/class/power_supply/BAT1/power_now') ||
                       readFile('/sys/class/power_supply/BAT0/power_now');
        let watts = 0.0;
        if (powerUwh) {
            watts = parseInt(powerUwh, 10) / 1e6;
        }

        let capStr = readFile('/sys/class/power_supply/BAT1/capacity') ||
                     readFile('/sys/class/power_supply/BAT0/capacity') || '100';

        let acad = readFile('/sys/class/power_supply/ACAD/online') ||
                   readFile('/sys/class/power_supply/AC/online');
        let onAc = (acad === '1');

        let timeNow = '';
        try {
            timeNow = GLib.DateTime.new_now_local().format('%H:%M') + '  |  ';
        } catch (_) {}

        // Check if video/music is actively playing
        const media = getActiveMediaInfo();
        let mediaText = '';
        if (media && media.title) {
            let shortTitle = media.title.length > 22 ? media.title.substring(0, 20) + '…' : media.title;
            mediaText = `${shortTitle}  |  `;
            if (this._mediaItem) {
                this._mediaItem.label.text = `${media.title} (${media.artist || 'Oynatılıyor'})`;
            }
        } else if (this._mediaItem) {
            this._mediaItem.label.text = 'Medya: Boşta (Oynatıcı Bekleniyor)';
        }

        if (onAc) {
            if (watts > 1.0) {
                this._label.text = `${timeNow}${mediaText}${watts.toFixed(1)}W • %${capStr} AC`;
            } else {
                this._label.text = `${timeNow}${mediaText}%${capStr} AC`;
            }
        } else {
            if (watts > 0.0) {
                this._label.text = `${timeNow}${mediaText}${watts.toFixed(1)}W • %${capStr}`;
            } else {
                this._label.text = `${timeNow}${mediaText}%${capStr}`;
            }
        }

        // Update Conservation Mode switch state
        let cm = readFile(CONSERVATION_NODE);
        if (cm !== null) {
            this._cmSwitch.setToggleState(cm === '1');
        }

        // Update ToF state
        let sensorStatus = readFile('/run/ff-power-manager/presence.state') || 'disabled';
        this._tofSwitch.setToggleState(sensorStatus !== 'disabled');

        let dist = readFile('/run/ff-power-manager/sensor_telemetry.json');
        if (dist && this._subHeader) {
            try {
                let tel = JSON.parse(dist);
                if (tel.active) {
                    this._subHeader.label.text = `ToF: ${tel.distance_cm} cm | ${tel.state.toUpperCase()} | ${watts.toFixed(1)} W`;
                }
            } catch (e) {}
        }
    }

    destroy() {
        if (this._timerId) {
            GLib.source_remove(this._timerId);
            this._timerId = 0;
        }
        super.destroy();
    }
});

export default class FFPowerIndicatorExtension extends Extension {
    enable() {
        this._indicator = new FFPowerIndicator();
        Main.panel.addToStatusArea('ff-power-indicator', this._indicator, 0, 'center');
    }

    disable() {
        if (this._indicator) {
            this._indicator.destroy();
            this._indicator = null;
        }
    }
}
