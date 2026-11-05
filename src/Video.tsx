import { Audio } from "@remotion/media";
import { ThreeCanvas } from "@remotion/three";
import React from "react";
import { AbsoluteFill, staticFile, useVideoConfig } from "remotion";
import { SceneRenderer } from "./scene/SceneRenderer";
import { Subtitles } from "./Subtitles";

export type VideoProps = { samples: number };

export const SamuraiVideo: React.FC<VideoProps> = ({ samples }) => {
  const { width, height } = useVideoConfig();
  return (
    <AbsoluteFill style={{ backgroundColor: "#000" }}>
      <ThreeCanvas
        width={width}
        height={height}
        dpr={1}
        gl={{ antialias: false, preserveDrawingBuffer: true, alpha: false }}
        linear
        flat
      >
        <SceneRenderer samples={samples} />
      </ThreeCanvas>
      <Subtitles />
      <Audio src={staticFile("voice/voiceover.wav")} />
    </AbsoluteFill>
  );
};
