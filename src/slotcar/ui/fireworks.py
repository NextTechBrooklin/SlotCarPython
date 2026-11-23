"""Procedural fireworks show, rendered with Pillow (no video file needed).

The simulation runs at a reduced "render" resolution and is up-scaled when
displayed, which keeps it fast and gives sparks a soft glow. Trails come from
fading the previous frame instead of clearing it, and sparks are blended
additively over a night-sky backdrop with a race-track skyline silhouette.
"""

from __future__ import annotations

import math
import random
from dataclasses import dataclass

from PIL import Image, ImageChops, ImageDraw

from .. import theme as T


@dataclass
class _Spark:
    x: float
    y: float
    vx: float
    vy: float
    life: float
    max_life: float
    rgb: tuple[int, int, int]
    drag: float = 2.2         # velocity decay per second
    gravity: float = 1.0      # multiplier on the base gravity
    width: int = 2
    crackle: bool = False
    px: float = 0.0
    py: float = 0.0


@dataclass
class _Rocket:
    x: float
    y: float
    vx: float
    vy: float
    rgb: tuple[int, int, int]
    kind: str
    px: float = 0.0
    py: float = 0.0


class FireworksShow:
    TRAIL_FADE = 0.84       # how much of the previous frame survives (trail length)
    MAX_SPARKS = 2600
    BURSTS = ("sphere", "sphere", "ring", "willow", "crackle", "twotone")

    def __init__(self, width: int, height: int, colors: list[str], finale_at: float = 4.4,
                 seed: int | None = None) -> None:
        self.w, self.h = max(160, width), max(100, height)
        self.rng = random.Random(seed)
        self.colors = [T.hex_to_rgb(c) for c in colors]
        self.finale_at = finale_at
        self.t = 0.0
        self.rockets: list[_Rocket] = []
        self.sparks: list[_Spark] = []
        self._next_launch = 0.05
        self.k = self.h / 520              # line-width scale (designed at ~520 px tall)
        self.g = self.h * 0.32           # spark gravity, px/s^2
        self.g_rocket = self.h * 0.55
        self._fade_lut = [int(v * self.TRAIL_FADE) for v in range(256)] * 3
        self.fx = Image.new("RGB", (self.w, self.h))
        self.sky, self.skyline, self.skyline_mask = self._backdrop()
        self._glow_r = int(self.h * 0.10)
        g = Image.radial_gradient("L").resize((self._glow_r * 2,) * 2, Image.BILINEAR)
        self._glow_mask = g.point(lambda v: int(max(0, 255 - v * 1.0) ** 2 / 255))  # soft falloff
        self._glow_cache: dict[tuple[int, int, int], Image.Image] = {}

    # ----------------------------------------------------------- backdrop
    def _backdrop(self) -> tuple[Image.Image, Image.Image, Image.Image]:
        w, h, rng = self.w, self.h, self.rng
        top, bottom = T.hex_to_rgb("#03040a"), T.hex_to_rgb("#141a35")
        grad = Image.new("RGB", (1, h))
        for y in range(h):
            t = (y / (h - 1)) ** 1.6
            grad.putpixel((0, y), tuple(int(a + (b - a) * t) for a, b in zip(top, bottom)))
        sky = grad.resize((w, h))
        d = ImageDraw.Draw(sky)
        for _ in range(int(w * h / 1800)):  # stars
            x, y = rng.randrange(w), rng.randrange(int(h * 0.7))
            v = rng.randint(40, 130)
            d.point((x, y), fill=(v, v, min(255, v + 25)))

        # Skyline: grandstand roof, buildings and floodlight towers.
        mask = Image.new("L", (w, h), 0)
        md = ImageDraw.Draw(mask)
        base = h * 0.86
        x = 0.0
        while x < w:
            bw = rng.uniform(0.04, 0.10) * w
            bh = rng.uniform(0.03, 0.11) * h
            md.rectangle((x, base - bh, x + bw, h), fill=255)
            x += bw
        gx0, gx1 = w * 0.18, w * 0.82                       # grandstand
        md.polygon([(gx0, h * 0.80), (gx1, h * 0.74), (gx1, h), (gx0, h)], fill=255)
        md.polygon([(gx0 - w * 0.02, h * 0.785), (gx1 + w * 0.02, h * 0.725),
                    (gx1 + w * 0.02, h * 0.735), (gx0 - w * 0.02, h * 0.795)], fill=255)
        lamps = []
        for fx in (0.08, 0.30, 0.70, 0.92):                 # floodlight towers
            cx = w * fx
            top_y = h * rng.uniform(0.58, 0.64)
            md.rectangle((cx - 1, top_y, cx + 1, h), fill=255)
            md.rectangle((cx - w * 0.018, top_y - h * 0.025, cx + w * 0.018, top_y), fill=255)
            lamps.append((cx, top_y))
        skyline = Image.new("RGB", (w, h), T.hex_to_rgb("#020308"))
        sd = ImageDraw.Draw(skyline)
        for cx, top_y in lamps:
            for i in range(4):
                lx = cx - w * 0.014 + i * w * 0.0093
                sd.rectangle((lx, top_y - h * 0.019, lx + w * 0.005, top_y - h * 0.008), fill=(255, 226, 150))
        for i in range(int(w / 6)):                          # chequered kerb along the bottom
            if i % 2 == 0:
                sd.rectangle((i * 6, h - 4, i * 6 + 5, h), fill=(38, 42, 52))
        for _ in range(int(w / 9)):                          # crowd / window lights
            x, y = rng.uniform(gx0, gx1), rng.uniform(h * 0.82, h * 0.96)
            sd.point((x, y), fill=rng.choice([(255, 210, 120), (120, 170, 255), (255, 255, 255)]))
        return sky, skyline, mask

    # ----------------------------------------------------------- simulation
    def _launch(self) -> None:
        rng = self.rng
        # The winner card sits in the middle, so favour the flanks; centre shells burst high above it.
        if rng.random() < 0.75:
            x = (rng.uniform(0.06, 0.32) if rng.random() < 0.5 else rng.uniform(0.68, 0.94)) * self.w
            apex = rng.uniform(0.10, 0.45) * self.h
        else:
            x = rng.uniform(0.36, 0.64) * self.w
            apex = rng.uniform(0.07, 0.16) * self.h
        vy = -math.sqrt(2 * self.g_rocket * (self.h - apex))
        vx = rng.uniform(-0.04, 0.04) * self.w
        self.rockets.append(_Rocket(x, self.h + 2, vx, vy, rng.choice(self.colors), rng.choice(self.BURSTS)))

    def _explode(self, r: _Rocket) -> None:
        rng = self.rng
        base_speed = rng.uniform(0.42, 0.62) * self.h
        n = rng.randint(90, 150)
        alt = rng.choice([c for c in self.colors if c != r.rgb] or self.colors)
        for i in range(n):
            ang = rng.uniform(0, math.tau)
            if r.kind == "ring":
                speed = base_speed * rng.uniform(0.96, 1.04)
            else:  # projected sphere: denser at the rim
                speed = base_speed * math.sqrt(max(0.0, 1 - rng.uniform(-1, 1) ** 2)) * rng.uniform(0.9, 1.05)
            spark = _Spark(r.x, r.y, math.cos(ang) * speed, math.sin(ang) * speed,
                           life=0, max_life=rng.uniform(1.1, 1.7), rgb=r.rgb)
            if r.kind == "willow":
                spark.rgb, spark.drag, spark.gravity = (255, 196, 90), 1.4, 1.5
                spark.max_life = rng.uniform(2.0, 2.8)
            elif r.kind == "crackle":
                spark.rgb, spark.crackle, spark.width = (255, 250, 235), True, 1
            elif r.kind == "twotone" and i % 2:
                spark.rgb = alt
            spark.life = spark.max_life
            self.sparks.append(spark)
        self._flash(r.x, r.y, r.rgb)
        if len(self.sparks) > self.MAX_SPARKS:
            del self.sparks[: len(self.sparks) - self.MAX_SPARKS]

    def _flash(self, x: float, y: float, rgb: tuple[int, int, int]) -> None:
        """Soft radial glow added into the trail buffer; it fades with the trails."""
        glow = self._glow_cache.get(rgb)
        if glow is None:
            m = self._glow_mask
            glow = Image.merge("RGB", [m.point(lambda v, c=c: int(v * (0.25 + 0.75 * c / 255) * 0.55))
                                       for c in rgb])
            self._glow_cache[rgb] = glow
        r = self._glow_r
        box = (int(x) - r, int(y) - r, int(x) + r, int(y) + r)
        region = self.fx.crop(box)
        self.fx.paste(ImageChops.add(region, glow), box)

    def step(self, dt: float) -> None:
        dt = max(0.0, min(dt, 0.05))
        self.t += dt
        if self.t >= self._next_launch:
            for _ in range(2 if self.t >= self.finale_at else 1):
                self._launch()
            gap = (0.07, 0.16) if self.t >= self.finale_at else (0.22, 0.55)
            self._next_launch = self.t + self.rng.uniform(*gap)

        alive_r = []
        for r in self.rockets:
            r.px, r.py = r.x, r.y
            r.vy += self.g_rocket * dt
            r.x += r.vx * dt
            r.y += r.vy * dt
            if self.rng.random() < 0.5:  # occasional falling embers
                self.sparks.append(_Spark(r.x, r.y, self.rng.uniform(-10, 10), self.rng.uniform(10, 30),
                                          0.45, 0.45, (255, 170, 80), drag=3.0, gravity=0.4, width=1))
            if r.vy >= -self.h * 0.05:
                self._explode(r)
            else:
                alive_r.append(r)
        self.rockets = alive_r

        alive = []
        for s in self.sparks:
            s.px, s.py = s.x, s.y
            k = math.exp(-s.drag * dt)
            s.vx *= k
            s.vy = s.vy * k + self.g * s.gravity * dt
            s.x += s.vx * dt
            s.y += s.vy * dt
            s.life -= dt
            if s.life > 0 and -20 < s.x < self.w + 20 and s.y < self.h + 20:
                alive.append(s)
        self.sparks = alive

    # ------------------------------------------------------------- render
    def render(self) -> Image.Image:
        self.fx = self.fx.point(self._fade_lut)
        d = ImageDraw.Draw(self.fx)
        rng = self.rng
        for s in self.sparks:
            age = s.max_life - s.life
            b = (s.life / s.max_life) ** 0.7
            if s.crackle and rng.random() < 0.45:
                continue
            if age < 0.12:  # white-hot just after the burst
                heat = 1 - age / 0.12
                rgb = tuple(int(c + (255 - c) * heat) for c in s.rgb)
            else:
                rgb = s.rgb
            if b < 0.35:  # flicker as the spark dies
                b *= rng.uniform(0.3, 1.0)
            col = tuple(int(c * b) for c in rgb)
            d.line((s.px, s.py, s.x, s.y), fill=col, width=max(1, round(s.width * self.k)))
        for r in self.rockets:  # continuous streak; the fading buffer turns it into a tail
            if r.py:
                d.line((r.px, r.py, r.x, r.y), fill=(255, 214, 150), width=max(1, round(2 * self.k)))
            rad = 1.5 * self.k
            d.ellipse((r.x - rad, r.y - rad, r.x + rad, r.y + rad), fill=(255, 248, 230))
        out = ImageChops.add(self.sky, self.fx)
        out.paste(self.skyline, (0, 0), self.skyline_mask)
        return out
