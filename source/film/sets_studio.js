// STUDIO: the film's white seamless set. The oversized newspaper page lies on the floor; the satisfaction dials build out of
// it (the signature object, reused at the climax as four dials in a row); a magnifier passes over them; the regulator's four
// rule cards are dealt onto the floor; a white low-poly hand holds the phone for the "type human" hook.
import * as THREE from "three";
import { K, flat, basic, hash, clamp, EASE, prog, lerp, canvasTex, rr, FONT, FONTGEN, makeDial, merge, M4 } from "./lib.js";
import { drawPhoneChat } from "./screens.js";

export function pageTexture(opts) {
  const o = opts || {};
  return canvasTex(1536, 2112, (g, w, h) => {
    g.fillStyle = "#f4f1ea"; g.fillRect(0, 0, w, h);
    // faint paper fibre
    for (let i = 0; i < 1800; i++) { g.fillStyle = "rgba(120,110,95," + (0.025 + hash(i, 3) * 0.03) + ")"; g.fillRect(hash(i, 1) * w, hash(i, 2) * h, 1 + hash(i, 4) * 3, 1); }
    g.fillStyle = "#1b1d21"; g.fillRect(80, 90, w - 160, 6); g.fillRect(80, 250, w - 160, 3);
    // masthead area (plain rule, no title), date strip
    g.fillStyle = "#2a2d33"; g.font = "600 44px " + FONT.mono; g.fillText("COMMENT", 80, 200); g.textAlign = "right"; g.fillText("MAY 2023", w - 80, 200); g.textAlign = "left";
    // 29 Sep: no headline bars (the column's headline is not in the fact ledger, and black bars read as redaction). The page is
    // body columns from the rule down; the two figures sit apart, each with its label, where the camera finds them.
    const cols = 4, cw = (w - 160 - 3 * 40) / cols;
    for (let c = 0; c < cols; c++) for (let r = 0; r < 58; r++) {
      const x = 80 + c * (cw + 40), y = 310 + r * 30;
      if (c === 1 && r >= 43 && r <= 48) continue;   // gap for the figures (below the dials' close-ups)
      g.fillStyle = "#b9bdc4"; g.fillRect(x, y, cw * (r % 9 === 8 ? 0.5 : 0.97 - hash(r + c * 50, 7) * 0.08), 12);
    }
    const fx = 80 + cw + 40;
    g.fillStyle = "#e0157f"; g.font = "700 46px " + FONT.heavy; g.fillText("80%", fx, 1652);
    g.font = "600 30px " + FONT.ui; g.fillText("AI emails", fx + 112, 1650);
    g.fillStyle = "#6b7078"; g.font = "700 46px " + FONT.heavy; g.fillText("65%", fx, 1722);
    g.font = "600 30px " + FONT.ui; g.fillText("staff", fx + 112, 1720);
  });
}

export function buildStudio(ctx) {
  const scene = new THREE.Scene();
  const BG = 0xeceef1;
  scene.background = new THREE.Color(BG);
  scene.fog = new THREE.Fog(BG, 18, 46);
  scene.add(new THREE.HemisphereLight(0xffffff, 0xbfc5cd, 1.55));
  const sun = new THREE.DirectionalLight(0xffffff, 1.55);
  sun.position.set(-6, 12, 7); sun.target.position.set(0, 0, 0);
  sun.castShadow = true; sun.shadow.mapSize.set(2048, 2048); sun.shadow.bias = -0.0008; sun.shadow.normalBias = 0.02;
  { const c = sun.shadow.camera; c.left = -9; c.right = 9; c.top = 9; c.bottom = -9; c.near = 1; c.far = 40; }
  scene.add(sun, sun.target);
  const floor = new THREE.Mesh(new THREE.PlaneGeometry(200, 200), flat(0xf1f2f4)); floor.rotation.x = -Math.PI / 2; floor.receiveShadow = true; scene.add(floor);

  // the oversized page
  const pageTex = pageTexture();
  const page = new THREE.Group(); scene.add(page);
  const PW = 4.6, PH = 6.33;
  const sheet = new THREE.Mesh(new THREE.BoxGeometry(PW, 0.02, PH), [flat(0xefece5), flat(0xefece5), new THREE.MeshLambertMaterial({ map: pageTex }), flat(0xefece5), flat(0xefece5), flat(0xefece5)]);
  sheet.position.y = 0.01; sheet.receiveShadow = true; sheet.castShadow = true; page.add(sheet);

  // four dials: 2023 AI / staff, 2026 AI / staff
  const D = [
    makeDial({ r: 0.9, color: K.magenta, label: "AI EMAILS" }), makeDial({ r: 0.9, color: 0x6f7682, label: "STAFF EMAILS" }),
    makeDial({ r: 0.9, color: K.magenta, label: "ARLO (AI)" }), makeDial({ r: 0.9, color: 0x6f7682, label: "HUMAN ADVISERS" })];
  D.forEach((d) => { d.g.traverse((m) => { if (m.isMesh) m.castShadow = true; }); scene.add(d.g); });
  // year plinths in front of the dial pairs (built as 3D type plates, not DOM, so they sit in the shot)
  function yearPlate(text) {
    const tex = canvasTex(512, 160, (g, w, h) => { g.fillStyle = "#15181d"; rr(g, 0, 0, w, h, 30); g.fill(); g.fillStyle = "#fff"; g.font = "700 104px " + FONT.heavy; g.textAlign = "center"; g.fillText(text, w / 2, 118); });
    const m = new THREE.Mesh(new THREE.PlaneGeometry(0.9, 0.28), new THREE.MeshBasicMaterial({ map: tex, transparent: true })); m.rotation.x = -Math.PI / 2; m.position.y = 0.035; scene.add(m); return m;
  }
  const Y23 = yearPlate("2023"), Y26 = yearPlate("2026");

  // magnifier
  const mag = new THREE.Group(); scene.add(mag);
  { const ring = new THREE.Mesh(new THREE.TorusGeometry(0.55, 0.05, 8, 40), flat(0x2b3037)); mag.add(ring);
    const glass = new THREE.Mesh(new THREE.CircleGeometry(0.53, 40), new THREE.MeshLambertMaterial({ color: 0xdfeefa, transparent: true, opacity: 0.28 })); mag.add(glass);
    const handle = new THREE.Mesh(new THREE.CylinderGeometry(0.055, 0.065, 0.9, 10), flat(0x2b3037)); handle.position.set(0.83, -0.42, 0); handle.rotation.z = Math.PI / 4; mag.add(handle);
    mag.rotation.x = -Math.PI / 2 + 0.25; mag.traverse((m) => { if (m.isMesh) m.castShadow = true; }); }

  // the regulator's four rule cards (dealt face up)
  const ICON = [
    (g) => { g.lineWidth = 22; g.strokeStyle = "#15181d"; g.beginPath(); g.ellipse(0, 0, 150, 90, 0, 0, Math.PI * 2); g.stroke(); g.beginPath(); g.arc(0, 0, 48, 0, Math.PI * 2); g.fillStyle = "#15181d"; g.fill(); },
    (g) => { g.fillStyle = "#15181d"; g.beginPath(); g.arc(0, -58, 52, 0, Math.PI * 2); g.fill(); g.beginPath(); g.ellipse(0, 70, 105, 70, 0, Math.PI, 0); g.fill(); g.fillRect(-105, 68, 210, 20); },
    (g) => { g.lineWidth = 20; g.strokeStyle = "#15181d"; g.strokeRect(-140, -90, 280, 180); g.beginPath(); g.moveTo(-140, -90); g.lineTo(0, 20); g.lineTo(140, -90); g.stroke(); },
    (g) => { g.lineWidth = 18; g.strokeStyle = "#15181d"; g.beginPath(); g.moveTo(0, -120); g.lineTo(0, 110); g.moveTo(-150, -70); g.lineTo(150, -70); g.moveTo(-90, 120); g.lineTo(90, 120); g.stroke();
      g.beginPath(); g.arc(-150, 0, 60, 0, Math.PI); g.stroke(); g.beginPath(); g.arc(150, 0, 60, 0, Math.PI); g.stroke(); g.beginPath(); g.moveTo(-150, -70); g.lineTo(-205, 0); g.moveTo(-150, -70); g.lineTo(-95, 0); g.moveTo(150, -70); g.lineTo(95, 0); g.moveTo(150, -70); g.lineTo(205, 0); g.stroke(); }];
  const RULES = [["BE", "OPEN"], ["A ROUTE", "TO A HUMAN"], ["HELP PEOPLE", "OFFLINE"], ["CHECK FOR", "FAIRNESS"]];
  const cards = RULES.map((lines, i) => {
    const tex = canvasTex(900, 1260, (g, w, h) => {
      g.fillStyle = "#ffffff"; g.fillRect(0, 0, w, h);
      g.strokeStyle = "#15181d"; g.lineWidth = 10; rr(g, 30, 30, w - 60, h - 60, 40); g.stroke();
      g.fillStyle = "#8b919a"; g.font = "600 56px " + FONT.mono; g.fillText("0" + (i + 1), 90, 150);
      g.save(); g.translate(w / 2, 470); ICON[i](g); g.restore();
      g.fillStyle = "#15181d"; g.font = "800 100px " + FONT.heavy; g.textAlign = "center";
      lines.forEach((l, k) => g.fillText(l, w / 2, 860 + k * 118));
    });
    const lit = canvasTex(900, 1260, (g, w, h) => { g.drawImage(tex.userData.canvas, 0, 0); g.strokeStyle = "#e0157f"; g.lineWidth = 26; rr(g, 30, 30, w - 60, h - 60, 40); g.stroke(); });
    const m = new THREE.Mesh(new THREE.BoxGeometry(1.2, 0.02, 1.68), [flat(0xf6f6f6), flat(0xf6f6f6), new THREE.MeshLambertMaterial({ map: tex }), flat(0xf6f6f6), flat(0xf6f6f6), flat(0xf6f6f6)]);
    m.castShadow = true; m.receiveShadow = true; scene.add(m);
    return { m, tex, lit };
  });

  // hand + phone (the hook): a low-poly hand from the right, phone upright facing camera
  const phoneTex = canvasTex(1040, 2000, () => {}, { dynamic: true });
  const hand = new THREE.Group(); scene.add(hand);
  const skin = flat(0xf4f4f2), dark = flat(0x16181c);
  const phone = new THREE.Mesh(new THREE.BoxGeometry(0.56, 1.08, 0.05), dark); phone.castShadow = true; hand.add(phone);
  const screen = new THREE.Mesh(new THREE.PlaneGeometry(0.52, 1.0), new THREE.MeshBasicMaterial({ map: phoneTex, toneMapped: false })); screen.position.z = 0.0255; hand.add(screen);
  { const palm = new THREE.Mesh(new THREE.BoxGeometry(0.44, 0.52, 0.12), skin); palm.position.set(0.02, -0.3, -0.1); palm.castShadow = true; hand.add(palm);
    for (let k = 0; k < 4; k++) { const f = new THREE.Mesh(new THREE.CapsuleGeometry(0.042, 0.1, 2, 6), skin); f.position.set(-0.3, -0.12 - k * 0.105, -0.01); f.rotation.set(Math.PI / 2, 0, 0); f.castShadow = true; hand.add(f);
      const tip = new THREE.Mesh(new THREE.SphereGeometry(0.042, 8, 6), skin); tip.position.set(-0.27, -0.12 - k * 0.105, 0.05); hand.add(tip); }
    const wrist = new THREE.Mesh(new THREE.CylinderGeometry(0.14, 0.16, 0.8, 8), skin); wrist.position.set(0.12, -0.85, -0.14); wrist.rotation.z = 0.25; hand.add(wrist); }
  const thumb = new THREE.Group(); thumb.position.set(0.27, -0.36, 0.03); hand.add(thumb);
  { const t = new THREE.Mesh(new THREE.CapsuleGeometry(0.048, 0.2, 2, 6), skin); t.position.set(-0.06, 0.1, 0.02); t.rotation.z = 0.7; t.castShadow = true; thumb.add(t); }
  let phoneKey = "";

  const anchors = {};
  const S = ctx.S;
  function anim(T, shot, ov) {
    const st = Object.assign({}, S.studio(T), ov);
    // page
    page.visible = st.page.vis; page.position.set(st.page.x || 0, 0, st.page.z || 0);
    page.rotation.set((st.page.stand || 0) * Math.PI / 2 * 0.92, st.page.ry || 0, 0);
    page.position.y = (st.page.stand || 0) * PH / 2 * 0.95; page.position.z = (st.page.z || 0) - (st.page.stand || 0) * 3.4;
    // dials
    st.dials.forEach((d, i) => {
      const dd = D[i];
      dd.g.visible = d.vis && d.build > 0.001;
      if (!dd.g.visible) return;
      dd.g.position.set(d.x, 0.02, d.z); dd.g.scale.setScalar(d.s || 1);
      dd.build(d.build); dd.set(d.v);
      anchors["dial" + i] = [d.x, 0.35 * (d.s || 1), d.z + 1.12 * (d.s || 1)];
      anchors["dialTop" + i] = [d.x, 0.5 * (d.s || 1), d.z - 1.05 * (d.s || 1)];
    });
    Y23.visible = st.years > 0; Y26.visible = st.years > 0 && st.dials[2].vis && st.dials[2].build > 0.9;
    Y23.position.set((st.dials[0].x + st.dials[1].x) / 2, 0.035, st.dials[0].z + 1.35 * (st.dials[0].s || 1)); Y23.scale.setScalar(st.dials[0].s || 1);
    Y26.position.set((st.dials[2].x + st.dials[3].x) / 2, 0.035, st.dials[2].z + 1.35 * (st.dials[2].s || 1)); Y26.scale.setScalar(st.dials[2].s || 1);
    anchors.pair23 = [(st.dials[0].x + st.dials[1].x) / 2, 0.1, st.dials[0].z + 1.9 * (st.dials[0].s || 1)];
    anchors.pair26 = [(st.dials[2].x + st.dials[3].x) / 2, 0.1, st.dials[2].z + 1.9 * (st.dials[2].s || 1)];
    anchors.all = [0, 0.1, 2.3];
    // magnifier
    mag.visible = !!st.mag.vis; mag.position.set(st.mag.x, 1.25, st.mag.z);
    // cards
    st.cards.forEach((c, i) => {
      const cm = cards[i]; cm.m.visible = c.vis;
      if (!c.vis) return;
      const p = EASE.out(clamp(c.p, 0, 1));
      // dealt from off the top of frame: arc down, spin to rest
      cm.m.position.set(lerp(c.x + 2.5, c.x, p), 0.012 + Math.sin(p * Math.PI) * 0.9 + (c.y || 0), lerp(c.z - 4.5, c.z, p));
      cm.m.rotation.set(0, (c.ry || 0) + (1 - p) * 1.4, 0);
      cm.m.material[2].map = c.lit > 0.5 ? cm.lit : cm.tex;
      anchors["card" + i] = [cm.m.position.x, 0.05, cm.m.position.z + 0.9];
    });
    // hand + phone
    hand.visible = !!st.phone.vis;
    if (hand.visible) {
      hand.position.set(st.phone.x || 0, st.phone.y || 1.25, st.phone.z || 3.2); hand.rotation.set(-0.12, -0.18, 0.04);
      const key = JSON.stringify(st.phone.chat) + FONTGEN.n;
      if (key !== phoneKey) {
        phoneKey = key; const g = phoneTex.userData.g;
        g.setTransform(1, 0, 0, 1, 0, 0); g.fillStyle = "#101216"; g.fillRect(0, 0, 1040, 2000);
        g.setTransform(2, 0, 0, 2, -700 * 2, -40 * 2); drawPhoneChat(g, st.phone.chat); phoneTex.needsUpdate = true;
      }
      thumb.rotation.x = -0.25 * (st.phone.tap || 0); thumb.position.z = 0.05 - 0.03 * (st.phone.tap || 0);
    }
    scene.fog.near = st.fogNear || 18; scene.fog.far = st.fogFar || 46;
  }
  return { scene, anim, anchors, D };
}
