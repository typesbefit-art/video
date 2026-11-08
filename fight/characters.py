"""Vector characters rendered as soft-unioned tapered capsules (signed distance
fields). The SDF gives anti-aliased edges for free and an analytic
pseudo-normal per pixel, which drives soft key light, teal/orange rim lights,
wet specular highlights, impact light and cloth folds - volume through light
and shadow instead of outlines.
"""
import math
import numpy as np

# ---------------------------------------------------------------- materials
MAT = {
    'skinA': dict(alb=(0.66, 0.44, 0.33), spec=0.45, shin=28, sss=0.20),
    'skinB': dict(alb=(0.76, 0.58, 0.48), spec=0.40, shin=28, sss=0.18),
    'topA': dict(alb=(0.085, 0.085, 0.10), spec=0.22, shin=14, fold='torso', famp=0.25),
    'topB': dict(alb=(0.74, 0.74, 0.72), spec=0.10, shin=10, fold='torso', famp=0.22),
    'pantsA': dict(alb=(0.13, 0.15, 0.24), spec=0.12, shin=10, fold='leg', famp=0.30),
    'pantsB': dict(alb=(0.055, 0.055, 0.065), spec=0.18, shin=12, fold='leg', famp=0.30),
    'shoe': dict(alb=(0.035, 0.035, 0.04), spec=0.55, shin=40),
    'hairA': dict(alb=(0.07, 0.04, 0.03), spec=0.5, shin=40, fold='hair', famp=0.35),
    'hairB': dict(alb=(0.025, 0.025, 0.03), spec=0.6, shin=45, fold='hair', famp=0.3),
    'band': dict(alb=(0.62, 0.06, 0.05), spec=0.2, shin=12, fold='leg', famp=0.2),
    'wrap': dict(alb=(0.78, 0.74, 0.68), spec=0.1, shin=8, fold='wrap', famp=0.25),
    'glove': dict(alb=(0.05, 0.045, 0.045), spec=0.6, shin=35),
    'beltA': dict(alb=(0.45, 0.06, 0.05), spec=0.2, shin=10),
    'beltB': dict(alb=(0.03, 0.03, 0.03), spec=0.5, shin=30),
    'eye': dict(alb=(0.03, 0.02, 0.02), spec=0.9, shin=60, flat=True),
    'brow': dict(alb=(0.04, 0.03, 0.025), spec=0.0, shin=10, flat=True),
    'lip': dict(alb=(0.40, 0.20, 0.17), spec=0.3, shin=20),
}

AMB = np.array([0.10, 0.12, 0.16], np.float32)
KEY_D = np.array([-0.25, -0.75, 0.62], np.float32)
KEY_D /= np.linalg.norm(KEY_D)
KEY_C = np.array([0.80, 0.76, 0.72], np.float32) * 0.62
RIM_T = (np.array([-0.96, -0.28], np.float32), np.array([0.12, 0.85, 0.95], np.float32) * 1.05)
RIM_O = (np.array([0.96, -0.28], np.float32), np.array([1.0, 0.52, 0.16], np.float32) * 1.05)
BOUNCE_C = np.array([0.10, 0.13, 0.20], np.float32)
HALF = KEY_D + np.array([0, 0, 1], np.float32)
HALF /= np.linalg.norm(HALF)


def render_blob(caps, mat, size, lights, shade=1.0, alpha_mul=1.0, k=0.0, seed=0.0):
    """caps: (n,6) array [ax, ay, bx, by, ra, rb] in canvas px.
    Returns (x0, y0, premultiplied rgb (h,w,3), alpha (h,w)) or None."""
    cw, ch = size
    lo_x = np.minimum(caps[:, 0] - caps[:, 4], caps[:, 2] - caps[:, 5]).min() - 2
    hi_x = np.maximum(caps[:, 0] + caps[:, 4], caps[:, 2] + caps[:, 5]).max() + 2
    lo_y = np.minimum(caps[:, 1] - caps[:, 4], caps[:, 3] - caps[:, 5]).min() - 2
    hi_y = np.maximum(caps[:, 1] + caps[:, 4], caps[:, 3] + caps[:, 5]).max() + 2
    x0, x1 = max(int(lo_x), 0), min(int(hi_x) + 1, cw)
    y0, y1 = max(int(lo_y), 0), min(int(hi_y) + 1, ch)
    if x1 - x0 < 1 or y1 - y0 < 1:
        return None
    X = np.arange(x0, x1, dtype=np.float32)[None, :] + 0.5
    Y = np.arange(y0, y1, dtype=np.float32)[:, None] + 0.5
    ds, nxs, nys = [], [], []
    t0 = u0 = None
    for i, (ax, ay, bx, by, ra, rb) in enumerate(caps):
        bax, bay = bx - ax, by - ay
        l2 = bax * bax + bay * bay + 1e-6
        px, py = X - ax, Y - ay
        h = np.clip((px * bax + py * bay) * (1.0 / l2), 0.0, 1.0)
        r = ra + (rb - ra) * h
        dx = px - bax * h
        dy = py - bay * h
        dist = np.sqrt(dx * dx + dy * dy)
        ir = 1.0 / np.maximum(r, 0.5)
        ds.append(dist - r)
        nxs.append(dx * ir)
        nys.append(dy * ir)
        if i == 0:
            t0 = h
            ln = math.sqrt(l2)
            u0 = (dx * (-bay) + dy * bax) * (ir / ln)
    if len(ds) == 1:
        d, nx, ny = ds[0], nxs[0], nys[0]
    else:
        kk = max(k, 0.5)
        dm = ds[0]
        for dd in ds[1:]:
            dm = np.minimum(dm, dd)
        S = 0.0
        nx = 0.0
        ny = 0.0
        for dd, a, b in zip(ds, nxs, nys):
            e = np.exp((dm - dd) * (1.0 / kk))
            S = S + e
            nx = nx + e * a
            ny = ny + e * b
        iS = 1.0 / S
        d = dm - kk * np.log(S)
        nx = nx * iS
        ny = ny * iS
    alpha = np.clip(0.5 - d, 0.0, 1.0) * alpha_mul
    if not alpha.any():
        return None
    n2 = np.minimum(nx * nx + ny * ny, 0.985)
    sc = np.sqrt(n2 / np.maximum(nx * nx + ny * ny, 1e-6))
    nx = nx * sc
    ny = ny * sc
    nz = np.sqrt(1.0 - n2)
    alb = np.array(mat['alb'], np.float32)
    if mat.get('flat'):
        lum = 0.6 + 0.4 * nz
        col = alb[None, None, :] * lum[..., None]
        sp = np.clip(nx * HALF[0] + ny * HALF[1] + nz * HALF[2], 0, 1) ** mat['shin'] * mat['spec']
        col = col + sp[..., None] * 0.9
        col = col * shade
        return x0, y0, col * alpha[..., None], alpha
    # soft wrapped key light
    ndl = nx * KEY_D[0] + ny * KEY_D[1] + nz * KEY_D[2]
    diff = np.clip((ndl + 0.35) / 1.35, 0, 1)
    ao = 0.62 + 0.38 * nz
    fold = mat.get('fold')
    m = 1.0
    if fold == 'leg':
        f = np.sin(t0 * 31.0 + u0 * 2.2 + seed) + 0.6 * np.sin(t0 * 13.0 - u0 * 3.1 + seed * 1.7)
        m = 1.0 - mat['famp'] * np.clip(f * 0.6, 0, 1) ** 2
    elif fold == 'torso':
        f = np.sin(t0 * 22.0 + u0 * 4.0 + seed) * np.sin(t0 * 9.0 - u0 * 1.5)
        m = 1.0 - mat['famp'] * np.clip(f, 0, 1) ** 1.5
    elif fold == 'hair':
        f = np.sin(u0 * 23.0 + t0 * 3.0 + seed)
        m = 1.0 - mat['famp'] * np.clip(f, 0, 1) ** 2
    elif fold == 'wrap':
        f = np.sin(t0 * 38.0 + u0 * 1.4 + seed)
        m = 1.0 - mat['famp'] * np.clip(f, 0, 1) ** 4
    lit = AMB[None, None, :] + (KEY_C[None, None, :] * (diff * ao)[..., None])
    # bounce light from the wet street
    lit = lit + BOUNCE_C[None, None, :] * np.clip(ny, 0, 1)[..., None]
    for (lx, ly, lz, lc, lr) in lights:
        vx, vy = lx - X, ly - Y
        dist2 = vx * vx + vy * vy
        inv = 1.0 / np.sqrt(dist2 + lz * lz)
        nd = np.clip((nx * vx + ny * vy + nz * lz) * inv, 0, 1)
        fall = 1.0 / (1.0 + dist2 / (lr * lr))
        lit = lit + np.asarray(lc, np.float32)[None, None, :] * (nd * fall)[..., None]
    col = alb[None, None, :] * lit
    if isinstance(m, np.ndarray):
        col = col * m[..., None]
    sss = mat.get('sss', 0.0)
    if sss:
        col = col + np.array([0.35, 0.08, 0.04], np.float32)[None, None, :] * (sss * (1 - nz) * diff)[..., None] * 0.5
    edge = (1.0 - nz) ** 1.6
    for (dvec, rc) in (RIM_T, RIM_O):
        rim = np.clip(nx * dvec[0] + ny * dvec[1], 0, 1) ** 1.5 * edge
        col = col + rc[None, None, :] * (rim * (0.35 + 0.65 * max(alb.max(), 0.35)))[..., None]
    sp = np.clip(nx * HALF[0] + ny * HALF[1] + nz * HALF[2], 0, 1) ** mat['shin'] * mat['spec']
    col = col + sp[..., None] * np.array([0.9, 0.9, 0.95], np.float32)
    col = col * shade
    return x0, y0, col * alpha[..., None], alpha


# ------------------------------------------------------------ part assembly
def _v(B, x, y, z):
    return B @ np.array([x, y, z])


class Look:
    def __init__(self, name):
        self.name = name
        if name == 'A':
            self.skin, self.top, self.pants, self.hair = 'skinA', 'topA', 'pantsA', 'hairA'
            self.hand, self.belt = 'wrap', 'beltA'
        else:
            self.skin, self.top, self.pants, self.hair = 'skinB', 'topB', 'pantsB', 'hairB'
            self.hand, self.belt = 'glove', 'beltB'


def build_parts(P, look, chains):
    """Return list of parts: dict(name, caps=[(p1, p2, r1, r2)], mat, k, bias)."""
    J, B = P.J, P.B
    Bu, Bh, Bl = B['upper'], B['head'], B['lower']
    parts = []

    def add(name, caps, mat, k=0.0, bias=0.0, depth=None):
        parts.append(dict(name=look.name + name, caps=caps, mat=mat, k=k, bias=bias, depth=depth))

    pel, cb, nb = J['pelvis'], J['chest_base'], J['neck_base']
    abd = J['abdomen']
    # pelvis / pants
    add('pelvis', [(pel + _v(Bl, 0.0, 0.0, 0.07), pel + _v(Bl, 0.0, 0.0, -0.07), 0.118, 0.118),
                   (pel + _v(Bl, 0.01, 0.06, 0.0), pel + _v(Bl, 0.0, -0.05, 0.0), 0.115, 0.11)],
        look.pants, k=0.03, bias=-0.01)
    # belt band
    add('belt', [(pel + _v(Bl, 0.0, 0.075, 0.07), pel + _v(Bl, 0.0, 0.075, -0.07), 0.122, 0.122)],
        look.belt, bias=-0.008)
    # shoulders (skin, under the tank top)
    add('traps', [(J['sh_n'], J['sh_f'], 0.062, 0.062),
                  (nb + _v(Bu, -0.01, -0.02, 0), J['neck_top'], 0.07, 0.055)], look.skin, k=0.03, bias=-0.02)
    # torso (tank top)
    chest_c = cb + _v(Bu, 0.035, 0.13, 0.0)
    add('torso', [(abd + _v(Bl, 0.0, -0.02, 0.0), nb + _v(Bu, -0.01, -0.07, 0.0), 0.11, 0.125),
                  (chest_c + _v(Bu, 0, 0, 0.075), chest_c + _v(Bu, 0, 0, -0.075), 0.118, 0.118),
                  (abd + _v(Bl, 0.02, 0.0, 0.055), abd + _v(Bl, 0.02, 0.0, -0.055), 0.104, 0.104)],
        look.top, k=0.045, bias=-0.005)
    # neck + head
    add('neck', [(nb + _v(Bu, 0.005, 0.0, 0), J['neck_top'], 0.058, 0.052)], look.skin, bias=0.0)
    hc = J['head']
    add('head', [(hc + _v(Bh, -0.005, 0.012, 0.0), hc + _v(Bh, -0.004, 0.013, 0.0), 0.099, 0.099),
                 (hc + _v(Bh, 0.03, -0.005, 0.03), hc + _v(Bh, 0.074, -0.083, 0.018), 0.064, 0.034),
                 (hc + _v(Bh, 0.03, -0.005, -0.03), hc + _v(Bh, 0.074, -0.083, -0.018), 0.064, 0.034),
                 (hc + _v(Bh, 0.098, -0.008, 0.0), hc + _v(Bh, 0.113, -0.036, 0.0), 0.014, 0.017)],
        look.skin, k=0.012, bias=0.02)
    # face details (visibility by orientation)
    fwd_depth = Bh[2, 0]   # depth component of head forward axis
    side_depth = Bh[2, 2]
    for zs in (1.0, -1.0):
        vis = side_depth * zs  # >0: this side faces camera
        ear = hc + _v(Bh, -0.012, -0.005, 0.095 * zs)
        if vis > -0.25:
            add('ear%d' % zs, [(ear + _v(Bh, 0, 0.018, 0), ear + _v(Bh, 0.004, -0.018, 0), 0.02, 0.016)],
                look.skin, bias=0.021 if vis > 0 else -0.03)
        if vis > -0.6 and fwd_depth > -0.5:
            eye = hc + _v(Bh, 0.085, 0.012, 0.036 * zs)
            add('eye%d' % zs, [(eye + _v(Bh, -0.006, 0, 0), eye + _v(Bh, 0.006, 0, 0), 0.0075, 0.0065)],
                'eye', bias=0.025)
            brow = hc + _v(Bh, 0.09, 0.034, 0.036 * zs)
            add('brow%d' % zs, [(brow + _v(Bh, -0.016, 0.003, 0), brow + _v(Bh, 0.012, -0.003, 0), 0.0055, 0.0045)],
                'brow', bias=0.025)
    mouth = hc + _v(Bh, 0.096, -0.062, 0.0)
    if fwd_depth > -0.5:
        add('mouth', [(mouth + _v(Bh, 0, 0, 0.018), mouth + _v(Bh, 0, 0, -0.018), 0.006, 0.006)], 'lip', bias=0.024)
    # hair
    if look.name == 'A':
        add('hair', [(hc + _v(Bh, -0.045, 0.035, 0), hc + _v(Bh, -0.015, 0.078, 0), 0.094, 0.055),
                     (hc + _v(Bh, -0.02, 0.09, 0), hc + _v(Bh, -0.13, 0.12, 0.0), 0.04, 0.008),
                     (hc + _v(Bh, 0.03, 0.1, 0.02), hc + _v(Bh, -0.06, 0.17, 0.03), 0.035, 0.007),
                     (hc + _v(Bh, -0.06, 0.05, 0), hc + _v(Bh, -0.15, 0.03, 0.0), 0.04, 0.008)],
            look.hair, k=0.01, bias=0.022)
        add('band', [(hc + _v(Bh, 0.098, 0.048, 0), hc + _v(Bh, -0.105, 0.03, 0), 0.016, 0.02)],
            'band', bias=0.023)
    else:
        add('hair', [(hc + _v(Bh, -0.045, 0.035, 0), hc + _v(Bh, -0.012, 0.078, 0), 0.095, 0.056),
                     (hc + _v(Bh, -0.09, 0.05, 0), hc + _v(Bh, -0.105, 0.065, 0), 0.04, 0.035)],
            look.hair, k=0.01, bias=0.022)
    # arms
    for s in ('n', 'f'):
        sh, el, wr, hd = J['sh_' + s], J['el_' + s], J['wr_' + s], J['hand_' + s]
        add('uarm' + s, [(sh, el, 0.060, 0.045), (sh + _v(Bu, 0.0, 0.01, 0), sh + _v(Bu, 0.01, -0.07, 0), 0.072, 0.056),
                          (sh + (el - sh) * 0.3, sh + (el - sh) * 0.7, 0.062, 0.05)],
            look.skin, k=0.02)
        if look.name == 'A':
            mid = wr + (el - wr) * 0.28
            add('farm' + s, [(el, mid, 0.048, 0.037), (el + (wr - el) * 0.1, el + (wr - el) * 0.4, 0.052, 0.042)], look.skin, k=0.015)
            add('wrap' + s, [(mid, wr, 0.038, 0.035)], 'wrap', bias=0.001)
        else:
            add('farm' + s, [(el, wr, 0.048, 0.034), (el + (wr - el) * 0.1, el + (wr - el) * 0.4, 0.052, 0.042)], look.skin, k=0.015)
        dvec = hd - wr
        ln = np.linalg.norm(dvec) + 1e-9
        side = Bu[:, 2]
        kn = hd - dvec / ln * 0.012
        add('hand' + s, [(wr, hd - dvec / ln * 0.02, 0.036, 0.042),
                         (kn + side * 0.03, kn - side * 0.03, 0.03, 0.03)], look.hand, k=0.012, bias=0.002)
    # legs
    for s in ('n', 'f'):
        hp, kn, an, he, ft = J['hip_' + s], J['knee_' + s], J['ankle_' + s], J['heel_' + s], J['foot_' + s]
        add('thigh' + s, [(hp, kn, 0.088, 0.06), (hp + _v(Bl, -0.03, 0.02, 0), hp + _v(Bl, -0.02, -0.15, 0), 0.085, 0.07)],
            look.pants, k=0.03)
        back = -Bl[:, 0]
        add('shin' + s, [(kn, an, 0.056, 0.042), (kn + back * 0.02 + (an - kn) * 0.15, kn + (an - kn) * 0.55, 0.056, 0.045)],
            look.pants, k=0.02)
        add('foot' + s, [(he, ft, 0.044, 0.034), (an, he, 0.046, 0.044)], 'shoe', k=0.015, bias=0.002)
    # spring chains
    if chains is not None:
        if look.name == 'A':
            for ci, pts in enumerate(chains[:2]):
                caps = [(pts[i], pts[i + 1], 0.019 - i * 0.0015, 0.017 - i * 0.0015) for i in range(len(pts) - 1)]
                add('ribbon%d' % ci, caps, 'band', k=0.005, bias=0.019 if ci == 0 else -0.04)
            for ci, pts in enumerate(chains[2:4]):
                caps = [(pts[i], pts[i + 1], 0.022, 0.02) for i in range(len(pts) - 1)]
                add('sash%d' % ci, caps, look.belt, k=0.005, bias=0.012)
        else:
            pts = chains[0]
            caps = [(pts[i], pts[i + 1], max(0.038 - i * 0.004, 0.012), max(0.034 - i * 0.004, 0.01)) for i in range(len(pts) - 1)]
            add('pony', caps, look.hair, k=0.012, bias=-0.03)
            pts = chains[1]
            caps = [(pts[i], pts[i + 1], 0.02, 0.018) for i in range(len(pts) - 1)]
            add('beltend', caps, look.belt, k=0.005, bias=0.012)
    hd = float(J['head'][2])
    head_rel = {'head': 0.020, 'hair': 0.0215, 'band': 0.0225, 'mouth': 0.024}
    for p in parts:
        nm = p['name'][1:]
        if nm in head_rel:
            p['depth'] = hd + head_rel[nm]
        elif nm.startswith(('eye', 'brow')):
            p['depth'] = hd + 0.025
        elif nm.startswith('ear'):
            p['depth'] = hd + (0.021 if p['bias'] > 0 else -0.03)
    for p in parts:
        if p['depth'] is None:
            p['depth'] = float(np.mean([c[0][2] + c[1][2] for c in p['caps']]) * 0.5) + p['bias']
    return parts


def project_caps(caps3d, cam):
    """caps3d: list of (p1, p2, r1, r2) world -> (n,6) canvas px."""
    out = np.empty((len(caps3d), 6), np.float32)
    cx, cy, zs, ax, ay, D = cam['cx'], cam['cy'], cam['zs'], cam['ax'], cam['ay'], cam['Dm']
    for i, (p1, p2, r1, r2) in enumerate(caps3d):
        f1 = D / max(D - p1[2], D * 0.12)
        f2 = D / max(D - p2[2], D * 0.12)
        out[i] = (ax + (p1[0] - cx) * zs * f1, ay - (p1[1] - cy) * zs * f1,
                  ax + (p2[0] - cx) * zs * f2, ay - (p2[1] - cy) * zs * f2,
                  r1 * zs * f1, r2 * zs * f2)
    return out


def project_pt(p, cam):
    D = cam['Dm']
    f = D / max(D - p[2], D * 0.12)
    return (cam['ax'] + (p[0] - cam['cx']) * cam['zs'] * f,
            cam['ay'] - (p[1] - cam['cy']) * cam['zs'] * f, f)
