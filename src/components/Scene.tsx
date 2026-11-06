import React from 'react';
import {AbsoluteFill, Img, interpolate, staticFile, useCurrentFrame, useVideoConfig} from 'remotion';
import {ColorGrade, Vignette} from './Effects';
import type {SceneData} from '../lib/timing';

export type SceneProps = {
  scene: SceneData;
  index: number;
  /** Длительность сцены без «хвоста» перехода. */
  duration: number;
};

/**
 * Обёртка сцены: плавный вход (кроссфейд поверх предыдущей сцены),
 * цветокоррекция, виньетка и ПЛЕЙСХОЛДЕР под пользовательскую иллюстрацию.
 *
 * Плейсхолдер: если в scenes.json у сцены задано поле "image"
 * (например "illustrations/hook.png" → файл public/illustrations/hook.png),
 * то вместо процедурного фона `art` показывается ваша картинка с Ken Burns.
 * Слой `overlay` (частицы, надписи, эффекты) остаётся в любом случае.
 */
export const Scene: React.FC<{
  scene: SceneData;
  art: React.ReactNode;
  overlay?: React.ReactNode;
  fadeIn?: number;
  grade?: {tint?: string; amount?: number; lift?: string};
  vignette?: number;
  background?: string;
}> = ({scene, art, overlay, fadeIn = 12, grade, vignette = 0.8, background = '#07090d'}) => {
  const frame = useCurrentFrame();
  const {durationInFrames} = useVideoConfig();
  const opacity = fadeIn > 0 ? interpolate(frame, [0, fadeIn], [0, 1], {extrapolateRight: 'clamp'}) : 1;

  return (
    <AbsoluteFill style={{opacity, background, overflow: 'hidden'}}>
      {scene.image ? <IllustrationImage src={scene.image} duration={durationInFrames} /> : art}
      <ColorGrade {...grade} />
      {overlay}
      <Vignette strength={vignette} />
    </AbsoluteFill>
  );
};

/** Пользовательская иллюстрация (из public/) с медленным наездом камеры. */
export const IllustrationImage: React.FC<{src: string; duration: number}> = ({src, duration}) => {
  const frame = useCurrentFrame();
  const zoom = interpolate(frame, [0, duration], [1.04, 1.16]);
  const y = interpolate(frame, [0, duration], [0, -30]);
  return (
    <AbsoluteFill style={{transform: `translateY(${y}px) scale(${zoom})`}}>
      <Img src={staticFile(src)} style={{width: '100%', height: '100%', objectFit: 'cover'}} />
    </AbsoluteFill>
  );
};
