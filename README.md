# «Что будет, если откладывать по 100$ в месяц 20 лет»

2D-анимационный ролик (Remotion + ffmpeg), 1920×1080, 60 fps, ~5:00, озвучка edge-tts `ru-RU-DmitryNeural`,
субтитры слово за словом по таймкодам WordBoundary, плюс 5 вертикальных Shorts 1080×1920.

## Сборка

```bash
npm install
pip install edge-tts numpy
python3 script/calc.py --json src/data/finance.json   # все цифры сложного процента (7% годовых)
python3 pipeline/tts.py                                # озвучка -> public/voice.wav + src/data/timeline.json
python3 pipeline/music.py                              # фоновая музыка (синтезирована кодом, без авторских прав)
npx remotion render src/index.ts Main out/main.mp4
for i in 1 2 3 4 5; do npx remotion render src/index.ts Short$i out/short$i.mp4; done
```

- `script/script.md` — согласованный сценарий; `src/data/script.json` — тот же текст, разбитый на кадры.
- `src/scenes/*` — сцены (SVG-персонажи и инфографика), `src/Subtitles.tsx` — субтитры, `src/Short.tsx` — вертикальная версия.
- В песочнице Remotion использует предустановленный `chrome-headless-shell` (см. `remotion.config.ts`),
  а edge-tts — CA-сертификат прокси (`TTS_CA_BUNDLE`).
