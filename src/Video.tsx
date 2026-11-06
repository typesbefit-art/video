import React from 'react';
import {AbsoluteFill, Audio, Sequence, staticFile} from 'remotion';
import {FilmGrain, FilmScratches, Vignette} from './components/Effects';
import type {SceneProps} from './components/Scene';
import {SafeZoneOverlay, Subtitles} from './components/Subtitles';
import {SCENES, sceneFrames} from './lib/timing';
import {S1Hook} from './scenes/S1Hook';
import {S2Seconds} from './scenes/S2Seconds';
import {S3Hour} from './scenes/S3Hour';
import {S4Days} from './scenes/S4Days';
import {S5Months} from './scenes/S5Months';
import {S6Year} from './scenes/S6Year';
import {S7Recovery} from './scenes/S7Recovery';
import {S8Final} from './scenes/S8Final';

/** Компоненты сцен по id из scenes.json. */
const SCENE_COMPONENTS: Record<string, React.FC<SceneProps>> = {
  hook: S1Hook,
  seconds: S2Seconds,
  hour: S3Hour,
  days: S4Days,
  months: S5Months,
  year: S6Year,
  recovery: S7Recovery,
  final: S8Final,
};

/** Сколько кадров сцена «живёт» после своей границы, пока поверх проявляется следующая. */
export const TRANSITION = 12;

export type VideoProps = {showSafeZone: boolean};

export const Video: React.FC<VideoProps> = ({showSafeZone}) => {
  return (
    <AbsoluteFill style={{background: '#000'}}>
      {SCENES.map((scene, i) => {
        const Comp = SCENE_COMPONENTS[scene.id];
        if (!Comp) throw new Error(`Нет компонента для сцены "${scene.id}" (scenes.json)`);
        const {from, duration} = sceneFrames(i);
        const isLast = i === SCENES.length - 1;
        // Сцена стартует ровно на своей границе из scenes.json; следующая
        // проявляется поверх неё (кроссфейд), поэтому продлеваем на TRANSITION.
        return (
          <Sequence key={scene.id} from={from} durationInFrames={duration + (isLast ? 0 : TRANSITION)} name={`${i + 1}. ${scene.id}`}>
            <Comp scene={scene} index={i} duration={duration} />
          </Sequence>
        );
      })}

      {/* общий «плёночный» слой */}
      <FilmGrain opacity={0.16} />
      <FilmScratches />
      <Vignette strength={0.35} />

      <Subtitles />
      {showSafeZone && <SafeZoneOverlay />}

      <Audio src={staticFile('voiceover.mp3')} />
    </AbsoluteFill>
  );
};
