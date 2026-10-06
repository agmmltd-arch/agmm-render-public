#!/usr/bin/env node
// dom_lint_runner.mjs  (root cards 6 Oct 2026, "dom-lint")  -- the in-browser half of kit/tools/dom_lint.py
//
// Loads each part of a BUILT short package in headless Chrome at 1080x1920, seeks the part's own GSAP timeline(s)
// (window.__timelines, exactly what hyperframes' gsap adapter and specs/S01/tools/fsnap.py do: pause + seek(t, false)),
// and at every requested time records FACTS about every visible text element, text-bearing image and painted element.
// It makes no judgement: the rules live in dom_lint.py, so they can be re-tuned on the saved raw JSON without a browser.
//
//   node dom_lint_runner.mjs --root <dir holding one folder per look> --plan <PLAN.json> --out <raw.json>
//        [--chrome <path to chrome / chrome-headless-shell>] [--profile <profile.json>] [--puppeteer <module dir>]
//        [--shots <dir>] [--shot-times 1.0,2.0]
// PLAN.json = [{"look": "s52-a", "part": "S52-A", "times": [part-local seconds ...]}]   (the snap plan format)
// profile.json (optional) = {"visible": {x0,y0,x1,y1}, "overlays": [{x0,y0,x1,y1}]}  only used to decide which texts
//   deserve the (slower) occlusion test; never to judge.
import fs from 'node:fs';
import path from 'node:path';
import { pathToFileURL } from 'node:url';

const argv = process.argv.slice(2);
const arg = (k, d) => { const i = argv.indexOf(k); return i >= 0 ? argv[i + 1] : d; };
const ROOT = arg('--root'), PLAN = arg('--plan'), OUT = arg('--out');
if (!ROOT || !PLAN || !OUT) { console.error('usage: dom_lint_runner.mjs --root DIR --plan PLAN.json --out raw.json'); process.exit(2); }
const PROFILE = arg('--profile') ? JSON.parse(fs.readFileSync(arg('--profile'), 'utf8')) : null;
const SHOTS = arg('--shots');
const SHOT_TIMES = (arg('--shot-times', '') || '').split(',').filter(Boolean).map(Number);

let puppeteer;
if (arg('--puppeteer') || process.env.PUPPETEER_CORE) {
  const dir = arg('--puppeteer') || process.env.PUPPETEER_CORE;
  puppeteer = (await import(pathToFileURL(path.join(dir, 'lib/puppeteer/puppeteer-core.js')).href)).default;
} else {
  puppeteer = (await import('puppeteer-core')).default;
}
const CHROME = arg('--chrome') || process.env.CHROME_PATH;
if (!CHROME) { console.error('no --chrome / CHROME_PATH'); process.exit(2); }

// ---------------------------------------------------------------------------------------------------------------
// Runs INSIDE the page. Returns a plain JSON object for one sample. Everything is in viewport px (= master px at 1080x1920).
const EXTRACT = (cfg) => {
  const W = 1080, H = 1920;
  const root = document.getElementById('root') || document.body;
  const ids = (window.__dlids = window.__dlids || new WeakMap());
  window.__dlnid = window.__dlnid || 0;
  const idOf = (el) => { let v = ids.get(el); if (v === undefined) { v = window.__dlnid++; ids.set(el, v); } return v; };
  const SKIP = new Set(['SCRIPT', 'STYLE', 'NOSCRIPT', 'TITLE', 'META', 'LINK', 'HEAD', 'DEFS', 'CLIPPATH', 'MASK', 'LINEARGRADIENT', 'RADIALGRADIENT', 'PATTERN', 'FILTER', 'SYMBOL']);
  const inter = (a, b) => !a ? b : (!b ? a : [Math.max(a[0], b[0]), Math.max(a[1], b[1]), Math.min(a[2], b[2]), Math.min(a[3], b[3])]);
  const area = (r) => Math.max(0, r[2] - r[0]) * Math.max(0, r[3] - r[1]);
  const rgba = (s) => { const m = /rgba?\(([^)]*)\)/.exec(s || ''); if (!m) return null; const p = m[1].split(/[ ,\/]+/).filter(Boolean).map(parseFloat); return { r: p[0], g: p[1], b: p[2], a: p.length > 3 ? p[3] : 1 }; };
  const matScale = (tr) => {   // [scale, rotation(rad)] of a computed transform
    if (!tr || tr === 'none') return [1, 0];
    let m = /^matrix\(([^)]*)\)$/.exec(tr);
    if (m) { const p = m[1].split(',').map(parseFloat); return [Math.sqrt(Math.abs(p[0] * p[3] - p[1] * p[2])), Math.atan2(p[1], p[0])]; }
    m = /^matrix3d\(([^)]*)\)$/.exec(tr);
    if (m) { const p = m[1].split(',').map(parseFloat); const sx = Math.hypot(p[0], p[1], p[2]), sy = Math.hypot(p[4], p[5], p[6]); return [Math.sqrt(sx * sy), Math.atan2(p[1], p[0])]; }
    return [1, 0];
  };
  const indScale = (s) => { if (!s || s === 'none') return 1; const p = s.split(/\s+/).map(parseFloat); return Math.sqrt(Math.abs(p[0] * (p.length > 1 ? p[1] : p[0]))) || 1; };
  const short = (el) => { let s = el.tagName.toLowerCase(); if (el.id) s += '#' + el.id; const c = (typeof el.className === 'string' ? el.className : (el.className && el.className.baseVal) || '').trim().split(/\s+/).filter(Boolean).slice(0, 2); if (c.length) s += '.' + c.join('.'); return s; };
  const canvas = (window.__dlcv = window.__dlcv || document.createElement('canvas').getContext('2d'));
  const inkCache = (window.__dlink = window.__dlink || new Map());
  const ink = (font, text) => {
    const key = font + '|' + text; let v = inkCache.get(key);
    if (!v) { canvas.font = font; const m = canvas.measureText(text); v = [m.actualBoundingBoxAscent, m.actualBoundingBoxDescent, m.fontBoundingBoxAscent, m.fontBoundingBoxDescent]; inkCache.set(key, v); }
    return v;
  };
  const texts = [], imgs = [], paints = [], canvases = new Map();
  const walk = (el, ctx) => {
    if (SKIP.has(el.tagName.toUpperCase())) return;
    const cs = getComputedStyle(el);
    if (cs.display === 'none') return;
    const op = ctx.op * parseFloat(cs.opacity);
    if (!(op > 0.02)) return;
    const [s1, rot1] = matScale(cs.transform);
    const sc = ctx.sc * s1 * indScale(cs.scale);
    if (!(sc > 0.01)) return;
    const rot = ctx.rot + rot1;
    let clip = ctx.clip;
    const ox = cs.overflowX, oy = cs.overflowY;
    if (el !== root && ((ox !== 'visible') || (oy !== 'visible')) && el.tagName.toUpperCase() !== 'SVG') {
      const r = el.getBoundingClientRect();
      // a clipper that covers the whole frame (the stage, a camera wrapper) only crops at the screen edge: that is the
      // very thing rule 2 must still see, so it is not a mask
      if (!(r.left <= 1 && r.top <= 1 && r.right >= W - 1 && r.bottom >= H - 1)) clip = inter(clip, [r.left, r.top, r.right, r.bottom]);
    }
    const cp = ctx.cp || (cs.clipPath && cs.clipPath !== 'none') || (cs.webkitMaskImage && cs.webkitMaskImage !== 'none') || false;
    const nctx = { op, sc, rot, clip, cp };
    const tag = el.tagName.toUpperCase();
    const hidden = cs.visibility === 'hidden';
    if (tag === 'CANVAS' && !hidden) canvases.set(el, nctx);
    // ---- own text
    if (!hidden) {
      const isSvgText = typeof SVGTextContentElement !== 'undefined' && el instanceof SVGTextContentElement;
      for (const n of el.childNodes) {
        if (n.nodeType !== 3) continue;
        const raw = n.nodeValue.replace(/\s+/g, ' ').trim();
        if (!raw) continue;
        const rg = document.createRange(); rg.selectNodeContents(n);
        const rects = [...rg.getClientRects()].filter((r) => r.width > 0.5 && r.height > 0.5);
        if (!rects.length) continue;
        let fs = parseFloat(cs.fontSize), fsc = sc;
        if (isSvgText && el.getScreenCTM) { const m = el.getScreenCTM(); if (m) fsc = Math.sqrt(Math.abs(m.a * m.d - m.b * m.c)); }
        const fpx = fs * fsc;
        let txt = raw;
        const tt = cs.textTransform; if (tt === 'uppercase') txt = raw.toUpperCase(); else if (tt === 'lowercase') txt = raw.toLowerCase();
        // alpha of the glyph fill
        let alpha = 1; const fill = rgba(cs.webkitTextFillColor) || rgba(cs.color);
        if (fill) alpha = fill.a;
        if (alpha < 0.02 && (cs.webkitBackgroundClip === 'text' || cs.backgroundClip === 'text')) alpha = 1;
        if (isSvgText) { const f = rgba(cs.fill); alpha = f ? f.a : 1; if (cs.fill === 'none') alpha = 0; }
        // tight ink boxes (what Vision's OCR would box): content-area line rect, narrowed to the glyph ascent/descent
        const font = cs.fontStyle + ' ' + cs.fontWeight + ' ' + fs + 'px ' + cs.fontFamily;
        const k = ink(font, txt);
        const useInk = Math.abs(rot) < 0.17 && k[2] > 0;
        const lines = [], inks = [];
        for (const r of rects) {
          let L = [r.left, r.top, r.right, r.bottom];
          const last = lines[lines.length - 1];
          if (last && Math.abs(last[1] - L[1]) < 0.35 * (L[3] - L[1]) && L[0] <= last[2] + 3 && L[2] >= last[0] - 3) { last[0] = Math.min(last[0], L[0]); last[2] = Math.max(last[2], L[2]); last[1] = Math.min(last[1], L[1]); last[3] = Math.max(last[3], L[3]); continue; }
          lines.push(L);
        }
        for (const L of lines) {
          if (useInk) { const top = L[1] + (k[2] - k[0]) * fsc, bot = L[1] + (k[2] + k[1]) * fsc; inks.push([L[0], Math.max(L[1], top), L[2], Math.min(L[3] + 0.5 * fsc, bot)]); }
          else inks.push(L.slice());
        }
        // visible share after non-root overflow clips
        let tot = 0, vis = 0; const cl = [];
        for (const L of inks) { const a = area(L); tot += a; const c = clip ? inter(L, clip) : L; const ca = area(c); vis += ca; if (ca > 0) cl.push(c); }
        texts.push({ id: idOf(el), n: texts.length, el, e: short(el), t: raw.slice(0, 160), fs: +fs.toFixed(2), sc: +fsc.toFixed(4), fpx: +fpx.toFixed(2), op: +(op * alpha).toFixed(3),
          ink: inks.map((r) => r.map((v) => +v.toFixed(1))), vis: tot > 0 ? +(vis / tot).toFixed(3) : 0, cp: !!cp, cut: cl.map((r) => r.map((v) => +v.toFixed(1))) });
      }
    }
    // ---- images (text-bearing crops are matched to sources.js in Python by src + natural size)
    if (!hidden && (tag === 'IMG')) {
      const r = el.getBoundingClientRect();
      if (r.width > 1 && r.height > 1) {
        const nw = el.naturalWidth || 0;
        const lw = el.offsetWidth || r.width / sc;
        imgs.push({ id: idOf(el), e: short(el), src: el.getAttribute('src') || el.currentSrc || '', nw, nh: el.naturalHeight || 0, k: nw ? +(lw / nw * sc).toFixed(4) : 0,
          op: +op.toFixed(3), box: [r.left, r.top, r.right, r.bottom].map((v) => +v.toFixed(1)), cut: (clip ? inter([r.left, r.top, r.right, r.bottom], clip) : [r.left, r.top, r.right, r.bottom]).map((v) => +v.toFixed(1)),
          vis: clip ? +(area(inter([r.left, r.top, r.right, r.bottom], clip)) / Math.max(1, area([r.left, r.top, r.right, r.bottom]))).toFixed(3) : 1, cp: !!cp });
      }
    }
    // ---- painted elements for the emptiness test
    if (!hidden && el !== root && !(typeof SVGElement !== 'undefined' && el instanceof SVGElement && tag !== 'SVG' && !(['PATH', 'RECT', 'CIRCLE', 'ELLIPSE', 'LINE', 'POLYLINE', 'POLYGON', 'IMAGE'].includes(tag)))) {
      let kind = null, eo = op;
      if (tag === 'IMG' || tag === 'VIDEO' || tag === 'CANVAS' || tag === 'PICTURE') kind = tag.toLowerCase();
      else if (['PATH', 'RECT', 'CIRCLE', 'ELLIPSE', 'LINE', 'POLYLINE', 'POLYGON', 'IMAGE'].includes(tag)) {
        const f = cs.fill, st = cs.stroke; const fa = f !== 'none' ? (rgba(f) ? rgba(f).a : 1) * parseFloat(cs.fillOpacity || 1) : 0; const sa = (st !== 'none' && parseFloat(cs.strokeWidth) > 0) ? parseFloat(cs.strokeOpacity || 1) : 0;
        if (tag === 'IMAGE' || fa > 0.05 || sa > 0.05) { kind = 'svg-' + tag.toLowerCase(); eo = op * Math.max(fa, sa); }
      } else {
        const bg = rgba(cs.backgroundColor), hasImg = cs.backgroundImage && cs.backgroundImage !== 'none';
        const bw = parseFloat(cs.borderTopWidth) + parseFloat(cs.borderBottomWidth) + parseFloat(cs.borderLeftWidth) + parseFloat(cs.borderRightWidth);
        const bc = rgba(cs.borderTopColor);
        if ((bg && bg.a > 0.05) || hasImg) { kind = hasImg ? (/url\(/.test(cs.backgroundImage) ? 'bgimg' : 'gradient') : 'bgcolor'; eo = op * (bg && bg.a > 0.05 ? bg.a : 1); }
        else if (bw > 0 && bc && bc.a > 0.05) { kind = 'border'; eo = op * bc.a; }
      }
      if (kind && eo >= 0.3) {
        const r = el.getBoundingClientRect();
        let b = [r.left, r.top, r.right, r.bottom];
        const c = clip ? inter(b, clip) : b;
        const frac = area(b) > 0 ? area(c) / area(b) : 0;
        if (area(c) >= 0.01 * W * H && frac > 0.2) paints.push({ id: idOf(el), e: short(el), kind, eo: +eo.toFixed(2), box: c.map((v) => +v.toFixed(1)), cp: !!cp });
      }
    }
    for (const ch of el.children) walk(ch, nctx);
  };
  walk(root, { op: 1, sc: 1, rot: 0, clip: null, cp: false });

  // ---- text drawn into a <canvas> (fillText / strokeText calls recorded during this seek by the init hook)
  const calls = window.__dlcalls || [];
  const seenCv = new Map();
  for (const c of calls) {
    const info = canvases.get(c.canvas); if (!info || !c.canvas.width || !c.canvas.height) continue;
    const r = c.canvas.getBoundingClientRect(); if (r.width < 1 || r.height < 1) continue;
    const kx = r.width / c.canvas.width, ky = r.height / c.canvas.height;
    canvas.font = c.font; canvas.textAlign = c.align; canvas.textBaseline = c.base;
    const m = canvas.measureText(c.text);
    const cs4 = [[c.x - m.actualBoundingBoxLeft, c.y - m.actualBoundingBoxAscent], [c.x + m.actualBoundingBoxRight, c.y - m.actualBoundingBoxAscent],
                 [c.x + m.actualBoundingBoxRight, c.y + m.actualBoundingBoxDescent], [c.x - m.actualBoundingBoxLeft, c.y + m.actualBoundingBoxDescent]];
    let X0 = 1e9, Y0 = 1e9, X1 = -1e9, Y1 = -1e9;
    for (const [px, py] of cs4) { const X = r.left + (c.tm.a * px + c.tm.c * py + c.tm.e) * kx, Y = r.top + (c.tm.b * px + c.tm.d * py + c.tm.f) * ky; X0 = Math.min(X0, X); X1 = Math.max(X1, X); Y0 = Math.min(Y0, Y); Y1 = Math.max(Y1, Y); }
    if (!(X1 > X0 && Y1 > Y0)) continue;
    const fsm = /(\d+(?:\.\d+)?)px/.exec(c.font); if (!fsm) continue;
    const fpx = parseFloat(fsm[1]) * Math.sqrt(Math.abs(c.tm.a * c.tm.d - c.tm.b * c.tm.c)) * Math.sqrt(kx * ky);
    const fa = typeof c.fill === 'string' ? rgba(c.fill) : null;
    const alpha = c.alpha * (fa ? fa.a : 1);
    const key = idOf(c.canvas) + '|' + c.text + '|' + Math.round(X0) + '|' + Math.round(Y0);
    if (seenCv.has(key)) continue; seenCv.set(key, 1);
    const nth = [...seenCv.keys()].filter((k) => k.startsWith(idOf(c.canvas) + '|' + c.text + '|')).length;
    const ib = [X0, Y0, X1, Y1]; const cl = info.clip ? inter(ib, info.clip) : ib;
    texts.push({ id: 'cv' + idOf(c.canvas) + ':' + c.text + '#' + nth, n: texts.length, el: c.canvas, e: 'canvas', t: c.text.replace(/\s+/g, ' ').trim().slice(0, 160), fs: +parseFloat(fsm[1]).toFixed(2), sc: +(fpx / parseFloat(fsm[1])).toFixed(4), fpx: +fpx.toFixed(2),
      op: +(info.op * alpha).toFixed(3), ink: [ib.map((v) => +v.toFixed(1))], vis: area(ib) > 0 ? +(area(cl) / area(ib)).toFixed(3) : 0, cp: !!info.cp, cut: [cl.map((v) => +v.toFixed(1))], cv: true });
  }

  // ---- occlusion (only for texts a rule might blame): an opaque painter above the text's own point hides it
  const profile = cfg.profile;
  const needOcc = (T) => {
    if (T.vis < 0.15 || T.op < 0.3) return false;
    if (T.fpx < 46) return true;
    const b = T.ink.reduce((a, r) => [Math.min(a[0], r[0]), Math.min(a[1], r[1]), Math.max(a[2], r[2]), Math.max(a[3], r[3])], [1e9, 1e9, -1e9, -1e9]);
    if (profile && profile.visible) {
      const v = profile.visible;
      if (b[0] < v.x0 + 12 || b[1] < v.y0 + 12 || b[2] > v.x1 - 12 || b[3] > v.y1 - 12) return true;
      for (const o of (profile.overlays || [])) { if (Math.min(b[2], o.x1) > Math.max(b[0], o.x0) && Math.min(b[3], o.y1) > Math.max(b[1], o.y0)) return true; }
    }
    // overlaps another text
    for (const U of texts) { if (U === T || U.vis < 0.15 || U.op < 0.3) continue; for (const a of T.ink) for (const c of U.ink) { const w = Math.min(a[2], c[2]) - Math.max(a[0], c[0]), h = Math.min(a[3], c[3]) - Math.max(a[1], c[1]); if (w > 0 && h > 0) return true; } }
    return false;
  };
  if (!window.__dlpe) { const st = document.createElement('style'); st.textContent = '*{pointer-events:auto!important}'; document.head.appendChild(st); window.__dlpe = true; }
  const opChain = new Map();
  const chainOp = (e) => { let o = 1; for (let x = e; x && x.nodeType === 1; x = x.parentElement) { if (opChain.has(x)) { o *= opChain.get(x); break; } o *= parseFloat(getComputedStyle(x).opacity); } return o; };
  const opaque = (e) => {
    const cs = getComputedStyle(e); const tag = e.tagName.toUpperCase();
    let own = 0;
    if (tag === 'IMG' || tag === 'VIDEO' || tag === 'CANVAS') own = 1;
    else { const bg = rgba(cs.backgroundColor); if (bg) own = bg.a; if (cs.backgroundImage && cs.backgroundImage !== 'none' && /url\(/.test(cs.backgroundImage)) own = Math.max(own, 0.9); }
    if (own < 0.8) return false;
    return chainOp(e) * own >= 0.8;
  };
  for (const T of texts) {
    T.occ = null;
    if (!needOcc(T)) continue;
    let hit = 0, n = 0;
    const pts = [];
    for (const r of T.ink.slice(0, 2)) { const cx = (r[0] + r[2]) / 2, cy = (r[1] + r[3]) / 2, hw = (r[2] - r[0]) / 4; pts.push([cx, cy], [cx - hw, cy], [cx + hw, cy]); }
    for (const [x, y] of pts) {
      if (x < 0 || y < 0 || x >= W || y >= H) continue;
      n++;
      for (const e of document.elementsFromPoint(x, y)) {
        if (e === T.el || e.contains(T.el)) break;   // the text's own box, or something painted beneath it (an ancestor)
        if (opaque(e)) { hit++; break; }   // anything else above it, a descendant included (children paint over their parent's text), hides it
      }
    }
    T.occ = n ? +(hit / n).toFixed(2) : null;
  }
  for (const T of texts) delete T.el;
  const rr = root.getBoundingClientRect();
  return { texts, imgs, paints, root: [rr.left, rr.top, rr.right, rr.bottom], nTl: Object.keys(window.__timelines || {}).length };
};

// ---------------------------------------------------------------------------------------------------------------
const plan = JSON.parse(fs.readFileSync(PLAN, 'utf8'));
const browser = await puppeteer.launch({ executablePath: CHROME, headless: true,
  args: ['--no-sandbox', '--disable-gpu', '--allow-file-access-from-files', '--disable-dev-shm-usage', '--hide-scrollbars', '--force-device-scale-factor=1'] });
const result = { runner: 'dom_lint_runner.mjs v1', chrome: await browser.version(), parts: {} };
let fail = 0;
for (const job of plan) {
  const page = await browser.newPage();
  await page.setViewport({ width: 1080, height: 1920, deviceScaleFactor: 1 });
  const errs = [];
  page.on('pageerror', (e) => errs.push(String(e).slice(0, 300)));
  await page.evaluateOnNewDocument(() => {
    // record every canvas text draw (fillText / strokeText) with the transform in force, so canvas-drawn labels are linted like DOM text
    window.__dlcalls = [];
    for (const name of ['fillText', 'strokeText']) {
      const orig = CanvasRenderingContext2D.prototype[name];
      CanvasRenderingContext2D.prototype[name] = function (text, x, y) {
        try { if (this.canvas && this.canvas.isConnected !== false) window.__dlcalls.push({ canvas: this.canvas, text: String(text), x, y, font: this.font, tm: this.getTransform(), alpha: this.globalAlpha, fill: name === 'fillText' ? this.fillStyle : this.strokeStyle, align: this.textAlign, base: this.textBaseline }); } catch (e) {}
        return orig.apply(this, arguments);
      };
    }
  });
  const idx = path.join(ROOT, job.look, 'index.html');
  await page.goto(pathToFileURL(idx).href, { waitUntil: 'load', timeout: 120000 });
  await page.addStyleTag({ content: 'html,body{margin:0}#root{width:1080px!important;height:1920px!important;position:relative;overflow:hidden}' });
  await page.waitForFunction('window.__timelines && Object.keys(window.__timelines).length > 0', { timeout: 60000 }).catch(() => {});
  await page.evaluate(async () => { try { await document.fonts.ready; } catch (e) {} await Promise.all([...document.images].map((i) => (i.decode ? i.decode().catch(() => 0) : 0))); });
  await new Promise((r) => setTimeout(r, 400));
  const samples = [];
  const times = [...new Set(job.times.map((t) => +t))].sort((a, b) => a - b);
  for (const t of times) {
    await page.evaluate((tt) => { window.__dlcalls = []; for (const k of Object.keys(window.__timelines || {})) { const tl = window.__timelines[k]; tl.pause(); tl.seek(tt, false); } }, t);
    const o = await page.evaluate(EXTRACT, { profile: PROFILE });
    o.t = t; samples.push(o);
    if (SHOTS && SHOT_TIMES.some((x) => Math.abs(x - t) < 1e-6)) { fs.mkdirSync(SHOTS, { recursive: true }); await page.screenshot({ path: path.join(SHOTS, job.part + '-t' + t.toFixed(2) + '.png') }); }
  }
  if (!samples.length || !samples[0].nTl) { fail++; errs.push('NO window.__timelines: the page did not register a timeline'); }
  result.parts[job.part] = { look: job.look, samples, errors: errs };
  await page.close();
  console.log('runner: ' + job.part + ' ' + samples.length + ' samples' + (errs.length ? ' ERRORS ' + errs.join(' | ') : ''));
}
await browser.close();
fs.mkdirSync(path.dirname(path.resolve(OUT)), { recursive: true });
fs.writeFileSync(OUT, JSON.stringify(result));
console.log('runner: wrote ' + OUT + ' (' + (fs.statSync(OUT).size / 1024).toFixed(0) + ' KB)');
process.exit(fail ? 3 : 0);
