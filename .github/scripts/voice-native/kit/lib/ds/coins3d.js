// DOSSIER look: monochrome 3D coins (three.js). Pure function of time: renderAt(t).
// Two choreographies share one renderer:
//   "tower":   coins fall one by one and stack into a single tower (a sum growing)
//   "accounts": coins arc in from off-frame and land round-robin on N stacks (money split across accounts)
import * as THREE from "three";
import { RoomEnvironment } from "./vendor/addons/RoomEnvironment.js";

const clamp = (v, a, b) => Math.max(a, Math.min(b, v));
const hash = (n, s) => { const x = Math.sin(n * 127.1 + (s || 1) * 311.7) * 43758.5453; return x - Math.floor(x); };
const easeOutBack = (p) => { const c1 = 1.4, c3 = c1 + 1; return 1 + c3 * Math.pow(p - 1, 3) + c1 * Math.pow(p - 1, 2); };
const easeInQuad = (p) => p * p;
const easeInOut = (p) => (p < 0.5 ? 4 * p * p * p : 1 - Math.pow(-2 * p + 2, 3) / 2);

export function createCoins(canvas, cfg) {
  const W = 1080, H = 1920;
  const renderer = new THREE.WebGLRenderer({ canvas, alpha: true, antialias: true, preserveDrawingBuffer: true });
  renderer.setPixelRatio(1);
  renderer.setSize(W, H, false);
  renderer.toneMapping = THREE.ACESFilmicToneMapping;
  renderer.toneMappingExposure = 1.05;
  renderer.outputColorSpace = THREE.SRGBColorSpace;

  const scene = new THREE.Scene();
  // Matcap shading (a lit sphere baked into a texture) instead of PBR + PMREM: same brushed-silver
  // read on a coin, a fraction of the software-GL cost on the headless render runner.
  function makeMatcap(hi, mid, lo) {
    const c = document.createElement("canvas"); c.width = c.height = 256;
    const g = c.getContext("2d");
    let gr = g.createRadialGradient(96, 84, 6, 128, 128, 132);
    gr.addColorStop(0, hi); gr.addColorStop(0.4, mid); gr.addColorStop(0.86, lo); gr.addColorStop(1, "#1c1c1c");
    g.fillStyle = gr; g.fillRect(0, 0, 256, 256);
    gr = g.createRadialGradient(150, 210, 4, 150, 210, 70);
    gr.addColorStop(0, "rgba(255,255,255,0.55)"); gr.addColorStop(1, "rgba(255,255,255,0)");
    g.fillStyle = gr; g.fillRect(0, 0, 256, 256);
    const tex = new THREE.CanvasTexture(c); tex.colorSpace = THREE.SRGBColorSpace;
    return tex;
  }
  const useMatcap = cfg.matcap !== false;
  if (useMatcap) renderer.toneMapping = THREE.NoToneMapping;
  if (!useMatcap) {
    const pmrem = new THREE.PMREMGenerator(renderer);
    scene.environment = pmrem.fromScene(new RoomEnvironment(), 0.04).texture;
  }

  const key = new THREE.DirectionalLight(0xffffff, 2.2);
  key.position.set(-4, 8, 6);
  scene.add(key);
  const rim = new THREE.DirectionalLight(0xffffff, 1.4);
  rim.position.set(5, 2, -6);
  scene.add(rim);

  // Coin: lathe profile with raised rim and recessed face, plus a fine reeded edge ring.
  const prof = [[0, 0.055], [0.78, 0.055], [0.82, 0.075], [0.95, 0.075], [1, 0.05], [1, -0.05], [0.95, -0.075], [0.82, -0.075], [0.78, -0.055], [0, -0.055]]
    .map(([x, y]) => new THREE.Vector2(x, y));
  const coinGeo = new THREE.LatheGeometry(prof, 64);
  const faceGeo = new THREE.TorusGeometry(0.55, 0.018, 6, 64);
  const mat = useMatcap ? new THREE.MeshMatcapMaterial({ matcap: makeMatcap("#ffffff", "#e4e4e0", "#8e8e8a") })
    : new THREE.MeshStandardMaterial({ color: 0xdcdcd8, metalness: 0.92, roughness: 0.26 });
  const matDark = useMatcap ? new THREE.MeshMatcapMaterial({ matcap: makeMatcap("#f4f4f0", "#b0b0ac", "#4a4a48") })
    : new THREE.MeshStandardMaterial({ color: 0x9a9a96, metalness: 0.9, roughness: 0.35 });

  function makeCoin(scale) {
    const g = new THREE.Group();
    const body = new THREE.Mesh(coinGeo, mat);
    g.add(body);
    for (const y of [0.056, -0.056]) {
      const ring = new THREE.Mesh(faceGeo, matDark);
      ring.rotation.x = Math.PI / 2;
      ring.position.y = y;
      g.add(ring);
    }
    g.scale.setScalar(scale);
    scene.add(g);
    return g;
  }

  const camera = new THREE.PerspectiveCamera(30, W / H, 0.1, 200);
  const T = 0.15; // coin thickness incl. gap

  const tower = cfg.tower ? Array.from({ length: cfg.tower.count }, () => makeCoin(1)) : [];
  const acc = cfg.accounts ? Array.from({ length: cfg.accounts.count }, () => makeCoin(cfg.accounts.scale || 0.52)) : [];

  function place(c, visible) { c.visible = visible; }

  function renderTower(t) {
    const o = cfg.tower;
    acc.forEach((c) => place(c, false));
    const local = t - o.from;
    tower.forEach((c, i) => {
      const land = o.firstLand + i * o.step;
      const fall = 0.55;
      const p = clamp((local - (land - fall)) / fall, 0, 1);
      place(c, local > land - fall);
      const yRest = i * T;
      const y0 = yRest + 7.5;
      const jitterX = (hash(i, 3) - 0.5) * 0.12, jitterZ = (hash(i, 4) - 0.5) * 0.12;
      c.position.set(jitterX + (1 - p) * (hash(i, 5) - 0.5) * 3, y0 + (yRest - y0) * easeInQuad(p), jitterZ);
      const spin = (1 - p) * (2 + hash(i, 6) * 3);
      c.rotation.set(spin * (hash(i, 7) - 0.3), hash(i, 8) * Math.PI * 2 + spin, spin * (hash(i, 9) - 0.5));
      // tiny landing settle
      const q = clamp((local - land) / 0.25, 0, 1);
      if (q > 0 && q < 1) c.position.y = yRest + Math.sin(q * Math.PI) * 0.06;
    });
    const orbit = -0.35 + local * 0.16;
    const dist = 14.5 - local * 0.35;
    camera.position.set(Math.sin(orbit) * dist, 5.2 + local * 0.1, Math.cos(orbit) * dist);
    camera.lookAt(0, o.lookY, 0);
  }

  function renderAccounts(t) {
    const o = cfg.accounts;
    tower.forEach((c) => place(c, false));
    const local = t - o.from;
    const n = o.stacks;
    acc.forEach((c, i) => {
      const k = i % n, level = Math.floor(i / n);
      const land = o.firstLand + i * o.step;
      const fly = 0.5;
      const p = clamp((local - (land - fly)) / fly, 0, 1);
      place(c, local > land - fly);
      const tx = (k - (n - 1) / 2) * o.gap, ty = level * T * (o.scale || 0.52), tz = 0;
      const sx = -5.5, sy = 6.5, sz = 2;
      const e = easeInOut(p);
      c.position.set(sx + (tx - sx) * e, sy + (ty - sy) * e + Math.sin(e * Math.PI) * 2.2, sz + (tz - sz) * e);
      const spin = (1 - e) * 6;
      c.rotation.set(spin * 0.7, spin, spin * 0.4);
    });
    const dist = (o.dist || 17) - local * 0.4;
    const orbit = 0.25 - local * 0.08;
    camera.position.set(Math.sin(orbit) * dist, o.camY || 4.2, Math.cos(orbit) * dist);
    camera.lookAt(0, o.lookY, 0);
  }

  function renderAt(t) {
    if (cfg.tower && t >= cfg.tower.from && t < cfg.tower.to) renderTower(t);
    else if (cfg.accounts && t >= cfg.accounts.from && t < cfg.accounts.to) renderAccounts(t);
    else { tower.forEach((c) => place(c, false)); acc.forEach((c) => place(c, false)); }
    renderer.render(scene, camera);
  }
  return renderAt;
}
