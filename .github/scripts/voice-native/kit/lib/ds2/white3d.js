// WHITE MODEL look: a Fern-style white low-poly reconstruction, one colour pop (red = the thing that matters).
// Ocado picking floor: storage stacks, a conveyor of totes, a row of robot arms; the red arm's lesson
// travels to every other arm as a ring across the floor. Pure function of time: renderAt(t).
import * as THREE from "three";

const clamp = (v, a, b) => Math.max(a, Math.min(b, v));
const hash = (n, s) => { const x = Math.sin(n * 127.1 + (s || 1) * 311.7) * 43758.5453; return x - Math.floor(x); };
const eio = (p) => (p < 0.5 ? 4 * p * p * p : 1 - Math.pow(-2 * p + 2, 3) / 2);
const eo = (p) => 1 - Math.pow(1 - p, 3);
const back = (p) => { const c1 = 1.7, c3 = c1 + 1; return 1 + c3 * Math.pow(p - 1, 3) + c1 * Math.pow(p - 1, 2); };
const lerp = (a, b, p) => a + (b - a) * p;

export function createWhite(canvas, cfg) {
  const W = 1080, H = 1920;
  const renderer = new THREE.WebGLRenderer({ canvas, antialias: true, preserveDrawingBuffer: true });
  renderer.setPixelRatio(1);
  renderer.setSize(W, H, false);
  renderer.outputColorSpace = THREE.SRGBColorSpace;
  renderer.shadowMap.enabled = true;
  renderer.shadowMap.type = THREE.PCFSoftShadowMap;
  renderer.setClearColor(0xf4f4f2, 1);

  const scene = new THREE.Scene();
  scene.fog = new THREE.Fog(0xf4f4f2, 34, 70);
  const hemi = new THREE.HemisphereLight(0xffffff, 0xd9d9d4, 2.1);
  scene.add(hemi);
  const sun = new THREE.DirectionalLight(0xffffff, 2.2);
  sun.position.set(-9, 16, 7);
  sun.castShadow = true;
  sun.shadow.mapSize.set(1024, 1024);
  const sc = sun.shadow.camera; sc.left = -16; sc.right = 16; sc.top = 16; sc.bottom = -16; sc.near = 1; sc.far = 50;
  sun.shadow.bias = -0.0015; sun.shadow.radius = 4;
  scene.add(sun);

  const white = new THREE.MeshLambertMaterial({ color: 0xf7f7f5 });
  const grey = new THREE.MeshLambertMaterial({ color: 0xd6d6d2 });
  const dark = new THREE.MeshLambertMaterial({ color: 0x3a3a38 });
  const red = new THREE.MeshLambertMaterial({ color: 0xe0301e, emissive: 0x3a0500 });

  // floor + a fine grid (the model-making base board)
  const floor = new THREE.Mesh(new THREE.PlaneGeometry(120, 120), new THREE.MeshLambertMaterial({ color: 0xf1f1ee }));
  floor.rotation.x = -Math.PI / 2; floor.receiveShadow = true; scene.add(floor);
  const grid = new THREE.GridHelper(80, 80, 0xdcdcd7, 0xe4e4e0); grid.position.y = 0.002; scene.add(grid);

  // storage grid: stacks of totes (instanced), they rise out of the floor as the hook builds the model
  const stackGeo = new THREE.BoxGeometry(0.86, 0.5, 0.86);
  const stacks = [];
  const blocks = [[-9, -8, 7, 5], [-9, 2.5, 7, 4], [3.5, -9, 6, 4]];
  blocks.forEach(([x0, z0, nx, nz], bi) => {
    for (let i = 0; i < nx; i++) for (let j = 0; j < nz; j++) {
      const h = 3 + Math.floor(hash(i * 13 + j * 7 + bi * 101, 5) * 4);
      for (let k = 0; k < h; k++) stacks.push({ x: x0 + i * 0.95, z: z0 + j * 0.95, k, d: Math.hypot(x0 + i - 0, z0 + j - 0) });
    }
  });
  const inst = new THREE.InstancedMesh(stackGeo, white, stacks.length);
  inst.castShadow = true; inst.receiveShadow = true; scene.add(inst);
  const m4 = new THREE.Matrix4(), q = new THREE.Quaternion(), v = new THREE.Vector3(), sv = new THREE.Vector3();

  // conveyor with moving totes
  const belt = new THREE.Mesh(new THREE.BoxGeometry(22, 0.35, 1.3), grey); belt.position.set(1, 0.9, 1.2); belt.castShadow = true; belt.receiveShadow = true; scene.add(belt);
  for (let i = 0; i < 12; i++) { const leg = new THREE.Mesh(new THREE.BoxGeometry(0.12, 0.8, 1.1), grey); leg.position.set(-9.5 + i * 1.9, 0.4, 1.2); scene.add(leg); }
  const toteGeo = new THREE.BoxGeometry(0.9, 0.42, 0.7);
  const totes = [];
  for (let i = 0; i < 14; i++) { const t = new THREE.Mesh(toteGeo, white); t.castShadow = true; t.receiveShadow = true; scene.add(t); totes.push(t); }

  // robot arms: base, turret, upper arm, forearm, gripper; the hero (index 2) is red
  const arms = [];
  const ARM_X = [-7.5, -4.5, -1.5, 1.5, 4.5, 7.5];
  ARM_X.forEach((x, i) => {
    const hero = i === (cfg.hero || 2);
    const mat = hero ? red : white;
    const root = new THREE.Group(); root.position.set(x, 0, 3.1); scene.add(root);
    const base = new THREE.Mesh(new THREE.CylinderGeometry(0.55, 0.65, 0.5, 20), grey); base.position.y = 0.25; base.castShadow = true; root.add(base);
    const turret = new THREE.Group(); turret.position.y = 0.5; root.add(turret);
    const tur = new THREE.Mesh(new THREE.CylinderGeometry(0.34, 0.4, 0.5, 18), mat); tur.position.y = 0.25; tur.castShadow = true; turret.add(tur);
    const shoulder = new THREE.Group(); shoulder.position.y = 0.55; turret.add(shoulder);
    const up = new THREE.Mesh(new THREE.BoxGeometry(0.26, 1.6, 0.26), mat); up.position.y = 0.8; up.castShadow = true; shoulder.add(up);
    const elbow = new THREE.Group(); elbow.position.y = 1.6; shoulder.add(elbow);
    const ej = new THREE.Mesh(new THREE.SphereGeometry(0.2, 14, 10), mat); ej.castShadow = true; elbow.add(ej);
    const fore = new THREE.Mesh(new THREE.BoxGeometry(0.2, 1.35, 0.2), mat); fore.position.y = 0.67; fore.castShadow = true; elbow.add(fore);
    const wrist = new THREE.Group(); wrist.position.y = 1.35; elbow.add(wrist);
    const head = new THREE.Mesh(new THREE.BoxGeometry(0.36, 0.2, 0.36), hero ? red : grey); head.castShadow = true; wrist.add(head);
    const cup = new THREE.Mesh(new THREE.CylinderGeometry(0.1, 0.13, 0.28, 12), dark); cup.position.y = 0.22; wrist.add(cup);
    // the "learned" light every arm receives when the lesson reaches it
    const lamp = new THREE.Mesh(new THREE.SphereGeometry(0.16, 12, 10), new THREE.MeshBasicMaterial({ color: 0xe0301e, transparent: true, opacity: 0 }));
    lamp.position.set(0, 1.25, 0); root.add(lamp);
    const item = new THREE.Mesh(new THREE.BoxGeometry(0.22, 0.28, 0.18), grey); item.castShadow = true; wrist.add(item); item.position.y = 0.46;
    arms.push({ root, turret, shoulder, elbow, wrist, lamp, item, hero, ph: hash(i, 9) * 3, x });
  });

  // lesson rings: expanding flat rings on the floor, from the hero arm outward
  const rings = [];
  for (let i = 0; i < 3; i++) {
    const r = new THREE.Mesh(new THREE.RingGeometry(0.9, 1.15, 72), new THREE.MeshBasicMaterial({ color: 0xe0301e, transparent: true, opacity: 0, side: THREE.DoubleSide }));
    r.rotation.x = -Math.PI / 2; r.position.set(ARM_X[cfg.hero || 2], 0.02, 3.1); scene.add(r); rings.push(r);
  }
  // floor links: red dashes from hero to each arm (drawn as thin boxes that grow)
  const links = arms.filter((a) => !a.hero).map((a) => {
    const hx = ARM_X[cfg.hero || 2];
    const len = Math.abs(a.x - hx);
    const m = new THREE.Mesh(new THREE.BoxGeometry(1, 0.03, 0.12), new THREE.MeshBasicMaterial({ color: 0xe0301e }));
    m.position.set((a.x + hx) / 2, 0.03, 4.25); m.scale.x = 0.0001; scene.add(m);
    return { m, len, dist: len, dir: Math.sign(a.x - hx), hx };
  });

  const cam = new THREE.OrthographicCamera(-W / 2, W / 2, H / 2, -H / 2, 0.1, 200);
  const target = new THREE.Vector3();
  const pv = new THREE.Vector3();

  // camera keys: [t, azimuth deg, elevation deg, zoom (px per unit), tx, ty, tz]
  const K = cfg.cam;
  function camAt(t) {
    let i = 0; while (i < K.length - 2 && t > K[i + 1][0]) i++;
    const a = K[i], b = K[i + 1];
    const p = clamp((t - a[0]) / (b[0] - a[0]), 0, 1);
    const e = (b[7] === "snap" ? (p2) => 1 - Math.pow(1 - p2, 5) : eio)(p);
    return a.slice(1, 7).map((x, k) => lerp(x, b[k + 1], e));
  }

  function renderAt(t) {
    // stacks rise out of the floor (the model builds itself for the hook), then sit
    for (let n = 0; n < stacks.length; n++) {
      const s = stacks[n];
      const start = 0.0 + s.d * 0.018 + s.k * 0.04;
      const p = clamp((t - start + 0.35) / 0.45, 0, 1);
      const y = s.k * 0.52 + 0.25;
      v.set(s.x, lerp(-0.4, y, back(p)), s.z); sv.set(1, Math.max(0.001, p), 1);
      m4.compose(v, q, sv); inst.setMatrixAt(n, m4);
    }
    inst.instanceMatrix.needsUpdate = true;
    // totes ride the belt (seamless loop)
    totes.forEach((tt, i) => { const x = ((i * 1.65 + t * 1.3) % 23) - 10.5; tt.position.set(x, 1.29, 1.2); });
    // arms: a pick cycle (reach down to the belt, lift, swing to the tote, release); hero runs slightly faster
    arms.forEach((a, i) => {
      const cyc = a.hero ? 1.7 : 2.1;
      const u = ((t + a.ph) % cyc) / cyc;
      const sw = Math.sin(u * Math.PI * 2);
      a.turret.rotation.y = 0.9 * sw + (a.hero ? 0.2 : 0);
      a.shoulder.rotation.x = -0.55 - 0.35 * Math.max(0, Math.sin(u * Math.PI * 2 + 1.2));
      a.elbow.rotation.x = -1.25 + 0.45 * Math.sin(u * Math.PI * 4);
      a.wrist.rotation.x = -0.9 - a.shoulder.rotation.x * 0.3;
      a.item.visible = u > 0.15 && u < 0.62;
      // lesson arrives: the lamp lights when the ring front passes this arm
      const dist = Math.abs(a.x - ARM_X[cfg.hero || 2]);
      const arrive = cfg.lessonAt + dist / cfg.ringSpeed;
      const lit = a.hero ? clamp((t - (cfg.lessonAt - 0.2)) / 0.2, 0, 1) : clamp((t - arrive) / 0.18, 0, 1);
      a.lamp.material.opacity = lit;
      a.lamp.scale.setScalar(1 + (lit > 0 && lit < 1 ? 0.6 : 0) + 0.3 * Math.max(0, 1 - (t - arrive) * 3) * (lit >= 1 ? 1 : 0));
    });
    rings.forEach((r, i) => {
      const t0 = cfg.lessonAt + i * 0.55;
      const p = clamp((t - t0) / 2.4, 0, 1);
      const rad = 0.3 + p * cfg.ringSpeed * 2.4;
      r.scale.set(rad, rad, 1);
      r.material.opacity = t < t0 ? 0 : 0.85 * (1 - p);
    });
    links.forEach((l) => {
      const p = clamp((t - cfg.lessonAt) * cfg.ringSpeed / l.dist, 0, 1);
      l.m.scale.x = Math.max(0.0001, l.len * p);
      l.m.position.x = l.hx + l.dir * l.len * p / 2;
    });
    // camera
    const [az, el, zoom, tx, ty, tz] = camAt(t);
    const A = (az * Math.PI) / 180, E = (el * Math.PI) / 180, R = 40;
    target.set(tx, ty, tz);
    cam.position.set(tx + R * Math.cos(E) * Math.sin(A), ty + R * Math.sin(E), tz + R * Math.cos(E) * Math.cos(A));
    cam.zoom = zoom / 1; cam.lookAt(target); cam.updateProjectionMatrix();
    renderer.render(scene, cam);
    // screen-space anchors for DOM callouts
    if (cfg.anchors) cfg.anchors.forEach((an) => {
      pv.set(an.p[0], an.p[1], an.p[2]).project(cam);
      an.el.style.left = ((pv.x * 0.5 + 0.5) * W).toFixed(1) + "px";
      an.el.style.top = ((-pv.y * 0.5 + 0.5) * H).toFixed(1) + "px";
    });
  }
  return renderAt;
}
