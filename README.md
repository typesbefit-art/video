# Космос: 3 факта — ролик для TikTok (Remotion)

1080×1920, 30 fps, 25 с → `output/space.mp4`.

```bash
npm install
npm run studio   # превью и правка в браузере (http://localhost:3000)
npm run render   # рендер в output/space.mp4
```

- Музыка: положите `assets/music.mp3` — она добавится тихим фоном (громкость 15%, с фейдами). Без файла ролик рендерится без звука.
- Тексты и тайминги сцен: `src/scenes.tsx`, `src/constants.ts`.
- Звёзды: `src/Starfield.tsx`, субтитры: `src/Captions.tsx`, прогресс-бар: `src/ProgressBar.tsx`.
- Шрифт: Inter Black (`public/fonts`, лицензия SIL OFL).
