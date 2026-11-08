import React from 'react';
import {AbsoluteFill, Audio, Sequence, interpolate, staticFile, useCurrentFrame} from 'remotion';
import timeline from './data/timeline.json';
import {Scenes} from './Scenes';
import {Subtitles} from './Subtitles';
import {C, FONT} from './lib';
import {MUSIC_VOLUME} from './Main';

const K = 1400 / 1920; // scene scale inside the 9:16 frame (crops 160px per side of the scaled scene)

export const Short: React.FC<{index: number}> = ({index}) => {
  const frame = useCurrentFrame();
  const {from, to} = timeline.shorts[index];
  const len = to - from;
  const fade = (f: number) => interpolate(f, [0, 12, len - 24, len], [0, 1, 1, 0], {extrapolateLeft: 'clamp', extrapolateRight: 'clamp'});
  return (
    <AbsoluteFill style={{background: `linear-gradient(180deg, ${C.navy} 0%, #4b3f9e 100%)`, fontFamily: FONT}}>
      <div style={{position: 'absolute', top: 90, left: 40, right: 40, textAlign: 'center', color: '#fff', fontWeight: 900, fontSize: 62, lineHeight: 1.12}}>
        Что будет, если откладывать
        <br />
        <span style={{color: C.yellow}}>$100 в месяц 20 лет?</span>
      </div>
      <div style={{position: 'absolute', top: 340, left: 0, right: 0, textAlign: 'center', color: 'rgba(255,255,255,0.75)', fontWeight: 700, fontSize: 40}}>
        Часть {index + 1} из {timeline.shorts.length}
      </div>
      <div style={{position: 'absolute', top: 420, left: 0, width: 1080, height: 1080 * K, overflow: 'hidden', borderTop: '6px solid #fff', borderBottom: '6px solid #fff'}}>
        <div style={{position: 'absolute', left: (1080 - 1920 * K) / 2, top: 0, width: 1920, height: 1080, transform: `scale(${K})`, transformOrigin: '0 0'}}>
          <Sequence from={-from} layout="none">
            <Scenes />
          </Sequence>
        </div>
      </div>
      <Subtitles offset={from} vertical />
      <div style={{position: 'absolute', bottom: 150, left: 0, right: 0, textAlign: 'center', color: '#fff', fontWeight: 800, fontSize: 44}}>
        Полное видео — на канале
      </div>
      <div style={{position: 'absolute', bottom: 80, left: 40, right: 40, textAlign: 'center', color: 'rgba(255,255,255,0.7)', fontWeight: 600, fontSize: 30}}>
        Не финансовая рекомендация · 7% годовых — допущение
      </div>
      <AbsoluteFill style={{background: '#000', opacity: 1 - fade(frame)}} />
      <Sequence from={-from} layout="none">
        <Audio src={staticFile('voice.wav')} volume={(f) => fade(f - from)} />
        <Audio src={staticFile('music.wav')} volume={(f) => MUSIC_VOLUME * 1.2 * fade(f - from)} />
      </Sequence>
    </AbsoluteFill>
  );
};
