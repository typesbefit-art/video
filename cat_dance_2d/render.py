"""2D cartoon remake of a dancing ginger Scottish-fold cat video.

Renders frames with Pillow (rigged cat + flat room background) and muxes
them with ffmpeg. Usage:

    python3 render.py [audio_source.mp4] [out.mp4]

If an audio source is given, its first DURATION seconds are used as the
soundtrack.
"""
import math
import os
import random
import subprocess
import sys
import tempfile

from PIL import Image, ImageDraw, ImageFilter

# ---------------------------------------------------------------- settings
W, H = 720, 1280          # output size
SS = 2                    # supersampling factor
FPS = 24
DURATION = 16.0
FLOOR = 1110              # y of the floor contact line (output px)

FUR = (242, 160, 84)
FUR_DARK = (214, 122, 52)
CREAM = (253, 230, 196)
LINE = (110, 52, 22)
PINK = (247, 150, 158)
EYE = (150, 196, 92)
PUPIL = (30, 24, 20)
OUT = 4 * SS              # outline thickness (supersampled px)


def S(v):
    return int(round(v * SS))


# ---------------------------------------------------------------- helpers
def ell(d, cx, cy, rx, ry, fill, outline=None, width=0):
    d.ellipse([cx - rx, cy - ry, cx + rx, cy + ry], fill=fill,
              outline=outline, width=width)


def outlined(draw_fn, size):
    """Draw a silhouette with draw_fn(d, color, grow) twice: outline, fill."""
    img = Image.new("RGBA", size, (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    draw_fn(d, LINE, OUT)
    draw_fn(d, FUR, 0)
    return img, d


def capsule(d, x, y0, y1, r, col):
    d.rounded_rectangle([x - r, y0 - r, x + r, y1 + r], radius=r, fill=col)


# ---------------------------------------------------------------- sprites
def make_limb(length, width, end_rx, end_ry, stripes=2, pads=False):
    """Limb pointing down; pivot at top centre. Returns (img, pivot)."""
    L, r = S(length), S(width / 2)
    erx, ery = S(end_rx), S(end_ry)
    pad = OUT + S(4)
    w = 2 * max(r, erx) + 2 * pad
    h = L + r + ery + 2 * pad
    cx, top = w // 2, pad + r

    def sil(d, col, g):
        capsule(d, cx, top, top + L, r + g, col)
        if erx:
            ell(d, cx, top + L, erx + g, ery + g, col)

    img, d = outlined(sil, (w, h))
    mask = Image.new("L", img.size, 0)
    md = ImageDraw.Draw(mask)
    capsule(md, cx, top, top + L, r, 255)
    stripe = Image.new("RGBA", img.size, (0, 0, 0, 0))
    sd = ImageDraw.Draw(stripe)
    for i in range(stripes):
        yy = top + L * (0.25 + 0.3 * i)
        sd.arc([cx - r * 1.4, yy - S(10), cx + r * 1.4, yy + S(14)],
               200, 340, fill=FUR_DARK, width=S(7))
    img.paste(stripe, (0, 0), Image.composite(stripe, Image.new("RGBA", img.size), mask))
    if erx:
        ell(d, cx, top + L + ery * 0.15, erx * 0.75, ery * 0.6, CREAM)
        if pads:
            ell(d, cx, top + L + ery * 0.3, erx * 0.35, ery * 0.3, PINK)
            for k in (-1, 0, 1):
                ell(d, cx + k * erx * 0.45, top + L - ery * 0.25 - (k == 0) * S(4),
                    S(5), S(6), PINK)
    return img, (cx, top)


def make_torso(back=False):
    """Pear-shaped torso, pivot = hip point. Torso grows upward."""
    Ln, Wb, Wc = S(250), S(210), S(140)
    pad = OUT + S(6)
    w, h = Wb + 2 * pad, Ln + S(80) + 2 * pad
    cx = w // 2
    neck_y = pad + S(10)
    hip_y = neck_y + Ln - S(30)

    def sil(d, col, g):
        ell(d, cx, hip_y - S(25), Wb / 2 + g, S(110) + g, col)      # belly
        ell(d, cx, neck_y + S(80), Wc / 2 + g, S(95) + g, col)      # chest
        d.polygon([(cx - Wc / 2 - g, neck_y + S(80)), (cx + Wc / 2 + g, neck_y + S(80)),
                   (cx + Wb / 2 + g, hip_y - S(25)), (cx - Wb / 2 - g, hip_y - S(25))],
                  fill=col)

    img, d = outlined(sil, (w, h))
    mask = Image.new("L", img.size, 0)
    sil(ImageDraw.Draw(mask), 255, 0)
    deco = Image.new("RGBA", img.size, (0, 0, 0, 0))
    dd = ImageDraw.Draw(deco)
    if not back:
        ell(dd, cx, hip_y - S(40), S(62), S(95), CREAM)
        ell(dd, cx, neck_y + S(55), S(48), S(60), CREAM)
        for side in (-1, 1):
            for i in range(4):
                yy = neck_y + S(70) + i * S(42)
                x0 = cx + side * (Wc / 2 + S(10) + i * S(8))
                dd.line([(x0, yy), (x0 - side * S(38), yy + S(14))],
                        fill=FUR_DARK, width=S(9))
    else:
        for i in range(6):
            yy = neck_y + S(30) + i * S(36)
            dd.arc([cx - Wb * 0.55, yy, cx + Wb * 0.55, yy + S(50)],
                   200, 340, fill=FUR_DARK, width=S(10))
        dd.line([(cx, neck_y), (cx, hip_y)], fill=FUR_DARK, width=S(10))
    img.paste(deco, (0, 0), Image.composite(deco, Image.new("RGBA", img.size), mask))
    return img, (cx, hip_y), Ln - S(30)  # sprite, pivot, hip->neck length


def make_head(mode="open"):
    """Round Scottish-fold head; pivot = neck point at bottom."""
    pad = OUT + S(8)
    rx, ry = S(110), S(92)
    w, h = 2 * rx + S(60) + 2 * pad, 2 * ry + S(60) + 2 * pad
    cx, cy = w // 2, pad + S(40) + ry

    def sil(d, col, g):
        for side in (-1, 1):  # folded ears
            ex, ey = cx + side * S(62), cy - ry + S(14)
            d.pieslice([ex - S(38) - g, ey - S(30) - g, ex + S(38) + g, ey + S(34) + g],
                       180, 360, fill=col)
            ell(d, cx + side * S(92), cy + S(40), S(40) + g, S(34) + g, col)  # cheeks
        ell(d, cx, cy, rx + g, ry + g, col)

    img, d = outlined(sil, (w, h))
    if mode == "back":
        for i in range(5):
            x = cx + (i - 2) * S(30)
            d.line([(x, cy - ry + S(10)), (x, cy - S(10))], fill=FUR_DARK, width=S(10))
        for side in (-1, 1):
            ex, ey = cx + side * S(62), cy - ry + S(14)
            d.arc([ex - S(30), ey - S(20), ex + S(30), ey + S(28)], 200, 340,
                  fill=LINE, width=S(4))
        return img, (cx, cy + ry - S(10))

    for side in (-1, 1):  # ear fold lines
        ex, ey = cx + side * S(62), cy - ry + S(14)
        d.arc([ex - S(30), ey - S(20), ex + S(30), ey + S(28)], 200, 340,
              fill=LINE, width=S(4))
        ell(d, ex, ey - S(4), S(20), S(10), PINK)
    for i in (-1, 0, 1):  # forehead "M" stripes
        x = cx + i * S(26)
        d.line([(x, cy - ry + S(6)), (x - i * S(6), cy - S(38))], fill=FUR_DARK, width=S(9))
    for side in (-1, 1):  # side stripes
        d.line([(cx + side * S(100), cy - S(10)), (cx + side * S(76), cy)],
               fill=FUR_DARK, width=S(8))
        d.line([(cx + side * S(104), cy + S(16)), (cx + side * S(80), cy + S(20))],
               fill=FUR_DARK, width=S(8))
    # muzzle
    ell(d, cx - S(22), cy + S(46), S(30), S(24), CREAM)
    ell(d, cx + S(22), cy + S(46), S(30), S(24), CREAM)
    ell(d, cx, cy + S(30), S(26), S(16), CREAM)
    # eyes
    for side in (-1, 1):
        ex, ey = cx + side * S(46), cy + S(2)
        if mode == "blink":
            d.arc([ex - S(26), ey - S(14), ex + S(26), ey + S(18)], 20, 160,
                  fill=LINE, width=S(6))
            continue
        ell(d, ex, ey, S(30), S(32), LINE)
        ell(d, ex, ey, S(26), S(28), EYE)
        ell(d, ex, ey + S(2), S(17), S(21), PUPIL)
        ell(d, ex - S(8), ey - S(10), S(8), S(8), (255, 255, 255))
        ell(d, ex + S(9), ey + S(9), S(4), S(4), (255, 255, 255))
    # nose + mouth
    d.polygon([(cx - S(11), cy + S(28)), (cx + S(11), cy + S(28)), (cx, cy + S(40))],
              fill=PINK, outline=LINE)
    if mode == "mouth":
        ell(d, cx, cy + S(60), S(14), S(16), LINE)
        ell(d, cx, cy + S(64), S(9), S(9), PINK)
    else:
        d.line([(cx, cy + S(40)), (cx, cy + S(50))], fill=LINE, width=S(4))
        d.arc([cx - S(22), cy + S(38), cx, cy + S(60)], 0, 160, fill=LINE, width=S(4))
        d.arc([cx, cy + S(38), cx + S(22), cy + S(60)], 20, 180, fill=LINE, width=S(4))
    for side in (-1, 1):  # whiskers
        for k in (-1, 0, 1):
            d.line([(cx + side * S(56), cy + S(46) + k * S(9)),
                    (cx + side * S(130), cy + S(38) + k * S(18))],
                   fill=(255, 245, 230), width=S(3))
    return img, (cx, cy + ry - S(10))


def make_tail_seg(last=False):
    L, r = S(34), S(24)
    pad = OUT + S(2)
    w, h = 2 * r + 2 * pad, L + 2 * r + 2 * pad
    cx, top = w // 2, pad + r

    def sil(d, col, g):
        capsule(d, cx, top, top + L, r + g, col)

    img, d = outlined(sil, (w, h))
    capsule(d, cx, top + S(4), top + L - S(4), r, FUR)
    d.rectangle([cx - r + S(3), top + L * 0.45, cx + r - S(3), top + L * 0.45 + S(10)],
                fill=FUR_DARK)
    return img, (cx, top)


# ---------------------------------------------------------------- background
def make_background():
    bg = Image.new("RGB", (W * SS, H * SS), (232, 220, 200))
    d = ImageDraw.Draw(bg)
    wall_bottom = S(990)
    # back wall gradient
    for y in range(0, wall_bottom, SS * 4):
        k = y / wall_bottom
        c = tuple(int(a * (1 - k) + b * k) for a, b in zip((240, 232, 216), (214, 200, 178)))
        d.rectangle([0, y, W * SS, y + SS * 4], fill=c)
    # left corner wall (slightly shadowed)
    d.polygon([(0, 0), (S(140), 0), (S(140), S(1000)), (0, S(1060))], fill=(222, 208, 186))
    d.line([(S(140), 0), (S(140), S(1000))], fill=(200, 184, 160), width=S(3))
    # door
    dx0, dx1, dy0 = S(470), S(735), S(110)
    d.rectangle([dx0 - S(14), dy0 - S(14), dx1, wall_bottom], fill=(92, 54, 30))
    d.rectangle([dx0, dy0, dx1, wall_bottom], fill=(122, 74, 42))
    for (py0, py1) in ((150, 520), (570, 940)):
        d.rounded_rectangle([dx0 + S(30), S(py0), dx1 - S(20), S(py1)], radius=S(8),
                            outline=(92, 54, 30), width=S(6))
    ell(d, dx0 + S(40), S(560), S(12), S(12), (214, 176, 90))
    # light switch
    d.rounded_rectangle([S(420), S(560), S(444), S(610)], radius=S(4), fill=(246, 240, 228),
                        outline=(190, 176, 150), width=S(2))
    # baseboard
    d.polygon([(0, S(1040)), (S(140), S(990)), (W * SS, S(990)), (W * SS, S(1020)),
               (S(140), S(1020)), (0, S(1075))], fill=(150, 98, 60))
    # carpet floor
    d.polygon([(0, S(1075)), (S(140), S(1020)), (W * SS, S(1020)), (W * SS, H * SS),
               (0, H * SS)], fill=(206, 194, 172))
    rnd = random.Random(7)
    for _ in range(9000):
        x, y = rnd.randrange(W * SS), rnd.randrange(S(1025), H * SS)
        c = rnd.choice([(190, 178, 156), (222, 212, 194), (198, 186, 164)])
        r = rnd.choice([1, 2, 3])
        d.ellipse([x - r, y - r, x + r, y + r], fill=c)
    # little plant by the door
    for i, a in enumerate(range(-60, 61, 30)):
        ang = math.radians(a)
        d.line([(S(458), S(990)), (S(458) + math.sin(ang) * S(24), S(990) - math.cos(ang) * S(30))],
               fill=(96, 150, 70), width=S(5))
    # vignette
    vig = Image.new("L", bg.size, 0)
    ImageDraw.Draw(vig).ellipse([-S(200), -S(150), W * SS + S(200), H * SS + S(150)], fill=255)
    vig = vig.filter(ImageFilter.GaussianBlur(S(120)))
    dark = Image.new("RGB", bg.size, (120, 100, 80))
    return Image.composite(bg, dark, vig)


# ---------------------------------------------------------------- poses
BASE = dict(x=360, air=0, s=1.0, t=0, st=1.0, sq=1.0, hd=0,
            aLu=10, aLf=115, aRu=-10, aRf=-115,
            lLu=-8, lLf=-3, lRu=8, lRf=3,
            tail=100, curl=9, back=0, face=0)  # face: 0 open, 1 blink, 2 mouth


def P(base=None, **kw):
    p = dict(BASE if base is None else base)
    if "arms" in kw:   # symmetric arms given as (upper, fore) for screen-left
        u, f = kw.pop("arms")
        p.update(aLu=u, aLf=f, aRu=-u, aRf=-f)
    if "legs" in kw:
        u, f = kw.pop("legs")
        p.update(lLu=u, lLf=f, lRu=-u, lRf=-f)
    p.update(kw)
    return p


STAND = P()
CROUCH_UP = P(legs=(-38, -8), st=0.88, arms=(-125, -165), face=2)
TALL = P(st=1.12, legs=(-3, 0), aLu=-12, aLf=-6, aRu=168, aRf=176)
SQUAT_PRAY = P(legs=(-70, 15), arms=(32, 158), hd=10)
BOW = P(x=470, t=135, hd=160, legs=(-12, -4), aLu=-5, aLf=5, aRu=10, aRf=0, tail=200, curl=6)
SWING_A = P(x=345, t=-8, legs=(-22, -6), aLu=-70, aLf=-90, aRu=-25, aRf=-60, hd=6, tail=70)
SWING_B = P(x=375, t=8, legs=(-22, -6), aRu=70, aRf=90, aLu=25, aLf=60, hd=-6, tail=50)
KICK = P(lRu=62, lRf=40, aLu=-150, aLf=-172, aRu=-10, aRf=-115, t=-6)
BACK = P(back=1, arms=(-150, -170), st=1.08)
HANDS_HEAD = P(st=1.1, arms=(-150, 120))
ARMS_UP = P(st=1.12, arms=(-165, -176), face=2)
SQUAT_WIDE = P(legs=(-52, -18), st=0.86, arms=(-82, -72), face=2)
CLASP = P(arms=(26, 112))
CLASP_KL = P(CLASP, lLu=-58, lLf=-38, t=5)
CLASP_KR = P(CLASP, lRu=58, lRf=38, t=-5)
DISCO_A = P(legs=(-30, -8), aLu=-162, aLf=-176, aRu=-25, aRf=-60, t=4)
DISCO_B = P(legs=(-30, -8), aLu=-70, aLf=-40, aRu=-30, aRf=-70)
DISCO_C = P(legs=(-30, -8), aLu=20, aLf=60, aRu=128, aRf=118, t=-5)
LIE = P(x=480, s=0.78, t=90, hd=-4, aLu=-55, aLf=-80, aRu=-65, aRf=-88,
        lLu=-40, lLf=-82, lRu=-28, lRf=-78, tail=150, curl=-12)
SIT = P(legs=(-78, -4), arms=(14, 100))
SIT_FAR = P(SIT, s=0.68, x=380)
JUMP = P(s=0.85, x=370, air=200, legs=(-5, 0), arms=(-150, -165), st=1.1, face=2)
SIT_CLOSE = P(SIT, s=1.12, x=390, arms=(30, 150))
BOX_A = P(SIT, s=0.98, x=360, hd=-12, t=-4, aLu=-22, aLf=172, aRu=8, aRf=-62)
BOX_B = P(SIT, s=0.98, x=360, hd=12, t=4, aRu=22, aRf=-172, aLu=-8, aLf=62)


def step(p, side):
    if side == "L":
        return P(p, lLu=-28, lLf=18, t=-4)
    return P(p, lRu=28, lRf=-18, t=4)


# (time, pose, cut?)  cut=True -> jump to this pose with no in-between
KEYS = [
    (0.00, STAND, False), (0.25, step(STAND, "L"), False), (0.50, step(STAND, "R"), False),
    (0.75, step(STAND, "L"), False), (1.00, CROUCH_UP, False),
    (1.25, P(CROUCH_UP, arms=(-112, -150)), False), (1.50, TALL, False),
    (1.75, P(TALL, aRu=176, aRf=180, st=1.16), False), (2.00, P(SWING_A, t=-14), False),
    (2.25, SQUAT_PRAY, False), (2.50, P(SQUAT_PRAY, hd=4), False), (2.75, BOW, False),
    (3.05, BOW, False),
]
t = 3.25
for i in range(7):
    KEYS.append((t, SWING_B if i % 2 == 0 else SWING_A, False))
    t += 0.25
KEYS += [
    (5.00, KICK, False), (5.25, STAND, False), (5.50, BACK, False), (5.75, HANDS_HEAD, False),
    (6.00, ARMS_UP, False), (6.25, P(ARMS_UP, arms=(-160, -170)), False),
    (6.50, SQUAT_WIDE, False), (6.75, P(SQUAT_WIDE, arms=(-76, -60)), False),
    (7.00, CLASP, False), (7.25, CLASP_KL, False), (7.50, CLASP, False), (7.75, CLASP_KR, False),
    (8.00, DISCO_A, False), (8.25, DISCO_B, False), (8.50, P(DISCO_B, aLu=-20, aLf=40), False),
    (8.75, DISCO_C, False), (9.05, P(DISCO_C, aRu=100, aRf=112), False),
    (9.25, LIE, True), (11.55, P(LIE, hd=4), False),
    (11.75, SIT_FAR, True), (12.15, P(SIT_FAR, hd=-6), False), (12.50, SIT_FAR, False),
    (12.75, JUMP, False), (13.05, P(JUMP, air=150, arms=(-140, -150)), False),
    (13.25, SIT_CLOSE, True), (13.55, P(SIT_CLOSE, hd=-8), False),
]
t = 13.75
i = 0
while t < DURATION + 0.3:
    KEYS.append((t, BOX_A if i % 2 == 0 else BOX_B, i == 0))
    t += 0.25
    i += 1


def ease(u):
    return u * u * (3 - 2 * u)


def pose_at(time):
    p = _pose_at(time)
    p["s"] *= CAM
    return p


def _pose_at(time):
    for k in range(len(KEYS) - 1):
        t0, p0, _ = KEYS[k]
        t1, p1, cut1 = KEYS[k + 1]
        if t0 <= time < t1:
            if cut1:
                return dict(p0)
            u = ease((time - t0) / (t1 - t0))
            out = {}
            for key in p0:
                if key in ("back", "face"):
                    out[key] = p0[key] if u < 0.5 else p1[key]
                else:
                    out[key] = p0[key] + (p1[key] - p0[key]) * u
            return out
    return dict(KEYS[-1][1])


# ---------------------------------------------------------------- rig
def vdir(a):
    r = math.radians(a)
    return math.sin(r), math.cos(r)


class Rig:
    def __init__(self):
        self.torso = make_torso()
        self.torso_back = make_torso(back=True)
        self.upper_arm = make_limb(78, 46, 0, 0, stripes=1)
        self.fore_arm = make_limb(70, 42, 30, 26, stripes=1, pads=True)
        self.thigh = make_limb(88, 58, 0, 0, stripes=2)
        self.shin = make_limb(76, 48, 36, 24, stripes=1)
        self.heads = {0: make_head("open"), 1: make_head("blink"),
                      2: make_head("mouth"), "back": make_head("back")}
        self.tail = make_tail_seg()
        self._cache = {}

    def scaled(self, key, spr, sx, sy=None):
        sy = sx if sy is None else sy
        ck = (key, round(sx, 3), round(sy, 3))
        if ck not in self._cache:
            img, (px, py) = spr
            nw, nh = max(1, int(img.width * sx)), max(1, int(img.height * sy))
            if len(self._cache) > 400:
                self._cache.clear()
            self._cache[ck] = (img.resize((nw, nh), Image.LANCZOS), (px * sx, py * sy))
        return self._cache[ck]


def put(canvas, spr, pos, angle):
    img, (px, py) = spr
    R = int(math.ceil(max(math.hypot(px - cx, py - cy)
                          for cx in (0, img.width) for cy in (0, img.height)))) + 2
    pad = Image.new("RGBA", (2 * R, 2 * R), (0, 0, 0, 0))
    pad.paste(img, (int(round(R - px)), int(round(R - py))))
    rot = pad.rotate(angle, resample=Image.BICUBIC)
    canvas.paste(rot, (int(round(pos[0] - R)), int(round(pos[1] - R))), rot)


CAM = 1.22


def layout(p):
    """Compute joint positions (output px, hip at y=0)."""
    s = p["s"]
    hip = (p["x"], 0.0)
    tL = 220 * p["st"] * s
    u = (-vdir(p["t"])[0], -vdir(p["t"])[1])          # torso up
    r = (math.cos(math.radians(p["t"])), -math.sin(math.radians(p["t"])))  # torso right
    neck = (hip[0] + u[0] * tL, hip[1] + u[1] * tL)
    sh = 0.86 * tL
    J = {"hip": hip, "neck": neck, "u": u, "r": r}
    for side, sgn in (("L", -1), ("R", 1)):
        shp = (hip[0] + u[0] * sh + r[0] * sgn * 58 * s * p["sq"],
               hip[1] + u[1] * sh + r[1] * sgn * 58 * s * p["sq"])
        el = tuple(shp[i] + vdir(p["a" + side + "u"])[i] * 74 * s for i in range(2))
        wr = tuple(el[i] + vdir(p["a" + side + "f"])[i] * 66 * s for i in range(2))
        hp = (hip[0] + r[0] * sgn * 52 * s * p["sq"] - u[0] * 8 * s,
              hip[1] + r[1] * sgn * 52 * s * p["sq"] - u[1] * 8 * s)
        kn = tuple(hp[i] + vdir(p["l" + side + "u"])[i] * 84 * s for i in range(2))
        an = tuple(kn[i] + vdir(p["l" + side + "f"])[i] * 72 * s for i in range(2))
        J[side] = dict(sh=shp, el=el, wr=wr, hp=hp, kn=kn, an=an)
    hu = vdir(p["hd"])
    J["head_up"] = (-hu[0], -hu[1])
    return J


def lowest(p, J):
    s = p["s"]
    pts = []
    for side in "LR":
        pts.append(J[side]["an"][1] + 22 * s)
        pts.append(J[side]["wr"][1] + 24 * s)
    # torso outline (approximate ellipse around belly)
    cx = J["hip"][0] + J["u"][0] * (-25 * s)
    cy = J["hip"][1] + J["u"][1] * (-25 * s)
    for k in range(24):
        a = 2 * math.pi * k / 24
        lx, ly = math.cos(a) * 105 * s * p["sq"], math.sin(a) * 110 * s
        pts.append(cy + J["r"][1] * lx + (-J["u"][1]) * ly)
    hx, hy = J["neck"]
    pts.append(hy + J["head_up"][1] * 80 * s + 110 * s)
    return max(pts)


def draw_cat(canvas, rig, p, time):
    s = p["s"]
    J = layout(p)
    dy = FLOOR - p["air"] - lowest(p, J)

    def W_(pt):
        return ((pt[0]) * SS, (pt[1] + dy) * SS)

    # shadow
    sh = Image.new("RGBA", canvas.size, (0, 0, 0, 0))
    k = 1 / (1 + p["air"] / 150)
    sw = (160 if p["t"] < 45 else 260) * s * k
    ImageDraw.Draw(sh).ellipse([(J["hip"][0] - sw) * SS, (FLOOR - 14 * s) * SS,
                                (J["hip"][0] + sw) * SS, (FLOOR + 18 * s) * SS],
                               fill=(70, 50, 30, int(90 * k)))
    canvas.alpha_composite(sh.filter(ImageFilter.GaussianBlur(S(8))))

    # tail (behind)
    seg = rig.scaled("tail", rig.tail, s)
    base = (J["hip"][0] + J["r"][0] * 40 * s - J["u"][0] * 20 * s,
            J["hip"][1] + J["r"][1] * 40 * s - J["u"][1] * 20 * s)
    a = p["tail"]
    pos = base
    for i in range(7):
        a += p["curl"] + 10 * math.sin(time * 7 - i * 0.7)
        put(canvas, seg, W_(pos), a)
        dv = vdir(a)
        pos = (pos[0] + dv[0] * 32 * s, pos[1] + dv[1] * 32 * s)

    back = p["back"] >= 0.5
    order = ("R", "L") if p["t"] > 45 else ("L", "R")
    # legs
    for side in order:
        j = J[side]
        put(canvas, rig.scaled("shin", rig.shin, s), W_(j["kn"]), p["l" + side + "f"])
        put(canvas, rig.scaled("thigh", rig.thigh, s), W_(j["hp"]), p["l" + side + "u"])

    def arm(side):
        j = J[side]
        put(canvas, rig.scaled("upper", rig.upper_arm, s), W_(j["sh"]), p["a" + side + "u"])
        put(canvas, rig.scaled("fore", rig.fore_arm, s), W_(j["el"]), p["a" + side + "f"])

    if back:
        for side in order:
            arm(side)
    # torso
    tor = rig.torso_back if back else rig.torso
    breathe = 1 + 0.015 * math.sin(time * 6)
    ts = rig.scaled("torso_b" if back else "torso", tor[:2],
                    s * p["sq"] * breathe, s * p["st"] * 220 / 220)
    put(canvas, ts, W_(J["hip"]), p["t"])
    # head
    if back:
        head = rig.heads["back"]
    else:
        face = int(round(p["face"]))
        blink = (time % 3.1) < 0.12 and face == 0
        head = rig.heads[1 if blink else face]
    hs = rig.scaled(("head", id(head)), head, s * 1.15)
    neck = (J["neck"][0] + J["head_up"][0] * 4 * s, J["neck"][1] + J["head_up"][1] * 4 * s)
    put(canvas, hs, W_(neck), p["hd"])
    if not back:
        for side in order:
            arm(side)


# ---------------------------------------------------------------- main
def main():
    audio_src = sys.argv[1] if len(sys.argv) > 1 else None
    out = sys.argv[2] if len(sys.argv) > 2 else os.path.join(os.path.dirname(__file__),
                                                             "cat_dance_2d.mp4")
    bg = make_background().convert("RGBA")
    rig = Rig()
    n = int(DURATION * FPS)
    cmd = ["ffmpeg", "-v", "error", "-y", "-f", "rawvideo", "-pix_fmt", "rgb24",
           "-s", f"{W}x{H}", "-r", str(FPS), "-i", "-"]
    if audio_src:
        cmd += ["-t", str(DURATION), "-i", audio_src, "-map", "0:v", "-map", "1:a",
                "-af", f"afade=t=out:st={DURATION - 0.5}:d=0.5", "-c:a", "aac", "-b:a", "160k"]
    cmd += ["-vf", f"fade=t=out:st={DURATION - 0.4}:d=0.4", "-c:v", "libx264",
            "-pix_fmt", "yuv420p", "-crf", "18", "-preset", "medium", "-shortest", out]
    proc = subprocess.Popen(cmd, stdin=subprocess.PIPE)
    for f in range(n):
        time = f / FPS
        p = pose_at(time)
        # small groove bounce on the beat while standing
        if p["t"] < 45 and p["air"] < 1:
            p["st"] *= 1 - 0.03 * abs(math.sin(time * math.pi * 2))
        frame = bg.copy()
        draw_cat(frame, rig, p, time)
        frame = frame.convert("RGB").resize((W, H), Image.LANCZOS)
        proc.stdin.write(frame.tobytes())
        if f % 48 == 0:
            print(f"frame {f}/{n}", flush=True)
    proc.stdin.close()
    proc.wait()
    print("wrote", out)


if __name__ == "__main__":
    main()
