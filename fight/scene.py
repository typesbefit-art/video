"""Static, cached background: layered night city (sky, far skyline, mid towers
with neon, street facade, alley wall), wet asphalt with mirrored reflections.

Layers are pre-rendered once (deterministic) in world metres and drawn every
frame with a single affine resample each. Parallax follows a dolly camera
model: a layer at distance d behind the fighter plane appears at
zoom_l = zoom / (1 + d * zoom / F).
"""
import math
import numpy as np
from PIL import Image, ImageDraw, ImageFilter, ImageChops
from .config import LENS_F

NEON = {
    'teal': (20, 235, 215), 'cyan': (60, 190, 255), 'pink': (255, 50, 150),
    'orange': (255, 135, 30), 'red': (255, 50, 45), 'violet': (165, 80, 255),
    'amber': (255, 190, 70),
}


def value_noise(w, h, cell, rng, octaves=4, persistence=0.5):
    acc = np.zeros((h, w), np.float32)
    amp, tot = 1.0, 0.0
    for o in range(octaves):
        c = max(1.0, cell / (2 ** o))
        gw, gh = max(2, int(w / c) + 2), max(2, int(h / c) + 2)
        g = Image.fromarray((rng.random((gh, gw)) * 255).astype(np.uint8))
        g = g.resize((int(gw * c), int(gh * c)), Image.BICUBIC).crop((0, 0, w, h))
        acc += np.asarray(g, np.float32) / 255.0 * amp
        tot += amp
        amp *= persistence
    return acc / tot


class Layer:
    def __init__(self, img, res, x0, y1, d, glow=None, glow_res=None):
        self.d, self.x0, self.y1 = d, x0, y1
        self.mips = []
        r, im = res, img
        while True:
            self.mips.append((r, im))
            if im.width < 600 or len(self.mips) >= 4:
                break
            im = im.resize((im.width // 2, im.height // 2), Image.BOX)
            r = r / 2
        self.glow = None
        if glow is not None:
            self.glow = (glow_res, glow)

    def zoom_l(self, zoom, s):
        return zoom * s / (1.0 + self.d * zoom / LENS_F)

    def _pick(self, zl):
        best = self.mips[0]
        for r, im in self.mips:
            if r / zl <= 1.5:
                best = (r, im)
                continue
            break
        # choose the coarsest mip whose ratio still >= ~0.75 to avoid aliasing
        for r, im in self.mips:
            if r / zl < 1.6:
                return r, im
            best = (r, im)
        return best

    def coeffs(self, cam, s, ax, ay, res, out_scale=1.0, mirror=False):
        zl = self.zoom_l(cam['zoom'], s) * out_scale
        k = res / zl
        a = k
        c = (cam['cx'] - self.x0) * res - ax * out_scale * k
        if not mirror:
            e = k
            f = (self.y1 - cam['cy']) * res - ay * out_scale * k
        else:
            e = -k
            f = (self.y1 + cam['cy']) * res + ay * out_scale * k
        return (a, 0.0, c, 0.0, e, f), zl

    def draw(self, size, cam, s, ax, ay, out_scale=1.0, mirror=False, glow=False):
        zl = self.zoom_l(cam['zoom'], s) * out_scale
        if glow:
            res, im = self.glow
        else:
            res, im = self._pick(zl)
        co, _ = self.coeffs(cam, s, ax, ay, res, out_scale, mirror)
        return im.transform(size, Image.AFFINE, co, resample=Image.BILINEAR)

    def base_y(self, cam, s, ay, out_scale=1.0):
        return ay * out_scale + cam['cy'] * self.zoom_l(cam['zoom'], s) * out_scale


# ------------------------------------------------------------------ builders
def _fog_overlay(img, res, col, y_lo, y_hi, a_lo, a_hi):
    w, h = img.size
    ys = (img.height - np.arange(h)) / res  # world height of each row
    t = np.clip((ys - y_lo) / (y_hi - y_lo), 0, 1)
    a = (a_lo + (a_hi - a_lo) * t).astype(np.float32)
    arr = np.asarray(img).astype(np.float32)
    rgb, al = arr[..., :3], arr[..., 3:4]
    m = a[:, None, None]
    rgb = rgb * (1 - m) + np.array(col, np.float32) * m
    return Image.fromarray(np.dstack([rgb, al]).clip(0, 255).astype(np.uint8), 'RGBA')


def _glyph(dr, x, y, cw, ch, col, wid, rng):
    for _ in range(rng.integers(2, 5)):
        kind = rng.integers(0, 3)
        if kind == 0:
            yy = y + rng.random() * ch
            dr.line([(x + cw * 0.1, yy), (x + cw * 0.9, yy)], fill=col, width=wid)
        elif kind == 1:
            xx = x + rng.random() * cw
            dr.line([(xx, y + ch * 0.1), (xx, y + ch * 0.9)], fill=col, width=wid)
        else:
            dr.line([(x + cw * rng.random(), y + ch * rng.random()),
                     (x + cw * rng.random(), y + ch * rng.random())], fill=col, width=wid)


def build_sky(rng):
    res, W, H = 2.0, 1600, 2600  # x [-400,400] m, y [0,1300] m
    y = np.arange(H, dtype=np.float32)[:, None] / H  # 0 top .. 1 bottom
    top = np.array([4, 6, 14], np.float32)
    mid = np.array([16, 18, 34], np.float32)
    hor = np.array([70, 42, 48], np.float32)
    t = y ** 2.2
    col = top * (1 - t)[..., None] + mid * t[..., None]
    g = np.clip((y - 0.86) / 0.14, 0, 1) ** 1.5
    col = col * (1 - g)[..., None] + hor * g[..., None]
    n = value_noise(W, H, 220, rng, 5)
    n2 = value_noise(W, H, 60, rng, 3)
    cloud = np.clip((n * 0.75 + n2 * 0.25 - 0.45) * 2.2, 0, 1) * (0.25 + 0.75 * y)
    cl = np.array([58, 44, 60], np.float32)
    col = col * (1 - cloud[..., None] * 0.55) + cl * cloud[..., None] * 0.55
    col = np.broadcast_to(col, (H, W, 3)) if col.shape[1] == 1 else col
    a = np.full((H, W, 1), 255, np.float32)
    img = Image.fromarray(np.dstack([col, a]).clip(0, 255).astype(np.uint8), 'RGBA')
    return Layer(img, res, -400.0, H / res, 1500.0)


def build_far(rng):
    res = 24.0
    x0, x1, yt = -75.0, 75.0, 140.0
    W, H = int((x1 - x0) * res), int(yt * res)
    img = Image.new('RGBA', (W, H), (0, 0, 0, 0))
    dr = ImageDraw.Draw(img)
    x = x0
    while x < x1:
        w = rng.uniform(6, 18)
        h = rng.uniform(35, 120) * (0.6 + 0.4 * math.cos(x / 60))
        c = rng.integers(14, 26)
        col = (c, c + 4, c + 18, 255)
        px0, px1 = (x - x0) * res, (x + w - x0) * res
        dr.rectangle([px0, H - h * res, px1, H], fill=col)
        if rng.random() < 0.5:  # stepped top
            dr.rectangle([px0 + w * res * 0.2, H - (h + rng.uniform(3, 10)) * res,
                          px1 - w * res * 0.25, H], fill=col)
        if rng.random() < 0.4:
            ax = (px0 + px1) / 2
            dr.line([(ax, H - h * res), (ax, H - (h + 12) * res)], fill=col, width=2)
            dr.rectangle([ax - 2, H - (h + 12) * res - 2, ax + 2, H - (h + 12) * res + 2],
                         fill=(255, 40, 40, 255))
        # windows
        n = int(w * h * 0.5)
        wx = rng.uniform(px0 + 2, px1 - 2, n)
        wy = rng.uniform(H - h * res + 4, H, n)
        lit = rng.random(n) < 0.22
        for X, Y, L in zip(wx, wy, lit):
            if L:
                cc = (255, 200, 120) if rng.random() < 0.6 else (150, 220, 255)
                k = rng.uniform(0.35, 0.8)
                dr.point((X, Y), fill=(int(cc[0] * k), int(cc[1] * k), int(cc[2] * k), 255))
        x += w + rng.uniform(-2, 3)
    img = _fog_overlay(img, res, (62, 48, 66), 0, 70, 0.7, 0.18)
    return Layer(img, res, x0, yt, 150.0)


def build_mid(rng):
    res = 60.0
    x0, x1, yt = -40.0, 40.0, 75.0
    W, H = int((x1 - x0) * res), int(yt * res)
    gres = 15.0
    img = Image.new('RGBA', (W, H), (0, 0, 0, 0))
    glow = Image.new('RGB', (int(W * gres / res), int(H * gres / res)), (0, 0, 0))
    dr, dg = ImageDraw.Draw(img), ImageDraw.Draw(glow)
    x = x0
    while x < x1:
        w = rng.uniform(8, 20)
        h = rng.uniform(18, 62)
        c = int(rng.integers(18, 32))
        col = (c, c + 3, c + 12, 255)
        px0, px1 = (x - x0) * res, (x + w - x0) * res
        top = H - h * res
        dr.rectangle([px0, top, px1, H], fill=col)
        # edge highlight (rim from neon haze)
        dr.rectangle([px0, top, px0 + 3, H], fill=(c + 25, c + 40, c + 55, 255))
        # window grid
        fw, fh = rng.uniform(1.2, 2.0), rng.uniform(2.8, 3.4)
        yy = top + 0.8 * res
        while yy < H - 1.0 * res:
            xx = px0 + 0.6 * res
            while xx < px1 - 0.9 * res:
                if rng.random() < 0.42:
                    warm = rng.random() < 0.65
                    k = rng.uniform(0.45, 0.95)
                    cc = (255, 190, 110) if warm else (140, 210, 255)
                    dr.rectangle([xx, yy, xx + fw * res * 0.55, yy + fh * res * 0.45],
                                 fill=(int(cc[0] * k), int(cc[1] * k), int(cc[2] * k), 255))
                xx += fw * res
            yy += fh * res
        # neon signs
        if rng.random() < 0.75:
            side = 'L' if x < 0 else 'R'
            name = rng.choice(['teal', 'cyan', 'violet']) if side == 'L' else rng.choice(['orange', 'pink', 'amber'])
            nc = NEON[name]
            sx = px0 + rng.uniform(0.15, 0.6) * (px1 - px0)
            sy = H - rng.uniform(8, max(9, min(h - 6, 30))) * res
            vw, vh = 1.4 * res, rng.uniform(5, 9) * res
            dr.rectangle([sx, sy, sx + vw, sy + vh], fill=(10, 10, 16, 255))
            ng = int(vh / vw)
            for gi in range(ng):
                _glyph(dr, sx + 0.1 * vw, sy + gi * vw + 0.1 * vw, vw * 0.8, vw * 0.8, nc + (255,),
                       max(2, int(0.12 * res)), rng)
            k = gres / res
            dg.rectangle([sx * k - 6, sy * k - 6, (sx + vw) * k + 6, (sy + vh) * k + 6], fill=tuple(int(v * 0.55) for v in nc))
        x += w + (rng.uniform(4, 12) if rng.random() < 0.5 else rng.uniform(0.3, 1.5))
    img = _fog_overlay(img, res, (40, 34, 50), 0, 40, 0.38, 0.03)
    glow = glow.filter(ImageFilter.GaussianBlur(10))
    return Layer(img, res, x0, yt, 40.0, glow=glow, glow_res=gres)


def build_street(rng):
    """Facade across the street (d=12 m): shops, awnings, fire escapes, big neon."""
    res = 150.0
    x0, x1, yt = -20.0, 16.0, 14.0
    W, H = int((x1 - x0) * res), int(yt * res)
    gres = 30.0
    k = gres / res
    img = Image.new('RGBA', (W, H), (0, 0, 0, 0))
    glow = Image.new('RGB', (int(W * k), int(H * k)), (0, 0, 0))
    dr, dg = ImageDraw.Draw(img), ImageDraw.Draw(glow)

    def X(m):
        return (m - x0) * res

    def Y(m):
        return H - m * res

    x = x0
    bi = 0
    while x < x1:
        w = rng.uniform(5.0, 8.5)
        h = rng.uniform(4.6, 9.0)
        c = int(rng.integers(22, 34))
        base = np.array([c, c - 2, c + 6])
        dr.rectangle([X(x), Y(h), X(x + w), Y(0)], fill=tuple(base) + (255,))
        # brick/concrete texture lines
        for yy in np.arange(0.0, h, 0.33):
            dr.line([(X(x), Y(yy)), (X(x + w), Y(yy))], fill=tuple(base - 5) + (255,), width=1)
        # cornice
        dr.rectangle([X(x) - 4, Y(h), X(x + w) + 4, Y(h - 0.35)], fill=tuple(base + 12) + (255,))
        # upper windows
        for fy in np.arange(4.0, h - 1.2, 2.9):
            for fx in np.arange(x + 0.6, x + w - 1.0, 1.7):
                lit = rng.random() < 0.35
                if lit:
                    warm = rng.random() < 0.7
                    cc = np.array((255, 185, 105) if warm else (130, 200, 255)) * rng.uniform(0.45, 0.85)
                else:
                    cc = np.array([12, 14, 22])
                dr.rectangle([X(fx), Y(fy + 1.6), X(fx + 1.0), Y(fy)], fill=tuple(cc.astype(int)) + (255,))
                dr.rectangle([X(fx) - 3, Y(fy) - 2, X(fx + 1.0) + 3, Y(fy) + 6], fill=tuple(base + 15) + (255,))
                if lit:
                    dg.rectangle([X(fx) * k, Y(fy + 1.6) * k, X(fx + 1.0) * k, Y(fy) * k], fill=tuple((cc * 0.35).astype(int)))
        # fire escape
        if rng.random() < 0.6:
            fx0 = x + rng.uniform(0.5, w - 3.5)
            for fy in np.arange(4.0, h - 2, 3.1):
                dr.rectangle([X(fx0), Y(fy + 0.06), X(fx0 + 2.8), Y(fy)], fill=(14, 14, 18, 255))
                for rx in np.arange(fx0, fx0 + 2.8, 0.18):
                    dr.line([(X(rx), Y(fy + 0.9)), (X(rx), Y(fy))], fill=(16, 16, 20, 255), width=3)
                dr.line([(X(fx0), Y(fy + 0.9)), (X(fx0 + 2.8), Y(fy + 0.9))], fill=(16, 16, 20, 255), width=5)
                dr.line([(X(fx0 + 0.3), Y(fy)), (X(fx0 + 2.4), Y(fy + 3.1))], fill=(16, 16, 20, 255), width=5)
        # AC units
        for _ in range(rng.integers(1, 4)):
            ux, uy = x + rng.uniform(0.3, w - 1), rng.uniform(4.0, max(4.1, h - 1.2))
            dr.rectangle([X(ux), Y(uy + 0.55), X(ux + 0.8), Y(uy)], fill=(48, 50, 56, 255))
            dr.line([(X(ux), Y(uy)), (X(ux + 0.8), Y(uy))], fill=(20, 20, 24, 255), width=3)
        # storefront
        side_l = x < -1.0
        sc = rng.choice(['teal', 'cyan']) if side_l else rng.choice(['orange', 'pink', 'amber'])
        nc = np.array(NEON[sc])
        win = (nc * 0.25 + np.array([40, 35, 30])).clip(0, 255).astype(int)
        dr.rectangle([X(x + 0.4), Y(3.1), X(x + w - 0.4), Y(0.0)], fill=tuple(win) + (255,))
        for mx in np.arange(x + 0.4, x + w - 0.4, 1.3):
            dr.line([(X(mx), Y(3.1)), (X(mx), Y(0))], fill=(15, 15, 18, 255), width=6)
        # silhouettes of shelves inside
        for sy in (0.9, 1.7, 2.4):
            dr.line([(X(x + 0.5), Y(sy)), (X(x + w - 0.5), Y(sy))], fill=tuple((win * 0.6).astype(int)) + (255,), width=5)
        dg.rectangle([X(x + 0.4) * k, Y(3.1) * k, X(x + w - 0.4) * k, Y(0) * k], fill=tuple((nc * 0.22).astype(int)))
        # awning
        aw = (nc * 0.35).astype(int)
        dr.polygon([(X(x + 0.2), Y(3.6)), (X(x + w - 0.2), Y(3.6)), (X(x + w), Y(3.05)), (X(x), Y(3.05))],
                   fill=tuple(aw) + (255,))
        # big neon sign
        if rng.random() < 0.85:
            if rng.random() < 0.5:  # horizontal
                sx, sy, sw, sh = x + rng.uniform(0.5, 1.5), rng.uniform(3.8, max(3.9, h - 1.6)), rng.uniform(2.5, max(2.6, w - 1.5)), 1.1
            else:
                sx, sy, sw, sh = x + rng.uniform(0.3, w - 1.8), 3.9, 1.25, rng.uniform(3, max(3.1, h - 4.2))
            dr.rectangle([X(sx), Y(sy + sh), X(sx + sw), Y(sy)], fill=(10, 10, 14, 255))
            dr.rectangle([X(sx) + 4, Y(sy + sh) + 4, X(sx + sw) - 4, Y(sy) - 4], outline=tuple(nc) + (255,), width=5)
            cells = int(max(sw, sh) / min(sw, sh))
            cs = min(sw, sh)
            for ci in range(cells):
                gx = sx + (ci * cs if sw > sh else 0) + 0.12 * cs
                gy = sy + sh - (ci * cs if sh > sw else 0) - 0.88 * cs
                _glyph(dr, X(gx), Y(gy + 0.76 * cs), 0.76 * cs * res, 0.76 * cs * res, tuple(nc) + (255,), 9, rng)
            dg.rectangle([X(sx) * k - 8, Y(sy + sh) * k - 8, X(sx + sw) * k + 8, Y(sy) * k + 8], fill=tuple((nc * 0.75).astype(int)))
        bi += 1
        x += w + (rng.uniform(1.5, 4.0) if rng.random() < 0.6 else 0.0)
    # street lamps
    for lx in (-11.0, -1.8, 7.5):
        dr.rectangle([X(lx) - 6, Y(6.2), X(lx) + 6, Y(0)], fill=(18, 18, 22, 255))
        dr.line([(X(lx), Y(6.2)), (X(lx + 1.1), Y(6.4))], fill=(18, 18, 22, 255), width=10)
        dr.ellipse([X(lx + 0.9), Y(6.45), X(lx + 1.5), Y(6.2)], fill=(255, 225, 170, 255))
        cx, cy = X(lx + 1.2) * k, Y(6.3) * k
        dg.ellipse([cx - 20, cy - 20, cx + 20, cy + 20], fill=(255, 210, 150))
        # volumetric cone
        dg.polygon([(cx - 6, cy), (cx + 6, cy), (cx + 2.6 * res * k, Y(0) * k), (cx - 2.6 * res * k, Y(0) * k)],
                   fill=(70, 58, 40))
    img = _fog_overlay(img, res, (42, 36, 48), 0, 14, 0.30, 0.0)
    glow = glow.filter(ImageFilter.GaussianBlur(9))
    return Layer(img, res, x0, yt, 12.0, glow=glow, glow_res=gres)


def build_wall(rng, cracked=False, crack_at=(-3.75, 1.15)):
    """Alley brick wall behind the crate stack (d=1.2 m)."""
    res = 220.0
    x0, x1, yt = -8.5, -2.2, 3.7
    W, H = int((x1 - x0) * res), int(yt * res)
    r2 = np.random.default_rng(77)
    arr = np.zeros((H, W, 4), np.float32)
    bw, bh = 0.24 * res, 0.075 * res
    yy, xx = np.mgrid[0:H, 0:W].astype(np.float32)
    row = (yy // bh).astype(int)
    off = (row % 2) * bw * 0.5
    col = ((xx + off) // bw).astype(int)
    bid = (row * 131 + col * 17) % 997
    tint = r2.random(1000).astype(np.float32)
    fx = ((xx + off) % bw) / bw
    fy = (yy % bh) / bh
    mortar = (fx < 0.05) | (fy < 0.1)
    base = np.array([62, 34, 30], np.float32)
    c = base[None, None, :] * (0.65 + 0.6 * tint[bid])[..., None]
    c = np.where(mortar[..., None], np.array([38, 36, 38], np.float32), c)
    n = value_noise(W, H, 40, r2, 3)
    c = c * (0.7 + 0.5 * n[..., None])
    # wet sheen gradient + streaks
    streak = value_noise(W, 8, 6, r2, 2)
    streak = np.repeat(streak[:1], H, 0)
    c = c * (0.85 + 0.35 * streak[..., None])
    top = np.clip(1 - yy / H, 0, 1)
    c = c * (0.6 + 0.5 * (1 - top))[..., None]
    arr[..., :3] = c
    arr[..., 3] = 255
    # wall edges / top coping
    arr[: int(0.1 * res), :, :3] = [30, 30, 34]
    if cracked:
        cx, cy = (crack_at[0] - x0) * res, H - crack_at[1] * res
        img = Image.fromarray(arr.clip(0, 255).astype(np.uint8), 'RGBA')
        dr = ImageDraw.Draw(img)
        dr.ellipse([cx - 0.35 * res, cy - 0.28 * res, cx + 0.35 * res, cy + 0.28 * res], fill=(16, 12, 12, 255))
        for i in range(14):
            a = i / 14 * 2 * math.pi + r2.uniform(-0.2, 0.2)
            px, py = cx, cy
            ln = r2.uniform(0.5, 1.3) * res
            pts = [(px, py)]
            for s in range(6):
                a += r2.uniform(-0.5, 0.5)
                px += math.cos(a) * ln / 6
                py += math.sin(a) * ln / 6
                pts.append((px, py))
            dr.line(pts, fill=(10, 8, 8, 255), width=int(r2.integers(3, 7)))
        return img, res, x0, yt
    return Image.fromarray(arr.clip(0, 255).astype(np.uint8), 'RGBA'), res, x0, yt


class GroundTex:
    def __init__(self, rng):
        self.res = 24.0
        self.u0, self.u1, self.d0, self.d1 = -30.0, 30.0, -8.0, 40.0
        W, H = int((self.u1 - self.u0) * self.res), int((self.d1 - self.d0) * self.res)
        n = value_noise(W, H, 90, rng, 4)
        self.puddle = np.clip((n - 0.47) * 6.0, 0, 1).astype(np.float32)
        self.rough = value_noise(W, H, 6, rng, 3).astype(np.float32)
        self.W, self.H = W, H

    def sample(self, u, d):
        iu = np.clip(((u - self.u0) * self.res).astype(np.int32), 0, self.W - 1)
        idd = np.clip(((d - self.d0) * self.res).astype(np.int32), 0, self.H - 1)
        return self.puddle[idd, iu], self.rough[idd, iu]


class Scene:
    def __init__(self, seed):
        rng = np.random.default_rng(seed)
        self.sky = build_sky(rng)
        self.far = build_far(rng)
        self.mid = build_mid(rng)
        self.street = build_street(rng)
        w0 = build_wall(rng)
        w1 = build_wall(rng, cracked=True)
        self.wall = Layer(w0[0], w0[1], w0[2], w0[3], 1.2)
        self.wall_cracked = Layer(w1[0], w1[1], w1[2], w1[3], 1.2)
        self.ground = GroundTex(rng)
        fr = np.random.default_rng(seed + 5)
        self.mist = value_noise(1024, 256, 120, fr, 4)
