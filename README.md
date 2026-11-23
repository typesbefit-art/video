# Генератор видео «фейковая переписка»

Вертикальное видео 1080×1920, 60 fps, H.264 + AAC для Shorts / TikTok / Reels. Тёмный мессенджер, озвучка двумя голосами через edge-tts, субтитры с подсветкой текущего слова, «поп» на каждое сообщение, фоновый бит, заголовок-крючок в начале и плашка с призывом подписаться в конце.

```bash
python generate.py script.json                  # -> output.mp4
python generate.py script.json -n 5 -o test.mp4 # проба: только первые 5 реплик
```

Нужны Python 3.9+ и ffmpeg в PATH. Пакеты Pillow, numpy и edge-tts скрипт при необходимости ставит сам. Для озвучки нужен интернет. Готовая озвучка кэшируется в `.tts_cache/`, поэтому повторный запуск с тем же текстом проходит быстрее и без сети.

Опции: `--workers N` (число потоков рендера), `--crf 18` (качество), `--preset veryfast`, `--no-fit` (не подгонять длину под 45–60 с).

## Сценарий

Всё лежит в `script.json`: блок `meta` с настройками и массив `lines`.

```json
{"who": "client", "text": "Сколько с меня?", "pause_after": 0.3}
```

- `who`: `client` (справа) или `master` (слева). Есть ещё `system`: плашка по центру, например «3 часа спустя». В `skip_minutes` указывается, на сколько минут сдвинуть время на сообщениях.
- `pause_after`: пауза после реплики, в секундах.
- Необязательные поля реплики:
  - `typing`: сколько секунд длится «печатает…»;
  - `rate` / `pitch` (например `"+30%"`, `"+10Hz"`) и `voice`: интонация этой реплики.

Если ролик выходит длиннее `max_duration` (по умолчанию 60 с), скрипт сам поджимает паузы, а если этого мало, ускоряет речь. Длинные паузы внутри озвучки между предложениями обрезаются автоматически (`max_word_gap`, `max_sentence_gap`; отключается так: `"tighten_pauses": false`).

Тексты экрана задаются в `meta`: `hook` (крючок), `cta` (финальная плашка), `contact_name`, `contact_initials`, `contact_status`, `start_time`, `date_label`. Слова в `*звёздочках*` подсвечиваются жёлтым. Длительности: `hook_duration`, `first_message_at`, `cta_duration`.

## Голоса

```json
"voices": {
  "client": {"voice": "ru-RU-SvetlanaNeural", "rate": "+25%", "pitch": "+0Hz"},
  "master": {"voice": "ru-RU-DmitryNeural",   "rate": "+20%", "pitch": "-2Hz"}
}
```

Посмотреть все голоса: `edge-tts --list-voices`. Русских голосов два: Dmitry и Svetlana. Многоязычные голоса (например `en-US-AndrewMultilingualNeural`) тоже читают по-русски, но с акцентом. Чтобы получить второй мужской голос, можно взять Dmitry с `pitch` +15Hz и другим `rate`.

## Цвета, шрифты, звук

Блок `meta.theme` перекрывает любые ключи из `DEFAULT_THEME` в generate.py:

```json
"theme": {
  "client_bubble": ["#FF6A3D", "#FF2E7E"],
  "master_bubble": "#2A2F3A",
  "sub_highlight": "#00E5FF",
  "bg": "#000000"
}
```

Другие ключи: `wallpaper`, `header`, `status_typing`, `accent`, `avatar`, `cta_button`, `hook_highlight`.

- Субтитры строчными буквами: `"subtitle_uppercase": false`.
- Свои шрифты: `"fonts": {"regular": "path.ttf", "medium": "...", "bold": "...", "black": "..."}`, либо просто положите файлы в папку `fonts/`.
- Звук: `music_volume` (громкость бита, 0.10), `music_file` (свой трек вместо синтезированного бита; под голосом он автоматически приглушается), `pop_volume`, `voice_volume`, `loudness` (по умолчанию -14 LUFS).
