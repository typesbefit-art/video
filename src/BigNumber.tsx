import React from 'react';
import {spring, useCurrentFrame, useVideoConfig} from 'remotion';
import {ACCENT, FONT} from './constants';

// Крупная цифра факта (зона 270..650 px)
export const BigNumber: React.FC<{n: number; delay?: number}> = ({n, delay = 0}) => {
  const frame = useCurrentFrame();
  const {fps} = useVideoConfig();
  const s = spring({frame: frame - delay, fps, config: {damping: 10, stiffness: 140}});
  const glow = 0.75 + 0.25 * Math.sin(frame / 6);
  return (
    <div
      style={{
        position: 'absolute',
        top: 270,
        left: 0,
        right: 0,
        height: 380,
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'center',
      }}
    >
      <div
        style={{
          width: 330,
          height: 330,
          borderRadius: '50%',
          border: `8px solid ${ACCENT}`,
          boxShadow: `0 0 ${40 * glow}px ${ACCENT}, inset 0 0 ${30 * glow}px rgba(0,229,255,0.5)`,
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'center',
          transform: `scale(${s}) rotate(${(1 - s) * -90}deg)`,
          background: 'rgba(10,0,30,0.45)',
        }}
      >
        <span
          style={{
            fontFamily: FONT,
            fontWeight: 900,
            fontSize: 250,
            lineHeight: 1,
            color: '#fff',
            textShadow: `0 0 ${30 * glow}px ${ACCENT}, 0 0 8px ${ACCENT}`,
            marginTop: -6,
          }}
        >
          {n}
        </span>
      </div>
    </div>
  );
};
