"""Skeletal rig: 2.5D FK + analytic two-bone IK, keyframe tracks, spring chains.

Body is ~1.80 m tall with realistic 7.5-head proportions (head = 0.24 m).
Local frame: x = forward, y = up, z = toward camera (canonical "near" side).
The body can yaw around the vertical axis (phi) and the upper body can twist
on top of that, which gives believable 3/4 views and spinning moves while
everything stays vector/2D.
"""
import math
import numpy as np

PARAMS = ['x', 'y', 'phi', 'lean', 'chestb', 'twist', 'head',
          'hnx', 'hny', 'hfx', 'hfy',   # hand targets relative to shoulder (body axes)
          'fnx', 'fny', 'ffx', 'ffy',   # ankle: x rel. pelvis, y = absolute world height
          'wn', 'wf', 'an', 'af']       # wrist / ankle angles
IDX = {k: i for i, k in enumerate(PARAMS)}
NP = len(PARAMS)

HEAD = 0.24
DIM = dict(abdomen=0.235, chest=0.25, neck=0.085, uarm=0.30, farm=0.27,
           thigh=0.45, shin=0.445, sh_z=0.175, hip_z=0.095, hand=0.085)


# --------------------------------------------------------------------- easing
def ease(name, u):
    u = min(max(u, 0.0), 1.0)
    if name == 'lin':
        return u
    if name == 'in':        # accelerate into the impact
        return u * u * u
    if name == 'in2':
        return u * u
    if name == 'out':
        return 1 - (1 - u) ** 3
    if name == 'out2':
        return 1 - (1 - u) ** 2
    if name == 'outback':   # follow-through overshoot
        c = 1.9
        v = u - 1
        return 1 + (c + 1) * v ** 3 + c * v ** 2
    if name == 'hold':
        return 0.0
    return u * u * (3 - 2 * u)  # 'io'


def ik2(sx, sy, tx, ty, l1, l2, bend):
    dx, dy = tx - sx, ty - sy
    d = math.hypot(dx, dy)
    if d < 1e-6:
        dx, dy, d = 0.0, -1e-6, 1e-6
    ux, uy = dx / d, dy / d
    d = min(max(d, abs(l1 - l2) + 1e-3), (l1 + l2) * 0.9995)
    a = (l1 * l1 - l2 * l2 + d * d) / (2 * d)
    h = math.sqrt(max(l1 * l1 - a * a, 0.0))
    px, py = -uy, ux
    return ((sx + ux * a + px * h * bend, sy + uy * a + py * h * bend),
            (sx + ux * d, sy + uy * d), d / (l1 + l2))


def _rz(a):
    c, s = math.cos(a), math.sin(a)
    return np.array([[c, s, 0.0], [-s, c, 0.0], [0.0, 0.0, 1.0]])


def _ry(a):
    c, s = math.cos(a), math.sin(a)
    return np.array([[c, 0.0, -s], [0.0, 1.0, 0.0], [s, 0.0, c]])


class Pose:
    """Result of FK: world-space joints (x, y, depth) and orientation bases."""
    __slots__ = ('J', 'B', 'phi', 'ext')


def fk(p, zs):
    X, Y = p[0], p[1]
    phi, lean, chestb, twist, head = p[2], p[3], p[4], p[5], p[6]
    c, s = math.cos(phi), math.sin(phi)
    M = np.array([[c, 0.0, zs * s], [0.0, 1.0, 0.0], [-s, 0.0, zs * c]])
    off = np.array([X, 0.0, 0.0])
    D = DIM
    L = {}
    pel = np.array([0.0, Y, 0.0])
    Rl = _rz(lean)
    cb = pel + Rl @ np.array([0.0, D['abdomen'], 0.0])
    ac = lean + chestb
    Rc = _rz(ac)
    nb = cb + Rc @ np.array([0.0, D['chest'], 0.0])
    T = _ry(twist)
    piv = np.array([cb[0], 0.0, 0.0])

    def tw(v, k=1.0):
        if k == 1.0:
            return piv + T @ (v - piv)
        return piv + _ry(twist * k) @ (v - piv)

    L['pelvis'] = pel
    L['abdomen'] = (pel + cb) * 0.5
    L['chest_base'] = tw(cb, 0.5)
    L['neck_base'] = tw(nb)
    ah = ac + head
    nt = nb + _rz(ac + 0.45 * head) @ np.array([0.012, D['neck'], 0.0])
    hc = nt + _rz(ah) @ np.array([0.02, 0.105, 0.0])
    L['neck_top'] = tw(nt, 0.9)
    L['head'] = tw(hc, 0.8)
    ext = {}
    for side, zsg, hx, hy, w in (('n', 1.0, p[7], p[8], p[15]), ('f', -1.0, p[9], p[10], p[16])):
        sh = nb + Rc @ np.array([-0.01, -0.045, 0.0])
        sz = D['sh_z'] * zsg
        (ex, ey), (wx, wy), e = ik2(sh[0], sh[1], sh[0] + hx, sh[1] + hy, D['uarm'], D['farm'], -1.0)
        ee = min(max((e - 0.55) / 0.45, 0.0), 1.0)
        fa = math.atan2(wy - ey, wx - ex) + w
        hx2, hy2 = wx + math.cos(fa) * D['hand'], wy + math.sin(fa) * D['hand']
        L['sh_' + side] = tw(np.array([sh[0], sh[1], sz]))
        L['el_' + side] = tw(np.array([ex, ey, sz * (1 - 0.15 * ee) + 0.02 * zsg]))
        L['wr_' + side] = tw(np.array([wx, wy, sz * (1 - 0.55 * ee)]))
        L['hand_' + side] = tw(np.array([hx2, hy2, sz * (1 - 0.6 * ee)]))
        ext['hand_' + side] = e
    for side, zsg, fx, fy, a in (('n', 1.0, p[11], p[12], p[17]), ('f', -1.0, p[13], p[14], p[18])):
        hp = pel + Rl @ np.array([0.0, -0.075, 0.0]) * 0.3 + np.array([0.0, -0.075, 0.0]) * 0.7
        hz = D['hip_z'] * zsg
        (kx, ky), (ax_, ay_), e = ik2(hp[0], hp[1], fx, fy, D['thigh'], D['shin'], 1.0)
        fwd = np.array([math.cos(a), math.sin(a)])
        L['hip_' + side] = np.array([hp[0], hp[1], hz])
        L['knee_' + side] = np.array([kx, ky, hz * 1.05])
        L['ankle_' + side] = np.array([ax_, ay_, hz * 0.95])
        L['heel_' + side] = np.array([ax_ - fwd[0] * 0.055, ay_ - 0.05 - fwd[1] * 0.05, hz * 0.95])
        L['foot_' + side] = np.array([ax_ + fwd[0] * 0.17 + fwd[1] * 0.05, ay_ - 0.055 + fwd[1] * 0.17, hz * 0.95])
        ext['foot_' + side] = e
    J = {k: M @ v + off for k, v in L.items()}
    # orientation bases (world vectors)
    Ttw = _ry(twist)
    Bu = M @ Ttw @ Rc            # upper body
    Bh = M @ _ry(twist * 0.8) @ _rz(ah)  # head
    Bl = M @ Rl                  # pelvis
    P = Pose()
    P.J, P.B, P.phi, P.ext = J, dict(upper=Bu, head=Bh, lower=Bl, body=M), phi, ext
    return P


# ---------------------------------------------------------------- key tracks
class Track:
    """Keyframed pose track. Times are video seconds converted to action time."""

    def __init__(self, name, zs, mirror, K, poses):
        self.name, self.zs, self.mirror, self.K, self.poses = name, zs, mirror, K, poses
        self.keys = []      # (tau, vec, ease)
        self.cur = None

    def key(self, t, pose=None, ease='io', **ov):
        base = dict(self.cur) if self.cur else {}
        if pose is not None:
            base.update(pose if isinstance(pose, dict) else self.poses[pose])
        if 'dx' in ov:
            base['x'] = base.get('x', 0.0) + ov.pop('dx')
        if 'dy' in ov:
            base['y'] = base.get('y', 0.0) + ov.pop('dy')
        base.update(ov)
        self.cur = base
        v = np.zeros(NP)
        for k, i in IDX.items():
            v[i] = base.get(k, 0.0)
        if self.mirror:
            v[IDX['phi']] = math.pi - v[IDX['phi']]
        self.keys.append((self.K(t), v, ease))
        return self

    def finalize(self):
        self.keys.sort(key=lambda k: k[0])
        self.taus = np.array([k[0] for k in self.keys])
        self.vecs = np.array([k[1] for k in self.keys])

    def vec(self, tau):
        ks = self.keys
        i = int(np.searchsorted(self.taus, tau, side='right'))
        if i <= 0:
            return self.vecs[0].copy()
        if i >= len(ks):
            return self.vecs[-1].copy()
        t0, t1 = self.taus[i - 1], self.taus[i]
        if t1 - t0 < 1e-9:
            return self.vecs[i].copy()
        u = ease(ks[i][2], (tau - t0) / (t1 - t0))
        return self.vecs[i - 1] + (self.vecs[i] - self.vecs[i - 1]) * u

    def pose(self, tau):
        return fk(self.vec(tau), self.zs)


# -------------------------------------------------------------- spring chains
class Chain:
    """Verlet rope attached to a body point; used for hair, ribbons, belt ends."""

    def __init__(self, n, seg, anchor_fn, rest_dir, stiff=0.08, damp=0.985, grav=9.8, drag=0.0):
        self.n, self.seg = n, seg
        self.anchor_fn = anchor_fn  # (pose) -> (point3, basis3x3)
        self.rest_dir = np.array(rest_dir, float)
        self.rest_dir /= np.linalg.norm(self.rest_dir)
        self.stiff, self.damp, self.grav, self.drag = stiff, damp, grav, drag


def simulate_chains(chains_by_track, tau_end, dt=1.0 / 360):
    """Deterministic sim over action time. Returns {track: [array(steps,n,3)]} and tau grid."""
    steps = int(math.ceil(tau_end / dt)) + 2
    taus = np.arange(steps) * dt
    out = {}
    for track, chains in chains_by_track.items():
        res = [np.zeros((steps, ch.n, 3), np.float32) for ch in chains]
        st = []
        P0 = track.pose(0.0)
        for ch in chains:
            a, B = ch.anchor_fn(P0)
            d = B @ ch.rest_dir
            pts = np.array([a + d * ch.seg * k for k in range(ch.n)])
            st.append([pts, pts.copy()])
        for si in range(steps):
            P = track.pose(taus[si])
            for ci, ch in enumerate(chains):
                cur, prev = st[ci]
                a, B = ch.anchor_fn(P)
                d = B @ ch.rest_dir
                wind = np.array([0.6 + 0.4 * math.sin(taus[si] * 1.7 + ci), -0.3, 0.0])
                vel = (cur - prev) * ch.damp
                nxt = cur + vel + (np.array([0.0, -ch.grav, 0.0]) + wind) * dt * dt
                nxt[0] = a
                for _ in range(3):
                    for k in range(1, ch.n):
                        # shape memory toward rest direction
                        target = nxt[k - 1] + d * ch.seg
                        nxt[k] += (target - nxt[k]) * ch.stiff
                        v = nxt[k] - nxt[k - 1]
                        ln = np.linalg.norm(v) + 1e-9
                        nxt[k] = nxt[k - 1] + v * (ch.seg / ln)
                nxt[:, 1] = np.maximum(nxt[:, 1], 0.015)
                st[ci] = [nxt, cur]
                res[ci][si] = nxt
        out[track.name] = res
    return taus, out
