# Вертикальный ролик «Что, если война закончится?»

1080×1920, 30 fps, 59 с. Сценарий — `script.md`, текст для диктора — `voiceover.txt`.
Результат — `output/video.mp4`, субтитры — `output/captions.srt`.

Сборка (Python 3 + Pillow + numpy + ffmpeg):

    ./build.sh                 # без голоса (только музыка)
    ./build.sh voice.wav       # с записанной озвучкой, музыка приглушается под голос
