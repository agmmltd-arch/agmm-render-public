/* FMT v2: the format engine's runtime (kit/tools/format_engine_rt.js; v1 was the slideshow template, archived as format_engine_rt.js.bak-2026-10-20-slideshow).
   format_engine.py inlines this file into specs/<ID>/scenes.js with the short's display list (window.FMT_DATA). ALL layout (wrapping, boxes, the universal safe zone) is decided in
   Python with the kit's own fonts; this file draws one WORLD and a few HERO objects and plays the display list. Everything is a pure function of timeline time.

   The grammar is S05's (the approved bar, 53% held at 3 s): one WORLD the story lives in (the real coastlines of ds/map.js, a camera that travels between beats), ONE hero tag
   that persists, moves and returns on the last frame, a known-name logo plate, condensed headlines that fill the width, real source clippings with the clause marked, a chart the
   figure turns into, physical artefacts (a legal pad), a CTA card over the world, and a last 0.5 s that is frame 0 again.
     world   AG_MAP land + graticule + pins; camera keys {t, px, py, z} sprung between beats (never still)
     tag     the hero: {t, x, y, w, h, vfs, lop, rot, op} keys; swings like a pendulum; slams on a spoken figure
     plate   the persistent known-name plate (logo image or condensed wordmark): {t, x, y, w, h, op} keys
     items   text (html runs for accent words) / rect / img / path / ring / bars, each with an in-time, an out-time and a motion
   Motion physics: damped spring on position and size (closed form), 6 frame fade, 5 frame ease-in exit, slam 1.06 -> 1.00 in 0.16 s from the top-left. */
(function () {
  "use strict";
  var F = window.FMT = window.FMT || {};
  var FR = 1 / 30;
  var FONT = { cond: "'AG2 Big Shoulders','Impact','Arial Narrow',sans-serif", serif: "'AG Source Serif','Source Serif 4',Georgia,serif", sans: "'AG Space Grotesk','Helvetica Neue',Arial,sans-serif",
               mono: "'AG2 JetBrains Mono','AG Plex Mono',monospace" };
  var AL = { l: "left", c: "center", r: "right" };
  function cl(v, a, b) { return v < a ? a : (v > b ? b : v); }
  function mix(a, b, u) { return a + (b - a) * u; }
  function eo3(p) { p = cl(p, 0, 1); return 1 - Math.pow(1 - p, 3); }
  function ei3(p) { p = cl(p, 0, 1); return p * p * p; }
  function eo4(p) { p = cl(p, 0, 1); return 1 - Math.pow(1 - p, 4); }
  function hex(c) { var m = /^#?([0-9a-f]{6})$/i.exec(c || "#000000"); var n = parseInt(m ? m[1] : "000000", 16); return [(n >> 16) & 255, (n >> 8) & 255, n & 255]; }
  function mixc(a, b, u) { var x = hex(a), y = hex(b); return "rgb(" + [0, 1, 2].map(function (i) { return Math.round(x[i] + (y[i] - x[i]) * u); }).join(",") + ")"; }
  function esc(s) { return String(s == null ? "" : s).replace(/&/g, "&amp;").replace(/</g, "&lt;"); }
  function px(v) { return (Math.round(v * 100) / 100) + "px"; }
  function spring(t, z, w) { if (t <= 0) return 0; var s = Math.sqrt(1 - z * z), wd = w * s, e = Math.exp(-z * w * t); return 1 - e * (Math.cos(wd * t) + (z / s) * Math.sin(wd * t)); }
  F.spring = spring;
  function mk(parent, css, html, tag) { var e = document.createElement(tag || "div"); e.style.cssText = "position:absolute;" + css; if (html != null) e.innerHTML = html; parent.appendChild(e); return e; }
  function svgEl(tag, attrs, parent) { var e = document.createElementNS("http://www.w3.org/2000/svg", tag); for (var k in attrs) e.setAttribute(k, attrs[k]); if (parent) parent.appendChild(e); return e; }

  // ---- the timed state of an item (in, hold, out)
  function timed(it, t, Z, W) {
    var s = { op: 0, dx: 0, dy: 0, sc: 1, sx: 1, bl: 0, clip: null, u: 0 };
    if (t < it.ti - 1e-6) return s;
    var di = it.di || 6 * FR, d = it.ain || "fade", u = (t - it.ti) / di, a = it.a == null ? 1 : it.a;
    s.u = cl(u, 0, 1);
    if (d === "rise") { s.op = eo3(u); s.dy = (1 - spring(t - it.ti, Z, W)) * (it.oy == null ? 22 : it.oy); }
    else if (d === "fade") { s.op = eo3(u); s.bl = (it.ob || 0) * (1 - eo3(u)); }
    else if (d === "cut") { s.op = 1; }
    else if (d === "slam") { s.op = 1; s.sc = 1 + ((it.os || 1.06) - 1) * (1 - eo4((t - it.ti) / 0.16)); }
    else if (d === "stamp") { s.op = eo3(u * 1.6); s.sc = 1 + ((it.os || 1.4) - 1) * (1 - eo3((t - it.ti) / 0.2)); }
    else if (d === "wipe") { s.op = 1; s.clip = "inset(0 " + (100 * (1 - eo3(u))).toFixed(2) + "% 0 0)"; }
    else if (d === "grow") { s.op = 1; s.sc = eo3(u); }
    else if (d === "flipx") { s.op = 1; s.sx = Math.max(0.001, eo3(u)); }
    else if (d === "draw" || d === "none") { s.op = d === "none" ? eo3(u * 3) : 1; }
    s.op *= a;
    if (it.fl && t >= it.ti) s.dy += 9 * Math.sin(t * 2.0 + it.fl * 1.7);          // the object floats a few px: a held beat is never a still picture
    if (it.to != null && t >= it.to - 1e-6) {
      var o = (t - it.to) / (it["do"] || 5 * FR), q = ei3(o);
      s.op *= 1 - q; s.dy -= 14 * q; s.bl = Math.max(s.bl, (it.ob || 0) * q);
    }
    return s;
  }
  function applyTimed(e, s, extraT) {
    e.style.opacity = s.op < 0.002 ? 0 : s.op.toFixed(3);
    e.style.visibility = s.op < 0.002 ? "hidden" : "visible";
    var tf = [];
    if (s.dx || s.dy) tf.push("translate(" + s.dx.toFixed(2) + "px," + s.dy.toFixed(2) + "px)");
    if (s.sc !== 1) tf.push("scale(" + s.sc.toFixed(4) + ")");
    if (s.sx !== 1) tf.push("scaleX(" + s.sx.toFixed(4) + ")");
    if (extraT) tf.push(extraT);
    e.style.transform = tf.join(" ");
    e.style.filter = s.bl > 0.05 ? "blur(" + s.bl.toFixed(2) + "px)" : "";
    e.style.clipPath = s.clip || "";
  }
  // keys: spring between layouts. props that are opacity-like ramp over 5 frames, the rest spring.
  function keyed(keys, t, props, Z, W, ramp) {
    var j = 0;
    for (var i = 0; i < keys.length; i++) if (t >= keys[i].t - 1e-9) j = i;
    var cur = keys[j], prev = keys[Math.max(0, j - 1)], p = j === 0 ? 1 : spring(t - cur.t, Z, W), q = j === 0 ? 1 : eo3((t - cur.t) / (5 * FR)), out = {};
    props.forEach(function (k) { var a0 = prev[k] == null ? cur[k] : prev[k], b0 = cur[k] == null ? a0 : cur[k]; out[k] = a0 == null ? undefined : mix(a0, b0, (ramp && ramp.indexOf(k) >= 0) ? q : p); });
    out.cur = cur;
    return out;
  }

  F.run = function (ctx, spec, K) {
    var D = window.FMT_DATA, ST = ctx.stage, Z = D.z, W = D.w, live = [];
    // =================================================== the world
    var WD = D.world, wroot = mk(ST, "left:0;top:0;width:1080px;height:1920px;overflow:hidden;background:" + D.pal.ground + ";z-index:0", null);
    wroot.className = "fmt-world";
    var plane = mk(wroot, "left:0;top:0;width:4000px;height:3550px;transform-origin:0 0;will-change:transform", null);
    var sv = svgEl("svg", { width: 4000, height: 3550, viewBox: "0 0 4000 3550" }, plane);
    sv.style.cssText = "position:absolute;left:0;top:0;overflow:visible";
    var MAP = window.AG_MAP;
    function rnd(seed) { var a = seed >>> 0; return function () { a = (a + 0x6D2B79F5) >>> 0; var t = a; t = Math.imul(t ^ (t >>> 15), t | 1); t ^= t + Math.imul(t ^ (t >>> 7), t | 61); return ((t ^ (t >>> 14)) >>> 0) / 4294967296; }; }
    function R_(parent, x, y, w, h, fill, r, rot, op) { var e = svgEl("rect", { x: x, y: y, width: w, height: h, fill: fill, rx: r || 0, opacity: op == null ? 1 : op }, parent); if (rot) e.setAttribute("transform", "rotate(" + rot + " " + (x + w / 2) + " " + (y + h / 2) + ")"); return e; }
    // Set-dressing worlds: abstract, no words, three tones from the palette (ground / land / coast). The camera travels over them like over the map.
    function drawSet(kind, sv, WD) {
      // one strong graphic plane per world, two or three flat tones, drawn at hero scale (no scattered silhouettes, no line patterns, no text-like shapes)
      var g0 = WD.ground, L = WD.land, C = WD.coast, i, j, x, y;
      R_(sv, 0, 0, 4000, 3550, g0, 0);
      if (kind === "desk") {                         // a big sheet of paper on the desk, a folder behind it, one mug ring
        R_(sv, 700, 300, 2700, 3000, C, 30, -4, .55);
        R_(sv, 900, 380, 2500, 2900, L, 24, 2.5);
        R_(sv, 900, 380, 2500, 330, C, 24, 2.5, .8);
        // (the mug ring is gone: a ring-shaped graphic reads as an object outside the safe zone to dom_lint)
        // (the mug ring is gone: a ring-shaped graphic reads as an object outside the safe zone to dom_lint)
        
      } else if (kind === "inbox") {                 // one screen: a single big plane and a header band (root 26 Oct: single planes, no rows, discs or pills)
        R_(sv, 500, 0, 3000, 3550, L, 0);
        R_(sv, 500, 0, 3000, 640, C, 0, 0, .55);
      } else if (kind === "statement") {             // one big sheet and a header band
        R_(sv, 600, 0, 2800, 3550, L, 0);
        R_(sv, 600, 0, 2800, 560, C, 0, 0, .8);
      } else if (kind === "counter" || kind === "room") {   // a room: wall, floor, one skirting band
        R_(sv, 0, 2250, 4000, 1300, L, 0);
        R_(sv, 0, 2250, 4000, 120, C, 0, 0, .85);
      } else if (kind === "phone") {                 // a phone at hero scale: body and screen
        R_(sv, 1000, 150, 2000, 3250, C, 220);
        R_(sv, 1090, 260, 1820, 3030, g0, 160);
      } else if (kind === "tribunal") {              // two dark panels and a bench plane
        R_(sv, 0, 0, 2000, 3550, L, 0);
        R_(sv, 0, 2300, 4000, 1250, C, 0, 0, .85);
      } else if (kind === "blueprint") {             // a drawing sheet with one inset plane
        R_(sv, 500, 200, 3000, 3150, L, 0);
        R_(sv, 800, 500, 2400, 2550, C, 0, 0, .28);
      }
    }
    if (WD.kind === "map" && MAP) {
      var g = svgEl("g", { stroke: WD.grid, "stroke-width": 3, fill: "none", opacity: 1 }, sv);
      for (var lon = -180; lon <= 180; lon += 10) { var a = MAP.project(lon, 80), b = MAP.project(lon, -60); svgEl("line", { x1: a[0], y1: a[1], x2: b[0], y2: b[1] }, g); }
      for (var lat = -60; lat <= 80; lat += 10) { var c = MAP.project(-180, lat), d = MAP.project(180, lat); svgEl("line", { x1: c[0], y1: c[1], x2: d[0], y2: c[1] }, g); }
      svgEl("path", { d: MAP.land, fill: WD.land, stroke: WD.coast, "stroke-width": 4, "shape-rendering": "optimizeSpeed" }, sv);
    } else if (WD.kind !== "map") { drawSet(WD.kind, sv, WD); }
    var routes = (WD.routes || []).map(function (r) {
      var mx = (r.a[0] + r.b[0]) / 2, my = (r.a[1] + r.b[1]) / 2 - Math.hypot(r.b[0] - r.a[0], r.b[1] - r.a[1]) * 0.22;
      var path = svgEl("path", { d: "M" + r.a[0] + "," + r.a[1] + " Q" + mx + "," + my + " " + r.b[0] + "," + r.b[1], stroke: WD.pin, "stroke-width": 9, fill: "none", "stroke-linecap": "round", pathLength: 1, "stroke-dasharray": "1", "stroke-dashoffset": 1, opacity: 0 }, sv);
      var da = svgEl("circle", { cx: r.a[0], cy: r.a[1], r: 26, fill: WD.pin, opacity: 0 }, sv), db = svgEl("circle", { cx: r.b[0], cy: r.b[1], r: 26, fill: WD.pin, opacity: 0 }, sv);
      return { r: r, path: path, da: da, db: db };
    });
    var pins = (WD.pins || []).map(function (p) {
      var xy = (MAP && WD.kind === "map") ? MAP.project(p.lon, p.lat) : [-9999, -9999];
      var ring = svgEl("circle", { cx: xy[0], cy: xy[1], r: 26, fill: "none", stroke: p.col || WD.pin, "stroke-width": 5 }, sv);
      var dot = svgEl("circle", { cx: xy[0], cy: xy[1], r: 20, fill: p.col || WD.pin }, sv);
      return { ring: ring, dot: dot, xy: xy, t0: p.t || 0 };
    });
    var scrimT = mk(wroot, "left:0;top:0;width:1080px;height:760px;background:linear-gradient(180deg,rgba(" + (WD.light ? "255,255,255,.35" : "0,0,0,.55") + ") 0%,rgba(" + (WD.light ? "255,255,255,.18" : "0,0,0,.38") + ") 55%,rgba(0,0,0,0) 100%);z-index:2;pointer-events:none", null);
    var scrimB = mk(wroot, "left:0;top:1180px;width:1080px;height:740px;background:linear-gradient(0deg,rgba(" + (WD.light ? "255,255,255,.3" : "0,0,0,.4") + ") 0%,rgba(0,0,0,0) 100%);z-index:2;pointer-events:none", null);
    live.push({ upd: function (t) {
      var s = keyed(WD.keys, t, ["px", "py", "z"], 0.9, 9, null);
      var drx = 34 * Math.sin(t * 0.75) + 10 * Math.sin(t * 1.7 + 1), dry = 26 * Math.sin(t * 0.61 + 0.5) + 8 * Math.sin(t * 1.4); s.z = s.z * (1 + 0.02 * Math.sin(t * 0.9));
      plane.style.transform = "translate(" + (WD.cx - s.px * s.z + drx).toFixed(2) + "px," + (WD.cy - s.py * s.z + dry).toFixed(2) + "px) scale(" + s.z.toFixed(4) + ")";
      routes.forEach(function (o) {
        var u = eo3((t - o.r.t0) / 1.0), on = t >= o.r.t0 - 1e-6 && t < o.r.t1, op = on ? 1 : 0;
        o.path.setAttribute("stroke-dashoffset", (1 - (on ? u : 0)).toFixed(4)); o.path.setAttribute("opacity", op); o.da.setAttribute("opacity", op); o.db.setAttribute("opacity", on && u > 0.98 ? 1 : 0);
      });
      pins.forEach(function (p) {
        var u = ((t * 0.7 + p.t0) % 1.6) / 1.6, on = t >= p.t0;
        p.ring.setAttribute("r", (24 + 90 * u).toFixed(1)); p.ring.setAttribute("opacity", on ? (0.8 * (1 - u)).toFixed(3) : 0); p.dot.setAttribute("opacity", on ? 1 : 0);
      });
    } });

    // =================================================== the display list (above the world)
    var car = mk(ST, "left:0;top:0;width:1080px;height:1920px;z-index:5", null);
    car.id = "fmt-carrier";
    function textCss(it) {
      return "left:" + px(it.x) + ";top:" + px(it.y) + ";width:" + px(it.w || 700) + ";font-family:" + FONT[it.face || "cond"] + ";font-weight:" + (it.wt || 400) + ";font-size:" + px(it.fs) +
        ";line-height:" + px(it.fs * (it.lh || 1.1)) + ";color:" + (it.col || D.pal.ink) + ";white-space:nowrap;text-align:" + AL[it.al || "l"] + ";letter-spacing:" + (it.ls || 0) +
        "em;opacity:0;visibility:hidden;" + (it.caps ? "text-transform:uppercase;" : "") + (it.it ? "font-style:italic;" : "") + (it.sh ? "text-shadow:" + it.sh + ";" : "") + "z-index:" + (it.z || 10) + ";" + (it.org ? "transform-origin:" + it.org + ";" : "");
    }
    function colorAt(it, t, base) {
      var c = base || it.col;
      if (!it.cols) return c;
      for (var i = 0; i < it.cols.length; i++) { var k = it.cols[i]; if (t >= k[0]) { var u = cl((t - k[0]) / (5 * FR), 0, 1); c = i === 0 ? mixc(it.col, k[1], u) : mixc(it.cols[i - 1][1], k[1], u); } }
      return c;
    }
    function buildText(it) {
      var e = mk(car, textCss(it), null);
      e.innerHTML = (it.html || it.lines.map(esc)).join("<br>");
      it.e = e;
      it.upd = function (t) {
        var s = timed(it, t, Z, W);
        var pl_ = it.pulses || (it.pulse != null ? [it.pulse] : []);
        for (var pi_ = 0; pi_ < pl_.length; pi_++) { var pt_ = pl_[pi_]; if (t >= pt_ && t < pt_ + 0.2) { s.sc *= 1 + 0.035 * Math.sin(Math.PI * (t - pt_) / 0.2); } }
        applyTimed(e, s, it.rot ? "rotate(" + it.rot + "deg)" : "");
        if (it.cols) e.style.color = colorAt(it, t);
      };
      return it;
    }
    function buildRect(it) {
      var css = "left:" + px(it.x) + ";top:" + px(it.y) + ";width:" + px(it.w) + ";height:" + px(it.h) + ";background-color:" + (it.fill || "transparent") + ";opacity:0;visibility:hidden;z-index:" + (it.z || 5) + ";" +
        (it.r != null ? "border-radius:" + (typeof it.r === "string" ? it.r : px(it.r)) + ";" : "") + (it.stroke ? "border:" + (it.sw || 4) + "px solid " + it.stroke + ";" : "") +
        (it.shadow ? "box-shadow:" + it.shadow + ";" : "") + (it.org ? "transform-origin:" + it.org + ";" : "") + (it.bg ? it.bg : "");
      var e = mk(car, css, null);
      it.e = e;
      it.upd = function (t) {
        var s = timed(it, t, Z, W), rot = it.rot ? "rotate(" + it.rot + "deg)" : "";
        if (it.pulse != null && t >= it.pulse && t < it.pulse + 0.2) { s.sc *= 1 - 0.06 * Math.sin(Math.PI * (t - it.pulse) / 0.2); }
        if (it.ain === "grow") { var gg = eo3((t - it.ti) / (it.di || 8 * FR)); if (t < it.ti) gg = 0; /* timed() owns opacity, including the exit. */ e.style.transformOrigin = it.org || "0% 50%"; s.sc = 1; applyTimed(e, s, (it.gx ? "scaleX(" : "scaleY(") + gg.toFixed(4) + ") " + rot); return; }
        applyTimed(e, s, rot);
        if (it.cols) e.style.backgroundColor = colorAt(it, t, it.fill);
      };
      return it;
    }
    function buildImg(it) {
      var e = mk(car, "left:" + px(it.x) + ";top:" + px(it.y) + ";width:" + px(it.w) + ";height:" + px(it.h) + ";opacity:0;visibility:hidden;z-index:" + (it.z || 6) + ";" + (it.shadow ? "box-shadow:" + it.shadow + ";" : "") + (it.bgc ? "background:" + it.bgc + ";" : ""), null, "img");
      e.src = it.src; e.alt = it.alt || ""; e.style.objectFit = "contain"; e.style.display = "block";
      it.e = e;
      it.upd = function (t) { applyTimed(e, timed(it, t, Z, W), it.rot ? "rotate(" + it.rot + "deg)" : ""); };
      return it;
    }
    function buildPath(it) {
      var holder = mk(car, "left:" + px(it.x) + ";top:" + px(it.y) + ";width:" + px(it.w) + ";height:" + px(it.h) + ";opacity:0;visibility:hidden;z-index:" + (it.z || 8) + ";", null);
      var s0 = svgEl("svg", { width: it.w, height: it.h, viewBox: it.vb || ("0 0 " + it.w + " " + it.h) }, holder);
      s0.style.cssText = "position:absolute;left:0;top:0;overflow:visible";
      var p = svgEl("path", { d: it.d, fill: it.fill || "none", stroke: it.stroke || "none", "stroke-width": it.sw || 6, "stroke-linecap": "round", "stroke-linejoin": "round", pathLength: 1 }, s0);
      if (it.ain === "draw") p.setAttribute("stroke-dasharray", "1");
      it.e = holder;
      it.upd = function (t) {
        var s = timed(it, t, Z, W);
        if (it.ain === "draw") p.setAttribute("stroke-dashoffset", (1 - eo3((t - it.ti) / (it.di || 10 * FR))).toFixed(4));
        applyTimed(holder, s, it.rot ? "rotate(" + it.rot + "deg)" : "");
      };
      return it;
    }
    function buildRing(it) {
      var e = mk(car, "left:" + px(it.x - it.r) + ";top:" + px(it.y - it.r) + ";width:" + px(2 * it.r) + ";height:" + px(2 * it.r) + ";border-radius:50%;border:" + (it.sw || 8) + "px solid " + it.stroke + ";opacity:0;visibility:hidden;z-index:" + (it.z || 12), null);
      it.e = e;
      it.upd = function (t) {
        var u = (t - it.ti) / (it.di || 0.5);
        if (u < 0 || u > 1) { e.style.opacity = 0; e.style.visibility = "hidden"; return; }
        e.style.visibility = "visible"; e.style.opacity = ((1 - eo3(u)) * 0.9).toFixed(3); e.style.transform = "scale(" + (0.5 + 1.7 * eo3(u)).toFixed(3) + ")";
      };
      return it;
    }
    function buildBars(it) {   // two bars rise on their spoken figures (S05's chart): it.bars [{x,w,h,fill,at,num,numfs,lab}], base line, value above, label below
      var holder = mk(car, "left:0;top:0;width:1080px;height:1920px;z-index:" + (it.z || 7) + ";opacity:0;visibility:hidden;pointer-events:none", null);
      mk(holder, "left:" + px(it.x) + ";top:" + px(it.base) + ";width:" + px(it.w) + ";height:6px;background:" + it.baseCol, null);
      var bs = it.bars.map(function (b) {
        var bar = mk(holder, "left:" + px(b.x) + ";top:" + px(it.base - b.h) + ";width:" + px(b.w) + ";height:" + px(b.h) + ";background:" + b.fill + ";border-radius:10px 10px 0 0;transform-origin:50% 100%", null);
        var num = mk(holder, "left:" + px(b.x - 40) + ";top:" + px(it.base - b.h - b.numfs * 1.0 - 14) + ";width:" + px(b.w + 80) + ";text-align:center;font-family:" + FONT.cond + ";font-weight:700;font-size:" + px(b.numfs) + ";line-height:" + px(b.numfs) + ";color:" + b.numcol + ";white-space:nowrap", esc(b.num));
        var lab = mk(holder, "left:" + px(b.x - 40) + ";top:" + px(it.base + 16) + ";width:" + px(b.w + 80) + ";text-align:center;font-family:" + FONT[it.labface || "cond"] + ";font-weight:700;font-size:" + px(it.labfs) + ";line-height:" + px(it.labfs * 1.1) + ";color:" + it.labcol + ";white-space:nowrap", esc(b.lab));
        return { bar: bar, num: num, lab: lab, b: b };
      });
      it.e = holder;
      it.upd = function (t) {
        var s = timed(it, t, Z, W);
        applyTimed(holder, s);
        bs.forEach(function (o) {
          var u = eo3((t - o.b.at) / 0.45), on = t >= o.b.at - 1e-6;
          o.bar.style.transform = "scaleY(" + (on ? Math.max(0.001, u) : 0.001).toFixed(4) + ")";
          var nu = on ? 1 : 0; o.num.style.opacity = nu; o.num.style.transform = on ? "scale(" + (1 + 0.05 * (1 - eo4((t - o.b.at) / 0.16))).toFixed(4) + ")" : "";
          o.num.style.transformOrigin = "50% 100%";
        });
      };
      return it;
    }

    // =================================================== the hero tag (persistent): keys {t,x,y,w,h,vfs,lop,rot,op}
    var TG = D.tag;
    var tagEl = mk(car, "z-index:20;transform-origin:50% 0;opacity:0", null);
    var card = mk(tagEl, "left:0;top:0;background:" + TG.fill + ";border-radius:" + TG.radius + "px;box-shadow:0 40px 90px rgba(0,0,0,.55);" + (TG.bg || ""), null);
    var hole = mk(card, "left:50%;top:26px;width:44px;height:44px;margin-left:-22px;border-radius:50%;background:" + D.pal.ground + ";box-shadow:inset 0 0 0 8px " + TG.rim, null);
    var str = mk(tagEl, "left:50%;width:8px;margin-left:-4px;background:" + TG.string + ";top:-24px;height:30px", null);
    var tv = mk(card, "left:0;width:100%;text-align:center;font-family:" + FONT.cond + ";font-weight:700;color:" + TG.ink + ";white-space:nowrap;line-height:1;letter-spacing:0", esc(TG.value));
    var tl = mk(card, "left:0;width:100%;text-align:center;font-family:" + FONT[TG.labface || "cond"] + ";font-weight:" + (TG.labwt || 700) + ";color:" + TG.labcol + ";line-height:1.12;white-space:nowrap;text-transform:uppercase;letter-spacing:.02em", (TG.label || []).map(esc).join("<br>"));
    live.push({ upd: function (t) {
      var s = keyed(TG.keys, t, ["x", "y", "w", "h", "vfs", "lfs", "lop", "rot", "op", "vy", "ly"], Z, W, ["op", "lop"]);
      var sw = 2.2 * Math.sin(t * 2 * Math.PI / 2.7) * Math.min(1, t / 0.8), rot = (s.rot || 0) + sw, sc = 1;
      (TG.pulses || []).forEach(function (pt) { if (t >= pt && t < pt + 0.22) { var u = (t - pt) / 0.22; sc *= 1 + 0.07 * (1 - eo4(u)); } });
      var drop = 0; (TG.drops || []).forEach(function (pt) { if (t >= pt) { drop += -40 * (1 - spring(t - pt, 0.5, 14)); } });
      tagEl.style.left = px(s.x); tagEl.style.top = px(s.y + drop); tagEl.style.width = px(s.w); tagEl.style.height = px(s.h);
      tagEl.style.transform = "rotate(" + rot.toFixed(3) + "deg) scale(" + sc.toFixed(4) + ")";
      card.style.width = px(s.w); card.style.height = px(s.h);
      hole.style.opacity = cl(s.lop, 0, 1).toFixed(3);
      tv.style.letterSpacing = (TG.vls || 0) + "em"; tv.style.fontSize = px(s.vfs); tv.style.top = px(s.vy);
      tl.style.fontSize = px(s.lfs); tl.style.top = px(s.ly); tl.style.opacity = cl(s.lop, 0, 1).toFixed(3);
      var op = cl(s.op, 0, 1); tagEl.style.opacity = op < 0.002 ? 0 : op.toFixed(3); tagEl.style.visibility = op < 0.002 ? "hidden" : "visible";
      str.style.opacity = cl(s.lop, 0, 1) < 0.5 ? 0 : 1;
    } });

    // =================================================== the known-name plate (persistent): keys {t,x,y,w,h,op}
    var PL = D.plate;
    var plEl = mk(car, "z-index:19;background:" + PL.fill + ";border-radius:18px;box-shadow:0 22px 50px rgba(0,0,0,.55);display:flex;align-items:center;justify-content:center;opacity:0;overflow:hidden", null);
    var plInner;
    if (PL.logo) { plInner = document.createElement("img"); plInner.src = PL.logo.src; plInner.alt = PL.name; plInner.style.cssText = "display:block;object-fit:contain"; plEl.appendChild(plInner); }
    else { plInner = document.createElement("div"); plInner.textContent = PL.name; plInner.style.cssText = "font-family:" + FONT.cond + ";font-weight:700;color:" + PL.ink + ";text-transform:uppercase;white-space:nowrap;line-height:1"; plEl.appendChild(plInner); }
    live.push({ upd: function (t) {
      var s = keyed(PL.keys, t, ["x", "y", "w", "h", "op", "fs"], Z, W, ["op"]);
      plEl.style.left = px(s.x); plEl.style.top = px(s.y); plEl.style.width = px(s.w); plEl.style.height = px(s.h);
      if (PL.logo) { plInner.style.maxWidth = px(s.w - 70); plInner.style.maxHeight = px(s.h - 36); plInner.style.width = "auto"; plInner.style.height = px(s.h - 36); plInner.style.maxWidth = px(s.w - 70); }
      else plInner.style.fontSize = px(s.fs);
      var op = cl(s.op, 0, 1); plEl.style.opacity = op < 0.002 ? 0 : op.toFixed(3); plEl.style.visibility = op < 0.002 ? "hidden" : "visible";
    } });

    // =================================================== the layout slots: one group per object span; its transform springs between the slots of its beats (the object travels, the camera stays)
    var OG = {};
    (D.og || []).forEach(function (g) {
      var el = mk(car, "left:0;top:0;width:1080px;height:1920px;z-index:11;pointer-events:none;transform-origin:" + px(g.cx) + " " + px(g.cy), null);
      OG[g.i] = el;
      live.push({ upd: function (t) { var s = keyed(g.keys, t, ["tx", "ty", "s", "op"], Z, W, ["op"]); el.style.opacity = cl(s.op == null ? 1 : s.op, 0, 1).toFixed(3); el.style.transform = "translate(" + s.tx.toFixed(2) + "px," + s.ty.toFixed(2) + "px) scale(" + s.s.toFixed(4) + ")"; } });
    });
    var car0 = car;
    D.items.forEach(function (it) {
      car = (it.og != null && OG[it.og]) ? OG[it.og] : car0;
      var b = it.k === "text" ? buildText(it) : it.k === "rect" ? buildRect(it) : it.k === "img" ? buildImg(it) : it.k === "path" ? buildPath(it) : it.k === "ring" ? buildRing(it) : it.k === "bars" ? buildBars(it) : null;
      if (b) live.push(b);
      car = car0;
    });
    function frame(t) { for (var i = 0; i < live.length; i++) live[i].upd(t); }
    AG.onFrame(ctx, frame);
    if (window.AGSTING && D.sting) AGSTING.mount(ctx, { avoid: D.sting.avoid, parent: ST });
  };
  F.beat = function (ctx, S, p, B, K) { /* intentionally empty: the world lives in the world scene */ };
})();
