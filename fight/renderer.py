"""Frame compositor: background layers -> wet ground with reflections ->
alley wall -> crates + fighters (with motion blur, smears, reflections, impact
light) -> particles -> rain -> fog -> lens effects -> camera roll -> post."""
import math
import zlib
import numpy as np
from PIL import Image, ImageChops
from .config import Settings, LENS_F, MARGIN_X, MARGIN_Y, MAX_ROLL_DEG
from .timeline import TL
from .scene import Scene
from .choreography import Choreo, camera
from .characters import Look, build_parts, project_caps, project_pt, render_blob, MAT
from .fx import FX, Post, CRASH_T

SMEAR_JOINTS = [('hand_n', 'wr_n'), ('hand_f', 'wr_f'), ('foot_n', 'ankle_n'), ('foot_f', 'ankle_f')]


class Renderer:
    def __init__(self, settings: Settings, scene=None, choreo=None):
        self.S = settings
        self.s = settings.s
        self.cw, self.ch = settings.canvas
        self.ax, self.ay = settings.anchor
        self.scene = scene if scene is not None else Scene(settings.seed)
        self.choreo = choreo if choreo is not None else Choreo()
        self.fx = FX(settings, self.choreo)
        self.post = Post(settings)
        self.looks = {'A': Look('A'), 'B': Look('B')}
        self.dt = 1.0 / settings.fps

    # ------------------------------------------------------------ camera
    def cam_at(self, t):
        c = camera(t, self.choreo)
        dx, dy, dr, zm = self.fx.shake(t)
        z = c['zoom'] * zm
        s = self.s
        cam = dict(cx=c['cx'] - dx / z * 0.5, cy=c['cy'] + dy / z * 0.5, zoom=z,
                   roll=max(-math.radians(MAX_ROLL_DEG), min(math.radians(MAX_ROLL_DEG), c['roll'] + dr)),
                   zs=z * s, ax=self.ax, ay=self.ay, shot=c['shot'])
        cam['cy'] = max(cam['cy'], 0.08)
        cam['Dm'] = c['D'] if c['D'] else LENS_F / z
        return cam

    # ------------------------------------------------------------ background
    def background(self, cam, t):
        size = (self.cw, self.ch)
        sc = self.scene
        # distant layers at half resolution (soft depth of field, ~4x cheaper)
        hs = 0.5
        hsz = (int(self.cw * hs), int(self.ch * hs))
        far = sc.sky.draw(hsz, cam, self.s, self.ax, self.ay, out_scale=hs)
        for L in (sc.far, sc.mid):
            far.alpha_composite(L.draw(hsz, cam, self.s, self.ax, self.ay, out_scale=hs))
        img = far.resize(size, Image.BILINEAR)
        img.alpha_composite(sc.street.draw(size, cam, self.s, self.ax, self.ay))
        return img

    def ground_fn(self, cam):
        Fs = LENS_F * self.s
        Dc = Fs / cam['zs']

        def fn(u, d):
            dist = Dc + d
            g = np.where(dist > 0.4, Fs / np.maximum(dist, 0.4), -1.0)
            x = cam['ax'] + (u - cam['cx']) * g
            y = cam['ay'] + cam['cy'] * g
            return x, y, g
        return fn

    def ground(self, img, cam, t):
        sc = self.scene
        s = self.s
        cw, ch = self.cw, self.ch
        yb = sc.street.base_y(cam, s, self.ay)
        if yb >= ch - 1:
            return None, ch
        hs = 0.5
        hw, hh = int(cw * hs), int(ch * hs)
        refl = Image.new('RGBA', (hw, hh), (0, 0, 0, 255))
        wall = sc.wall_cracked if t >= CRASH_T else sc.wall
        for L in (sc.sky, sc.far, sc.mid, sc.street, wall):
            refl.alpha_composite(L.draw((hw, hh), cam, s, self.ax, self.ay, out_scale=hs, mirror=True))
        rgb = refl.convert('RGB')
        for L in (sc.mid, sc.street):
            rgb = ImageChops.add(rgb, L.draw((hw, hh), cam, s, self.ax, self.ay, out_scale=hs, mirror=True, glow=True))
        blur = rgb.resize((max(hw // 3, 1), max(hh // 9, 1)), Image.BILINEAR).resize((hw, hh), Image.BILINEAR)
        r0 = max(int(yb * hs), 0)
        R = np.asarray(rgb, np.float32)[r0:]
        Rb = np.asarray(blur, np.float32)[r0:]
        rows = (np.arange(r0, hh, dtype=np.float32) + 0.5) / hs
        cols = (np.arange(hw, dtype=np.float32) + 0.5) / hs
        cy = max(cam['cy'], 0.08)
        g = np.maximum((rows - self.ay) / cy, 1e-3)  # px per metre at that ground row
        Fs = LENS_F * s
        Dc = Fs / cam['zs']
        d = Fs / g - Dc
        u = cam['cx'] + (cols[None, :] - self.ax) / g[:, None]
        pud, rough = sc.ground.sample(u, np.broadcast_to(d[:, None], u.shape))
        g0 = sc.street.zoom_l(cam['zoom'], s)
        fres = np.clip(0.30 + 0.70 * (g0 / g) ** 0.55, 0, 1)[:, None]
        base = np.array([13, 14, 18], np.float32) * (0.75 + 0.5 * rough)[..., None]
        refl_k = fres * (0.30 + 0.62 * pud)
        out = base + (pud[..., None] * R * 0.85 + (1 - pud[..., None]) * Rb * 0.55) * fres[..., None]
        gimg = Image.fromarray(out.clip(0, 255).astype(np.uint8)).resize((cw, ch - int(r0 / hs)), Image.BILINEAR)
        y_paste = int(r0 / hs)
        img.paste(gimg, (0, y_paste))
        kmap = Image.fromarray((refl_k * 255).clip(0, 255).astype(np.uint8)).resize((cw, ch - y_paste), Image.BILINEAR)
        return np.asarray(kmap, np.float32) / 255.0, y_paste

    # ------------------------------------------------------------ characters
    def char_parts(self, tau, cam, smear_from=None):
        out = []
        for name in ('A', 'B'):
            tr = self.choreo.tracks[name]
            P = tr.pose(tau)
            chains = self.choreo.chain_pts(name, tau)
            parts = build_parts(P, self.looks[name], chains)
            if smear_from is not None:
                P2 = tr.pose(smear_from)
                for jn, base in SMEAR_JOINTS:
                    a0 = project_pt(P.J[jn], cam)
                    a1 = project_pt(P2.J[jn], cam)
                    dist = math.hypot(a0[0] - a1[0], a0[1] - a1[1]) / self.s
                    if dist > 70:
                        look = self.looks[name]
                        mat = look.hand if jn.startswith('hand') else 'shoe'
                        r = 0.045 if jn.startswith('hand') else 0.04
                        mid = (P.J[jn] + P2.J[jn]) * 0.5
                        parts.append(dict(name=name + 'smear' + jn,
                                          caps=[(P.J[jn], mid, r, r * 0.75), (mid, P2.J[jn], r * 0.75, r * 0.15)],
                                          mat=mat, k=0.01, bias=0.0, smear=min(1.0, (dist - 70) / 120),
                                          depth=float(P.J[jn][2]) - 0.001))
            out += parts
        out.sort(key=lambda p: p['depth'])
        for p in out:
            p['c2'] = project_caps(p['caps'], cam)
        return out

    def characters(self, t, cam, lights):
        S = self.S
        tau = float(TL.tau(t))
        tau_prev = float(TL.tau(t - S.shutter * self.dt))
        # decide motion-blur sample count from limb displacement in the shutter
        n = 1
        if S.mb_samples > 1 and abs(tau - tau_prev) > 1e-6:
            maxd = 0.0
            for name in ('A', 'B'):
                tr = self.choreo.tracks[name]
                P0, P1 = tr.pose(tau), tr.pose(tau_prev)
                for jn in ('hand_n', 'hand_f', 'foot_n', 'foot_f', 'head', 'pelvis'):
                    a = project_pt(P0.J[jn], cam)
                    b = project_pt(P1.J[jn], cam)
                    maxd = max(maxd, math.hypot(a[0] - b[0], a[1] - b[1]))
            if maxd > S.mb_threshold_px * self.s:
                n = S.mb_samples
        taus = [float(TL.tau(t - S.shutter * self.dt * k / max(n - 1, 1))) for k in range(n)] if n > 1 else [tau]
        smear_tau = float(TL.tau(t - 2.5 * self.dt))
        samples = [self.char_parts(tk, cam, smear_from=smear_tau if k == 0 else None) for k, tk in enumerate(taus)]
        # union bbox
        allc = np.concatenate([p['c2'] for smp in samples for p in smp])
        lo_x = np.minimum(allc[:, 0] - allc[:, 4], allc[:, 2] - allc[:, 5]).min() - 3
        hi_x = np.maximum(allc[:, 0] + allc[:, 4], allc[:, 2] + allc[:, 5]).max() + 3
        lo_y = np.minimum(allc[:, 1] - allc[:, 4], allc[:, 3] - allc[:, 5]).min() - 3
        hi_y = np.maximum(allc[:, 1] + allc[:, 4], allc[:, 3] + allc[:, 5]).max() + 3
        X0, X1 = max(int(lo_x), 0), min(int(hi_x) + 1, self.cw)
        Y0, Y1 = max(int(lo_y), 0), min(int(hi_y) + 1, self.ch)
        if X1 - X0 < 2 or Y1 - Y0 < 2:
            return None
        h, w = Y1 - Y0, X1 - X0
        acc_c = np.zeros((h, w, 3), np.float32)
        acc_a = np.zeros((h, w), np.float32)
        cache = {}
        size = (self.cw, self.ch)
        lt = [(sx, sy, 300.0 * self.s, tuple(np.array(col) * min(I, 1.2) * 0.8), 650.0 * self.s * (0.6 + 0.4 * (e['power'] if e else 1.0)))
              for (sx, sy, I, col, e) in lights]
        for smp in samples:
            lc = np.zeros((h, w, 3), np.float32) if n > 1 else acc_c
            la = np.zeros((h, w), np.float32) if n > 1 else acc_a
            for p in smp:
                key = p['name']
                c2 = p['c2']
                hit = cache.get(key)
                if hit is not None and hit[0].shape == c2.shape and np.abs(hit[0] - c2).max() < 0.6:
                    res = hit[1]
                else:
                    shade = 0.80 if p['depth'] < -0.06 else 1.0
                    res = render_blob(c2, MAT[p['mat']], size, lt, shade=shade,
                                      alpha_mul=0.45 * p['smear'] if 'smear' in p else 1.0,
                                      k=p['k'] * cam['zs'], seed=zlib.crc32(key.encode()) % 7)
                    cache[key] = (c2, res)
                if res is None:
                    continue
                x0, y0, pc, pa = res
                ys, xs = y0 - Y0, x0 - X0
                hh, ww = pa.shape
                ys0, xs0 = max(ys, 0), max(xs, 0)
                ys1, xs1 = min(ys + hh, h), min(xs + ww, w)
                if ys1 <= ys0 or xs1 <= xs0:
                    continue
                sub_c = pc[ys0 - ys:ys1 - ys, xs0 - xs:xs1 - xs]
                sub_a = pa[ys0 - ys:ys1 - ys, xs0 - xs:xs1 - xs]
                inv = 1.0 - sub_a
                lc[ys0:ys1, xs0:xs1] = sub_c + lc[ys0:ys1, xs0:xs1] * inv[..., None]
                la[ys0:ys1, xs0:xs1] = sub_a + la[ys0:ys1, xs0:xs1] * inv
            if n > 1:
                acc_c += lc
                acc_a += la
        if n > 1:
            acc_c /= n
            acc_a /= n
        return X0, Y0, np.clip(acc_c, 0, 4) * 255.0, acc_a

    # ------------------------------------------------------------ compositing
    def comp(self, cv, layer, yg, kmap, ygb, t, refl=True):
        x0, y0, pc, pa = layer
        h, w = pa.shape
        ch = cv.shape[0]
        if refl and kmap is not None:
            r0 = max(int(math.ceil(yg)), ygb, 0)
            r1 = min(int(2 * yg - y0), ch)
            if r1 > r0:
                rows = np.arange(r0, r1)
                src = np.round(2 * yg - rows - y0).astype(np.int32)
                ok = (src >= 0) & (src < h)
                rows, src = rows[ok], src[ok]
                if len(rows):
                    P = pc[src]
                    A = pa[src]
                    # vertical blur via cumulative sum
                    k = max(1, int(6 * self.s))
                    def vblur(a):
                        c = np.cumsum(a, axis=0)
                        out = np.empty_like(a)
                        out[k:] = (c[k:] - c[:-k]) / k
                        out[:k] = c[:k] / (np.arange(1, min(k, len(a)) + 1).reshape((-1,) + (1,) * (a.ndim - 1)))
                        return out
                    if len(rows) > k:
                        P = vblur(P)
                        A = vblur(A)
                    # ripple
                    sh = (np.sin(rows * 0.11 / self.s + t * 7.0) * 2.5 * self.s +
                          np.sin(rows * 0.031 / self.s - t * 3.0) * 3.0 * self.s).astype(np.int32)
                    xi = np.clip(np.arange(w)[None, :] + sh[:, None], 0, w - 1)
                    P = P[np.arange(len(rows))[:, None], xi]
                    A = A[np.arange(len(rows))[:, None], xi]
                    dist = (rows - yg) / (self.s * 900.0)
                    fade = np.exp(-dist * 2.2)[:, None]
                    km = kmap[rows - ygb][:, x0:x0 + w] if rows.max() - ygb < kmap.shape[0] else None
                    if km is not None and km.shape[1] == w:
                        m = km * fade * 0.85
                        A2 = A * m
                        P2 = P * m[..., None] * np.array([0.72, 0.78, 0.9], np.float32)
                        region = cv[rows, x0:x0 + w]
                        cv[rows, x0:x0 + w] = P2 + region * (1 - A2[..., None])
        cv[y0:y0 + h, x0:x0 + w] = pc + cv[y0:y0 + h, x0:x0 + w] * (1 - pa[..., None])

    def contact_shadows(self, cv, cam, tau):
        ch, cw = cv.shape[:2]
        for name in ('A', 'B'):
            P = self.choreo.tracks[name].pose(tau)
            ys = [P.J[j][1] for j in ('ankle_n', 'ankle_f', 'pelvis')]
            hgt = min(ys)
            k = max(0.0, 1.0 - hgt / 1.2)
            if k <= 0:
                continue
            xs = [P.J[j][0] for j in ('ankle_n', 'ankle_f', 'pelvis', 'head')]
            xc = float(np.mean(xs[:3]))
            half = max(abs(max(xs) - min(xs)) * 0.6, 0.35)
            gx, gy, _ = project_pt(np.array([xc, 0.0, 0.0]), cam)
            rx, ry = half * cam['zs'], 0.07 * cam['zs']
            x0, x1 = max(int(gx - rx), 0), min(int(gx + rx), cw)
            y0, y1 = max(int(gy - ry), 0), min(int(gy + ry), ch)
            if x1 <= x0 or y1 <= y0:
                continue
            X = (np.arange(x0, x1) - gx) / rx
            Y = (np.arange(y0, y1) - gy) / ry
            d = X[None, :] ** 2 + Y[:, None] ** 2
            m = np.clip(1 - d, 0, 1) ** 1.5 * 0.55 * k
            cv[y0:y1, x0:x1] *= (1 - m)[..., None]

    # ------------------------------------------------------------ frame
    def render(self, t, frame):
        cam = self.cam_at(t)
        tau = float(TL.tau(t))
        img = self.background(cam, t)
        kmap, ygb = self.ground(img, cam, t)
        sc = self.scene
        gl = sc.mid.draw((self.cw // 2, self.ch // 2), cam, self.s, self.ax, self.ay, out_scale=0.5, glow=True)
        gl = ImageChops.add(gl, sc.street.draw((self.cw // 2, self.ch // 2), cam, self.s, self.ax, self.ay,
                                               out_scale=0.5, glow=True)).resize((self.cw, self.ch), Image.BILINEAR)
        img = Image.merge('RGBA', ImageChops.add(img.convert('RGB'), gl).split() + (img.getchannel('A'),))
        wall = sc.wall_cracked if t >= CRASH_T else sc.wall
        img.alpha_composite(wall.draw((self.cw, self.ch), cam, self.s, self.ax, self.ay))
        img = self.fx.draw_splashes(img, t, cam, self.ground_fn(cam))
        cv = np.asarray(img.convert('RGB'), np.float32).copy()
        li = self.fx.lightning(t)
        if li > 0.01:
            grad = np.linspace(1.0, 0.2, self.ch, dtype=np.float32)[:, None, None]
            cv += grad * np.array([0.55, 0.65, 1.0], np.float32) * (li * 110)
        yg = self.ay + cam['cy'] * cam['zs']
        self.contact_shadows(cv, cam, tau)
        lights = self.fx.flash_lights(t, tau, cam)
        crates = self.fx.draw_crates(t, cam, (self.cw, self.ch))
        if crates is not None:
            x0, y0, pc, pa = crates
            self.comp(cv, (x0, y0, pc * 255.0, pa), yg, kmap, ygb, t)
        chars = self.characters(t, cam, lights)
        if chars is not None:
            self.comp(cv, chars, yg, kmap, ygb, t)
        self.fx.draw_glows(cv, lights, cam)
        img = Image.fromarray(cv.clip(0, 255).astype(np.uint8)).convert('RGBA')
        img = self.fx.draw_particles(img, t, tau, cam)
        img = self.fx.mist(img, t, cam, sc.mist, yg)
        img = self.fx.draw_rain(img, t, cam, cam['roll'])
        img = self.fx.shockwaves(img, t, tau, cam)
        img = self.fx.speed_lines(img, t, cam, frame)
        img = img.convert('RGB')
        if abs(cam['roll']) > 1e-4:
            img = img.rotate(math.degrees(cam['roll']), resample=Image.BILINEAR, center=(self.ax, self.ay))
        mx, my = int(round(MARGIN_X * self.s)), int(round(MARGIN_Y * self.s))
        img = img.crop((mx, my, mx + self.S.width, my + self.S.height))
        return self.post.apply(img, t, frame, ca=self.fx.ca_amount(t), flash=self.fx.impact_frame(t))
