# Видео-история для Shorts / Reels / TikTok

Генерирует вертикальное безлицевое видео «страшная и смешная история» с озвучкой,
субтитрами по словам, звуковыми эффектами и световыми эффектами.

```bash
pip install -r requirements.txt        # + нужен ffmpeg в PATH
python generate.py story.txt           # -> output.mp4 (1080x1920, 30 fps, H.264 + AAC)
python generate.py story.txt --fps 60  # 60 fps
python generate.py story.txt --preview 15   # пробный ролик: первые 15 с -> output_preview.mp4
python generate.py story.txt -o my.mp4 --seed 3   # своё имя файла / другой случайный фон
```

## Как менять историю
`story.txt`: первая строка — заголовок (показывается 1,5 с в начале), дальше текст.
Код не трогаем. Длина ролика держится в рамках 45–60 с: если текст длинный,
паузы сокращаются, затем голос слегка ускоряется; если короткий — удлиняется хвост.

## Настройки — `config.json`
- **Голос** — `voice`: `name` (например `ru-RU-SvetlanaNeural`, `ru-RU-DmitryNeural`),
  `rate` (`-6%`), `pitch` (`-3Hz`), `volume`. Список голосов: `edge-tts --list-voices`.
- **Паузы** — `pauses.between_phrases` (0,5 с) и `pauses.before` — особые паузы перед фразами.
- **Цвета субтитров** — `subtitles`: `color`, `active_color` (текущее слово), `stroke_color`,
  `size`, `y` (0.62 = 62 % высоты), `max_words`, `uppercase`, `fonts`.
- **Подсветка фраз** — `highlights`: фраза, цвет, масштаб.
- **Заголовок / финал** — `title`, `outro` (`lines`, `plate_color`).
- **Фон** — `background`: цвета градиента и полосы света, `video_dim`, `dark_level`.
- **Звук** — `audio`: `hum_db` (гул, -28), `voice_rms_db`, `voice_over_bed_min_db` (12).
- **События** — `events`: слово-триггер из текста → `light` (`flicker`/`off`/`flash`),
  `sfx` (`click`/`breath`/`squelch`/`ding`), `hum` (`off`/`on`). Если триггера нет
  в новой истории, событие просто пропускается.

## Фоновые видео
Положите `.mp4` / `.mov` в папку `bg/`. Берётся случайный файл, зацикливается под длину
ролика, обрезается по центру в 9:16, яркость −35 %, виньетка. Пустая папка → генерируется
тёмный сине-серый фон с полосой света, как в щели дверей лифта.

## Шрифт
Ищется Inter ExtraBold, затем DejaVu Sans Bold. Свой шрифт можно положить в `fonts/`
и указать имя файла (без расширения) в `subtitles.fonts`.
