import * as THREE from "three";

// Общие униформы контрового (rim) света: цвет/сила и направление на источник в view-space.
export const RIM = {
  uRimLight: { value: new THREE.Color(1, 1, 1) },
  uLightDirV: { value: new THREE.Vector3(0, 0, 1) },
};

type RimOpts = {
  color: THREE.ColorRepresentation;
  rim: THREE.ColorRepresentation;
  rimPow?: number;
  roughness?: number;
  metalness?: number;
  side?: THREE.Side;
};

/** MeshStandardMaterial + френелевский контур, подсвеченный со стороны источника. */
export function rimMaterial(o: RimOpts) {
  const m = new THREE.MeshStandardMaterial({
    color: o.color,
    roughness: o.roughness ?? 0.7,
    metalness: o.metalness ?? 0.1,
    side: o.side ?? THREE.FrontSide,
  });
  const tint = new THREE.Color(o.rim);
  const pow = { value: o.rimPow ?? 3.0 };
  m.onBeforeCompile = (shader) => {
    shader.uniforms.uRimTint = { value: tint };
    shader.uniforms.uRimPow = pow;
    shader.uniforms.uRimLight = RIM.uRimLight;
    shader.uniforms.uLightDirV = RIM.uLightDirV;
    shader.fragmentShader = shader.fragmentShader
      .replace(
        "void main() {",
        "uniform vec3 uRimTint; uniform float uRimPow; uniform vec3 uRimLight; uniform vec3 uLightDirV;\nvoid main() {",
      )
      .replace(
        "#include <emissivemap_fragment>",
        `#include <emissivemap_fragment>
        {
          float ndv = clamp(dot(normal, normalize(vViewPosition)), 0.0, 1.0);
          float fres = pow(1.0 - ndv, uRimPow);
          float side = smoothstep(-0.35, 0.75, dot(normal, uLightDirV));
          totalEmissiveRadiance += uRimTint * uRimLight * fres * (0.18 + 0.82 * side);
        }`,
      );
  };
  return m;
}
