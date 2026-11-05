import React from "react";
import { Audio, Sequence, staticFile } from "remotion";
import { getStaticFiles } from "@remotion/studio";

/** Есть ли файл в public/. Отсутствующие файлы просто пропускаем — без падений. */
export const hasPublicFile = (name: string): boolean => {
  try {
    return getStaticFiles().some((f) => f.name === name);
  } catch {
    return false;
  }
};

/** <Audio>, который ничего не рендерит, если файла нет в public/. */
export const SafeAudio: React.FC<{ file: string; volume?: number; loop?: boolean }> = ({
  file,
  volume = 1,
  loop,
}) => {
  if (!hasPublicFile(file)) return null;
  return <Audio src={staticFile(file)} volume={volume} loop={loop} />;
};

export type SfxCue = { frame: number; name: string; volume?: number };

/** Звуковые эффекты из public/sfx/<name>.mp3 на нужных кадрах. */
export const SfxTrack: React.FC<{ cues: SfxCue[] }> = ({ cues }) => (
  <>
    {cues.map((c, i) =>
      hasPublicFile(`sfx/${c.name}.mp3`) ? (
        <Sequence key={`${c.name}-${c.frame}-${i}`} from={c.frame} layout="none" name={`sfx: ${c.name}`}>
          <Audio src={staticFile(`sfx/${c.name}.mp3`)} volume={c.volume ?? 1} />
        </Sequence>
      ) : null,
    )}
  </>
);
