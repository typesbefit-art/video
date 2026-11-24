# Страшная история → вертикальное видео

Генерирует безлицевое вертикальное видео с озвучкой и субтитрами для TikTok / YouTube Shorts / Reels:
MP4 1080×1920, H.264 + AAC, 30 fps (или `--fps 60`), длина 50–65 с.

## Установка
```bash
pip install -r requirements.txt     # edge-tts, numpy, Pillow
# нужен ffmpeg (+ ffprobe) в PATH
```

## Запуск
```bash
python generate.py story.txt                 # -> output.mp4
python generate.py story.txt --fps 60        # 60 fps
python generate.py story.txt --preview 15    # пробник: первые 15 секунд
python generate.py story.txt -o video.mp4 --seed 7   # другое имя / воспроизводимая случайность
```

## Как менять
* **История** — `story.txt`: первая строка заголовок, дальше текст. Код не трогаем.
  Если длина выйдет за 50–65 с, паузы (а при необходимости темп) подстроятся автоматически — об этом будет сообщение.
* **Голос, цвета, громкости, шрифт, тексты плашки** — `config.py`
  (`VOICE`, `RATE`, `PITCH`, `SUB_HIGHLIGHT`, `BG_TOP_COLOR`, `FOG_COLOR`, `DRONE_DB`, `OUTRO_TEXT_1` …).
  Список голосов: `edge-tts --list-voices | grep ru-RU`.
* **Фон** — положите `.mp4`/`.mov` в папку `bg/`: возьмётся случайный файл, зациклится,
  обрежется до центральной вертикали 9:16, станет темнее на 35% и получит виньетку.
  Пустая папка — генерируется фон с туманом и мерцаниями.

Озвучка кэшируется в `.cache/tts`, поэтому повторные запуски с тем же текстом не ходят в сеть.
