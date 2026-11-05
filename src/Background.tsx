import React from 'react';
import {AbsoluteFill, useCurrentFrame} from 'remotion';

export const Background: React.FC = () => {
  const frame = useCurrentFrame();
  const drift = Math.sin(frame / 90) * 60;
  return (
    <AbsoluteFill
      style={{
        background: 'linear-gradient(180deg, #07011A 0%, #1A0638 40%, #2B0B52 70%, #12022C 100%)',
      }}
    >
      <AbsoluteFill
        style={{
          background: `radial-gradient(circle at ${30 + drift / 20}% ${35}%, rgba(140,60,255,0.35) 0%, rgba(140,60,255,0) 45%),
             radial-gradient(circle at ${75 - drift / 25}% 75%, rgba(0,229,255,0.12) 0%, rgba(0,229,255,0) 40%)`,
        }}
      />
    </AbsoluteFill>
  );
};
