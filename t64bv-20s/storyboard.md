# Т-64БВ — ролик на 20 секунд «Выход»

**Идея:** холодный запуск, рывок, прыжок с гребня, выстрел с ходу, уход в дымовую завесу.
Без музыки в первой половине: только звук двигателя, гусениц и выстрела. Это и даёт реализм.

**Место:** танковый полигон, раннее утро, низкое солнце, туман у земли, сырой чернозём, колеи.
**Камера:** 24 к/с, выдержка 1/48, длиннофокусная оптика и дрон, лёгкая ручная тряска. Цвет: приглушённая зелень, холодные тени, тёплый контровой свет.

---

## Раскадровка

| # | Время | План | Что происходит | Звук |
|---|-------|------|----------------|------|
| 1 | 0:00–0:02.5 | Макро, кормовая часть | Чёрный экран → тихий свист стартера. Запуск 5ТДФ: из выпускного патрубка на **левом борту** бьёт густой сизо-чёрный выхлоп и затягивает кадр | Нарастающий свист, «чих», затем характерный высокий вой двухтактного дизеля |
| 2 | 0:02.5–0:05 | Камера на земле, в колее | Танк накатывает прямо на камеру и проходит над ней/рядом. Узкие гусеницы, **6 малых опорных катков** и поддерживающие ролики, на объектив летят комья грязи | Лязг траков, гусеница «шлёпает» по грязи, вибрация в басу |
| 3 | 0:05–0:08 | Дрон, сопровождение сбоку, низко | Танк идёт по полю ~50 км/ч, корпус раскачивается, резиновые бортовые экраны хлопают, за кормой шлейф пыли и брызг. Видны бочки на корме, блоки **«Контакт-1»** на башне и ВЛД | Рёв мотора с доплер-сдвигом |
| 4 | 0:08–0:10 | Телевик, спереди-снизу | Прыжок с гребня: нос вверх, приземление «клевком», подвеска проседает, грязь веером из-под гусениц | Глухой удар корпуса о землю, лязг |
| 5 | 0:10–0:12.5 | Крупно, с кормы над башней | Корпус качается на кочках, а **ствол стабилизирован и держит цель** — вот главная деталь реализма. Башня быстро доворачивает | Гудение приводов наведения поверх мотора |
| 6 | 0:12.5–0:14.5 | Средний план, 3/4 спереди | **Выстрел 125-мм 2А46М-1.** Вспышка, ударная волна поднимает кольцо пыли и травы вокруг танка, корпус приседает, кадр трясёт. 4 кадра рапида, затем обычная скорость | Жёсткий удар, на 0.5 с почти тишина и «звон в ушах» |
| 7 | 0:14.5–0:16.5 | Из-за кормы, через плечо | Вдали (~2 км) разрыв в мишенном поле: вспышка, пыль, звук приходит с задержкой | Далёкий глухой разрыв |
| 8 | 0:16.5–0:18.5 | Средний план | Залп гранатомётов **902Б «Туча»** с башни, перед танком встаёт белая завеса. Танк сдаёт назад | Хлопки пусков, шипение дыма |
| 9 | 0:18.5–0:20 | Общий план | Из дыма виден только силуэт ствола, он уходит в белое. Титр **«Т-64БВ»**. Последний вой мотора → чёрный | Затухание мотора |

---

## Детали, которые делают ролик достоверным

- **Звук 5ТДФ.** Это не «рычащий» V-образный дизель: двухтактный оппозитный мотор воет и свистит. Если подставить звук от Т-72 или «Абрамса», знающий зритель сразу заметит.
- **Выхлоп выходит по левому борту** в корме, не назад.
- **Подвеска:** 6 малых обрезиненных катков с внутренней амортизацией и 4 поддерживающих ролика. У Т-72 катки крупные, у Т-80 другие; путать нельзя.
- **Гильзы не вылетают.** В автомате заряжания Т-64 поддон гильзы возвращается в лоток конвейера. Выброс поддона через люк в корме башни бывает у Т-72, не у Т-64.
- **Комплект БВ:** блоки ДЗ «Контакт-1» на башне и ВЛД, 902Б «Туча», НСВТ на командирской башенке, бочки и ОПВТ-труба на корме, бульдозерный отвал под ВЛД.
- **Стабилизация:** ствол «плавает» относительно корпуса и держит линию на цель.
- **Ударная волна:** выстрел поднимает пыль кольцом и вдавливает траву, а не просто даёт огненный шар.
- **Задержка звука** на дальних планах (≈1 с на 340 м).

---

## Промпты для AI-видео (Veo / Sora / Kling / Runway)

Генерировать каждый план отдельно (5–8 с), потом резать по таймингу выше. Общий суффикс к каждому промпту:

> `photorealistic, documentary military footage, 24fps, shot on cinema camera, natural motion blur, early morning low sun, ground fog, muddy tank training ground, muted green color grade, no text, no music`

1. `Extreme close-up of the rear left hull side of a Soviet T-64BV main battle tank as its engine cold-starts, a thick burst of blue-black diesel exhaust smoke erupts from the side exhaust grille and engulfs the frame`
2. `Camera placed low on the ground inside a muddy track rut, a T-64BV tank drives directly toward and past the camera, narrow steel tracks with six small road wheels and return rollers, clumps of mud splatter onto the lens`
3. `Low drone tracking shot alongside a T-64BV tank speeding across a wet field at 50 km/h, hull pitching on bumps, rubber side skirts flapping, Kontakt-1 explosive reactive armor blocks on turret and glacis, fuel drums on the rear, spray of mud and dust trailing behind`
4. `Telephoto shot from low front angle, a T-64BV tank crests a dirt berm, the front lifts into the air and slams down nose-first, suspension compresses, a fan of mud flies from the tracks`
5. `Over-the-turret shot from behind a moving T-64BV, the hull rocks violently over rough terrain while the stabilized 125mm gun barrel stays perfectly steady on a distant target, turret traverses quickly`
6. `Three-quarter front view of a T-64BV firing its 125mm main gun, bright muzzle flash, circular blast wave kicks up dust and flattens grass around the tank, hull rocks back, camera shake, brief slow motion`
7. `Over-the-shoulder view from behind a T-64BV tank, a distant target explodes about two kilometers away in a dusty field, small flash and rising dust cloud`
8. `T-64BV turret-mounted smoke grenade launchers fire a salvo, white smoke screen blooms in front of the tank, the tank reverses into it`
9. `Wide shot, only the silhouette of a tank gun barrel visible as it disappears into dense white smoke, fade to black`

---

## Монтаж

- Планы 1–5: ускоряющийся ритм, склейки «по движению».
- План 6: единственный рапид в ролике. Сразу после выстрела 0.3–0.5 с почти тишины, потом звук возвращается.
- Музыка, если нужна, вступает только на 0:14 (низкий барабан) и обрывается на титре.
- Титр на 0:18.5: простой моноширинный шрифт, белый, без эффектов.
