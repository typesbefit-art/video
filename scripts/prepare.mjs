// Если есть assets/music.mp3 — копируем в public/, иначе убираем старую копию (ролик без звука)
import {copyFileSync, existsSync, rmSync} from 'node:fs';

const src = 'assets/music.mp3';
const dst = 'public/music.mp3';
if (existsSync(src)) {
  copyFileSync(src, dst);
  console.log('🎵 Музыка найдена: assets/music.mp3 будет тихим фоном');
} else {
  rmSync(dst, {force: true});
  console.log('🔇 assets/music.mp3 нет — рендерим без звука');
}
