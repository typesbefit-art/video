import React from 'react';
import {AbsoluteFill, Audio, interpolate, Easing, Sequence, spring, staticFile, useCurrentFrame} from 'remotion';
import {Background} from './Background';
import {DropIcon, FireIcon, FlashesIcon, PauseIcon, ShelterIcon, SubscribeButton, WarningIcon} from './Icons';
import {Subtitles} from './Subtitles';
import {COLORS, FONT, FPS, SCENES, SceneData} from './theme';

const ICONS: Record<string, React.FC<{t: number}>> = {
  stop: PauseIcon,
  shelter: ShelterIcon,
  water: DropIcon,
  fire: FireIcon,
  signal: FlashesIcon,
  food: WarningIcon,
};

const FADE = 10; // frames of fade in/out per scene

const MUSIC_BASE = 0.12;
const MUSIC_DUCKED = 0.06;

/** Music volume: ~12% in pauses, ducked to ~6% under the voice, with soft ramps. */
const musicVolume = (f: number) => {
  const ramp = 0.3 * FPS;
  let duck = 0;
  for (const s of SCENES) {
    const a = s.from + s.words[0].start * FPS - 3;
    const b = s.from + s.audioDuration * FPS;
    const d = interpolate(f, [a - ramp, a, b, b + ramp], [0, 1, 1, 0], {
      extrapolateLeft: 'clamp',
      extrapolateRight: 'clamp',
    });
    duck = Math.max(duck, d);
  }
  return MUSIC_BASE + (MUSIC_DUCKED - MUSIC_BASE) * duck;
};

export const ForestSurvival: React.FC = () => {
  const frame = useCurrentFrame();
  const fire = SCENES.find((s) => s.id === 'fire')!;
  const warmth = interpolate(
    frame,
    [fire.from - 15, fire.from + 20, fire.from + fire.durationInFrames - 15, fire.from + fire.durationInFrames + 20],
    [0, 1, 1, 0],
    {extrapolateLeft: 'clamp', extrapolateRight: 'clamp', easing: Easing.inOut(Easing.sin)}
  );

  return (
    <AbsoluteFill style={{backgroundColor: COLORS.bgTop}}>
      <Background warmth={warmth} />
      <Audio src={staticFile('music.mp3')} volume={musicVolume} />
      {SCENES.map((s, i) => (
        <Sequence key={s.id} from={s.from} durationInFrames={s.durationInFrames} name={s.id}>
          <Audio src={staticFile(s.audio)} />
          <Scene scene={s} index={i} />
        </Sequence>
      ))}
    </AbsoluteFill>
  );
};

const Scene: React.FC<{scene: SceneData; index: number}> = ({scene, index}) => {
  const frame = useCurrentFrame();
  const t = frame / FPS;
  const dur = scene.durationInFrames;
  const opacity = interpolate(frame, [0, FADE, dur - FADE, dur], [0, 1, 1, 0], {
    extrapolateLeft: 'clamp',
    extrapolateRight: 'clamp',
  });
  const enter = spring({frame, fps: FPS, config: {damping: 200}, durationInFrames: 24});

  const isHook = scene.id === 'hook';
  const isOutro = scene.id === 'outro';
  const Icon = ICONS[scene.id];

  return (
    <AbsoluteFill style={{opacity}}>
      {Icon && (
        <>
          {/* step number, y ≈ 270–520 */}
          <div
            style={{
              position: 'absolute',
              top: 262,
              left: 0,
              right: 0,
              textAlign: 'center',
              fontFamily: FONT,
              fontWeight: 800,
              fontSize: 230,
              lineHeight: 1,
              color: COLORS.accent,
              textShadow: '0 0 60px rgba(255,179,71,0.45), 0 8px 24px rgba(0,0,0,0.5)',
              transform: `translateY(${(1 - enter) * 30}px) scale(${0.9 + 0.1 * enter})`,
              opacity: enter,
            }}
          >
            {index}
          </div>
          {/* icon, y ≈ 560–960 */}
          <div
            style={{
              position: 'absolute',
              top: 560,
              left: 0,
              right: 0,
              height: 400,
              display: 'flex',
              justifyContent: 'center',
              transform: `scale(${0.85 + 0.15 * enter})`,
              opacity: enter,
            }}
          >
            <Icon t={t} />
          </div>
        </>
      )}
      {isOutro && (
        <div
          style={{
            position: 'absolute',
            top: 620,
            left: 0,
            right: 0,
            display: 'flex',
            justifyContent: 'center',
            opacity: enter,
            transform: `translateY(${(1 - enter) * 30}px)`,
          }}
        >
          <SubscribeButton t={t} />
        </div>
      )}
      <Subtitles
        words={scene.words}
        t={t}
        fontSize={isHook ? 92 : 70}
        top={isHook ? 640 : 1030}
        height={isHook ? 560 : 440}
      />
    </AbsoluteFill>
  );
};
