from __future__ import annotations

import math
import random
import time

import cairo
import gi

gi.require_version('Gdk', '4.0')
gi.require_version('Gtk', '4.0')
from gi.repository import Gdk, GLib, Gtk

from .core import on_battery_from_sysfs


def _surface_to_texture(surf: cairo.ImageSurface) -> Gdk.Texture:
    """Convert a Cairo ARGB32 surface into a GPU-resident Gdk.MemoryTexture."""
    surf.flush()
    fmt = getattr(Gdk.MemoryFormat, 'B8G8R8A8_PREMULTIPLIED', Gdk.MemoryFormat.B8G8R8A8)
    raw = GLib.Bytes.new(bytes(surf.get_data()))
    return Gdk.MemoryTexture.new(surf.get_width(), surf.get_height(), fmt, raw, surf.get_stride())


def _make_picture(surf: cairo.ImageSurface) -> Gtk.Picture:
    pic = Gtk.Picture.new_for_paintable(_surface_to_texture(surf))
    pic.set_size_request(surf.get_width(), surf.get_height())
    pic.set_can_shrink(False)
    pic.set_can_target(False)
    return pic


class _MeteorCanvas(Gtk.DrawingArea):
    """Lightweight overlay canvas active ONLY while a shooting star is streaking."""

    def __init__(self, meteors: list[dict]) -> None:
        super().__init__()
        self.set_hexpand(True)
        self.set_vexpand(True)
        self.set_can_target(False)
        self._meteors = meteors
        self.set_draw_func(self._on_draw)

    def _on_draw(self, _area: Gtk.DrawingArea, cr: cairo.Context, w: int, h: int) -> None:
        if w <= 0 or h <= 0:
            return
        CosmicBackdrop._draw_shooting_stars_on(self._meteors, cr, float(w), float(h))


class CosmicBackdrop(Gtk.Overlay):
    """Zero-lag GPU-cached cosmic space backdrop: static VRAM nebula + hardware-moved planet sprites."""

    def __init__(self) -> None:
        super().__init__()
        self.set_hexpand(True)
        self.set_vexpand(True)
        self.set_can_target(False)

        self._phase = 0.0
        self._last_frame = time.monotonic()
        self._enabled = True
        self._timer_id = 0
        self._scroll_pause_until = 0.0
        self._bat_check_at = 0.0
        self._on_bat = False

        self._stars = self._init_stars(140, seed=20261118)
        self._meteors = self._init_meteors(3)
        self._meteor_was_active = False

        # Layer 0: Static full-window cosmic nebula & starfield baked ONCE into VRAM
        bg_surf = self._bake_nebula_surface(1600, 1000)
        self._bg_pic = Gtk.Picture.new_for_paintable(_surface_to_texture(bg_surf))
        self._bg_pic.set_hexpand(True)
        self._bg_pic.set_vexpand(True)
        self._bg_pic.set_can_target(False)
        if hasattr(Gtk, 'ContentFit'):
            self._bg_pic.set_content_fit(Gtk.ContentFit.COVER)
        self.set_child(self._bg_pic)

        # Layer 1: GPU-resident floating cosmic sprites moved cheaply via Gtk.Fixed
        self._fixed = Gtk.Fixed()
        self._fixed.set_hexpand(True)
        self._fixed.set_vexpand(True)
        self._fixed.set_can_target(False)
        self.add_overlay(self._fixed)

        self._exo_pic = _make_picture(self._bake_exoplanet_surface(42.0))
        self._moon_back = _make_picture(self._bake_moon_surface(10.0))
        self._planet_pic = _make_picture(self._bake_ringed_planet_surface(74.0))
        self._moon_front = _make_picture(self._bake_moon_surface(10.0))
        self._twinkle_a = _make_picture(self._bake_twinkle_star(14.0, (0.88, 0.72, 1.0)))
        self._twinkle_b = _make_picture(self._bake_twinkle_star(12.0, (0.45, 0.88, 1.0)))

        for w in (self._moon_back, self._exo_pic, self._planet_pic, self._moon_front, self._twinkle_a, self._twinkle_b):
            self._fixed.put(w, 0, 0)

        # Layer 2: Tiny transient shooting-star canvas (only invalidated during meteor flight)
        self._meteor_canvas = _MeteorCanvas(self._meteors)
        self.add_overlay(self._meteor_canvas)

        self._schedule_next(40)

    def notify_scroll(self) -> None:
        """Pause background motion briefly while user scrolls to guarantee locked input frame rates."""
        self._scroll_pause_until = time.monotonic() + 0.18

    def set_enabled(self, enabled: bool) -> None:
        self._enabled = bool(enabled)
        self._fixed.set_visible(self._enabled)
        self._meteor_canvas.set_visible(self._enabled)
        if not self._enabled and self._timer_id:
            GLib.source_remove(self._timer_id)
            self._timer_id = 0
        elif self._enabled and not self._timer_id:
            self._last_frame = time.monotonic()
            self._schedule_next(40)

    def is_enabled(self) -> bool:
        return self._enabled

    @staticmethod
    def _init_stars(count: int, seed: int = 20261118) -> list[dict]:
        rng = random.Random(seed)
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
                'r': 0.7 + depth * 1.35,
                'alpha': 0.28 + rng.random() * 0.65,
                'speed': 0.8 + rng.random() * 2.0,
                'phase': rng.random() * math.tau,
                'drift': 0.0008 * depth,
                'color': palette[idx % len(palette)],
            })
        return stars

    @staticmethod
    def _init_meteors(count: int) -> list[dict]:
        rng = random.Random(4242)
        return [
            {
                'cooldown': 1.2 + i * 2.6 + rng.random() * 2.2,
                'active': False,
                'progress': 0.0,
                'duration': 0.90 + rng.random() * 0.45,
                'x0': 0.12 + rng.random() * 0.68,
                'y0': 0.04 + rng.random() * 0.32,
                'dx': 0.20 + rng.random() * 0.22,
                'dy': 0.13 + rng.random() * 0.14,
                'hue': i % 2,
            }
            for i in range(count)
        ]

    @classmethod
    def _draw_nebula(cls, cr: cairo.Context, w: float, h: float, _t: float = 0.0) -> None:
        bg = cairo.LinearGradient(0, 0, w * 0.85, h)
        bg.add_color_stop_rgba(0.0, 0.030, 0.015, 0.075, 1.0)
        bg.add_color_stop_rgba(0.50, 0.088, 0.032, 0.200, 1.0)
        bg.add_color_stop_rgba(1.0, 0.048, 0.020, 0.125, 1.0)
        cr.set_source(bg)
        cr.rectangle(0, 0, w, h)
        cr.fill()

        clouds = [
            (w * 0.18, h * 0.24, max(w, h) * 0.46, (0.50, 0.16, 0.82, 0.22)),
            (w * 0.80, h * 0.30, max(w, h) * 0.42, (0.34, 0.18, 0.85, 0.20)),
            (w * 0.55, h * 0.82, max(w, h) * 0.48, (0.74, 0.18, 0.64, 0.15)),
            (w * 0.15, h * 0.76, max(w, h) * 0.32, (0.12, 0.65, 0.88, 0.11)),
        ]
        for cx, cy, rad, (r, g, b, a) in clouds:
            neb = cairo.RadialGradient(cx, cy, rad * 0.05, cx, cy, rad)
            neb.add_color_stop_rgba(0.0, r, g, b, a)
            neb.add_color_stop_rgba(0.55, r * 0.7, g * 0.7, b * 0.9, a * 0.40)
            neb.add_color_stop_rgba(1.0, r, g, b, 0.0)
            cr.set_source(neb)
            cr.arc(cx, cy, rad, 0, math.tau)
            cr.fill()

    def _bake_nebula_surface(self, w: int, h: int) -> cairo.ImageSurface:
        surf = cairo.ImageSurface(cairo.FORMAT_ARGB32, w, h)
        cr = cairo.Context(surf)
        self._draw_nebula(cr, float(w), float(h), 0.0)
        for s in self._stars:
            r, g, b = s['color']
            cr.set_source_rgba(r, g, b, s['alpha'] * 0.82)
            cr.arc(s['x'] * w, s['y'] * h, s['r'], 0, math.tau)
            cr.fill()
            if s['r'] > 1.7:
                cr.set_source_rgba(r, g, b, s['alpha'] * 0.20)
                cr.arc(s['x'] * w, s['y'] * h, s['r'] * 2.5, 0, math.tau)
                cr.fill()
        return surf

    @staticmethod
    def _draw_exoplanet(cr: cairo.Context, cx: float, cy: float, radius: float, _t: float = 0.0) -> None:
        cr.save()
        halo = cairo.RadialGradient(cx, cy, radius * 0.8, cx, cy, radius * 1.55)
        halo.add_color_stop_rgba(0.0, 0.25, 0.72, 0.96, 0.22)
        halo.add_color_stop_rgba(1.0, 0.10, 0.30, 0.70, 0.0)
        cr.set_source(halo)
        cr.arc(cx, cy, radius * 1.55, 0, math.tau)
        cr.fill()

        cr.arc(cx, cy, radius, 0, math.tau)
        cr.clip()
        body = cairo.RadialGradient(cx - radius * 0.35, cy - radius * 0.35, radius * 0.1, cx, cy, radius * 1.15)
        body.add_color_stop_rgba(0.0, 0.45, 0.88, 0.98, 0.94)
        body.add_color_stop_rgba(0.55, 0.22, 0.32, 0.72, 0.96)
        body.add_color_stop_rgba(1.0, 0.06, 0.04, 0.18, 1.0)
        cr.set_source(body)
        cr.paint()
        cr.restore()

    def _bake_exoplanet_surface(self, radius: float) -> cairo.ImageSurface:
        pad = int(math.ceil(radius * 1.65))
        surf = cairo.ImageSurface(cairo.FORMAT_ARGB32, pad * 2, pad * 2)
        cr = cairo.Context(surf)
        self._draw_exoplanet(cr, float(pad), float(pad), radius, 0.0)
        return surf

    @staticmethod
    def _draw_ringed_planet(cr: cairo.Context, cx: float, cy: float, radius: float, _t: float = 0.0) -> None:
        def _ring_half(front: bool) -> None:
            cr.save()
            cr.translate(cx, cy)
            cr.rotate(-0.34)
            cr.scale(1.0, 0.28)
            start_a, end_a = (0.0, math.pi) if front else (math.pi, math.tau)
            for scale_r, width, col in [
                (1.90, radius * 0.15, (0.76, 0.58, 0.99, 0.34)),
                (1.60, radius * 0.11, (0.36, 0.78, 0.98, 0.30)),
                (1.36, radius * 0.08, (0.94, 0.65, 0.96, 0.24)),
            ]:
                cr.set_source_rgba(*col)
                cr.set_line_width(width)
                cr.arc(0, 0, radius * scale_r, start_a, end_a)
                cr.stroke()
            cr.restore()

        _ring_half(front=False)
        halo = cairo.RadialGradient(cx, cy, radius * 0.85, cx, cy, radius * 1.45)
        halo.add_color_stop_rgba(0.0, 0.65, 0.35, 0.98, 0.30)
        halo.add_color_stop_rgba(1.0, 0.40, 0.15, 0.80, 0.0)
        cr.set_source(halo)
        cr.arc(cx, cy, radius * 1.45, 0, math.tau)
        cr.fill()

        cr.save()
        cr.arc(cx, cy, radius, 0, math.tau)
        cr.clip()
        sphere = cairo.RadialGradient(cx - radius * 0.38, cy - radius * 0.35, radius * 0.1, cx, cy, radius * 1.15)
        sphere.add_color_stop_rgba(0.0, 0.82, 0.62, 1.0, 0.98)
        sphere.add_color_stop_rgba(0.55, 0.38, 0.18, 0.68, 0.98)
        sphere.add_color_stop_rgba(1.0, 0.07, 0.03, 0.16, 1.0)
        cr.set_source(sphere)
        cr.paint()
        for i, offset in enumerate([-0.52, -0.20, 0.14, 0.45]):
            by = cy + offset * radius
            cr.set_source_rgba(0.92, 0.78, 1.0, 0.09 if i % 2 == 0 else 0.05)
            cr.rectangle(cx - radius - 4, by, radius * 2.1, radius * 0.14)
            cr.fill()
        cr.restore()
        _ring_half(front=True)

    def _bake_ringed_planet_surface(self, radius: float) -> cairo.ImageSurface:
        w = int(math.ceil(radius * 4.2))
        h = int(math.ceil(radius * 3.1))
        surf = cairo.ImageSurface(cairo.FORMAT_ARGB32, w, h)
        cr = cairo.Context(surf)
        self._draw_ringed_planet(cr, w / 2.0, h / 2.0, radius, 0.0)
        return surf

    @staticmethod
    def _bake_moon_surface(radius: float) -> cairo.ImageSurface:
        dim = int(math.ceil(radius * 3.0))
        surf = cairo.ImageSurface(cairo.FORMAT_ARGB32, dim, dim)
        cr = cairo.Context(surf)
        c = dim / 2.0
        g = cairo.RadialGradient(c - radius * 0.3, c - radius * 0.3, radius * 0.1, c, c, radius)
        g.add_color_stop_rgba(0.0, 0.92, 0.96, 1.0, 0.98)
        g.add_color_stop_rgba(0.65, 0.46, 0.60, 0.95, 0.95)
        g.add_color_stop_rgba(1.0, 0.12, 0.09, 0.25, 1.0)
        cr.set_source(g)
        cr.arc(c, c, radius, 0, math.tau)
        cr.fill()
        return surf

    @staticmethod
    def _bake_twinkle_star(radius: float, col: tuple[float, float, float]) -> cairo.ImageSurface:
        dim = int(math.ceil(radius * 3.0))
        surf = cairo.ImageSurface(cairo.FORMAT_ARGB32, dim, dim)
        cr = cairo.Context(surf)
        c = dim / 2.0
        r, g, b = col
        glow = cairo.RadialGradient(c, c, 0.5, c, c, radius * 1.4)
        glow.add_color_stop_rgba(0.0, 1.0, 1.0, 1.0, 0.95)
        glow.add_color_stop_rgba(0.35, r, g, b, 0.55)
        glow.add_color_stop_rgba(1.0, r, g, b, 0.0)
        cr.set_source(glow)
        cr.arc(c, c, radius * 1.4, 0, math.tau)
        cr.fill()
        return surf

    @staticmethod
    def _draw_shooting_stars_on(meteors: list[dict], cr: cairo.Context, w: float, h: float) -> None:
        for m in meteors:
            if not m['active']:
                continue
            p = m['progress']
            fade = math.sin(p * math.pi)
            hx = (m['x0'] + m['dx'] * p) * w
            hy = (m['y0'] + m['dy'] * p) * h
            tp = max(0.0, p - 0.18)
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

            cr.set_source(grad)
            cr.set_line_width(2.2)
            cr.set_line_cap(cairo.LINE_CAP_ROUND)
            cr.move_to(tx, ty)
            cr.line_to(hx, hy)
            cr.stroke()

            cr.set_source_rgba(1.0, 1.0, 1.0, 0.9 * fade)
            cr.arc(hx, hy, 2.2, 0, math.tau)
            cr.fill()

    def _draw_shooting_stars(self, cr: cairo.Context, w: float, h: float) -> None:
        self._draw_shooting_stars_on(self._meteors, cr, w, h)

    def _schedule_next(self, delay_ms: int) -> None:
        if self._timer_id:
            GLib.source_remove(self._timer_id)
        self._timer_id = GLib.timeout_add(delay_ms, self._tick)

    def _tick(self) -> bool:
        self._timer_id = 0
        if not self._enabled:
            return GLib.SOURCE_REMOVE

        now = time.monotonic()
        if now < self._scroll_pause_until:
            self._schedule_next(60)
            return GLib.SOURCE_REMOVE

        dt = max(0.01, min(0.25, now - self._last_frame))
        self._last_frame = now
        self._phase += dt

        if now - self._bat_check_at >= 6.0:
            self._bat_check_at = now
            self._on_bat = on_battery_from_sysfs()

        w = max(600, self.get_width())
        h = max(400, self.get_height())
        t = self._phase

        # Hardware sprite moves (VRAM textures already uploaded — 0 pixel draws!)
        px = w * 0.87 - self._planet_pic.get_width() / 2.0
        py = h * 0.21 + math.cos(t * 0.45) * 7.0 - self._planet_pic.get_height() / 2.0
        self._fixed.move(self._planet_pic, px, py)

        ex = w * 0.09 - self._exo_pic.get_width() / 2.0
        ey = h * 0.82 + math.sin(t * 0.40) * 6.0 - self._exo_pic.get_height() / 2.0
        self._fixed.move(self._exo_pic, ex, ey)

        orbit = t * 0.65
        pcx = w * 0.87
        pcy = h * 0.21 + math.cos(t * 0.45) * 7.0
        mx = pcx + math.cos(orbit) * 145.0 - self._moon_front.get_width() / 2.0
        my = pcy + math.sin(orbit) * 42.0 - self._moon_front.get_height() / 2.0
        front = math.sin(orbit) >= 0.0
        self._moon_front.set_visible(front)
        self._moon_back.set_visible(not front)
        self._fixed.move(self._moon_front if front else self._moon_back, mx, my)

        self._fixed.move(self._twinkle_a, w * 0.28, h * 0.16)
        self._twinkle_a.set_opacity(0.35 + 0.65 * (0.5 + 0.5 * math.sin(t * 1.9)))
        self._fixed.move(self._twinkle_b, w * 0.63, h * 0.72)
        self._twinkle_b.set_opacity(0.30 + 0.70 * (0.5 + 0.5 * math.cos(t * 1.5)))

        # Advance shooting stars and ONLY invalidate tiny transient meteor canvas when active
        rng = random.Random(int(now * 1000) & 0xFFFF)
        any_active = False
        for m in self._meteors:
            if m['active']:
                any_active = True
                m['progress'] += dt / m['duration']
                if m['progress'] >= 1.0:
                    m['active'] = False
                    m['progress'] = 0.0
                    m['cooldown'] = 2.4 + rng.random() * 4.5
            else:
                m['cooldown'] -= dt
                if m['cooldown'] <= 0.0:
                    m['active'] = True
                    any_active = True
                    m['progress'] = 0.0
                    m['x0'] = 0.08 + rng.random() * 0.72
                    m['y0'] = 0.03 + rng.random() * 0.35
                    m['dx'] = 0.20 + rng.random() * 0.24
                    m['dy'] = 0.14 + rng.random() * 0.15

        if any_active or self._meteor_was_active:
            self._meteor_canvas.queue_draw()
        self._meteor_was_active = any_active

        self._schedule_next(100 if self._on_bat else 40)
        return GLib.SOURCE_REMOVE


class TelemetrySparklineChart(Gtk.DrawingArea):
    """Live Cairo sparkline rendering rolling Power Draw (W) and Package Temp (°C)."""

    def __init__(self) -> None:
        super().__init__()
        self.set_size_request(-1, 175)
        self.set_hexpand(True)
        self._samples: list[dict] = []
        self.set_draw_func(self._on_draw)

    def set_samples(self, samples: list[dict]) -> None:
        self._samples = samples[-90:] if samples else []
        self.queue_draw()

    def _on_draw(self, _area: Gtk.DrawingArea, cr: cairo.Context, w: int, h: int) -> None:
        if w <= 20 or h <= 20:
            return

        pad_l, pad_r, pad_t, pad_b = 42.0, 42.0, 16.0, 22.0
        plot_w = max(10.0, w - pad_l - pad_r)
        plot_h = max(10.0, h - pad_t - pad_b)

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
            cr.show_text('Collecting live wattage & thermal telemetry...')
            return

        watts_vals = [float(s.get('watts', 0.0) or 0.0) for s in self._samples]
        temp_vals = [float(s.get('temp_c', 0.0) or 0.0) for s in self._samples]
        max_w = max(12.0, math.ceil(max(watts_vals) / 10.0) * 10.0)

        cr.set_source_rgba(0.70, 0.85, 1.0, 0.75)
        for frac, val in ((0.0, 0.0), (0.5, max_w * 0.5), (1.0, max_w)):
            y = pad_t + plot_h * (1.0 - frac) + 3.0
            cr.move_to(6.0, y)
            cr.show_text(f'{val:.0f}W')

        cr.set_source_rgba(0.96, 0.55, 0.78, 0.72)
        for frac, deg in ((0.0, 30), (0.5, 65), (1.0, 100)):
            y = pad_t + plot_h * (1.0 - frac) + 3.0
            cr.move_to(w - 35.0, y)
            cr.show_text(f'{deg}°C')

        n = len(self._samples)
        pts_w = [
            (pad_l + (i / (n - 1)) * plot_w, pad_t + plot_h * (1.0 - min(1.0, watts_vals[i] / max_w)))
            for i in range(n)
        ]

        fill_grad = cairo.LinearGradient(0, pad_t, 0, pad_t + plot_h)
        fill_grad.add_color_stop_rgba(0.0, 0.56, 0.32, 0.98, 0.44)
        fill_grad.add_color_stop_rgba(0.6, 0.22, 0.74, 0.97, 0.16)
        fill_grad.add_color_stop_rgba(1.0, 0.22, 0.74, 0.97, 0.0)

        cr.move_to(pts_w[0][0], pad_t + plot_h)
        for px, py in pts_w:
            cr.line_to(px, py)
        cr.line_to(pts_w[-1][0], pad_t + plot_h)
        cr.close_path()
        cr.set_source(fill_grad)
        cr.fill()

        cr.set_source_rgba(0.22, 0.82, 0.99, 0.96)
        cr.set_line_width(2.4)
        cr.set_line_join(cairo.LINE_JOIN_ROUND)
        cr.move_to(*pts_w[0])
        for px, py in pts_w[1:]:
            cr.line_to(px, py)
        cr.stroke()

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

        cur_w = watts_vals[-1]
        cur_t = temp_vals[-1]
        cr.set_source_rgba(0.88, 0.95, 1.0, 0.88)
        cr.move_to(pad_l + 6, h - 5)
        cr.show_text(f'Power: {cur_w:.1f} W   •   CPU Temp: {cur_t:.0f}°C   •   Samples: {n}')
