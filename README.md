# Тут все оттуда

Мультфильм примерно на 45 секунд в одном файле `index.html`: SVG + CSS-анимации, озвучка через Web Speech API (ru-RU). Внешних библиотек нет.

Откройте `index.html` в браузере (лучше Chrome или Edge с русским голосом) и нажмите «▶ Старт». Пауза ставится кнопкой или пробелом.

Параметры для отладки: `?mute=1` (без звука), `?speed=6` (ускорение, звук выключается), `?scene=5` (начать с 5-й сцены).

## Видео

Готовая запись лежит в `tut-vse-ottuda.mp4`: 1280×720, 25 кадров/с. Озвучка сделана нейронным синтезатором Piper: рассказчик говорит голосом `ru_RU-ruslan-medium`, продавщица — голосом `ru-irinia-medium` с чуть поднятым тоном.

Как пересобрать. Нужны Playwright с Chromium, ffmpeg и `pip install piper-tts`. Голоса берутся из релизов на GitHub: [k2-fsa/sherpa-onnx, tts-models](https://github.com/k2-fsa/sherpa-onnx/releases/tag/tts-models) (`vits-piper-ru_RU-ruslan-medium.tar.bz2`, там же dmitri и denis) и [rhasspy/piper v0.0.2](https://github.com/rhasspy/piper/releases/tag/v0.0.2) (`voice-ru-irinia-medium.tar.gz`).

```
PIPER_MODEL=путь/к/ru_RU-ruslan-medium.onnx \
PIPER_MODEL_ALT=путь/к/ru-irinia-medium.onnx \
node tools/record-video.js /tmp/rec tut-vse-ottuda.mp4
```

Без `PIPER_MODEL` скрипт озвучивает через espeak-ng. Он берёт фразы из массива `scenes`, синтезирует их, записывает мультфильм из браузера и сводит видео со звуком через ffmpeg.
