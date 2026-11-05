# Мост. Бой двух самураев — Remotion + @remotion/three

Вертикальное видео 1080×1920, 30 с. Процедурная 3D-сцена без внешних моделей: фигуры из примитивов,
скелет с IK рук/ног, хореография по ключам, рамп скорости (слоумо), искры, туман, контровой свет,
motion blur (подкадры, затвор 180°), грейд/зерно/виньетка/хроматическая аберрация в пост-шейдере.

## Пресеты
| Композиция | fps | кадров | подкадров motion blur |
|---|---|---|---|
| `Samurai120` | 120 | 3600 | 2 (+MSAA ×2) |
| `Samurai60`  | 60  | 1800 | 3 |

```bash
npm install
npm run render:test   # 0–5 с, 60 fps -> out/test_5s_60fps.mp4
npm run render:60     # out/samurai_60fps.mp4 (TikTok / Shorts)
npm run render:120    # out/samurai_120fps.mp4
```
Рендер программный (SwiftShader, `--gl=swangle`): GPU в среде нет. Путь к Chromium задан в
`remotion.config.ts` (переменная `REMOTION_BROWSER`).

## Озвучка
`public/voice/voiceover.wav` сгенерирована edge-tts (голос `ru-RU-DmitryNeural`) скриптом
`scripts/tts.py`: фразы синтезируются по отдельности, тишина обрезается, фразы раскладываются
по окнам сценария; реальные тайминги пишутся в `src/voice.json` (по ним идут субтитры).
Звуков ударов и музыки нет — файлов не было.

## Структура
- `src/scene/time.ts` — рамп скорости: видео-время → время сцены
- `src/scene/choreo.ts` — ключевые позы бойцов
- `src/scene/fighter.ts` — фигура, доспехи, IK, меч
- `src/scene/camera.ts` — план за планом, ручная тряска на ударах
- `src/scene/world.ts` — сборка мира, точки искр по реальной геометрии клинков
- `src/scene/SceneRenderer.tsx` — подкадры motion blur + пост-обработка
- `src/Subtitles.tsx` — субтитры над нижней безопасной зоной (нижний край на 1520 px)
- `scripts/stills.mjs` — контрольные кадры; `scripts/debug.ts` — численная проверка поз
