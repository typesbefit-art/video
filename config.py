"""
Настройки генератора. Меняйте здесь голос, цвета, тайминги и громкости —
generate.py трогать не нужно. Текст истории — в story.txt (первая строка = заголовок).
"""

# ---------------------------------------------------------------- ВИДЕО
WIDTH, HEIGHT = 1080, 1920
DEFAULT_FPS = 30
TARGET_MIN_SEC = 50.0      # допустимая длина ролика; если выходит за рамки,
TARGET_MAX_SEC = 65.0      # паузы (а при необходимости и темп) подстраиваются автоматически
CRF = 19                   # качество H.264 (меньше = лучше и тяжелее)

# ---------------------------------------------------------------- ГОЛОС (edge-tts)
VOICE = "ru-RU-DmitryNeural"   # женский вариант: "ru-RU-SvetlanaNeural"
RATE = "-8%"
PITCH = "-4Hz"
VOICE_TITLE = False            # True = диктор читает заголовок (добавит ~2 с к ролику)
PAUSE_SENTENCE = 0.6           # пауза после каждого предложения, с
PAUSE_BEFORE_LAST = 1.2        # пауза перед последней фразой, с
VOICE_RMS_DB = -15.5           # громкость голоса (RMS активной речи, dBFS)
VOICE_REVERB = True            # лёгкая "комнатная" реверберация голоса

# ---------------------------------------------------------------- ЗВУК
DRONE_DB = -28.0               # громкость дрона
SFX_DB = -33.0                 # скрипы / шорохи
HEARTBEAT_DB = -30.0           # сердцебиение (на пике)
HEARTBEAT_BPM = (58, 132)      # от / до (к кульминации)
STINGER_DB = -14.0             # удар на последней фразе (до авто-дакинга)
VOICE_OVER_MUSIC_DB = 12.0     # голос всегда громче музыки минимум на столько dB
TAIL_SILENCE = 1.0             # секунд тишины в самом конце

# ---------------------------------------------------------------- ФОН
BG_DIR = "bg"                  # сюда кладите свои .mp4 / .mov
BG_VIDEO_BRIGHTNESS = 0.65     # яркость фонового видео (0.65 = приглушить на 35%)
BG_TOP_COLOR = (10, 16, 36)    # градиент генерируемого фона (верх)
BG_BOTTOM_COLOR = (1, 2, 7)    # (низ)
FOG_COLOR = (88, 104, 135)     # цвет тумана
FOG_STRENGTH = 0.55
FLICKER_COLOR = (170, 190, 230)

# ---------------------------------------------------------------- ТЕКСТ
FONT_CANDIDATES = [
    "fonts/Inter-ExtraBold.otf",
    "fonts/Inter-ExtraBold.ttf",
    "/usr/share/fonts/opentype/inter/Inter-ExtraBold.otf",
    "/usr/share/fonts/truetype/inter/Inter-ExtraBold.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
    "C:/Windows/Fonts/arialbd.ttf",
    "/System/Library/Fonts/Supplemental/Arial Bold.ttf",
]
SUB_FONT_SIZE = 92
SUB_Y = 0.65                   # вертикальное положение субтитров (доля высоты)
SUB_MAX_WORDS = 4              # слов на экране (3–4)
SUB_UPPERCASE = False
SUB_COLOR = (255, 255, 255)
SUB_HIGHLIGHT = (235, 32, 42)  # текущее слово / последнее предложение
SUB_STROKE = 8
SUB_STROKE_COLOR = (0, 0, 0)
SUB_PULSE = 0.13               # амплитуда пульсации размера слова

TITLE_DURATION = 1.5
TITLE_FONT_SIZE = 128
TITLE_COLOR = (255, 255, 255)
TITLE_ACCENT = (235, 32, 42)

FINAL_SHAKE_SEC = 3.0          # дрожание + красное свечение в конце
SHAKE_PX = 14
GLOW_COLOR = (255, 18, 24)

OUTRO_TEXT_1 = "Часть 2?"
OUTRO_TEXT_2 = "Подписывайся"
OUTRO_DURATION = 1.5
OUTRO_GAP = 0.4                # пауза между последним словом и плашкой
