"""Текст диктора по сценам и расчёт таймингов слов / фраз субтитров.

Пока нет реальной озвучки, тайминги слов оцениваются по числу слогов
(гласных) с паузами на знаках препинания. Если запишете голос с другим
темпом — поправьте start/end сцен или LEAD_IN/LEAD_OUT ниже и перерендерьте.
"""
import re

FPS = 30
DURATION = 59.0

SCENES = [
    dict(id="hook", start=0.0, end=4.0, lead_in=0.15, lead_out=0.35,
         text="Что, если война между Россией и Украиной закончится?"),
    dict(id="security", start=4.0, end=15.0,
         text="Первый вопрос — безопасность. Кто и как даст гарантии? "
              "Линия фронта может стать линией разграничения. "
              "А разминирование, по оценкам, займёт годы."),
    dict(id="people", start=15.0, end=27.0,
         text="Дальше — люди. Миллионы уехали из-за войны. "
              "Часть из них может вернуться домой, а семьи — воссоединиться. "
              "Но для этого нужны жильё, работа и восстановленные города."),
    dict(id="economy", start=27.0, end=40.0,
         text="Экономика. Восстановление, по оценкам, обойдётся в сотни миллиардов долларов. "
              "Встанет вопрос санкций: смягчать их или сохранить. "
              "Изменятся энергетика и цены, а инвесторы будут ждать стабильности."),
    dict(id="risks", start=40.0, end=52.0,
         text="Но мир может оказаться хрупким. Всё зависит от условий соглашения: "
              "кто гарантирует его выполнение и смогут ли стороны доверять друг другу."),
    dict(id="final", start=52.0, end=59.0, lead_out=0.9,
         text="А как думаете вы: каким должен быть прочный мир? "
              "Пишите в комментариях и подписывайтесь!"),
]

VOWELS = set("аеёиоуыэюяАЕЁИОУЫЭЮЯ")
PAUSE_SOFT = 0.22   # , : —
PAUSE_HARD = 0.45   # . ? !


def tokenize(text):
    toks = []
    for raw in text.split():
        if re.fullmatch(r"[—–-]+", raw) and toks:
            toks[-1] += " " + raw   # тире приклеиваем к предыдущему слову
        else:
            toks.append(raw)
    return toks


def syllables(word):
    return max(1, sum(ch in VOWELS for ch in word))


def pause_after(word):
    w = word.rstrip()
    if w[-1] in ".?!":
        return PAUSE_HARD
    if w[-1] in ",:—–;":
        return PAUSE_SOFT
    return 0.0


def word_timings():
    """[(scene_id, word, start, end)] для всех слов."""
    out = []
    for sc in SCENES:
        toks = tokenize(sc["text"])
        a = sc["start"] + sc.get("lead_in", 0.3)
        b = sc["end"] - sc.get("lead_out", 0.5)
        pauses = [pause_after(t) for t in toks]
        pauses[-1] = 0.0
        weights = [syllables(t) + 0.6 for t in toks]
        per = (b - a - sum(pauses)) / sum(weights)
        t = a
        for tok, wgt, p in zip(toks, weights, pauses):
            d = wgt * per
            out.append((sc["id"], tok, round(t, 3), round(t + d, 3)))
            t += d + p
    return out


WORDS = word_timings()


def wt(scene_id, needle, which="start"):
    """Время начала (или конца) первого слова сцены, содержащего needle."""
    for sid, w, s, e in WORDS:
        if sid == scene_id and needle.lower() in w.lower():
            return s if which == "start" else e
    raise KeyError(f"{scene_id}: {needle}")


def scene_by_id(sid):
    return next(s for s in SCENES if s["id"] == sid)


def fmt_srt(t):
    ms = int(round(t * 1000))
    h, ms = divmod(ms, 3600000)
    m, ms = divmod(ms, 60000)
    s, ms = divmod(ms, 1000)
    return f"{h:02}:{m:02}:{s:02},{ms:03}"


def fmt_tc(t):
    m, s = divmod(t, 60)
    return f"{int(m):02}:{s:05.2f}"
