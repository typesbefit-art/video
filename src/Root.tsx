import React from "react";
import { Composition } from "remotion";
import { SamuraiVideo } from "./Video";

// Пресеты: 120 fps (мастер) и 60 fps (TikTok / Shorts). Сцена считается от времени, не от номера кадра.
// samples — число подкадров motion blur (затвор 180°).
export const Root: React.FC = () => (
  <>
    <Composition id="Samurai120" component={SamuraiVideo} width={1080} height={1920} fps={120} durationInFrames={3600} defaultProps={{ samples: 2 }} />
    <Composition id="Samurai60" component={SamuraiVideo} width={1080} height={1920} fps={60} durationInFrames={1800} defaultProps={{ samples: 3 }} />
  </>
);
