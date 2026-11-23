# Fake messenger video generator

Вертикальное видео (1080×1920, 60 fps, H.264 + AAC) в формате переписки в мессенджере.

```bash
pip install -r requirements.txt        # + нужен ffmpeg в системе
python generate.py script.json          # → output.mp4
python generate.py script.json -o test.mp4 --limit 6   # пробная версия: первые 6 реплик
python generate.py script.json --frames 1.5,20,45      # PNG-кадры для быстрой проверки
```

Озвучка кешируется в `.cache/tts/` — повторный запуск с тем же текстом не ходит в сеть.

## Сценарий — `script.json`

```json
{"who": "mom", "text": "Ты поел?", "pause_after": 0.3}
```

Необязательные поля реплики:

| поле     | что делает |
|----------|------------|
| `rate`   | скорость голоса для этой реплики, например `"+15%"` |
| `pitch`  | высота, например `"+10Hz"` (сын «паникует») |
| `typing` | сколько секунд показывать «печатает…» перед сообщением |
| `tts`    | другой текст для озвучки (если на экране одно, а произнести надо иначе) |
| `voice`  | другой голос только для этой реплики |

Если ролик выходит короче `min_duration` (45 с), паузы автоматически растягиваются;
если длиннее `max_duration` (60 с) — немного сжимаются.

## Настройки — блок `"config"` в `script.json`

Всё из `DEFAULT_CONFIG` в `generate.py` можно переопределить в `config`, код не трогая.

- **Имя и аватар:** `"contact_name": "Батя"`, `"contact_initial": "Б"`, `"status_online"`, `"status_typing"`.
- **Голоса:**
  ```json
  "voices": {
    "mom": {"voice": "ru-RU-SvetlanaNeural", "rate": "-10%", "pitch": "-2Hz"},
    "son": {"voice": "ru-RU-DmitryNeural",   "rate": "+0%",  "pitch": "+0Hz"}
  }
  ```
  Список голосов: `edge-tts --list-voices` (для русского: `ru-RU-SvetlanaNeural`, `ru-RU-DmitryNeural`;
  можно взять, например, `uk-UA-…` или многоязычные голоса).
- **Цвета:** `"colors": {"son_bubble_top": "#A5D8FF", "son_bubble_bottom": "#74C0FC", "subtitle_highlight": "#7CFC00"}` —
  полный список ключей в `DEFAULT_CONFIG["colors"]`.
- **Тексты:** `"hook"` (заголовок первой секунды), `"outro"` (финальная плашка), `"knock_caption"`.
  Перенос строки — `\n`, фрагмент в `[квадратных скобках]` выделяется цветом.
- **Звук:** `"audio": {"beat_volume": 0.17, "beat_bpm": 88, "pop_volume": 0.22, "knock_volume": 0.95}`.
- **Время в чате:** `"clock_start": "21:47"`.
- **История над перепиской:** `"history"` — сообщения, видимые с самого начала (без озвучки), и плашки-даты `{"chip": "Вчера"}`.
