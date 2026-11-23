# Фейковая переписка → вертикальное видео

```
pip install pillow numpy edge-tts      # + ffmpeg в PATH
python generate.py script.json         # → output.mp4 (1080x1920, 60 fps, H.264 + AAC, −14 LUFS)
python generate.py script.json -o trial.mp4 --limit 6   # пробник: первые 6 реплик
python generate.py script.json --frame 12.5             # один кадр в PNG для проверки
```

Весь сюжет и оформление задаются в `script.json`, `generate.py` при смене сюжета не трогаем.
Озвучка кешируется в `.cache/tts/`, повторный запуск с тем же текстом не ходит в сеть.

## Реплики (`messages`)
```json
{"who": "tenant", "text": "...", "pause_after": 0.3}
```
Необязательные поля реплики:
- `rate`, `pitch`, `volume`, `voice`: переопределить голос только для этой реплики (`"+14%"`, `"+5Hz"`);
- `time`: время под сообщением (`"11:02"`); следующие идут от него;
- `typing`: длительность «печатает…» в секундах;
- `stop_drill: true`: фоновая «дрель» резко обрывается в момент, когда начинается эта реплика.

## Настройки (`settings`)
- **Голоса:** `voices.tenant.voice` / `voices.neighbor.voice` + `rate`, `pitch`. Список голосов: `edge-tts --list-voices | grep ru-RU`.
- **Имена и шапка:** `contact_name`, `contact_status`, `contact_typing`, `avatar_initial`, `date_chip`, `start_time`.
- **Кто справа:** `me` (по умолчанию `tenant`: салатовые пузыри с синими галочками).
- **Тексты:** `title` (крючок на первую секунду), `title_highlight` (слова, выделенные жёлтым), `outro_text` (`\n` = перенос строки).
- **Цвета:** `colors.*` (hex): `bubble_me`, `bubble_other`, `checks`, `accent`, `avatar`, `subtitle_highlight` (у каждого говорящего свой цвет), `outro_bg` и т.д. Полный список ключей в `DEFAULTS` в начале `generate.py`.
- **Звук:** `audio.beat_level`, `audio.drill_level`, `audio.pop_level`, `audio.beat_bpm`, `audio.beat_duck`.
- **Длительность:** `duration_min` / `duration_max`. Если ролик короче минимума, паузы растягиваются; если длиннее максимума, сначала сжимаются паузы и «печатает», и только потом ускоряется речь.
- Прочее: `subtitles`, `subtitle_uppercase`, `subtitle_max_words`, `shake` (тряска интерфейса под дрель), `fonts`.
