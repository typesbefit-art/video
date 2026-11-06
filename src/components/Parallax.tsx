import React, {createContext, useContext} from 'react';
import {AbsoluteFill} from 'remotion';
import {H, W} from '../lib/math';

export type Camera = {
  /** Наезд: 1 — без увеличения. Ближние слои увеличиваются сильнее. */
  zoom: number;
  /** Панорама в пикселях (для слоя depth=1). */
  x: number;
  y: number;
};

export type Shake = {x: number; y: number; r: number};

const CameraContext = createContext<Camera>({zoom: 1, x: 0, y: 0});

/**
 * Параллакс-сцена: камера двигается, а каждый <Layer depth> смещается
 * пропорционально своей глубине. depth 0 — небо (почти неподвижно),
 * 1 — передний план. Тряска (shake) применяется ко всему кадру одинаково.
 */
export const Parallax: React.FC<{
  camera: Camera;
  shake?: Shake;
  focus?: {x: number; y: number};
  children: React.ReactNode;
}> = ({camera, shake, focus = {x: W / 2, y: H / 2}, children}) => {
  const s = shake ?? {x: 0, y: 0, r: 0};
  return (
    <CameraContext.Provider value={camera}>
      <AbsoluteFill
        style={{
          transform: `translate(${s.x}px, ${s.y}px) rotate(${s.r}deg) scale(${s.x || s.y ? 1.04 : 1})`,
          transformOrigin: `${focus.x}px ${focus.y}px`,
        }}
      >
        {children}
      </AbsoluteFill>
    </CameraContext.Provider>
  );
};

/** Один слой параллакса. Содержимое рисуется в координатах 1080×1920 (SVG). */
export const Layer: React.FC<{
  depth: number;
  children: React.ReactNode;
  /** true — дети являются содержимым SVG; false — обычный HTML. */
  svg?: boolean;
  style?: React.CSSProperties;
  origin?: {x: number; y: number};
}> = ({depth, children, svg = true, style, origin = {x: W / 2, y: H * 0.55}}) => {
  const cam = useContext(CameraContext);
  const scale = 1 + (cam.zoom - 1) * (0.25 + depth * 0.75);
  const tx = cam.x * depth;
  const ty = cam.y * depth;
  return (
    <AbsoluteFill
      style={{
        transform: `translate(${tx}px, ${ty}px) scale(${scale})`,
        transformOrigin: `${origin.x}px ${origin.y}px`,
        ...style,
      }}
    >
      {svg ? (
        <svg
          width={W}
          height={H}
          viewBox={`0 0 ${W} ${H}`}
          style={{overflow: 'visible', position: 'absolute', inset: 0}}
        >
          {children}
        </svg>
      ) : (
        children
      )}
    </AbsoluteFill>
  );
};
