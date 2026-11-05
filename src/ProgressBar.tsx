import React from 'react';
import {useCurrentFrame, useVideoConfig} from 'remotion';
import {ACCENT} from './constants';

export const ProgressBar: React.FC = () => {
  const frame = useCurrentFrame();
  const {durationInFrames, width} = useVideoConfig();
  const progress = Math.min(1, (frame + 1) / durationInFrames);
  return (
    <div style={{position: 'absolute', left: 0, bottom: 0, width, height: 10, background: 'rgba(255,255,255,0.12)'}}>
      <div
        style={{
          width: width * progress,
          height: '100%',
          background: `linear-gradient(90deg, #7B2CFF, ${ACCENT})`,
          boxShadow: `0 0 16px ${ACCENT}`,
        }}
      />
    </div>
  );
};
