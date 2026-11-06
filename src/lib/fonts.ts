import {continueRender, delayRender} from 'remotion';
// Montserrat с кириллицей лежит в node_modules (@fontsource) — рендер не зависит от сети.
import '@fontsource/montserrat/600.css';
import '@fontsource/montserrat/800.css';
import '@fontsource/montserrat/900.css';

export const FONT = `'Montserrat', 'Arial Black', 'Helvetica Neue', Arial, sans-serif`;

// Ждём загрузки шрифтов, чтобы первый кадр не отрисовался системным шрифтом.
if (typeof document !== 'undefined') {
  const handle = delayRender('Загрузка Montserrat');
  Promise.all(
    ['600', '800', '900'].map((w) => document.fonts.load(`${w} 64px Montserrat`, 'ЯДЕРНАЯ ЗИМА abc')),
  )
    .catch(() => undefined)
    .finally(() => continueRender(handle));
}
