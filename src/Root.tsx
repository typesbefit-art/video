import React from "react";
import { Composition } from "remotion";
import { EPISODES } from "./episodes";

export const RemotionRoot: React.FC = () => (
  <>
    {EPISODES.map((ep) => (
      <Composition
        key={ep.id}
        id={ep.id}
        component={ep.component}
        durationInFrames={ep.durationInFrames}
        fps={ep.fps}
        width={ep.width}
        height={ep.height}
      />
    ))}
  </>
);
