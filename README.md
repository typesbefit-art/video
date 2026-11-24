# Фейковая переписка → вертикальное видео

Генерирует ролик 1080×1920, 60 fps, H.264 + AAC в виде переписки в мессенджере
(тёмная тема, «печатает…», пузыри, синие галочки, субтитры с подсветкой слова,
озвучка edge-tts, «поп» на каждое сообщение, фоновый бит).

```bash
pip install -r requirements.txt     # + нужен ffmpeg в PATH
python generate.py script.json      # → output.mp4
python generate.py script.json -o my.mp4
python generate.py script.json --preview 12.5   # один кадр в preview.png (быстро)
```

## Сценарий — `script.json`

```json
{
  "settings": {
    "contact_name": "Курьер",
    "contact_status": "онлайн",
    "hook": "Когда курьер у двери, а ты без макияжа",
    "outro_title": "Подписывайся на",
    "outro_channel": "«Прочитано и проигнорировано»",
    "min_duration": 45,
    "max_duration": 60
  },
  "messages": [
    {"who": "courier", "text": "Я с заказом. Стою у двери.", "pause_after": 0.3},
    {"who": "client",  "text": "Вижу вас в глазок.", "pause_after": 0.3}
  ]
}
```

* `who` — `courier` (слева, серый) или `client` (справа, мятный, с галочками).
* `pause_after` — пауза после реплики, сек.
* Необязательно для отдельной реплики: `"rate": 15` (%), `"pitch": -5` (Hz),
  `"volume": 10` (%), `"voice": "ru-RU-..."`.
* `"say"` — как произносить реплику: список кусков `{"text", "rate", "pitch", "volume", "gap", "fx"}`.
  `rate`/`pitch` — смещение от базового голоса, `gap` — пауза после куска,
  `fx`: `wobble` (дрожь паники), `melt` («тающий» голос), `chipmunk` (писк), `slowmo` (бас).
  Субтитры и пузыри берутся из `text`, так что многоточия и «?!» в `say` на экран не попадут.
* `"sfx"` — комедийный звук: `rimshot`, `sad_trombone`, `crickets`, `record_scratch`,
  `boing`, `applause`; `{"name": "rimshot", "at": "end|start|before", "offset": 0, "volume": 1}`.
* В заголовке-крючке часть после запятой подсвечивается акцентным цветом.
* Если ролик выходит короче `min_duration` или длиннее `max_duration`, паузы и
  «печатает» растягиваются или сжимаются автоматически. Если и этого мало, выводится
  предупреждение: тогда сократите или дополните текст.

## Голоса

В `generate.py` → `VOICES`, или без правки кода в `script.json`:

```json
"settings": {
  "voices": {
    "courier": {"voice": "ru-RU-DmitryNeural", "rate_start": -8, "rate_end": -10},
    "client":  {"voice": "ru-RU-SvetlanaNeural", "rate_start": 4, "rate_end": 26,
                "pitch_start": 0, "pitch_end": 14}
  }
}
```

Скорость, высота и громкость плавно меняются от первой реплики персонажа (`*_start`)
к последней (`*_end`). Список голосов: `edge-tts --list-voices | grep ru-RU`.

## Цвета и тайминги

`generate.py` → `THEME` (цвета, hex) и `TIMING` (длина крючка/плашки, «печатает»,
громкость бита и «попа», BPM). Их тоже можно переопределить в `script.json`:

```json
"settings": {
  "theme":  {"client_bubble": "#7AB8FF", "client_text": "#071A33", "sub_hl_client": "#7AB8FF"},
  "timing": {"beat_volume": 0.15, "hook": 1.2}
}
```

Озвучка кешируется в `.tts_cache/`, поэтому повторный запуск после правки цветов
ничего не скачивает заново.
