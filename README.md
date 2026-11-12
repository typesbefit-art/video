# GTA 6 Short (1080x1920, 30 с, 60 fps)

Вертикальный ролик, целиком собранный кодом: графика на Pillow + numpy, музыка и SFX синтезированы,
озвучка офлайн через RHVoice (голос `aleksandr-hq`).

- `script.json`: сцены, тайминги, текст озвучки (`отображение|произношение`)
- `build.py`: `python3 build.py` (audio → frames → thumb → check), `python3 build.py preview 1.0 5.5`
- `assets/`: шрифты (Russo One, Montserrat, OFL), озвучка + `timings.json`, музыка, итоговый `mix.wav`
- `output/gta6_short.mp4`, `output/thumbnail.png`, `publish.md`, `voiceover.txt`

Зависимости: python3, numpy, Pillow, ffmpeg, `apt install rhvoice rhvoice-russian`.
