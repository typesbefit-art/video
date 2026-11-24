#!/usr/bin/env python3
"""
Генератор вертикальных хоррор-роликов серии «Ночная смена»
(страшная история с озвучкой и субтитрами, безлицевой формат для Shorts/Reels/TikTok).

    python generate.py story.txt                 -> output.mp4        (часть 1, config.json)
    python generate.py story2.txt part2          -> output_part2.mp4  (config.json + parts/part2.json)
    python generate.py story3.txt part3          -> output_part3.mp4
    ... --preview 15                             -> только первые 15 секунд (preview_*.mp4)
    ... --fps 60                                 -> 60 fps

История — в story*.txt (первая строка — заголовок). Голоса, паузы, цвета, камеры,
громкости и сценарий эффектов (привязка к фразам) — в config.json и parts/<часть>.json.
Код при смене истории не трогаем.
"""
from __future__ import annotations

import argparse
import asyncio
import copy
import hashlib
import json
import math
import multiprocessing as mp
import os
import random
import re
import shutil
import ssl
import subprocess
import sys
import tempfile
import time
import wave
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFilter, ImageFont

ROOT = Path(__file__).resolve().parent
W, H = 1080, 1920
SR = 48000


def log(msg: str) -> None:
    print(f"[{time.strftime('%H:%M:%S')}] {msg}", flush=True)


# ════════════════════════════════════════════════════════════════════════════
#  Конфиг
# ════════════════════════════════════════════════════════════════════════════

def deep_merge(a: dict, b: dict) -> dict:
    out = copy.deepcopy(a)
    for k, v in b.items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = deep_merge(out[k], v)
        else:
            out[k] = copy.deepcopy(v)
    return out


def load_config(path: Path, part: str | None = None) -> dict:
    with open(path, encoding="utf-8") as f:
        cfg = json.load(f)
    if part:
        pp = Path(part)
        if not pp.suffix:
            pp = ROOT / "parts" / f"{part}.json"
        if not pp.exists():
            sys.exit(f"Не найден файл сценария части: {pp}")
        with open(pp, encoding="utf-8") as f:
            cfg = deep_merge(cfg, json.load(f))
    return cfg


def first_existing(paths, base: Path = ROOT):
    for p in paths:
        pp = Path(p)
        if not pp.is_absolute():
            pp = base / pp
        if pp.exists():
            return str(pp)
    return None


def parse_hms(s):
    h, m, *rest = [int(x) for x in str(s).split(":")]
    return h * 3600 + m * 60 + (rest[0] if rest else 0)


# ════════════════════════════════════════════════════════════════════════════
#  Текст: разбор истории, реплики, нормализация, числа
# ════════════════════════════════════════════════════════════════════════════

PAUSE_MARK = re.compile(r"\[(?:пауза|pause)\s*([\d.,]+)\s*(?:с|s|сек)?\]", re.I)
SENT_END = re.compile(r"[.!?…]+[»\"”)]*(?=\s|$)")


def norm(word: str) -> str:
    w = word.lower().replace("ё", "е")
    return re.sub(r"[^0-9a-zа-я]+", "", w)


def norm_phrase(phrase: str) -> list[str]:
    return [n for n in (norm(x) for x in phrase.split()) if n]


def split_sentences(text):
    out, pos = [], 0
    for m in SENT_END.finditer(text):
        if re.match(r"\s*[—–]", text[m.end():]):  # «Где ты?» — прошептал я.
            continue
        s = text[pos:m.end()].strip()
        if s:
            out.append(s)
        pos = m.end()
    tail = text[pos:].strip()
    if tail:
        out.append(tail)
    return out


def match_speaker(inner: str, cfg) -> str:
    toks = norm_phrase(inner)
    for rule in cfg.get("dialogue", []):
        if "exact" in rule and toks == norm_phrase(rule["exact"]):
            return rule["speaker"]
        if "starts" in rule:
            st = norm_phrase(rule["starts"])
            if st and toks[:len(st)] == st:
                return rule["speaker"]
    return "narrator"


def parse_story(path: Path, cfg):
    """-> (заголовок, сегменты озвучки). Реплики в «ёлочках», совпавшие с правилами
    cfg.dialogue, озвучиваются голосом соответствующего персонажа."""
    text = path.read_text(encoding="utf-8").replace("\r\n", "\n")
    lines = [ln.strip() for ln in text.split("\n")]
    while lines and not lines[0]:
        lines.pop(0)
    if not lines:
        sys.exit(f"{path} пустой")
    title = lines[0]
    body = re.sub(r"\s+", " ", " ".join(ln for ln in lines[1:] if ln)).strip()

    pieces, pos = [], 0
    for m in re.finditer(r"«([^»]*)»", body):
        pieces.append(["narrator", body[pos:m.start()]])
        spk = match_speaker(m.group(1), cfg)
        pieces.append([spk, m.group(1) if spk != "narrator" else m.group(0)])
        pos = m.end()
    pieces.append(["narrator", body[pos:]])
    merged = []
    for spk, t in pieces:
        if merged and merged[-1][0] == spk == "narrator":
            merged[-1][1] += t
        else:
            merged.append([spk, t])

    segs = []
    for spk, t in merged:
        t = t.strip()
        if spk == "narrator":
            t = re.sub(r"^[\s.,;:!?…—–-]+", "", t).strip()  # хвост пунктуации после реплики
        if not re.search(r"[0-9A-Za-zА-Яа-яЁё]", t):
            continue
        if spk != "narrator" and not re.search(r"[.!?…]$", t):
            t += "."
        sents = split_sentences(t)
        for k, s in enumerate(sents):
            pause = None
            m = PAUSE_MARK.search(s)
            if m:
                pause = float(m.group(1).replace(",", "."))
                s = PAUSE_MARK.sub("", s).strip()
            if not s:
                continue
            inline = bool(segs) and k == 0 and re.search(r"[:,—–-]$", segs[-1]["text"]) is not None
            segs.append({"text": s, "pause": pause, "speaker": spk, "inline": inline,
                         "quote": spk != "narrator", "q_first": k == 0,
                         "q_last": k == len(sents) - 1})
    return title, segs


# Русские числительные (именительный/родительный и др. частые формы)
_NUM = {}
for v, forms in {
    1: "один одна одно одного одной одному одним одну",
    2: "два две двух двум двумя", 3: "три трех трем тремя",
    4: "четыре четырех четырем четырьмя", 5: "пять пяти пятью",
    6: "шесть шести", 7: "семь семи", 8: "восемь восьми", 9: "девять девяти",
}.items():
    for f in forms.split():
        _NUM[f] = (v, 0)
for v, stem in {10: "десят", 11: "одиннадцат", 12: "двенадцат", 13: "тринадцат",
                14: "четырнадцат", 15: "пятнадцат", 16: "шестнадцат",
                17: "семнадцат", 18: "восемнадцат", 19: "девятнадцат"}.items():
    for end in ("ь", "и", "ью"):
        _NUM[stem + end] = (v, 1)
for v, forms in {20: "двадцать двадцати", 30: "тридцать тридцати", 40: "сорок сорока",
                 50: "пятьдесят пятидесяти", 60: "шестьдесят шестидесяти",
                 70: "семьдесят семидесяти", 80: "восемьдесят восьмидесяти",
                 90: "девяносто девяноста"}.items():
    for f in forms.split():
        _NUM[f] = (v, 2)
for v, forms in {100: "сто ста", 200: "двести двухсот", 300: "триста трехсот",
                 400: "четыреста четырехсот", 500: "пятьсот пятисот",
                 600: "шестьсот шестисот", 700: "семьсот семисот",
                 800: "восемьсот восьмисот", 900: "девятьсот девятисот"}.items():
    for f in forms.split():
        _NUM[f] = (v, 3)


def num_word(n: str):
    """-> (value, class) или None. class: 0 единицы, 1 десять-девятнадцать, 2 десятки, 3 сотни."""
    if n.isdigit():
        return (int(n), 9)
    return _NUM.get(n)


def number_groups(words):
    """Склеивает подряд идущие числительные в числа: «двухсот четырнадцати» -> 214,
    но «три, четыре, пять» остаются тремя отдельными числами."""
    groups, i = [], 0
    while i < len(words):
        nw = num_word(words[i]["norm"])
        if not nw:
            i += 1
            continue
        val, cls = nw
        j = i + 1
        last_cls = cls
        while j < len(words) and words[j]["sent"] == words[i]["sent"]:
            nx = num_word(words[j]["norm"])
            if not nx or nx[1] >= last_cls or last_cls in (0, 1, 9) or nx[1] == 9:
                break
            val += nx[0]
            last_cls = nx[1]
            j += 1
        groups.append({"i0": i, "i1": j - 1, "value": val})
        i = j
    return groups


def find_phrase(words, phrase, start_at=0, occurrence="first"):
    toks = norm_phrase(phrase or "")
    if not toks:
        return None
    seq = [w["norm"] for w in words]
    hits = [(i, i + len(toks) - 1) for i in range(start_at, len(seq) - len(toks) + 1)
            if seq[i:i + len(toks)] == toks]
    if not hits:
        return None
    return hits[-1] if occurrence == "last" else hits[0]


# ════════════════════════════════════════════════════════════════════════════
#  Озвучка: edge-tts + WordBoundary
# ════════════════════════════════════════════════════════════════════════════

def _patch_edge_tts_ssl():
    """Если в системе задан свой CA (корпоративный прокси и т.п.) — доверяем ему."""
    ca = os.environ.get("SSL_CERT_FILE") or os.environ.get("REQUESTS_CA_BUNDLE")
    if ca and os.path.exists(ca):
        try:
            import edge_tts.communicate as ec
            ec._SSL_CTX = ssl.create_default_context(cafile=ca)
        except Exception:
            pass


async def _tts_request(text, voice, rate, pitch):
    import edge_tts
    proxy = os.environ.get("HTTPS_PROXY") or os.environ.get("https_proxy") or None
    kwargs = dict(rate=rate, pitch=pitch, proxy=proxy)
    try:
        comm = edge_tts.Communicate(text, voice, boundary="WordBoundary", **kwargs)
    except TypeError:  # старые версии edge-tts: WordBoundary по умолчанию
        comm = edge_tts.Communicate(text, voice, **kwargs)
    audio = bytearray()
    words = []
    async for ch in comm.stream():
        if ch["type"] == "audio":
            audio += ch["data"]
        elif ch["type"] == "WordBoundary":
            words.append({"text": ch["text"], "offset": ch["offset"] / 1e7,
                          "duration": ch["duration"] / 1e7})
    if not audio:
        raise RuntimeError("edge-tts не вернул аудио")
    return bytes(audio), words


def _fake_tts(text, rate, mp3: Path, js: Path):
    """Отладка без сети (HORROR_FAKE_TTS=1): тон вместо голоса, тайминги по длине слов."""
    k = 1 / (1 + int(rate.rstrip("%")) / 100)
    toks = [t for t in text.split() if norm(t)]
    t, words, audio = 0.1, [], []
    for tok in toks:
        d = (0.12 + 0.065 * len(norm(tok))) * k
        words.append({"text": re.sub(r"^[«\"(]+|[»\",.:;!?)…]+$", "", tok), "offset": t, "duration": d})
        n = int(d * SR)
        tt = np.arange(n) / SR
        audio.append(np.zeros(int(0.0 * SR)))
        audio.append(0.2 * np.sin(2 * np.pi * 140 * tt) * np.sin(np.pi * tt / d))
        t += d
    a = np.concatenate([np.zeros(int(0.1 * SR))] + audio + [np.zeros(int(0.2 * SR))]).astype(np.float32)
    with wave.open(str(mp3), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(SR)
        w.writeframes((a * 32767).astype("<i2").tobytes())
    js.write_text(json.dumps(words, ensure_ascii=False), encoding="utf-8")
    return mp3, words


def tts_cached(text, voice, rate, pitch, cache_dir: Path):
    if os.environ.get("HORROR_FAKE_TTS"):
        d = cache_dir.parent / "fake_tts"
        d.mkdir(exist_ok=True)
        key = hashlib.sha1(json.dumps([text, rate]).encode()).hexdigest()[:16]
        return _fake_tts(text, rate, d / f"{key}.wav", d / f"{key}.json")
    key =hashlib.sha1(json.dumps([text, voice, rate, pitch], ensure_ascii=False)
                       .encode("utf-8")).hexdigest()[:20]
    mp3, js = cache_dir / f"{key}.mp3", cache_dir / f"{key}.json"
    if mp3.exists() and js.exists():
        return mp3, json.loads(js.read_text(encoding="utf-8"))
    last = None
    r0 = int(rate.rstrip("%"))
    for attempt in range(12):
        # сервис иногда стабильно «не любит» конкретную пару текст+темп — слегка сдвигаем темп
        r = r0 if attempt < 5 else r0 + (1, -1, 2, -2, 1, -1, 2)[attempt - 5]
        try:
            audio, words = asyncio.run(_tts_request(text, voice, f"{r:+d}%", pitch))
            if not words:
                raise RuntimeError("нет WordBoundary")
            mp3.write_bytes(audio)
            js.write_text(json.dumps(words, ensure_ascii=False), encoding="utf-8")
            return mp3, words
        except Exception as e:  # сервис иногда отвечает пусто — повторяем
            last = e
            time.sleep(min(6.0, 0.6 * (1.5 ** attempt)) + random.random() * 0.5)
    sys.exit(f"edge-tts не отвечает на фразу «{text}» ({last}). Проверьте интернет и повторите запуск.")


def decode_audio(path: Path) -> np.ndarray:
    out = subprocess.run(["ffmpeg", "-v", "error", "-i", str(path), "-f", "f32le",
                          "-ac", "1", "-ar", str(SR), "pipe:1"],
                         capture_output=True, check=True).stdout
    return np.frombuffer(out, dtype=np.float32).copy()


def align_display(sentence: str, wb_words):
    """Сопоставляет слова из WordBoundary с исходным текстом, чтобы забрать пунктуацию."""
    out, pos, low = [], 0, sentence.lower()
    for w in wb_words:
        t = w["text"]
        k = low.find(t.lower(), pos)
        if k < 0:
            out.append(t)
            continue
        a, b = k, k + len(t)
        while a > 0 and sentence[a - 1] in "«\"„(":
            a -= 1
        while b < len(sentence) and sentence[b] in ",.:;!?»\"”)…":
            b += 1
        out.append(sentence[a:b])
        pos = k + len(t)
    return out


def _trim_bounds(a, wb):
    """Границы фразы по реальной громкости речи (edge-tts оставляет тишину по краям)."""
    hop = 480
    fr = np.sqrt(np.mean(a[: len(a) // hop * hop].reshape(-1, hop) ** 2, 1))
    act = np.where(fr > fr.max() * 0.03)[0]
    if len(act) == 0:
        return 0.0, len(a) / SR
    e0, e1 = act[0] * hop / SR, (act[-1] + 1) * hop / SR
    t0 = max(0.0, min(e0, wb[0]["offset"]) - 0.03)
    t1 = min(len(a) / SR, e1 + 0.07)
    return t0, t1


def speaker_cfg(cfg, spk):
    vc = cfg["voice"]
    base = {"name": vc["name"], "rate": vc["rate"], "pitch": vc["pitch"], "fx": "none"}
    if spk != "narrator":
        base.update(cfg.get("speakers", {}).get(spk, {}))
    return base


def voice_segments(title, segs):
    return [{"text": title.rstrip(".") + ".", "pause": None, "speaker": "narrator",
             "inline": False, "quote": False, "is_title": True}] + \
           [dict(s, is_title=False) for s in segs]


def segment_rates(cfg, segs, extra_ramp=0.0):
    """Темп по ходу истории: старт ровно с базового rate каждого голоса, к финалу —
    быстрее (рассказчик теряет самообладание). Прибавка ограничена voice.max_rate."""
    vc = cfg["voice"]
    n = len(segs)
    ramp = vc.get("tension_ramp", 0) + extra_ramp
    cap = vc.get("max_rate", 100) - vc["rate"]
    out = []
    for i, s in enumerate(segs):
        add = min(cap, ramp * (i / max(1, n - 1)))
        out.append(speaker_cfg(cfg, s["speaker"])["rate"] + add)
    return out


def radio_fx(clip, rng):
    """Рация: полоса 300–3000 Гц, лёгкий перегруз, шипение."""
    rms0 = np.sqrt(np.mean(clip ** 2)) + 1e-9
    x = fft_filter(clip, 300, 3000, order=4)
    pk = np.max(np.abs(x)) + 1e-9
    x = np.tanh(2.6 * x / pk) / np.tanh(2.6) * pk
    x = fft_filter(x, 280, 3400, order=2)
    hiss = fft_filter(rng.standard_normal(len(x)).astype(np.float32), 600, 6000, order=2)
    hiss *= rms0 * db(-24) / (np.sqrt(np.mean(hiss ** 2)) + 1e-9)
    x = x * (rms0 / (np.sqrt(np.mean(x ** 2)) + 1e-9)) * 0.95 + hiss
    return x.astype(np.float32)


def synth_segments(segs, rates, cfg, cache_dir):
    jobs = []
    for s, r in zip(segs, rates):
        sc = speaker_cfg(cfg, s["speaker"])
        jobs.append((s["text"], sc["name"], f"{int(round(r)):+d}%", f"{int(sc['pitch']):+d}Hz"))
    from concurrent.futures import ThreadPoolExecutor
    with ThreadPoolExecutor(3) as ex:
        results = list(ex.map(lambda j: tts_cached(*j, cache_dir), jobs))
    out = []
    rng = np.random.default_rng(99)
    for s, (mp3, wb) in zip(segs, results):
        a = decode_audio(mp3)
        t0, t1 = _trim_bounds(a, wb)
        clip = a[int(t0 * SR):int(t1 * SR)].copy()
        if speaker_cfg(cfg, s["speaker"]).get("fx") == "radio":
            clip = radio_fx(clip, rng)
        fade = min(len(clip) // 2, int(0.012 * SR))
        clip[:fade] *= np.linspace(0, 1, fade)
        clip[-fade:] *= np.linspace(1, 0, fade)
        words = [dict(w, offset=w["offset"] - t0) for w in wb]
        out.append((clip, words))
    return out


def segment_pauses(segs, cfg):
    vc = cfg["voice"]
    n = len(segs)
    rules = [(norm_phrase(k), float(v)) for k, v in vc.get("pause_before", {}).items()]
    pauses, kinds = [0.0], ["none"]
    for i in range(1, n):
        s = segs[i]
        pause, kind = vc["pause"], "regular"
        if s.get("inline"):
            pause, kind = vc.get("pause_inline", vc["pause"]), "inline"
        if i == 1:
            pause, kind = vc.get("pause_after_title", pause), "regular"
        ntoks = norm_phrase(s["text"])
        for toks, sec in rules:
            if toks and ntoks[:len(toks)] == toks:
                pause, kind = sec, "key"
        if i == n - 1:
            pause, kind = vc.get("pause_before_last", pause), "key"
        if s.get("pause") is not None:
            pause, kind = s["pause"], "key"
        pauses.append(pause)
        kinds.append(kind)
    return pauses, kinds


VOICE_LEAD = 0.35


def assemble_voice(segs, synth, pauses, cfg):
    pieces, words, spans = [], [], []
    cursor = VOICE_LEAD
    for i, (s, (clip, wb)) in enumerate(zip(segs, synth)):
        cursor += pauses[i]
        pieces.append((cursor, clip))
        disp = align_display(s["text"], wb)
        if s.get("quote") and disp:
            if s.get("q_first"):
                disp[0] = "«" + disp[0]
            if s.get("q_last"):
                disp[-1] = disp[-1].rstrip(".") + "»"
        for w, d in zip(wb, disp):
            words.append({"text": d, "raw": w["text"], "norm": norm(w["text"]),
                          "start": cursor + w["offset"],
                          "end": cursor + w["offset"] + w["duration"],
                          "sent": i, "title": s["is_title"], "speaker": s["speaker"]})
        sc = speaker_cfg(cfg, s["speaker"])
        spans.append({"start": cursor, "end": cursor + len(clip) / SR, "speaker": s["speaker"],
                      "fx": sc.get("fx", "none"), "first": bool(s.get("q_first", True)),
                      "last": bool(s.get("q_last", True)), "text": s["text"]})
        cursor += len(clip) / SR
    voice = np.zeros(int((cursor + 0.1) * SR), dtype=np.float32)
    for st, clip in pieces:
        k = int(st * SR)
        voice[k:k + len(clip)] += clip
    return voice, words, cursor, spans


def end_tail(cfg):
    e = cfg.get("end", {})
    if e.get("card_on_black"):
        return e.get("gap", 0.4) + e.get("fade", 2.6) + e.get("card", 1.8)
    return cfg["duration"]["end_tail"]


def build_voice_fitted(title, story_segs, cfg, cache_dir):
    """Озвучка + подгонка длины ролика под duration.max:
    1) нарастание темпа к финалу (до voice.max_rate), 2) при нехватке — обычные паузы
    ужимаются до voice.min_pause (ключевые паузы не трогаем)."""
    vc = cfg["voice"]
    segs = voice_segments(title, story_segs)
    pauses, kinds = segment_pauses(segs, cfg)
    regular = [i for i, k in enumerate(kinds) if k == "regular"]
    dmax = cfg["duration"]["max"]
    tail = end_tail(cfg)
    fit = cfg["duration"].get("fit", "auto") != "none"
    extra = 0.0
    rates = segment_rates(cfg, segs, 0)
    synth = None
    for attempt in range(4):
        rates = segment_rates(cfg, segs, extra)
        nr = [r for r, s in zip(rates, segs) if s["speaker"] == "narrator"]
        log(f"Озвучка edge-tts: рассказчик {vc['name']} rate {nr[0]:+.0f}% → {max(nr):+.0f}%, "
            f"pitch {vc['pitch']:+d}Hz; паузы {pauses[regular[0]] if regular else vc['pause']:.2f} с")
        synth = synth_segments(segs, rates, cfg, cache_dir)
        lens = [len(c) / SR for c, _ in synth]
        total = VOICE_LEAD + sum(pauses) + tail + sum(lens)
        log(f"  длина ролика: {total:.1f} с")
        if total <= dmax + 0.05 or not fit:
            break
        target = dmax - 0.5
        base_speed = [ln * (1 + r / 100) for ln, r in zip(lens, rates)]

        def predict(ex, pz):
            pr = segment_rates(cfg, segs, ex)
            return VOICE_LEAD + pz + tail + sum(b / (1 + r / 100) for b, r in zip(base_speed, pr))

        fixed_p = sum(p for i, p in enumerate(pauses) if i not in regular)
        cur_p = sum(pauses)
        if predict(extra + 300, cur_p) > target:
            extra = 300
            need = predict(extra, fixed_p)
            per = (target - need) / max(1, len(regular))
            per = max(vc.get("min_pause", 0.3), min(vc["pause"], per))
            for i in regular:
                pauses[i] = per
        else:
            lo, hi = extra, extra + 300
            for _ in range(40):
                mid = (lo + hi) / 2
                if predict(mid, cur_p) > target:
                    lo = mid
                else:
                    hi = mid
            extra = hi
        log(f"  длиннее {dmax} с — подгоняю темп/паузы")
    voice, words, end, spans = assemble_voice(segs, synth, pauses, cfg)
    return voice, words, end, rates, spans


# ════════════════════════════════════════════════════════════════════════════
#  Таймлайн: счётчик, щелчки, эффекты
# ════════════════════════════════════════════════════════════════════════════

def parse_sequence(spec: str):
    """«1-10,20-210:10,211-214» -> [1..10, 20, 30, ... 210, 211..214]"""
    out = []
    for part in spec.split(","):
        part = part.strip()
        step = 1
        if ":" in part:
            part, st = part.split(":")
            step = int(st)
        if "-" in part:
            a, b = [int(x) for x in part.split("-")]
            out += list(range(a, b + 1, step))
        else:
            out.append(int(part))
    return out


def accel_times(t0, t1, n, power=1.8):
    """n моментов на [t0, t1] с ускорением (интервалы сокращаются)."""
    if n <= 0:
        return []
    return [t0 + (t1 - t0) * (1 - (1 - (k + 1) / n) ** (1 / power)) for k in range(n)]


def build_timeline(words, voice_end, spans, cfg, fps):
    cues = cfg.get("cues", {})
    tl = {"fps": fps, "voice_end": voice_end, "spans": spans}
    ecfg = cfg.get("end", {})
    if ecfg.get("card_on_black"):
        tl["fade_start"] = voice_end + ecfg.get("gap", 0.4)
        tl["fade_end"] = tl["fade_start"] + ecfg.get("fade", 2.6)
        T = tl["fade_end"] + ecfg.get("card", 1.8)
        if T < cfg["duration"]["min"]:
            d = cfg["duration"]["min"] - T
            tl["fade_start"] += d
            tl["fade_end"] += d
            T += d
        tl["card_start"] = tl["fade_end"]
    else:
        T = max(voice_end + cfg["duration"]["end_tail"], cfg["duration"]["min"])
        tl["fade_start"] = T - 3.0
        tl["fade_end"] = T - 0.45
        tl["card_start"] = T - cfg["text"]["end_card_seconds"]
    tl["T"] = T

    def ph(phrase, occurrence="first"):
        if not phrase:
            return None
        if phrase == "@last":  # последнее предложение
            last = max(w["sent"] for w in words)
            idx = [i for i, w in enumerate(words) if w["sent"] == last]
            return (idx[0], idx[-1])
        r = find_phrase(words, phrase, occurrence=occurrence)
        if not r:
            log(f"  ! фраза «{phrase}» не найдена в тексте — эффект пропущен")
        return r

    def t_start(r):
        return words[r[0]]["start"]

    def t_end(r):
        return words[r[1]]["end"]

    # ── счётчик и щелчки (логика части 1) ──
    silence_r = ph(cues.get("silence_at"))
    tl["silence_t"] = t_start(silence_r) if silence_r else None
    clicks_r = ph(cues.get("clicks_from"))
    counter_r = ph(cues.get("counter_start"))
    groups = number_groups(words)
    clicks, counter_steps = [], []
    if clicks_r:
        prev_val, prev_end_i = 0, clicks_r[0]
        for g in groups:
            if g["i0"] < clicks_r[0]:
                continue
            if silence_r and g["i0"] >= silence_r[0]:
                break
            w0, w1 = words[g["i0"]], words[g["i1"]]
            in_counter = counter_r is not None and g["i1"] >= counter_r[0]
            if in_counter and prev_val and g["value"] - prev_val > 10:
                lead_i = max(prev_end_i + 1, g["i0"] - 2)
                t0, t1 = words[lead_i]["start"], w1["end"] - 0.02
                times, dt, t = [], 0.030, t1
                while t > t0:
                    times.append(t)
                    t -= dt
                    dt = min(dt / 0.90, 0.24)
                times = sorted(times)
                K = len(times)
                for k, ct in enumerate(times):
                    v = prev_val + int(round((g["value"] - prev_val) * ((k + 1) / K) ** 1.7))
                    counter_steps.append((ct, v))
                    clicks.append((ct, 0.62 + 0.38 * (1 - k / K)))
            else:
                clicks.append((w0["start"] + 0.02, 1.0))
                if in_counter:
                    counter_steps.append((w0["start"] + 0.02, g["value"]))
            if in_counter:
                prev_val = g["value"]
            prev_end_i = g["i1"]

    ccfg = cfg.get("counter", {})
    tl["counter_initial"] = ccfg.get("initial")
    tl["counter_start"] = t_start(counter_r) if counter_r else (0.0 if ccfg.get("initial") is not None else None)
    tl["counter_alert_at"] = ccfg.get("alert_at")
    ar = ph(ccfg.get("alert_after")) if ccfg.get("alert_after") else None
    tl["counter_alert_after"] = t_start(ar) if ar else None
    tl["counter_flash"] = []

    fl = ph(cues.get("monitors_flicker"))
    tl["flicker"] = (t_start(fl), t_end(fl) + 0.35) if fl else None
    si = ph(cues.get("silhouettes"))
    tl["silhouette_t"] = words[si[1]]["start"] if si else None
    cr = ph(cues.get("crowd"))
    tl["crowd_t"] = t_start(cr) if cr else None
    tl["hit_t"] = words[cr[1]]["start"] if cr else None

    # ── сценарий эффектов частей 2/3 ──
    fx = {"interference": [], "glitch": [], "crowd_cells": [], "doors": [], "freeze": [],
          "shake": [], "zoom": None, "static": None, "walkers": [], "semyon": None,
          "silence": [], "hum_cut": None, "drone": None, "radio_hiss": []}
    for e in cfg.get("effects", []):
        typ = e["type"]
        occ = e.get("occurrence", "first")
        if typ == "final_static":
            fx["static"] = (tl["fade_start"] - e.get("lead", 1.2), tl["fade_end"])
            continue
        r = ph(e.get("phrase"), occ)
        if not r and typ not in ("corridor_crowd", "count_out"):
            continue
        if typ == "cam_interference":
            t0 = t_start(r)
            t1 = t_end(r) + e.get("extend", 0.3) if "duration" not in e else t0 + e["duration"]
            fx["interference"].append((e["cam"] - 1, t0, t1))
        elif typ == "radio_hiss":
            fx["radio_hiss"].append((t_start(r), t_start(r) + e.get("duration", 2.0)))
        elif typ == "corridor_crowd":
            vr = ph(e.get("vanish_phrase")) if e.get("vanish_phrase") else None
            fx["crowd_cells"].append({"cam": e["cam"] - 1,
                                      "t_in": None if e.get("initial") else (t_start(r) if r else None),
                                      "fade": e.get("fade", 6.0),
                                      "t_out": t_start(vr) if vr else None})
            if vr:
                fx["interference"].append((e["cam"] - 1, t_start(vr) - 0.1, t_start(vr) + 0.6))
        elif typ == "counter_set":
            t = words[r[1]]["start"] if e.get("at_last_word", True) else t_start(r)
            counter_steps.append((t, e["value"]))
            if e.get("flash"):
                tl["counter_flash"].append(t)
            if e.get("shake"):
                fx["shake"].append((t, e["shake"], e.get("shake_amp", 14)))
            if e.get("click", True):
                clicks.append((t, 1.0))
        elif typ == "shake":
            fx["shake"].append((t_start(r), e.get("duration", 0.8), e.get("amp", 8)))
        elif typ == "hum_cut":
            fx["hum_cut"] = (t_start(r), e.get("tone_hz", 45))
        elif typ == "silence_before":
            t = t_start(r)
            fx["silence"].append((t - e.get("seconds", 1.5), t))
        elif typ == "drone":
            fx["drone"] = t_start(r)
        elif typ == "doors_open":
            fx["doors"].append((e["cam"] - 1, words[r[1]]["start"]))
        elif typ == "freeze":
            fx["freeze"].append((t_start(r), e.get("duration", 1.0)))
        elif typ == "zoom_cam":
            fx["zoom"] = {"cam": e["cam"] - 1, "t": words[r[0]]["start"], "dur": e.get("duration", 0.7)}
        elif typ == "count_out":
            _count_out(e, words, groups, ph, t_start, t_end, tl, fx, counter_steps, clicks, cfg)

    # щелчки турникета — по времени
    tl["clicks"] = sorted(clicks)
    tl["counter_steps"] = sorted(counter_steps)
    tl["counter_final"] = (max(v for _, v in counter_steps) if counter_steps else None) \
        if not cfg.get("counter") else None
    tl["fx"] = fx

    # ── часы ──
    clk = cfg.get("clock", {})
    events = []
    if clk.get("start"):
        c0 = parse_hms(clk["start"])
        for j in clk.get("jumps", []):
            r = ph(j.get("phrase") or j.get("word"))
            if r:
                tj = words[r[1]]["start"]
                events.append(("jump", tj, parse_hms(j["to"])))
                if j.get("glitch"):
                    fx["glitch"].append((tj, j["glitch"]))
        for rr in clk.get("ramps", []):
            a, b = ph(rr["from_phrase"]), ph(rr["to_phrase"])
            if a and b:
                events.append(("ramp", t_start(a), words[b[1]]["start"], parse_hms(rr["to"])))
        events.sort(key=lambda e: e[1])
        tl["clock"] = {"c0": c0, "events": events}
    else:
        clock = None
        for w in words:
            m = re.match(r"^(\d{1,2}):(\d{2})$", w["raw"])
            if m:
                clock = int(m.group(1)) * 3600 + int(m.group(2)) * 60 - w["start"]
                break
        tl["clock"] = {"c0": clock if clock is not None else 3 * 3600, "events": []}

    # ── субтитры ──
    tc = cfg["text"]
    per_line = tc.get("words_per_line")
    per = per_line * tc.get("max_lines", 2) if per_line else int(tc.get("words_per_screen", 4))
    body = [i for i, w in enumerate(words) if not w["title"]]
    by_sent = {}
    for i in body:
        by_sent.setdefault(words[i]["sent"], []).append(i)
    chunks = []
    for sent in sorted(by_sent):
        idx = by_sent[sent]
        n = len(idx)
        k = max(1, math.ceil(n / per))
        base, rem = divmod(n, k)
        pos = 0
        for c in range(k):
            size = base + (1 if c < rem else 0)
            chunks.append(idx[pos:pos + size])
            pos += size
    out = []
    for ci, ch in enumerate(chunks):
        st = words[ch[0]]["start"]
        en = words[ch[-1]]["end"] + 0.45
        if ci + 1 < len(chunks):
            en = min(en, words[chunks[ci + 1][0]]["start"])
        out.append({"words": ch, "start": st, "end": min(en, tl["card_start"])})
    tl["chunks"] = out
    return tl


def _count_out(e, words, groups, ph, t_start, t_end, tl, fx, counter_steps, clicks, cfg):
    """Часть 3: счёт вслух у турникета, счётчик «ВНУТРИ» убывает, люди выходят в двери."""
    seq = parse_sequence(e.get("sequence", "1-10,20-210:10,211-214"))
    start_val = e.get("start", 215)
    nf, bf, bu = ph(e.get("numbers_from")), ph(e.get("burst_from")), ph(e.get("burst_until"))
    ls = ph(e.get("last_step_phrase"))
    if not (nf and bf and bu):
        return
    spoken = [g for g in groups if nf[0] <= g["i0"] < bf[0]]
    steps = []
    for g, v in zip(spoken, seq):
        steps.append((words[g["i0"]]["start"] + 0.02, v, True))
    rest = seq[len(spoken):]
    last_v = rest.pop() if rest else None
    tA = (words[spoken[-1]["i1"]]["end"] + 0.25) if spoken else t_start(nf)
    tB0 = t_start(bf)
    tB1 = words[bu[0] - 1]["end"] + 0.05 if bu[0] > 0 else t_start(bu) - 0.1
    split = e.get("burst_split", 100)
    a_vals = [v for v in rest if v <= split]
    b_vals = [v for v in rest if v > split]
    for t, v in zip(accel_times(tA, tB0 - 0.05, len(a_vals)), a_vals):
        steps.append((t, v, True))
    for k, v in enumerate(b_vals):
        steps.append((tB0 + (tB1 - tB0) * (k + 1) / (len(b_vals) + 0.3), v, False))
    for (t, v, click) in steps:
        counter_steps.append((t, start_val - v))
        if click:
            clicks.append((t, 1.0))
    # очередь щелчков с «двухсот»
    t = tB0
    k = 0
    while t < tB1:
        clicks.append((t, 0.55 + 0.25 * (k % 2)))
        t += 0.034 + 0.008 * math.sin(k * 1.7)
        k += 1
    # Семён: появляется, останавливается, оборачивается, уходит в рассвет
    cam = e.get("cam", 1) - 1
    stop_t = t_start(bu)
    turn_r = ph(e.get("turn_phrase"))
    turn_t = t_start(turn_r) if turn_r else stop_t + 1.5
    exit_t = t_start(ls) if ls else turn_t + 3
    fx["semyon"] = {"cam": cam, "spawn": stop_t - 1.6, "stop": stop_t, "turn": turn_t,
                    "exit": exit_t, "exit_dur": e.get("exit_duration", 2.6)}
    if last_v is not None:
        tl_last = exit_t + e.get("exit_duration", 2.6) * 0.85
        counter_steps.append((tl_last, start_val - last_v))
        clicks.append((tl_last, 1.0))
    # процессия в дверях
    rng = random.Random(77)
    door_t = fx["doors"][-1][1] if fx["doors"] else tA
    t = door_t + 0.5
    while t < tB1 - 0.2:
        dense = t >= tB0 - 0.3
        fx["walkers"].append({"cam": cam, "t": t, "x": rng.uniform(-2.6, 2.6),
                              "h": rng.uniform(1.62, 1.92), "dur": rng.uniform(2.3, 2.9),
                              "seed": rng.randrange(1 << 30)})
        t += rng.uniform(0.18, 0.28) if dense else rng.uniform(0.45, 0.8)


# ════════════════════════════════════════════════════════════════════════════
#  Звук: всё синтезируется в numpy
# ════════════════════════════════════════════════════════════════════════════

def db(x):
    return 10 ** (x / 20)


def rms_db(x):
    return 20 * np.log10(np.sqrt(np.mean(np.square(x, dtype=np.float64))) + 1e-12)


def fft_filter(x, lo=None, hi=None, order=4):
    n = len(x)
    X = np.fft.rfft(x)
    f = np.fft.rfftfreq(n, 1 / SR)
    m = np.ones_like(f)
    if lo:
        m *= 1 / np.sqrt(1 + (lo / np.maximum(f, 1e-3)) ** (2 * order))
    if hi:
        m *= 1 / np.sqrt(1 + (f / hi) ** (2 * order))
    return np.fft.irfft(X * m, n=n).astype(np.float32)


def fft_convolve(x, ir):
    n = len(x) + len(ir) - 1
    nf = 1 << (n - 1).bit_length()
    y = np.fft.irfft(np.fft.rfft(x, nf) * np.fft.rfft(ir, nf), nf)[:len(x)]
    return y.astype(np.float32)


def reverb_ir(sec, decay, rng, lo=None, hi=None):
    n = int(sec * SR)
    t = np.arange(n) / SR
    ir = rng.standard_normal(n).astype(np.float32) * np.exp(-t / decay)
    if lo or hi:
        ir = fft_filter(ir, lo, hi, order=2)
    ir /= np.sqrt(np.sum(ir ** 2)) + 1e-9
    return ir


def smooth_noise(n, rate_hz, rng):
    """Медленная случайная огибающая 0..1."""
    k = max(2, int(n / SR * rate_hz) + 2)
    pts = rng.random(k)
    x = np.linspace(0, k - 1, n)
    i = np.floor(x).astype(int)
    fr = x - i
    fr = fr * fr * (3 - 2 * fr)
    i2 = np.minimum(i + 1, k - 1)
    return (pts[i] * (1 - fr) + pts[i2] * fr).astype(np.float32)


def gen_hum(n, rng, level_db):
    white = rng.standard_normal(n).astype(np.float32)
    X = np.fft.rfft(white)
    f = np.fft.rfftfreq(n, 1 / SR)
    shape = 1 / np.sqrt(np.maximum(f, 20)) * (1 / np.sqrt(1 + (f / 700) ** 6)) \
        * (1 / np.sqrt(1 + (35 / np.maximum(f, 1e-3)) ** 4))
    air = np.fft.irfft(X * shape, n=n).astype(np.float32)
    t = np.arange(n) / SR
    mains = (np.sin(2 * np.pi * 50 * t) * 0.35 + np.sin(2 * np.pi * 100 * t) * 0.5
             + np.sin(2 * np.pi * 150 * t) * 0.15).astype(np.float32)
    air /= np.sqrt(np.mean(air ** 2)) + 1e-9
    mains /= np.sqrt(np.mean(mains ** 2)) + 1e-9
    hum = air + 0.25 * mains
    hum *= 0.85 + 0.3 * smooth_noise(n, 0.15, rng)
    hum *= db(level_db) / (np.sqrt(np.mean(hum ** 2)) + 1e-9)
    dl = int(0.011 * SR)
    left, right = hum, np.concatenate([np.zeros(dl, np.float32), hum[:-dl]])
    return np.stack([left, right], 1)


def one_step(rng):
    n = int(0.25 * SR)
    t = np.arange(n) / SR
    thud = np.sin(2 * np.pi * (75 + rng.random() * 20) * t) * np.exp(-t / 0.045)
    scuff = fft_filter(rng.standard_normal(n).astype(np.float32), 120, 1100) * np.exp(-t / 0.03)
    s = (thud * 0.9 + scuff * 0.6).astype(np.float32)
    return s / (np.max(np.abs(s)) + 1e-9)


def gen_steps(n, rng, level_db, until):
    out = np.zeros((n, 2), np.float32)
    t = 4.0 + rng.random() * 3
    end = (until if until else n / SR) - 2.0
    while t < end:
        count = rng.integers(4, 8)
        pan = rng.uniform(-0.8, 0.8)
        interval = rng.uniform(0.55, 0.68)
        for k in range(count):
            st = t + k * interval + rng.uniform(-0.02, 0.02)
            if st >= end:
                break
            env = math.sin(math.pi * (k + 0.5) / count)
            s = one_step(rng) * env * rng.uniform(0.8, 1.0)
            i0 = int(st * SR)
            i1 = min(n, i0 + len(s))
            out[i0:i1, 0] += s[:i1 - i0] * (1 - pan) / 2
            out[i0:i1, 1] += s[:i1 - i0] * (1 + pan) / 2
        t += count * interval + rng.uniform(7, 13)
    ir = reverb_ir(1.4, 0.45, rng, 80, 2500)
    for c in range(2):
        dry = fft_filter(out[:, c], 60, 900)
        out[:, c] = dry * 0.35 + fft_convolve(dry, ir) * 0.9
    peak = np.max(np.abs(out)) + 1e-9
    return out / peak * db(level_db)


def turnstile_click(rng, gain=1.0):
    n = int(0.07 * SR)
    t = np.arange(n) / SR
    tick = fft_filter(rng.standard_normal(n).astype(np.float32), 1800, 9000) * np.exp(-t / 0.0012)
    f1 = 2100 + rng.uniform(-150, 150)
    ring = np.sin(2 * np.pi * f1 * t) * np.exp(-t / 0.006) * 0.35 \
        + np.sin(2 * np.pi * 860 * t) * np.exp(-t / 0.010) * 0.25
    thunk = np.sin(2 * np.pi * 150 * t) * np.exp(-t / 0.016) * 0.45
    d = int(0.011 * SR)
    s = tick * 1.0 + ring + thunk
    s2 = np.zeros_like(s)
    s2[d:] = (tick[:-d] * 0.45 + thunk[:-d] * 0.25)
    s = (s + s2).astype(np.float32)
    return s / (np.max(np.abs(s)) + 1e-9) * gain


def radio_button(rng):
    """Щелчок тангенты рации: короткий пластиковый «тык» + всплеск эфира."""
    n = int(0.09 * SR)
    t = np.arange(n) / SR
    click = fft_filter(rng.standard_normal(n).astype(np.float32), 2500, 10000) * np.exp(-t / 0.0009)
    body = np.sin(2 * np.pi * 1300 * t) * np.exp(-t / 0.004) * 0.4
    burst = fft_filter(rng.standard_normal(n).astype(np.float32), 400, 4000) * \
        np.exp(-np.maximum(t - 0.012, 0) / 0.03) * (t > 0.012) * 0.35
    s = (click + body + burst).astype(np.float32)
    return s / (np.max(np.abs(s)) + 1e-9)


def squelch(rng):
    n = int(0.16 * SR)
    t = np.arange(n) / SR
    s = fft_filter(rng.standard_normal(n).astype(np.float32), 500, 5000) * np.exp(-t / 0.05)
    return (s / (np.max(np.abs(s)) + 1e-9)).astype(np.float32)


def band_hiss(n, rng, lo=600, hi=6000):
    h = fft_filter(rng.standard_normal(n).astype(np.float32), lo, hi, order=2)
    return h / (np.sqrt(np.mean(h ** 2)) + 1e-9)


def gen_crowd(n, rng, level_db, start):
    out = np.zeros((n, 2), np.float32)
    i0 = int(start * SR)
    m = n - i0
    if m <= SR:
        return out
    acc = np.zeros((m, 2), np.float32)
    for v in range(10):
        src = fft_filter(rng.standard_normal(m).astype(np.float32), 1300, 5200, order=2)
        syl = smooth_noise(m, rng.uniform(3, 6), rng) ** 3
        phrase = (smooth_noise(m, 0.35, rng) > 0.45).astype(np.float32)
        phrase = fft_filter(phrase, None, 3)
        s = src * syl * np.clip(phrase, 0, 1)
        pan = rng.uniform(-0.9, 0.9)
        acc[:, 0] += s * (1 - pan) / 2
        acc[:, 1] += s * (1 + pan) / 2
    murmur = fft_filter(rng.standard_normal(m).astype(np.float32), 110, 420, order=3)
    murmur *= 0.6 + 0.4 * smooth_noise(m, 1.5, rng)
    acc[:, 0] += murmur * 1.6
    acc[:, 1] += murmur * 1.6
    ir = reverb_ir(1.8, 0.6, rng, 150, 4000)
    for c in range(2):
        acc[:, c] = acc[:, c] * 0.4 + fft_convolve(acc[:, c], ir)
    acc *= db(level_db) / (np.sqrt(np.mean(acc ** 2)) + 1e-9)
    fade = np.clip(np.arange(m) / (2.5 * SR), 0, 1)[:, None]
    out[i0:] = acc * fade
    return out


def gen_hit(rng, level_db):
    n = int(3.0 * SR)
    t = np.arange(n) / SR
    freq = 32 + 26 * np.exp(-t / 0.35)
    phase = 2 * np.pi * np.cumsum(freq) / SR
    boom = np.sin(phase) * np.exp(-t / 0.9)
    trans = fft_filter(rng.standard_normal(n).astype(np.float32), None, 350) * np.exp(-t / 0.06) * 3
    s = (boom + trans).astype(np.float32)
    ir = reverb_ir(2.5, 0.8, rng, 40, 1500)
    s = s * 0.8 + fft_convolve(s, ir) * 0.5
    s /= np.max(np.abs(s)) + 1e-9
    return s * db(level_db)


def _add(dst, src, t, gain=1.0, pan=0.0):
    i0 = int(t * SR)
    if i0 >= len(dst) or i0 + len(src) <= 0:
        return
    a = max(0, -i0)
    i0 = max(0, i0)
    i1 = min(len(dst), i0 + len(src) - a)
    seg = src[a:a + i1 - i0] * gain
    if seg.ndim == 1:
        dst[i0:i1, 0] += seg * (1 - pan) / 2 * 2 ** 0.5
        dst[i0:i1, 1] += seg * (1 + pan) / 2 * 2 ** 0.5
    else:
        dst[i0:i1] += seg


def _ramp_gate(n, t0, t1, fade_out=0.02, fade_in=0.15):
    g = np.ones(n, np.float32)
    a, b = int(t0 * SR), int(t1 * SR) if t1 is not None else n
    r1, r2 = int(fade_out * SR), int(fade_in * SR)
    a = max(0, min(n, a))
    b = max(a, min(n, b))
    g[a:min(n, a + r1)] = np.linspace(1, 0, min(n, a + r1) - a)
    g[min(n, a + r1):b] = 0
    if t1 is not None and b < n:
        e = min(n, b + r2)
        g[b:e] = np.linspace(0, 1, e - b)
    return g


def build_audio(voice, tl, cfg, seed=7):
    ac = cfg["audio"]
    fx = tl["fx"]
    rng = np.random.default_rng(seed)
    T = tl["T"]
    n = int(math.ceil(T * SR))
    v = np.zeros(n, np.float32)
    v[:min(n, len(voice))] = voice[:n]
    v = fft_filter(v, 70, None, order=2)
    frames = v[: len(v) // 1024 * 1024].reshape(-1, 1024)
    fr = np.sqrt(np.mean(frames ** 2, 1))
    active = fr > (np.max(fr) * 0.08)
    v_rms = np.sqrt(np.mean(fr[active] ** 2)) if active.any() else 1e-3
    v *= db(ac["voice_rms_db"]) / v_rms
    pk = np.max(np.abs(v))
    if pk > db(-1.5):
        v *= db(-1.5) / pk

    silence = tl["silence_t"]
    cut = fx["hum_cut"][0] if fx["hum_cut"] else None
    steps_until = min([x for x in (silence, cut) if x is not None], default=None)
    bed = gen_hum(n, rng, ac["hum_db"]) + gen_steps(n, rng, ac["steps_db"], steps_until)
    gate = np.ones(n, np.float32)
    if silence:
        gate *= _ramp_gate(n, silence, None, 0.03)
    if cut:
        gate *= _ramp_gate(n, cut, None, 0.015)
    for (a, b) in fx["silence"]:
        gate *= _ramp_gate(n, a, b, 0.015, 0.25)
    bed *= gate[:, None]

    sfx = np.zeros((n, 2), np.float32)
    for (ct, gain) in tl["clicks"]:
        c = turnstile_click(rng, gain) * db(ac["clicks_db"])
        _add(sfx, np.stack([c * 0.9, c], 1), ct)

    # рация: щелчок кнопки перед репликой, шипение под ней, «хвост» после
    for sp in tl["spans"]:
        if sp["fx"] != "radio":
            continue
        if sp["first"]:
            _add(sfx, radio_button(rng), sp["start"] - 0.17, db(ac.get("radio_click_db", -20)))
        if sp["last"]:
            _add(sfx, squelch(rng), sp["end"] + 0.03, db(ac.get("radio_hiss_db", -36) + 8))
        a, b = sp["start"] - (0.17 if sp["first"] else 0.0), sp["end"] + (0.2 if sp["last"] else 0.0)
        m = int((b - a) * SR)
        if m > 0:
            h = band_hiss(m, rng) * db(ac.get("radio_hiss_db", -36))
            f = min(m // 2, int(0.04 * SR))
            h[:f] *= np.linspace(0, 1, f)
            h[-f:] *= np.linspace(1, 0, f)
            _add(sfx, h, a)
    for (a, b) in fx["radio_hiss"]:
        m = int((b - a) * SR)
        h = band_hiss(m, rng, 400, 7000) * db(ac.get("radio_hiss_db", -36) + 5)
        env = np.sin(np.linspace(0, np.pi, m)) ** 0.6
        h *= env * (0.75 + 0.25 * smooth_noise(m, 9, rng))
        _add(sfx, h, a)
        _add(sfx, radio_button(rng), a - 0.05, db(ac.get("radio_click_db", -20)))

    music = bed.copy()
    if tl["crowd_t"]:
        music += gen_crowd(n, rng, ac["crowd_db"], tl["crowd_t"])
        _add(sfx, gen_hit(rng, ac["hit_db"]), tl["hit_t"])
    if fx["hum_cut"]:
        t0, hz = fx["hum_cut"]
        m = n - int(t0 * SR)
        tt = np.arange(m) / SR
        tone = (np.sin(2 * np.pi * hz * tt) + 0.18 * np.sin(2 * np.pi * 2 * hz * tt)).astype(np.float32)
        tone *= db(ac.get("tone_db", -30)) / (np.sqrt(np.mean(tone ** 2)) + 1e-9)
        tone[:int(0.05 * SR)] *= np.linspace(0, 1, int(0.05 * SR))
        _add(music, tone, t0)
    if fx["drone"] is not None:
        t0 = fx["drone"]
        m = n - int(t0 * SR)
        tt = np.arange(m) / SR
        dr = fft_filter(rng.standard_normal(m).astype(np.float32), 30, 140, order=3)
        dr /= np.sqrt(np.mean(dr ** 2)) + 1e-9
        dr += 0.8 * np.sin(2 * np.pi * 52 * tt) + 0.3 * np.sin(2 * np.pi * 104.5 * tt)
        dr *= db(ac.get("drone_db", -32)) / (np.sqrt(np.mean(dr ** 2)) + 1e-9)
        dr *= np.clip(tt / 1.5, 0, 1)
        _add(music, dr.astype(np.float32), t0)
    if fx["static"]:
        a, b = fx["static"]
        m = int((b - a) * SR)
        st = band_hiss(m, rng, 300, 9000)
        crack = (rng.random(m) < 0.002) * rng.standard_normal(m) * 6
        st = (st + crack).astype(np.float32) * np.linspace(0.2, 1, m) ** 1.5
        _add(sfx, st * db(ac.get("static_db", -32)), a)

    fade = np.ones(n, np.float32)
    f0, f1 = int(tl["fade_start"] * SR), int(min(T, tl["fade_end"] + 1.0) * SR)
    f0 = min(f0, n)
    f1 = max(f0 + 1, min(f1, n))
    fade[f0:f1] = np.linspace(1, 0, f1 - f0) ** 1.5
    fade[f1:] = 0
    music *= fade[:, None]
    sfx *= fade[:, None]

    nonvoice = music + sfx
    mix = np.stack([v, v], 1) + nonvoice
    pk = np.max(np.abs(mix))
    if pk > db(-1.0):
        mix = np.tanh(mix / db(-1.0)) * db(-1.0)

    # контроль: голос громче всего остального минимум на 12 dB
    end_v = int(min(T, tl["voice_end"]) * SR)
    nv = nonvoice[:end_v].mean(1)
    bed_rms = rms_db(nv)
    w = SR
    loud = max(rms_db(nv[i:i + w]) for i in range(0, max(1, len(nv) - w), w // 2))
    report = {"voice_rms": ac["voice_rms_db"], "bed_rms": bed_rms, "diff": ac["voice_rms_db"] - bed_rms,
              "loudest_1s": loud}
    return mix.astype(np.float32), report


def write_wav(path, stereo):
    data = (np.clip(stereo, -1, 1) * 32767).astype("<i2")
    with wave.open(str(path), "wb") as w:
        w.setnchannels(2)
        w.setsampwidth(2)
        w.setframerate(SR)
        w.writeframes(data.tobytes())


# ════════════════════════════════════════════════════════════════════════════
#  Картинка: мониторы охраны (генерация)
# ════════════════════════════════════════════════════════════════════════════

DEFAULT_CAMS = [["CAM 01", "ВХОД", "entrance"], ["CAM 02", "ГАЛЕРЕЯ 1", "corridor"],
                ["CAM 03", "АТРИУМ", "hall"], ["CAM 04", "ПАРКОВКА -1", "parking"],
                ["CAM 05", "СЛУЖ. КОРИДОР", "service"], ["CAM 06", "ФУДКОРТ", "food"]]

SCENES = {
    "entrance": dict(rw=9.0, ceil=4.2, depth=22, camh=3.4, cy=0.30, xoff=0.0),
    "corridor": dict(rw=6.0, ceil=4.0, depth=40, camh=3.3, cy=0.28, xoff=-0.8),
    "hall": dict(rw=16.0, ceil=7.0, depth=34, camh=5.5, cy=0.22, xoff=1.2),
    "parking": dict(rw=14.0, ceil=2.8, depth=36, camh=2.5, cy=0.36, xoff=0.5),
    "service": dict(rw=3.2, ceil=3.0, depth=30, camh=2.7, cy=0.30, xoff=0.3),
    "food": dict(rw=14.0, ceil=5.0, depth=26, camh=4.4, cy=0.25, xoff=-1.0),
}


def window_rects():
    m, gap = 22, 16
    ww = (W - 2 * m - gap) // 2
    wh = (H - 2 * m - 2 * gap) // 3
    rects = []
    for r in range(3):
        for c in range(2):
            x0 = m + c * (ww + gap)
            y0 = m + r * (wh + gap)
            rects.append((x0, y0, x0 + ww, y0 + wh))
    return rects


class Cam3D:
    def __init__(self, w, h, f, cx, cy, cam_h, ceil_h):
        self.w, self.h, self.f, self.cx, self.cy = w, h, f, cx, cy
        self.ch, self.ceil = cam_h, ceil_h

    def p(self, x, y, z):
        """x вправо, y — высота от пола, z — вперёд."""
        z = max(z, 0.05)
        return (self.cx + self.f * x / z, self.cy + self.f * (self.ch - y) / z)

    def quad(self, d, pts, fill):
        d.polygon([self.p(*q) for q in pts], fill=fill)

    def line(self, d, a, b, fill, width=1):
        d.line([self.p(*a), self.p(*b)], fill=fill, width=width)


def draw_person(d, cam: Cam3D, x, z, height=1.75, fill=10, rng=None, turn=0.0, eyes=None, step=0.0):
    """Силуэт человека. turn 0..1 — голова поворачивается к камере (eyes — слой для бликов)."""
    rng = rng or random.Random(0)
    fx, fy = cam.p(x, 0, z)
    hx, hy = cam.p(x, height, z)
    s = (fy - hy) / height  # пикселей на метр
    if s <= 0:
        return
    head_r = 0.11 * s
    sh = 0.23 * s * rng.uniform(0.9, 1.1)
    hip = 0.17 * s
    neck_y = hy + 2.1 * head_r
    hshift = head_r * 0.35 * (1 - turn)  # в профиль голова чуть смещена
    d.ellipse([hx - head_r + hshift, hy, hx + head_r + hshift, hy + 2.2 * head_r], fill=fill)
    torso_bottom = hy + 0.52 * (fy - hy)
    d.polygon([(hx - sh * 0.55, neck_y), (hx + sh * 0.55, neck_y), (hx + sh, neck_y + 0.08 * s),
               (hx + hip, torso_bottom), (hx - hip, torso_bottom), (hx - sh, neck_y + 0.08 * s)],
              fill=fill)
    d.polygon([(hx - sh, neck_y + 0.08 * s), (hx - sh * 0.8, neck_y + 0.08 * s),
               (hx - hip * 0.95, torso_bottom + 0.1 * s), (hx - hip * 1.25, torso_bottom + 0.1 * s)],
              fill=fill)
    d.polygon([(hx + sh, neck_y + 0.08 * s), (hx + sh * 0.8, neck_y + 0.08 * s),
               (hx + hip * 0.95, torso_bottom + 0.1 * s), (hx + hip * 1.25, torso_bottom + 0.1 * s)],
              fill=fill)
    sw = 0.06 * s * math.sin(step)  # шаг
    d.polygon([(hx - hip, torso_bottom), (hx - 0.01 * s, torso_bottom), (hx - 0.03 * s + sw, fy),
               (hx - hip * 0.9 + sw, fy)], fill=fill)
    d.polygon([(hx + hip, torso_bottom), (hx + 0.01 * s, torso_bottom), (hx + 0.03 * s - sw, fy),
               (hx + hip * 0.9 - sw, fy)], fill=fill)
    if eyes is not None and turn > 0.6:
        a = int(255 * (turn - 0.6) / 0.4)
        ey = hy + head_r * 1.0
        er = max(1.0, head_r * 0.13)
        for ex in (hx - head_r * 0.38, hx + head_r * 0.38):
            eyes.ellipse([ex - er, ey - er * 0.7, ex + er, ey + er * 0.7], fill=a)


def scene_cam(kind, w, h):
    c = SCENES[kind]
    return Cam3D(w, h, f=w * 0.62, cx=w * 0.5, cy=h * c["cy"], cam_h=c["camh"], ceil_h=c["ceil"]), c


def postprocess_scene(img, w, h):
    img = img.filter(ImageFilter.GaussianBlur(1.1))
    arr = np.asarray(img).astype(np.float32)
    yy, xx = np.mgrid[0:h, 0:w]
    r = np.sqrt(((xx - w / 2) / (w / 2)) ** 2 + ((yy - h * 0.45) / (h / 2)) ** 2)
    arr *= np.clip(1.15 - 0.45 * r ** 1.6, 0.35, 1.2)
    glow = np.asarray(img.filter(ImageFilter.GaussianBlur(10 * w / 507))).astype(np.float32)
    arr = arr + np.clip(glow - 110, 0, None) * 0.6
    return np.clip(arr, 0, 255)


def draw_scene(kind, w, h, seed, people=False, doors_open=False):
    rng = random.Random(seed)
    img = Image.new("L", (w, h), 20)
    d = ImageDraw.Draw(img)
    cam, c = scene_cam(kind, w, h)
    rw, ceil, D, xo = c["rw"] / 2, c["ceil"], c["depth"], c["xoff"]
    zn = 0.3
    L, R = -rw + xo, rw + xo
    cam.quad(d, [(L, 0, zn), (R, 0, zn), (R, 0, D), (L, 0, D)], 92)
    cam.quad(d, [(L, ceil, zn), (R, ceil, zn), (R, ceil, D), (L, ceil, D)], 38)
    cam.quad(d, [(L, 0, zn), (L, ceil, zn), (L, ceil, D), (L, 0, D)], 66)
    cam.quad(d, [(R, 0, zn), (R, ceil, zn), (R, ceil, D), (R, 0, D)], 58)
    cam.quad(d, [(L, 0, D), (R, 0, D), (R, ceil, D), (L, ceil, D)], 44)
    step = 1.2 if kind != "parking" else 2.5
    x = L
    while x <= R:
        cam.line(d, (x, 0, zn), (x, 0, D), 78)
        x += step
    z = 1.0
    while z < D:
        cam.line(d, (L, 0, z), (R, 0, z), 80)
        z += step
    if kind == "parking":
        for x in np.arange(L + 2.5, R, 2.6):
            cam.line(d, (x, 0.01, 4), (x, 0.01, D - 2), 150, 2)
    for z in np.arange(3, D - 1, 3.5 if kind != "service" else 4.5):
        for lx in ([xo] if rw < 4 else [L / 2 + xo / 2, R / 2 + xo / 2]):
            cam.quad(d, [(lx - 0.6, ceil - 0.01, z), (lx + 0.6, ceil - 0.01, z),
                         (lx + 0.6, ceil - 0.01, z + 0.5), (lx - 0.6, ceil - 0.01, z + 0.5)],
                     185 if rng.random() > 0.12 else 70)
    if kind in ("corridor", "hall", "food", "entrance"):
        z = 2.0
        while z < D - 3:
            ln = rng.uniform(3, 6)
            for wx in (L, R):
                lit = rng.random() < 0.3
                cam.quad(d, [(wx, 0.05, z), (wx, 2.9, z), (wx, 2.9, z + ln), (wx, 0.05, z + ln)],
                         110 if lit else 30)
                cam.line(d, (wx, 2.9, z), (wx, 2.9, z + ln), 120, 2)
                cam.line(d, (wx, 0.05, z), (wx, 2.9, z), 100, 2)
            z += ln + rng.uniform(0.5, 1.5)
    if kind == "service":
        for z in np.arange(3, D - 2, 5):
            wx = L if rng.random() < 0.5 else R
            cam.quad(d, [(wx, 0, z), (wx, 2.1, z), (wx, 2.1, z + 0.9), (wx, 0, z + 0.9)], 48)
        cam.line(d, (L + 0.05, 2.5, zn), (L + 0.05, 2.5, D), 90, 3)
        cam.line(d, (L + 0.05, 2.65, zn), (L + 0.05, 2.65, D), 80, 2)
    if kind in ("hall", "parking", "food"):
        for z in np.arange(6, D - 2, 7 if kind != "parking" else 6):
            for cx in ([L / 2 + xo / 2, R / 2 + xo / 2] if kind != "parking" else [L / 3, R / 3]):
                cam.quad(d, [(cx - 0.45, 0, z), (cx + 0.45, 0, z), (cx + 0.45, ceil, z),
                             (cx - 0.45, ceil, z)], 74)
                cam.quad(d, [(cx - 0.45, 0, z), (cx - 0.45, ceil, z), (cx - 0.45, ceil, z + 0.9),
                             (cx - 0.45, 0, z + 0.9)], 60)
    if kind == "food":
        for _ in range(14):
            tx, tz = rng.uniform(L + 1, R - 1), rng.uniform(4, D - 4)
            cam.quad(d, [(tx - 0.5, 0.75, tz - 0.4), (tx + 0.5, 0.75, tz - 0.4),
                         (tx + 0.5, 0.75, tz + 0.4), (tx - 0.5, 0.75, tz + 0.4)], 120)
            cam.line(d, (tx, 0, tz), (tx, 0.75, tz), 50, 2)
    if kind == "hall":
        cam.quad(d, [(xo - 1.0, 0, 10), (xo + 1.0, 0, 10), (xo + 1.0, 5.5, 22), (xo - 1.0, 5.5, 22)], 70)
        cam.line(d, (xo - 1.0, 1.0, 10), (xo - 1.0, 6.5, 22), 140, 2)
        cam.line(d, (xo + 1.0, 1.0, 10), (xo + 1.0, 6.5, 22), 140, 2)
    if kind == "entrance":
        if doors_open:
            # распахнутые двери: проём залит рассветом, свет ложится на пол
            cam.quad(d, [(-4.0, 0, D), (4.0, 0, D), (4.0, 2.7, D), (-4.0, 2.7, D)], 250)
            cam.quad(d, [(-4.0, 0.01, D), (4.0, 0.01, D), (5.5, 0.01, D - 9), (-5.5, 0.01, D - 9)], 150)
            for dx in (-4.0, 4.0):  # створки, развёрнутые к стенам
                cam.quad(d, [(dx, 0, D), (dx * 1.05, 0, D - 1.6), (dx * 1.05, 2.6, D - 1.6), (dx, 2.6, D)], 60)
        else:
            for dx in (-3, -1, 1, 3):
                cam.quad(d, [(dx - 0.9, 0, D), (dx + 0.9, 0, D), (dx + 0.9, 2.6, D), (dx - 0.9, 2.6, D)], 26)
                cam.line(d, (dx, 0, D), (dx, 2.6, D), 110, 2)
        for tx in (-2.4, -0.8, 0.8, 2.4):
            cam.quad(d, [(tx - 0.12, 0, 6), (tx + 0.12, 0, 6), (tx + 0.12, 1.0, 6), (tx - 0.12, 1.0, 6)], 150)
            cam.quad(d, [(tx - 0.12, 1.0, 6), (tx + 0.12, 1.0, 6), (tx + 0.12, 1.0, 6.8),
                         (tx - 0.12, 1.0, 6.8)], 170)
            cam.line(d, (tx + 0.12, 0.9, 6.3), (tx + 0.75, 0.9, 6.3), 175, 3)
    if people:
        prng = random.Random(seed * 31 + 7)
        count = prng.randint(3, 6)
        spots = sorted([(prng.uniform(L + 0.6, R - 0.6), prng.uniform(4.5, min(D - 2, 16)))
                        for _ in range(count)], key=lambda p: -p[1])
        for (px, pz) in spots:
            draw_person(d, cam, px, pz, prng.uniform(1.65, 1.9), fill=prng.randint(4, 14), rng=prng)
    return postprocess_scene(img, w, h)


def corridor_rows_mask(kind, w, h, seed):
    """Маска: неподвижные силуэты, выстроенные рядами по обеим сторонам коридора."""
    cam, c = scene_cam(kind, w, h)
    rw, D, xo = c["rw"] / 2, c["depth"], c["xoff"]
    L, R = -rw + xo, rw + xo
    img = Image.new("L", (w, h), 0)
    d = ImageDraw.Draw(img)
    rng = random.Random(seed)
    spots = []
    for side in (L + 0.42, R - 0.42):
        z = 3.2
        while z < D - 2:
            spots.append((side + rng.uniform(-0.06, 0.06), z))
            z += rng.uniform(1.0, 1.3)
    for (x, z) in sorted(spots, key=lambda p: -p[1]):
        draw_person(d, cam, x, z, rng.uniform(1.68, 1.88), fill=255, rng=rng)
    img = img.filter(ImageFilter.GaussianBlur(1.3 * w / 507))
    return np.asarray(img).astype(np.float32) / 255.0


def single_figure_mask(kind, w, h, seed, z_back=4.0):
    cam, c = scene_cam(kind, w, h)
    img = Image.new("L", (w, h), 0)
    d = ImageDraw.Draw(img)
    draw_person(d, cam, c["xoff"], c["depth"] - z_back, 1.8, fill=255, rng=random.Random(seed))
    img = img.filter(ImageFilter.GaussianBlur(1.5 * w / 507))
    return np.asarray(img).astype(np.float32) / 255.0


def tint_rgb(L, tint, expo):
    return L[..., None] * tint[None, None, :] * expo + np.array([6, 10, 7], np.float32)


def build_monitor_bases(cfg, seed=11):
    tint = np.array(cfg["colors"]["monitor_tint"], np.float32)
    rects = window_rects()
    cams = cfg.get("cameras", DEFAULT_CAMS)
    wins = []
    bases = []
    for people in (False, True):
        full = np.zeros((H, W, 3), np.float32)
        full[:] = (9, 11, 10)
        for k, ((x0, y0, x1, y1), (_, _, kind)) in enumerate(zip(rects, cams)):
            w, h = x1 - x0, y1 - y0
            L = draw_scene(kind, w, h, seed + k, people=people)
            expo = 0.78 + 0.16 * ((k * 37) % 7) / 6
            if not people:
                wins.append({"L": L, "expo": expo, "kind": kind, "seed": seed + k})
            full[y0:y1, x0:x1] = tint_rgb(L, tint, expo)
            full[y0:y0 + 2, x0:x1] = 70
            full[y1 - 2:y1, x0:x1] = 40
            full[y0:y1, x0:x0 + 2] = 55
            full[y0:y1, x1 - 2:x1] = 45
        bases.append(np.clip(full, 0, 255).astype(np.uint8))
    return bases[0], bases[1], rects, wins


# ════════════════════════════════════════════════════════════════════════════
#  Рендер кадров (в нескольких процессах)
# ════════════════════════════════════════════════════════════════════════════

CTX: dict = {}


class Fonts:
    def __init__(self, cfg):
        self.bold_path = first_existing(cfg["fonts"]["bold"])
        self.mono_path = first_existing(cfg["fonts"]["mono"])
        self._cache = {}

    def bold(self, size):
        key = ("b", int(size))
        if key not in self._cache:
            self._cache[key] = ImageFont.truetype(self.bold_path, int(size)) if self.bold_path \
                else ImageFont.load_default()
        return self._cache[key]

    def mono(self, size):
        key = ("m", int(size))
        if key not in self._cache:
            self._cache[key] = ImageFont.truetype(self.mono_path, int(size)) if self.mono_path \
                else ImageFont.load_default()
        return self._cache[key]


def text_w(font, s, stroke=0):
    b = font.getbbox(s, stroke_width=stroke)
    return b[2] - b[0]


def wrap_words(words, font, maxw):
    lines, cur = [], []
    for w in words:
        trial = " ".join(cur + [w])
        if cur and text_w(font, trial) > maxw:
            lines.append(" ".join(cur))
            cur = [w]
        else:
            cur.append(w)
    if cur:
        lines.append(" ".join(cur))
    return lines


def make_title_layer(title, fonts: Fonts, cfg):
    col = cfg["colors"]
    tc = cfg["text"]
    t = title.upper() if tc["uppercase"] else title
    pale = tc.get("title_style") == "pale"
    size = tc.get("title_size", 150)
    words = t.replace(".", ". ").split()
    while True:
        f = fonts.bold(size)
        lines = wrap_words(words, f, 920)
        if max(text_w(f, ln, 10) for ln in lines) <= 960 or size < 60:
            break
        size -= 8
    img = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    lh = size * 1.08
    y = H * tc.get("title_y", 0.45) - lh * (len(lines) - 1) / 2
    for ln in lines:
        if pale:
            pc = tuple(col.get("title_pale", [218, 226, 218]))
            d.text((W / 2, y), ln, font=f, fill=(*pc, 255), anchor="mm",
                   stroke_width=4, stroke_fill=(10, 14, 12, 200))
        else:
            d.text((W / 2, y), ln, font=f, fill=(*col["subtitle"], 255), anchor="mm",
                   stroke_width=10, stroke_fill=(*col["stroke"], 255))
        y += lh
    if not pale:
        ly = int(y - lh / 2 + size * 0.35)
        d.rectangle([W / 2 - 170, ly, W / 2 + 170, ly + 6], fill=(*col["highlight"], 255))
    arr = np.asarray(img).astype(np.float32) / 255.0
    if pale:
        arr[..., 3] *= tc.get("title_opacity", 0.55)
    return arr


def make_end_card(cfg, fonts: Fonts):
    col = cfg["colors"]
    tc = cfg["text"]
    lines = tc["end_card"].split("\n")
    img = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    big_size = tc.get("end_card_size", 118)
    small = fonts.bold(84)
    big = fonts.bold(big_size)
    while text_w(big, lines[0], 6) > 780 and big_size > 60:
        big_size -= 6
        big = fonts.bold(big_size)
    bw, bh = 860, 400
    x0, y0 = (W - bw) / 2, H * 0.5 - bh / 2
    d.rounded_rectangle([x0, y0, x0 + bw, y0 + bh], radius=36, fill=(12, 6, 6, 235),
                        outline=(*col["highlight"], 255), width=6)
    if len(lines) == 1:
        d.text((W / 2, H * 0.5), lines[0], font=big, fill=(*col["subtitle"], 255), anchor="mm",
               stroke_width=6, stroke_fill=(0, 0, 0, 255))
    else:
        d.text((W / 2, H * 0.5 - 70), lines[0], font=big, fill=(*col["highlight"], 255),
               anchor="mm", stroke_width=6, stroke_fill=(0, 0, 0, 255))
        rest = " ".join(lines[1:])
        d.text((W / 2, H * 0.5 + 80), rest.upper() if tc["uppercase"] else rest, font=small,
               fill=(*col["subtitle"], 255), anchor="mm", stroke_width=6, stroke_fill=(0, 0, 0, 255))
    return np.asarray(img).astype(np.float32) / 255.0


def display_word(w, cfg):
    keep = cfg["text"]["keep_punct"]
    s = w["text"]
    s = "".join(ch for ch in s if ch.isalnum() or ch in keep or ch in "-–—'’")
    s = s.strip("-–— ")
    if not s:
        s = w["raw"]
    return s.upper() if cfg["text"]["uppercase"] else s


def chunk_layout(ci):
    """Раскладка слов субтитра по строкам: центры слов и размер шрифта."""
    cache = CTX.setdefault("layouts", {})
    if ci in cache:
        return cache[ci]
    cfg, fonts, words = CTX["cfg"], CTX["fonts"], CTX["words"]
    tc = cfg["text"]
    ch = CTX["tl"]["chunks"][ci]
    texts = [display_word(words[i], cfg) for i in ch["words"]]
    size = tc["subtitle_size"]
    maxw = tc.get("subtitle_maxw", 900)
    per_line = tc.get("words_per_line")
    stroke = max(4, size // 12)
    while True:
        f = fonts.bold(size)
        stroke = max(4, size // 12)
        ws = [text_w(f, t, stroke) for t in texts]
        sp = size * 0.34
        n = len(ws)
        if per_line:
            if n <= per_line:
                lines = [list(range(n))]
            else:
                k = math.ceil(n / 2)
                lines = [list(range(k)), list(range(k, n))]
        else:
            total = sum(ws) + sp * (n - 1)
            if total <= maxw:
                lines = [list(range(n))]
            else:
                best = None
                for k in range(1, n):
                    a = sum(ws[:k]) + sp * (k - 1)
                    b = sum(ws[k:]) + sp * (n - k - 1)
                    if best is None or max(a, b) < best[0]:
                        best = (max(a, b), k)
                lines = [list(range(best[1])), list(range(best[1], n))]
        widest = max(sum(ws[i] for i in ln) + sp * (len(ln) - 1) for ln in lines)
        if widest <= maxw or size <= 50:
            break
        size -= 6
    lh = size * 1.16
    cy0 = H * tc["subtitle_y"] - lh * (len(lines) - 1) / 2
    pos = [None] * len(ws)
    for li, ln in enumerate(lines):
        lw = sum(ws[i] for i in ln) + sp * (len(ln) - 1)
        x = W / 2 - lw / 2
        for i in ln:
            pos[i] = (x + ws[i] / 2, cy0 + li * lh)
            x += ws[i] + sp
    cache[ci] = (texts, pos, size, stroke)
    return cache[ci]


def draw_subtitles(d: ImageDraw.ImageDraw, t):
    tl, words, cfg, fonts = CTX["tl"], CTX["words"], CTX["cfg"], CTX["fonts"]
    col = cfg["colors"]
    for ci, ch in enumerate(tl["chunks"]):
        if not (ch["start"] <= t < ch["end"]):
            continue
        texts, pos, size, stroke = chunk_layout(ci)
        idx = ch["words"]
        cur = None
        for k, wi in enumerate(idx):
            nxt = words[idx[k + 1]]["start"] if k + 1 < len(idx) else words[wi]["end"] + 0.15
            if words[wi]["start"] <= t < nxt:
                cur = k
        age = t - ch["start"]
        for k, (txt, (x, y)) in enumerate(zip(texts, pos)):
            if k == cur:
                ws = t - words[idx[k]]["start"]
                scale = 1 + 0.08 * math.exp(-ws / 0.09) + 0.025 * math.sin(2 * math.pi * 4.5 * ws)
                glow = 0.5 + 0.5 * math.sin(2 * math.pi * 4.5 * ws)
                hc = col["highlight"]
                fill = (hc[0], int(min(255, hc[1] + 40 * glow)), int(min(255, hc[2] + 30 * glow)))
                f = fonts.bold(round(size * scale))
                d.text((x, y), txt, font=f, fill=fill, anchor="mm",
                       stroke_width=stroke + 1, stroke_fill=tuple(col["stroke"]))
            else:
                sc = 1.0 + 0.06 * math.exp(-age / 0.07)
                f = fonts.bold(round(size * sc))
                d.text((x, y), txt, font=f, fill=tuple(col["subtitle"]), anchor="mm",
                       stroke_width=stroke, stroke_fill=tuple(col["stroke"]))


COUNTER_BOX = (40, 100, 400, 286)


def counter_value(t):
    tl = CTX["tl"]
    if tl["counter_start"] is None or t < tl["counter_start"]:
        return None, None
    val, last_t = tl.get("counter_initial"), None
    for (ct, v) in tl["counter_steps"]:
        if ct <= t:
            val, last_t = v, ct
        else:
            break
    if val is None:
        val, last_t = 1, tl["counter_start"]
    if last_t is None:
        last_t = -10.0
    return val, last_t


def counter_alert(val, t):
    tl = CTX["tl"]
    if tl["counter_alert_after"] is not None and t >= tl["counter_alert_after"]:
        return True
    if tl["counter_alert_at"] is not None:
        return val >= tl["counter_alert_at"]
    final = tl["counter_final"]
    return final is not None and val >= final


def draw_counter(d: ImageDraw.ImageDraw, t):
    val, last_t = counter_value(t)
    if val is None or CTX.get("zoom_full"):
        return
    cfg, fonts = CTX["cfg"], CTX["fonts"]
    col = cfg["colors"]
    x0, y0, x1, y1 = COUNTER_BOX
    age = t - last_t
    if counter_alert(val, t):
        pulse = 0.5 + 0.5 * math.sin(2 * math.pi * 1.2 * t)
        c = col["counter_alert"]
        fill = tuple(int(v * (0.75 + 0.25 * pulse)) for v in c)
        border = fill
    else:
        k = math.exp(-age / 0.18)
        a, b = np.array(col["counter_alert"]), np.array(col["counter"])
        fill = tuple(int(v) for v in b + (a - b) * k)
        border = (90, 120, 95)
    width = 3
    for ft in CTX["tl"]["counter_flash"]:
        if 0 <= t - ft < 0.9:
            k = math.exp(-(t - ft) / 0.25)
            width = 3 + int(9 * k)
            border = tuple(int(min(255, v + (255 - v) * k * 0.5)) for v in col["counter_alert"])
    d.rectangle([x0, y0, x1, y1], outline=border, width=width)
    d.text((x0 + 22, y0 + 18), cfg["cues"].get("counter_label", "ВНУТРИ:"), font=fonts.mono(36),
           fill=tuple(col["hud"]))
    if age < 0.12:
        d.ellipse([x1 - 34, y0 + 22, x1 - 18, y0 + 38], fill=tuple(col["counter_alert"]))
    sc = 1 + 0.08 * math.exp(-age / 0.1)
    d.text((x0 + 22, y1 - 20), str(val), font=fonts.bold(round(108 * sc)), fill=fill, anchor="ls",
           stroke_width=3, stroke_fill=(0, 0, 0))


def clock_seconds(t):
    clk = CTX["tl"]["clock"]
    t_ref, c_ref = 0.0, clk["c0"]
    for ev in clk["events"]:
        if ev[0] == "jump":
            if t >= ev[1]:
                t_ref, c_ref = ev[1], ev[2]
        else:
            _, t0, t1, to = ev
            if t >= t1:
                t_ref, c_ref = t1, to
            elif t >= t0:
                c0 = c_ref + (t0 - t_ref)
                return c0 + (to - c0) * (t - t0) / (t1 - t0)
    return c_ref + (t - t_ref)


def fmt_clock(t):
    s = int(math.floor(clock_seconds(t))) % 86400
    return f"{s // 3600:02d}:{s // 60 % 60:02d}:{s % 60:02d}"


def frame_rng(fi):
    return np.random.default_rng(CTX["seed"] * 100003 + fi)


def monitor_events():
    """Расписание случайных мерцаний одного окна."""
    rng = random.Random(CTX["seed"] + 5)
    ev, t = [], 2.5
    T = CTX["tl"]["T"]
    while t < T:
        t += rng.uniform(2.5, 6.0)
        ev.append((t, rng.uniform(0.15, 0.5), rng.randrange(6)))
    return ev


def bg_time(t):
    """Время «картинки» с учётом заморозок (все ячейки замирают)."""
    shift = 0.0
    for (t0, dur) in CTX["tl"]["fx"]["freeze"]:
        if t0 <= t < t0 + dur:
            return t0 - shift, True
        if t >= t0 + dur:
            shift += dur
    return t - shift, False


def in_any(spans, t):
    return any(a <= t < b for (_, a, b) in spans)


def window_dynamic(k, t, tb):
    """Если окно k сейчас меняется (силуэты, двери, процессия) — вернуть L-массив и оттенок."""
    fx = CTX["tl"]["fx"]
    win = CTX["wins"][k]
    L = None
    tint = CTX["tint"]
    expo = win["expo"]
    for cc in fx["crowd_cells"]:
        if cc["cam"] != k:
            continue
        if cc["t_in"] is None:
            a = 1.0
        else:
            a = float(np.clip((t - cc["t_in"]) / cc["fade"], 0, 1)) if t >= cc["t_in"] else 0.0
            a = a * a * (3 - 2 * a)
        if cc["t_out"] is not None and t >= cc["t_out"]:
            a = 0.0
        if a > 0:
            base = win["L"] if L is None else L
            L = base * (1 - CTX["crowd_mask"][k] * CTX["cfg"].get("scene", {}).get("crowd_darkness", 0.42) * a)
    for (dk, td) in fx["doors"]:
        if dk != k or tb < td:
            continue
        o = float(np.clip((tb - td) / 0.6, 0, 1))
        base = win["L"] if L is None else L
        L = base * (1 - o) + CTX["door_open_L"] * o
        cool = np.array(CTX["cfg"]["colors"].get("door_tint", [0.78, 0.92, 1.05]), np.float32)
        tint = tint * (1 - o) + cool * o
        expo = expo * (1 + 0.18 * o)
        flash = max(0.0, 1 - (tb - td) / 0.25)
        if flash > 0:
            L = L + 90 * flash
    walkers = [wk for wk in fx["walkers"] if wk["cam"] == k and wk["t"] <= tb < wk["t"] + wk["dur"]]
    sem = fx["semyon"] if fx["semyon"] and fx["semyon"]["cam"] == k else None
    if sem and not (sem["spawn"] <= t < sem["exit"] + sem["exit_dur"]):
        sem = None
    if walkers or sem:
        base = win["L"] if L is None else L
        h, w = base.shape
        cam, c = scene_cam(win["kind"], w, h)
        D = c["depth"]
        mimg = Image.new("L", (w, h), 0)
        md = ImageDraw.Draw(mimg)
        eimg = Image.new("L", (w, h), 0)
        ed = ImageDraw.Draw(eimg)
        figs = []
        for wk in walkers:
            p = (tb - wk["t"]) / wk["dur"]
            z = 3.4 + (D - 0.6 - 3.4) * p
            a = 1.0 if p < 0.82 else max(0.0, (1 - p) / 0.18)
            figs.append((z, wk["x"], wk["h"], a, 0.0, (tb - wk["t"]) * 9, wk["seed"]))
        if sem:
            z_stop = 6.9
            if t < sem["stop"]:
                p = (tb - sem["spawn"]) / max(0.1, (sem["stop"] - sem["spawn"]))
                z, a, stepph = 3.4 + (z_stop - 3.4) * min(1.0, p), 1.0, tb * 9
            elif t < sem["exit"]:
                z, a, stepph = z_stop, 1.0, 0.0
            else:
                p = (t - sem["exit"]) / sem["exit_dur"]
                z = z_stop + (D - 0.6 - z_stop) * p
                a = 1.0 if p < 0.8 else max(0.0, (1 - p) / 0.2)
                stepph = t * 9
            turn = float(np.clip((t - sem["turn"]) / 0.8, 0, 1)) if t < sem["exit"] else \
                max(0.0, 1 - (t - sem["exit"]) / 0.4)
            figs.append((z, 0.3, 1.82, a, turn, stepph, 4242))
        for (z, x, hh, a, turn, stepph, sd) in sorted(figs, key=lambda f: -f[0]):
            draw_person(md, cam, x, z, hh, fill=int(255 * a), rng=random.Random(sd),
                        turn=turn, eyes=ed if turn > 0 else None, step=stepph)
        m = np.asarray(mimg.filter(ImageFilter.GaussianBlur(1.0))).astype(np.float32) / 255.0
        L = base * (1 - 0.93 * m) + 4 * m
        if sem and turn > 0.6:
            e = np.asarray(eimg.filter(ImageFilter.GaussianBlur(0.8))).astype(np.float32)
            L = L + e * 0.55
    if L is None:
        return None
    return L, tint, expo


def background_generated(t, fi, rng):
    tl = CTX["tl"]
    fx = tl["fx"]
    tb, frozen = bg_time(t)
    fb = int(round(tb * tl["fps"]))
    if frozen:
        rng = frame_rng(fb)
    sil_t = tl["silhouette_t"]
    sil = sil_t is not None and 0 <= t - sil_t < (1 / 30) - 1e-6
    base = CTX["base_sil"] if sil else CTX["base"]
    f = base.astype(np.float32)
    rects = CTX["rects"]
    for k, (x0, y0, x1, y1) in enumerate(rects):
        dyn = window_dynamic(k, t, tb) if CTX["dyn_windows"][k] else None
        if dyn is not None:
            L, tint, expo = dyn
            f[y0 + 2:y1 - 2, x0 + 2:x1 - 2] = tint_rgb(L[2:-2, 2:-2], tint, expo)
    # зум камеры на весь экран (финал части 3)
    z = fx["zoom"]
    CTX["zoom_full"] = False
    if z and t >= z["t"]:
        p = min(1.0, (t - z["t"]) / z["dur"])
        p = p * p * (3 - 2 * p)
        x0, y0, x1, y1 = rects[z["cam"]]
        rx0, ry0 = x0 * (1 - p), y0 * (1 - p)
        rx1, ry1 = x1 + (W - x1) * p, y1 + (H - y1) * p
        img = CTX["zoom_img"]
        if p < 1.0:
            ww, hh = max(2, int(rx1 - rx0)), max(2, int(ry1 - ry0))
            arr = np.asarray(img.resize((ww, hh), Image.BILINEAR)).astype(np.float32)
            xa, ya = int(rx0), int(ry0)
            f[ya:ya + hh, xa:xa + ww] = arr[:H - ya, :W - xa]
        else:
            f = CTX["zoom_arr"].copy()
            CTX["zoom_full"] = True
    bank = CTX["noise"]
    nz = bank[int(rng.integers(len(bank)))]
    if rng.random() < 0.5:
        nz = nz[::-1]
    f += nz[..., None] * 1.0
    f *= CTX["scan"][:, None, None]
    band_y = (tb * 140) % (H + 400) - 200
    f *= (1 + 0.10 * np.exp(-((CTX["yy"] - band_y) / 60) ** 2))[:, None, None]
    hidden = set()
    if CTX["zoom_full"]:
        return f, hidden, tb
    flk = tl["flicker"]
    global_flick = flk is not None and flk[0] <= t < flk[1]
    for wi, (x0, y0, x1, y1) in enumerate(rects):
        g = 1.0 + (rng.uniform(-0.03, 0.03) if not frozen else 0.0)
        tear = 0
        heavy = in_any([s for s in fx["interference"] if s[0] == wi], t)
        if global_flick:
            r = rng.random()
            g = 0.0 if r < 0.22 else (rng.uniform(1.25, 1.6) if r < 0.4 else rng.uniform(0.2, 1.0))
            tear = int(rng.integers(-40, 40)) if rng.random() < 0.4 else 0
        elif heavy:
            r = rng.random()
            g = 0.08 if r < 0.25 else rng.uniform(0.5, 1.5)
            tear = int(rng.integers(-60, 60))
        elif not frozen:
            for (et, ed, ew) in CTX["events"]:
                if ew == wi and et <= t < et + ed:
                    r = rng.random()
                    g = 0.05 if r < 0.3 else rng.uniform(0.4, 1.35)
                    tear = int(rng.integers(-25, 25)) if rng.random() < 0.5 else 0
        if g != 1.0:
            f[y0 + 2:y1 - 2, x0 + 2:x1 - 2] *= g
        if g < 0.1:
            hidden.add(wi)
        if tear:
            ty = int(rng.integers(y0 + 20, y1 - 80))
            th = int(rng.integers(20, 70))
            f[ty:ty + th, x0 + 2:x1 - 2] = np.roll(f[ty:ty + th, x0 + 2:x1 - 2], tear, axis=1)
        if heavy:
            reg = f[y0 + 2:y1 - 2, x0 + 2:x1 - 2]
            nz2 = bank[int(rng.integers(len(bank)))][y0 + 2:y1 - 2, x0 + 2:x1 - 2]
            reg += nz2[..., None] * 3.2
            for _ in range(int(rng.integers(2, 6))):  # белые полосы помех
                by = int(rng.integers(0, reg.shape[0] - 8))
                reg[by:by + int(rng.integers(2, 9))] += rng.uniform(40, 120)
    return f, hidden, tb


def background_video(t, fi, rng):
    tl = CTX["tl"]
    raw = CTX["reader"].stdout.read(W * H * 3)
    if len(raw) < W * H * 3:
        raw = CTX.get("last_raw", bytes(W * H * 3))
    CTX["last_raw"] = raw
    f = np.frombuffer(raw, np.uint8).reshape(H, W, 3).astype(np.float32)
    bank = CTX["noise"]
    f += bank[int(rng.integers(len(bank)))][..., None] * 1.1
    f *= CTX["scan"][:, None, None]
    sil_t = tl["silhouette_t"]
    if sil_t is not None and 0 <= t - sil_t < (1 / 30) - 1e-6:
        f *= (1 - CTX["sil_alpha"][..., None] * 0.9)
    flk = tl["flicker"]
    if flk is not None and flk[0] <= t < flk[1]:
        r = rng.random()
        f *= 0.05 if r < 0.25 else (rng.uniform(1.2, 1.5) if r < 0.4 else rng.uniform(0.3, 1.0))
    else:
        for (et, ed, _) in CTX["events"]:
            if et <= t < et + ed * 0.5:
                f *= rng.uniform(0.55, 1.1)
                break
    CTX["zoom_full"] = False
    return f, set(), t


def draw_hud(d, t, tb, hidden, rng):
    fonts, cfg = CTX["fonts"], CTX["cfg"]
    hc = cfg.get("hud", {})
    hud = tuple(cfg["colors"]["hud"])
    red = tuple(cfg["colors"]["counter_alert"])
    clock = fmt_clock(tb)
    date = hc.get("date", "2026-11-24")
    colon_blink = hc.get("colon_blink", True)
    cams = cfg.get("cameras", DEFAULT_CAMS)
    if CTX["mode"] == "generated" and CTX.get("zoom_full"):
        cam, name, _ = cams[CTX["tl"]["fx"]["zoom"]["cam"]]
        f = fonts.mono(40)
        d.text((40, 36), f"{cam}  {name}", font=f, fill=hud)
        d.text((40, 88), f"{date}  {clock}", font=f, fill=hud)
        if (tb % 1.0) < 0.5:
            d.ellipse([W - 200, 44, W - 172, 72], fill=red)
        d.text((W - 160, 36), "REC", font=f, fill=hud)
        return
    if CTX["mode"] == "generated":
        f = fonts.mono(24)
        for wi, (x0, y0, x1, y1) in enumerate(CTX["rects"]):
            if wi in hidden:
                continue
            cam, name, _ = cams[wi]
            d.text((x0 + 14, y0 + 12), f"{cam}  {name}", font=f, fill=hud)
            ph = (wi * 0.37) % 1 if colon_blink else 0.0
            blink = ((tb + ph) % 1.0) < 0.5
            tc = clock if (blink or not colon_blink) else clock.replace(":", " ")
            if colon_blink and rng.random() < 0.015:
                continue
            d.text((x0 + 14, y0 + 42), f"{date}  {tc}", font=f, fill=hud)
            if blink:
                d.ellipse([x1 - 104, y0 + 16, x1 - 88, y0 + 32], fill=red)
            d.text((x1 - 80, y0 + 12), "REC", font=f, fill=hud)
    else:
        f = fonts.mono(34)
        blink = (t % 1.0) < 0.5
        d.text((44, H - 120), "CAM 07  КОРИДОР", font=f, fill=hud)
        d.text((44, H - 76), f"{date}  {clock if blink else clock.replace(':', ' ')}", font=f, fill=hud)
        if blink:
            d.ellipse([W - 190, 82, W - 166, 106], fill=red)
        d.text((W - 150, 76), "REC", font=f, fill=hud)


def post_effects(arr, t, rng):
    """Глитч (RGB-сдвиг, разрывы), тряска, финальные помехи. None — если ничего нет."""
    fx = CTX["tl"]["fx"]
    g = 0.0
    for (t0, dur) in fx["glitch"]:
        if t0 - 0.05 <= t < t0 + dur:
            g = max(g, 1.0 - max(0.0, t - t0) / dur * 0.6)
    st = 0.0
    if fx["static"] and fx["static"][0] <= t < fx["static"][1]:
        st = (t - fx["static"][0]) / (fx["static"][1] - fx["static"][0])
    sh = 0.0
    for (t0, dur, amp) in fx["shake"]:
        if t0 <= t < t0 + dur:
            sh = max(sh, amp * (1 - (t - t0) / dur))
    if g == 0 and st == 0 and sh == 0:
        return None
    f = arr.astype(np.float32)
    if g > 0 or st > 0.4:
        amt = g if g > 0 else (st - 0.4)
        dx = int(6 + 26 * amt * rng.random())
        f[..., 0] = np.roll(f[..., 0], dx, axis=1)
        f[..., 2] = np.roll(f[..., 2], -dx, axis=1)
        for _ in range(int(3 + 9 * amt)):
            y = int(rng.integers(0, H - 40))
            hgt = int(rng.integers(6, 60))
            f[y:y + hgt] = np.roll(f[y:y + hgt], int(rng.integers(-120, 120) * amt), axis=1)
    if st > 0:
        nz = CTX["noise"][int(rng.integers(len(CTX["noise"])))]
        f += nz[..., None] * (1.5 + 5 * st)
        for _ in range(int(2 + 10 * st)):
            y = int(rng.integers(0, H - 10))
            f[y:y + int(rng.integers(2, 10))] += rng.uniform(30, 140) * st
    if sh > 0:
        dx, dy = int(rng.uniform(-sh, sh)), int(rng.uniform(-sh, sh))
        f = np.roll(np.roll(f, dx, axis=1), dy, axis=0)
    return np.clip(f, 0, 255).astype(np.uint8)


def render_frame(fi):
    tl, cfg = CTX["tl"], CTX["cfg"]
    fps = tl["fps"]
    t = fi / fps
    rng = frame_rng(fi)
    if CTX["mode"] == "generated":
        f, hidden, tb = background_generated(t, fi, rng)
    else:
        f, hidden, tb = background_video(t, fi, rng)
    f *= CTX["vignette"][..., None]
    f *= CTX["sub_shade"][:, None, None]
    if tl["counter_start"] is not None and t >= tl["counter_start"] and not CTX.get("zoom_full"):
        x0, y0, x1, y1 = COUNTER_BOX
        f[y0:y1, x0:x1] *= 0.25
    tc = cfg["text"]
    title_s = tc["title_seconds"]
    if t < title_s:
        fo = tc.get("title_fade", 0.45)
        a = 1.0 if t < title_s - fo else max(0.0, (title_s - t) / fo)
        if tc.get("title_style") == "pale":
            a *= min(1.0, t / 0.25 + 0.4)
        else:
            f *= (1 - 0.45 * a)
        lay = CTX["title"]
        al = lay[..., 3:4] * a
        f = f * (1 - al) + lay[..., :3] * 255 * al
    img = Image.fromarray(np.clip(f, 0, 255).astype(np.uint8))
    d = ImageDraw.Draw(img)
    draw_hud(d, t, tb, hidden, rng)
    draw_counter(d, t)
    post = post_effects(np.asarray(img), t, rng)
    if post is not None:
        img = Image.fromarray(post)
        d = ImageDraw.Draw(img)
    draw_subtitles(d, t)
    fs, fe = tl["fade_start"], tl["fade_end"]
    if t < fs:
        return np.asarray(img)
    # финал: красное свечение по краям нарастает, кадр уходит в чёрное, плашка
    f = np.asarray(img).astype(np.float32)
    k = min(1.0, (t - fs) / max(0.1, fe - fs))
    glow = min(1.0, k * 1.6) * (0.85 + 0.15 * math.sin(2 * math.pi * 1.3 * t))
    f += CTX["edge"][..., None] * np.array(cfg["colors"]["edge_glow"], np.float32) * glow
    bright = max(0.0, 1 - min(1.0, k / 0.92) ** 1.3)
    f *= bright
    if t >= tl["card_start"]:
        a = min(1.0, (t - tl["card_start"]) / 0.25)
        lay = CTX["end_card"]
        al = lay[..., 3:4] * a
        f = f * (1 - al) + lay[..., :3] * 255 * al
    return np.clip(f, 0, 255).astype(np.uint8)


def prepare_ctx(cfg, tl, words, mode, bg_prepped, title, seed=1337):
    CTX.clear()
    CTX.update(cfg=cfg, tl=tl, words=words, mode=mode, seed=seed, bg_prepped=bg_prepped)
    CTX["fonts"] = Fonts(cfg)
    yy, xx = np.mgrid[0:H, 0:W].astype(np.float32)
    r = np.sqrt(((xx - W / 2) / (W / 2)) ** 2 + ((yy - H / 2) / (H / 2)) ** 2)
    CTX["vignette"] = np.clip(1.08 - 0.42 * r ** 2.0, 0.25, 1.0).astype(np.float32)
    CTX["edge"] = (np.clip((r - 0.62) / 0.75, 0, 1) ** 1.4).astype(np.float32)
    CTX["yy"] = np.arange(H, dtype=np.float32)
    tc = cfg["text"]
    if tc.get("sub_shade") == "gradient":
        y = CTX["yy"] / H
        a = np.clip((y - tc.get("gradient_from", 0.5)) / 0.3, 0, 1)
        CTX["sub_shade"] = (1 - tc.get("gradient_strength", 0.62) * a * a * (3 - 2 * a)).astype(np.float32)
    else:
        sy = H * tc["subtitle_y"]
        CTX["sub_shade"] = (1 - 0.5 * np.exp(-((CTX["yy"] - sy) / 150) ** 4)).astype(np.float32)
    scan = np.ones(H, np.float32)
    scan[::3] = 0.84
    CTX["scan"] = scan
    rng = np.random.default_rng(seed)
    bank = []
    for _ in range(10):
        coarse = rng.normal(0, 9, (H // 2, W // 2)).astype(np.float32)
        coarse = np.repeat(np.repeat(coarse, 2, 0), 2, 1)
        fine = rng.normal(0, 6, (H, W)).astype(np.float32)
        bank.append((coarse + fine).astype(np.float32))
    CTX["noise"] = bank
    CTX["events"] = monitor_events()
    CTX["title"] = make_title_layer(title, CTX["fonts"], cfg)
    CTX["end_card"] = make_end_card(cfg, CTX["fonts"])
    CTX["tint"] = np.array(cfg["colors"]["monitor_tint"], np.float32)
    for kind, ov in cfg.get("scene", {}).get("overrides", {}).items():
        SCENES[kind] = dict(SCENES[kind], **ov)
    if mode == "generated":
        CTX["base"], CTX["base_sil"], CTX["rects"], CTX["wins"] = build_monitor_bases(cfg)
        fx = tl["fx"]
        dyn = [False] * 6
        CTX["crowd_mask"] = {}
        for cc in fx["crowd_cells"]:
            k = cc["cam"]
            dyn[k] = True
            w = CTX["wins"][k]
            hh, ww = w["L"].shape
            CTX["crowd_mask"][k] = corridor_rows_mask(w["kind"], ww, hh, 555 + k)
        for (k, _) in fx["doors"]:
            dyn[k] = True
            w = CTX["wins"][k]
            hh, ww = w["L"].shape
            CTX["door_open_L"] = draw_scene(w["kind"], ww, hh, w["seed"], doors_open=True)
        for wk in fx["walkers"]:
            dyn[wk["cam"]] = True
        if fx["semyon"]:
            dyn[fx["semyon"]["cam"]] = True
        CTX["dyn_windows"] = dyn
        if fx["zoom"]:
            w = CTX["wins"][fx["zoom"]["cam"]]
            Lz = draw_scene(w["kind"], W, H, w["seed"])
            m = single_figure_mask(w["kind"], W, H, 91, z_back=cfg.get("scene", {}).get("zoom_figure_back", 13))
            Lz = Lz * (1 - 0.9 * m) + 4 * m
            rgb = np.clip(tint_rgb(Lz, CTX["tint"], w["expo"]), 0, 255)
            CTX["zoom_arr"] = rgb.astype(np.float32)
            CTX["zoom_img"] = Image.fromarray(rgb.astype(np.uint8))
    else:
        CTX["rects"] = []
        CTX["sil_alpha"] = silhouette_alpha_fullframe(seed)


def silhouette_alpha_fullframe(seed):
    img = Image.new("L", (W, H), 0)
    d = ImageDraw.Draw(img)
    cam = Cam3D(W, H, f=W * 0.62, cx=W / 2, cy=H * 0.32, cam_h=2.2, ceil_h=3.0)
    prng = random.Random(seed)
    spots = sorted([(prng.uniform(-2.4, 2.4), prng.uniform(3.5, 14)) for _ in range(7)],
                   key=lambda p: -p[1])
    for (x, z) in spots:
        draw_person(d, cam, x, z, prng.uniform(1.65, 1.9), fill=255, rng=prng)
    img = img.filter(ImageFilter.GaussianBlur(3))
    return np.asarray(img).astype(np.float32) / 255.0


def worker_segment(args):
    seg_idx, f0, f1, out_path = args
    fps = CTX["tl"]["fps"]
    if CTX["mode"] == "video":
        CTX["reader"] = subprocess.Popen(
            ["ffmpeg", "-v", "error", "-ss", f"{f0 / fps:.6f}", "-i", CTX["bg_prepped"],
             "-frames:v", str(f1 - f0), "-f", "rawvideo", "-pix_fmt", "rgb24", "pipe:1"],
            stdout=subprocess.PIPE)
    enc = subprocess.Popen(
        ["ffmpeg", "-v", "error", "-y", "-f", "rawvideo", "-pix_fmt", "rgb24",
         "-s", f"{W}x{H}", "-r", str(fps), "-i", "pipe:0",
         "-vf", "scale=out_color_matrix=bt709:out_range=tv,format=yuv420p",
         "-c:v", "libx264", "-preset", "medium", "-crf", "21", "-maxrate", "10M" if fps <= 30 else "14M",
         "-bufsize", "20M", "-profile:v", "high",
         "-level", "4.2", "-colorspace", "bt709", "-color_primaries", "bt709",
         "-color_trc", "bt709", "-g", str(fps * 2), "-threads", "2", str(out_path)],
        stdin=subprocess.PIPE)
    for fi in range(f0, f1):
        enc.stdin.write(render_frame(fi).tobytes())
    enc.stdin.close()
    enc.wait()
    if CTX["mode"] == "video":
        CTX["reader"].stdout.close()
        CTX["reader"].wait()
    if enc.returncode != 0:
        raise RuntimeError(f"ffmpeg упал на сегменте {seg_idx}")
    return seg_idx


def prep_bg_video(src: Path, T, fps, cfg, out: Path):
    tint = cfg["colors"]["bg_video_tint"]
    vf = (f"scale={W}:{H}:force_original_aspect_ratio=increase,crop={W}:{H},fps={fps},"
          f"format=gray,format=rgb24,"
          f"colorchannelmixer=rr={tint[0]}:gg={tint[1]}:bb={tint[2]},"
          f"eq=contrast=1.08")
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-stream_loop", "-1", "-i", str(src),
                    "-t", f"{T + 0.5:.3f}", "-an", "-vf", vf, "-c:v", "libx264",
                    "-preset", "veryfast", "-crf", "14", "-pix_fmt", "yuv444p", str(out)],
                   check=True)


# ════════════════════════════════════════════════════════════════════════════
#  main
# ════════════════════════════════════════════════════════════════════════════

def main():
    ap = argparse.ArgumentParser(description="Хоррор-шортс «Ночная смена»: озвучка + субтитры + атмосфера")
    ap.add_argument("story", nargs="?", default="story.txt")
    ap.add_argument("part", nargs="?", default=None,
                    help="сценарий части: part2 -> parts/part2.json (или путь к .json)")
    ap.add_argument("-o", "--output", default=None)
    ap.add_argument("--fps", type=int, default=30, choices=[30, 60])
    ap.add_argument("--preview", type=float, default=0,
                    help="отрендерить только первые N секунд (пробная версия)")
    ap.add_argument("--config", default=str(ROOT / "config.json"))
    ap.add_argument("--bg", default=str(ROOT / "bg"), help="папка с фоновыми видео")
    ap.add_argument("--workers", type=int, default=max(1, (os.cpu_count() or 2)))
    ap.add_argument("--seed", type=int, default=None, help="зерно случайности (фон, звук)")
    ap.add_argument("--keep-temp", action="store_true")
    args = ap.parse_args()

    for tool in ("ffmpeg", "ffprobe"):
        if not shutil.which(tool):
            sys.exit(f"Не найден {tool}. Установите ffmpeg (https://ffmpeg.org) и повторите.")
    try:
        __import__("edge_tts")
    except ImportError:
        log("Устанавливаю edge-tts…")
        subprocess.run([sys.executable, "-m", "pip", "install", "-q", "edge-tts"], check=True)
    _patch_edge_tts_ssl()

    cfg = load_config(Path(args.config), args.part)
    story_path = Path(args.story)
    suffix = f"_{Path(args.part).stem}" if args.part else ""
    out = Path(args.output or (f"preview{suffix}.mp4" if args.preview else f"output{suffix}.mp4"))
    fps = args.fps
    seed = args.seed if args.seed is not None else cfg.get("seed", 1337)
    cache_dir = ROOT / ".cache" / "tts"
    cache_dir.mkdir(parents=True, exist_ok=True)

    title, segs = parse_story(story_path, cfg)
    n_q = sum(1 for s in segs if s["speaker"] != "narrator")
    log(f"История «{title}»: {len(segs)} фраз, из них реплик персонажей: {n_q}")

    voice, words, voice_end, rates, spans = build_voice_fitted(title, segs, cfg, cache_dir)
    log(f"  голос: {voice_end:.1f} с, слов с таймингами: {len(words)}")

    tl = build_timeline(words, voice_end, spans, cfg, fps)
    T = tl["T"]
    render_T = min(T, args.preview) if args.preview else T

    log("Синтез звука: вентиляция, шаги, турникет, рация, тона…")
    mix, rep = build_audio(voice, tl, cfg, seed=seed)
    log(f"  голос {rep['voice_rms']:.1f} dBFS RMS, всё остальное {rep['bed_rms']:.1f} dBFS RMS → "
        f"разница {rep['diff']:.1f} dB {'(OK ≥12)' if rep['diff'] >= 12 else '(!) меньше 12'}; "
        f"самая громкая секунда фона {rep['loudest_1s']:.1f} dBFS")

    tmp = Path(tempfile.mkdtemp(prefix="horror_"))
    mode = "generated"
    try:
        wav = tmp / "audio.wav"
        write_wav(wav, mix[: int(render_T * SR)])
        bg_dir = Path(args.bg)
        vids = sorted([p for p in bg_dir.glob("*") if p.suffix.lower() in (".mp4", ".mov")]) \
            if bg_dir.is_dir() else []
        bg_prepped = None
        if vids:
            src = random.Random(seed if args.seed is not None else None).choice(vids)
            log(f"Фон: {src.name} → 9:16, холодная гамма, -35% яркости, зерно")
            bg_prepped = tmp / "bg.mp4"
            prep_bg_video(src, render_T, fps, cfg, bg_prepped)
            mode = "video"
        else:
            log("Фон: генерирую мониторы охраны (2×3)")

        log("Подготовка рендера…")
        prepare_ctx(cfg, tl, words, mode, str(bg_prepped) if bg_prepped else None, title, seed)
        n_frames = int(round(render_T * fps))
        n_seg = max(1, min(args.workers * 2, n_frames // fps))
        bounds = np.linspace(0, n_frames, n_seg + 1).astype(int)
        jobs = [(i, int(bounds[i]), int(bounds[i + 1]), tmp / f"seg_{i:03d}.mp4")
                for i in range(n_seg) if bounds[i + 1] > bounds[i]]
        log(f"Рендер {n_frames} кадров ({W}x{H}, {fps} fps) в {args.workers} процессах…")
        t0 = time.time()
        ctx = mp.get_context("fork") if hasattr(os, "fork") else mp.get_context()
        if ctx.get_start_method() == "fork" and args.workers > 1:
            with ctx.Pool(args.workers) as pool:
                for k, _ in enumerate(pool.imap_unordered(worker_segment, jobs), 1):
                    log(f"  сегмент {k}/{len(jobs)} готов")
        else:
            for k, j in enumerate(jobs, 1):
                worker_segment(j)
                log(f"  сегмент {k}/{len(jobs)} готов")
        log(f"  кадры готовы за {time.time() - t0:.0f} с")

        lst = tmp / "list.txt"
        lst.write_text("".join(f"file '{j[3].as_posix()}'\n" for j in jobs), encoding="utf-8")
        subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "concat", "-safe", "0", "-i", str(lst),
                        "-i", str(wav), "-map", "0:v", "-map", "1:a", "-c:v", "copy",
                        "-c:a", "aac", "-b:a", "192k", "-ar", str(SR), "-t", f"{render_T:.3f}",
                        "-movflags", "+faststart", str(out)], check=True)
    finally:
        if args.keep_temp:
            log(f"Временные файлы: {tmp}")
        else:
            shutil.rmtree(tmp, ignore_errors=True)

    dur = float(subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration",
                                "-of", "csv=p=0", str(out)], capture_output=True, text=True).stdout)
    log(f"Готово: {out.resolve()}  ({dur:.1f} с, {out.stat().st_size / 1e6:.1f} МБ)")
    if mode == "generated":
        log("Подсказка: положите свои .mp4/.mov в папку bg/ — фон возьмётся оттуда.")


if __name__ == "__main__":
    main()
