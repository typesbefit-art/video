"""Global configuration. All pixel values are given for the 1080x1920 master and
scaled automatically for other resolutions (e.g. --preview)."""
from dataclasses import dataclass

BASE_W, BASE_H = 1080, 1920

# TikTok UI safe zones (px at 1080x1920)
SAFE_TOP = 150
SAFE_BOTTOM = 380
SAFE_RIGHT = 140
SAFE_LEFT = 0

# Extra canvas margin so the camera can roll without empty corners
MARGIN_X, MARGIN_Y = 140, 80
MAX_ROLL_DEG = 7.0

# Virtual lens: px-per-metre * camera-distance (dolly model for parallax)
LENS_F = 2880.0

SEED = 1337


@dataclass
class Settings:
    width: int = 1080
    height: int = 1920
    fps: int = 120
    t_start: float = 0.0
    t_end: float = 20.0
    seed: int = SEED
    debug_safe_zones: bool = False
    mb_samples: int = 4          # motion-blur sub-frame samples on fast motion
    mb_threshold_px: float = 5.0  # min limb displacement per shutter to enable MB
    shutter: float = 0.85         # fraction of a frame interval
    grain: float = 1.0
    bloom: float = 1.0
    rain_density: float = 1.0

    @property
    def s(self):
        return self.width / BASE_W

    @property
    def n_frames(self):
        return int(round((self.t_end - self.t_start) * self.fps))

    @property
    def canvas(self):
        s = self.s
        return (int(round((BASE_W + 2 * MARGIN_X) * s)),
                int(round((BASE_H + 2 * MARGIN_Y) * s)))

    @property
    def anchor(self):
        """Canvas point where the camera centre lands = centre of the safe zone."""
        s = self.s
        ax = (SAFE_LEFT + (BASE_W - SAFE_RIGHT - SAFE_LEFT) / 2 + MARGIN_X) * s
        ay = (SAFE_TOP + (BASE_H - SAFE_BOTTOM - SAFE_TOP) / 2 + MARGIN_Y) * s
        return ax, ay
