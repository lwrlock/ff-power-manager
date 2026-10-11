import GObject from 'gi://GObject';
import St from 'gi://St';
import Clutter from 'gi://Clutter';
import GLib from 'gi://GLib';
import Gio from 'gi://Gio';
import * as Main from 'resource:///org/gnome/shell/ui/main.js';
import * as PanelMenu from 'resource:///org/gnome/shell/ui/panelMenu.js';
import * as PopupMenu from 'resource:///org/gnome/shell/ui/popupMenu.js';
import {Extension} from 'resource:///org/gnome/shell/extensions/extension.js';

const CONSERVATION_NODE = '/sys/bus/platform/drivers/ideapad_acpi/VPC2004:00/conservation_mode';
const SENSOR_SERVICE = 'ff-presence-sensor.service';

function readFile(path) {
    try {
        let [ok, contents] = GLib.file_get_contents(path);
        if (ok) {
            let decoder = new TextDecoder('utf-8');
            return decoder.decode(contents).trim();
        }
    } catch (e) {
        // file doesn't exist or unreadable
    }
    return null;
}

const FFPowerIndicator = GObject.registerClass(
class FFPowerIndicator extends PanelMenu.Button {
    _init() {
        super._init(0.0, 'FF Power Indicator', false);

        this._box = new St.BoxLayout({
            style_class: 'panel-status-indicators-box',
        });

        this._label = new St.Label({
            text: '⚡ ...',
            y_align: Clutter.ActorAlign.CENTER,
            style_class: 'ff-power-label',
        });

        this._box.add_child(this._label);
        this.add_child(this._box);

        this._buildMenu();
        this._updateTelemetry();

        this._timerId = GLib.timeout_add_seconds(GLib.PRIORITY_DEFAULT, 3, () => {
            this._updateTelemetry();
            return GLib.SOURCE_CONTINUE;
        });
    }

    _buildMenu() {
        // Title Header
        let headerItem = new PopupMenu.PopupMenuItem('FF Power Manager (v1.2.0)', {reactive: false});
        headerItem.label.style = 'font-weight: bold; font-size: 13px; color: #38bdf8;';
        this.menu.addMenuItem(headerItem);

        this._subHeader = new PopupMenu.PopupMenuItem('Samsung 2.8K OLED • Lenovo IdeaPad', {reactive: false});
        this._subHeader.label.style = 'font-size: 11px; color: #94a3b8;';
        this.menu.addMenuItem(this._subHeader);

        this.menu.addMenuItem(new PopupMenu.PopupSeparatorMenuItem());

        // Quick Profiles
        let profilesSection = new PopupMenu.PopupMenuSection();
        
        let pRec = new PopupMenu.PopupMenuItem('⚡ Recommended (Balanced)');
        pRec.connect('activate', () => this._runCmd('/usr/local/bin/ffctl apply'));
        profilesSection.addMenuItem(pRec);

        let pExt = new PopupMenu.PopupMenuItem('🚀 Extreme Performance');
        pExt.connect('activate', () => this._runCmd('/usr/local/bin/ffctl apply extreme_performance'));
        profilesSection.addMenuItem(pExt);

        let pBat = new PopupMenu.PopupMenuItem('🍃 Maximum Battery Saver');
        pBat.connect('activate', () => this._runCmd('/usr/local/bin/ffctl apply max_battery'));
        profilesSection.addMenuItem(pBat);

        let pQuiet = new PopupMenu.PopupMenuItem('❄️ Cool & Quiet');
        pQuiet.connect('activate', () => this._runCmd('/usr/local/bin/ffctl apply cool_quiet'));
        profilesSection.addMenuItem(pQuiet);

        this.menu.addMenuItem(profilesSection);
        this.menu.addMenuItem(new PopupMenu.PopupSeparatorMenuItem());

        // Toggles
        this._cmSwitch = new PopupMenu.PopupSwitchMenuItem('80% Battery Conservation', false);
        this._cmSwitch.connect('toggled', (item, state) => {
            this._runCmd(`/usr/local/bin/ffctl conservation ${state ? 'on' : 'off'}`);
        });
        this.menu.addMenuItem(this._cmSwitch);

        this._tofSwitch = new PopupMenu.PopupSwitchMenuItem('ToF Presence Sensor Radar', true);
        this._tofSwitch.connect('toggled', (item, state) => {
            let act = state ? 'enable-now' : 'disable-now';
            this._runCmd(`/usr/local/lib/ff-power-manager/ff-power-helper sensor-service ${act}`);
        });
        this.menu.addMenuItem(this._tofSwitch);

        this.menu.addMenuItem(new PopupMenu.PopupSeparatorMenuItem());

        // Launchers
        let guiItem = new PopupMenu.PopupMenuItem('Open Control Center (GUI)');
        guiItem.connect('activate', () => this._runCmd('ff-power-manager'));
        this.menu.addMenuItem(guiItem);

        let tuiItem = new PopupMenu.PopupMenuItem('Launch Terminal Dashboard (ff-tui)');
        tuiItem.connect('activate', () => {
            this._runCmd('blackbox-terminal -e /usr/local/bin/ff-tui || gnome-terminal -- /usr/local/bin/ff-tui || ptyxis -e /usr/local/bin/ff-tui');
        });
        this.menu.addMenuItem(tuiItem);
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

        if (onAc) {
            if (watts > 1.0) {
                this._label.text = `🔌 ${watts.toFixed(1)} W (${capStr}%)`;
            } else {
                this._label.text = `🔌 AC (${capStr}%)`;
            }
        } else {
            if (watts > 0.0) {
                this._label.text = `⚡ ${watts.toFixed(1)} W (${capStr}%)`;
            } else {
                this._label.text = `⚡ ${capStr}%`;
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
