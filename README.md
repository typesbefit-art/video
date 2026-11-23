# Фейковая переписка → вертикальное видео

`python generate.py script.json` → `output.mp4` (1080x1920, 60 fps, H.264 + AAC).

Зависимости: Python 3.9+, `pip install pillow numpy edge-tts`, ffmpeg в PATH. Шрифты Roboto лежат в `fonts/`.

Опции:
- `-o file.mp4` — имя выходного файла
- `--limit 6` — только первые N реплик (пробный ролик, без подгонки длины)
- `--frames 1,10,20` — сохранить PNG-кадры для быстрой проверки, без рендера видео
- `--no-fit` — не подгонять длительность под 45–60 с
- `--preset veryfast` — пресет x264 (быстрее рендер, файл больше)

## Сценарий
`script.json` → `messages`: `{"who": "me|friend", "text": "...", "pause_after": 0.3}`.
Дополнительные поля реплики (по желанию): `"say"` — что произносить вместо текста,
`"rate"` (%), `"pitch"` (Гц), `"voice"` — переопределить голос для одной реплики.

## Настройки
Всё в `script.json` → `settings` (переопределяет `DEFAULTS` в `generate.py`):
- `hook`, `outro_top`, `outro_title` — заголовок-крючок и финальная плашка
- `contact_name`, `contact_status`, `clock_start`, `date_label`
- `voices.me` / `voices.friend`: `voice`, `rate_start/rate_end`, `pitch_start/pitch_end`, `volume`
- `colors.*` — все цвета интерфейса (например, `me_bubble`, `friend_bubble`, `checks`, `sub_active`)
- `audio.*` — громкость бита, попов, ducking; `timing.*` — длительность «печатает» и анимаций
- `duration.min/max` — рамки длины ролика
