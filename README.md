# Procedural Street Fight — 20 s vertical TikTok video, 100% code

Renders a 20-second 1080×1920, 120 fps "2D-realism" fight between two fighters in a
rainy neon city. No external assets and no generative models: every pixel and
every sample comes from Python + numpy + Pillow, encoded with ffmpeg.

## Requirements

Only what was already installed in the build environment:

| Need | Used | Note |
|---|---|---|
| Python ≥ 3.10 | 3.13 | |
| numpy | 2.x | SDF shading, particles, audio DSP |
| Pillow | 12.x | layer resampling, compositing, drawing |
| ffmpeg / ffprobe | 6.1 (libx264, aac) | encoding, muxing, checks |

`pycairo`, `skia`, `scipy`, `numba` and `opencv` were **not** available, so:
vector shapes are rasterised as signed-distance fields in numpy (this gives
anti-aliasing and per-pixel normals for lighting for free); filters (band-pass,
K-weighting) run in the FFT domain; reverb is FFT convolution.

## Run

```bash
python3 render.py --preview              # 540x960, 30 fps, first 3 s -> fight_preview.mp4
python3 render.py                        # full: fight_tiktok.mp4 + fight_tiktok_60fps.mp4
python3 render.py --debug-safe-zones     # overlay TikTok UI safe zones (red = UI, green = safe)
python3 render.py --start 15 --end 17.5 --out slowmo.mp4   # render any time range
python3 render.py --workers 8 --preset slow
```

At the end of each run ffprobe prints codec, profile, size, fps, frame count,
duration and the audio stream.

## Output spec

* `fight_tiktok.mp4`: 1080×1920, 120 fps, 2400 frames, 20.00 s, H.264 High,
  yuv420p, CRF 18, `+faststart`, AAC 192 kbps stereo 48 kHz.
* `fight_tiktok_60fps.mp4`: the same picture through `ffmpeg -vf fps=60`, audio
  copied. TikTok re-encodes uploads, and 120 fps may not survive.
* Frames are piped as raw RGB into ffmpeg's stdin. No images are written to disk.
* The render runs in parallel (fork-based `multiprocessing`, chunks of frames,
  bounded in-flight queue so RAM stays flat) with a progress bar and ETA.
* It is fully deterministic: fixed seed, all randomness from seeded generators,
  and particles/rain/shake are closed-form functions of time. Any worker can
  render any frame or sub-frame identically. This was verified by matching
  per-frame hashes across processes with different `PYTHONHASHSEED`.

## Architecture (`fight/`)

| Module | Role |
|---|---|
| `config.py` | resolution, fps, safe zones, canvas margins, lens, motion-blur settings |
| `timeline.py` | event list (hits, blocks, crash…), **hit-stop** freezes, **slow-mo** ramp; maps video time → action time `K(t)` |
| `rig.py` | skeleton: 2.5D FK (body yaw + upper-body twist, perspective), analytic two-bone **IK** for arms and legs, keyframe tracks with easing (anticipation `in`, follow-through `outback`), Verlet **spring chains** |
| `choreography.py` | pose library (guard, jab, cross, hook, uppercut, body shot, block, slip, kicks, hit reactions, airborne, lying, victory), keyframes for both fighters, shot list / camera tracking |
| `characters.py` | 18 body segments + face details + hair/ribbon/belt chains rendered as soft-unioned tapered capsules; key light, teal/orange rim lights, wet specular, impact lights, bounce light from the street, cloth folds. No outlines |
| `scene.py` | cached layered city (sky, far skyline, mid towers with neon, street facade, alley brick wall + cracked variant), wet-asphalt texture; dolly-camera parallax |
| `renderer.py` | per-frame compositor: layers → mirrored reflections on wet ground → wall → crates → fighters (4-sample **motion blur**, **smear** trails, reflections, contact shadows) → effects → camera roll → post |
| `fx.py` | particles (water, sparks, splinters, planks, bricks, dust, splash rings), breakable crates, rain (3 depth layers, freezes in slow-mo), ground splashes, shockwaves with refraction, speed lines, impact glow, shake, zoom punch, post-processing (teal & orange grade, bloom, vignette, film grain, chromatic aberration, impact frames, fades) |
| `audio.py` | numpy synthesis: rain bed, drone, 128 bpm drum beat, impact thumps with sub-bass accents on the hit frames, whooshes, wood crash, silence drop, reverse swell, slowed monster hit, heartbeat; BS.1770 loudness → **−14 LUFS**, look-ahead limiter (≤ −1 dBTP) |
| `main.py` | CLI, parallel render, ffmpeg pipe, 60 fps export, ffprobe report |

## Timeline

| Time | Beat |
|---|---|
| 0–1 s | **Hook:** POV close-up, fighter A's fist flies into the lens (strong perspective), impact flash, sparks, shockwave, chromatic aberration |
| 1–3 s | Fast pull-back to the wide shot: face-off in the rain, lightning |
| 3–7 s | Exchange: jab/block, cross/slip, hook/block, body shot, low kick/check, elbow/duck, uppercut miss, front kick, jab. Camera angle changes every 0.55–1.1 s (low two-shot, over-shoulder, legs, faces, tilted) |
| 7–11 s | B's charged uppercut launches A upward (camera cranes up), A falls through the frame into a crate stack against a brick wall (planks, splinters, bricks, dust, cracked wall), B walks in, A gets up |
| 11–15 s | Counter: duck + body hook, jab, crouch, jump (camera follows up), 360° spinning kick in the air, landing splash, haymaker slip, wind-up |
| 15–17.5 s | Silence drop, then **15 % slow motion** (~1.5 s): the decisive cross, slow shockwave, frozen raindrops, orbiting camera, heartbeat |
| 17.5–20 s | B flies back and slams into a puddle (big splash, final boom), A's victory pose, camera pulls back and up over the city, fade to dark. The first frame fades in from the same darkness, so the video loops cleanly |

## Tunable parameters

`fight/config.py` (`Settings`, also exposed via the CLI):

* `width`, `height`, `fps`, `t_start`, `t_end`, `seed`
* `mb_samples` (4), `mb_threshold_px`, `shutter`: motion blur
* `grain`, `bloom`, `rain_density`
* `SAFE_TOP/BOTTOM/RIGHT`: TikTok UI zones. The camera anchor sits at the
  centre of the safe area, so the action is framed away from the UI.
* `MARGIN_X/Y`, `MAX_ROLL_DEG`: roll headroom
* `LENS_F`: dolly-lens constant that controls parallax strength

`fight/timeline.py`:

* `EVENTS`: time, kind, power and **hit-stop length** of every impact (in
  30 fps animation frames, `HS_FPS`, i.e. 2–6 frames = 67–200 ms)
* `SLOWMO`: start, full, end and speed (0.15); `rain_speed` (0.02 freezes the drops)
* `SILENCE`, `FADE_IN`, `FADE_OUT`

`fight/choreography.py`: `POSES`, the keyframes in `build_tracks()` and `SHOTS`
(camera keys `(t, (cx, cy, zoom px/m, roll°), ease)`, optional per-shot camera
distance for stronger perspective).

`fight/characters.py`: `MAT` materials (albedo, specular, folds) and light
colours/directions.

`fight/audio.py`: `build_audio(target_lufs=-14)`, drum pattern, BPM and the
sound of each event kind.

## Performance

On 4 CPU cores a 1080×1920 frame takes about 1–2.5 s per worker; frames with
4-sample motion blur are the slowest. Optimisations already in place: the
background is pre-rendered once with mip levels and inherited copy-on-write by
the workers; the distant layers, glow layers and reflections are rendered at
half resolution; SDF shading is vectorised per part bounding box; motion-blur
samples reuse unchanged parts.
