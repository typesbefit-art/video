# Плейсхолдеры для иллюстраций

Сюда кладите свои иллюстрации для сцен (PNG/JPG, лучше всего 1080×1920 или больше, 9:16).

Чтобы сцена показывала вашу картинку вместо процедурного SVG-фона, укажите путь
в поле `image` нужной сцены в `scenes.json` (путь считается от `public/`):

```json
{ "id": "hook", "image": "illustrations/hook.png", ... }
```

Частицы, надписи, иконки, зерно, виньетка и субтитры останутся поверх картинки.
К картинке автоматически применяется медленный наезд (Ken Burns).

| Сцена | id | Предлагаемое имя файла |
|---|---|---|
| 1. Хук | `hook` | `illustrations/hook.png` |
| 2. Первые секунды | `seconds` | `illustrations/seconds.png` |
| 3. Первый час | `hour` | `illustrations/hour.png` |
| 4. Первые дни | `days` | `illustrations/days.png` |
| 5. Первые месяцы | `months` | `illustrations/months.png` |
| 6. Через год | `year` | `illustrations/year.png` |
| 7. Восстановление | `recovery` | `illustrations/recovery.png` |
| 8. Финал | `final` | `illustrations/final.png` |

Если нужен параллакс из ваших слоёв (небо / дальний план / город / передний план),
замените содержимое соответствующих `<Layer depth={…}>` в `src/scenes/S*.tsx`
на `<image href={staticFile('illustrations/hook-sky.png')} … />`.
