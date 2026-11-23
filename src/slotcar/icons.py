"""Racing icon set, drawn procedurally with Pillow.

Every icon is drawn on a 100x100 unit grid at high resolution as a single
alpha mask, then down-sampled (anti-aliased) and tinted. This means icons are
crisp at any size/DPI and recolourable to match the theme - no external icon
fonts or image packs required.

Run ``python tools/generate_assets.py`` to export PNGs and the app ``.ico``.
"""

from __future__ import annotations

import math
from functools import lru_cache
from typing import Callable

from PIL import Image, ImageDraw, ImageFilter

from .theme import hex_to_rgb

SS = 8          # supersample factor relative to a 64px icon
GRID = 100      # drawing units


class Pen:
    """Tiny helper that maps 0-100 units to supersampled pixels on an 'L' mask."""

    def __init__(self, px: int) -> None:
        self.px = px
        self.k = px / GRID
        self.mask = Image.new("L", (px, px), 0)
        self.d = ImageDraw.Draw(self.mask)

    def _p(self, pts):
        return [(x * self.k, y * self.k) for x, y in pts]

    def _b(self, box):
        x0, y0, x1, y1 = box
        return (x0 * self.k, y0 * self.k, x1 * self.k, y1 * self.k)

    def w(self, width: float) -> int:
        return max(1, round(width * self.k))

    # Drawing primitives -- ``ink=0`` erases (cuts holes).
    def poly(self, pts, ink=255):
        self.d.polygon(self._p(pts), fill=ink)

    def rect(self, box, ink=255, r=0.0):
        if r:
            self.d.rounded_rectangle(self._b(box), radius=r * self.k, fill=ink)
        else:
            self.d.rectangle(self._b(box), fill=ink)

    def ellipse(self, box, ink=255):
        self.d.ellipse(self._b(box), fill=ink)

    def circle(self, cx, cy, r, ink=255):
        self.ellipse((cx - r, cy - r, cx + r, cy + r), ink)

    def ring(self, cx, cy, r, width, ink=255):
        self.d.ellipse(self._b((cx - r, cy - r, cx + r, cy + r)), outline=ink, width=self.w(width))

    def line(self, pts, width, ink=255, round_caps=True):
        pts_px = self._p(pts)
        self.d.line(pts_px, fill=ink, width=self.w(width), joint="curve")
        if round_caps:
            r = width * self.k / 2
            for x, y in (pts_px[0], pts_px[-1]):
                self.d.ellipse((x - r, y - r, x + r, y + r), fill=ink)

    def arc(self, cx, cy, r, start, end, width, ink=255):
        self.d.arc(self._b((cx - r, cy - r, cx + r, cy + r)), start, end, fill=ink, width=self.w(width))

    def pie(self, cx, cy, r, start, end, ink=255):
        self.d.pieslice(self._b((cx - r, cy - r, cx + r, cy + r)), start, end, fill=ink)


def _star(cx, cy, r_out, r_in, points=5, rot=-90):
    pts = []
    for i in range(points * 2):
        r = r_out if i % 2 == 0 else r_in
        a = math.radians(rot + i * 180 / points)
        pts.append((cx + r * math.cos(a), cy + r * math.sin(a)))
    return pts


# ---------------------------------------------------------------------------
# Icon drawings
# ---------------------------------------------------------------------------

def _checkered_flag(p: Pen) -> None:
    p.line([(16, 10), (16, 92)], 6)  # pole
    p.circle(16, 9, 4.5)

    def warp(x, y):  # waving cloth
        return x, y + 5 * math.sin((x - 20) / 70 * 2 * math.pi)

    cols, rows = 5, 4
    x0, x1, y0, y1 = 20, 92, 12, 60
    cw, ch = (x1 - x0) / cols, (y1 - y0) / rows
    for r in range(rows):
        for c in range(cols):
            if (r + c) % 2 == 0:
                xa, xb = x0 + c * cw, x0 + (c + 1) * cw
                ya, yb = y0 + r * ch, y0 + (r + 1) * ch
                p.poly([warp(xa, ya), warp(xb, ya), warp(xb, yb), warp(xa, yb)])
    edge = [warp(x0 + i * (x1 - x0) / 24, y0) for i in range(25)]
    edge += [warp(x1 - i * (x1 - x0) / 24, y1) for i in range(25)]
    p.line(edge + [edge[0]], 3.2, round_caps=False)


def _helmet(p: Pen) -> None:
    p.ellipse((8, 14, 92, 96))
    p.rect((0, 74, 100, 100), ink=0)                       # flat neck line
    p.poly([(46, 70), (93, 60), (90, 80), (80, 86), (46, 86)])  # chin guard
    p.rect((14, 74, 50, 86), r=4)                          # neck roll
    p.poly([(55, 38), (95, 38), (95, 56), (60, 59)], ink=0)  # visor opening
    p.arc(56, 58, 40, 200, 262, 5, ink=0)                  # livery stripe
    p.circle(40, 58, 4, ink=0)                             # visor pivot


def _traffic_cone(p: Pen) -> None:
    p.rect((12, 82, 88, 93), r=3)

    def half(y):
        return 7 + (y - 8) / (82 - 8) * 21

    p.poly([(50 - 7, 8), (50 + 7, 8), (50 + 28, 82), (50 - 28, 82)])
    p.circle(50, 9, 7)
    for ya, yb in ((32, 42), (56, 66)):
        p.poly([(50 - half(ya) - 2, ya), (50 + half(ya) + 2, ya),
                (50 + half(yb) + 2, yb), (50 - half(yb) - 2, yb)], ink=0)


def _ghost(p: Pen) -> None:
    left, right, top, bottom = 30, 90, 10, 78
    p.ellipse((left, top, right, top + (right - left)))
    p.rect((left, top + 30, right, bottom))
    bump_r = (right - left) / 6
    for i in range(3):
        p.circle(left + bump_r * (1 + 2 * i), bottom, bump_r)
    p.ellipse((48, 30, 58, 46), ink=0)
    p.ellipse((66, 30, 76, 46), ink=0)
    for y, x0 in ((34, 4), (50, 0), (66, 6)):  # speed lines
        p.line([(x0, y), (x0 + 16, y)], 5)


def _trophy(p: Pen) -> None:
    p.ellipse((24, -16, 76, 62))
    p.rect((0, -20, 100, 12), ink=0)
    p.rect((22, 8, 78, 15), r=3)
    p.arc(24, 30, 14, 90, 270, 6)
    p.arc(76, 30, 14, 270, 90, 6)
    p.rect((45, 56, 55, 74))
    p.rect((32, 72, 68, 80), r=2)
    p.rect((24, 80, 76, 91), r=3)
    p.poly(_star(50, 33, 11, 4.6), ink=0)


def _podium(p: Pen) -> None:
    p.rect((36, 42, 64, 92), r=2)
    p.rect((8, 60, 34, 92), r=2)
    p.rect((66, 70, 92, 92), r=2)
    p.poly(_star(50, 22, 13, 5.5))
    p.rect((46, 50, 54, 72), ink=0)  # "1"
    p.poly([(46, 50), (54, 50), (46, 56)], ink=0)


def _reset(p: Pen) -> None:
    cx, cy, r = 50, 52, 34
    start, end = 50, 320
    p.arc(cx, cy, r, start, end, 9)
    a = math.radians(end)
    px, py = cx + r * math.cos(a), cy + r * math.sin(a)
    tx, ty = -math.sin(a), math.cos(a)        # clockwise tangent
    nx, ny = math.cos(a), math.sin(a)         # radial
    s = 15
    p.poly([(px + tx * s, py + ty * s), (px + nx * s, py + ny * s), (px - nx * s, py - ny * s)])
    p.ring(cx, cy, 13, 6)                     # wheel hub
    p.circle(cx, cy, 4)


def _bluetooth(p: Pen) -> None:
    p.line([(30, 30), (70, 68), (50, 88), (50, 12), (70, 32), (30, 70)], 8)


def _speaker(p: Pen, waves: bool = True) -> None:
    p.poly([(8, 36), (26, 36), (48, 16), (48, 84), (26, 64), (8, 64)])
    if waves:
        p.arc(48, 50, 18, -50, 50, 7)
        p.arc(48, 50, 34, -50, 50, 7)
    else:
        p.line([(62, 36), (90, 64)], 8)
        p.line([(90, 36), (62, 64)], 8)


def _stopwatch(p: Pen) -> None:
    p.ring(50, 57, 35, 8)
    p.rect((40, 6, 60, 15), r=3)
    p.rect((46, 13, 54, 24))
    p.line([(80, 22), (87, 15)], 7)
    p.line([(50, 57), (50, 34)], 7)
    p.line([(50, 57), (64, 64)], 6)
    p.circle(50, 57, 5)


def _tachometer(p: Pen) -> None:
    p.arc(50, 58, 40, 150, 390, 9)
    for i in range(7):
        a = math.radians(150 + i * 40)
        p.line([(50 + 26 * math.cos(a), 58 + 26 * math.sin(a)),
                (50 + 30 * math.cos(a), 58 + 30 * math.sin(a))], 4)
    a = math.radians(300)
    p.line([(50, 58), (50 + 30 * math.cos(a), 58 + 30 * math.sin(a))], 7)
    p.circle(50, 58, 8)


def _radar(p: Pen) -> None:
    p.ring(50, 50, 40, 6)
    p.ring(50, 50, 22, 5)
    p.pie(50, 50, 40, -90, -30)
    p.circle(50, 50, 6)
    p.circle(72, 30, 5)


def _plug(p: Pen) -> None:
    p.rect((38, 10, 45, 34), r=2)
    p.rect((55, 10, 62, 34), r=2)
    p.rect((26, 30, 74, 58), r=8)
    p.poly([(34, 56), (66, 56), (56, 70), (44, 70)])
    p.line([(50, 68), (50, 92)], 8)


def _unplug(p: Pen) -> None:
    _plug(p)
    p.line([(8, 92), (92, 8)], 14, ink=0)
    p.line([(12, 88), (88, 12)], 7)


def _race_car(p: Pen) -> None:
    # Low-slung endurance prototype, side profile, facing right.
    p.poly([(3, 66), (3, 48), (20, 45), (38, 42), (46, 32), (62, 31), (74, 42),
            (90, 50), (98, 58), (98, 66)])
    p.rect((0, 30, 20, 35), r=1.5)          # rear wing
    p.rect((9, 34, 13, 47))
    p.poly([(49, 40), (53, 35), (62, 35), (68, 41)], ink=0)   # canopy glass
    p.line([(24, 52), (44, 52)], 3.5, ink=0)                  # side-pod vent
    for cx in (22, 77):
        p.circle(cx, 66, 14, ink=0)
        p.circle(cx, 66, 10.5)
        p.circle(cx, 66, 3.5, ink=0)


def _folder(p: Pen) -> None:
    p.poly([(6, 22), (38, 22), (46, 30), (94, 30), (94, 84), (6, 84)])
    p.rect((12, 38, 88, 44), ink=0)


def _start_lights(p: Pen) -> None:
    p.rect((6, 30, 94, 70), r=12)
    for cx in (22, 50, 78):
        p.circle(cx, 50, 11, ink=0)
        p.circle(cx, 50, 6.5)


def _close(p: Pen) -> None:
    p.line([(22, 22), (78, 78)], 10)
    p.line([(78, 22), (22, 78)], 10)


def _check(p: Pen) -> None:
    p.line([(16, 52), (40, 76), (86, 26)], 11)


def _logo_badge(p: Pen) -> None:
    """Checkered flag knocked out of a rounded square (app icon)."""
    p.rect((0, 0, 100, 100), r=22)
    inner = Pen(p.px)
    _checkered_flag(inner)
    small = inner.mask.resize((round(p.px * 0.72),) * 2, Image.LANCZOS)
    hole = Image.new("L", p.mask.size, 0)
    off = round(p.px * 0.15)
    hole.paste(small, (off, off))
    p.mask.paste(0, mask=hole)


ICONS: dict[str, Callable[[Pen], None]] = {
    "flag": _checkered_flag,
    "helmet": _helmet,
    "cone": _traffic_cone,
    "ghost": _ghost,
    "trophy": _trophy,
    "podium": _podium,
    "reset": _reset,
    "bluetooth": _bluetooth,
    "speaker": _speaker,
    "mute": lambda p: _speaker(p, waves=False),
    "stopwatch": _stopwatch,
    "tacho": _tachometer,
    "radar": _radar,
    "plug": _plug,
    "unplug": _unplug,
    "car": _race_car,
    "folder": _folder,
    "lights": _start_lights,
    "close": _close,
    "check": _check,
    "logo": _logo_badge,
}


@lru_cache(maxsize=512)
def _mask(name: str, size: int) -> Image.Image:
    px = max(64, size) * SS
    pen = Pen(px)
    ICONS[name](pen)
    return pen.mask.resize((size, size), Image.LANCZOS)


@lru_cache(maxsize=512)
def render(name: str, size: int, color: str = "#ffffff") -> Image.Image:
    """Return an RGBA icon of ``size`` px tinted with ``color``."""
    mask = _mask(name, size)
    img = Image.new("RGBA", (size, size), (*hex_to_rgb(color), 0))
    img.putalpha(mask)
    return img


def render_glow(name: str, size: int, color: str, glow: int = 6) -> Image.Image:
    """Icon with a soft coloured halo - used for hero/celebration artwork."""
    pad = glow * 3
    canvas = Image.new("RGBA", (size + pad * 2, size + pad * 2), (0, 0, 0, 0))
    icon = render(name, size, color)
    halo = Image.new("RGBA", canvas.size, (0, 0, 0, 0))
    halo.paste(icon, (pad, pad), icon)
    halo = halo.filter(ImageFilter.GaussianBlur(glow))
    canvas = Image.alpha_composite(canvas, halo)
    canvas = Image.alpha_composite(canvas, halo)
    canvas.paste(icon, (pad, pad), icon)
    return canvas


def app_icon(size: int = 256, bg: str = "#ff2a3c") -> Image.Image:
    return render("logo", size, bg)
