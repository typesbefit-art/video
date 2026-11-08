"""Effects: closed-form particles (sparks, water, splinters, dust, planks),
breakable crates, rain + ground splashes, shockwaves, speed lines, impact
light, camera shake / zoom punch, and post-processing (teal & orange grade,
bloom, vignette, film grain, chromatic aberration, fades).

Everything is a pure function of time + fixed seeds, so any worker can render
any frame or sub-frame deterministically.
"""
import math
import numpy as np
from PIL import Image, ImageDraw, ImageFilter, ImageChops
from .timeline import TL, HS_FPS, SLOWMO, FADE_IN, FADE_OUT
from .characters import project_pt
from .config import SAFE_TOP, SAFE_BOTTOM, SAFE_RIGHT, BASE_W, BASE_H, MAX_ROLL_DEG

G = np.array([0.0, -9.8, 0.0])
CRASH_T = 8.70
LIGHTNING = [(1.12, 1.0), (18.50, 0.8)]


def _smooth(x):
    x = min(max(x, 0.0), 1.0)
    return x * x * (3 - 2 * x)


# ------------------------------------------------------------------ crates
CRATES = [  # x centre, y bottom, depth centre, w, h, dep, breaks
    (-4.28, 0.0, -0.30, 0.70, 0.70, 0.70, False),
    (-3.52, 0.0, -0.25, 0.70, 0.66, 0.66, True),
    (-3.92, 0.70, -0.30, 0.62, 0.60, 0.60, True),
    (-3.10, 0.66, -0.28, 0.46, 0.44, 0.44, True),
]
WOOD = np.array([0.50, 0.35, 0.21])


def _box_faces(x, y0, dc, w, h, dp):
    xs, xe = x - w / 2, x + w / 2
    ys, ye = y0, y0 + h
    zb, zf = dc - dp / 2, dc + dp / 2
    v = lambda a, b, c: np.array([a, b, c])
    return [
        ('front', [v(xs, ys, zf), v(xe, ys, zf), v(xe, ye, zf), v(xs, ye, zf)], 0.62),
        ('top', [v(xs, ye, zf), v(xe, ye, zf), v(xe, ye, zb), v(xs, ye, zb)], 0.90),
        ('left', [v(xs, ys, zb), v(xs, ys, zf), v(xs, ye, zf), v(xs, ye, zb)], 0.42),
        ('right', [v(xe, ys, zf), v(xe, ys, zb), v(xe, ye, zb), v(xe, ye, zf)], 0.48),
    ]


class Particles:
    """Closed-form ballistic particle systems spawned by events."""

    def __init__(self, choreo, seed):
        self.systems = []
        for e in choreo.events:
            k = e['kind']
            pos = np.array(e['pos'], float)
            att = choreo.tracks[e['att']]
            fdir = 1.0 if e['att'] == 'A' else -1.0
            rng = np.random.default_rng(seed * 101 + e['id'] * 7)
            if k in ('hit', 'heavy', 'final', 'block', 'hook'):
                n = {'block': 26, 'hit': 45, 'heavy': 80, 'final': 140, 'hook': 70}[k]
                self._water(rng, e, pos, fdir, n, 2.0 + 3.0 * e['power'])
            if k in ('heavy', 'final', 'hook', 'block', 'crash'):
                n = {'block': 14, 'heavy': 45, 'final': 70, 'hook': 50, 'crash': 40}[k]
                self._sparks(rng, e, pos, fdir, n)
            if k in ('jump', 'land', 'fall', 'crash'):
                gp = pos.copy()
                gp[1] = 0.02
                n = {'jump': 50, 'land': 60, 'fall': 130, 'crash': 60}[k]
                self._ground_splash(rng, e, gp, n, 1.0 if k != 'fall' else 1.6)
            if k == 'crash':
                self._crash(rng, e, pos)
            if k == 'fall':
                self._dust(rng, e, np.array([pos[0], 0.15, 0.0]), 8, 0.6, (0.40, 0.42, 0.46))

    def _water(self, rng, e, pos, fdir, n, spd):
        d = np.stack([fdir * rng.uniform(0.3, 1.0, n), rng.uniform(-0.4, 0.9, n), rng.uniform(-0.7, 0.7, n)], 1)
        d /= np.linalg.norm(d, axis=1, keepdims=True)
        v = d * rng.uniform(0.4, 1.0, (n, 1)) * spd
        self.systems.append(dict(kind='water', tau=e['tau'], p0=pos + rng.normal(0, 0.03, (n, 3)), v=v,
                                 life=rng.uniform(0.35, 0.8, n), size=rng.uniform(0.004, 0.012, n), drag=1.5))

    def _sparks(self, rng, e, pos, fdir, n):
        d = np.stack([fdir * rng.uniform(-0.2, 1.0, n), rng.uniform(-0.6, 1.0, n), rng.uniform(-0.8, 0.8, n)], 1)
        d /= np.linalg.norm(d, axis=1, keepdims=True)
        v = d * rng.uniform(2.5, 9.0, (n, 1))
        self.systems.append(dict(kind='spark', tau=e['tau'], p0=np.repeat(pos[None], n, 0), v=v,
                                 life=rng.uniform(0.15, 0.55, n), size=rng.uniform(0.004, 0.009, n), drag=2.5))

    def _ground_splash(self, rng, e, gp, n, k):
        ang = rng.uniform(0, 2 * np.pi, n)
        v = np.stack([np.cos(ang) * rng.uniform(0.3, 1.8, n) * k, rng.uniform(1.2, 3.8, n) * k,
                      np.sin(ang) * rng.uniform(0.3, 1.2, n)], 1)
        p0 = gp + np.stack([rng.normal(0, 0.18, n), np.zeros(n), rng.normal(0, 0.1, n)], 1)
        self.systems.append(dict(kind='water', tau=e['tau'], p0=p0, v=v, life=rng.uniform(0.4, 0.9, n),
                                 size=rng.uniform(0.005, 0.014, n), drag=0.8))
        self.systems.append(dict(kind='ring', tau=e['tau'], p0=gp, life=0.9 * k, rmax=0.9 * k))

    def _dust(self, rng, e, pos, n, scale, col):
        v = np.stack([rng.normal(0, 1.2, n), rng.uniform(0.1, 0.9, n), rng.normal(0, 0.3, n)], 1) * scale
        self.systems.append(dict(kind='dust', tau=e['tau'], p0=pos + rng.normal(0, 0.15, (n, 3)) * scale, v=v,
                                 life=rng.uniform(1.6, 3.0, n), size=rng.uniform(0.25, 0.5, n) * scale, col=col))

    def _crash(self, rng, e, pos):
        planks = []
        for (x, y0, dc, w, h, dp, brk) in CRATES:
            if not brk:
                continue
            for i in range(7):
                p0 = np.array([x + rng.uniform(-w / 2, w / 2), y0 + rng.uniform(0, h), dc])
                dirx = (p0[0] - pos[0]) * 2.0 + rng.normal(0, 0.8)
                v = np.array([dirx - 1.2, rng.uniform(0.5, 4.0), rng.normal(0, 0.8)])
                planks.append((p0, v, rng.uniform(-14, 14), rng.uniform(0, np.pi),
                               rng.uniform(0.35, 0.62), rng.uniform(0.07, 0.11), rng.uniform(0.75, 1.15)))
        self.systems.append(dict(kind='plank', tau=e['tau'], items=planks))
        n = 160
        d = rng.normal(0, 1, (n, 3))
        d[:, 1] = np.abs(d[:, 1]) * 0.8 + 0.3
        v = d * rng.uniform(1.5, 6.5, (n, 1))
        self.systems.append(dict(kind='splinter', tau=e['tau'], p0=pos + rng.normal(0, 0.12, (n, 3)), v=v,
                                 life=rng.uniform(0.8, 2.2, n), size=rng.uniform(0.02, 0.07, n),
                                 rot=rng.uniform(-30, 30, n), ang=rng.uniform(0, 6.28, n)))
        # brick chunks from the wall
        n2 = 30
        v2 = np.stack([rng.normal(-0.5, 1.2, n2), rng.uniform(0.0, 2.5, n2), rng.uniform(0.5, 2.0, n2)], 1)
        self.systems.append(dict(kind='brick', tau=e['tau'], p0=np.array([-3.75, 1.15, -0.8]) + rng.normal(0, 0.15, (n2, 3)),
                                 v=v2, life=np.full(n2, 6.0), size=rng.uniform(0.03, 0.08, n2),
                                 rot=rng.uniform(-12, 12, n2), ang=rng.uniform(0, 6.28, n2)))
        self._dust(rng, e, pos + np.array([0, -0.4, 0]), 16, 1.0, (0.50, 0.46, 0.42))

    # -- evaluation --------------------------------------------------------
    @staticmethod
    def ballistic(p0, v, a, drag):
        if drag > 0:
            k = (1 - np.exp(-drag * a)) / drag
        else:
            k = a
        return p0 + v * k[..., None] + 0.5 * G * (a * a)[..., None]


def plank_state(it, a):
    p0, v, w, ang0, ln, wd, br = it
    # time to hit ground (y=0.03)
    A, Bq, C = -4.9, v[1], p0[1] - 0.03
    disc = Bq * Bq - 4 * A * C
    th = (-Bq - math.sqrt(max(disc, 0))) / (2 * A)
    if a < th:
        p = p0 + v * a + 0.5 * G * a * a
        return p, ang0 + w * a, ln, wd, br
    ph = p0 + v * th
    ph[1] = 0.03
    b = a - th
    slide = (1 - math.exp(-6 * b)) / 6
    p = ph + np.array([v[0], 0, v[2]]) * 0.35 * slide
    angh = ang0 + w * th
    target = round(angh / math.pi) * math.pi
    ang = target + (angh - target) * math.exp(-10 * b)
    return p, ang, ln, wd * 0.6, br


class FX:
    def __init__(self, settings, choreo):
        self.S = settings
        self.ch = choreo
        self.parts = Particles(choreo, settings.seed)
        self.events = choreo.events
        rng = np.random.default_rng(settings.seed + 99)
        n = int(2600 * settings.rain_density)
        self.rain = dict(x=rng.random(n), y=rng.random(n), layer=rng.choice(3, n, p=[0.6, 0.32, 0.08]),
                         sp=rng.uniform(0.8, 1.2, n), a=rng.uniform(0.35, 1.0, n))
        m = 700
        self.spl = dict(u=rng.uniform(-14, 14, m), d=rng.uniform(-3, 18, m), per=rng.uniform(0.45, 1.1, m),
                        ph=rng.random(m), sz=rng.uniform(0.6, 1.4, m))
        g = np.linspace(-1, 1, 256)
        gx, gy = np.meshgrid(g, g)
        self.sprite = np.exp(-(gx ** 2 + gy ** 2) * 4.5).astype(np.float32)

    # ---------------------------------------------------------- camera fx
    def shake(self, t):
        dx = dy = droll = 0.0
        zmul = 1.0
        amp_tab = {'hook': 34, 'hit': 10, 'heavy': 32, 'block': 6, 'crash': 40, 'final': 30, 'fall': 30, 'land': 8}
        for e in self.events:
            A = amp_tab.get(e['kind'])
            if A is None or t < e['t']:
                continue
            if e['kind'] == 'final':
                a = float(TL.tau(t)) - e['tau']
            else:
                a = t - e['t']
            env = math.exp(-a / (0.22 if e['kind'] in ('crash', 'heavy', 'fall', 'hook') else 0.12))
            if env < 0.01:
                continue
            ph = e['id'] * 1.7
            w = 2 * math.pi * 17
            dx += A * env * (math.sin(a * w + ph) * 0.7 + math.sin(a * w * 1.9 + ph * 2) * 0.3)
            dy += A * env * (math.cos(a * w * 1.3 + ph) * 0.7 + math.sin(a * w * 2.3 + ph * 3) * 0.3)
            droll += A * 0.03 * env * math.sin(a * w * 0.7 + ph)
            pulse = (a / 0.03) if a < 0.03 else math.exp(-(a - 0.03) / 0.14)
            zmul += 0.07 * e['power'] * pulse * (A / 30.0)
        return dx, dy, math.radians(droll), zmul

    def flash_lights(self, t, tau, cam):
        """Impact light sources for the character shader + screen glow."""
        out = []
        for e in self.events:
            if e['kind'] not in ('hook', 'hit', 'heavy', 'block', 'crash', 'final', 'fall'):
                continue
            a = tau - e['tau']
            if a < 0 or t < e['t'] - 1e-6:
                continue
            dec = 0.25 if e['kind'] == 'final' else 0.07
            I = e['power'] * math.exp(-a / dec)
            if I < 0.03:
                continue
            col = (1.0, 0.86, 0.68) if e['kind'] != 'block' else (0.65, 0.85, 1.0)
            if e['kind'] in ('crash', 'fall'):
                col = (0.9, 0.85, 0.8)
            sx, sy, f = project_pt(e['pos'], cam)
            out.append((sx, sy, I, col, e))
        for (tl, p) in LIGHTNING:
            a = t - tl
            if 0 <= a < 0.6:
                I = p * (math.exp(-a / 0.05) + 0.6 * math.exp(-max(a - 0.18, 0) / 0.06) * (a > 0.18))
                out.append((cam['ax'], -2000.0, I * 0.8, (0.6, 0.7, 1.0), None))
        return out

    def lightning(self, t):
        I = 0.0
        for (tl, p) in LIGHTNING:
            a = t - tl
            if 0 <= a < 0.6:
                I += p * (math.exp(-a / 0.05) + 0.6 * math.exp(-max(a - 0.18, 0) / 0.06) * (a > 0.18))
        return I

    def ca_amount(self, t):
        amt = 0.0
        for e in self.events:
            if e['kind'] in ('hook', 'heavy', 'crash', 'final', 'fall', 'hit'):
                a = t - e['t']
                if a >= 0:
                    k = 0.4 if e['kind'] == 'hit' else 1.0
                    dec = 0.6 if e['kind'] == 'final' else 0.18
                    amt += k * e['power'] * math.exp(-a / dec)
        return min(amt, 1.6)

    def impact_frame(self, t):
        for e in self.events:
            if e['kind'] in ('hook', 'heavy', 'final', 'crash'):
                if 0 <= t - e['t'] < 0.025:
                    return 0.42 if e['kind'] != 'crash' else 0.25
        return 0.0

    # ------------------------------------------------------------ drawing
    def draw_crates(self, t, cam, size):
        """Return (x0, y0, premult rgb, alpha) of crates/debris layer at 2x AA, or None."""
        polys = []
        broken = t >= CRASH_T
        for (x, y0, dc, w, h, dp, brk) in CRATES:
            if broken and brk:
                continue
            if broken:  # surviving crate is knocked askew
                x -= 0.12
            for name, vs, sh in _box_faces(x, y0, dc, w, h, dp):
                pts = [project_pt(v, cam)[:2] for v in vs]
                area = 0.0
                for i in range(4):
                    x1, y1 = pts[i]
                    x2, y2 = pts[(i + 1) % 4]
                    area += x1 * y2 - x2 * y1
                if area >= 0:  # screen y is down -> visible faces are CW (negative)
                    continue
                polys.append((pts, sh, name, vs))
        tau = float(TL.tau(t))
        for sysd in self.parts.systems:
            if sysd['kind'] != 'plank':
                continue
            a = tau - sysd['tau']
            if a < 0:
                continue
            for it in sysd['items']:
                p, ang, ln, wd, br = plank_state(it, a)
                c, s = math.cos(ang), math.sin(ang)
                hx, hy = c * ln / 2, s * ln / 2
                px, py = -s * wd / 2, c * wd / 2
                vs = [p + np.array([hx + px, hy + py, 0]), p + np.array([hx - px, hy - py, 0]),
                      p + np.array([-hx - px, -hy - py, 0]), p + np.array([-hx + px, -hy + py, 0])]
                pts = [project_pt(v, cam)[:2] for v in vs]
                polys.append((pts, 0.5 + 0.35 * abs(math.sin(ang * 1.3 + br)) * br, 'plank', vs))
        if not polys:
            return None
        allp = np.array([p for pl in polys for p in pl[0]])
        cw, ch = size
        x0, y0 = max(int(allp[:, 0].min()) - 2, 0), max(int(allp[:, 1].min()) - 2, 0)
        x1, y1 = min(int(allp[:, 0].max()) + 3, cw), min(int(allp[:, 1].max()) + 3, ch)
        if x1 - x0 < 2 or y1 - y0 < 2:
            return None
        SS = 2
        img = Image.new('RGBA', ((x1 - x0) * SS, (y1 - y0) * SS), (0, 0, 0, 0))
        dr = ImageDraw.Draw(img)
        for pts, sh, name, vs in polys:
            P = [((px - x0) * SS, (py - y0) * SS) for px, py in pts]
            col = WOOD * sh
            if name == 'plank':
                col = WOOD * sh * 1.1
            dr.polygon(P, fill=tuple(int(c * 255) for c in col) + (255,))
            if name in ('front', 'left', 'right'):
                # plank seams + frame + diagonal brace
                for k in (0.25, 0.5, 0.75):
                    a1 = (P[0][0] + (P[3][0] - P[0][0]) * k, P[0][1] + (P[3][1] - P[0][1]) * k)
                    a2 = (P[1][0] + (P[2][0] - P[1][0]) * k, P[1][1] + (P[2][1] - P[1][1]) * k)
                    dr.line([a1, a2], fill=tuple(int(c * 160) for c in col) + (255,), width=max(1, SS))
                dk = tuple(int(c * 140) for c in col) + (255,)
                fw = max(2, int(0.035 * cam['zs'] * SS))
                dr.line(P + [P[0]], fill=dk, width=fw)
                dr.line([P[0], P[2]], fill=tuple(int(c * 200) for c in col) + (255,), width=fw)
                # rim lights
                dr.line([P[3], P[2]], fill=(int(255 * 0.75), int(255 * 0.5), int(255 * 0.3), 255), width=max(1, SS))
            elif name == 'top':
                dr.line([P[0], P[1]], fill=(230, 170, 110, 255), width=max(1, SS))
        img = img.resize((x1 - x0, y1 - y0), Image.BOX)
        arr = np.asarray(img, np.float32) / 255.0
        a = arr[..., 3]
        return x0, y0, arr[..., :3] * a[..., None], a

    def draw_particles(self, img, t, tau, cam, front=True):
        """Draw sparks/water/splinters/bricks/rings/dust onto PIL RGBA canvas."""
        cw, ch = img.size
        add = Image.new('RGB', img.size, (0, 0, 0))
        da = ImageDraw.Draw(add)
        dr = ImageDraw.Draw(img, 'RGBA')
        zs = cam['zs']
        dust_layer = None
        any_add = False
        for sysd in self.parts.systems:
            a = tau - sysd['tau']
            if a < 0:
                continue
            k = sysd['kind']
            if k in ('water', 'spark'):
                life = sysd['life']
                alive = a < life
                if not alive.any():
                    continue
                aa = np.full(len(life), a)
                p = Particles.ballistic(sysd['p0'], sysd['v'], aa, sysd['drag'])
                ps = Particles.ballistic(sysd['p0'], sysd['v'], np.maximum(aa - 0.016, 0), sysd['drag'])
                for i in np.nonzero(alive)[0]:
                    if p[i, 1] < 0.0:
                        continue
                    x1, y1, f = project_pt(p[i], cam)
                    x2, y2, _ = project_pt(ps[i], cam)
                    fade = 1 - a / life[i]
                    w = max(1, min(int(sysd['size'][i] * zs * min(f, 1.8)), int(5 * self.S.s) + 1))
                    if k == 'spark':
                        c = (int(255 * fade), int(200 * fade ** 1.5), int(90 * fade ** 3))
                        da.line([(x1, y1), (x2, y2)], fill=c, width=w)
                        any_add = True
                    else:
                        c = (200, 225, 255, int(200 * fade))
                        dr.line([(x1, y1), (x2, y2)], fill=c, width=w)
            elif k == 'ring':
                if a > sysd['life']:
                    continue
                r = sysd['rmax'] * (1 - math.exp(-a * 5))
                fade = 1 - a / sysd['life']
                c, _, f = project_pt(sysd['p0'], cam)
                x, y, _ = project_pt(sysd['p0'], cam)
                rx, ry = r * zs, r * zs * 0.18
                dr.ellipse([x - rx, y - ry, x + rx, y + ry], outline=(190, 220, 255, int(150 * fade)),
                           width=max(1, int(3 * self.S.s)))
            elif k in ('splinter', 'brick'):
                life = sysd['life']
                for i in range(len(life)):
                    if a > life[i]:
                        continue
                    aa = np.array([a])
                    p = Particles.ballistic(sysd['p0'][i], sysd['v'][i], aa, 0.0)[0]
                    if p[1] < 0.02:  # rest on the ground
                        vy, py0 = sysd['v'][i][1], sysd['p0'][i][1]
                        th = (vy + math.sqrt(vy * vy + 2 * 9.8 * max(py0 - 0.02, 0))) / 9.8
                        p = sysd['p0'][i] + sysd['v'][i] * th + 0.5 * G * th * th
                        p[1] = 0.02
                        ang = sysd['ang'][i] + sysd['rot'][i] * th
                    else:
                        ang = sysd['ang'][i] + sysd['rot'][i] * a
                    x, y, f = project_pt(p, cam)
                    L = sysd['size'][i] * zs * f
                    c, s = math.cos(ang), math.sin(ang)
                    if k == 'splinter':
                        pts = [(x + c * L, y + s * L), (x + -s * L * 0.18, y + c * L * 0.18),
                               (x - c * L, y - s * L), (x + s * L * 0.18, y - c * L * 0.18)]
                        col = (150, 105, 62, 255)
                    else:
                        pts = [(x + c * L - s * L * 0.6, y + s * L + c * L * 0.6),
                               (x - c * L - s * L * 0.6, y - s * L + c * L * 0.6),
                               (x - c * L + s * L * 0.6, y - s * L - c * L * 0.6),
                               (x + c * L + s * L * 0.6, y + s * L - c * L * 0.6)]
                        col = (90, 48, 40, 255)
                    dr.polygon(pts, fill=col)
            elif k == 'dust':
                if dust_layer is None:
                    ds = 4
                    dust_layer = Image.new('L', (cw // ds, ch // ds), 0)
                    dd = ImageDraw.Draw(dust_layer)
                    dcol = np.array(sysd['col'])
                life = sysd['life']
                for i in range(len(life)):
                    if a > life[i]:
                        continue
                    kk = (1 - math.exp(-a * 1.8)) / 1.8
                    p = sysd['p0'][i] + sysd['v'][i] * kk + np.array([0, 0.12 * a, 0])
                    r = sysd['size'][i] * (1 + 1.6 * a)
                    x, y, f = project_pt(p, cam)
                    rr = r * zs * f / ds
                    al = int(110 * (1 - a / life[i]) ** 1.5 * min(1, a * 8))
                    dd.ellipse([x / ds - rr, y / ds - rr, x / ds + rr, y / ds + rr], fill=al)
        if dust_layer is not None:
            dust_layer = dust_layer.filter(ImageFilter.GaussianBlur(6 * self.S.s + 1)).resize(img.size, Image.BILINEAR)
            colimg = Image.new('RGBA', img.size, tuple(int(c * 255) for c in dcol) + (0,))
            colimg.putalpha(dust_layer)
            img.alpha_composite(colimg)
        if any_add:
            glow = add.resize((cw // 4, ch // 4), Image.BILINEAR).filter(ImageFilter.GaussianBlur(3))
            glow = glow.resize(img.size, Image.BILINEAR)
            rgb = ImageChops.add(ImageChops.add(img.convert('RGB'), add), glow)
            img.paste(rgb)
        return img

    def draw_rain(self, img, t, cam, roll):
        s = self.S.s
        cw, ch = img.size
        tr = float(TL.rain(t))
        spd_now = (float(TL.rain(t + 0.002)) - float(TL.rain(t - 0.002))) / 0.004
        R = self.rain
        lay_cfg = [  # speed px/s, len, width, alpha, parallax
            (1500, 26, 1, 70, 0.25), (2300, 55, 2, 95, 0.55), (3400, 140, 4, 120, 1.2)]
        over = Image.new('RGBA', img.size, (0, 0, 0, 0))
        dr = ImageDraw.Draw(over)
        slant = 0.13
        for li, (sp, ln, wd, al, par) in enumerate(lay_cfg):
            m = R['layer'] == li
            xs = R['x'][m]
            ys = R['y'][m]
            spv = R['sp'][m]
            av = R['a'][m]
            span_y = ch + 300 * s
            yy = (ys * span_y + tr * sp * spv * s) % span_y - 150 * s
            xx = (xs * (cw + 200 * s) - cam['cx'] * cam['zs'] * par * 0.6 + yy * slant) % (cw + 200 * s) - 100 * s
            L = (ln * s) * max(spd_now, 0.06) + 2 * s
            for x, y, a in zip(xx, yy, av):
                dr.line([(x, y), (x - L * slant, y - L)], fill=(185, 205, 230, int(al * a)), width=max(1, int(wd * s)))
        if True:
            near = over
            img.alpha_composite(near)
        return img

    def draw_splashes(self, img, t, cam, scene_ground_fn):
        """Rain splashes + ripple rings on the ground (perspective via ground fn)."""
        tr = float(TL.rain(t))
        sp = self.spl
        age = (tr + sp['ph'] * sp['per']) % sp['per']
        cyc = np.floor((tr + sp['ph'] * sp['per']) / sp['per'])
        act = age < 0.22
        if not act.any():
            return img
        dr = ImageDraw.Draw(img, 'RGBA')
        idx = np.nonzero(act)[0]
        u = sp['u'][idx] + ((cyc[idx] * 7.31) % 1.0 - 0.5) * 3.0
        d = sp['d'][idx] + ((cyc[idx] * 3.77) % 1.0 - 0.5) * 2.0
        xs, ys, g = scene_ground_fn(u, d)
        for x, y, gg, a, z in zip(xs, ys, g, age[idx], sp['sz'][idx]):
            if gg <= 0:
                continue
            k = a / 0.22
            r = (0.02 + 0.07 * k) * gg * z
            al = int(55 * (1 - k))
            dr.ellipse([x - r, y - r * 0.22, x + r, y + r * 0.22], outline=(170, 200, 235, al), width=1)
            if k < 0.4:
                h = 0.05 * gg * z * (1 - k / 0.4)
                dr.line([(x, y), (x, y - h)], fill=(200, 220, 245, int(140 * (1 - k / 0.4))), width=max(1, int(gg * 0.004)))
        return img

    def draw_glows(self, arr, lights, cam):
        """Additive impact glow on a float canvas array (H,W,3)."""
        ch, cw = arr.shape[:2]
        s = self.S.s
        for (sx, sy, I, col, e) in lights:
            if e is None:
                continue
            R = int(520 * s * min(1.4, 0.5 + 0.6 * e['power']))
            x0, y0 = int(sx - R), int(sy - R)
            spr = Image.fromarray((self.sprite * 255).astype(np.uint8)).resize((2 * R, 2 * R), Image.BILINEAR)
            sp = np.asarray(spr, np.float32) / 255.0
            xa, ya = max(x0, 0), max(y0, 0)
            xb, yb = min(x0 + 2 * R, cw), min(y0 + 2 * R, ch)
            if xb <= xa or yb <= ya:
                continue
            sub = sp[ya - y0:yb - y0, xa - x0:xb - x0]
            core = sub ** 6
            arr[ya:yb, xa:xb] += (sub * 0.45 + core * 0.7)[..., None] * np.array(col, np.float32) * (min(I, 1.0) * 255 * 0.6)

    def shockwaves(self, img, t, tau, cam):
        out = []
        s = self.S.s
        for e in self.events:
            if e['kind'] not in ('hook', 'heavy', 'final', 'crash', 'hit'):
                continue
            a = tau - e['tau']
            if a < 0:
                continue
            life = 0.6 if e['kind'] == 'final' else 0.32
            if a > life:
                continue
            sx, sy, f = project_pt(e['pos'], cam)
            rmax = {'final': 1.6, 'heavy': 0.9, 'hook': 0.7, 'crash': 1.1, 'hit': 0.45}[e['kind']]
            r = rmax * (1 - math.exp(-a * (5.0 if e['kind'] == 'final' else 9.0))) * cam['zs'] * f
            out.append((sx, sy, r, 1 - a / life, e))
        if not out:
            return img
        cw, ch = img.size
        ds = 2
        L = Image.new('L', (cw // ds, ch // ds), 0)
        dl = ImageDraw.Draw(L)
        for sx, sy, r, fade, e in out:
            w = max(1, int((10 if e['kind'] == 'final' else 6) * s * fade / ds) + 1)
            dl.ellipse([(sx - r) / ds, (sy - r * 0.92) / ds, (sx + r) / ds, (sy + r * 0.92) / ds],
                       outline=int(255 * fade ** 1.2), width=w)
        L = L.filter(ImageFilter.GaussianBlur(2)).resize(img.size, Image.BILINEAR)
        # refraction-ish displacement for the big ones
        for sx, sy, r, fade, e in out:
            if e['kind'] in ('final', 'heavy', 'hook') and r > 20:
                self._distort(img, sx, sy, r, fade * (1.0 if e['kind'] == 'final' else 0.6))
        white = Image.new('RGB', img.size, (215, 235, 255))
        rgb = img.convert('RGB')
        rgb = Image.composite(white, rgb, L.point(lambda v: int(v * 0.55)))
        img.paste(rgb)
        return img

    def _distort(self, img, sx, sy, r, amt):
        cw, ch = img.size
        band = max(20.0, r * 0.25)
        R = int(r + band)
        x0, y0, x1, y1 = max(int(sx - R), 0), max(int(sy - R), 0), min(int(sx + R), cw), min(int(sy + R), ch)
        if x1 - x0 < 4 or y1 - y0 < 4:
            return
        sub = np.asarray(img.crop((x0, y0, x1, y1)))
        X, Y = np.meshgrid(np.arange(x0, x1, dtype=np.float32), np.arange(y0, y1, dtype=np.float32))
        dx, dy = X - sx, Y - sy
        dist = np.sqrt(dx * dx + dy * dy) + 1e-3
        prof = np.exp(-((dist - r) / band) ** 2) * amt * band * 0.5
        srcx = np.clip(X - dx / dist * prof - x0, 0, x1 - x0 - 1).astype(np.int32)
        srcy = np.clip(Y - dy / dist * prof - y0, 0, y1 - y0 - 1).astype(np.int32)
        img.paste(Image.fromarray(sub[srcy, srcx]), (x0, y0))

    def speed_lines(self, img, t, cam, frame):
        s = self.S.s
        cw, ch = img.size
        mode = None
        if 0.18 <= t < 0.62:
            mode, I, fx_, fy_ = 'radial', 1.0, cam['ax'], cam['ay']
        elif 7.40 <= t < 7.80:
            mode, I = 'radial', 0.9
            fx_, fy_, _ = project_pt(self.events[10]['pos'], cam)
        elif 7.80 <= t < 8.65:
            mode, I = 'dir', 0.8
        elif 12.95 <= t < 13.55:
            mode, I = 'radial', 0.7
            fx_, fy_, _ = project_pt(self.events[16]['pos'], cam)
        elif 15.60 <= t < 16.9:
            mode, I = 'radial', 0.85 * (1 - _smooth((t - 16.4) / 0.5))
            fx_, fy_, _ = project_pt(self.events[19]['pos'], cam)
        if mode is None or I <= 0.02:
            return img
        rng = np.random.default_rng(self.S.seed * 31 + int(t * 40))
        L = Image.new('L', img.size, 0)
        dl = ImageDraw.Draw(L)
        diag = math.hypot(cw, ch)
        if mode == 'radial':
            for _ in range(70):
                ang = rng.uniform(0, 2 * math.pi)
                rin = rng.uniform(0.28, 0.5) * diag
                w = rng.uniform(0.004, 0.012)
                p1 = (fx_ + math.cos(ang - w) * diag, fy_ + math.sin(ang - w) * diag)
                p2 = (fx_ + math.cos(ang + w) * diag, fy_ + math.sin(ang + w) * diag)
                p3 = (fx_ + math.cos(ang) * rin, fy_ + math.sin(ang) * rin)
                dl.polygon([p1, p2, p3], fill=int(rng.uniform(90, 200) * I))
        else:
            for _ in range(40):
                x = rng.uniform(0, cw)
                y = rng.uniform(0, ch)
                ln = rng.uniform(0.15, 0.4) * ch
                w = rng.uniform(1.5, 5) * s
                dl.polygon([(x - w, y), (x + w, y), (x, y - ln)], fill=int(rng.uniform(60, 150) * I))
        white = Image.new('RGBA', img.size, (240, 245, 255, 0))
        white.putalpha(L)
        img.alpha_composite(white)
        return img

    def mist(self, img, t, cam, mist_tex, y_ground):
        """Low drifting fog band near the street."""
        cw, ch = img.size
        s = self.S.s
        h = int(420 * s)
        y0 = int(y_ground - h * 0.75)
        if y0 > ch or y0 + h < 0:
            return img
        tex = mist_tex
        off = (t * 0.03 + cam['cx'] * 0.02) % 1.0
        W = tex.shape[1]
        cols = ((np.arange(cw) / cw * 0.6 + off) * W).astype(int) % W
        band = tex[:, cols]  # (256, cw)
        band = Image.fromarray((band * 255).astype(np.uint8)).resize((cw, h), Image.BILINEAR)
        prof = np.sin(np.linspace(0, np.pi, h)) ** 1.5
        a = np.asarray(band, np.float32) / 255.0 * prof[:, None] * 0.28
        A = Image.fromarray((a * 255).clip(0, 255).astype(np.uint8))
        fog = Image.new('RGBA', (cw, h), (120, 130, 150, 0))
        fog.putalpha(A)
        img.alpha_composite(fog, (0, max(y0, 0)), (0, max(-y0, 0)))
        return img


# --------------------------------------------------------------- post
class Post:
    def __init__(self, settings):
        self.S = settings
        W, H = settings.width, settings.height
        v = np.arange(256) / 255.0
        sh = 1 - np.clip(v / 0.5, 0, 1) ** 2 * (3 - 2 * np.clip(v / 0.5, 0, 1))
        hi = np.clip((v - 0.45) / 0.55, 0, 1) ** 2
        con = v + 0.10 * (v - 0.5) * (1 - np.abs(2 * v - 1))
        r = con - 0.040 * sh + 0.060 * hi
        g = con + 0.012 * sh + 0.012 * hi
        b = con + 0.050 * sh - 0.075 * hi
        lut = []
        for c in (r, g, b):
            c = 0.018 + c * 0.985
            lut += list((np.clip(c, 0, 1) * 255).astype(np.uint8))
        self.lut = lut
        ax = (BASE_W - SAFE_RIGHT) / 2 / BASE_W * W
        ay = (SAFE_TOP + (BASE_H - SAFE_BOTTOM - SAFE_TOP) / 2) / BASE_H * H
        yy, xx = np.mgrid[0:H, 0:W].astype(np.float32)
        r_ = np.sqrt(((xx - ax) / (W * 0.62)) ** 2 + ((yy - ay) / (H * 0.62)) ** 2)
        vig = 1 - 0.62 * np.clip((r_ - 0.45) / 0.75, 0, 1) ** 1.6
        self.vig_base = vig.astype(np.float32)
        rng = np.random.default_rng(settings.seed + 7)
        self.grain = [(rng.normal(0, 7.0 * settings.grain, (H // 2 + 16, W // 2 + 16))).astype(np.int16) for _ in range(6)]
        self.center = (ax, ay)

    def apply(self, img, t, frame, ca=0.0, flash=0.0):
        S = self.S
        W, H = img.size
        if ca > 0.02:
            k = 0.006 * ca
            r, g, b = img.split()
            cx, cy = self.center
            def sc(ch, f):
                return ch.transform(img.size, Image.AFFINE, (1 / f, 0, cx - cx / f, 0, 1 / f, cy - cy / f),
                                    resample=Image.BILINEAR)
            img = Image.merge('RGB', (sc(r, 1 + k), g, sc(b, 1 - k)))
        if S.bloom > 0:
            small = img.resize((W // 6, H // 6), Image.BILINEAR)
            br = small.point(lambda v: max(0, v - 150) * 2)
            br = br.filter(ImageFilter.GaussianBlur(4)).resize(img.size, Image.BILINEAR)
            img = ImageChops.add(img, br.point(lambda v: int(v * 0.55 * S.bloom)))
        img = img.point(self.lut)
        if flash > 0:
            img = Image.blend(img, Image.new('RGB', img.size, (255, 248, 235)), flash)
        # fade in/out (loop seam: both ends are equally dark)
        fade = 1.0
        if t < FADE_IN[1]:
            fade = 0.12 + 0.88 * _smooth((t - FADE_IN[0]) / (FADE_IN[1] - FADE_IN[0]))
        if t > FADE_OUT[0]:
            fade = min(fade, 1 - 0.88 * _smooth((t - FADE_OUT[0]) / (FADE_OUT[1] - FADE_OUT[0])))
        arr = np.asarray(img).astype(np.int16)
        vig = self.vig_base * fade
        arr = (arr * vig[..., None]).astype(np.int16)
        gi = frame % 6
        rng = np.random.default_rng(frame)
        ox, oy = rng.integers(0, 16, 2)
        gr = self.grain[gi][oy:oy + (H + 1) // 2, ox:ox + (W + 1) // 2]
        gr = np.repeat(np.repeat(gr, 2, 0), 2, 1)[:H, :W]
        arr += gr[..., None]
        out = np.clip(arr, 0, 255).astype(np.uint8)
        if S.debug_safe_zones:
            out = draw_safe_zones(out, S)
        return out


def draw_safe_zones(arr, S):
    W, H = S.width, S.height
    s = S.s
    o = arr.astype(np.float32)
    top, bot, right = int(SAFE_TOP * s), int(SAFE_BOTTOM * s), int(SAFE_RIGHT * s)
    red = np.array([255, 30, 30], np.float32)
    o[:top] = o[:top] * 0.6 + red * 0.4
    o[H - bot:] = o[H - bot:] * 0.6 + red * 0.4
    o[top:H - bot, W - right:] = o[top:H - bot, W - right:] * 0.6 + red * 0.4
    img = Image.fromarray(o.astype(np.uint8))
    d = ImageDraw.Draw(img)
    d.rectangle([0, top, W - right - 1, H - bot - 1], outline=(40, 255, 80), width=max(2, int(4 * s)))
    d.line([(0, H / 3), (W - right, H / 3)], fill=(255, 255, 0), width=max(1, int(2 * s)))
    d.line([(0, 2 * H / 3), (W - right, 2 * H / 3)], fill=(255, 255, 0), width=max(1, int(2 * s)))
    return np.asarray(img)
