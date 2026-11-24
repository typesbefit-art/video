# Генератор вертикальных видео-историй

Безлицевое видео «смешная история от первого лица» для TikTok / Shorts / Reels:
озвучка edge-tts, субтитры с подсветкой слов, бит, звуковые эффекты.
На выходе MP4 1080x1920, H.264 + AAC.

## Установка
```bash
pip install -r requirements.txt     # edge-tts, numpy, Pillow, certifi
# + ffmpeg в PATH (apt install ffmpeg / brew install ffmpeg / ffmpeg.org)
```

## Запуск
```bash
python generate.py story.txt              # -> output.mp4, 30 fps
python generate.py story.txt --fps 60     # 60 fps
python generate.py story.txt --preview 15 # -> preview.mp4, первые 15 секунд
python generate.py story.txt -o my.mp4 --seed 42
```

## Как менять
- **История**: правьте `story.txt`. Первая строка — заголовок, дальше текст.
  Финальная шутка — последнее предложение (если оно короче 4 слов, то два последних).
  Явно задать шутку можно, отделив её строкой `---`.
  Темп речи сам подстраивается, чтобы ролик был 45–60 с.
- **Голос**: `--voice ru-RU-DmitryNeural --rate +15% --pitch +0Hz`
  или константы `VOICE`, `RATE`, `PITCH` в начале `generate.py`.
  Список голосов: `edge-tts --list-voices | grep ru-RU`.
- **Цвета**: в блоке «НАСТРОЙКИ» в начале `generate.py`:
  `BG_COLOR_A`/`BG_COLOR_B` (градиент), `SHAPE_COLORS` (фигуры),
  `SUB_COLOR`/`SUB_HIGHLIGHT` (субтитры), `END_CARD_COLOR`, `END_CARD_TEXT`.
  Там же размеры шрифтов, паузы, громкость бита (`MUSIC_DB`), темп бита (`BPM`).
- **Фон**: положите `.mp4` / `.mov` в папку `bg/` — будет взят случайный файл,
  обрезан/зациклен под длину ролика, вырезан центр 9:16 и чуть затемнён.
  Если папка пуста — генерируется анимированный градиент с фигурами.
- **Шрифт**: Inter ExtraBold, если найден (можно положить в `fonts/Inter-ExtraBold.ttf`),
  иначе DejaVu Sans Bold.

Озвучка кэшируется в `.cache/` — повторный запуск с тем же текстом не ходит в сеть.
