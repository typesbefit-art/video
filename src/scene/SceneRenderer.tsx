import { useFrame, useThree } from "@react-three/fiber";
import React, { useEffect, useMemo, useRef } from "react";
import { useCurrentFrame, useVideoConfig } from "remotion";
import * as THREE from "three";
import { World } from "./world";
import { SHOTS, shotIndex } from "./camera";

const MAX_SAMPLES = 4;

const POST_FRAG = `
  uniform sampler2D t0, t1, t2, t3;
  uniform int uCount;
  uniform vec2 uRes;
  uniform float uSeed, uExposure, uSat, uContrast, uGrain, uVig, uFade, uFlash, uCA, uDawn, uFreeze;
  varying vec2 vUv;

  vec3 aces(vec3 x){ return clamp((x*(2.51*x+0.03))/(x*(2.43*x+0.59)+0.14), 0.0, 1.0); }
  float hash(vec2 p){ p = fract(p*vec2(443.897, 441.423)); p += dot(p, p.yx+19.19); return fract((p.x+p.y)*p.x); }

  vec3 samp(sampler2D t, vec2 uv, vec2 off){
    return vec3(texture2D(t, uv + off).r, texture2D(t, uv).g, texture2D(t, uv - off).b);
  }

  void main(){
    vec2 c = vUv - 0.5;
    float r2 = dot(c*vec2(0.5625,1.0), c*vec2(0.5625,1.0));
    vec2 off = c * uCA * r2 * 0.03;
    vec3 col = samp(t0, vUv, off);
    if (uCount > 1) col += samp(t1, vUv, off);
    if (uCount > 2) col += samp(t2, vUv, off);
    if (uCount > 3) col += samp(t3, vUv, off);
    col /= float(uCount);

    col *= uExposure;
    col += vec3(1.0, 0.85, 0.65) * uFlash * 0.035;
    col = aces(col);
    // в sRGB
    col = pow(col, vec3(1.0/2.2));

    // грейд: холодные тени, нейтральные/тёплые света; к рассвету — теплее
    float l = dot(col, vec3(0.2126, 0.7152, 0.0722));
    vec3 shadowTint = mix(vec3(0.86, 0.95, 1.12), vec3(0.92, 0.9, 1.04), uDawn);
    vec3 highTint = mix(vec3(0.95, 1.0, 1.06), vec3(1.12, 1.0, 0.86), uDawn);
    col *= mix(shadowTint, highTint, smoothstep(0.1, 0.8, l));
    col = mix(vec3(l), col, uSat);
    col = (col - 0.5) * uContrast + 0.5;
    // приподнятые чёрные, как у плёнки
    col = col * 0.965 + vec3(0.012, 0.016, 0.022);

    // виньетка
    float v = smoothstep(0.85, 0.2, length(c * vec2(1.0, 0.82)) * (1.0 + uVig));
    col *= mix(1.0, v, 0.85);

    // зерно (зависит от яркости)
    float g = hash(vUv * uRes + uSeed * 17.0) + hash(vUv * uRes * 0.5 + uSeed * 3.1) - 1.0;
    col += g * uGrain * (0.6 + 0.6 * (1.0 - l));

    col *= uFade;
    gl_FragColor = vec4(clamp(col, 0.0, 1.0), 1.0);
  }`;

export const SceneRenderer: React.FC<{ samples: number }> = ({ samples }) => {
  const frame = useCurrentFrame();
  const { fps, width, height } = useVideoConfig();
  const frameRef = useRef(frame);
  frameRef.current = frame;
  const { gl } = useThree();

  const world = useMemo(() => new World(), []);

  const post = useMemo(() => {
    const opts: THREE.RenderTargetOptions = {
      type: THREE.HalfFloatType,
      depthBuffer: true,
      samples: samples >= 3 ? 0 : 2, // при 3+ подкадрах сглаживание даёт сам motion blur
      minFilter: THREE.LinearFilter,
      magFilter: THREE.LinearFilter,
    };
    const rts = Array.from({ length: MAX_SAMPLES }, () => new THREE.WebGLRenderTarget(width, height, opts));
    const mat = new THREE.ShaderMaterial({
      uniforms: {
        t0: { value: rts[0].texture },
        t1: { value: rts[1].texture },
        t2: { value: rts[2].texture },
        t3: { value: rts[3].texture },
        uCount: { value: 1 },
        uRes: { value: new THREE.Vector2(width, height) },
        uSeed: { value: 0 },
        uExposure: { value: 1 },
        uSat: { value: 1 },
        uContrast: { value: 1 },
        uGrain: { value: 0.05 },
        uVig: { value: 0.4 },
        uFade: { value: 1 },
        uFlash: { value: 0 },
        uCA: { value: 1 },
        uDawn: { value: 0 },
        uFreeze: { value: 0 },
      },
      vertexShader: `varying vec2 vUv; void main(){ vUv = uv; gl_Position = vec4(position.xy, 0.0, 1.0); }`,
      fragmentShader: POST_FRAG,
      depthTest: false,
      depthWrite: false,
    });
    const quad = new THREE.Mesh(new THREE.PlaneGeometry(2, 2), mat);
    quad.frustumCulled = false;
    const scene = new THREE.Scene();
    scene.add(quad);
    const cam = new THREE.OrthographicCamera(-1, 1, 1, -1, 0, 1);
    return { rts, mat, scene, cam };
  }, [width, height, samples]);

  useEffect(() => {
    gl.toneMapping = THREE.NoToneMapping;
    gl.outputColorSpace = THREE.LinearSRGBColorSpace;
    return () => post.rts.forEach((r) => r.dispose());
  }, [gl, post]);

  useFrame(() => {
    const t = frameRef.current / fps;
    const n = Math.max(1, Math.min(MAX_SAMPLES, samples));
    // затвор 180°: подкадры в пределах половины длительности кадра, не пересекая склейку
    const shot = SHOTS[shotIndex(t)];
    const shutter = 0.5 / fps;
    let look = world.look;
    let flash = 0;
    for (let i = 0; i < n; i++) {
      let ts = n === 1 ? t : t - shutter * 0.5 + (shutter * i) / (n - 1);
      ts = Math.min(Math.max(ts, shot.t0), shot.t1 - 1e-4);
      look = world.update(ts, t);
      flash = Math.max(flash, world.flash);
      gl.setRenderTarget(post.rts[i]);
      gl.clear();
      gl.render(world.scene, world.camera);
    }
    // финальная точка — ровно на кадре (для грейда)
    const u = post.mat.uniforms;
    u.uCount.value = n;
    u.uSeed.value = (frameRef.current % 997) * 0.618;
    u.uExposure.value = look.exposure;
    u.uSat.value = look.saturation;
    u.uContrast.value = look.contrast;
    u.uGrain.value = look.grain;
    u.uVig.value = look.vignette;
    u.uFade.value = look.fade;
    u.uFlash.value = flash;
    u.uDawn.value = look.dawn;
    u.uFreeze.value = look.freeze;
    gl.setRenderTarget(null);
    gl.render(post.scene, post.cam);
  }, 1);

  return null;
};
