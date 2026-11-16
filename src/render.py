"""Рендер вертикального ролика 1080x1920@30 в стиле flat design.

Все спрайты рисуются один раз с суперсэмплингом (сглаживание), кадры
собираются композитингом в Pillow и подаются в ffmpeg через pipe.
Запуск:  python3 render.py [--preview] [--frames 0,120,...]
"""
import math, os, sys, subprocess, random
from functools import lru_cache
from multiprocessing import Pool

import numpy as np
from PIL import Image, ImageDraw, ImageFont

from narration import WORDS, SCENES, wt, scene_by_id, FPS, DURATION, tokenize

W, H = 1080, 1920
NF = int(round(DURATION * FPS))
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, "output")

# ---------------------------------------------------------------- палитра
NAVY = (29, 43, 83)
INK = (33, 41, 60)
TEAL = (42, 157, 143)
TEAL_D = (31, 112, 104)
SAND = (255, 209, 102)
CORAL = (244, 162, 97)
RED = (231, 111, 81)
CREAM = (250, 246, 238)
SKY = (168, 218, 220)
BLUE = (69, 123, 157)
LILAC = (157, 142, 196)
GREEN = (106, 176, 76)
OLIVE = (122, 156, 74)
WHITE = (255, 255, 255)
GREY = (176, 184, 197)

FD = "/usr/share/fonts/opentype/inter/"


@lru_cache(None)
def font(name, size):
    return ImageFont.truetype(FD + name, size)


# ---------------------------------------------------------------- easing
def c01(x):
    return 0.0 if x < 0 else 1.0 if x > 1 else x


def prog(t, a, d):
    return c01((t - a) / d) if d > 0 else float(t >= a)


def eo(x):  # ease out cubic
    x = c01(x); return 1 - (1 - x) ** 3


def eio(x):
    x = c01(x); return 3 * x * x - 2 * x * x * x


def eback(x, s=1.9):
    x = c01(x); x -= 1
    return x * x * ((s + 1) * x + s) + 1


def lerp(a, b, x):
    return a + (b - a) * x


def lerpc(c1, c2, x):
    return tuple(int(round(lerp(a, b, x))) for a, b in zip(c1, c2))


def appear(t, a, d=0.45):
    """(scale, alpha) для «выпрыгивания» элемента."""
    p = prog(t, a, d)
    return (0.001 if p <= 0 else eback(p)), eo(prog(t, a, d * 0.6))


# ---------------------------------------------------------------- спрайты
class D:
    """ImageDraw с масштабированием координат (для суперсэмплинга)."""

    def __init__(self, img, k):
        self.d = ImageDraw.Draw(img); self.k = k; self.img = img

    def _b(self, box):
        return [v * self.k for v in box]

    def _p(self, pts):
        return [(x * self.k, y * self.k) for x, y in pts]

    def ellipse(self, box, fill, outline=None, width=0):
        self.d.ellipse(self._b(box), fill=fill, outline=outline, width=int(width * self.k))

    def circle(self, cx, cy, r, fill, **kw):
        self.ellipse((cx - r, cy - r, cx + r, cy + r), fill, **kw)

    def rect(self, box, fill, r=0, outline=None, width=0):
        self.d.rounded_rectangle(self._b(box), radius=r * self.k, fill=fill,
                                 outline=outline, width=int(width * self.k))

    def poly(self, pts, fill):
        self.d.polygon(self._p(pts), fill=fill)

    def line(self, pts, fill, width, joint="curve"):
        self.d.line(self._p(pts), fill=fill, width=int(width * self.k), joint=joint)
        r = width / 2
        for x, y in (pts[0], pts[-1]):
            self.circle(x, y, r, fill)

    def arc(self, box, a0, a1, fill, width):
        self.d.arc(self._b(box), a0, a1, fill=fill, width=int(width * self.k))

    def pie(self, box, a0, a1, fill):
        self.d.pieslice(self._b(box), a0, a1, fill=fill)

    def text(self, xy, s, fnt_name, size, fill, anchor="mm"):
        self.d.text((xy[0] * self.k, xy[1] * self.k), s, font=font(fnt_name, int(size * self.k)),
                    fill=fill, anchor=anchor)


def sprite(w, h, fn, ss=3):
    img = Image.new("RGBA", (w * ss, h * ss), (0, 0, 0, 0))
    fn(D(img, ss))
    return img.resize((w, h), Image.LANCZOS)


def with_alpha(spr, a):
    if a >= 0.999:
        return spr
    s = spr.copy()
    s.putalpha(spr.getchannel("A").point(lambda v: int(v * a)))
    return s


def tint(spr, color, amount=1.0):
    col = Image.new("RGBA", spr.size, color + (255,))
    col.putalpha(spr.getchannel("A"))
    return Image.blend(spr, col, amount) if amount < 1 else col


def put(base, spr, x, y, scale=1.0, alpha=1.0, rot=0.0, anchor="c", sx=None, sy=None):
    """Наложить спрайт. anchor: c — центр, b — низ по центру, tl — левый верх."""
    if alpha <= 0.003:
        return
    sx = scale if sx is None else sx * scale
    sy = scale if sy is None else sy * scale
    if sx <= 0.002 or sy <= 0.002:
        return
    s = spr
    if abs(sx - 1) > 1e-3 or abs(sy - 1) > 1e-3:
        s = s.resize((max(1, int(s.width * sx)), max(1, int(s.height * sy))), Image.BILINEAR)
    if abs(rot) > 0.05:
        s = s.rotate(rot, resample=Image.BICUBIC, expand=True)
    s = with_alpha(s, alpha)
    if anchor == "c":
        x0, y0 = x - s.width / 2, y - s.height / 2
    elif anchor == "b":
        x0, y0 = x - s.width / 2, y - s.height
    else:
        x0, y0 = x, y
    x0, y0 = int(round(x0)), int(round(y0))
    cx0, cy0 = max(0, -x0), max(0, -y0)
    cx1, cy1 = min(s.width, base.width - x0), min(s.height, base.height - y0)
    if cx1 <= cx0 or cy1 <= cy0:
        return
    if (cx0, cy0, cx1, cy1) != (0, 0, s.width, s.height):
        s = s.crop((cx0, cy0, cx1, cy1))
    base.alpha_composite(s, dest=(x0 + cx0, y0 + cy0))


def reveal(spr, p, direction="lr"):
    """Обрезка спрайта для эффекта «прорисовки» (0..1)."""
    p = c01(p)
    if p >= 1:
        return spr
    out = Image.new("RGBA", spr.size, (0, 0, 0, 0))
    if direction == "lr":
        w = int(spr.width * p)
        if w > 0:
            out.paste(spr.crop((0, 0, w, spr.height)), (0, 0))
    else:  # bt — снизу вверх
        h = int(spr.height * p)
        if h > 0:
            out.paste(spr.crop((0, spr.height - h, spr.width, spr.height)), (0, spr.height - h))
    return out


def vgrad(stops):
    """Вертикальный градиент: stops = [(pos0..1, color), ...]"""
    ys = np.linspace(0, 1, H)
    arr = np.zeros((H, 3))
    pos = [p for p, _ in stops]
    for ch in range(3):
        arr[:, ch] = np.interp(ys, pos, [c[ch] for _, c in stops])
    img = np.repeat(arr[:, None, :], W, axis=1).astype(np.uint8)
    return Image.fromarray(img, "RGB").convert("RGBA")


def radial_glow(r, color, power=2.0):
    yy, xx = np.mgrid[-r:r, -r:r]
    d = np.sqrt(xx ** 2 + yy ** 2) / r
    a = np.clip(1 - d, 0, 1) ** power
    arr = np.zeros((2 * r, 2 * r, 4), np.uint8)
    arr[..., :3] = color
    arr[..., 3] = (a * 255).astype(np.uint8)
    return Image.fromarray(arr, "RGBA")


def hills(width, height, color, seed, amp=60, base=0.45, freq=1.0):
    rnd = random.Random(seed)
    ph = [rnd.uniform(0, 6.28) for _ in range(3)]

    def fn(d):
        pts = [(0, height)]
        for i in range(0, width + 1, 6):
            x = i / width
            y = height * base - amp * (0.6 * math.sin(x * 6.0 * freq + ph[0]) +
                                       0.3 * math.sin(x * 13 * freq + ph[1]) +
                                       0.15 * math.sin(x * 29 * freq + ph[2]))
            pts.append((i, y))
        pts.append((width, height))
        d.poly(pts, color + (255,))
    return sprite(width, height, fn, ss=2)


# ---- персонажи и объекты
def person(color, h=220, bag=None, child=False):
    w = int(h * 0.62)

    def fn(d):
        hr = h * 0.15
        cx = w / 2
        d.circle(cx, hr + 2, hr, color + (255,))
        d.rect((cx - h * 0.2, hr * 2 + 10, cx + h * 0.2, h), color + (255,), r=h * 0.16)
        if bag:
            d.rect((cx + h * 0.16, h * 0.62, cx + h * 0.29, h * 0.92), bag + (255,), r=6)
            d.rect((cx + h * 0.19, h * 0.57, cx + h * 0.26, h * 0.64), bag + (255,), r=3)
    return sprite(w, h, fn)


def dove(wing_up=True, glass=False):
    w, h = 300, 220
    body = (235, 246, 255) if glass else WHITE
    wing = (205, 228, 246) if glass else (232, 236, 242)

    def fn(d):
        # оливковая ветвь
        if not glass:
            d.line([(222, 118), (262, 150), (290, 160)], OLIVE + (255,), 5)
            for (lx, ly, rot) in [(248, 134, 0), (265, 156, 0), (280, 150, 0), (258, 146, 0)]:
                d.ellipse((lx - 11, ly - 6, lx + 11, ly + 6), GREEN + (255,))
        # хвост
        d.poly([(70, 118), (8, 92), (14, 132), (70, 138)], body + (255,))
        # тело
        d.ellipse((50, 92, 210, 160), body + (255,))
        # голова
        d.circle(212, 104, 30, body + (255,))
        d.poly([(236, 98), (262, 110), (236, 116)], SAND + (255,))
        d.circle(220, 98, 5, INK + (255,))
        # крыло
        if wing_up:
            d.poly([(95, 112), (165, 112), (150, 12), (100, 40)], wing + (255,))
        else:
            d.poly([(95, 120), (165, 118), (140, 210), (98, 186)], wing + (255,))
    return sprite(w, h, fn)


def shield(size=360):
    def fn(d):
        s = size
        pts = [(s * .5, s * .03), (s * .9, s * .16), (s * .88, s * .5), (s * .5, s * .97), (s * .12, s * .5), (s * .1, s * .16)]
        d.poly(pts, TEAL + (255,))
        inner = [(s * .5, s * .12), (s * .8, s * .22), (s * .78, s * .5), (s * .5, s * .86), (s * .22, s * .5), (s * .2, s * .22)]
        d.poly(inner, (64, 182, 166, 255))
    return sprite(size, size, fn)


def checkmark(size=360, color=WHITE):
    def fn(d):
        s = size
        d.line([(s * .32, s * .5), (s * .46, s * .64), (s * .7, s * .36)], color + (255,), s * .075, joint="curve")
    return sprite(size, size, fn)


def warn_sign(s=96):
    def fn(d):
        d.poly([(s / 2, 6), (s - 4, s - 8), (4, s - 8)], SAND + (255,))
        d.rect((s / 2 - 5, s * .34, s / 2 + 5, s * .64), INK + (255,), r=4)
        d.circle(s / 2, s * .76, 6, INK + (255,))
    return sprite(s, s, fn)


def flag(color=GREEN, s=110):
    def fn(d):
        d.rect((s * .3, 8, s * .3 + 7, s), (90, 90, 100, 255), r=3)
        d.poly([(s * .3 + 7, 10), (s * .9, s * .25), (s * .3 + 7, s * .45)], color + (255,))
    return sprite(s, s, fn)


def deminer(color=OLIVE):
    w, h = 260, 250

    def fn(d):
        hx = 90
        d.circle(hx, 36, 30, color + (255,))
        d.rect((hx - 20, 22, hx + 34, 46), (110, 190, 210, 255), r=10)  # визор
        d.rect((hx - 44, 74, hx + 44, h - 4), color + (255,), r=36)
        d.line([(hx + 30, 120), (200, 190), (220, 236)], (70, 70, 80, 255), 7)
        d.ellipse((190, 228, 254, 246), (70, 70, 80, 255))
    return sprite(w, h, fn)


def watchtower(s=150):
    def fn(d):
        d.line([(s * .35, s), (s * .45, s * .35)], (120, 130, 150, 255), 7)
        d.line([(s * .65, s), (s * .55, s * .35)], (120, 130, 150, 255), 7)
        d.rect((s * .3, s * .22, s * .7, s * .42), CREAM + (255,), r=6)
        d.poly([(s * .24, s * .24), (s * .5, s * .06), (s * .76, s * .24)], BLUE + (255,))
    return sprite(s, s, fn)


def house(color, roof, w=210, h=230, seed=0):
    def fn(d):
        d.rect((14, h * .38, w - 14, h), color + (255,), r=6)
        d.poly([(0, h * .42), (w / 2, 4), (w, h * .42)], roof + (255,))
        d.rect((w * .42, h * .68, w * .58, h), (90, 70, 60, 255), r=5)
        for wx in (w * .18, w * .66):
            d.rect((wx, h * .52, wx + w * .16, h * .66), (255, 236, 170, 255), r=4)
    return sprite(w, h, fn)


def block_building(color, w=180, h=360):
    def fn(d):
        d.rect((0, 0, w, h), color + (255,), r=8)
        for r in range(int((h - 40) / 60)):
            for c in range(3):
                x = 22 + c * (w - 44) / 3
                d.rect((x, 28 + r * 60, x + (w - 44) / 3 - 16, 28 + r * 60 + 34), (255, 236, 170, 255), r=4)
    return sprite(w, h, fn)


def crane(h=560):
    w = 460

    def fn(d):
        col = SAND + (255,)
        d.rect((96, 40, 124, h), col, r=4)
        for y in range(60, h, 50):
            d.line([(98, y), (122, y + 40)], (220, 170, 60, 255), 4)
        d.rect((20, 40, w - 10, 64), col, r=6)
        d.rect((20, 64, 70, 104), (100, 110, 130, 255), r=4)  # противовес
        d.poly([(110, 0), (128, 40), (92, 40)], col)
    return sprite(w, h, fn)


def train():
    w, h = 940, 230

    def fn(d):
        for i, x in enumerate((0, 320, 640)):
            body = TEAL if i == 0 else (CREAM if i == 1 else TEAL)
            d.rect((x + 6, 30, x + 300, 200), body + (255,), r=34)
            for wx in range(int(x) + 40, int(x) + 280, 70):
                d.rect((wx, 60, wx + 46, 112), (210, 238, 245, 255), r=10)
            d.rect((x + 6, 150, x + 300, 166), (CORAL if i != 1 else TEAL) + (255,))
            for wx in (x + 60, x + 240):
                d.circle(wx, 206, 20, (60, 66, 80, 255))
        d.rect((300, 120, 326, 140), (90, 90, 100, 255))
        d.rect((620, 120, 646, 140), (90, 90, 100, 255))
    return sprite(w, h, fn)


def heart(s=90, color=RED):
    def fn(d):
        r = s * .27
        d.circle(s * .3, s * .36, r, color + (255,))
        d.circle(s * .7, s * .36, r, color + (255,))
        d.poly([(s * .05, s * .44), (s * .95, s * .44), (s * .5, s * .92)], color + (255,))
    return sprite(s, s, fn)


def pylon(h=420):
    w = 220

    def fn(d):
        c = (95, 105, 125, 255)
        d.line([(30, h), (100, 30)], c, 9)
        d.line([(190, h), (120, 30)], c, 9)
        for y in range(80, h, 70):
            fx = (y - 30) / (h - 30)
            xl, xr = 100 - 70 * fx, 120 + 70 * fx
            d.line([(xl, y), (xr, y + 60 if y + 60 < h else y)], c, 5)
            d.line([(xr, y), (xl, y + 60 if y + 60 < h else y)], c, 5)
        d.rect((10, 60, 210, 74), c, r=4)
        d.rect((40, 120, 180, 132), c, r=4)
        d.rect((105, 0, 115, 40), c)
    return sprite(w, h, fn)


def power_lines(xs, ytops, sag=55, color=(80, 90, 110)):
    def fn(d):
        for off in (60, 120):
            for i in range(len(xs) - 1):
                x0, x1 = xs[i], xs[i + 1]
                pts = []
                for k in range(41):
                    u = k / 40
                    x = lerp(x0, x1, u)
                    y = lerp(ytops[i], ytops[i + 1], u) + off + sag * 4 * u * (1 - u)
                    pts.append((x, y))
                d.line(pts, color + (255,), 4)
    return sprite(W, H, fn, ss=2)


def bolt(s=170):
    def fn(d):
        d.poly([(s * .58, 0), (s * .18, s * .56), (s * .46, s * .56), (s * .36, s), (s * .84, s * .38), (s * .54, s * .38), (s * .7, 0)], SAND + (255,))
    return sprite(s, s, fn)


def coin(s=110):
    def fn(d):
        d.circle(s / 2, s / 2, s / 2 - 2, (230, 170, 60, 255))
        d.circle(s / 2, s / 2, s / 2 - 12, SAND + (255,))
        d.text((s / 2, s / 2 + 2), "$", "Inter-Black.otf", s * .5, (200, 140, 40, 255))
    return sprite(s, s, fn)


def padlock_body(s=260):
    def fn(d):
        d.rect((10, 10, s - 10, s * .8), (95, 105, 125, 255), r=40)
        d.circle(s / 2, s * .36, s * .09, INK + (255,))
        d.rect((s / 2 - 10, s * .38, s / 2 + 10, s * .58), INK + (255,), r=6)
    return sprite(s, int(s * .82), fn)


def shackle(s=260):
    def fn(d):
        d.arc((s * .2, 10, s * .8, s * .62), 180, 360, (140, 150, 168, 255), s * .09)
        d.rect((s * .2, s * .31 - 2, s * .2 + s * .09, s * .62), (140, 150, 168, 255))
        d.rect((s * .8 - s * .09, s * .31 - 2, s * .8, s * .62), (140, 150, 168, 255))
    return sprite(s, int(s * .62), fn)


def factory():
    w, h = 420, 300

    def fn(d):
        c = (120, 132, 160, 255)
        d.rect((250, 20, 290, 160), c, r=4)
        d.poly([(0, 300), (0, 120), (90, 170), (90, 120), (180, 170), (180, 120), (270, 170), (270, 120), (420, 170), (420, 300)], c)
        for x in range(30, 400, 80):
            d.rect((x, 200, x + 46, 240), (255, 236, 170, 255), r=6)
    return sprite(w, h, fn)


def puff(s=90):
    def fn(d):
        d.circle(s / 2, s / 2, s / 2 - 2, (235, 240, 245, 255))
    return sprite(s, s, fn)


def crack(w=300, h=220):
    def fn(d):
        c = (60, 80, 110, 255)
        d.line([(150, 0), (138, 50), (165, 92), (128, 140), (150, 220)], c, 5, joint="curve")
        d.line([(165, 92), (228, 112), (290, 100)], c, 4)
        d.line([(138, 50), (80, 64), (40, 40)], c, 4)
        d.line([(128, 140), (70, 168)], c, 3)
    return sprite(w, h, fn)


def document():
    w, h = 470, 600

    def fn(d):
        d.rect((10, 16, w - 4, h - 2), (0, 0, 0, 40), r=26)
        d.rect((0, 0, w - 14, h - 18), WHITE + (255,), r=26)
        d.text(((w - 14) / 2, 72), "СОГЛАШЕНИЕ", "Inter-ExtraBold.otf", 42, INK + (255,))
        d.rect((60, 112, w - 74, 118), (225, 228, 235, 255), r=3)
        for i in range(3):
            y = 170 + i * 110
            d.rect((50, y, 110, y + 60), (240, 242, 247, 255), r=12, outline=(190, 196, 210, 255), width=4)
            d.rect((140, y + 10, w - 70, y + 24), (215, 220, 230, 255), r=7)
            d.rect((140, y + 38, w - 150, y + 52), (230, 233, 240, 255), r=7)
        d.line([(260, 520), (300, 500), (330, 530), (380, 498)], (120, 140, 200, 255), 5)
    return sprite(w, h, fn)


def qmark(s=70, color=RED):
    def fn(d):
        d.text((s / 2, s / 2), "?", "Inter-Black.otf", s * .9, color + (255,))
    return sprite(s, s, fn)


def scales_stand():
    w, h = 140, 430

    def fn(d):
        c = (95, 105, 125, 255)
        d.rect((60, 30, 80, 400), c, r=6)
        d.poly([(10, 430), (70, 370), (130, 430)], c)
        d.circle(70, 30, 22, SAND + (255,))
    return sprite(w, h, fn)


def beam():
    def fn(d):
        d.rect((0, 0, 620, 22), (95, 105, 125, 255), r=11)
    return sprite(620, 22, fn)


def pan(label, color):
    w, h = 250, 110

    def fn(d):
        d.pie((10, -60, w - 10, 100), 0, 180, color + (255,))
        d.text((w / 2, 52), label, "Inter-ExtraBold.otf", 30, WHITE + (255,))
    return sprite(w, h, fn)


def bubble():
    w, h = 520, 300

    def fn(d):
        d.rect((0, 0, w, 230), WHITE + (255,), r=60)
        d.poly([(90, 220), (60, 300), (170, 222)], WHITE + (255,))
    return sprite(w, h, fn)


def dot(s=40, color=INK):
    return sprite(s, s, lambda d: d.circle(s / 2, s / 2, s / 2 - 1, color + (255,)))


def sub_button():
    w, h = 640, 140

    def fn(d):
        d.rect((0, 0, w, h), (230, 57, 70, 255), r=70)
        # колокольчик
        d.pie((54, 34, 116, 104), 180, 360, WHITE + (255,))
        d.rect((54, 68, 116, 96), WHITE + (255,))
        d.rect((46, 92, 124, 102), WHITE + (255,), r=4)
        d.circle(85, 108, 9, WHITE + (255,))
        d.text((w / 2 + 40, h / 2 + 2), "ПОДПИСАТЬСЯ", "Inter-Black.otf", 52, WHITE + (255,))
    return sprite(w, h, fn)


def star(s=12):
    return sprite(s, s, lambda d: d.circle(s / 2, s / 2, s / 2 - 1, (255, 255, 255, 255)))


def cloud(w=320, h=120, color=WHITE):
    def fn(d):
        c = color + (255,)
        d.circle(w * .3, h * .6, h * .38, c)
        d.circle(w * .52, h * .45, h * .45, c)
        d.circle(w * .74, h * .62, h * .34, c)
        d.rect((w * .2, h * .6, w * .85, h * .96), c, r=h * .3)
    return sprite(w, h, fn)


def tree(color=GREEN, h=200):
    w = int(h * .6)

    def fn(d):
        d.rect((w / 2 - 8, h * .55, w / 2 + 8, h), (130, 100, 80, 255), r=4)
        d.circle(w / 2, h * .38, w * .42, color + (255,))
    return sprite(w, h, fn)


# ---- текстовые плашки
@lru_cache(None)
def text_img(s, size, color=WHITE, fnt="Inter-Black.otf", shadow=True):
    f = font(fnt, size)
    l, t, r, b = f.getbbox(s)
    pad = 14
    img = Image.new("RGBA", (r - l + pad * 2, b - t + pad * 2), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    if shadow:
        d.text((pad - l + 3, pad - t + 5), s, font=f, fill=(0, 0, 0, 70))
    d.text((pad - l, pad - t), s, font=f, fill=color + (255,))
    return img


@lru_cache(None)
def chip(s, bg, fg=WHITE, size=40):
    f = font("Inter-ExtraBold.otf", size)
    l, t, r, b = f.getbbox(s)
    w, h = r - l + 60, int(size * 1.7)

    def fn(d):
        d.rect((0, 0, w, h), bg + (255,), r=h / 2)
    img = sprite(w, h, fn)
    ImageDraw.Draw(img).text((w / 2, h / 2), s, font=f, fill=fg + (255,), anchor="mm")
    return img


@lru_cache(None)
def card(lines, bg=WHITE, fg=INK, size=64, accent=None):
    """Карточка-акцент: несколько строк крупного текста на плашке."""
    f = font("Inter-Black.otf", size)
    ws = [f.getbbox(s) for s in lines]
    lh = int(size * 1.18)
    w = max(b[2] - b[0] for b in ws) + 90
    h = lh * len(lines) + 60

    def fn(d):
        d.rect((0, 8, w, h + 8), (0, 0, 0, 45), r=36)
        d.rect((0, 0, w, h), bg + (255,), r=36)
    img = sprite(w, h + 10, fn)
    dr = ImageDraw.Draw(img)
    for i, s in enumerate(lines):
        col = accent if (accent and i == len(lines) - 1) else fg
        dr.text((w / 2, 30 + lh * i + lh / 2), s, font=f, fill=col + (255,), anchor="mm")
    return img


# ================================================================ АССЕТЫ
print("building sprites…", file=sys.stderr)
A = {}
A["dove_u"], A["dove_d"] = dove(True), dove(False)
A["gdove_u"], A["gdove_d"] = dove(True, glass=True), dove(False, glass=True)
A["glow_sun"] = radial_glow(420, (255, 214, 140), 1.6)
A["glow_small"] = radial_glow(200, (255, 240, 200), 1.8)
A["star"] = star()
A["shield"], A["check"] = shield(), checkmark()
A["warn"], A["flag"] = warn_sign(), flag()
A["deminer1"], A["deminer2"] = deminer(OLIVE), deminer(TEAL_D)
A["tower"] = watchtower()
A["people"] = [person(c, 200, bag=b) for c, b in
               [(BLUE, CORAL), (TEAL_D, SAND), (LILAC, RED), (NAVY, CORAL), (RED, SAND), (TEAL, CORAL)]]
A["kid"] = person(CORAL, 130)
A["adult_a"], A["adult_b"] = person(BLUE, 230), person(RED, 220)
A["train"] = train()
A["heart"], A["heart_s"] = heart(110), heart(60, CORAL)
A["houses"] = [house(c, r) for c, r in [((246, 200, 160), RED), ((200, 220, 230), BLUE), ((240, 226, 190), TEAL_D), ((235, 210, 220), LILAC)]]
A["blocks"] = [block_building(c, 180, h) for c, h in [((150, 190, 210), 380), ((240, 200, 150), 300), ((180, 170, 210), 440)]]
A["crane"] = crane()
A["pylon"] = pylon()
A["bolt"], A["coin"] = bolt(), coin()
A["lock"], A["shackle"] = padlock_body(), shackle()
A["factory"], A["puff"] = factory(), puff()
A["crack"] = crack()
A["doc"], A["q"] = document(), qmark()
A["stand"], A["beam"] = scales_stand(), beam()
A["pan_l"], A["pan_r"] = pan("ГАРАНТИИ", TEAL), pan("ДОВЕРИЕ", CORAL)
A["bubble"], A["dot"] = bubble(), dot()
A["sub"] = sub_button()
A["cloud"], A["cloud_s"] = cloud(), cloud(220, 84)
A["tree"], A["tree2"] = tree(GREEN), tree(OLIVE, 160)

PYLON_X = [40, 400, 760, 1120]
PYLON_TOP = [770, 790, 770, 790]
A["wires"] = power_lines([x + 0 for x in PYLON_X], [y + 0 for y in PYLON_TOP])

HORIZON = 1180


def ground_grad(c):
    ys = np.linspace(0, 1, H - HORIZON)[:, None]
    top = np.array([min(255, v * 1.06 + 6) for v in c])
    bot = np.array([v * 0.72 for v in c])
    arr = top * (1 - ys) + bot * ys
    img = np.repeat(arr[:, None, :], W, axis=1).astype(np.uint8)
    return Image.fromarray(img, "RGB").convert("RGBA")


def make_bg(sky, far, near, ground, seed):
    bg = vgrad(sky)
    return dict(bg=bg,
                far=hills(1400, 420, far, seed, amp=50, base=0.4),
                near=hills(1400, 360, near, seed + 7, amp=36, base=0.45, freq=0.7),
                ground=ground, groundimg=ground_grad(ground))


BG = {
    "hook": make_bg([(0, (20, 28, 62)), (0.45, (52, 56, 112)), (0.62, (196, 118, 128)), (0.7, (250, 176, 120)), (1, (250, 176, 120))],
                    (62, 52, 100), (40, 36, 74), (34, 30, 60), 1),
    "security": make_bg([(0, (126, 186, 214)), (0.6, (214, 236, 238)), (1, (214, 236, 238))],
                        (150, 196, 186), (112, 170, 150), (96, 150, 120), 2),
    "people": make_bg([(0, (255, 196, 150)), (0.6, (255, 232, 200)), (1, (255, 232, 200))],
                      (230, 180, 140), (196, 160, 120), (170, 150, 112), 3),
    "economy": make_bg([(0, (110, 190, 190)), (0.6, (220, 242, 236)), (1, (220, 242, 236))],
                       (140, 196, 176), (100, 170, 150), (84, 140, 130), 4),
    "risks": make_bg([(0, (92, 100, 140)), (0.6, (180, 184, 210)), (1, (180, 184, 210))],
                     (120, 124, 160), (96, 100, 136), (80, 84, 116), 5),
    "final": make_bg([(0, (110, 170, 220)), (0.4, (255, 205, 160)), (0.62, (255, 232, 170)), (1, (255, 232, 170))],
                     (240, 170, 130), (220, 140, 120), (196, 120, 110), 6),
}


def landscape(sid, t, zoom_drift=True):
    """Фон с параллаксом: небо, дальние/ближние холмы, земля."""
    b = BG[sid]
    img = b["bg"].copy()
    put(img, b["far"], -100 - t * 6, HORIZON - 420 * 0.62, anchor="tl")
    put(img, b["near"], -60 - t * 16, HORIZON - 360 * 0.42, anchor="tl")
    img.alpha_composite(b["groundimg"], dest=(0, HORIZON))
    return img


def header(img, t, text, bg, t0=0.0):
    s, a = appear(t, t0 + 0.05, 0.5)
    put(img, chip(text, bg, size=40), W / 2, 210, scale=s, alpha=a)


def accent(img, t, t0, lines, y=380, bg=WHITE, fg=INK, size=64, accent_col=None, t1=None):
    s, a = appear(t, t0, 0.45)
    if t1 is not None:
        a *= 1 - eo(prog(t, t1, 0.3))
        s *= 1 - 0.1 * eo(prog(t, t1, 0.3))
    put(img, card(tuple(lines), bg, fg, size, accent_col), W / 2, y, scale=s, alpha=a)


def fly_dove(img, x, y, t, scale=1.0, glass=False, flap=6.0, alpha=1.0, rot=0):
    up = math.sin(t * flap) > 0
    key = ("gdove_" if glass else "dove_") + ("u" if up else "d")
    put(img, A[key], x, y + math.sin(t * flap) * 8, scale=scale, alpha=alpha, rot=rot)


# ================================================================ СЦЕНЫ
def sc_hook(t):
    img = landscape("hook", t)
    rnd = random.Random(11)
    for i in range(46):
        x, y = rnd.uniform(0, W), rnd.uniform(60, 900)
        tw = 0.45 + 0.55 * (0.5 + 0.5 * math.sin(t * 3 + i * 1.7))
        put(img, A["star"], x, y, scale=rnd.uniform(.5, 1.1), alpha=tw * 0.8)
    # восходящее солнце
    sun_y = HORIZON - 30 - 120 * eo(t / 4)
    put(img, A["glow_sun"], W / 2, sun_y, alpha=0.9)
    img_d = ImageDraw.Draw(img)
    # заголовок «ЧТО, ЕСЛИ / ВОЙНА / ЗАКОНЧИТСЯ?»
    lines = [("ЧТО, ЕСЛИ", 0.0, WHITE, 118), ("ВОЙНА", 0.55, WHITE, 150), ("ЗАКОНЧИТСЯ?", 1.6, SAND, 128)]
    y = 400
    for txt, t0, col, size in lines:
        p = prog(t, t0 - 0.12, 0.4)
        s = 1.25 - 0.25 * eback(p) if t0 == 0 else eback(p)
        a = 1.0 if t0 == 0 else eo(p * 1.6)
        put(img, text_img(txt, size, col), W / 2, y, scale=max(s, .001), alpha=a)
        y += size * 1.15
    put(img, text_img("сценарии, а не прогнозы", 40, (230, 230, 245), "Inter-SemiBold.otf", False),
        W / 2, y + 30, alpha=eo(prog(t, 2.3, 0.6)) * 0.9)
    # голубь пролетает
    p = eio(prog(t, 0.3, 3.0))
    fly_dove(img, lerp(-200, 760, p), lerp(1080, 960, p), t, scale=1.0)
    # силуэты на холме — смотрят на рассвет
    for i, (x, sc) in enumerate([(200, 1.0), (300, .7), (860, .95)]):
        put(img, tint(A["people"][i], (24, 22, 46)), x, HORIZON + 6, scale=sc, anchor="b")
    return img


def sc_security(t):
    sid = "security"
    img = landscape(sid, t)
    T = lambda k: wt(sid, k) - 4.0
    header(img, t, "1 · БЕЗОПАСНОСТЬ", TEAL)
    put(img, A["cloud"], 160 + t * 10, 640, alpha=.9)
    put(img, A["cloud_s"], 700 - t * 8, 760, alpha=.8)
    # --- щит гарантий
    tg = T("гарантии")
    s, a = appear(t, T("Кто") - 0.1, 0.5)
    move = eio(prog(t, T("Линия") - 0.2, 0.6))
    sx, sy, ss = lerp(W / 2, 930, move), lerp(760, 610, move), lerp(1.0, 0.4, move)
    put(img, A["shield"], sx, sy, scale=s * ss, alpha=a)
    put(img, reveal(A["check"], prog(t, tg, 0.5)), sx, sy, scale=s * ss, alpha=a)
    accent(img, t, tg - 0.15, ["ГАРАНТИИ?"], y=380, accent_col=TEAL, t1=T("Линия") - 0.2)
    # --- линия фронта → линия разграничения с наблюдателями
    tl = T("Линия")
    pl = prog(t, tl, 0.9)
    yline = HORIZON + 90
    if pl > 0:
        col = lerpc(RED, BLUE, eio(prog(t, T("разграничения") - 0.1, 0.8)))
        d = ImageDraw.Draw(img)
        x_end = int(W * eo(pl))
        for x in range(-20, x_end, 60):
            y0 = yline + 18 * math.sin(x / 90)
            y1 = yline + 18 * math.sin((x + 36) / 90)
            d.line((x, y0, min(x + 36, x_end), y1), fill=col + (255,), width=12)
        for i, x in enumerate((180, 540, 900)):
            s2, a2 = appear(t, T("разграничения") + 0.15 * i, 0.4)
            put(img, A["tower"], x, yline + 18 * math.sin(x / 90) - 4, scale=s2, alpha=a2, anchor="b")
    accent(img, t, tl + 0.2, ["ЛИНИЯ ФРОНТА →", "ЛИНИЯ РАЗГРАНИЧЕНИЯ"], y=400, size=54,
           accent_col=BLUE, t1=T("разминирование") - 0.2)
    # --- разминирование
    tm = T("разминирование")
    mines = [(170, 1330), (430, 1290), (650, 1350), (890, 1310), (310, 1420), (790, 1430)]
    walk = eio(prog(t, tm - 0.3, 3.8))
    dx = lerp(-200, 1250, walk)
    for i, (mx, my) in enumerate(mines):
        s3, a3 = appear(t, tl + 0.6 + 0.1 * i, 0.4)
        cleared = prog(t, tm - 0.3 + 3.8 * c01((mx + 250) / 1450), 0.35)
        put(img, A["warn"], mx, my, scale=s3 * (1 - eo(cleared)), alpha=a3 * (1 - cleared), anchor="b")
        if cleared > 0:
            put(img, A["flag"], mx, my, scale=eback(cleared) * 0.8, anchor="b")
    if t > tm - 0.3:
        bob = abs(math.sin(t * 6)) * 6
        put(img, A["deminer1"], dx, HORIZON + 270 - bob, anchor="b")
        put(img, A["deminer2"], dx - 300, HORIZON + 190 - bob, scale=.8, anchor="b")
    accent(img, t, tm + 0.1, ["РАЗМИНИРОВАНИЕ", "ЗАЙМЁТ ГОДЫ"], y=400, size=60, accent_col=RED)
    return img


def sc_people(t):
    sid = "people"
    img = landscape(sid, t)
    T = lambda k: wt(sid, k) - 15.0
    header(img, t, "2 · ЛЮДИ", CORAL)
    put(img, A["glow_small"], 860, 560, scale=1.4, alpha=.9)
    put(img, A["cloud"], 200 + t * 9, 560, alpha=.85)
    # --- миллионы уехали: вереница людей уходит влево
    tm = T("Миллионы")
    tv = T("вернуться")
    out_alpha = 1 - eo(prog(t, tv - 0.6, 0.5))
    for i in range(12):
        ph = (t - tm + 0.4) * 140 - i * 120
        x = W + 60 - ph
        if -100 < x < W + 100 and t > tm - 0.6:
            pp = A["people"][i % 6]
            put(img, pp, x, HORIZON + 130 + (i % 3) * 40 - abs(math.sin(t * 7 + i)) * 8,
                scale=0.75 - (i % 3) * 0.06, alpha=out_alpha, anchor="b")
    accent(img, t, tm, ["МИЛЛИОНЫ", "УЕХАЛИ ИЗ-ЗА ВОЙНЫ"], y=400, size=56, accent_col=CORAL, t1=tv - 0.5)
    # --- поезд возвращается, семья встречается
    tt = tv - 0.7
    p_tr = eo(prog(t, tt, 1.6))
    tr_x = lerp(W + 520, 420, p_tr)
    tr_out = eio(prog(t, T("жильё") - 0.4, 1.2))
    tr_x -= tr_out * 1500
    if t > tt:
        ImageDraw.Draw(img).rectangle((0, HORIZON + 86, W, HORIZON + 100), fill=(140, 120, 100, 255))
        put(img, A["train"], tr_x, HORIZON + 90, anchor="b")
    tf = T("семьи")
    pm = eio(prog(t, tf - 0.2, 1.0))
    fam_a = 1 - eo(prog(t, T("жильё") - 0.3, 0.4))
    if t > tf - 0.4:
        put(img, A["adult_a"], lerp(180, 470, pm), HORIZON + 260, alpha=fam_a, anchor="b")
        put(img, A["kid"], lerp(110, 400, pm), HORIZON + 260, alpha=fam_a, anchor="b")
        put(img, A["adult_b"], lerp(940, 600, pm), HORIZON + 260, alpha=fam_a, anchor="b")
        hs, ha = appear(t, tf + 0.85, 0.5)
        put(img, A["heart"], 535, HORIZON - 30 - 20 * math.sin(t * 3), scale=hs * (1 + .06 * math.sin(t * 8)),
            alpha=ha * fam_a)
    accent(img, t, tv - 0.1, ["ВОЗВРАЩЕНИЕ", "ДОМОЙ"], y=400, size=64, accent_col=CORAL, t1=T("жильё") - 0.3)
    # --- восстановление: дома растут, кран
    tb = T("жильё")
    if t > tb - 0.5:
        cs, ca = appear(t, tb - 0.4, 0.6)
        put(img, A["crane"], 850, HORIZON + 40, scale=cs * 0.9, alpha=ca, anchor="b")
        hook_y = HORIZON - 380 + 120 * math.sin((t - tb) * 1.6)
        d = ImageDraw.Draw(img)
        if ca > .9:
            d.line((1040 * 0.9 + 0, HORIZON - 440, 1040 * 0.9, hook_y), fill=(90, 90, 100, 255), width=4)
            d.rectangle((1040 * .9 - 40, hook_y, 1040 * .9 + 40, hook_y + 46), fill=(240, 200, 150, 255))
        bl = [(150, 0), (330, 1), (560, 2)]
        for i, (x, k) in enumerate(bl):
            p = eback(prog(t, tb + 0.15 * i, 0.8), 1.2)
            put(img, A["blocks"][k], x, HORIZON + 60, sy=max(p, .001), anchor="b")
        for i, x in enumerate((110, 330, 560, 800)):
            p = eback(prog(t, T("работа") + 0.12 * i, 0.7), 1.3)
            put(img, A["houses"][i], x, HORIZON + 250, sy=max(p, .001), anchor="b")
        for i, x in enumerate((220, 450, 690, 950)):
            s4, a4 = appear(t, T("восстановленные") + 0.1 * i, 0.5)
            put(img, A["tree"], x, HORIZON + 270, scale=s4 * 0.8, alpha=a4, anchor="b")
    accent(img, t, tb, ["ЖИЛЬЁ · РАБОТА", "ВОССТАНОВЛЕНИЕ"], y=400, size=56, accent_col=TEAL)
    return img


def sc_economy(t):
    sid = "economy"
    img = landscape(sid, t)
    T = lambda k: wt(sid, k) - 27.0
    header(img, t, "3 · ЭКОНОМИКА", BLUE)
    put(img, A["cloud_s"], 800 - t * 10, 560, alpha=.85)
    # --- опоры ЛЭП и провода
    tr = T("Восстановление")
    pyl_a = 1 - 0.7 * eo(prog(t, T("санкций") - 0.6, 0.5))
    for i, x in enumerate(PYLON_X):
        p = eback(prog(t, tr - 0.2 + 0.18 * i, 0.7), 1.2)
        put(img, A["pylon"], x, PYLON_TOP[i] + 420, sy=max(p, .001), sx=1, anchor="b", alpha=pyl_a)
    put(img, reveal(A["wires"], prog(t, tr + 0.6, 1.4)), 0, 0, anchor="tl", alpha=pyl_a)
    bs, ba = appear(t, T("миллиардов"), 0.5)
    accent(img, t, T("сотни") - 0.1, ["ПО ОЦЕНКАМ:", "СОТНИ МЛРД $"], y=400, size=62,
           accent_col=TEAL_D, t1=T("санкций") - 0.4)
    # --- санкции: замок и два варианта
    ts = T("санкций")
    ls, la = appear(t, ts - 0.4, 0.5)
    lock_out = eo(prog(t, T("Изменятся") - 0.3, 0.4))
    open_p = 0.5 + 0.5 * math.sin((t - ts) * 2.4) if t > ts else 0
    lx, ly = W / 2, 760
    put(img, A["shackle"], lx, ly - 90 - 50 * eio(open_p), scale=ls, alpha=la * (1 - lock_out))
    put(img, A["lock"], lx, ly + 20, scale=ls, alpha=la * (1 - lock_out))
    accent(img, t, ts - 0.2, ["САНКЦИИ?"], y=380, size=72, accent_col=RED, t1=T("Изменятся") - 0.3)
    if t > ts:
        on = open_p > 0.5
        for j, (txt, x) in enumerate((("смягчать", 300), ("сохранить", 780))):
            s5, a5 = appear(t, T("смягчать") + 0.3 * j, 0.4)
            active = (j == 0) == on
            put(img, chip(txt, TEAL if active else GREY, size=42), x, 1030,
                scale=s5 * (1.08 if active else 0.95), alpha=a5 * (1 - lock_out))
    # --- энергия, цены, инвестиции
    te = T("Изменятся")
    if t > te - 0.4:
        bs, ba = appear(t, te - 0.2, 0.5)
        put(img, A["bolt"], 220, 640 + 10 * math.sin(t * 4), scale=bs, alpha=ba)
        put(img, A["factory"], 790, HORIZON + 10, scale=bs * 0.8, alpha=ba, anchor="b")
        for k in range(5):
            ph = ((t - te) * 0.45 + k * 0.2) % 1.0
            put(img, A["puff"], 790 + 40 + ph * 50, HORIZON - 240 - ph * 230, scale=0.4 + ph * 0.9,
                alpha=ba * (1 - ph) * 0.9)
        # столбцы диаграммы: колеблются, затем стабилизируются
        stab = eio(prog(t, T("стабильности") - 0.4, 1.0))
        d = ImageDraw.Draw(img)
        bx0 = 120
        for k in range(5):
            target = 90 + k * 52
            wob = (1 - stab) * 70 * math.sin(t * 5 + k * 1.9)
            hgt = max(4, (target + wob) * eo(prog(t, T("цены") - 0.2 + 0.08 * k, 0.6)))
            x = bx0 + k * 78
            d.rounded_rectangle((x, HORIZON + 240 - hgt, x + 56, HORIZON + 240), radius=10,
                                fill=(TEAL if stab > .5 else CORAL) + (255,))
        for k in range(3):
            p = prog(t, T("инвесторы") + 0.25 * k, 0.9)
            if 0 < p < 1:
                put(img, A["coin"], 680 + k * 110, lerp(560, HORIZON + 40, eio(p)), alpha=1 - prog(p, 0.8, 0.2),
                    rot=p * 200)
    accent(img, t, te, ["ЭНЕРГЕТИКА · ЦЕНЫ", "ИНВЕСТИЦИИ"], y=400, size=54, accent_col=TEAL_D)
    return img


def sc_risks(t):
    sid = "risks"
    img = landscape(sid, t)
    T = lambda k: wt(sid, k) - 40.0
    header(img, t, "4 · РИСКИ", LILAC)
    # --- хрупкий мир: стеклянный голубь с трещиной
    th = T("хрупким")
    out1 = eo(prog(t, T("зависит") - 0.4, 0.5))
    shake = 6 * math.sin(t * 50) * (prog(t, th, 0.1) - prog(t, th + 0.6, 0.3))
    s1, a1 = appear(t, 0.1, 0.6)
    gx, gy = W / 2 + shake, 780
    fly_dove(img, gx, gy, t, scale=s1 * 1.6 * (1 - 0.3 * out1), glass=True, flap=2.5, alpha=a1 * (1 - out1))
    put(img, reveal(A["crack"], prog(t, th, 0.6), "bt"), gx - 20, gy + 10, scale=1.0, alpha=a1 * (1 - out1))
    accent(img, t, th - 0.1, ["ХРУПКИЙ МИР"], y=400, size=72, fg=INK, accent_col=None, t1=T("зависит") - 0.4)
    # --- документ соглашения с вопросами
    tz = T("условий")
    out2 = eo(prog(t, T("смогут") - 0.4, 0.5))
    p = eo(prog(t, T("зависит") - 0.3, 0.7))
    put(img, A["doc"], W / 2, lerp(1400, 820, p), alpha=c01(p * 2) * (1 - out2), rot=-3 + 3 * p)
    for i in range(3):
        qs, qa = appear(t, tz + 0.35 * i + 0.2, 0.4)
        put(img, A["q"], W / 2 - 155, lerp(1400, 820, p) - 300 + 200 + i * 110,
            scale=qs, alpha=qa * (1 - out2))
    accent(img, t, tz - 0.1, ["УСЛОВИЯ", "РЕШАЮТ ВСЁ"], y=400, size=64, accent_col=RED, t1=T("смогут") - 0.4)
    # --- весы доверия
    tsm = T("смогут")
    s3, a3 = appear(t, tsm - 0.3, 0.6)
    if a3 > 0:
        cx, cy = W / 2, 690
        ang = 14 * math.sin((t - tsm) * 2.2) * math.exp(-max(0, t - tsm) * 0.12)
        put(img, A["stand"], cx, cy + 430 * s3 - 20, scale=s3, alpha=a3, anchor="b")
        put(img, A["beam"], cx, cy, scale=s3, alpha=a3, rot=-ang)
        r = math.radians(ang)
        d = ImageDraw.Draw(img)
        for side, key in ((-1, "pan_l"), (1, "pan_r")):
            ex = cx + side * 290 * math.cos(r) * s3
            ey = cy + side * 290 * math.sin(r) * s3
            if a3 > .5:
                d.line((ex, ey, ex - 100 * s3, ey + 170 * s3), fill=(95, 105, 125, 255), width=4)
                d.line((ex, ey, ex + 100 * s3, ey + 170 * s3), fill=(95, 105, 125, 255), width=4)
            put(img, A[key], ex, ey + 170 * s3, scale=s3, alpha=a3)
    accent(img, t, T("доверять") - 0.1, ["ДОВЕРИЕ?"], y=400, size=72, accent_col=CORAL)
    return img


def sc_final(t):
    sid = "final"
    img = landscape(sid, t)
    T = lambda k: wt(sid, k) - 52.0
    put(img, A["glow_sun"], W / 2, HORIZON - 150 - 80 * eo(t / 6), scale=1.3)
    put(img, A["cloud"], 180 + t * 12, 640, alpha=.9)
    put(img, A["cloud_s"], 880 - t * 10, 760, alpha=.85)
    p = eio(prog(t, 0.0, 6.5))
    fly_dove(img, lerp(-180, 1260, p), 1000 - 180 * p, t, scale=0.9)
    # главный вопрос
    for i, (txt, size, col) in enumerate((("А КАК", 120, INK), ("ДУМАЕТЕ ВЫ?", 120, RED))):
        s, a = appear(t, 0.05 + 0.3 * i, 0.5)
        put(img, text_img(txt, size, col, shadow=False), W / 2, 340 + i * 140, scale=s, alpha=a)
    # пузырь комментария с «печатающими» точками
    tc = T("комментариях")
    bs, ba = appear(t, tc - 0.5, 0.5)
    put(img, A["bubble"], W / 2, 830, scale=bs, alpha=ba)
    for k in range(3):
        bob = 12 * max(0, math.sin(t * 7 - k * 0.9))
        put(img, A["dot"], W / 2 - 80 + k * 80, 800 - bob, scale=bs, alpha=ba)
    # кнопка подписки
    tp = T("подписывайтесь")
    ss, sa = appear(t, tp - 0.3, 0.5)
    pulse = 1 + 0.05 * max(0, math.sin((t - tp) * 6)) if t > tp else 1
    put(img, A["sub"], W / 2, 1080, scale=ss * pulse, alpha=sa)
    # сердечки
    for k in range(5):
        ph = ((t - tc) * 0.6 + k * 0.23) % 1.0
        if t > tc:
            put(img, A["heart_s"], 820 + 40 * math.sin(k * 2 + t * 2), 1120 - ph * 520, scale=0.6 + 0.6 * ph,
                alpha=(1 - ph) * ba)
    put(img, text_img("сценарии, а не прогнозы", 34, INK, "Inter-SemiBold.otf", False), W / 2, 610,
        alpha=0.7 * eo(prog(t, 1.2, 0.6)))
    return img


SCENE_FUNCS = [sc_hook, sc_security, sc_people, sc_economy, sc_risks, sc_final]
XFADE = 0.45


# ================================================================ СУБТИТРЫ
SUB_FONT = font("Inter-ExtraBold.otf", 64)
SUB_MAXW = W - 2 * 170
SUB_CENTER_Y = 1585
LINE_H = 84
SPACE_W = SUB_FONT.getlength(" ")


def build_chunks():
    """Разбиваем слова на фразы ≤ 2 строк (ширина ≤ SUB_MAXW)."""
    chunks, cur = [], []

    SH = {"и", "а", "в", "с", "к", "у", "о", "по", "на", "не", "из", "от", "для", "или", "между"}

    def width(ws):
        return sum(SUB_FONT.getlength(w[1]) for w in ws) + SPACE_W * (len(ws) - 1)

    def layout(ws):
        if width(ws) <= SUB_MAXW * 0.9 or (width(ws) <= SUB_MAXW and len(ws) <= 3):
            return [ws]
        best = None
        for k in range(1, len(ws)):
            a, b = ws[:k], ws[k:]
            wa, wb = width(a), width(b)
            if wa > SUB_MAXW or wb > SUB_MAXW:
                continue
            c = max(wa, wb) + (600 if a[-1][1].lower() in SH else 0) - (120 if a[-1][1][-1] in ",:—" else 0)
            if best is None or c < best[0]:
                best = (c, [a, b])
        if best:
            return best[1]
        return layout_greedy(ws)

    def layout_greedy(ws):
        lines, line, w = [], [], 0
        for wd in ws:
            ww = SUB_FONT.getlength(wd[1])
            if line and w + SPACE_W + ww > SUB_MAXW:
                lines.append(line); line, w = [], 0
            w = w + (SPACE_W if line else 0) + ww
            line.append(wd)
        if line:
            lines.append(line)
        return lines

    # предложения (в пределах сцены)
    sents, cur = [], []
    for wd in WORDS:
        if cur and cur[-1][0] != wd[0]:
            sents.append(cur); cur = []
        cur.append(wd)
        if wd[1].rstrip()[-1] in ".?!":
            sents.append(cur); cur = []
    if cur:
        sents.append(cur)
    SHORT = {"и", "а", "в", "с", "к", "у", "о", "по", "на", "не", "из", "от", "для", "или", "между"}

    def cost(seg, nxt):
        lay = layout(seg)
        if len(lay) > 2:
            return 1e9
        if len(lay) == 2 and lay[0][-1][1].lower() in SHORT:
            return 20.0 + (0 if seg[-1][1][-1] in ".?!,:" else 3)
        last = seg[-1][1].lower().strip(",:— ")
        c = 10.0
        if last in SHORT:
            c += 6
        if nxt is not None and nxt[1].lower() == "ли":
            c += 6
        if seg[-1][1].rstrip()[-1] in ",:—":
            c -= 3
        elif nxt is not None:
            c += 3
        if len(seg) == 1 and nxt is not None:
            c += 4
        return c

    for sent in sents:
        n = len(sent)
        best = [0.0] + [1e18] * n
        prev = [0] * (n + 1)
        for j in range(1, n + 1):
            for i in range(max(0, j - 8), j):
                cst = best[i] + cost(sent[i:j], sent[j] if j < n else None)
                if cst < best[j]:
                    best[j], prev[j] = cst, i
        cuts, j = [], n
        while j > 0:
            cuts.append((prev[j], j)); j = prev[j]
        for i, j in reversed(cuts):
            chunks.append(sent[i:j])
    out = []
    for k, ch in enumerate(chunks):
        start = ch[0][2] - 0.08
        nxt = chunks[k + 1][0][2] - 0.08 if k + 1 < len(chunks) else DURATION
        end = min(nxt, ch[-1][3] + 0.7)
        out.append(dict(words=ch, lines=layout(ch), start=start, end=end))
    return out


CHUNKS = build_chunks()


def draw_subs(frame, t):
    ch = next((c for c in CHUNKS if c["start"] <= t < c["end"]), None)
    if not ch:
        return
    a = eo(prog(t, ch["start"], 0.12)) * (1 - prog(t, ch["end"] - 0.1, 0.1))
    pop = 0.92 + 0.08 * eback(prog(t, ch["start"], 0.2))
    d = ImageDraw.Draw(frame, "RGBA")
    nl = len(ch["lines"])
    widths = [sum(SUB_FONT.getlength(w[1]) for w in ln) + SPACE_W * (len(ln) - 1) for ln in ch["lines"]]
    boxw = max(widths) + 70
    boxh = nl * LINE_H + 44
    y0 = SUB_CENTER_Y - boxh / 2
    d.rounded_rectangle((W / 2 - boxw / 2, y0, W / 2 + boxw / 2, y0 + boxh), radius=30,
                        fill=(20, 24, 40, int(175 * a)))
    for li, ln in enumerate(ch["lines"]):
        x = W / 2 - widths[li] / 2
        y = y0 + 22 + li * LINE_H + LINE_H / 2
        for (_, wd, s, e) in ln:
            ww = SUB_FONT.getlength(wd)
            if s <= t < e + 0.05:
                d.rounded_rectangle((x - 10, y - 40, x + ww + 10, y + 40), radius=16,
                                    fill=SAND + (int(255 * a),))
                col = INK
            elif t >= e:
                col = WHITE
            else:
                col = (200, 206, 220)
            d.text((x, y), wd, font=SUB_FONT, fill=col + (int(255 * a),), anchor="lm")
            x += ww + SPACE_W


# ================================================================ КАДР
def scene_frame(i, t):
    sc = SCENES[i]
    return SCENE_FUNCS[i](t - sc["start"]).convert("RGB")


def render_frame(n):
    t = n / FPS
    idx = max(i for i, s in enumerate(SCENES) if t >= s["start"] - 1e-9)
    img = scene_frame(idx, t)
    # кроссфейд на стыках сцен
    if idx > 0 and t < SCENES[idx]["start"] + XFADE / 2:
        a = eio((t - (SCENES[idx]["start"] - XFADE / 2)) / XFADE)
        img = Image.blend(scene_frame(idx - 1, t), img, a)
    elif idx + 1 < len(SCENES) and t > SCENES[idx + 1]["start"] - XFADE / 2:
        a = eio((t - (SCENES[idx + 1]["start"] - XFADE / 2)) / XFADE)
        img = Image.blend(img, scene_frame(idx + 1, t), a)
    # общая плавная «камера»: лёгкий наезд внутри сцены
    sc = SCENES[idx]
    z = 1.0 + 0.03 * (t - sc["start"]) / (sc["end"] - sc["start"])
    if z > 1.001:
        cw, chh = W / z, H / z
        img = img.resize((W, H), Image.BILINEAR, box=((W - cw) / 2, (H - chh) / 2, (W + cw) / 2, (H + chh) / 2))
    draw_subs(img, t)
    return img.tobytes()


def main():
    os.makedirs(OUT, exist_ok=True)
    args = sys.argv[1:]
    if "--frames" in args:
        fr = [int(x) for x in args[args.index("--frames") + 1].split(",")]
        os.makedirs(os.path.join(OUT, "preview"), exist_ok=True)
        for n in fr:
            Image.frombytes("RGB", (W, H), render_frame(n)).save(os.path.join(OUT, "preview", f"f{n:04}.png"))
        return
    audio = os.path.join(OUT, "music.wav")
    silent = os.path.join(ROOT, "build", "video_noaudio.mp4")
    os.makedirs(os.path.dirname(silent), exist_ok=True)
    cmd = ["ffmpeg", "-y", "-loglevel", "error", "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", f"{W}x{H}",
           "-r", str(FPS), "-i", "-", "-c:v", "libx264", "-preset", "medium", "-crf", "18",
           "-pix_fmt", "yuv420p", "-movflags", "+faststart", silent]
    p = subprocess.Popen(cmd, stdin=subprocess.PIPE)
    with Pool(os.cpu_count()) as pool:
        for k, buf in enumerate(pool.imap(render_frame, range(NF), chunksize=6)):
            p.stdin.write(buf)
            if k % 150 == 0:
                print(f"frame {k}/{NF}", file=sys.stderr)
    p.stdin.close(); p.wait()
    print("video done:", silent, file=sys.stderr)


if __name__ == "__main__":
    main()
