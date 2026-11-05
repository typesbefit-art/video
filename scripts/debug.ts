import { World } from "../src/scene/world";
const w = new World();
const r = (v: any) => `(${v.x.toFixed(2)},${v.y.toFixed(2)},${v.z.toFixed(2)})`;
for (const t of process.argv.slice(2).map(Number)) {
  w.update(t);
  const [b0, b1] = w.B.bladeSegment();
  const h = w.A.headWorld();
  // расстояние от лица A до клинка B
  const d = b1.clone().sub(b0); const s = Math.min(1, Math.max(0, h.clone().sub(b0).dot(d) / d.dot(d)));
  const dist = b0.clone().addScaledVector(d, s).distanceTo(h);
  console.log(t, "A", r(w.A.root.position), "B", r(w.B.root.position), "Bhead", r(w.B.headWorld()), "cam", r(w.camera.position), "Bblade->Aface", dist.toFixed(2), "Bsword", r(w.B.sword.position));
}
