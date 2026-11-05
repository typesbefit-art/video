import React from "react";
import { Ep01, EP01 } from "./ep01";

/** Реестр серий. Новая серия: src/episodes/epNN.tsx + её script.json, затем строка здесь. */
export const EPISODES: {
  id: string;
  component: React.FC;
  fps: number;
  durationInFrames: number;
  width: number;
  height: number;
}[] = [{ ...EP01, component: Ep01 }];
