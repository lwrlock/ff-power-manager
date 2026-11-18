from __future__ import annotations

import math
import random
import time

import cairo
import gi

gi.require_version('Gtk', '4.0')
from gi.repository import GLib, Gtk

from .core import on_battery_from_sysfs


class CosmicBackdrop(Gtk.DrawingArea):
    """Animated purple cosmic space background with nebulae, rotating planets, orbiting moon, and shooting stars."""

    def __init__(self) -> None:
        super().__init__()
        self.set_hexpand(True)
        self.set_vexpand(True)
        self.set_can_target(False)

        self._t0 = time.monotonic()
        self._last_frame = self._t0
        self._phase = 0.0
        self._enabled = True
        self._timer_id = 0
        self._stars = self._init_stars(145)
        self._meteors = self._init_meteors(4)
        self._bat_check_at = 0.0
        self._on_bat = False

        self.set_draw_func(self._on_draw)
        self._schedule_next(33)

    @staticmethod
    def _init_stars(count: int) -> list[dict]:
        rng = random.Random(20261118)
        palette = [
            (0.95, 0.93, 1.0),
            (0.85, 0.72, 1.0),
            (0.65, 0.85, 1.0),
            (0.98, 0.75, 0.95),
        ]
        stars = []
        for idx in range(count):
            depth = 0.25 + (idx % 3) * 0.35
            stars.append({
                'x': rng.random(),
                'y': rng.random(),
                'r': 0.65 + depth * 1.45,
                'alpha': 0.25 + rng.random() * 0.65,
                'speed': 0.8 + rng.random() * 2.4,
                'phase': rng.random() * math.tau,
                'drift': 0.0012 * depth,
                'color': palette[idx % len(palette)],
            })
        return stars

    @staticmethod
    def _init_meteors(count: int) -> list[dict]:
        rng = random.Random(4242)
        meteors = []
        for i in range(count):
            meteors.append({
                'cooldown': 1.2 + i * 2.7 + rng.random() * 2.5,
                'active': False,
                'progress': 0.0,
                'duration': 0.9 + rng.random() * 0.5,
                'x0': 0.15 + rng.random() * 0.7,
                'y0': 0.04 + rng.random() * 0.35,
                'dx': 0.24 + rng.random() * 0.20,
                'dy': 0.16 + rng.random() * 0.14,
                'hue': i % 2,
            })
        return meteors

    def set_enabled(self, enabled: bool) -> None:
        self._enabled = bool(enabled)
        if not self._enabled and self._timer_id:
            GLib.source_remove(self._timer_id)
            self._timer_id = 0
            self.queue_draw()
        elif self._enabled and not self._timer_id:
            self._last_frame = time.monotonic()
            self._schedule_next(33)

    def is_enabled(self) -> bool:
        return self._enabled

    def _schedule_next(self, delay_ms: int) -> None:
        if self._timer_id:
            GLib.source_remove(self._timer_id)
        self._timer_id = GLib.timeout_add(delay_ms, self._tick)

    def _tick(self) -> bool:
        self._timer_id = 0
        if not self._enabled:
            return GLib.SOURCE_REMOVE

        now = time.monotonic()
        dt = max(0.005, min(0.25, now - self._last_frame))
        self._last_frame = now
        self._phase += dt

        if now - self._bat_check_at >= 6.0:
            self._bat_check_at = now
            self._on_bat = on_battery_from_sysfs()

        rng = random.Random(int(now * 1000) & 0xFFFF)
        for m in self._meteors:
            if m['active']:
                m['progress'] += dt / m['duration']
                if m['progress'] >= 1.0:
                    m['active'] = False
                    m['progress'] = 0.0
                    m['cooldown'] = 2.4 + rng.random() * 4.5
            else:
                m['cooldown'] -= dt
                if m['cooldown'] <= 0.0:
                    m['active'] = True
                    m['progress'] = 0.0
                    m['x0'] = 0.08 + rng.random() * 0.72
                    m['y0'] = 0.03 + rng.random() * 0.35
                    m['dx'] = 0.20 + rng.random() * 0.24
                    m['dy'] = 0.14 + rng.random() * 0.15

        self.queue_draw()
        # Honor battery endurance: 33ms (~30 FPS) on AC, 110ms (~9 FPS) on battery
        self._schedule_next(110 if self._on_bat else 33)
        return GLib.SOURCE_REMOVE

    def _draw_nebula(self, cr: cairo.Context, w: float, h: float, t: float) -> None:
        bg = cairo.LinearGradient(0, 0, w * 0.85, h)
        bg.add_color_stop_rgba(0.0, 0.035, 0.016, 0.085, 1.0)
        bg.add_color_stop_rgba(0.50, 0.095, 0.035, 0.21, 1.0)
        bg.add_color_stop_rgba(1.0, 0.055, 0.025, 0.14, 1.0)
        cr.set_source(bg)
        cr.rectangle(0, 0, w, h)
        cr.fill()

        clouds = [
            (w * (0.20 + 0.02 * math.sin(t * 0.15)), h * 0.24, max(w, h) * 0.45, (0.48, 0.15, 0.78, 0.22)),
            (w * (0.78 + 0.02 * math.cos(t * 0.12)), h * 0.32, max(w, h) * 0.42, (0.32, 0.18, 0.82, 0.20)),
            (w * 0.52, h * (0.82 + 0.02 * math.sin(t * 0.18)), max(w, h) * 0.48, (0.72, 0.18, 0.62, 0.16)),
            (w * 0.18, h * 0.72, max(w, h) * 0.30, (0.12, 0.62, 0.85, 0.10)),
        ]
        for cx, cy, rad, (r, g, b, a) in clouds:
            neb = cairo.RadialGradient(cx, cy, rad * 0.05, cx, cy, rad)
            neb.add_color_stop_rgba(0.0, r, g, b, a)
            neb.add_color_stop_rgba(0.55, r * 0.7, g * 0.7, b * 0.9, a * 0.42)
            neb.add_color_stop_rgba(1.0, r, g, b, 0.0)
            cr.set_source(neb)
            cr.arc(cx, cy, rad, 0, math.tau)
            cr.fill()

    def _draw_stars(self, cr: cairo.Context, w: float, h: float, t: float) -> None:
        for s in self._stars:
            sx = ((s['x'] + t * s['drift']) % 1.0) * w
            sy = s['y'] * h
            twinkle = 0.55 + 0.45 * math.sin(t * s['speed'] + s['phase'])
            a = s['alpha'] * twinkle
            r, g, b = s['color']
            cr.set_source_rgba(r, g, b, a)
            cr.arc(sx, sy, s['r'], 0, math.tau)
            cr.fill()
            if s['r'] > 1.75:
                cr.set_source_rgba(r, g, b, a * 0.22)
                cr.arc(sx, sy, s['r'] * 2.6, 0, math.tau)
                cr.fill()

    def _draw_shooting_stars(self, cr: cairo.Context, w: float, h: float) -> None:
        for m in self._meteors:
            if not m['active']:
                continue
            p = m['progress']
            fade = math.sin(p * math.pi)
            hx = (m['x0'] + m['dx'] * p) * w
            hy = (m['y0'] + m['dy'] * p) * h
            tail = 0.16
            tp = max(0.0, p - tail)
            tx = (m['x0'] + m['dx'] * tp) * w
            ty = (m['y0'] + m['dy'] * tp) * h

            grad = cairo.LinearGradient(tx, ty, hx, hy)
            if m['hue'] == 0:
                grad.add_color_stop_rgba(0.0, 0.65, 0.35, 1.0, 0.0)
                grad.add_color_stop_rgba(0.6, 0.85, 0.65, 1.0, 0.55 * fade)
                grad.add_color_stop_rgba(1.0, 1.0, 1.0, 1.0, 0.95 * fade)
            else:
                grad.add_color_stop_rgba(0.0, 0.22, 0.74, 0.97, 0.0)
                grad.add_color_stop_rgba(0.6, 0.68, 0.88, 1.0, 0.55 * fade)
                grad.add_color_stop_rgba(1.0, 1.0, 1.0, 1.0, 0.95 * fade)

            cr.save()
            cr.set_source(grad)
            cr.set_line_width(2.2)
            cr.set_line_cap(cairo.LINE_CAP_ROUND)
            cr.move_to(tx, ty)
            cr.line_to(hx, hy)
            cr.stroke()

            cr.set_source_rgba(1.0, 1.0, 1.0, 0.9 * fade)
            cr.arc(hx, hy, 2.3, 0, math.tau)
            cr.fill()
            cr.restore()

    def _draw_ringed_planet(self, cr: cairo.Context, cx: float, cy: float, radius: float, t: float) -> None:
        orbit_angle = t * 0.55
        moon_x = cx + math.cos(orbit_angle) * (radius * 2.15)
        moon_y = cy + math.sin(orbit_angle) * (radius * 0.58)
        moon_front = math.sin(orbit_angle) >= 0.0

        def _draw_moon() -> None:
            cr.save()
            mr = max(6.0, radius * 0.16)
            mg = cairo.RadialGradient(moon_x - mr * 0.35, moon_y - mr * 0.35, mr * 0.1, moon_x, moon_y, mr)
            mg.add_color_stop_rgba(0.0, 0.90, 0.95, 1.0, 0.95)
            mg.add_color_stop_rgba(0.6, 0.45, 0.58, 0.92, 0.90)
            mg.add_color_stop_rgba(1.0, 0.10, 0.08, 0.25, 0.95)
            cr.set_source(mg)
            cr.arc(moon_x, moon_y, mr, 0, math.tau)
            cr.fill()
            cr.restore()

        def _draw_ring_half(front: bool) -> None:
            cr.save()
            cr.translate(cx, cy)
            cr.rotate(-0.34)
            cr.scale(1.0, 0.28)
            start_a, end_a = (0.0, math.pi) if front else (math.pi, math.tau)
            for idx, (scale_r, width, col) in enumerate([
                (1.92, radius * 0.16, (0.76, 0.58, 0.99, 0.32)),
                (1.62, radius * 0.12, (0.36, 0.78, 0.98, 0.30)),
                (1.38, radius * 0.08, (0.94, 0.65, 0.96, 0.25)),
            ]):
                cr.set_source_rgba(*col)
                cr.set_line_width(width)
                cr.arc(0, 0, radius * scale_r, start_a, end_a)
                cr.stroke()
            cr.restore()

        if not moon_front:
            _draw_moon()
        _draw_ring_half(front=False)

        # Atmospheric halo
        halo = cairo.RadialGradient(cx, cy, radius * 0.85, cx, cy, radius * 1.45)
        halo.add_color_stop_rgba(0.0, 0.65, 0.35, 0.98, 0.30)
        halo.add_color_stop_rgba(1.0, 0.40, 0.15, 0.80, 0.0)
        cr.set_source(halo)
        cr.arc(cx, cy, radius * 1.45, 0, math.tau)
        cr.fill()

        # Planet body + rotating latitude bands
        cr.save()
        cr.arc(cx, cy, radius, 0, math.tau)
        cr.clip()

        sphere = cairo.RadialGradient(cx - radius * 0.38, cy - radius * 0.35, radius * 0.1, cx, cy, radius * 1.15)
        sphere.add_color_stop_rgba(0.0, 0.82, 0.62, 1.0, 0.98)
        sphere.add_color_stop_rgba(0.55, 0.38, 0.18, 0.68, 0.98)
        sphere.add_color_stop_rgba(1.0, 0.07, 0.03, 0.16, 1.0)
        cr.set_source(sphere)
        cr.paint()

        # Rotating cloud bands across the sphere
        band_shift = math.sin(t * 0.35) * radius * 0.18
        for i, offset in enumerate([-0.55, -0.22, 0.12, 0.44]):
            by = cy + offset * radius + math.cos(t * 0.25 + i) * 2.5
            cr.set_source_rgba(0.92, 0.78, 1.0, 0.10 if i % 2 == 0 else 0.06)
            cr.rectangle(cx - radius - 10 + band_shift, by, radius * 2.2, radius * 0.14)
            cr.fill()

        # Rim light highlight
        rim = cairo.RadialGradient(cx - radius * 0.4, cy - radius * 0.4, radius * 0.72, cx, cy, radius)
        rim.add_color_stop_rgba(0.0, 0.0, 0.0, 0.0, 0.0)
        rim.add_color_stop_rgba(1.0, 0.72, 0.85, 1.0, 0.22)
        cr.set_source(rim)
        cr.paint()
        cr.restore()

        _draw_ring_half(front=True)
        if moon_front:
            _draw_moon()

    def _draw_exoplanet(self, cr: cairo.Context, cx: float, cy: float, radius: float, t: float) -> None:
        cr.save()
        halo = cairo.RadialGradient(cx, cy, radius * 0.8, cx, cy, radius * 1.55)
        halo.add_color_stop_rgba(0.0, 0.25, 0.72, 0.96, 0.20)
        halo.add_color_stop_rgba(1.0, 0.10, 0.30, 0.70, 0.0)
        cr.set_source(halo)
        cr.arc(cx, cy, radius * 1.55, 0, math.tau)
        cr.fill()

        cr.arc(cx, cy, radius, 0, math.tau)
        cr.clip()
        body = cairo.RadialGradient(cx - radius * 0.35, cy - radius * 0.35, radius * 0.1, cx, cy, radius * 1.15)
        body.add_color_stop_rgba(0.0, 0.45, 0.88, 0.98, 0.92)
        body.add_color_stop_rgba(0.55, 0.22, 0.32, 0.72, 0.95)
        body.add_color_stop_rgba(1.0, 0.06, 0.04, 0.18, 1.0)
        cr.set_source(body)
        cr.paint()

        # Rotating surface feature
        drift = ((t * 6.0) % (radius * 2.4)) - radius * 1.2
        cr.set_source_rgba(0.75, 0.95, 1.0, 0.14)
        cr.arc(cx + drift, cy + radius * 0.12, radius * 0.28, 0, math.tau)
        cr.fill()
        cr.restore()

    def _on_draw(self, _area: Gtk.DrawingArea, cr: cairo.Context, w: int, h: int) -> None:
        if w <= 0 or h <= 0:
            return
        t = self._phase
        self._draw_nebula(cr, float(w), float(h), t)
        self._draw_stars(cr, float(w), float(h), t)
        self._draw_shooting_stars(cr, float(w), float(h))

        # Distant exoplanet bottom-left
        exo_r = max(24.0, min(w, h) * 0.055)
        self._draw_exoplanet(cr, w * 0.11, h * 0.82 + math.sin(t * 0.4) * 6.0, exo_r, t)

        # Primary ringed planet top-right
        p_r = max(46.0, min(w, h) * 0.105)
        self._draw_ringed_planet(cr, w * 0.84, h * 0.23 + math.cos(t * 0.35) * 8.0, p_r, t)


class TelemetrySparklineChart(Gtk.DrawingArea):
    """Live Cairo sparkline rendering rolling Power Draw (W) and Package Temp (°C)."""

    def __init__(self) -> None:
        super().__init__()
        self.set_size_request(-1, 155)
        self.set_hexpand(True)
        self._samples: list[dict] = []
        self.set_draw_func(self._on_draw)

    def set_samples(self, samples: list[dict]) -> None:
        self._samples = samples[-90:] if samples else []
        self.queue_draw()

    def _on_draw(self, _area: Gtk.DrawingArea, cr: cairo.Context, w: int, h: int) -> None:
        if w <= 20 or h <= 20:
            return

        pad_l, pad_r, pad_t, pad_b = 42.0, 16.0, 18.0, 22.0
        plot_w = max(10.0, w - pad_l - pad_r)
        plot_h = max(10.0, h - pad_t - pad_b)

        # Grid lines
        cr.set_font_size(10.0)
        for frac in (0.0, 0.5, 1.0):
            y = pad_t + plot_h * (1.0 - frac)
            cr.set_source_rgba(0.65, 0.55, 0.95, 0.16)
            cr.set_line_width(1.0)
            cr.move_to(pad_l, y)
            cr.line_to(pad_l + plot_w, y)
            cr.stroke()

        if len(self._samples) < 2:
            cr.set_source_rgba(0.82, 0.78, 0.98, 0.65)
            cr.move_to(pad_l + 8, pad_t + plot_h * 0.5)
            cr.show_text('Collecting live wattage & thermal telemetry from ff-power-autoboost...')
            return

        watts_vals = [float(s.get('watts', 0.0) or 0.0) for s in self._samples]
        temp_vals = [float(s.get('temp_c', 0.0) or 0.0) for s in self._samples]
        max_w = max(12.0, math.ceil(max(watts_vals) / 10.0) * 10.0)

        # Y-axis watt labels
        cr.set_source_rgba(0.70, 0.85, 1.0, 0.72)
        for frac, val in ((0.0, 0.0), (0.5, max_w * 0.5), (1.0, max_w)):
            y = pad_t + plot_h * (1.0 - frac) + 3.0
            cr.move_to(6.0, y)
            cr.show_text(f'{val:.0f}W')

        n = len(self._samples)
        pts_w = [
            (pad_l + (i / (n - 1)) * plot_w, pad_t + plot_h * (1.0 - min(1.0, watts_vals[i] / max_w)))
            for i in range(n)
        ]

        # Gradient fill under power curve
        fill_grad = cairo.LinearGradient(0, pad_t, 0, pad_t + plot_h)
        fill_grad.add_color_stop_rgba(0.0, 0.56, 0.32, 0.98, 0.42)
        fill_grad.add_color_stop_rgba(0.6, 0.22, 0.74, 0.97, 0.16)
        fill_grad.add_color_stop_rgba(1.0, 0.22, 0.74, 0.97, 0.0)

        cr.move_to(pts_w[0][0], pad_t + plot_h)
        for px, py in pts_w:
            cr.line_to(px, py)
        cr.line_to(pts_w[-1][0], pad_t + plot_h)
        cr.close_path()
        cr.set_source(fill_grad)
        cr.fill()

        # Glowing wattage stroke
        cr.set_source_rgba(0.22, 0.82, 0.99, 0.95)
        cr.set_line_width(2.4)
        cr.set_line_join(cairo.LINE_JOIN_ROUND)
        cr.move_to(*pts_w[0])
        for px, py in pts_w[1:]:
            cr.line_to(px, py)
        cr.stroke()

        # Package Temperature dashed overlay (30°C - 100°C range)
        if any(t > 0 for t in temp_vals):
            cr.save()
            cr.set_dash([5.0, 4.0])
            cr.set_source_rgba(0.96, 0.45, 0.71, 0.85)
            cr.set_line_width(1.7)
            pts_t = [
                (pad_l + (i / (n - 1)) * plot_w, pad_t + plot_h * (1.0 - max(0.0, min(1.0, (temp_vals[i] - 30.0) / 70.0))))
                for i in range(n)
            ]
            cr.move_to(*pts_t[0])
            for px, py in pts_t[1:]:
                cr.line_to(px, py)
            cr.stroke()
            cr.restore()

        # Legend
        cur_w = watts_vals[-1]
        cur_t = temp_vals[-1]
        cr.set_source_rgba(0.88, 0.95, 1.0, 0.88)
        cr.move_to(pad_l + 6, h - 5)
        cr.show_text(f'Power: {cur_w:.1f} W   •   CPU Temp: {cur_t:.0f}°C   •   Samples: {n}')
