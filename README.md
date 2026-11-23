# Видео-переписка «Пациент и врач»

Генератор вертикальных роликов (1080×1920, 60 fps, H.264 + AAC) в формате фейковой переписки в мессенджере — для YouTube Shorts / TikTok / Reels.

## Запуск

```bash
pip install pillow numpy edge-tts      # нужен ещё ffmpeg в PATH
python generate.py script.json         # -> output.mp4
python generate.py script.json --lines 6 -o preview.mp4   # пробная версия
python generate.py script.json --frame 12 -o test         # один кадр в test.png
```

Озвучка кэшируется в `.tts_cache/`: повторный запуск с тем же текстом и голосами не обращается к сервису edge-tts.

## Файлы

| Файл | Что внутри |
|---|---|
| `script.json` | сюжет: реплики, имя в шапке, хук, финальная плашка |
| `config.json` | голоса, темп, цвета, шрифты, тайминги, громкость |
| `generate.py` | код (при смене сюжета не трогаем) |

## Как менять

**Сценарий** — `script.json` → `lines`:
```json
{"who": "patient", "text": "...", "pause_after": 0.3}
```
Дополнительно у реплики можно указать `"typing": 0.8` (сколько секунд «печатает») и `"rate"` / `"pitch"` / `"voice"`, чтобы переопределить голос только для неё.

**Имена и тексты** — `script.json`:
- `chat.name` — имя в шапке (инициал на аватарке берётся из него), `chat.status` — «в сети», `chat.typing_status` — «печатает»;
- `hook` — заголовок на первую секунду;
- `outro.top` / `outro.channel` — финальная плашка.

**Голоса** — `config.json` → `speakers.<who>`:
- `voice` — голос edge-tts. Список: `edge-tts --list-voices | grep ru-RU` (например `ru-RU-SvetlanaNeural`, `ru-RU-DmitryNeural`);
- `rate` (`"+24%"`) — темп, `pitch` (`"-6Hz"`) — высота, `volume`.

Новый персонаж: добавьте ещё один блок в `speakers` (например `"nurse"`) со `side: "left"` или `"right"` и используйте `"who": "nurse"`.

**Цвета** — `config.json`:
- пузыри: `speakers.<who>.bubble`, `text`, `time`;
- остальное в `colors`: фон (`bg_top`/`bg_bottom`), шапка, галочки (`read_check`), субтитры (`subtitle`, `subtitle_highlight`), хук, плашка.

**Длительность** — `config.json` → `video.min_duration` / `max_duration`. Если ролик короче минимума, паузы растягиваются автоматически. Если длиннее максимума, скрипт выводит предупреждение: сократите `pause_after` или `timing.typing_*` либо ускорьте `rate`.

**Звук** — `config.json` → `audio`: `beat_gain` (громкость бита), `beat_duck` (насколько бит приглушается под голосом), `pop_gain`, `beat_bpm`.

Любой ключ из `config.json` можно переопределить для отдельного ролика блоком `"config": {...}` внутри `script.json`.
