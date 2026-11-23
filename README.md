# Генератор видео «переписка в мессенджере»

Вертикальное видео 1080×1920, 60 fps, H.264 + AAC: фейковая переписка водителя такси и пассажирки,
озвучка edge-tts, субтитры с подсветкой слов, маршрут с машинкой, поп-звуки и фоновый бит.

```bash
pip install -r requirements.txt      # (generate.py и сам доставит недостающее)
python generate.py script.json                         # -> output.mp4
python generate.py script.json --lines 6 -o preview.mp4  # пробная версия
python generate.py script.json --frame 12.5 -o check     # один кадр -> check.png
```

Нужен `ffmpeg` в PATH. Озвучка кэшируется в `.tts_cache/`: повторный запуск без смены текста не ходит в сеть.

## Сценарий — `script.json`

```json
{
  "title": "Заголовок-крючок на первую секунду",
  "outro": "Подписывайся на «Название канала»",
  "driver_name": "Водитель",
  "driver_status": "в пути",
  "route_from": "Подъезд", "route_to": "Вокзал",
  "clock_start": "08:14",
  "lines": [
    {"who": "driver", "text": "...", "pause_after": 0.3},
    {"who": "passenger", "text": "...", "pause_after": 0.3, "route": "jump"}
  ]
}
```

- `who`: `driver` (слева, серый) или `passenger` (справа, фиолетовый, с галочками).
- `pause_after`: пауза после реплики, сек.
- `route`: `"jump"` — машинка резко прыгает назад на этой реплике (если нигде не указано, берётся первая реплика со словом «налево»);
  `"arrive"` — машинка доезжает до финиша.
- Для отдельной реплики можно задать `"voice"`, `"rate"` (`"+10%"`), `"pitch"` (`"-5Hz"`).
- Можно указать просто список реплик вместо объекта.

Полная версия автоматически подгоняется под 45–60 с: сначала ужимаются паузы, потом равномерно ускоряется озвучка.
Длинные паузы внутри реплик вырезаются (темп как в Shorts). `--lines N` (пробная версия) и `--no-fit` отключают подгонку.

## Голоса
Блок `VOICES` в начале `generate.py` или ключ `"voices"` в script.json:

```json
"voices": {
  "driver":    {"voice": "ru-RU-DmitryNeural", "rate": "+4%", "pitch": "-4Hz"},
  "passenger": {"voice": "ru-RU-SvetlanaNeural", "rate_start": "+12%", "rate_end": "+32%",
                "pitch_start": "+0Hz", "pitch_end": "+14Hz"}
}
```

У пассажирки темп и высота растут от `*_start` к `*_end` по ходу ролика; к репликам с «!» добавляется `exclaim_rate` / `exclaim_pitch`.
Список голосов: `edge-tts --list-voices | grep ru-RU`.

Если сервис edge-tts не отдаёт фразу (у ru-RU-DmitryNeural такое бывает), генератор повторяет попытки
и озвучивает по предложениям и частям. В крайнем случае ставит запасной голос, пишет «ВНИМАНИЕ»
и переозвучивает эту реплику при следующем запуске.

## Цвета и вид
Блок `THEME` в `generate.py` или `"theme"` в script.json, например
`"theme": {"passenger_bubble": "#1E88E5", "sub_hl": "#00E676"}`.
Раскладка (`VIEW_Y0`, `SUB_CY`, `MSG_FONT` и т. д.) и длительности (`HOOK_DUR`, `OUTRO_DUR`, `MIN_DUR`, `MAX_DUR`) —
константы в начале `generate.py`. Шрифт Inter лежит в `fonts/` (лицензия OFL).
