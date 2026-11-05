export const WIDTH = 1080;
export const HEIGHT = 1920;
export const FPS = 30;
export const DURATION = 25 * FPS; // 750 кадров

export const ACCENT = '#00E5FF';
export const WHITE = '#FFFFFF';
export const FONT = "'InterBlack', 'Montserrat', 'Inter', sans-serif";

// Безопасная зона TikTok для текста: 250..1500 px по вертикали
export const SAFE_TOP = 250;
export const SAFE_BOTTOM = 1500;

// Тайминг сцен (в кадрах)
export const SCENES = {
  hook: {from: 0, duration: 3 * FPS},
  fact1: {from: 3 * FPS, duration: 7 * FPS},
  fact2: {from: 10 * FPS, duration: 7 * FPS},
  fact3: {from: 17 * FPS, duration: 6 * FPS},
  outro: {from: 23 * FPS, duration: 2 * FPS},
};

// Звёзды замирают на 1 секунду внутри сцены факта 3, затем вспышка
export const FREEZE_START = SCENES.fact3.from + 30;
export const FREEZE_LEN = FPS;
export const FLASH_AT = FREEZE_START + FREEZE_LEN;
