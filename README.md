# Бублик — мультсериал на Remotion

Вертикальные серии 1080×1920, 30 fps, 40 с (1200 кадров).

```bash
npm install
npm run studio        # превью в Remotion Studio
npm run render:ep01   # → out/ep01.mp4 (H.264)
```

## Структура

```
src/
  script.json            тексты, тайминги субтитров, время на будильнике, звонки, аудио (секунды)
  index.ts, Root.tsx     регистрация композиций
  episodes/
    index.ts             реестр серий
    ep01.tsx             серия 1: хореография Бублика, реквизит, удары, sfx
  scenes/Bedroom.tsx     декорация спальни (+ лампа, тапок)
  components/
    Bublik.tsx           персонаж (SVG, mood, lookAt, squash & stretch, автоморгание)
    Subtitles.tsx        субтитры по словам
    Shake.tsx            screen shake на ударах
    SafeAudio.tsx        <Audio>/sfx, отсутствующие файлы пропускаются
    AlarmClock.tsx, Cat.tsx, motion.ts (spring/easing-помощники), script.ts
public/
  voice.mp3              озвучка (необязательно)
  music.mp3              фон, громкость 0.15 (необязательно)
  sfx/*.mp3              hit, jump, bonk, boing, whoosh, meow, ring (необязательно)
```

## Звук

- **Озвучка:** положите файл в `public/voice.mp3`. Он играет с кадра 0.
- **Музыка:** `public/music.mp3`, зацикливается, громкость 0.15.
- **Эффекты:** `public/sfx/<имя>.mp3`. Имена: `hit`, `jump`, `bonk`, `boing`, `whoosh`, `meow`, `ring`.
- Имена файлов и громкость меняются в блоке `audio` файла `src/script.json`.
- Если какого-то файла нет, он просто не звучит, рендер не падает.
- После добавления файла в студии обновите страницу.

## Новая серия

1. Скопируйте `src/episodes/ep01.tsx` → `ep02.tsx` и задайте `id: "Ep02"`.
2. Положите рядом свой script-файл (например, `src/episodes/ep02.json`) и импортируйте его.
3. Замените сцену и хореографию.
4. Добавьте серию в `src/episodes/index.ts`.
5. Добавьте скрипт `render:ep02` в `package.json`.
