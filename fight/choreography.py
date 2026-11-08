"""Fight choreography: pose library, keyframes for both fighters, camera shots.

All times are VIDEO seconds; Track.key converts them with K() so hit-stops and
slow motion are respected automatically. Poses are authored for fighter A
(facing +x); fighter B uses the same library mirrored.
"""
import math
import numpy as np
from .rig import Track, Chain, simulate_chains, ease
from .timeline import K, TL, EVENTS, SLOWMO

PHI0 = -0.45  # 3/4 view: chest turned toward camera

GUARD = dict(y=0.92, phi=PHI0, lean=0.10, chestb=0.06, twist=0.30, head=0.12,
             hnx=0.17, hny=0.13, hfx=0.30, hfy=0.10,
             fnx=-0.33, fny=0.075, ffx=0.30, ffy=0.075, wn=0.35, wf=0.25, an=0.0, af=0.0)


def P(**kw):
    d = dict(GUARD)
    d.update(kw)
    return d


POSES = {
    'guard': P(),
    'guard_b': P(y=0.89, lean=0.16, head=0.16, hfx=0.28, hfy=0.12),
    'guard_loose': P(y=0.94, lean=0.02, head=0.0, hnx=0.15, hny=0.02, hfx=0.24, hfy=0.0),
    'jab': P(hfx=0.60, hfy=0.09, twist=0.55, lean=0.17, wf=0.0, head=0.1),
    'jab_back': P(hfx=0.22, hfy=0.12),
    'cross_wind': P(twist=0.55, hnx=0.06, hny=0.10, lean=0.12, y=0.90),
    'cross': P(hnx=0.61, hny=0.07, twist=-0.32, lean=0.24, hfx=0.16, hfy=0.15,
               ffx=0.34, fnx=-0.30, fny=0.10, an=-0.35, wn=0.0),
    'hook_wind': P(hfx=0.16, hfy=0.02, twist=0.62, lean=0.14),
    'hook': P(hfx=0.50, hfy=0.13, twist=-0.18, lean=0.18, wf=0.1),
    'upper_dip': P(y=0.83, lean=0.24, hnx=0.10, hny=-0.20, twist=0.20, head=0.2),
    'uppercut': P(y=0.98, lean=0.0, hnx=0.30, hny=0.44, twist=-0.45, head=-0.05,
                  an=-0.45, fny=0.11, wn=0.6),
    'body_dip': P(y=0.85, lean=0.30, hnx=0.12, hny=-0.05, twist=0.35),
    'body_shot': P(y=0.81, lean=0.40, hnx=0.53, hny=-0.24, twist=-0.35, head=0.22, wn=0.1),
    'block': P(hnx=0.17, hny=0.27, hfx=0.24, hfy=0.25, head=0.32, lean=0.07, twist=0.12,
               wn=1.1, wf=1.1),
    'slip': P(y=0.73, lean=0.56, head=0.10, hnx=0.15, hny=0.10, hfx=0.24, hfy=0.12),
    'lean_back': P(lean=-0.24, head=-0.14, y=0.93, ffx=0.34, fnx=-0.36),
    'kick_chamber': P(y=0.95, lean=-0.06, fnx=0.24, fny=0.62, an=0.35, ffx=0.12, twist=0.1),
    'front_kick': P(y=0.97, lean=-0.26, fnx=0.82, fny=0.84, an=1.0, ffx=0.10, af=-0.1,
                    hnx=0.1, hny=0.15, hfx=0.25, hfy=0.18),
    'low_kick': P(y=0.93, lean=0.02, fnx=0.62, fny=0.33, an=0.1, twist=-0.25, ffx=0.18),
    'check': P(ffx=0.26, ffy=0.45, af=0.25, y=0.95, lean=0.05),
    'elbow_wind': P(twist=0.55, hnx=0.02, hny=0.08, lean=0.15),
    'elbow': P(twist=-0.60, hnx=0.26, hny=0.13, lean=0.30, ffx=0.36, fnx=-0.25, an=-0.3,
               fny=0.10, wn=-1.4),
    'hit_head': P(head=-0.60, lean=-0.32, chestb=-0.15, hnx=0.08, hny=-0.02, hfx=0.18,
                  hfy=-0.04, twist=0.1),
    'hit_body': P(y=0.83, lean=0.58, head=0.28, hnx=0.13, hny=-0.08, hfx=0.2, hfy=-0.05),
    'crouch': P(y=0.66, lean=0.40, head=0.1, hnx=-0.22, hny=-0.28, hfx=-0.08, hfy=-0.32,
                fnx=-0.25, ffx=0.25),
    'kneel': P(y=0.56, lean=0.42, head=0.15, fnx=-0.48, fny=0.08, an=-1.2,
               ffx=0.30, hnx=0.05, hny=-0.15, hfx=0.30, hfy=-0.38),
    'victory': P(y=0.99, lean=-0.03, chestb=-0.02, head=-0.20, twist=0.0, phi=-0.85,
                 hnx=0.06, hny=0.56, hfx=0.04, hfy=-0.50, fnx=-0.17, ffx=0.20, wn=0.0, wf=0.0),
}


def air(y, **kw):
    """Airborne pose helper (ankle heights follow the pelvis)."""
    d = dict(GUARD)
    d.update(dict(y=y, fnx=-0.10, fny=y - 0.62, ffx=0.20, ffy=y - 0.55, an=-0.3, af=-0.2))
    d.update(kw)
    return d


def lying(x, y=0.17, **kw):
    d = dict(GUARD)
    d.update(dict(x=x, y=y, lean=-1.47, chestb=0.0, head=0.25, twist=0.0,
                  fnx=0.86, fny=0.085, ffx=0.62, ffy=0.20, an=1.2, af=0.9,
                  hnx=0.18, hny=-0.12, hfx=-0.22, hfy=0.02, wn=0.0, wf=0.0))
    d.update(kw)
    return d


def walk(tr, t0, t1, x0, x1, pose='guard_loose', steps=4):
    """Generate walking keys with alternating feet."""
    for i in range(steps + 1):
        u = i / steps
        t = t0 + (t1 - t0) * u
        x = x0 + (x1 - x0) * u
        sgn = 1 if i % 2 == 0 else -1
        tr.key(t, pose, x=x, y=POSES[pose]['y'] + (0.0 if i in (0, steps) else -0.02),
               fnx=-0.28 * sgn - 0.02, ffx=0.28 * sgn + 0.02)
        if i < steps:  # passing position, lifted foot
            tm = t + (t1 - t0) / steps * 0.5
            xm = x + (x1 - x0) / steps * 0.5
            lift = dict(fny=0.18) if sgn > 0 else dict(ffy=0.18)
            tr.key(tm, pose, x=xm, y=POSES[pose]['y'] + 0.025, fnx=0.0, ffx=0.0, **lift)


def build_tracks():
    A = Track('A', 1.0, False, K, POSES)
    B = Track('B', -1.0, True, K, POSES)

    # ------------------------------------------------ 0-1 s : HOOK (POV punch)
    A.key(0.00, 'guard', x=-0.9, phi=-1.22, twist=0.40, hnx=-0.02, hny=0.05)
    A.key(0.22, 'cross_wind', phi=-1.22, twist=0.62, hnx=-0.10, hny=0.06, lean=0.06)
    A.key(0.42, 'cross', phi=-1.25, ease='in', hnx=0.60, hny=0.12, twist=-0.28)
    A.key(0.56, 'cross', phi=-1.25, hnx=0.60, hny=0.12, twist=-0.28)
    A.key(0.80, 'guard', phi=-1.15, ease='out', twist=0.3)
    A.key(0.995, 'guard', phi=-1.15)
    B.key(0.00, 'guard', x=0.9)

    # ------------------------------------------------ 1-3 s : face-off in rain
    A.key(1.00, 'guard', x=-0.62, phi=PHI0)
    B.key(1.00, 'guard', x=0.62)
    for i, t in enumerate(np.arange(1.35, 3.0, 0.38)):
        A.key(float(t), 'guard_b' if i % 2 == 0 else 'guard', dx=0.035 if i % 2 else 0.0)
    for i, t in enumerate(np.arange(1.2, 3.0, 0.42)):
        B.key(float(t), 'guard' if i % 2 == 0 else 'guard_b', dx=-0.03 if i % 2 else 0.0)
    A.key(3.0, 'guard', x=-0.46)
    B.key(3.0, 'guard', x=0.48)

    # ------------------------------------------------ 3-7 s : exchange
    # B jab -> A block
    B.key(3.12, 'jab_back', ease='io')
    B.key(3.25, 'jab', ease='in', dx=-0.06)
    B.key(3.39, 'guard', ease='out')
    A.key(3.12, 'guard')
    A.key(3.23, 'block', ease='out2')
    A.key(3.40, 'block')
    # B cross -> A slips
    B.key(3.46, 'cross_wind')
    B.key(3.55, 'cross', ease='in', dx=-0.05)
    B.key(3.72, 'guard', ease='out', dx=0.06)
    A.key(3.54, 'slip', ease='out2')
    A.key(3.72, 'guard', ease='io')
    # A hook -> B block ; A body shot -> B hit
    A.key(3.90, 'hook_wind')
    A.key(4.05, 'hook', ease='in', dx=0.05)
    A.key(4.16, 'body_dip', ease='out')
    A.key(4.30, 'body_shot', ease='in', dx=0.04)
    A.key(4.48, 'guard', ease='out', dx=-0.06)
    B.key(3.92, 'guard')
    B.key(4.03, 'block', ease='out2')
    B.key(4.18, 'block')
    B.key(4.30, 'guard_b')
    B.key(4.48, 'hit_body', ease='out', dx=0.10)
    B.key(4.60, 'guard', ease='io')
    # B low kick -> A checks
    B.key(4.63, 'kick_chamber', fnx=0.30, fny=0.30)
    B.key(4.72, 'low_kick', ease='in')
    B.key(4.90, 'guard', ease='out')
    A.key(4.60, 'guard')
    A.key(4.71, 'check', ease='out2')
    A.key(4.86, 'check')
    A.key(5.00, 'guard')
    # B elbow -> A ducks ; A uppercut -> B leans back
    B.key(5.30, 'elbow_wind', dx=-0.03)
    B.key(5.45, 'elbow', ease='in', dx=-0.08)
    B.key(5.60, 'guard_b', ease='out')
    B.key(5.72, 'lean_back', ease='out2')
    B.key(5.86, 'guard')
    A.key(5.32, 'guard')
    A.key(5.45, 'slip', ease='out2', y=0.70)
    A.key(5.58, 'upper_dip')
    A.key(5.72, 'uppercut', ease='in')
    A.key(5.90, 'guard', ease='out')
    # B front kick -> A body
    B.key(6.04, 'kick_chamber')
    B.key(6.20, 'front_kick', ease='in')
    B.key(6.38, 'kick_chamber', ease='out')
    B.key(6.52, 'guard', ease='io')
    A.key(6.06, 'guard')
    A.key(6.20, 'guard')
    A.key(6.40, 'hit_body', ease='out', dx=-0.20)
    A.key(6.52, 'guard', ease='io')
    # A jab -> B block
    A.key(6.62, 'jab', ease='in', dx=0.06)
    A.key(6.78, 'guard', ease='out')
    B.key(6.60, 'block', ease='out2')
    B.key(6.75, 'block')
    B.key(6.90, 'guard')

    # ------------------------------------------------ 7-11 s : the big hit
    B.key(7.05, 'guard', dx=-0.05)
    B.key(7.20, 'upper_dip', dx=-0.10)
    B.key(7.33, 'upper_dip', y=0.80, twist=0.38, lean=0.30, dx=-0.08)
    B.key(7.45, 'uppercut', ease='in', dx=-0.14)
    B.key(7.70, 'uppercut', ease='outback', hny=0.52, y=1.0)
    B.key(8.10, 'guard_loose', ease='io')
    A.key(7.10, 'guard')
    A.key(7.30, 'jab_back', dx=0.04)
    A.key(7.45, 'guard', head=0.05, hfx=0.4)
    # launched upward and back, falls DOWN through the frame into the crates
    A.key(7.66, air(1.25, x=-0.72, lean=-0.55, head=-0.75, chestb=-0.2,
                    hnx=-0.05, hny=0.32, hfx=0.18, hfy=0.42), ease='out2')
    A.key(8.06, air(3.35, x=-2.15, lean=-1.45, head=-0.4, hnx=-0.25, hny=0.40, hfx=0.10,
                    hfy=0.50, fnx=0.25, fny=3.35 - 0.45, ffx=0.40, ffy=3.35 - 0.62),
          ease='out2')
    A.key(8.70, air(1.30, x=-3.72, lean=-1.75, head=-0.2, hnx=-0.35, hny=0.35, hfx=0.2,
                    hfy=0.45, fnx=0.55, fny=1.30 + 0.05, ffx=0.65, ffy=1.30 - 0.15),
          ease='in2')
    A.key(8.84, air(1.30, x=-3.72, lean=-1.75, head=-0.2, hnx=-0.35, hny=0.35, hfx=0.2,
                    hfy=0.45, fnx=0.55, fny=1.35, ffx=0.65, ffy=1.15))
    A.key(9.05, lying(-3.90, y=0.17), ease='in2')
    A.key(9.22, lying(-3.92, y=0.24, head=0.05), ease='out2')
    A.key(9.40, lying(-3.93, y=0.17), ease='in2')
    A.key(9.90, lying(-3.93, y=0.175, head=0.35, hfx=-0.1, hfy=0.1))
    A.key(10.20, lying(-3.93, y=0.18, head=0.5, hnx=0.25, hny=-0.25))
    A.key(10.50, 'kneel', x=-3.75, phi=PHI0, ease='io')
    A.key(10.85, 'guard_b', x=-3.45, ease='out')
    A.key(11.00, 'guard', x=-3.40)
    walk(B, 8.85, 10.55, 0.05, -2.30, steps=4)
    B.key(10.80, 'guard', x=-2.32)

    # ------------------------------------------------ 11-15 s : counter-attack
    B.key(11.18, 'cross_wind', x=-2.36)
    B.key(11.40, 'cross', ease='in', x=-2.62)
    B.key(11.56, 'cross', x=-2.64, hnx=0.5)
    B.key(11.66, 'guard_b', x=-2.62)
    B.key(11.85, 'hit_body', ease='out', x=-2.46)
    B.key(12.00, 'guard_loose', x=-2.44)
    B.key(12.25, 'hit_head', ease='out', x=-2.20)
    B.key(12.55, 'guard_loose', x=-2.10)
    B.key(13.10, 'guard', x=-2.08)
    B.key(13.30, 'guard_b', x=-2.08)
    B.key(13.62, 'hit_head', ease='out', x=-1.72, twist=-0.4, lean=-0.4)
    B.key(13.95, 'guard_loose', x=-1.62, ease='io')
    B.key(14.22, 'cross_wind', x=-1.62, twist=0.75)
    B.key(14.40, 'cross', ease='in', x=-1.85, hny=0.18)
    B.key(14.62, 'slip', x=-1.90, lean=0.45, y=0.82, ease='out')
    B.key(15.00, 'guard_loose', x=-1.72, ease='io')
    B.key(15.40, 'guard_loose', x=-1.66, head=0.05)
    B.key(15.75, 'guard_loose', x=-1.65, head=0.08, ease='io')
    # decisive hit: head snaps in slow motion, then flies back and falls
    B.key(16.40, P(x=-1.55, y=0.98, head=-0.75, lean=-0.30, chestb=-0.2, hnx=0.05,
                   hny=0.05, hfx=0.25, hfy=0.15, fny=0.10, ffy=0.09), ease='out2')
    B.key(17.00, air(1.10, x=-1.32, lean=-0.55, head=-0.85, chestb=-0.2, hnx=-0.05, hny=0.35,
                     hfx=0.25, hfy=0.40), ease='io')
    B.key(17.28, air(1.30, x=-0.20, lean=-1.05, head=-0.6, hnx=-0.2, hny=0.42, hfx=0.1,
                     hfy=0.48, fnx=0.35, fny=1.30 - 0.5), ease='out2')
    B.key(17.65, lying(0.85, y=0.17, head=-0.2, hnx=-0.1, hny=0.25, hfx=-0.3, hfy=0.2),
          ease='in2')
    B.key(17.80, lying(1.02, y=0.23, head=0.05), ease='out2')
    B.key(18.05, lying(1.18, y=0.17, head=0.15), ease='out')
    B.key(20.0, lying(1.20, y=0.17, head=0.2))

    A.key(11.18, 'guard', x=-3.40)
    A.key(11.40, 'slip', ease='out2', x=-3.36)
    A.key(11.52, 'body_dip', x=-3.30)
    A.key(11.66, 'body_shot', ease='in', x=-3.20)
    A.key(11.86, 'guard', ease='out', x=-3.15)
    A.key(12.00, 'jab', ease='in', x=-3.05)
    A.key(12.16, 'guard', ease='out', x=-3.0)
    A.key(12.40, 'crouch', x=-2.98)
    A.key(12.62, air(1.06, x=-2.92, lean=0.15, hnx=0.1, hny=0.3, hfx=0.25, hfy=0.35,
                     fnx=-0.15, fny=0.12, ffx=0.05, ffy=0.15, an=-0.9, af=-0.9), ease='in')
    A.key(12.86, air(1.80, x=-2.82, lean=0.05, hnx=0.05, hny=0.15, hfx=0.2, hfy=0.2,
                     fnx=0.15, fny=1.80 - 0.40, ffx=0.20, ffy=1.80 - 0.45), ease='out2')
    A.key(13.08, air(1.95, x=-2.78, phi=PHI0 - math.pi, lean=0.25, twist=0.0,
                     fnx=-0.2, fny=1.95 - 0.35, ffx=0.1, ffy=1.95 - 0.5), ease='io')
    A.key(13.30, air(1.86, x=-2.76, phi=PHI0 - 2 * math.pi, lean=-0.35, twist=0.2,
                     fnx=0.80, fny=1.86 - 0.02, an=0.4, ffx=-0.05, ffy=1.86 - 0.55,
                     hnx=-0.1, hny=0.1, hfx=0.2, hfy=0.15), ease='in')
    A.key(13.48, air(1.70, x=-2.72, phi=PHI0 - 2 * math.pi, lean=-0.2,
                     fnx=0.45, fny=1.70 - 0.25, ffx=0.0, ffy=1.70 - 0.6), ease='out')
    A.key(13.66, 'crouch', x=-2.66, phi=PHI0 - 2 * math.pi, ease='in2', y=0.74)
    A.key(13.90, 'guard', x=-2.62, phi=PHI0 - 2 * math.pi, ease='out')
    A.key(14.28, 'guard', x=-2.58, phi=PHI0 - 2 * math.pi)
    A.key(14.42, 'lean_back', ease='out2', x=-2.64, phi=PHI0 - 2 * math.pi)
    A.key(14.62, 'guard', ease='io', x=-2.58, phi=PHI0 - 2 * math.pi)
    A.key(14.95, 'cross_wind', x=-2.50, phi=PHI0 - 2 * math.pi, twist=0.75, hnx=-0.02)
    A.key(15.30, 'cross_wind', x=-2.48, phi=PHI0 - 2 * math.pi, twist=0.85, hnx=-0.08,
          y=0.88, lean=0.10)
    A.key(15.75, 'cross', ease='in', x=-2.42, phi=PHI0 - 2 * math.pi, hnx=0.62, hny=0.10)
    A.key(16.60, 'cross', ease='out', x=-2.36, phi=PHI0 - 2 * math.pi, hnx=0.62, hny=0.13,
          twist=-0.42, lean=0.28)
    A.key(17.40, 'guard', x=-2.30, phi=PHI0 - 2 * math.pi, ease='io')
    A.key(17.90, 'guard_loose', x=-2.28, phi=PHI0 - 2 * math.pi)
    A.key(18.25, 'guard_loose', x=-2.28, phi=PHI0 - 2 * math.pi, y=0.97)
    A.key(18.85, 'victory', x=-2.28, phi=-0.85 - 2 * math.pi, ease='out')
    A.key(19.50, 'victory', x=-2.28, phi=-0.85 - 2 * math.pi, hny=0.58, y=0.995)
    A.key(20.0, 'victory', x=-2.28, phi=-0.85 - 2 * math.pi, hny=0.56)
    A.finalize()
    B.finalize()
    return A, B


# ------------------------------------------------------------ secondary motion
def head_pt(local):
    local = np.array(local, float)

    def fn(P):
        return P.J['head'] + P.B['head'] @ local, P.B['head']
    return fn


def pelvis_pt(local):
    local = np.array(local, float)

    def fn(P):
        return P.J['pelvis'] + P.B['lower'] @ local, P.B['lower']
    return fn


def build_chains(A, B):
    chA = [
        Chain(7, 0.055, head_pt([-0.105, 0.035, 0.02]), [-1.0, -0.25, 0.15], stiff=0.04),
        Chain(6, 0.055, head_pt([-0.105, 0.030, -0.02]), [-1.0, -0.45, -0.15], stiff=0.05),
        Chain(4, 0.055, pelvis_pt([0.10, 0.06, 0.06]), [0.15, -1.0, 0.0], stiff=0.03),
        Chain(4, 0.05, pelvis_pt([0.10, 0.06, 0.02]), [0.05, -1.0, 0.0], stiff=0.03),
    ]
    chB = [
        Chain(8, 0.052, head_pt([-0.10, 0.06, 0.0]), [-0.55, -1.0, 0.0], stiff=0.06),
        Chain(4, 0.05, pelvis_pt([0.10, 0.06, 0.05]), [0.1, -1.0, 0.0], stiff=0.03),
    ]
    return {A: chA, B: chB}


class Choreo:
    def __init__(self):
        self.A, self.B = build_tracks()
        self.tracks = {'A': self.A, 'B': self.B}
        tau_end = float(TL.tau(20.5))
        self.chains = build_chains(self.A, self.B)
        self.chain_taus, self.chain_states = simulate_chains(self.chains, tau_end)
        self.events = [dict(e) for e in EVENTS]
        for e in self.events:
            tr = self.tracks[e['att']]
            Pz = tr.pose(K(e['t']))
            j = e['limb']
            e['pos'] = Pz.J[j].copy()
            e['tau'] = K(e['t'])

    def chain_pts(self, name, tau):
        ts = self.chain_taus
        f = np.clip(tau / (ts[1] - ts[0]), 0, len(ts) - 2)
        i = int(f)
        a = f - i
        return [st[i] * (1 - a) + st[i + 1] * a for st in self.chain_states[name]]


# ------------------------------------------------------------------- camera
def _kf(t, keys):
    """keys: [(t, (cx, cy, zoom, roll_deg), ease)] -> interpolated tuple."""
    if t <= keys[0][0]:
        return keys[0][1]
    for (t0, v0, _), (t1, v1, e) in zip(keys, keys[1:]):
        if t <= t1:
            u = ease(e, (t - t0) / (t1 - t0))
            return tuple(a + (b - a) * u for a, b in zip(v0, v1))
    return keys[-1][1]


def _expo_out(u):
    u = min(max(u, 0.0), 1.0)
    return 1 - 2 ** (-9 * u)


SHOTS = [  # (t0, t1, keys, D-override)
    (0.0, 1.0, [(0.0, (-0.66, 1.46, 640, 1.5), 'io'), (0.42, (-0.57, 1.48, 700, 0.0), 'in'),
                (1.0, (-0.58, 1.48, 760, -2.0), 'out')], 0.76),
    (1.0, 3.0, None, None),  # special pull-back
    (3.0, 3.8, [(3.0, (0.0, 1.18, 430, -3.0), 'io'), (3.8, (-0.05, 1.22, 480, -2.0), 'io')], None),
    (3.8, 4.5, [(3.8, (0.12, 1.36, 600, 2.5), 'io'), (4.5, (0.18, 1.32, 650, 1.5), 'io')], 3.2),
    (4.5, 5.2, [(4.5, (0.02, 0.62, 640, 0.0), 'io'), (5.2, (-0.02, 0.66, 700, -1.5), 'io')], None),
    (5.2, 5.9, [(5.2, (0.0, 1.50, 820, -4.0), 'io'), (5.9, (0.05, 1.45, 900, -1.5), 'io')], 2.6),
    (5.9, 6.45, [(5.9, (-0.12, 1.18, 450, 5.0), 'io'), (6.45, (-0.15, 1.2, 480, 4.0), 'io')], None),
    (6.45, 7.0, [(6.45, (0.05, 1.42, 640, -2.0), 'io'), (7.0, (0.02, 1.42, 680, -3.0), 'io')], 3.0),
    (7.0, 7.62, [(7.0, (0.12, 1.42, 700, -2.0), 'io'), (7.45, (0.02, 1.45, 830, -3.5), 'in2'),
                 (7.62, (0.0, 1.45, 840, -3.5), 'io')], 2.6),
    (7.62, 9.05, 'trackA', None),
    (9.05, 9.6, [(9.05, (-2.65, 1.30, 390, 1.0), 'io'), (9.6, (-2.55, 1.25, 410, 0.0), 'io')], None),
    (9.6, 10.2, 'closeA', 2.2),
    (10.2, 11.0, [(10.2, (-3.25, 0.95, 480, 3.0), 'io'), (11.0, (-3.0, 1.22, 470, 1.0), 'io')], None),
    (11.0, 11.9, [(11.0, (-3.0, 1.22, 430, -3.0), 'io'), (11.9, (-2.88, 1.25, 480, -1.0), 'io')], None),
    (11.9, 12.38, [(11.9, (-2.78, 1.45, 700, 2.0), 'io'), (12.38, (-2.72, 1.42, 760, 3.0), 'io')], 3.0),
    (12.38, 13.62, 'jumpA', None),
    (13.62, 14.75, [(13.62, (-2.22, 1.20, 430, 2.0), 'io'), (14.75, (-2.15, 1.25, 480, -1.0), 'io')], None),
    (14.75, 15.42, [(14.75, (-2.30, 1.50, 760, 0.0), 'io'), (15.42, (-2.22, 1.52, 900, -2.0), 'in2')], 2.4),
    (15.42, 17.0, [(15.42, (-2.20, 1.50, 720, 6.0), 'io'), (17.0, (-1.80, 1.45, 840, -5.0), 'io')], 2.8),
    (17.0, 18.25, 'trackB', None),
    (18.25, 20.0, [(18.25, (-1.75, 1.40, 560, 0.0), 'io'), (20.0, (-1.30, 2.65, 270, 0.0), 'io')], None),
]
CUTS = [s[0] for s in SHOTS[1:]]


def shot_index(t):
    for i, s in enumerate(SHOTS):
        if s[0] <= t < s[1]:
            return i
    return len(SHOTS) - 1


def camera(t, ch):
    """Returns dict(cx, cy, zoom, roll(rad), D) before shake/zoom-punch."""
    i = shot_index(t)
    t0, t1, keys, Dov = SHOTS[i]
    if keys is None:  # 1-3 s fast pull-back to the wide shot
        u = _expo_out((t - 1.0) / 0.75)
        a = (0.0, 1.56, 1150.0, 4.0)
        b = (-0.10, 2.05, 270.0, 0.0)
        v = tuple(x + (y - x) * u for x, y in zip(a, b))
        w = ease('io', (t - 1.75) / 1.25)
        c = (-0.05, 1.80, 340.0, -1.0)
        if t > 1.75:
            v = tuple(x + (y - x) * w for x, y in zip(b, c))
        cx, cy, z, r = v
    elif keys == 'trackA':
        P = ch.A.pose(TL.tau(t - 0.05))
        p = P.J['pelvis']
        u = ease('io', (t - 7.62) / 0.25)
        cx = 0.0 + (p[0] + 0.25 - 0.0) * u
        cy = 1.45 + (p[1] + 0.25 - 1.45) * u
        z = 840 + (430 - 840) * ease('out', (t - 7.62) / 0.3)
        r = -3.5 + 7.0 * ease('io', (t - 7.7) / 1.0)
    elif keys == 'closeA':
        P = ch.A.pose(TL.tau(t))
        h = P.J['head']
        cx, cy = h[0] + 0.32, 0.42 + (t - 9.6) * 0.05
        z = 780 + (t - 9.6) * 110
        r = -2.0
    elif keys == 'jumpA':
        P = ch.A.pose(TL.tau(t - 0.04))
        p = P.J['pelvis']
        cx = -2.62 + (p[0] + 0.30 + 2.62) * 0.6
        cy = max(1.25, p[1] + 0.30)
        z = 470 + 70 * ease('io', (t - 12.38) / 0.8)
        r = -5.0 * ease('io', (t - 12.7) / 0.6)
    elif keys == 'trackB':
        P = ch.B.pose(TL.tau(t - 0.06))
        p = P.J['pelvis']
        u = ease('io', (t - 17.0) / 0.5)
        cx = -1.9 + (p[0] - 0.6 + 1.9) * u
        cy = 1.15
        z = 520 + (400 - 520) * ease('out', (t - 17.0) / 0.6)
        r = -5.0 + 5.0 * ease('io', (t - 17.0) / 0.8)
    else:
        cx, cy, z, r = _kf(t, keys)
    D = Dov
    return dict(cx=cx, cy=cy, zoom=z, roll=math.radians(r), D=D, shot=i)
