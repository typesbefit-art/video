# Страшная история: вертикальное видео

Генератор безлицевых хоррор-шортсов (TikTok / YouTube Shorts / Reels): озвучка через edge-tts,
субтитры по словам, звуки, сгенерированные в numpy, визуальные эффекты. Выход: MP4 1080x1920, H.264 + AAC.

## Установка
```bash
pip install -r requirements.txt     # edge-tts, numpy, Pillow
# нужен ffmpeg в PATH
```

## Запуск
```bash
python generate.py story.txt                # -> output.mp4 (30 fps)
python generate.py story.txt --fps 60       # 60 fps
python generate.py story.txt --preview 15   # только первые 15 с -> output_preview.mp4
python generate.py story.txt -o my.mp4
python generate.py story.txt --frames 2,22,63   # отладка: PNG отдельных кадров
```
Озвучка кэшируется в `cache/tts/`, поэтому повторный запуск не обращается к сервису.

## Как менять

| Что | Где |
|---|---|
| История | `story.txt`: первая строка — заголовок, дальше текст. Реплики — в «ёлочках». |
| Голос | `config.json` → `voice.name / rate / pitch` (список голосов: `edge-tts --list-voices`) |
| Паузы | `voice.pause_after_sentence`, `pause_before_last_sentence`, `pauses_before` (фраза → секунды) |
| Реплики «из телефона» | `voice.phone_quotes`: начала реплик; эффект трубки задаёт `voice.phone_filter` (фильтры ffmpeg) |
| Звуки и эффекты на словах | `cues`: фраза из текста + эффект (`ring`, `ring_quiet`, `creak`, `whisper`, `drone_cut`, `shake`, `double`) |
| Цвета субтитров | `subtitles.color / highlight / phone_highlight / phone_color` (RGB) |
| Шрифт, размер, высота | `subtitles.font / size / y` |
| Цвета фона | `background.top_color / bottom_color / light_color / fog_color` |
| Плашка в конце | `plate.text` |
| Длина ролика | `duration.min / max`: если не влезает, обычные паузы немного сжимаются |

Сердцебиение и тишина на последнем предложении, а также красное свечение с затемнением в конце
включаются автоматически для любой истории.

## Фоновые видео
Положите `.mp4` / `.mov` в папку `bg/`. Каждый запуск берёт случайный файл, зацикливает его,
вырезает центральную вертикаль 9:16, приглушает яркость на 40 % (`background.dim`) и добавляет виньетку.
Если папка пустая, генерируется тёмный «коридор» с туманом и полоской света.
