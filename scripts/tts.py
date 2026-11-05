"""Озвучка через edge-tts: каждая фраза отдельно, тишина по краям обрезается,
фразы раскладываются по таймингам из сценария -> public/voice/voiceover.wav
и src/voice.json (реальные тайминги фраз для субтитров).

Запуск:  python3 scripts/tts.py   (нужен pip-пакет edge-tts)
"""
import asyncio, json, os, subprocess, sys, tempfile, time

VOICE = "ru-RU-DmitryNeural"
RATE = "-6%"
PITCH = "-6Hz"
SR = 48000

# (начало окна, конец окна, [фразы]) — окна из ТЗ
SCRIPT = [
    (0.0, 6.0, ["Туман над мостом.", "Двое.", "Ни слова.", "Лишь ветер и холод стали."]),
    (6.0, 13.0, ["Клинки покидают ножны.", "Первый удар.", "Блок.", "Искры во тьме.",
                 "Каждое движение может стать последним."]),
    (13.0, 21.0, ["Шаг в сторону.", "Разворот.", "Сталь режет воздух у самого лица.",
                  "Один пропускает удар, но остаётся стоять."]),
    (21.0, 27.0, ["Последний выпад.", "Тишина.", "Секунда, длиннее всей жизни."]),
    (27.0, 30.0, ["Один клинок падает.", "Рассвет.", "Бой окончен."]),
]
LEAD = 0.35   # отступ от начала окна
TAIL = 0.25   # запас до конца окна
TOTAL = 30.0

import edge_tts  # noqa: E402


async def synth_once(text, path, rate):
    c = edge_tts.Communicate(text, VOICE, rate=rate, pitch=PITCH,
                             proxy=os.environ.get("HTTPS_PROXY"))
    await c.save(path)


def synth(text, path, rate=RATE):
    for attempt in range(8):
        try:
            asyncio.run(synth_once(text, path, rate))
            if os.path.getsize(path) > 2000:
                return
        except Exception as e:  # сервис иногда отвечает NoAudioReceived
            err = e
        time.sleep(1.5 * (attempt + 1))
    sys.exit(f"TTS не удался для фразы: {text!r} ({err if 'err' in dir() else 'пустой ответ'})")


def to_trimmed_wav(src, dst):
    # обрезаем тишину в начале и в конце
    f = ("silenceremove=start_periods=1:start_threshold=-45dB:start_silence=0.02,"
         "areverse,silenceremove=start_periods=1:start_threshold=-45dB:start_silence=0.06,areverse")
    subprocess.check_call(["ffmpeg", "-y", "-v", "error", "-i", src, "-af", f,
                           "-ar", str(SR), "-ac", "1", dst])


def dur(p):
    return float(subprocess.check_output(["ffprobe", "-v", "error", "-show_entries",
                                          "format=duration", "-of", "csv=p=0", p]))


def main():
    tmp = tempfile.mkdtemp()
    cues, inputs, delays = [], [], []
    n = 0
    for (w0, w1, phrases) in SCRIPT:
        # если речь не влезает в окно — чуть ускоряем именно это окно
        for rate in (RATE, "+0%", "+5%", "+10%", "+15%", "+20%"):
            clips = []
            for k, ph in enumerate(phrases):
                mp3, wav = f"{tmp}/{n + k}.mp3", f"{tmp}/{n + k}.wav"
                synth(ph, mp3, rate)
                to_trimmed_wav(mp3, wav)
                clips.append((ph, wav, dur(wav)))
            speech = sum(c[2] for c in clips)
            lead, tail = (0.05, 0.05) if w1 - w0 <= 3 else (LEAD, TAIL)
            avail = (w1 - w0) - lead - tail
            if speech <= avail - 0.25 * (len(clips) - 1) or rate == "+20%":
                break
        n += len(phrases)
        if speech > avail:
            sys.exit(f"Окно {w0}-{w1}: речь {speech:.2f}s не помещается в {avail:.2f}s")
        gap = (avail - speech) / max(1, len(clips) - 1) if len(clips) > 1 else 0
        gap = min(gap, 0.9)  # паузы не длиннее 0.9 с, остаток — в конце окна
        t = w0 + lead
        for ph, wav, d in clips:
            cues.append({"text": ph, "start": round(t, 3), "end": round(t + d, 3)})
            inputs.append(wav)
            delays.append(t)
            t += d + gap
        print(f"{w0:4.0f}-{w1:<4.0f} rate {rate:>4} речь {speech:5.2f}s  пауза {gap:.2f}s  конец {t - gap:5.2f}")
    # сводим всё в одну дорожку
    args = ["ffmpeg", "-y", "-v", "error"]
    for i in inputs:
        args += ["-i", i]
    parts = [f"[{i}]adelay={int(d * 1000)}:all=1[a{i}]" for i, d in enumerate(delays)]
    mix = "".join(f"[a{i}]" for i in range(len(inputs)))
    parts.append(f"{mix}amix=inputs={len(inputs)}:normalize=0,"
                 f"apad,atrim=0:{TOTAL},loudnorm=I=-16:TP=-1.5:LRA=11[out]")
    args += ["-filter_complex", ";".join(parts), "-map", "[out]", "-ar", str(SR),
             "public/voice/voiceover.wav"]
    subprocess.check_call(args)
    with open("src/voice.json", "w", encoding="utf-8") as f:
        json.dump(cues, f, ensure_ascii=False, indent=1)
    print("ok: public/voice/voiceover.wav, src/voice.json")


main()
