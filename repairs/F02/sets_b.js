// F02 sets B: THE SCOREBOARD (the film's signature: a split-flap board, four slots and a fifth that never gets a
// number), the scales (the machine's test), the sorting line (repeat vs hard errands), and the studio (a TV set and a
// podcast table). Built for this film only. Every value is a pure function of film time T.
export function createSetsB(K) {
  const { THREE, flat, basic, hash, prog, EASE, lerp, clamp, S, person, pose, M4, canvasTex, box, rr, sun, FONT, HEAVY, SERIF, MONO, COL,
    bubbleGeo, labelMesh, labelTex, glowTex } = K;
  const st = (name, T) => (S[name] ? S[name](T) : {});
  const out = {};
  const white = flat(COL.white), whiteDim = flat(COL.whiteDim), grey = flat(COL.grey), dark = flat(COL.slate), ink = flat(COL.ink);

  // ============================================================== BOARD: the split-flap scoreboard
  {
    const sc = new THREE.Scene(); const BG = 0x0d1117; sc.background = new THREE.Color(BG); sc.fog = new THREE.Fog(BG, 22, 60);
    sc.add(new THREE.HemisphereLight(0xc9d6ea, 0x0b0e13, 0.9));
    const spotA = new THREE.SpotLight(0xfff0dc, 900, 40, 0.5, 0.6, 1.6); spotA.position.set(-6, 9, 12); spotA.target.position.set(-3, 5, 0); sc.add(spotA, spotA.target);
    const spotB = new THREE.SpotLight(0xdfe8ff, 700, 40, 0.5, 0.6, 1.6); spotB.position.set(8, 10, 10); spotB.target.position.set(5, 5, 0); sc.add(spotB, spotB.target);
    const fill = new THREE.DirectionalLight(0xffffff, 0.6); fill.position.set(0, 4, 20); sc.add(fill);
    // glyph atlas: 8 x 8 cells of 256 x 320, white on the flap colour
    const GL = " 0123456789<>$%?.,:-+ABCDEFGHIJKLMNOPQRSTUVWXYZ'/";
    const CW = 256, CH = 320, AC = 8, AR = Math.ceil(GL.length / AC);
    const FLAPC = "#23272e";
    const atlas = canvasTex(CW * AC, CH * AR, (g) => {
      g.fillStyle = FLAPC; g.fillRect(0, 0, CW * AC, CH * AR);
      g.textAlign = "center"; g.textBaseline = "middle";
      for (let i = 0; i < GL.length; i++) {
        const cx = (i % AC) * CW, cy = Math.floor(i / AC) * CH;
        const grd = g.createLinearGradient(0, cy, 0, cy + CH); grd.addColorStop(0, "#2a2f37"); grd.addColorStop(0.5, "#1f232a"); grd.addColorStop(0.5, "#191c22"); grd.addColorStop(1, "#23272e");
        g.fillStyle = grd; g.fillRect(cx + 4, cy + 4, CW - 8, CH - 8);
        g.fillStyle = "#f4f2ec"; g.font = "500 300px " + MONO; g.fillText(GL[i], cx + CW / 2, cy + CH / 2 + 14);
      }
    });
    atlas.anisotropy = 16; atlas.generateMipmaps = true;
    const flapMat = new THREE.MeshBasicMaterial({ map: atlas, toneMapped: false, side: THREE.FrontSide });
    const geoCache = {};
    function halfGeo(ch, top, w, h) {
      const k = ch + (top ? "T" : "B") + w + "x" + h; if (geoCache[k]) return geoCache[k];
      let i = GL.indexOf(ch); if (i < 0) i = 0;
      const u0 = (i % AC) / AC, u1 = u0 + 1 / AC, vTop = 1 - Math.floor(i / AC) / AR, vBot = vTop - 1 / AR, vMid = (vTop + vBot) / 2;
      const g = new THREE.PlaneGeometry(w, h / 2);
      const uv = g.attributes.uv; // order: (0,1) (1,1) (0,0) (1,0) -> top-left, top-right, bottom-left, bottom-right
      const a = top ? vTop : vMid, b = top ? vMid : vBot;
      uv.setXY(0, u0, a); uv.setXY(1, u1, a); uv.setXY(2, u0, b); uv.setXY(3, u1, b); uv.needsUpdate = true;
      geoCache[k] = g; return g;
    }
    // a flap cell: housing, static top (next), static bottom (current), and the falling flap (front: current top, back: next bottom)
    function cell(parent, x, y, w, h) {
      const g = new THREE.Group(); g.position.set(x, y, 0.1); parent.add(g);
      const hous = new THREE.Mesh(new THREE.BoxGeometry(w * 1.1, h * 1.08, 0.12), flat(0x0f1216)); hous.position.z = -0.07; g.add(hous);
      const top = new THREE.Mesh(halfGeo(" ", true, w, h), flapMat); top.position.y = h / 4; g.add(top);
      const bot = new THREE.Mesh(halfGeo(" ", false, w, h), flapMat); bot.position.y = -h / 4; g.add(bot);
      const piv = new THREE.Group(); piv.position.z = 0.012; g.add(piv);
      const ff = new THREE.Mesh(halfGeo(" ", true, w, h), flapMat); ff.position.y = h / 4; piv.add(ff);
      const fb = new THREE.Mesh(halfGeo(" ", false, w, h), flapMat); fb.rotation.x = Math.PI; fb.position.y = h / 4; piv.add(fb);
      const seam = new THREE.Mesh(new THREE.PlaneGeometry(w, 0.012), basic(0x050608)); seam.position.z = 0.02; g.add(seam);
      const pins = [-1, 1].map((s) => { const p = new THREE.Mesh(new THREE.CylinderGeometry(0.018, 0.018, 0.05, 6), grey); p.rotation.z = Math.PI / 2; p.position.set(s * (w / 2 + 0.02), 0, 0.01); g.add(p); return p; });
      return { g, top, bot, piv, ff, fb, w, h, set(from, to, p) {
        // p: 0 (showing from) .. 1 (showing to); one flap, no intermediate characters
        const e = EASE.in(clamp(p, 0, 1));
        if (p <= 0 || from === to) { top.geometry = halfGeo(from === to ? to : from, true, w, h); bot.geometry = halfGeo(from === to ? to : from, false, w, h); piv.visible = false; return; }
        if (p >= 1) { top.geometry = halfGeo(to, true, w, h); bot.geometry = halfGeo(to, false, w, h); piv.visible = false; return; }
        top.geometry = halfGeo(to, true, w, h); bot.geometry = halfGeo(from, false, w, h);
        ff.geometry = halfGeo(from, true, w, h); fb.geometry = halfGeo(to, false, w, h);
        piv.visible = true; piv.rotation.x = -Math.PI * e;
        ff.visible = e < 0.5; fb.visible = e >= 0.5;
      } };
    }
    // the board: five slots in a steel frame
    const board = new THREE.Group(); sc.add(board); board.position.set(0, 5.2, 0);
    const BW = 22.4, BH = 5.0;
    box(BW, BH, 0.4, flat(0x161a20), 0, 0, -0.3, board);
    // white frame + truss (the model-maker look: white members)
    const frameM = flat(0xe9ecef);
    [[0, BH / 2 + 0.2, BW + 0.8, 0.4], [0, -BH / 2 - 0.2, BW + 0.8, 0.4]].forEach(([x, y, w, h]) => box(w, h, 0.5, frameM, x, y, -0.2, board));
    [-BW / 2 - 0.2, BW / 2 + 0.2].forEach((x) => box(0.4, BH + 0.8, 0.5, frameM, x, 0, -0.2, board));
    for (let k = 0; k < 12; k++) { const x = -BW / 2 + k * BW / 11; const d = box(0.12, 3.2, 0.12, frameM, x, BH / 2 + 1.9, -0.4, board); }
    box(BW + 0.8, 0.14, 0.14, frameM, 0, BH / 2 + 3.5, -0.4, board);
    for (let k = 0; k < 11; k++) { const x = -BW / 2 + (k + 0.5) * BW / 11; const d = box(0.08, 3.4, 0.08, frameM, x, BH / 2 + 1.9, -0.4, board); d.rotation.z = (k % 2 ? 0.6 : -0.6); }
    // cables up into the dark
    [-7, 7].forEach((x) => { const c = new THREE.Mesh(new THREE.CylinderGeometry(0.03, 0.03, 20, 5), dark); c.position.set(x, BH / 2 + 13.5, -0.4); board.add(c); });
    const SLOT_W = 4.2, CELLW = 0.62, CELLH = 0.8;
    const LABELS = ["SPEED", "VOLUME", "REPEAT QUESTIONS", "MONEY", "ON PAR WITH HUMANS"];
    const slots = LABELS.map((lab, i) => {
      const g = new THREE.Group(); board.add(g); g.position.set(-BW / 2 + 0.3 + SLOT_W / 2 + i * (SLOT_W + 0.22), 0, 0);
      const panel = box(SLOT_W, BH - 0.5, 0.1, flat(0x1b2027), 0, 0, -0.05, g, true);
      const lt = labelTex(lab, { fs: lab.length > 12 ? 104 : 124, color: "#f4f2ec", font: MONO, weight: 500, track: 0.08, w: 1600, h: 170 });
      const lm = new THREE.Mesh(new THREE.PlaneGeometry(SLOT_W - 0.3, (SLOT_W - 0.3) * 170 / 1600), new THREE.MeshBasicMaterial({ map: lt, transparent: true, toneMapped: false }));
      lm.position.set(0, BH / 2 - 0.55, 0.02); g.add(lm);
      const rule = box(SLOT_W - 0.5, 0.03, 0.02, basic(0x3a414c), 0, BH / 2 - 0.9, 0.01, g, true);
      const n = i === 4 ? 1 : 6;
      const cells = []; for (let c = 0; c < n; c++) cells.push(cell(g, (c - (n - 1) / 2) * (CELLW + 0.05), 0.35, i === 4 ? 1.1 : CELLW, CELLH));
      // status lamp
      const lampG = new THREE.Group(); lampG.position.set(0, -0.85, 0.02); g.add(lampG);
      const lampBez = new THREE.Mesh(new THREE.CylinderGeometry(0.2, 0.2, 0.06, 20), flat(0x0f1216)); lampBez.rotation.x = Math.PI / 2; lampG.add(lampBez);
      const lamp = new THREE.Mesh(new THREE.CircleGeometry(0.15, 24), basic(0x2a3038, { toneMapped: false })); lamp.position.z = 0.035; lampG.add(lamp);
      const halo = new THREE.Mesh(new THREE.PlaneGeometry(1.3, 1.3), new THREE.MeshBasicMaterial({ map: glowTex, color: COL.green, transparent: true, opacity: 0, depthWrite: false, toneMapped: false, blending: THREE.AdditiveBlending })); halo.position.z = 0.03; lampG.add(halo);
      // sub-label (redrawn when its text changes)
      let subTxt = "";
      const subTex = canvasTex(1600, 360, () => {});
      const sub = new THREE.Mesh(new THREE.PlaneGeometry(SLOT_W - 0.3, (SLOT_W - 0.3) * 360 / 1600), new THREE.MeshBasicMaterial({ map: subTex, transparent: true, toneMapped: false }));
      sub.position.set(0, -1.57, 0.02); g.add(sub);
      function setSub(t) { if (t === subTxt && subTex.userData.drawnWith === K.fontsReady()) return; subTxt = t; subTex.userData.drawnWith = K.fontsReady();
        subTex.userData.draw = (gg, w, h) => { gg.clearRect(0, 0, w, h); gg.fillStyle = "rgba(244,242,236,0.92)"; gg.font = "600 120px " + MONO; gg.textAlign = "center"; gg.textBaseline = "middle"; gg.letterSpacing = "4px";
          // Keep the original type size: wrap against actual glyph widths, never squash or clip evidence.
          const lines = []; let line = "";
          for (const word of t.split(/\s+/).filter(Boolean)) {
            if (gg.measureText(word).width > w - 120) throw new Error("F02 board subtitle word exceeds safe width");
            const next = line ? line + " " + word : word;
            if (line && gg.measureText(next).width > w - 120) { lines.push(line); line = word; }
            else line = next;
          }
          if (line) lines.push(line);
          if (lines.length > 2) throw new Error("F02 board subtitle exceeds two readable lines");
          lines.forEach((text, i) => gg.fillText(text, w / 2, h / 2 + (i - (lines.length - 1) / 2) * 144)); };
        const c = subTex.userData.canvas; subTex.userData.draw(c.getContext("2d"), c.width, c.height); subTex.needsUpdate = true; }
      // red cross (the fifth slot, at the end)
      const cross = new THREE.Group(); cross.position.set(0, 0.35, 0.2); g.add(cross);
      [-1, 1].forEach((s) => { const b = new THREE.Mesh(new THREE.PlaneGeometry(1.5, 0.12), basic(COL.red, { toneMapped: false })); b.rotation.z = 0.78 * s; cross.add(b); });
      return { g, cells, lamp, halo, setSub, cross, lm, panel };
    });
    // floor: a dark polished stage under the board
    const fl = new THREE.Mesh(new THREE.PlaneGeometry(80, 40), flat(0x151920)); fl.rotation.x = -Math.PI / 2; fl.position.y = -0.01; sc.add(fl);
    const pad = (s, n) => { s = String(s); const L = Math.max(0, n - s.length); const l = Math.floor(L / 2); return " ".repeat(l) + s + " ".repeat(L - l); };
    const GREEN = new THREE.Color(COL.green), OFF = new THREE.Color(0x2a3038), AMBER = new THREE.Color(COL.amber);
    out.board = { scene: sc, anim(T) {
      const s = st("board", T);
      // s.slots[i] = {on: 0..1 panel visible, from: "", to: "<2 MIN", p: 0..1 flip progress, lamp: 0..1 green, sub: "..."}, s.fifth {on, lamp, cross}
      (s.slots || []).forEach((q, i) => {
        const sl = slots[i]; if (!sl) return;
        const on = q.on === undefined ? 1 : q.on;
        sl.g.visible = on > 0.001; sl.g.position.y = (1 - EASE.out(on)) * 1.2; sl.g.scale.setScalar(0.92 + 0.08 * EASE.out(on));
        const n = sl.cells.length, from = pad(q.from || "", n), to = pad(q.to || "", n);
        sl.cells.forEach((c, k) => c.set(from[k], to[k], ((q.p === undefined ? 1 : q.p) * (1 + 0.12 * n) - k * 0.12) / 1));
        const lp = q.lamp || 0;
        sl.lamp.material.color.copy(OFF).lerp(q.amber ? AMBER : GREEN, lp); sl.halo.material.color.copy(q.amber ? AMBER : GREEN); sl.halo.material.opacity = 0.9 * lp * (0.9 + 0.1 * Math.sin(T * 5 + i));
        sl.setSub(q.sub || "");
        sl.cross.visible = (q.cross || 0) > 0; sl.cross.scale.set(EASE.out(q.cross || 0), 1, 1);
        sl.lm.material.opacity = on * (s.headers === undefined ? 1 : s.headers);
      });
    }, anchors: { s0: [slotsX(0), 7.9, 0.3], s1: [slotsX(1), 7.9, 0.3], s2: [slotsX(2), 7.9, 0.3], s3: [slotsX(3), 7.9, 0.3], s4: [slotsX(4), 7.9, 0.3] },
      slotX: slotsX };
    function slotsX(i) { return -BW / 2 + 0.3 + SLOT_W / 2 + i * (SLOT_W + 0.22); }
  }

  // ============================================================== SCALES: fewer mistakes than humans (a test of the machine)
  {
    const sc = new THREE.Scene(); const BG = 0xeceae6; sc.background = new THREE.Color(BG); sc.fog = new THREE.Fog(BG, 10, 30);
    sc.add(new THREE.HemisphereLight(0xffffff, 0xbdb6ab, 1.3));
    sun(sc, [-4, 7, 5], [0, 1, 0], 4, 2.4, 0xfff1e0);
    const fl = new THREE.Mesh(new THREE.PlaneGeometry(40, 40), flat(0xdcd8d1)); fl.rotation.x = -Math.PI / 2; fl.receiveShadow = true; sc.add(fl);
    const brass = flat(0xf2f0ec), brassD = flat(0xd9d5ce);
    // base, column, beam, pans on hanging rods
    const base = new THREE.Mesh(new THREE.CylinderGeometry(0.7, 0.85, 0.25, 8), brass); base.position.y = 0.125; base.castShadow = true; base.receiveShadow = true; sc.add(base);
    const col = new THREE.Mesh(new THREE.CylinderGeometry(0.09, 0.12, 2.5, 8), brass); col.position.y = 1.45; col.castShadow = true; sc.add(col);
    const top = new THREE.Mesh(new THREE.OctahedronGeometry(0.18, 0), brassD); top.position.y = 2.8; sc.add(top);
    const beam = new THREE.Group(); beam.position.y = 2.62; sc.add(beam);
    box(3.4, 0.1, 0.12, brass, 0, 0, 0, beam); const pointer = box(0.05, 0.6, 0.05, brassD, 0, -0.3, 0.07, beam);
    const pans = [-1, 1].map((s) => {
      const hang = new THREE.Group(); hang.position.set(1.6 * s, 0, 0); beam.add(hang);
      const pan = new THREE.Group(); hang.add(pan); pan.position.y = -1.3;
      const dish = new THREE.Mesh(new THREE.CylinderGeometry(0.72, 0.5, 0.12, 10), brass); dish.castShadow = true; dish.receiveShadow = true; pan.add(dish);
      [0, 1, 2].forEach((k) => { const a = k * Math.PI * 2 / 3; const r = new THREE.Mesh(new THREE.CylinderGeometry(0.012, 0.012, 1.3, 4), brassD); r.position.set(Math.cos(a) * 0.3, 0.65, Math.sin(a) * 0.3); r.lookAt(0, 1.3, 0); r.rotateX(Math.PI / 2); pan.add(r); });
      return { hang, pan };
    });
    // left pan: the machine (a chat bubble with a small spark icon); right pan: a human agent with a headset
    const botB = new THREE.Group(); pans[0].pan.add(botB); botB.position.y = 0.55;
    const bb = new THREE.Mesh(bubbleGeo(0.9, 0.62, 1, 0.14), flat(0xffffff, { emissive: 0x1a1a1a })); bb.castShadow = true; botB.add(bb);
    const sparkTex = canvasTex(256, 256, (g) => { g.fillStyle = "#ffb3c7"; g.beginPath(); for (let i = 0; i < 8; i++) { const a = i * Math.PI / 4, r = i % 2 ? 40 : 110; g.lineTo(128 + Math.cos(a) * r, 128 + Math.sin(a) * r); } g.closePath(); g.fill(); });
    const spark = new THREE.Mesh(new THREE.PlaneGeometry(0.34, 0.34), new THREE.MeshBasicMaterial({ map: sparkTex, transparent: true })); spark.position.z = 0.09; botB.add(spark);
    const agent = person({ body: 0xf0f1f3, legs: 0x9aa3ae, hair: 0x5d6168, headset: true }); agent.root.scale.setScalar(0.42); agent.root.position.y = 0.06; pans[1].pan.add(agent.root);
    pose(agent, { t: 0 });
    // mistake chips
    const chipM = flat(COL.red, { emissive: 0x3a0804 });
    const chips = []; for (let k = 0; k < 10; k++) { const c = new THREE.Mesh(new THREE.CylinderGeometry(0.1, 0.1, 0.04, 10), chipM); c.castShadow = true; sc.add(c); chips.push(c); }
    const cw = new THREE.Vector3();
    out.scales = { scene: sc, anim(T) {
      const s = st("scales", T);   // {chipsL: [times..], chipsR: [...], tilt: -1..1 (machine side up = positive), zoom}
      const tilt = s.tilt || 0;
      beam.rotation.z = tilt * 0.14 + Math.sin(T * 1.3) * 0.004;
      pans.forEach((p) => { p.hang.rotation.z = -beam.rotation.z; });
      pose(agent, { t: T, look: -0.05 });
      botB.rotation.y = Math.sin(T * 0.7) * 0.15;
      const drops = (s.drops || []);    // [{side: 0|1, t: start, k}]
      chips.forEach((c, i) => {
        const d = drops[i]; c.visible = !!d && T >= d.t; if (!c.visible) return;
        const pan = pans[d.side].pan; pan.getWorldPosition(cw);
        const u = clamp((T - d.t) / 0.45, 0, 1); const e = u * u;
        const off = [(hash(i, 3) - 0.5) * 0.7, (hash(i, 5) - 0.5) * 0.5];
        const restY = cw.y + 0.08 + (d.stack || 0) * 0.045;
        c.position.set(cw.x + off[0] * (d.side ? 0.3 : 1) + (d.side ? 0.35 : 0), lerp(cw.y + 2.2, restY, e) + (u >= 1 ? 0 : 0), cw.z + off[1] * 0.6);
        if (u >= 1) c.position.y = restY;
        c.rotation.set(hash(i, 7) * 0.3 * (1 - e), 0, hash(i, 9) * 0.3 * (1 - e));
      });
    }, anchors: { left: [-1.6, 3.2, 0], right: [1.6, 3.2, 0], under: [-1.6, 0.4, 0.8] } };
  }

  // ============================================================== SORT: the sorting line (repeat vs hard) and the machine arm
  {
    const sc = new THREE.Scene(); const BG = 0xe7eaee; sc.background = new THREE.Color(BG); sc.fog = new THREE.Fog(BG, 14, 40);
    sc.add(new THREE.HemisphereLight(0xffffff, 0xb1b8c2, 1.35));
    const sunL = sun(sc, [-6, 10, 6], [0, 0.8, 0], 7, 2.3, 0xfff2e2);
    const fl = new THREE.Mesh(new THREE.PlaneGeometry(60, 60), flat(0xd5dadf)); fl.rotation.x = -Math.PI / 2; fl.receiveShadow = true; sc.add(fl);
    // conveyor: frame, belt with moving slats, rollers, legs
    const conv = new THREE.Group(); sc.add(conv);
    box(8, 0.12, 1.2, flat(0xcfd4da), -1, 0.9, 0, conv); [-4.8, -1, 2.8].forEach((x) => [-0.5, 0.5].forEach((z) => box(0.1, 0.9, 0.1, grey, x, 0.45, z, conv)));
    const beltTex = canvasTex(64, 512, (g) => { g.fillStyle = "#3a4048"; g.fillRect(0, 0, 64, 512); g.fillStyle = "#4a515b"; for (let y = 0; y < 512; y += 32) g.fillRect(0, y, 64, 6); });
    beltTex.wrapS = beltTex.wrapT = THREE.RepeatWrapping; beltTex.repeat.set(1, 6);
    const belt = new THREE.Mesh(new THREE.PlaneGeometry(1.0, 8), new THREE.MeshLambertMaterial({ map: beltTex })); belt.rotation.set(-Math.PI / 2, 0, Math.PI / 2); belt.position.set(-1, 0.965, 0); sc.add(belt);
    [-0.6, 0.6].forEach((z) => box(8, 0.16, 0.06, white, -1, 1.0, z, conv));
    // the sorting gate
    const gate = new THREE.Group(); gate.position.set(2.2, 1.0, 0); sc.add(gate);
    box(0.08, 1.4, 1.4, white, 0, 0.7, 0, gate).visible = false;
    const arch = new THREE.Group(); gate.add(arch); [-0.72, 0.72].forEach((z) => box(0.12, 1.2, 0.12, white, 0, 0.6, z, arch)); box(0.12, 0.14, 1.56, white, 0, 1.2, 0, arch);
    const scanM = basic(0xffb3c7, { toneMapped: false, transparent: true, opacity: 0.85 }); const scan = new THREE.Mesh(new THREE.PlaneGeometry(1.3, 0.04), scanM); scan.rotation.y = Math.PI / 2; scan.position.set(0.07, 0.9, 0); gate.add(scan);
    // two chutes to two bins
    const bins = ["REPEAT", "HARD"].map((lab, i) => {
      const g = new THREE.Group(); g.position.set(4.0, 0, i === 0 ? -1.2 : 1.3); sc.add(g);
      const bm = i === 0 ? flat(0xf3f4f6) : flat(0xf3f4f6);
      box(1.3, 0.06, 1.1, bm, 0, 0.03, 0, g); [[0, 0.4, 0.55, 1.3, 0.8, 0.06], [0, 0.4, -0.55, 1.3, 0.8, 0.06], [0.65, 0.4, 0, 0.06, 0.8, 1.1], [-0.65, 0.4, 0, 0.06, 0.8, 1.1]].forEach(([x, y, z, w, h, d]) => box(w, h, d, bm, x, y, z, g));
      const lm = labelMesh(lab, { fs: 110, bg: i === 0 ? "#14171c" : "#e0412f", color: "#ffffff", r: 14, pad: 50, font: HEAVY, weight: 900 }, 1.0); lm.position.set(0, 0.45, i === 0 ? -0.585 : 0.585); if (i === 0) lm.rotation.y = Math.PI; g.add(lm);
      const lm2 = labelMesh(lab, { fs: 110, bg: i === 0 ? "#14171c" : "#e0412f", color: "#ffffff", r: 14, pad: 50, font: HEAVY, weight: 900 }, 1.0); lm2.position.set(-0.685, 0.45, 0); lm2.rotation.y = -Math.PI / 2; g.add(lm2);
      return { g, lab };
    });
    // the machine arm: base, turret, upper link, fore link, gripper
    const armM = flat(0xf7f8f9), armJ = flat(0x2f343c);
    const arm = new THREE.Group(); arm.position.set(5.9, 0, 0); sc.add(arm);
    const abase = new THREE.Mesh(new THREE.CylinderGeometry(0.45, 0.55, 0.3, 10), armM); abase.position.y = 0.15; abase.castShadow = true; arm.add(abase);
    const turret = new THREE.Group(); turret.position.y = 0.3; arm.add(turret);
    const tu = new THREE.Mesh(new THREE.CylinderGeometry(0.3, 0.35, 0.5, 10), armM); tu.position.y = 0.25; tu.castShadow = true; turret.add(tu);
    const sh = new THREE.Group(); sh.position.y = 0.55; turret.add(sh);
    const shj = new THREE.Mesh(new THREE.CylinderGeometry(0.2, 0.2, 0.5, 12), armJ); shj.rotation.z = Math.PI / 2; sh.add(shj);
    const l1 = box(0.26, 1.7, 0.3, armM, 0, 0.85, 0, sh);
    const el = new THREE.Group(); el.position.y = 1.7; sh.add(el);
    const elj = new THREE.Mesh(new THREE.CylinderGeometry(0.16, 0.16, 0.42, 12), armJ); elj.rotation.z = Math.PI / 2; el.add(elj);
    const l2 = box(0.22, 1.5, 0.24, armM, 0, 0.75, 0, el);
    const wr = new THREE.Group(); wr.position.y = 1.5; el.add(wr);
    const wj = new THREE.Mesh(new THREE.SphereGeometry(0.13, 10, 8), armJ); wr.add(wj);
    const claw = [-1, 1].map((s) => { const c = box(0.06, 0.34, 0.2, armJ, 0.12 * s, 0.2, 0, wr); return c; });
    const ringA = new THREE.Mesh(new THREE.TorusGeometry(0.31, 0.03, 4, 24), basic(0xffb3c7, { toneMapped: false })); ringA.rotation.x = Math.PI / 2; ringA.position.y = 0.52; turret.add(ringA);
    // bubbles on the belt: each has a class (0 repeat, 1 hard) and a birth time
    const bubM = flat(0xffffff, { emissive: 0x202020 }), hardM = flat(0xffe1e6, { emissive: 0x201014 });
    const NB = 26; const bubs = [];
    for (let k = 0; k < NB; k++) { const m = new THREE.Mesh(bubbleGeo(0.46, 0.3, 1, 0.08), k % 4 === 3 ? hardM : bubM); m.castShadow = true; sc.add(m); bubs.push({ m, hard: k % 4 === 3, k }); }
    // bin contents (piles that grow)
    const piles = bins.map((b, i) => { const gp = new THREE.Group(); b.g.add(gp); const ms = []; for (let k = 0; k < 14; k++) { const m = new THREE.Mesh(bubbleGeo(0.36, 0.24, 1, 0.06), i === 0 ? bubM : hardM); m.position.set((hash(k, 3) - 0.5) * 0.8, 0.12 + Math.floor(k / 5) * 0.12, (hash(k, 5) - 0.5) * 0.6); m.rotation.set(-Math.PI / 2 + (hash(k, 7) - 0.5) * 0.6, hash(k, 9) * 3, 0); gp.add(m); ms.push(m); } return { gp, ms }; });
    const binStart = bins.map((b) => b.g.position.clone());
    const tmp = new THREE.Vector3();
    out.sort = { scene: sc, anim(T, shot) {
      const s = st("sort", T);   // {flow 0|1, rate, fillR 0..1, fillH 0..1, lift 0..1 (arm lifts REPEAT bin away), reach 0..1 (arm into HARD bin), solved}
      const flow = s.flow === undefined ? 1 : s.flow, rate = s.rate || 1;
      beltTex.offset.y = -T * 0.45 * flow * rate;
      scanM.opacity = 0.5 + 0.4 * Math.sin(T * 8);
      // bubbles ride the belt from x=-5 to the gate at x=2.2, then drop into their bin
      bubs.forEach((b) => {
        const period = 5.2 / rate; const ph = (((T * flow) / period + b.k / NB) % 1 + 1) % 1;
        b.m.visible = flow > 0 || s.still;
        const u = ph;
        if (u < 0.72) { const x = lerp(-5, 2.3, u / 0.72); b.m.position.set(x, 1.19, (hash(b.k, 3) - 0.5) * 0.5); b.m.rotation.set(-Math.PI / 2, 0, (hash(b.k, 11) - 0.5) * 0.6); }
        else { const v = (u - 0.72) / 0.28; const bin = bins[b.hard ? 1 : 0].g.position; const x = lerp(2.3, bin.x, EASE.out(v)), z = lerp(0, bin.z, EASE.out(v)), y = lerp(1.19, 0.5, v * v) + Math.sin(v * Math.PI) * 0.35;
          b.m.position.set(x, y, z); b.m.rotation.set(-Math.PI / 2 + v * 2.5, 0, v * 1.4); b.m.visible = b.m.visible && v < 0.97; }
      });
      piles.forEach((p, i) => { const f = i === 0 ? (s.fillR || 0) : (s.fillH || 0); p.ms.forEach((m, k) => { m.visible = k < Math.round(f * p.ms.length); }); });
      // arm: rest pose, then (lift) swing to the REPEAT bin, grip, lift it up and away; or (reach) into the HARD bin and set a case down
      const lift = s.lift || 0, reach = s.reach || 0;
      let yaw = 0.0, a1 = -0.35, a2 = 1.0, grip = 0.6;
      if (lift > 0) { const u1 = EASE.io(clamp(lift / 0.35, 0, 1)), u2 = EASE.io(clamp((lift - 0.35) / 0.2, 0, 1)), u3 = EASE.io(clamp((lift - 0.55) / 0.45, 0, 1));
        yaw = lerp(0, 0.62, u1) + lerp(0, -0.9, u3); a1 = lerp(-0.35, -0.95, u1) + lerp(0, 0.5, u3); a2 = lerp(1.0, 1.35, u1) - lerp(0, 0.6, u3); grip = lerp(0.6, 0.15, u2); }
      if (reach > 0) { const u1 = EASE.io(clamp(reach / 0.4, 0, 1)), u2 = EASE.io(clamp((reach - 0.4) / 0.2, 0, 1)), u3 = EASE.io(clamp((reach - 0.6) / 0.4, 0, 1));
        yaw = lerp(0, -0.72, u1) + lerp(0, 1.25, u3); a1 = lerp(-0.35, -1.0, u1) + lerp(0, 0.35, u3); a2 = lerp(1.0, 1.45, u1) - lerp(0, 0.25, u3); grip = lerp(0.6, 0.15, u2) + lerp(0, 0.45, clamp((reach - 0.92) / 0.08, 0, 1)); }
      turret.rotation.y = Math.PI / 2 + yaw; sh.rotation.x = a1; el.rotation.x = a2; wr.rotation.x = 0.6;
      claw[0].position.x = -0.06 - grip * 0.12; claw[1].position.x = 0.06 + grip * 0.12;
      // the REPEAT bin travels with the gripper once gripped
      const gb = bins[0].g;
      if (lift > 0.45) { wr.getWorldPosition(tmp); gb.position.set(tmp.x, Math.max(0, tmp.y - 1.0), tmp.z); gb.rotation.y = turret.rotation.y - Math.PI / 2; }
      else { gb.position.copy(binStart[0]); gb.rotation.y = 0; }
      gb.visible = !(s.binGone);
      ringA.material.color.set(lift > 0 || reach > 0 ? 0xffb3c7 : 0xd4d8de);
    }, anchors: { repeat: [4.0, 1.5, -1.2], hard: [4.0, 1.5, 1.3], gate: [2.2, 2.6, 0], arm: [5.9, 3.6, 0] } };
  }

  // ============================================================== STUDIO: a TV set (left) and a podcast table (right), nobody on camera
  {
    const sc = new THREE.Scene(); const BG = 0x11151b; sc.background = new THREE.Color(BG); sc.fog = new THREE.Fog(BG, 14, 40);
    sc.add(new THREE.HemisphereLight(0xcfd8e6, 0x14181e, 0.9));
    const key = new THREE.SpotLight(0xfff0dc, 500, 22, 0.55, 0.6, 1.5); key.position.set(-8, 7, 6); key.target.position.set(-8, 0.8, -1); key.castShadow = true; key.shadow.mapSize.set(1024, 1024); sc.add(key, key.target);
    const key2 = new THREE.SpotLight(0xffe8cc, 420, 20, 0.5, 0.6, 1.5); key2.position.set(8, 6, 4); key2.target.position.set(8, 0.8, -0.5); key2.castShadow = true; key2.shadow.mapSize.set(1024, 1024); sc.add(key2, key2.target);
    const fl = new THREE.Mesh(new THREE.PlaneGeometry(60, 40), flat(0x2a2f37)); fl.rotation.x = -Math.PI / 2; fl.receiveShadow = true; sc.add(fl);
    // TV set (x around -8): riser, two chairs, low table, a backdrop screen of plain news graphics (no network marks)
    const tv = new THREE.Group(); tv.position.set(-8, 0, 0); sc.add(tv);
    const riser = new THREE.Mesh(new THREE.CylinderGeometry(3.4, 3.5, 0.3, 24), flat(0xe8ebee)); riser.position.y = 0.15; riser.receiveShadow = true; tv.add(riser);
    const chairM = flat(0xf2f3f4);
    const chairs = [-1, 1].map((s) => { const c = new THREE.Group(); c.position.set(1.1 * s, 0.3, 0.2); c.rotation.y = -s * 0.55; tv.add(c);
      box(0.7, 0.14, 0.66, chairM, 0, 0.42, 0, c); box(0.7, 0.62, 0.12, chairM, 0, 0.75, -0.3, c); box(0.12, 0.3, 0.6, chairM, 0.34, 0.6, 0, c); box(0.12, 0.3, 0.6, chairM, -0.34, 0.6, 0, c);
      const st2 = new THREE.Mesh(new THREE.CylinderGeometry(0.05, 0.22, 0.36, 8), dark); st2.position.y = 0.18; c.add(st2); return c; });
    const tab = new THREE.Mesh(new THREE.CylinderGeometry(0.42, 0.42, 0.05, 16), chairM); tab.position.set(0, 0.8, 0.5); tv.add(tab); const tl = new THREE.Mesh(new THREE.CylinderGeometry(0.04, 0.2, 0.5, 8), dark); tl.position.set(0, 0.55, 0.5); tv.add(tl);
    const mug = new THREE.Mesh(new THREE.CylinderGeometry(0.05, 0.045, 0.1, 10), flat(0xffffff)); mug.position.set(0.12, 0.88, 0.5); tv.add(mug);
    const bdTex = canvasTex(2400, 1000, (g, w, h) => { const gr = g.createLinearGradient(0, 0, w, h); gr.addColorStop(0, "#1b2b4a"); gr.addColorStop(1, "#0e1626"); g.fillStyle = gr; g.fillRect(0, 0, w, h);
      g.strokeStyle = "rgba(160,190,255,0.16)"; g.lineWidth = 3; for (let i = 0; i < 26; i++) { g.beginPath(); g.moveTo(0, i * 40); g.lineTo(w, i * 40 + 300); g.stroke(); }
      g.fillStyle = "rgba(255,255,255,0.08)"; for (let i = 0; i < 9; i++) { g.beginPath(); g.arc(1700 + Math.sin(i) * 300, 400 + Math.cos(i * 1.7) * 200, 120 + i * 20, 0, Math.PI * 2); g.fill(); } });
    const bd = new THREE.Mesh(new THREE.PlaneGeometry(7.2, 3.0), new THREE.MeshBasicMaterial({ map: bdTex, toneMapped: false })); bd.position.set(0, 2.1, -2.6); tv.add(bd);
    box(7.6, 3.4, 0.2, flat(0x1b1f26), 0, 2.1, -2.72, tv);
    // studio cameras on pedestals (backs to us in the wide)
    [[-2.8, 4.6, 0.35], [2.6, 4.8, -0.3], [0, 5.6, 0]].forEach(([x, z, r]) => { const c = new THREE.Group(); c.position.set(x, 0, z); c.rotation.y = Math.PI + r; tv.add(c);
      const ped = new THREE.Mesh(new THREE.CylinderGeometry(0.08, 0.35, 1.3, 8), dark); ped.position.y = 0.65; c.add(ped);
      box(0.42, 0.42, 0.9, flat(0x1b1f26), 0, 1.5, 0, c); const lens = new THREE.Mesh(new THREE.CylinderGeometry(0.13, 0.15, 0.36, 12), dark); lens.rotation.x = Math.PI / 2; lens.position.set(0, 1.5, -0.6); c.add(lens);
      const tally = new THREE.Mesh(new THREE.BoxGeometry(0.08, 0.05, 0.02), basic(COL.red, { toneMapped: false })); tally.position.set(0, 1.76, -0.3); c.add(tally); });
    // light truss overhead
    box(8, 0.12, 0.12, grey, 0, 4.6, 2, tv); for (let k = 0; k < 5; k++) { const l = new THREE.Mesh(new THREE.CylinderGeometry(0.14, 0.2, 0.34, 10), dark); l.position.set(-3 + k * 1.5, 4.35, 2); l.rotation.x = 0.8; tv.add(l); }
    // podcast table (x around +8): a round table, two mic arms, headphones, acoustic panels, no faces
    const pod = new THREE.Group(); pod.position.set(8, 0, 0); sc.add(pod);
    const ptab = new THREE.Mesh(new THREE.CylinderGeometry(1.1, 1.1, 0.06, 20), flat(0xe8e2d6)); ptab.position.y = 0.76; ptab.castShadow = true; ptab.receiveShadow = true; pod.add(ptab);
    const pl = new THREE.Mesh(new THREE.CylinderGeometry(0.08, 0.35, 0.74, 8), dark); pl.position.y = 0.37; pod.add(pl);
    const mics = [-1, 1].map((s) => { const g = new THREE.Group(); g.position.set(0.55 * s, 0.79, -0.1 * s); g.rotation.y = s > 0 ? -0.6 : Math.PI - 0.6; pod.add(g);
      box(0.12, 0.03, 0.12, dark, 0, 0, 0, g); const a1 = box(0.03, 0.5, 0.03, dark, 0, 0.25, 0, g); a1.rotation.x = 0.3; const a2 = box(0.03, 0.45, 0.03, dark, 0, 0.5, 0.25, g); a2.rotation.x = 1.2;
      const mic = new THREE.Mesh(new THREE.CylinderGeometry(0.06, 0.05, 0.22, 12), flat(0x1b1f26)); mic.rotation.x = Math.PI / 2 + 0.3; mic.position.set(0, 0.62, 0.48); g.add(mic);
      const grill = new THREE.Mesh(new THREE.SphereGeometry(0.062, 10, 8), flat(0x3b424c)); grill.position.set(0, 0.64, 0.58); g.add(grill);
      const ring = new THREE.Mesh(new THREE.TorusGeometry(0.08, 0.008, 4, 16), basic(0xffb3c7, { toneMapped: false })); ring.position.set(0, 0.62, 0.47); ring.rotation.x = 0.3; g.add(ring); return { g, ring }; });
    const hp = new THREE.Mesh(new THREE.TorusGeometry(0.1, 0.012, 5, 14, Math.PI), dark); hp.position.set(0.1, 0.81, 0.4); hp.rotation.x = -Math.PI / 2; pod.add(hp);
    for (let i = 0; i < 6; i++) for (let j = 0; j < 3; j++) { const p = new THREE.Mesh(new THREE.BoxGeometry(0.9, 0.9, 0.12), flat(j % 2 === i % 2 ? 0x2d333c : 0x353c46)); p.position.set(-2.4 + i * 0.95, 0.9 + j * 0.95, -2.2); pod.add(p);
      for (let q = 0; q < 3; q++) { const w = new THREE.Mesh(new THREE.BoxGeometry(0.8, 0.08, 0.1), flat(0x3d4550)); w.position.set(-2.4 + i * 0.95, 0.9 + j * 0.95 - 0.3 + q * 0.3, -2.12); pod.add(w); } }
    // on-air light
    const onair = labelMesh("ON AIR", { fs: 90, bg: "#e0412f", color: "#ffffff", r: 12, font: MONO, weight: 500, track: 0.2 }, 1.1); onair.position.set(0, 3.7, -2.1); pod.add(onair);
    out.studio = { scene: sc, anim(T) {
      const s = st("studio", T);   // {pulse}
      mics.forEach((m, i) => { m.ring.material.color.set((s.live === i) ? 0xffb3c7 : 0x39404a); });
      onair.material.opacity = 0.75 + 0.25 * Math.sin(T * 4);
    }, anchors: { tv: [-8, 3.9, -2.6], pod: [8, 1.8, 0] } };
  }
  return out;
}
