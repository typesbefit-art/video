/**
 * Проверяет, что озвучка лежит на месте. Запускается перед dev / render / align.
 */
import {existsSync, statSync} from 'node:fs';
import {resolve} from 'node:path';

const file = resolve(__dirname, '..', 'public', 'voiceover.mp3');

if (!existsSync(file) || statSync(file).size === 0) {
  console.error(
    [
      '',
      '  ⛔  Не найден файл озвучки: public/voiceover.mp3',
      '',
      '  Положите готовую озвучку из ElevenLabs (≈54.9 сек) в папку public/',
      '  под именем voiceover.mp3 и запустите команду ещё раз.',
      '  После этого рекомендуется уточнить тайминги: npm run align',
      '',
    ].join('\n'),
  );
  process.exit(1);
}
