# video

## Forest survival — TikTok (Remotion)

1080×1920, 30 fps. Result: `output/forest_survival.mp4`.

- `scripts/script.json` — scenario (voiceover + subtitle text per scene).
- `scripts/tts.py` — edge-tts voiceover (`ru-RU-SvetlanaNeural`, rate −5%), one mp3 per scene in `public/voice/`;
  measures each with ffprobe and writes `src/timeline.json` (scene length = voice + 0.4 s, word timings for subtitles).
- `scripts/ambient.sh` — soft low ambient pad via ffmpeg (used when `assets/music.mp3` is absent).
- `scripts/build.sh` — whole pipeline: voiceover → music → render.

```bash
npm install
pip install edge-tts
scripts/build.sh
```

Music plays at ~12% volume and ducks to ~6% under the voice.
