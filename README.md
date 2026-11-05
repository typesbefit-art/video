# video

«Что если бы собаки умели говорить?» — TikTok-ролик (1080×1920, 30 fps) на Remotion.

- `scripts/script.json` — сценарий (реплики рассказчика и собаки).
- `python3 scripts/make_voice.py` — озвучка edge-tts (ru-RU-DmitryNeural: рассказчик −5%, собака +20% / +25Hz), длины через ffprobe → `src/timeline.json`.
- `npm run render` — рендер в `output/talking_dogs.mp4`.
