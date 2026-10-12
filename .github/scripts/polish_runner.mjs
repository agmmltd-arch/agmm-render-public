#!/usr/bin/env node
// polish_runner.mjs  (root card "polish-shorts", 12 Oct 2026)  -- the in-browser half of kit/tools/polish_check.py
//
// Loads each part of a BUILT short package in headless Chrome at 1080x1920 and seeks the part's own GSAP timeline(s)
// at EVERY output frame (30 fps; window.__timelines, pause + seek(t, false): the mechanism dom_lint_runner.mjs and the
// hyperframes gsap adapter use).  For every visible element worth tracking it records, per frame, the facts a
// micro-defect check needs: box, effective opacity, cumulative scale and rotation, visible share after clips.
// It makes no judgement: the rules live in polish_check.py, so they can be re-tuned on the saved raw JSON with no browser.
//
//   node polish_runner.mjs --root <dir holding one folder per look> --parts <parts.json> --out <raw.json>
//        [--chrome <path>] [--puppeteer <module dir>] [--from 0] [--to 99999] [--every 1] [--fps 30]
// parts.json = [{"look": "s52-a", "part": "S52-A", "off": 0.0, "dur": 15.0}]   (kit/out/<ID>/build/parts.json "parts")
//
// Output raw.json:
//   {runner, chrome, fps, parts: {PART: {look, off, dur, g0, frames: [g..], els: {key: {m: meta, f: [frame idx into frames], d: [[x0,y0,x1,y1,o,s,r,v,zi]...]}}, errors}}}
//   key = DOM path; meta = {k: kind (text|img|svg|canvas|video|box), e: short tag, t: text, fs: font px, ta: text-align,
//        lw: words per line (text), ln: [[x0,y0,x1,y1]...] line boxes of the FIRST sample seen, pid: parent key, z: z-index chain}
import fs from 'node:fs';
import path from 'node:path';
import { pathToFileURL } from 'node:url';

const argv = process.argv.slice(2);
const arg = (k, d) => { const i = argv.indexOf(k); return i >= 0 ? argv[i + 1] : d; };
const ROOT = arg('--root'), PARTS = arg('--parts'), OUT = arg('--out');
if (!ROOT || !PARTS || !OUT) { console.error('usage: polish_runner.mjs --root DIR --parts parts.json --out raw.json'); process.exit(2); }
const FPS = +arg('--fps', '30');
const EVERY = Math.max(1, +arg('--every', '1'));
const T_FROM = +arg('--from', '0'), T_TO = +arg('--to', '99999');

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
// Runs INSIDE the page. One sample = every tracked element's facts at the current seek.
const EXTRACT = (cfg) => {
  const W = 1080, H = 1920;
  const root = document.getElementById('root') || document.body;
  const store = (window.__pc = window.__pc || { paths: new WeakMap(), meta: new Map(), words: new Map() });
  const SKIP = new Set(['SCRIPT', 'STYLE', 'NOSCRIPT', 'TITLE', 'META', 'LINK', 'HEAD', 'DEFS', 'CLIPPATH', 'MASK', 'LINEARGRADIENT', 'RADIALGRADIENT', 'PATTERN', 'FILTER', 'SYMBOL']);
  const SVGSHAPE = new Set(['PATH', 'RECT', 'CIRCLE', 'ELLIPSE', 'LINE', 'POLYLINE', 'POLYGON', 'IMAGE']);
  const inter = (a, b) => !a ? b : (!b ? a : [Math.max(a[0], b[0]), Math.max(a[1], b[1]), Math.min(a[2], b[2]), Math.min(a[3], b[3])]);
  const area = (r) => Math.max(0, r[2] - r[0]) * Math.max(0, r[3] - r[1]);
  const rgba = (s) => { const m = /rgba?\(([^)]*)\)/.exec(s || ''); if (!m) return null; const p = m[1].split(/[ ,\/]+/).filter(Boolean).map(parseFloat); return { r: p[0], g: p[1], b: p[2], a: p.length > 3 ? p[3] : 1 }; };
  const matScale = (tr) => {
    if (!tr || tr === 'none') return [1, 0];
    let m = /^matrix\(([^)]*)\)$/.exec(tr);
    if (m) { const p = m[1].split(',').map(parseFloat); return [Math.sqrt(Math.abs(p[0] * p[3] - p[1] * p[2])), Math.atan2(p[1], p[0])]; }
    m = /^matrix3d\(([^)]*)\)$/.exec(tr);
    if (m) { const p = m[1].split(',').map(parseFloat); const sx = Math.hypot(p[0], p[1], p[2]), sy = Math.hypot(p[4], p[5], p[6]); return [Math.sqrt(sx * sy), Math.atan2(p[1], p[0])]; }
    return [1, 0];
  };
  const indScale = (s) => { if (!s || s === 'none') return 1; const p = s.split(/\s+/).map(parseFloat); return Math.sqrt(Math.abs(p[0] * (p.length > 1 ? p[1] : p[0]))) || 1; };
  const short = (el) => { let s = el.tagName.toLowerCase(); if (el.id) s += '#' + el.id; const c = (typeof el.className === 'string' ? el.className : (el.className && el.className.baseVal) || '').trim().split(/\s+/).filter(Boolean).slice(0, 2); if (c.length) s += '.' + c.join('.'); return s; };
  const keyOf = (el) => {
    let k = store.paths.get(el);
    if (k) return k;
    const par = el.parentElement;
    let nth = 1;
    if (par) { for (const s of par.children) { if (s === el) break; if (s.tagName === el.tagName) nth++; } }
    k = (par && el !== root ? keyOf(par) + '/' : '') + el.tagName.toLowerCase() + (el.id ? '#' + el.id : '') + ':' + nth;
    store.paths.set(el, k);
    return k;
  };
  const MIN_OBJ = cfg.minObj || 2500;     // px^2: smaller painted things are texture, not objects
  const els = [];                          // [key, kind, box(4), eo, sc, rot, vis, zi, extra]
  const metas = [];
  const zOf = (cs) => { const z = parseInt(cs.zIndex, 10); return Number.isFinite(z) ? z : 0; };
  const canvases = [];
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
      if (!(r.left <= 1 && r.top <= 1 && r.right >= W - 1 && r.bottom >= H - 1)) clip = inter(clip, [r.left, r.top, r.right, r.bottom]);
    }
    if (cs.clipPath && cs.clipPath.startsWith('inset(')) {
      const m = /^inset\(([^)]*)\)/.exec(cs.clipPath);
      if (m) {
        const tok = m[1].split(' round')[0].trim().split(/\s+/);
        const r = el.getBoundingClientRect();
        const val = (v, ref) => (v.endsWith('%') ? parseFloat(v) / 100 * ref : parseFloat(v));
        const T = tok[0], Rr = tok[1] || tok[0], B = tok[2] || tok[0], L = tok[3] || tok[1] || tok[0];
        const box = [r.left + val(L, r.width), r.top + val(T, r.height), r.right - val(Rr, r.width), r.bottom - val(B, r.height)];
        if (box.every((v) => Number.isFinite(v))) clip = inter(clip, box);
      }
    }
    const zc = ctx.z.slice(); const zi = zOf(cs); if (cs.position !== 'static' && cs.zIndex !== 'auto') zc.push(zi);
    const nctx = { op, sc, rot, clip, z: zc };
    const tag = el.tagName.toUpperCase();
    const hidden = cs.visibility === 'hidden';
    // ---- own text
    if (!hidden) {
      for (const n of el.childNodes) {
        if (n.nodeType !== 3) continue;
        const raw = n.nodeValue.replace(/\s+/g, ' ').trim();
        if (!raw) continue;
        const rg = document.createRange(); rg.selectNodeContents(n);
        const rects = [...rg.getClientRects()].filter((r) => r.width > 0.5 && r.height > 0.5);
        if (!rects.length) continue;
        const lines = [];
        for (const r of rects) {
          const L = [r.left, r.top, r.right, r.bottom];
          const last = lines[lines.length - 1];
          if (last && Math.abs(last[1] - L[1]) < 0.35 * (L[3] - L[1]) && L[0] <= last[2] + 3 && L[2] >= last[0] - 3) { last[0] = Math.min(last[0], L[0]); last[2] = Math.max(last[2], L[2]); last[1] = Math.min(last[1], L[1]); last[3] = Math.max(last[3], L[3]); continue; }
          lines.push(L);
        }
        const fs0 = parseFloat(cs.fontSize);
        const isSvgText = typeof SVGTextContentElement !== 'undefined' && el instanceof SVGTextContentElement;
        let fsc = sc;
        if (isSvgText && el.getScreenCTM) { const m = el.getScreenCTM(); if (m) fsc = Math.sqrt(Math.abs(m.a * m.d - m.b * m.c)); }
        let alpha = 1; const fill = rgba(cs.webkitTextFillColor) || rgba(cs.color); if (fill) alpha = fill.a;
        if (alpha < 0.02 && (cs.webkitBackgroundClip === 'text' || cs.backgroundClip === 'text')) alpha = 1;
        if (isSvgText) { const f = rgba(cs.fill); alpha = f ? f.a : 1; if (cs.fill === 'none') alpha = 0; }
        const bx = [1e9, 1e9, -1e9, -1e9];
        for (const L of lines) { bx[0] = Math.min(bx[0], L[0]); bx[1] = Math.min(bx[1], L[1]); bx[2] = Math.max(bx[2], L[2]); bx[3] = Math.max(bx[3], L[3]); }
        let tot = 0, vis = 0;
        for (const L of lines) { tot += area(L); vis += area(clip ? inter(L, clip) : L); }
        const key = keyOf(el) + '#t' + (el.childNodes.length > 1 ? [...el.childNodes].indexOf(n) : 0);
        // words per line, only when the text wraps (cached by text + line count + width, so layout work is not repeated per frame)
        let lw = null;
        if (lines.length >= 2) {
          const ck = raw + '|' + lines.length + '|' + Math.round(bx[2] - bx[0]) + '|' + fs0;
          lw = store.words.get(ck);
          if (!lw) {
            lw = []; const tops = [];
            const re = /\S+/g; let m; const nv = n.nodeValue;
            while ((m = re.exec(nv))) {
              const r2 = document.createRange(); r2.setStart(n, m.index); r2.setEnd(n, m.index + m[0].length);
              const rr = r2.getClientRects()[0]; if (!rr) continue;
              const cy = (rr.top + rr.bottom) / 2;
              let li = tops.findIndex((t) => Math.abs(t - cy) < 0.5 * (rr.bottom - rr.top));
              if (li < 0) { tops.push(cy); li = tops.length - 1; lw.push(0); }
              lw[li]++;
            }
            store.words.set(ck, lw);
          }
        }
        let txt = raw; const tt = cs.textTransform; if (tt === 'uppercase') txt = raw.toUpperCase(); else if (tt === 'lowercase') txt = raw.toLowerCase();
        if (!store.meta.has(key)) store.meta.set(key, 1);
        els.push([key, 'text', bx.map((v) => +v.toFixed(1)), +(op * alpha).toFixed(3), +fsc.toFixed(4), +rot.toFixed(4), tot > 0 ? +(vis / tot).toFixed(3) : 0, zc.join('.'),
                  { t: txt.slice(0, 120), fs: +(fs0 * fsc).toFixed(1), ta: cs.textAlign, lw, ln: lines.map((r) => r.map((v) => +v.toFixed(1))), e: short(el), pid: keyOf(el.parentElement || el) }]);
      }
    }
    // ---- painted objects
    if (!hidden && el !== root) {
      let kind = null, eo = op;
      if (tag === 'IMG' || tag === 'VIDEO' || tag === 'CANVAS' || tag === 'PICTURE') kind = tag.toLowerCase();
      else if (SVGSHAPE.has(tag)) {
        const f = cs.fill, st = cs.stroke;
        const fa = f !== 'none' ? (rgba(f) ? rgba(f).a : 1) * parseFloat(cs.fillOpacity || 1) : 0;
        const sa = (st !== 'none' && parseFloat(cs.strokeWidth) > 0) ? parseFloat(cs.strokeOpacity || 1) : 0;
        if (tag === 'IMAGE' || fa > 0.05 || sa > 0.05) { kind = 'svg'; eo = op * Math.max(fa, sa); }
      } else if (!(typeof SVGElement !== 'undefined' && el instanceof SVGElement)) {
        const bg = rgba(cs.backgroundColor), hasImg = cs.backgroundImage && cs.backgroundImage !== 'none';
        const bw = parseFloat(cs.borderTopWidth) + parseFloat(cs.borderBottomWidth) + parseFloat(cs.borderLeftWidth) + parseFloat(cs.borderRightWidth);
        const bc = rgba(cs.borderTopColor);
        if ((bg && bg.a > 0.05) || hasImg) { kind = 'box'; eo = op * (bg && bg.a > 0.05 ? bg.a : 1); }
        else if (bw > 0 && bc && bc.a > 0.05) { kind = 'box'; eo = op * bc.a; }
      }
      if (kind && eo >= 0.05) {
        const r = el.getBoundingClientRect();
        const b = [r.left, r.top, r.right, r.bottom];
        const c = clip ? inter(b, clip) : b;
        if (area(b) >= MIN_OBJ) {
          const frac = area(b) > 0 ? area(c) / area(b) : 0;
          els.push([keyOf(el), kind, b.map((v) => +v.toFixed(1)), +eo.toFixed(3), +sc.toFixed(4), +rot.toFixed(4), +frac.toFixed(3), zc.join('.'),
                    { e: short(el), pid: keyOf(el.parentElement || el), cr: (cs.borderTopLeftRadius || '0'), sh: (cs.boxShadow && cs.boxShadow !== 'none') ? 1 : 0, bw: parseFloat(cs.borderTopWidth) || 0 }]);
        }
      }
    }
    for (const ch of el.children) walk(ch, nctx);
  };
  walk(root, { op: 1, sc: 1, rot: 0, clip: null, z: [] });
  return els;
};

// ---------------------------------------------------------------------------------------------------------------
const parts = JSON.parse(fs.readFileSync(PARTS, 'utf8'));
const browser = await puppeteer.launch({ executablePath: CHROME, headless: true,
  args: ['--no-sandbox', '--disable-gpu', '--allow-file-access-from-files', '--disable-dev-shm-usage', '--hide-scrollbars', '--force-device-scale-factor=1'] });
const result = { runner: 'polish_runner.mjs v1', chrome: await browser.version(), fps: FPS, parts: {} };
let fail = 0;
for (const job of parts) {
  const page = await browser.newPage();
  await page.setViewport({ width: 1080, height: 1920, deviceScaleFactor: 1 });
  const errs = [];
  page.on('pageerror', (e) => errs.push(String(e).slice(0, 300)));
  const idx = path.join(ROOT, job.look, 'index.html');
  await page.goto(pathToFileURL(idx).href, { waitUntil: 'load', timeout: 120000 });
  await page.addStyleTag({ content: 'html,body{margin:0}#root{width:1080px!important;height:1920px!important;position:relative;overflow:hidden}' });
  await page.waitForFunction('window.__timelines && Object.keys(window.__timelines).length > 0', { timeout: 60000 }).catch(() => {});
  await page.evaluate(async () => { try { await document.fonts.ready; } catch (e) {} await Promise.all([...document.images].map((i) => (i.decode ? i.decode().catch(() => 0) : 0))); });
  await new Promise((r) => setTimeout(r, 400));
  // story frames covered by this part: g in [ceil(off*fps), (off+dur)*fps)
  const g0 = Math.ceil(job.off * FPS - 1e-6), g1 = Math.ceil((job.off + job.dur) * FPS - 1e-6);
  const frames = [];
  const els = {};
  let nTl = 0;
  const t0 = Date.now();
  for (let g = g0; g < g1; g += EVERY) {
    const tl = g / FPS - job.off;
    if (g / FPS < T_FROM || g / FPS > T_TO) continue;
    const nT = await page.evaluate((tt) => {
      for (const k of Object.keys(window.__timelines || {})) { const tlx = window.__timelines[k]; tlx.pause(); tlx.seek(tt, false); }
      return Object.keys(window.__timelines || {}).length;
    }, tl);
    const rows = [nT, await page.evaluate(EXTRACT, {})];
    frames.push(g);
    const fi = frames.length - 1;
    nTl = rows[0];
    for (const r of rows[1]) {
      const key = r[0];
      let e = els[key];
      if (!e) { e = els[key] = { m: { k: r[1], ...r[8] }, f: [], d: [] }; }
      e.f.push(fi);
      e.d.push([r[2][0], r[2][1], r[2][2], r[2][3], r[3], r[4], r[5], r[6], r[7]]);
      if (r[1] === 'text' && r[8]) { e.m.t = r[8].t; if (r[8].lw) e.m.lw = r[8].lw; e.m.fs = r[8].fs; }
    }
  }
  if (!frames.length || !nTl) { fail++; errs.push('NO window.__timelines: the page did not register a timeline'); }
  result.parts[job.part] = { look: job.look, off: job.off, dur: job.dur, frames, els, errors: errs };
  await page.close();
  console.log('runner: ' + job.part + ' ' + frames.length + ' frames, ' + Object.keys(els).length + ' elements, ' + ((Date.now() - t0) / 1000).toFixed(0) + ' s' + (errs.length ? ' ERRORS ' + errs.join(' | ') : ''));
}
await browser.close();
fs.mkdirSync(path.dirname(path.resolve(OUT)), { recursive: true });
fs.writeFileSync(OUT, JSON.stringify(result));
console.log('runner: wrote ' + OUT + ' (' + (fs.statSync(OUT).size / 1024).toFixed(0) + ' KB)');
process.exit(fail ? 3 : 0);
