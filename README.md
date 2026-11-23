# Переписка-шортс: генератор вертикального видео

Фейковая переписка «начальник ↔ сотрудница» в тёмном мессенджере: 1080×1920, 60 fps, H.264 + AAC.

```bash
pip install -r requirements.txt           # + ffmpeg в PATH
python generate.py script.json            # -> output.mp4
python generate.py script.json --limit 6 -o preview.mp4   # пробная версия: первые 6 реплик
```

Флаги: `--tts auto|edge|rhvoice` (по умолчанию edge-tts, а если он недоступен, то офлайн RHVoice),
`--no-fit` (не подгонять полную версию под 45–60 с), `--workers N`.
Озвучка кэшируется в `.cache/tts`, поэтому повторный запуск быстрый.

## Сценарий — `script.json`
```json
{"who": "boss|employee", "text": "...", "pause_after": 0.3}
```
Реплики лежат в `lines`. Там же можно задать `hook` (заголовок первой секунды, последняя строка подсвечивается жёлтым),
`cta` (финальная плашка), `contact_name`, `start_time`, `final_typing_seconds`.
У реплики можно переопределить голос по отдельности: см. «Голоса».

## Голоса, цвета, имена — без правки кода
Любой ключ из блока `CONFIG` в начале `generate.py` можно перекрыть в `script.json`:
```json
{
  "contact_name": "Шеф",
  "voices": {
    "boss":     {"edge": "ru-RU-DmitryNeural",   "rate": 10, "pitch": 4},
    "employee": {"edge": "ru-RU-SvetlanaNeural", "rate": -4, "pitch": -2, "rate_step": -1.5, "pitch_step": -1}
  },
  "colors": {"employee_bubble_top": "#4F8BFF", "employee_bubble_bottom": "#2F5FE0", "subtitle_highlight": "#7CFF6B"},
  "audio": {"beat_volume": 0.06, "bpm": 100}
}
```
* `rate` — скорость в %, `pitch` — тон в Гц; `*_step` — добавка к каждой следующей реплике персонажа
  (у сотрудницы голос становится медленнее и ниже, то есть всё более уставшим).
* Список голосов: `edge-tts --list-voices | grep ru-RU` (есть ещё `ru-RU-DariyaNeural`).
* Офлайн-голоса RHVoice: ключи `rhvoice`, `rh_rate`, `rh_pitch` (aleksandr-hq, anna, elena, irina, mikhail…).

## Если edge-tts отвечает через раз
Скрипт повторяет запрос до 15 раз (`EDGE_RETRIES=25 python generate.py script.json` — больше).
Уже озвученные реплики кэшируются, поэтому повторный запуск дозаписывает только недостающие.
Ролик всегда озвучивается одним движком: если edge-tts так и не ответил, весь ролик озвучит RHVoice
(или упадёт с ошибкой при `--tts edge`).
