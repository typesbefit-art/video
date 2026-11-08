"""Video-time -> action-time mapping (hit-stops, slow motion) and the event list.

Choreography is authored in *video* seconds and converted to action time with
K(t), so impacts land exactly on the frame where the hit-stop starts.
"""
import numpy as np

DURATION = 20.0
HS_FPS = 30.0  # hit-stop lengths are counted in classic 30 fps animation frames

SLOWMO = dict(start=15.30, full=15.45, end_full=16.85, end=17.00,
              speed=0.15, rain_speed=0.02)
SILENCE = (15.08, 15.46)      # audio drop before the slow-mo hit
FADE_OUT = (19.05, 20.0)
FADE_IN = (0.0, 0.10)

# kind: hook|hit|heavy|block|crash|final|fall|whoosh|jump|land|step
# att/limb: attacker + joint used as impact point
EVENTS = [
    dict(t=0.42, kind='hook', att='A', limb='hand_n', hs=4, power=1.0),
    dict(t=3.25, kind='block', att='B', limb='hand_f', hs=2, power=0.45),
    dict(t=3.55, kind='whoosh', att='B', limb='hand_n', hs=0, power=0.6),
    dict(t=4.05, kind='block', att='A', limb='hand_f', hs=2, power=0.5),
    dict(t=4.30, kind='hit', att='A', limb='hand_n', hs=3, power=0.65),
    dict(t=4.72, kind='block', att='B', limb='foot_n', hs=2, power=0.5),
    dict(t=5.45, kind='whoosh', att='B', limb='hand_n', hs=0, power=0.6),
    dict(t=5.72, kind='whoosh', att='A', limb='hand_n', hs=0, power=0.5),
    dict(t=6.20, kind='hit', att='B', limb='foot_n', hs=3, power=0.7),
    dict(t=6.62, kind='block', att='A', limb='hand_f', hs=2, power=0.45),
    dict(t=7.45, kind='heavy', att='B', limb='hand_n', hs=6, power=1.0),
    dict(t=8.70, kind='crash', att='A', limb='pelvis', hs=4, power=1.0),
    dict(t=11.40, kind='whoosh', att='B', limb='hand_n', hs=0, power=0.7),
    dict(t=11.66, kind='hit', att='A', limb='hand_n', hs=3, power=0.7),
    dict(t=12.00, kind='hit', att='A', limb='hand_f', hs=3, power=0.6),
    dict(t=12.62, kind='jump', att='A', limb='pelvis', hs=0, power=0.6),
    dict(t=13.30, kind='heavy', att='A', limb='foot_n', hs=5, power=0.9),
    dict(t=13.66, kind='land', att='A', limb='pelvis', hs=0, power=0.6),
    dict(t=14.40, kind='whoosh', att='B', limb='hand_n', hs=0, power=0.8),
    dict(t=15.75, kind='final', att='A', limb='hand_n', hs=0, power=1.3),
    dict(t=17.65, kind='fall', att='B', limb='pelvis', hs=3, power=1.0),
]
for i, e in enumerate(EVENTS):
    e['id'] = i
STRIKES = [e for e in EVENTS if e['kind'] in ('hook', 'hit', 'heavy', 'block', 'final')]


def _smooth(x):
    x = np.clip(x, 0.0, 1.0)
    return x * x * (3 - 2 * x)


class Timeline:
    def __init__(self, events=EVENTS, dt=1.0 / 4800):
        self.events = events
        ts = np.arange(0.0, DURATION + 2.0, dt)
        s = self._speed(ts, SLOWMO['speed'])
        r = self._speed(ts, SLOWMO['rain_speed'])
        self.ts = ts
        self.tau_arr = np.concatenate([[0.0], np.cumsum((s[1:] + s[:-1]) * 0.5 * dt)])
        self.rain_arr = np.concatenate([[0.0], np.cumsum((r[1:] + r[:-1]) * 0.5 * dt)])

    def _speed(self, ts, slow):
        sm = SLOWMO
        s = np.ones_like(ts)
        a = _smooth((ts - sm['start']) / (sm['full'] - sm['start']))
        b = _smooth((ts - sm['end_full']) / (sm['end'] - sm['end_full']))
        k = a * (1 - b)
        s = s * (1 - k) + slow * k
        for e in self.events:
            if e['hs'] > 0:
                t0, t1 = e['t'], e['t'] + e['hs'] / HS_FPS
                s[(ts >= t0) & (ts < t1)] = 0.0
        return s

    def tau(self, t):
        return np.interp(t, self.ts, self.tau_arr)

    def rain(self, t):
        return np.interp(t, self.ts, self.rain_arr)

    def hitstop_active(self, t):
        for e in self.events:
            if e['hs'] > 0 and e['t'] <= t < e['t'] + e['hs'] / HS_FPS:
                return True
        return False


TL = Timeline()


def K(t):
    """Video seconds -> action seconds (use when authoring keyframes)."""
    return float(TL.tau(t))
