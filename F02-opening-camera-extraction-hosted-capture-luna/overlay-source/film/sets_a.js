// F02 sets A: the press-release desk (cold open), the support floor (700 desks, the recurring set), the globe,
// and the customer's flat. Built for this film only. Every value is a pure function of film time T.
export function createSetsA(K) {
  const { THREE, flat, basic, hash, prog, EASE, lerp, clamp, S, person, pose, instanced, WORKER, DESK, M4, canvasTex, box, rr,
    skyPlate, sun, FONT, HEAVY, SERIF, MONO, COL, bubbleGeo, labelMesh, glowTex } = K;
  const st = (name, T) => (S[name] ? S[name](T) : {});
  const out = {};
  const white = flat(COL.white), whiteDim = flat(COL.whiteDim), grey = flat(COL.grey), dark = flat(COL.slate), ink = flat(COL.ink);

  // ============================================================== RELEASE: a morning desk, a printer, the press release
  {
    const sc = new THREE.Scene(); sc.background = new THREE.Color(0xe9ecef); sc.fog = new THREE.Fog(0xe9ecef, 9, 26);
    sc.add(new THREE.HemisphereLight(0xffffff, 0xb9c0c9, 1.5));
    const key = sun(sc, [-3.5, 6, 3], [0, 0.7, 0], 3.2, 2.4, 0xfff1e0);
    const fl = new THREE.Mesh(new THREE.PlaneGeometry(40, 40), flat(0xd9dde2)); fl.rotation.x = -Math.PI / 2; fl.receiveShadow = true; sc.add(fl);
    // back wall with a tall window (light falls across the desk)
    const wallM = flat(0xf1f2f3);
    box(12, 4, 0.15, wallM, 0, 2, -1.6, sc);
    const win = new THREE.Mesh(new THREE.PlaneGeometry(2.2, 2.4), basic(0xfdfdfd)); win.position.set(-1.6, 2.0, -1.52); sc.add(win);
    [-2.7, -1.6, -0.5].forEach((x) => box(0.06, 2.5, 0.08, white, x, 2.0, -1.5, sc));
    box(2.3, 0.08, 0.16, white, -1.6, 0.78, -1.5, sc); box(2.3, 0.08, 0.1, white, -1.6, 3.22, -1.5, sc);
    // desk
    box(2.4, 0.05, 0.9, white, 0, 0.75, -0.6, sc);
    [[-1.15, -0.2], [1.15, -0.2], [-1.15, -0.98], [1.15, -0.98]].forEach(([x, z]) => box(0.05, 0.74, 0.05, grey, x, 0.37, z, sc));
    // the printer: body, paper tray, output tray, a lit status LED
    const pr = new THREE.Group(); pr.position.set(0.25, 0.775, -0.72); sc.add(pr);
    box(0.46, 0.2, 0.4, flat(0xeef0f2), 0, 0.1, 0, pr); box(0.46, 0.05, 0.36, flat(0xdfe2e6), 0, 0.225, -0.02, pr);
    box(0.36, 0.012, 0.22, flat(0xcfd3d8), 0, 0.105, 0.28, pr);              // output tray (sticks out the front)
    box(0.4, 0.035, 0.02, dark, 0, 0.17, 0.202, pr, true);                     // output slot
    const led = new THREE.Mesh(new THREE.SphereGeometry(0.008, 8, 6), basic(COL.green)); led.position.set(0.19, 0.2, 0.2); pr.add(led);
    box(0.06, 0.012, 0.03, flat(0xc7ccd2), 0.14, 0.2, 0.2, pr, true);
    // the page: A4, bends as it leaves the slot. Text is drawn at print resolution (1654 x 2339).
    const pageTex = canvasTex(1654, 2339, (g, w, h) => {
      g.fillStyle = "#fbfaf7"; g.fillRect(0, 0, w, h);
      g.fillStyle = "#ffb3c7"; rr(g, 110, 100, 500, 150, 22); g.fill();
      g.fillStyle = "#14171c"; g.font = "900 110px " + HEAVY; g.fillText("KLARNA", 150, 212);
      g.fillStyle = "#4b5563"; g.font = "500 46px " + MONO; g.fillText("PRESS RELEASE · 27 FEBRUARY 2024", 110, 330);
      g.fillStyle = "#14171c"; g.font = "800 120px " + FONT;
      const releaseLines = ["AI assistant handles", "two-thirds of customer", "service chats in its", "first month"];
      if (releaseLines.some((line) => g.measureText(line).width > 1434)) throw new Error("press-release body line does not fit its page column");
      releaseLines.forEach((s, i) => g.fillText(s, 110, 510 + i * 132));
      g.fillStyle = "#eef0f3"; rr(g, 110, 1040, 1434, 170, 18); g.fill();
      g.fillStyle = "#14171c"; g.font = "900 78px " + HEAVY;
      const metricLines = ["2.3M CHATS · 23 MARKETS", "· 35+ LANGUAGES"];
      const metricMaxWidth = 1340;
      if (metricLines.some((line) => g.measureText(line).width > metricMaxWidth)) throw new Error("press-release metric does not fit its panel");
      metricLines.forEach((line, i) => g.fillText(line, 145, 1098 + i * 84));
      g.fillStyle = "#ffb3c7"; rr(g, 98, 1230, 1458, 138, 16); g.fill();
      g.fillStyle = "#14171c"; g.font = "800 78px " + FONT; g.fillText("THE WORK OF 700 FULL-TIME AGENTS", 130, 1324);
      g.fillStyle = "#14171c"; g.font = "700 62px " + FONT;
      g.fillText("Resolution time: under 2 minutes, down from 11", 110, 1510);
      g.fillStyle = "#4b5563"; g.font = "500 48px " + FONT;
      g.fillText("Reported by Klarna after the assistant's first month", 110, 1600);
      g.fillStyle = "#14171c"; g.fillRect(110, 1710, 1434, 4);
      g.font = "500 44px " + MONO; g.fillText("SOURCE: KLARNA PRESS MATERIAL", 110, 1800);
    });
    const pageMat = new THREE.MeshLambertMaterial({ map: pageTex, side: THREE.DoubleSide });
    const pgGeo = new THREE.PlaneGeometry(0.21, 0.297, 1, 30); const pgBase = pgGeo.attributes.position.array.slice();
    const page = new THREE.Mesh(pgGeo, pageMat); page.castShadow = true; page.receiveShadow = true; pr.add(page);
    // earlier copies on the tray (same page), so a close-up can open on a printed sheet
    const stackTex = pageTex;
    for (let k = 0; k < 3; k++) { const s = new THREE.Mesh(new THREE.PlaneGeometry(0.21, 0.297), new THREE.MeshLambertMaterial({ map: stackTex }));
      s.rotation.x = -Math.PI / 2; s.rotation.z = (hash(k, 4) - 0.5) * 0.08; s.position.set((hash(k, 2) - 0.5) * 0.01, 0.112 + k * 0.0015, 0.29); s.receiveShadow = true; pr.add(s); }
    // the number lifts off the page (a cut-out of the printed digits, drawn separately so it stays sharp when big)
    const numTex = canvasTex(1200, 560, (g, w, h) => { g.fillStyle = "#14171c"; g.font = "800 470px " + FONT; g.textAlign = "center"; g.textBaseline = "middle"; g.fillText("700", w / 2, h / 2 + 20); });
    const num = new THREE.Mesh(new THREE.PlaneGeometry(0.3, 0.14), new THREE.MeshBasicMaterial({ map: numTex, transparent: true, depthWrite: false, side: THREE.DoubleSide }));
    num.visible = false; sc.add(num);
    const numShadow = new THREE.Mesh(new THREE.PlaneGeometry(0.3, 0.14), new THREE.MeshBasicMaterial({ map: numTex, transparent: true, opacity: 0.18, depthWrite: false, color: 0x000000 }));
    numShadow.rotation.x = -Math.PI / 2; numShadow.visible = false; sc.add(numShadow);
    // props: a mug, a closed laptop, a pen, a plant, a lamp
    const mug = new THREE.Mesh(new THREE.CylinderGeometry(0.045, 0.04, 0.1, 10), flat(0xf4f5f6)); mug.position.set(-0.45, 0.83, -0.45); mug.castShadow = true; sc.add(mug);
    const hdl = new THREE.Mesh(new THREE.TorusGeometry(0.028, 0.008, 5, 10), flat(0xf4f5f6)); hdl.position.set(-0.5, 0.835, -0.45); hdl.rotation.y = Math.PI / 2; sc.add(hdl);
    box(0.36, 0.02, 0.25, flat(0xc9ced4), -0.75, 0.785, -0.7, sc);
    const pen = new THREE.Mesh(new THREE.CylinderGeometry(0.005, 0.005, 0.14, 6), dark); pen.rotation.set(0, 0.6, Math.PI / 2); pen.position.set(-0.2, 0.781, -0.35); sc.add(pen);
    const pot = new THREE.Mesh(new THREE.CylinderGeometry(0.07, 0.055, 0.12, 8), flat(0xd8dcdf)); pot.position.set(0.95, 0.84, -0.85); sc.add(pot);
    for (let k = 0; k < 7; k++) { const lf = new THREE.Mesh(new THREE.IcosahedronGeometry(0.06, 0), flat(0xa9b8a6)); lf.scale.set(0.5, 1.4, 0.3); lf.position.set(0.95 + Math.sin(k * 2.4) * 0.05, 0.98 + hash(k, 3) * 0.06, -0.85 + Math.cos(k * 2.4) * 0.05); lf.rotation.set(Math.sin(k) * 0.5, k, Math.cos(k * 1.3) * 0.5); sc.add(lf); }
    const tmp = new THREE.Vector3();
    out.release = { scene: sc, anim(T, shot) {
      const s = st("release", T);   // {out: 0..1 page travel, lift: 0..1 number lift, glow}
      const o = s.out === undefined ? 1 : s.out;
      // page path: leaves the slot heading +z and slightly up, then drops onto the tray; the leading edge curls down
      const arr = pgGeo.attributes.position.array;
      const L = 0.297, travel = o * (L + 0.02);
      for (let i = 0; i < arr.length; i += 3) {
        const bx = pgBase[i], by = pgBase[i + 1];          // by: -L/2 (leading edge) .. +L/2 (trailing edge)
        const d = travel - (by + L / 2);                    // how far this row has come out of the slot
        let y, z;
        if (d <= 0) { y = 0.17; z = 0.2 + d; }             // still inside the printer
        else { const a = Math.min(d, 0.07); const b = Math.max(0, d - 0.07);
          y = 0.17 + a * 0.35 - b * 0.4 - b * b * 1.2; z = 0.2 + a + b * 0.92;
          y = Math.max(y, 0.114 + (1 - o) * 0.0) ; }
        arr[i] = bx; arr[i + 1] = y; arr[i + 2] = z;
      }
      pgGeo.attributes.position.needsUpdate = true; pgGeo.computeVertexNormals();
      page.visible = o > 0;
      led.material.color.setHex(o > 0 && o < 1 ? (Math.floor(T * 6) % 2 ? COL.green : 0x0e5a33) : COL.green);
      // the number lifting
      const lf = s.lift || 0;
      // The printed 700 stays still until its spoken emphasis; then it lifts normal to the sheet.
      num.visible = numShadow.visible = T >= 12.566 && T < 13.2666666667;
      if (T >= 12.566 && T < 13.2666666667) {
        // The cut-out uses the same font and source anchor as the printed heading (page row 1290).
        pr.localToWorld(tmp.set(-0.012, 0.1152, 0.2 + 0.018 + (1290 / 2339) * 0.297 * 0.92));
        const p = clamp((T - 12.566) / 0.44, 0, 1);
        const e = EASE.out(p);
        num.position.set(tmp.x, tmp.y + e * 0.22 + 0.002, tmp.z);
        num.rotation.set(-Math.PI / 2 * (1 - e), 0, 0);
        num.scale.setScalar(lerp(0.10, 0.38, e));
        numShadow.position.set(tmp.x, tmp.y + 0.001, tmp.z); numShadow.scale.setScalar(0.10); numShadow.material.opacity = 0.18 * (1 - e);
      }
    }, anchors: {} };
  }

  // ============================================================== FLOOR: the support floor, 700 desks (the film's recurring set)
  {
    const sc = new THREE.Scene(); const BG = 0xe6eaee; sc.background = new THREE.Color(BG); sc.fog = new THREE.Fog(BG, 45, 150);
    const hemi = new THREE.HemisphereLight(0xffffff, 0xaeb6c0, 1.45); sc.add(hemi);
    const sunL = sun(sc, [-30, 60, 25], [0, 0, 0], 40, 2.2, 0xfff3e2);
    const flM = flat(0xdadee3); const fl = new THREE.Mesh(new THREE.PlaneGeometry(200, 200), flM); fl.rotation.x = -Math.PI / 2; fl.receiveShadow = true; sc.add(fl);
    // carpet zones under the desk blocks (subtle, a model-maker's grey card)
    const COLS = 28, ROWS = 25, DX = 1.75, DZ = 2.15;
    const x0 = -(COLS - 1) * DX / 2, z0 = -(ROWS - 1) * DZ / 2;
    const deskM = [], chairM = [], monM = [], workM = [];
    const heroIdx = { c: 13, r: ROWS - 1 };                         // front row, just left of the centre aisle
    const aisle = (c) => (c >= 14 ? 1.4 : 0);                       // a centre aisle
    const slots = [];
    for (let r = 0; r < ROWS + 4; r++) for (let c = 0; c < COLS; c++) {
      const x = x0 + c * DX + aisle(c), z = z0 + r * DZ - (r >= ROWS ? 0 : 0);
      slots.push({ r, c, x, z: r < ROWS ? z : z0 - (r - ROWS + 1) * DZ, extra: r >= ROWS, hero: r === heroIdx.r && c === heroIdx.c });
    }
    const main = slots.filter((s) => !s.extra && !s.hero);           // 699 + hero = 700
    const extra = slots.filter((s) => s.extra).slice(0, 100);        // the 800 (2025)
    const all = main.concat(extra);
    const deskMat = flat(0xf3f4f5), chairMat = flat(0xc5cad1), monMat = flat(0x2f343c);
    const deskI = instanced(DESK.desk, deskMat, all.map((s) => M4(s.x, 0, s.z)), { colors: () => 0xffffff });
    const chairI = instanced(DESK.chair, chairMat, all.map((s) => M4(s.x, 0, s.z)), { colors: () => 0xffffff });
    const monI = instanced(DESK.mon, monMat, all.map((s) => M4(s.x, 0, s.z)), { colors: () => 0xffffff, noCast: true });
    sc.add(deskI, chairI, monI);
    // monitor faces: a glow plane per desk (instanced), colour = what the screen shows
    const scrGeo = new THREE.PlaneGeometry(0.54, 0.32);
    const scrI = new THREE.InstancedMesh(scrGeo, basic(0xffffff, { toneMapped: false }), all.length);
    all.forEach((s, i) => { scrI.setMatrixAt(i, M4(s.x, 1.12, s.z - 0.183, -0.06)); scrI.setColorAt(i, new THREE.Color(0x9fb3cf)); });
    sc.add(scrI);
    // seated workers (body / skin / hair) facing their monitors
    const wMat = new THREE.MeshLambertMaterial({ color: 0xffffff, flatShading: true, transparent: true, opacity: 1 });
    const sMat = new THREE.MeshLambertMaterial({ color: 0xe8e3db, flatShading: true, transparent: true, opacity: 1 });
    const hMat = new THREE.MeshLambertMaterial({ color: 0x8e949c, flatShading: true, transparent: true, opacity: 1 });
    const wX = (s) => M4(s.x, 0, s.z + 0.64, 0, Math.PI, 0);
    const wBody = instanced(WORKER.body, wMat, all.map(wX), { colors: (i) => [0xf2f3f5, 0xe4e7eb, 0xd5dae0, 0xf7f7f7][Math.floor(hash(i, 7) * 4)] });
    const wSkin = instanced(WORKER.skin, sMat, all.map(wX), {});
    const wHair = instanced(WORKER.hair, hMat, all.map(wX), { colors: (i) => [0x6b6f76, 0x9aa0a8, 0x4d5057, 0xb9a88f][Math.floor(hash(i, 9) * 4)] });
    sc.add(wBody, wSkin, wHair);
    // machine pods (the assistant, where a person used to sit): a white capsule with a light ring
    const podGeo = new THREE.CapsuleGeometry(0.2, 0.34, 3, 8); const podMat = flat(0xf7f8f9);
    const podI = instanced(podGeo, podMat, all.map((s) => M4(s.x, 0.95, s.z + 0.62)), {});
    const ringI = new THREE.InstancedMesh(new THREE.TorusGeometry(0.205, 0.018, 4, 20), basic(0xffb3c7, { toneMapped: false }), all.length);
    all.forEach((s, i) => ringI.setMatrixAt(i, M4(s.x, 1.1, s.z + 0.62, Math.PI / 2)));
    sc.add(podI, ringI);
    // walls: a low perimeter so it reads as a floor inside a building, windows along the left, two doors on the right
    const wallM = flat(0xeef0f2);
    const WX = x0 - 3.2, EX = -x0 + 4.6, NZ = z0 - 4 * DZ - 3, FZ = -z0 + 4.5;
    box(0.3, 3.6, FZ - NZ, wallM, WX, 1.8, (FZ + NZ) / 2, sc);
    for (let z = NZ + 2; z < FZ; z += 3.2) { const w = new THREE.Mesh(new THREE.PlaneGeometry(2.4, 2.2), basic(0xfbfcfd)); w.position.set(WX + 0.16, 1.9, z); w.rotation.y = Math.PI / 2; sc.add(w); }
    box(EX - WX, 3.6, 0.3, wallM, (EX + WX) / 2, 1.8, NZ, sc);
    const rightWall = new THREE.Group(); sc.add(rightWall);
    const DOOR_Z = [-4, 6];
    // right wall built in pieces around two door openings
    let zz = NZ; const edges = []; DOOR_Z.forEach((dz) => { edges.push([zz, dz - 0.8]); zz = dz + 0.8; }); edges.push([zz, FZ]);
    edges.forEach(([a, b]) => box(0.3, 3.6, b - a, wallM, EX, 1.8, (a + b) / 2, rightWall));
    DOOR_Z.forEach((dz) => { box(0.3, 1.2, 1.6, wallM, EX, 3.0, dz, rightWall); const frame = box(0.36, 2.44, 0.08, grey, EX - 0.02, 1.2, dz - 0.82, rightWall); box(0.36, 2.44, 0.08, grey, EX - 0.02, 1.2, dz + 0.82, rightWall); });
    const doorLabels = ["ENGINEERING", "MARKETING"].map((t, i) => { const m = labelMesh(t, { fs: 90, bg: "#14171c", color: "#ffffff", r: 12, pad: 40, font: MONO, weight: 500, track: 0.12 }, 1.5);
      m.position.set(EX - 0.17, 2.62, DOOR_Z[i]); m.rotation.y = -Math.PI / 2; sc.add(m); return m; });
    // columns
    for (let cx = -2; cx <= 2; cx++) for (let cz = -2; cz <= 2; cz++) box(0.6, 3.6, 0.6, whiteDim, cx * 11 + 0.7, 1.8, cz * 11, sc);
    // the hero desk (front row): a real desk, a lamp that switches on, a headset waiting, and its person
    const hs = slots.find((s) => s.hero);
    const hero = new THREE.Group(); hero.position.set(hs.x, 0, hs.z); sc.add(hero);
    hero.add(new THREE.Mesh(DESK.desk, deskMat)); hero.children[0].castShadow = true; hero.children[0].receiveShadow = true;
    const hChair = new THREE.Mesh(DESK.chair, chairMat); hChair.castShadow = true; hero.add(hChair);
    const hMon = new THREE.Mesh(DESK.mon, monMat); hero.add(hMon);
    const hScrTex = canvasTex(1080, 640, (g, w, h) => { g.fillStyle = "#f6f7f9"; g.fillRect(0, 0, w, h); g.fillStyle = "#2f6bff"; g.fillRect(0, 0, w, 70);
      g.fillStyle = "#fff"; g.font = "600 38px " + FONT; g.fillText("Support queue", 30, 48);
      for (let i = 0; i < 5; i++) { g.fillStyle = i === 0 ? "#e8efff" : "#ffffff"; rr(g, 30, 100 + i * 104, w - 60, 88, 12); g.fill(); g.fillStyle = "#c9ced6"; rr(g, 60, 128 + i * 104, 420, 18, 6); g.fill(); rr(g, 60, 158 + i * 104, 260, 14, 6); g.fill(); } });
    const hScr = new THREE.Mesh(new THREE.PlaneGeometry(0.54, 0.32), new THREE.MeshBasicMaterial({ map: hScrTex, toneMapped: false })); hScr.position.set(0, 1.12, -0.183); hScr.rotation.x = -0.06; hero.add(hScr);
    const lampArm = new THREE.Group(); lampArm.position.set(0.55, 0.77, -0.22); hero.add(lampArm);
    box(0.14, 0.02, 0.14, dark, 0, 0, 0, lampArm); const la = box(0.02, 0.42, 0.02, dark, 0, 0.21, 0, lampArm); la.rotation.z = 0.25;
    const shade = new THREE.Mesh(new THREE.ConeGeometry(0.09, 0.12, 10, 1, true), flat(0x2a2e35, { side: THREE.DoubleSide })); shade.position.set(-0.1, 0.42, 0.02); shade.rotation.z = 0.9; lampArm.add(shade);
    const bulb = new THREE.Mesh(new THREE.SphereGeometry(0.03, 8, 6), basic(0xfff1c9)); bulb.position.set(-0.13, 0.39, 0.02); lampArm.add(bulb);
    const lampLight = new THREE.PointLight(0xffe2b0, 0, 3.2, 1.6); lampLight.position.set(hs.x + 0.4, 1.1, hs.z - 0.15); sc.add(lampLight);
    const lampPool = new THREE.Mesh(new THREE.PlaneGeometry(1.8, 1.8), new THREE.MeshBasicMaterial({ map: glowTex, color: 0xffd9a0, transparent: true, opacity: 0, depthWrite: false }));
    lampPool.rotation.x = -Math.PI / 2; lampPool.position.set(hs.x + 0.25, 0.772, hs.z - 0.05); sc.add(lampPool);
    const deskHeadset = new THREE.Group(); deskHeadset.position.set(-0.35, 0.79, 0.05); hero.add(deskHeadset);
    { const hm = flat(0x2a2e35); const b = new THREE.Mesh(new THREE.TorusGeometry(0.09, 0.009, 5, 16, Math.PI), hm); b.rotation.x = -Math.PI / 2; deskHeadset.add(b);
      [-1, 1].forEach((s) => { const c = new THREE.Mesh(new THREE.CylinderGeometry(0.032, 0.032, 0.022, 10), hm); c.position.set(0.09 * s, 0.01, 0); deskHeadset.add(c); }); }
    const heroP = person({ body: 0xf2f3f5, legs: 0x9aa3ae, hair: 0x5d6168, headset: true });
    sc.add(heroP.root);
    // a glowing chat bubble above the hero desk (the assistant)
    const glowBub = new THREE.Mesh(bubbleGeo(1.2, 0.72, 1, 0.14), basic(0xffb3c7, { toneMapped: false }));
    glowBub.position.set(hs.x, 2.6, hs.z - 0.2); sc.add(glowBub);
    const glowHalo = new THREE.Mesh(new THREE.PlaneGeometry(4, 4), new THREE.MeshBasicMaterial({ map: glowTex, color: 0xffb3c7, transparent: true, opacity: 0.22, depthWrite: false, blending: THREE.AdditiveBlending }));
    glowHalo.position.copy(glowBub.position); sc.add(glowHalo);
    // walkers: engineers and marketers carrying laptops, from the two doors to empty desks near the front
    const walkers = [];
    for (let k = 0; k < 8; k++) {
      const p = person({ body: [0xe9ebee, 0xdfe3e8, 0xf4f4f4, 0xd4d9df][k % 4], legs: [0x7d8591, 0x5f6671, 0x9aa3ae][k % 3], hair: [0x5d6168, 0x9a8b76, 0x3d4047, 0xb0b5bb][k % 4], laptop: true, headset: k % 2 === 0 });
      const door = DOOR_Z[k % 2];
      const target = main.filter((s) => s.r >= ROWS - 6 && s.c >= 16)[k * 5 % 40];
      walkers.push({ p, from: [EX - 0.4, door], to: [target.x, target.z + 0.64], idx: main.indexOf(target), t0: k * 0.45 });
      sc.add(p.root);
    }
    // rehired lit desks: desk lamps (instanced glow disks) that switch on in sequence
    const litGeo = new THREE.PlaneGeometry(1.6, 1.6); const litMat = new THREE.MeshBasicMaterial({ map: glowTex, color: 0xffd9a0, transparent: true, opacity: 0.6, depthWrite: false });
    const litI = new THREE.InstancedMesh(litGeo, litMat, all.length); sc.add(litI);
    // scratch
    const m4 = new THREE.Matrix4(), zero = new THREE.Matrix4().makeScale(0, 0, 0), col = new THREE.Color();
    let lastKey = "";
    const GREY = new THREE.Color(0x9ea4ac), WHITE = new THREE.Color(0xffffff);
    out.floor = { scene: sc, anim(T, shot) {
      const s = st("floor", T);
      // s: {rise (0..1 rows appear), people (0..1 opacity), mode: "white"|"grey", emptyRows (0..ROWS rows emptied from the back),
      //     extra (0..1 the 800), pods (0..1 share of pods), lit (count of lit desks), hero {...}, bubble 0..1, walk 0..1, gs (0..1 grey mix)}
      const rise = s.rise === undefined ? 1 : s.rise, extraOn = s.extra || 0, emptyRows = s.emptyRows || 0, podShare = s.pods || 0, litN = s.lit || 0;
      const key = [Math.round(rise * 200), Math.round(extraOn * 100), Math.round(emptyRows * 10), Math.round(podShare * 100), litN, s.walk ? Math.round(s.walk * 60) : 0, s.onlyHero ? 1 : 0].join(",");
      if (key !== lastKey) {
        lastKey = key;
        all.forEach((sl, i) => {
          let vis = 1, y = 0;
          if (!sl.extra) { const rowT = (ROWS - 1 - sl.r) / ROWS; const a = clamp((rise * 1.25 - rowT * 0.9) / 0.35, 0, 1); vis = a; y = -(1 - EASE.out(a)) * 0.9; }
          else { const k = (sl.r - ROWS) * COLS + sl.c; const a = clamp(extraOn * 1.4 - (k / 100) * 0.4, 0, 1); vis = EASE.out(a); y = -(1 - vis) * 0.9; }
          const S1 = vis > 0.001 ? 1 : 0;
          const sc3 = S1 * Math.max(0.001, vis); m4.makeScale(sc3, sc3, sc3).setPosition(sl.x, y, sl.z);
          deskI.setMatrixAt(i, m4); chairI.setMatrixAt(i, m4); monI.setMatrixAt(i, m4);
          scrI.setMatrixAt(i, vis > 0.9 ? M4(sl.x, 1.12 + y, sl.z - 0.183, -0.06) : zero);
          // who sits here: a person, a pod, or nobody
          const rowFromBack = sl.extra ? -1 : sl.r;
          const emptied = !sl.extra && rowFromBack < emptyRows;
          const isPod = podShare > 0 && ((sl.c + sl.r) % 2 === 0) && hash(i, 13) < podShare * 1.8;
          const seated = vis > 0.95 && !emptied && !isPod && !s.onlyHero;
          const wm = seated ? M4(sl.x, 0, sl.z + 0.64, 0, Math.PI, 0) : zero;
          wBody.setMatrixAt(i, wm); wSkin.setMatrixAt(i, wm); wHair.setMatrixAt(i, wm);
          const pm = isPod && vis > 0.95 ? M4(sl.x, 0.95, sl.z + 0.62) : zero;
          podI.setMatrixAt(i, pm); ringI.setMatrixAt(i, isPod && vis > 0.95 ? M4(sl.x, 1.1, sl.z + 0.62, Math.PI / 2) : zero);
          litI.setMatrixAt(i, zero);
        });
        // lit desks: the front rows light first, from the hero desk outward
        if (litN > 0) {
          const order = main.map((sl, i) => ({ i: all.indexOf(sl), d: Math.hypot(sl.x - hs.x, (sl.z - hs.z) * 0.8) })).sort((a, b) => a.d - b.d);
          order.slice(0, litN).forEach((o) => { const sl = all[o.i]; litI.setMatrixAt(o.i, M4(sl.x + 0.2, 0.772, sl.z - 0.05, -Math.PI / 2));
            const wm = M4(sl.x, 0, sl.z + 0.64, 0, Math.PI, 0); wBody.setMatrixAt(o.i, wm); wSkin.setMatrixAt(o.i, wm); wHair.setMatrixAt(o.i, wm); });
        }
        // walkers take their desks: hide the instanced worker at those desks until they arrive
        walkers.forEach((w) => { if (s.walk !== undefined) { wBody.setMatrixAt(w.idx, zero); wSkin.setMatrixAt(w.idx, zero); wHair.setMatrixAt(w.idx, zero); } });
        [deskI, chairI, monI, scrI, wBody, wSkin, wHair, podI, ringI, litI].forEach((im) => { im.instanceMatrix.needsUpdate = true; });
      }
      // grey (2022) vs white (2024): desk + worker colours and the room
      const gs = s.gs || 0;
      deskMat.color.copy(WHITE).lerp(GREY, gs * 0.9); chairMat.color.set(0xc5cad1).lerp(new THREE.Color(0x7d838b), gs * 0.8);
      wMat.color.copy(WHITE).lerp(GREY, gs * 0.85); sMat.color.set(0xe8e3db).lerp(GREY, gs * 0.8);
      sc.background.set(BG).lerp(new THREE.Color(0x9da2a8), gs); sc.fog.color.copy(sc.background);
      flM.color.set(0xdadee3).lerp(new THREE.Color(0x8f949b), gs);
      hemi.intensity = lerp(1.45, 1.0, gs); sunL.intensity = lerp(2.2, 1.2, gs); sunL.color.set(0xfff3e2).lerp(new THREE.Color(0xdfe6ee), gs);
      const pp = s.people === undefined ? 1 : s.people;
      wMat.opacity = sMat.opacity = hMat.opacity = pp; wBody.visible = wSkin.visible = wHair.visible = pp > 0.01;
      wMat.depthWrite = sMat.depthWrite = hMat.depthWrite = pp > 0.99;
      // screens: blue-grey idle, or a chat (pink tint) when the assistant is working
      scrI.material.color.set(s.screens === "chat" ? 0xffd6e1 : s.screens === "off" ? 0x39404a : 0xb9c7da);
      // the hero desk and its person
      const h = s.hero || {};
      hero.visible = true;
      const lamp = h.lamp || 0; lampLight.intensity = 6 * lamp; bulb.material.color.set(lamp > 0.05 ? 0xfff1c9 : 0x6b6f76); lampPool.material.opacity = 0.5 * lamp;
      hScr.visible = (h.screen || 0) > 0.5; hMon.visible = true;
      // hero person: walks in from the aisle, sits, puts the headset on
      const hp = heroP; const arrive = h.arrive === undefined ? -1 : h.arrive;
      hp.root.visible = arrive >= 0;
      if (arrive >= 0) {
        const wx = lerp(hs.x + 0.95, hs.x + 0.05, EASE.out(clamp(arrive / 0.55, 0, 1)));
        const wz = hs.z + 0.64 + lerp(0.6, 0, EASE.out(clamp(arrive / 0.55, 0, 1)));
        const sit = EASE.io(clamp((arrive - 0.5) / 0.3, 0, 1));
        hp.root.position.set(wx, 0, wz);
        hp.root.rotation.y = lerp(-Math.PI / 2 - 0.3, -Math.PI, EASE.io(clamp((arrive - 0.35) / 0.3, 0, 1)));
        const ear = clamp((arrive - 0.8) / 0.12, 0, 1) * (1 - clamp((arrive - 0.94) / 0.06, 0, 1));
        pose(hp, { sit, walk: arrive < 0.55 ? 1 - sit : 0, phase: T * 7.5, ear, t: T, typing: arrive > 0.99 ? (h.typing || 0) : 0, look: -0.12 });
        hp.headset.visible = arrive > 0.86; deskHeadset.visible = arrive <= 0.86;
        hp.headsetLight.material.color.set(arrive > 0.9 ? COL.green : 0x3b4450);
      } else deskHeadset.visible = true;
      // the chat bubble over the hero desk
      const bb = s.bubble || 0; glowBub.visible = glowHalo.visible = bb > 0.01;
      glowBub.scale.setScalar(0.4 + 0.6 * EASE.out(bb)); glowBub.position.y = 2.6 + Math.sin(T * 1.4) * 0.05; glowBub.rotation.y = Math.sin(T * 0.6) * 0.2;
      glowHalo.position.copy(glowBub.position); glowHalo.position.z -= 0.2; glowHalo.material.opacity = 0.5 * bb * (0.85 + 0.15 * Math.sin(T * 3));
      if (shot && shot.cam) { glowHalo.lookAt(new THREE.Vector3(...shot.cam[0].p)); }
      // walkers
      const wk = s.walk;
      walkers.forEach((w, k) => {
        w.p.root.visible = wk !== undefined && wk >= 0;
        if (!w.p.root.visible) return;
        const a = clamp((wk * 8 - w.t0) / 5.5, 0, 1);                      // each walker's own progress
        const e = EASE.sio(a);
        // path: out of the door (-x), along the front aisle, down to the desk
        const mid = [w.to[0], w.from[1] + (w.to[1] - w.from[1]) * 0.15];
        let x, z, dir;
        if (e < 0.55) { const u = e / 0.55; x = lerp(w.from[0], mid[0], u); z = lerp(w.from[1], mid[1], u); dir = Math.atan2(mid[0] - w.from[0], mid[1] - w.from[1]); }
        else { const u = (e - 0.55) / 0.45; x = mid[0]; z = lerp(mid[1], w.to[1], u); dir = Math.atan2(0, w.to[1] - mid[1]); }
        const sit = EASE.io(clamp((a - 0.9) / 0.1, 0, 1));
        w.p.root.position.set(x, 0, z);
        w.p.root.rotation.y = sit > 0 ? lerp(dir, Math.PI, sit) : dir;
        pose(w.p, { walk: a < 0.97 ? 1 : 0, phase: T * 7.2 + k, sit, carry: 1 - sit, t: T, id: k });
        if (w.p.laptop) w.p.laptop.visible = sit < 0.5;
      });
      // shadows follow the shot: tight for close work, wide for the aerials
      const ss = (shot && shot.ss) || 38;
      const tgt = (shot && shot.cam) ? shot.cam[1] ? shot.cam[1].l : shot.cam[0].l : [0, 0, 0];
      sunL.target.position.set(tgt[0], 0, tgt[2]); sunL.position.set(tgt[0] - 30, 60, tgt[2] + 25);
      const c = sunL.shadow.camera; if (c.right !== ss) { c.left = -ss; c.right = ss; c.top = ss; c.bottom = -ss; c.updateProjectionMatrix(); }
    }, anchors: { hero: [hs.x, 1.9, hs.z], bubble: [hs.x, 3.2, hs.z - 0.2], doorE: [EX - 0.3, 3.1, DOOR_Z[0]], doorM: [EX - 0.3, 3.1, DOOR_Z[1]],
      back: [0, 2.2, z0], front: [0, 2.0, -z0], extra: [0, 2.2, z0 - 2.5 * DZ] },
      info: { x0, z0, DX, DZ, COLS, ROWS, hs, EX, WX, NZ, FZ, DOOR_Z } };
  }

  // ============================================================== GLOBE: faceted Earth, raised land, lights spreading, market pins
  {
    const sc = new THREE.Scene(); sc.background = new THREE.Color(0x0e1218); sc.fog = new THREE.Fog(0x0e1218, 60, 160);
    sc.add(new THREE.HemisphereLight(0xdfe6f0, 0x1c222b, 1.2));
    const key = new THREE.DirectionalLight(0xfff4e6, 2.4); key.position.set(-30, 25, 40); sc.add(key);
    const rim = new THREE.DirectionalLight(0x9fb8ff, 1.2); rim.position.set(40, 10, -30); sc.add(rim);
    // land mask: draw the Mercator land path, then sample it by lat/lon
    const M = window.AG_MAP; const MW = 2000, MH = 1775;
    const mc = document.createElement("canvas"); mc.width = MW; mc.height = MH; const mg = mc.getContext("2d");
    mg.fillStyle = "#000"; mg.fillRect(0, 0, MW, MH); mg.scale(MW / M.w, MH / M.h); mg.fillStyle = "#fff"; mg.fill(new Path2D(M.land));
    const md = mg.getImageData(0, 0, MW, MH).data;
    const isLand = (lon, lat) => { if (lat < -60) return true; if (lat > 83) return false; const p = M.project(lon, lat); const x = Math.floor(p[0] * MW / M.w), y = Math.floor(p[1] * MH / M.h);
      if (x < 0 || y < 0 || x >= MW || y >= MH) return false; return md[(y * MW + x) * 4] > 127; };
    const R = 10;
    const g = new THREE.IcosahedronGeometry(R, 42); // non-indexed, 20*43^2 faces
    const pos = g.attributes.position; const colors = new Float32Array(pos.count * 3);
    const landC = new THREE.Color(0xf2f3f4), seaC = new THREE.Color(0x2b3442), a = new THREE.Vector3(), b = new THREE.Vector3(), c = new THREE.Vector3(), n = new THREE.Vector3();
    const landFaces = [];
    for (let f = 0; f < pos.count; f += 3) {
      a.fromBufferAttribute(pos, f); b.fromBufferAttribute(pos, f + 1); c.fromBufferAttribute(pos, f + 2);
      n.copy(a).add(b).add(c).divideScalar(3).normalize();
      const lat = Math.asin(n.y) * 180 / Math.PI, lon = Math.atan2(n.x, n.z) * 180 / Math.PI;
      const land = isLand(lon, lat);
      const col = land ? landC.clone().multiplyScalar(0.96 + hash(f, 3) * 0.04) : seaC.clone().multiplyScalar(0.94 + hash(f, 5) * 0.08);
      for (let k = 0; k < 3; k++) { colors[(f + k) * 3] = col.r; colors[(f + k) * 3 + 1] = col.g; colors[(f + k) * 3 + 2] = col.b;
        if (land) { const v = new THREE.Vector3().fromBufferAttribute(pos, f + k).multiplyScalar(1.012); pos.setXYZ(f + k, v.x, v.y, v.z); } }
      if (land && Math.abs(lat) < 72) landFaces.push({ lon, lat, n: n.clone() });
    }
    g.setAttribute("color", new THREE.BufferAttribute(colors, 3)); g.computeVertexNormals();
    const globe = new THREE.Group(); sc.add(globe);
    globe.add(new THREE.Mesh(g, new THREE.MeshLambertMaterial({ vertexColors: true, flatShading: true })));
    // atmosphere rim
    const atm = new THREE.Mesh(new THREE.SphereGeometry(R * 1.035, 48, 32), new THREE.MeshBasicMaterial({ color: 0x9fb8ff, transparent: true, opacity: 0.08, side: THREE.BackSide, depthWrite: false })); globe.add(atm);
    // 150 million people: lights on land, spreading (instanced tiny emissive facets, ordered by a deterministic spread)
    const NL = 2600; const lights = [];
    for (let i = 0; i < NL; i++) { const f = landFaces[Math.floor(hash(i, 21) * landFaces.length)]; const wt = (f.lat > 30 && f.lat < 62 && f.lon > -12 && f.lon < 32) ? 0 : (f.lat > 20 && f.lon < -60 ? 0.3 : 0.6);
      lights.push({ f, order: wt + hash(i, 23) * 0.4 }); }
    lights.sort((p, q) => p.order - q.order);
    const lightI = new THREE.InstancedMesh(new THREE.OctahedronGeometry(0.05, 0), basic(0xffd27a, { toneMapped: false }), NL); globe.add(lightI);
    // 23 market pins (unlabelled): Europe-heavy, plus North America and Oceania
    const PIN_LL = [[18, 59.3], [10.7, 59.9], [12.5, 55.7], [25, 60.2], [13.4, 52.5], [-0.1, 51.5], [2.35, 48.85], [4.9, 52.4], [4.35, 50.85], [16.4, 48.2], [8.55, 47.4],
      [-3.7, 40.4], [12.5, 41.9], [-9.1, 38.7], [21, 52.2], [14.4, 50.1], [-6.3, 53.3], [23.7, 37.98], [-74, 40.7], [-79.4, 43.7], [-99.1, 19.4], [151.2, -33.9], [174.8, -36.8]];
    const toV = (lon, lat, r) => { const la = lat * Math.PI / 180, lo = lon * Math.PI / 180; return new THREE.Vector3(Math.cos(la) * Math.sin(lo) * r, Math.sin(la) * r, Math.cos(la) * Math.cos(lo) * r); };
    const pins = PIN_LL.map(([lon, lat]) => {
      const gp = new THREE.Group(); const v = toV(lon, lat, R * 1.012); gp.position.copy(v); gp.lookAt(v.clone().multiplyScalar(2)); globe.add(gp);
      const stem = new THREE.Mesh(new THREE.CylinderGeometry(0.02, 0.02, 0.5, 5), basic(0xffb3c7)); stem.rotation.x = Math.PI / 2; stem.position.z = 0.25; gp.add(stem);
      const head = new THREE.Mesh(new THREE.OctahedronGeometry(0.1, 0), basic(0xffb3c7, { toneMapped: false })); head.position.z = 0.52; gp.add(head);
      const ring = new THREE.Mesh(new THREE.RingGeometry(0.16, 0.2, 24), new THREE.MeshBasicMaterial({ color: 0xffb3c7, transparent: true, depthWrite: false, side: THREE.DoubleSide })); ring.position.z = 0.02; gp.add(ring);
      return { gp, ring };
    });
    const m4 = new THREE.Matrix4(), zero = new THREE.Matrix4().makeScale(0, 0, 0);
    let lastN = -1;
    out.globe = { scene: sc, anim(T) {
      const s = st("globe", T);   // {spin (radians), lights 0..1, pins 0..23 (fractional), tilt}
      globe.rotation.y = s.spin || 0; globe.rotation.x = s.tilt || 0.35;
      const nOn = Math.floor((s.lights || 0) * NL);
      if (nOn !== lastN) { lastN = nOn;
        lights.forEach((L, i) => { if (i < nOn) { const v = L.f.n.clone().multiplyScalar(R * 1.016); m4.makeTranslation(v.x, v.y, v.z); lightI.setMatrixAt(i, m4); } else lightI.setMatrixAt(i, zero); });
        lightI.instanceMatrix.needsUpdate = true; }
      const pn = s.pins || 0;
      pins.forEach((p, i) => { const a = clamp(pn - i, 0, 1); p.gp.visible = a > 0; p.gp.scale.setScalar(EASE.out(a) + 0.001);
        const ph = (T * 0.9 + i * 0.37) % 1; p.ring.scale.setScalar(1 + ph * 2.5); p.ring.material.opacity = 0.8 * (1 - ph) * a; });
    }, anchors: {} };
  }

  // ============================================================== HOME: THE CUSTOMER (blue), a flat, a phone
  {
    const sc = new THREE.Scene(); sc.background = new THREE.Color(0xe8e6e1); sc.fog = new THREE.Fog(0xe8e6e1, 8, 22);
    sc.add(new THREE.HemisphereLight(0xffffff, 0xb8b2a8, 1.3));
    const key = sun(sc, [-4, 5, -3], [0, 0.6, 0], 4, 2.6, 0xfff0dc);
    const flM = flat(0xd8d3cb); const fl = new THREE.Mesh(new THREE.PlaneGeometry(30, 30), flM); fl.rotation.x = -Math.PI / 2; fl.receiveShadow = true; sc.add(fl);
    const wallM = flat(0xf0eee9);
    box(8, 3, 0.15, wallM, 0, 1.5, -2.2, sc); box(0.15, 3, 6, wallM, -3.2, 1.5, 0.5, sc);
    // window with frames on the back wall; light pours in
    const win = new THREE.Mesh(new THREE.PlaneGeometry(1.8, 1.8), basic(0xfefefe)); win.position.set(-1.2, 1.7, -2.12); sc.add(win);
    [-2.1, -1.2, -0.3].forEach((x) => box(0.05, 1.9, 0.06, flat(0xffffff), x, 1.7, -2.1, sc)); box(1.9, 0.05, 0.06, flat(0xffffff), -1.2, 1.7, -2.1, sc);
    box(1.9, 0.06, 0.2, flat(0xffffff), -1.2, 0.78, -2.06, sc);
    // sofa
    const sofaM = flat(0xc9c2b6), sofaD = flat(0xb7b0a3);
    box(2.2, 0.42, 0.9, sofaM, 0.3, 0.21, -0.2, sc); box(2.2, 0.55, 0.22, sofaD, 0.3, 0.62, -0.55, sc);
    box(0.24, 0.3, 0.9, sofaD, -0.78, 0.55, -0.2, sc); box(0.24, 0.3, 0.9, sofaD, 1.38, 0.55, -0.2, sc);
    [-0.25, 0.55].forEach((x) => box(0.78, 0.12, 0.7, flat(0xd3ccc1), x + 0.05, 0.47, -0.12, sc));
    // a floor lamp, a plant, a rug, a side table with a mug
    box(0.02, 1.5, 0.02, dark, 1.9, 0.75, -0.9, sc); const sh = new THREE.Mesh(new THREE.CylinderGeometry(0.16, 0.22, 0.26, 10, 1, true), flat(0xf6f1e6, { side: THREE.DoubleSide })); sh.position.set(1.9, 1.55, -0.9); sc.add(sh);
    const rug = new THREE.Mesh(new THREE.PlaneGeometry(2.6, 1.6), flat(0xe3ddd2)); rug.rotation.x = -Math.PI / 2; rug.position.set(0.3, 0.005, 0.9); rug.receiveShadow = true; sc.add(rug);
    box(0.4, 0.45, 0.4, flat(0xffffff), -1.2, 0.225, -0.3, sc);
    const pot = new THREE.Mesh(new THREE.CylinderGeometry(0.16, 0.12, 0.3, 8), flat(0xd8d3cb)); pot.position.set(-2.4, 0.15, -1.6); sc.add(pot);
    for (let k = 0; k < 11; k++) { const lf = new THREE.Mesh(new THREE.IcosahedronGeometry(0.16, 0), flat(0x9fb39a)); lf.scale.set(0.45, 1.5, 0.25); lf.position.set(-2.4 + Math.sin(k * 2.4) * 0.14, 0.55 + hash(k, 3) * 0.35, -1.6 + Math.cos(k * 2.4) * 0.14); lf.rotation.set(Math.sin(k) * 0.6, k, Math.cos(k * 1.3) * 0.6); lf.castShadow = true; sc.add(lf); }
    // the phone screen: a canvas at 1080x2340, redrawn when the state changes
    const PW = 1080, PH = 2340;
    const phTex = canvasTex(PW, PH, (g) => { g.fillStyle = "#fff"; g.fillRect(0, 0, PW, PH); });
    const phMat = new THREE.MeshBasicMaterial({ map: phTex, toneMapped: false });
    const cust = person({ body: COL.blue, legs: COL.blueDeep, hair: 0x2c3140, skin: 0xdcd6cc, phone: true, phoneScreen: phMat });
    cust.root.position.set(0.1, 0, -0.08); cust.root.rotation.y = 0; sc.add(cust.root);
    // errand bubbles rising from the phone
    const errTex = canvasTex(512, 256, (g, w, h) => { g.fillStyle = "#14171c"; g.font = "500 76px " + MONO; g.textAlign = "center"; g.textBaseline = "middle"; g.fillText("ERRAND", w / 2, h / 2 + 4); });
    const bubbles = [];
    for (let k = 0; k < 14; k++) {
      const gb = new THREE.Group(); sc.add(gb);
      const b = new THREE.Mesh(bubbleGeo(0.5, 0.3, 1, 0.07), flat(0xffffff, { emissive: 0x333333 })); gb.add(b);
      const l = new THREE.Mesh(new THREE.PlaneGeometry(0.42, 0.21), new THREE.MeshBasicMaterial({ map: errTex, transparent: true, depthWrite: false })); l.position.z = 0.061; gb.add(l);
      bubbles.push({ gb, k });
    }
    let phKey = "";
    function drawPhone(m) {
      const g = phTex.userData.canvas.getContext("2d");
      g.setTransform(1, 0, 0, 1, 0, 0);
      g.fillStyle = "#f7f7f8"; g.fillRect(0, 0, PW, PH);
      g.fillStyle = "#14171c"; g.font = "600 44px " + FONT; g.fillText("9:41", 70, 90);
      if (m.mode === "checkout") {
        g.fillStyle = "#14171c"; g.font = "700 76px " + FONT; g.fillText("Checkout", 70, 260);
        g.fillStyle = "#e9e7e3"; rr(g, 70, 330, PW - 140, 520, 36); g.fill();
        g.fillStyle = "#cfd3d8"; rr(g, 120, 380, 300, 300, 24); g.fill();
        g.fillStyle = "#14171c"; g.font = "600 56px " + FONT; g.fillText("Trainers", 470, 450); g.fillStyle = "#6b7280"; g.font = "500 44px " + FONT; g.fillText("Size 9", 470, 520);
        g.fillStyle = "#14171c"; g.font = "700 96px " + FONT; g.fillText("£120.00", 470, 660);
        // the split into instalments
        const sp = m.split || 0;
        for (let i = 0; i < 3; i++) { const x = 70 + i * 320, a = clamp(sp * 3 - i, 0, 1);
          g.globalAlpha = a; g.fillStyle = "#ffffff"; rr(g, x, 920, 290, 250, 30); g.fill(); g.strokeStyle = "#14171c"; g.lineWidth = 4; rr(g, x, 920, 290, 250, 30); g.stroke();
          g.fillStyle = "#14171c"; g.font = "700 70px " + FONT; g.fillText("£40", x + 60, 1040); g.fillStyle = "#6b7280"; g.font = "500 40px " + FONT; g.fillText(["Today", "In 30 days", "In 60 days"][i], x + 50, 1120); g.globalAlpha = 1; }
        const pressed = m.tap ? 1 : 0;
        g.fillStyle = pressed ? "#e98ca4" : "#ffb3c7"; rr(g, 70, 1300, PW - 140, 190, 95); g.fill();
        g.fillStyle = "#14171c"; g.font = "700 72px " + FONT; g.textAlign = "center"; g.fillText("Pay later", PW / 2, 1420); g.textAlign = "left";
        g.fillStyle = "#6b7280"; g.font = "500 40px " + FONT; g.fillText("Pay in 3 interest-free payments", 190, 1580);
      } else if (m.mode === "chat") {
        g.fillStyle = "#14171c"; g.font = "700 64px " + FONT; g.fillText("Help", 70, 250);
        g.fillStyle = "#6b7280"; g.font = "500 40px " + FONT; g.fillText(m.human ? "Chatting with a person" : "Chat assistant", 70, 320);
        g.fillStyle = "#e5e7eb"; g.fillRect(0, 370, PW, 3);
        let y = 460;
        (m.lines || []).forEach((ln) => {
          const me = ln[0] === ">"; const txt = me ? ln.slice(1) : ln; g.font = "500 50px " + FONT;
          const w = Math.min(PW - 260, g.measureText(txt).width + 80);
          g.fillStyle = me ? "#2f6bff" : "#ffffff"; rr(g, me ? PW - 70 - w : 70, y, w, 120, 40); g.fill();
          if (!me) { g.strokeStyle = "#e5e7eb"; g.lineWidth = 3; rr(g, 70, y, w, 120, 40); g.stroke(); }
          g.fillStyle = me ? "#ffffff" : "#14171c"; g.fillText(txt, (me ? PW - 70 - w : 70) + 40, y + 76); y += 160;
        });
        if (m.typing) { g.fillStyle = "#ffffff"; rr(g, 70, y, 200, 110, 40); g.fill(); for (let i = 0; i < 3; i++) { g.fillStyle = "#9ca3af"; g.beginPath(); g.arc(125 + i * 45, y + 55, 13, 0, Math.PI * 2); g.fill(); } }
        if (m.button) { g.fillStyle = "#2f6bff"; rr(g, 70, PH - 380, PW - 140, 170, 85); g.fill(); g.fillStyle = "#fff"; g.font = "700 64px " + FONT; g.textAlign = "center"; g.fillText("Talk to a person", PW / 2, PH - 272); g.textAlign = "left"; }
      } else if (m.mode === "call") {
        g.fillStyle = "#14171c"; g.fillRect(0, 0, PW, PH); g.fillStyle = "#fff"; g.textAlign = "center";
        g.font = "600 64px " + FONT; g.fillText(m.label || "Calling", PW / 2, 700); g.font = "500 44px " + MONO; g.fillStyle = "#9ca3af"; g.fillText(m.sub || "", PW / 2, 790);
        g.fillStyle = m.hang ? "#e0412f" : "#2fd27a"; g.beginPath(); g.arc(PW / 2, PH - 500, 110, 0, Math.PI * 2); g.fill(); g.textAlign = "left";
      }
      phTex.needsUpdate = true;
    }
    out.home = { scene: sc, anim(T, shot) {
      const s = st("home", T);   // {phone: screen model, lift 0..1, bubbles 0..1, lower 0..1}
      const m = s.screen || { mode: "checkout" };
      const k = JSON.stringify(m) + (K.fontsReady() ? 1 : 0);
      if (k !== phKey) { phKey = k; drawPhone(m); }
      const lift = s.lift === undefined ? 1 : s.lift, lower = s.lower || 0;
      pose(cust, { sit: 1, phone: clamp(lift - lower, 0, 1), phone2: 0.0, look: -0.35 + lower * 0.25, t: T, turn: Math.sin(T * 0.4) * 0.04 });
      cust.pelvis.position.z = 0.02;
      // errand bubbles
      const bl = s.bubbles || 0;
      const ph = new THREE.Vector3(); cust.phone.getWorldPosition(ph);
      bubbles.forEach((b) => { const a = bl * 1.6 - b.k * 0.08; const u = ((a % 1) + 1) % 1; const on = a > 0;
        b.gb.visible = on; if (!on) return;
        b.gb.position.set(ph.x + Math.sin(b.k * 2.3) * (0.2 + u * 0.8), ph.y + 0.15 + u * 2.4, ph.z + Math.cos(b.k * 1.7) * 0.3 - u * 0.5);
        b.gb.scale.setScalar(0.35 + EASE.out(Math.min(1, u * 4)) * 0.65 - Math.max(0, u - 0.8) * 3);
        if (shot && shot.cam) b.gb.lookAt(new THREE.Vector3(...shot.cam[0].p)); });
    }, anchors: { phone: () => { const v = new THREE.Vector3(); cust.phone.getWorldPosition(v); return [v.x, v.y + 0.14, v.z]; } } };
  }
  return out;
}
