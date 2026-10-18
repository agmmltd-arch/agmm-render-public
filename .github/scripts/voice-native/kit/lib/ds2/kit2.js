/* AGMM short-form design system, looks v2 (evidence, whitemodel, softui, desktop, chart, opsmap).
   Loads after the unmodified base engine ds/kit.js and reuses it: AG.init / AG.scene / AG.onFrame /
   AG.drift / AG.grain / AG.reel / AG.count / AG.normWords / AG.groupWords / AG.drawOn / AG.boil /
   AG.shake / AG.wobblePath / AG.roughLine / AG.tx.*. Adds the six looks' own versions of the shared
   components (captions, CTA) plus the look-specific primitives each needs (pins and string, window
   chrome and cursor, bars and axes, map plotting). Same law as the base: every effect is a pure
   function of timeline time, no Math.random, no clocks. */
(function () {
  "use strict";
  var AG = window.AG;
  window.__timelines = window.__timelines || {}; // the runtime normally provides it; a bare page preview does not
  var AG2 = (window.AG2 = {});
  var NS = "http://www.w3.org/2000/svg";

  // ---------------------------------------------------------------- camera keyframes
  // keys: [{t, x, y, s, r, ease}] -> one continuous move through every pose (never a held still).
  AG2.cam = function (ctx, el, keys, o) {
    o = o || {};
    var k0 = keys[0];
    ctx.tl.set(el, { x: k0.x || 0, y: k0.y || 0, scale: k0.s || 1, rotation: k0.r || 0, transformOrigin: o.origin || "50% 50%" }, 0);
    for (var i = 1; i < keys.length; i++) {
      var a = keys[i - 1], b = keys[i];
      ctx.tl.fromTo(el, { x: a.x || 0, y: a.y || 0, scale: a.s || 1, rotation: a.r || 0 },
        { x: b.x || 0, y: b.y || 0, scale: b.s || 1, rotation: b.r || 0, duration: b.t - a.t, ease: b.ease || "sine.inOut", immediateRender: false }, a.t);
    }
  };

  // ---------------------------------------------------------------- paper helpers
  // Torn / deckled edge as a clip-path polygon (seeded, so every render tears the same way).
  AG2.torn = function (seed, amp, sides) {
    amp = amp || 1.2; sides = sides || "tb";
    var pts = [], n = 26, i;
    for (i = 0; i <= n; i++) pts.push((i / n * 100).toFixed(2) + "% " + (sides.indexOf("t") >= 0 ? (AG.hash(i, seed) * amp).toFixed(2) : 0) + "%");
    for (i = n; i >= 0; i--) pts.push((i / n * 100).toFixed(2) + "% " + (100 - (sides.indexOf("b") >= 0 ? AG.hash(i + 99, seed) * amp : 0)).toFixed(2) + "%");
    return "polygon(" + pts.join(",") + ")";
  };

  // A photo print (polaroid style): white border, image, handwritten caption under it.
  AG2.photo = function (parent, o) {
    var p = AG.el("div", "ag2-photo", parent);
    p.style.cssText = "position:absolute;left:" + o.x + "px;top:" + o.y + "px;width:" + o.w + "px;background:#fbf8f1;padding:" + Math.round(o.w * 0.05) + "px " + Math.round(o.w * 0.05) + "px " + Math.round(o.w * (o.cap ? 0.2 : 0.07)) + "px;box-shadow:0 18px 30px var(--shadow),0 2px 3px rgba(0,0,0,0.3);transform-origin:50% 0%;";
    var im = AG.el("div", "", p);
    im.style.cssText = "width:100%;height:" + Math.round(o.w * (o.ratio || 0.75)) + "px;overflow:hidden;background:#222;";
    var img = AG.el("img", "", im); img.src = o.src;
    img.style.cssText = "width:100%;height:100%;object-fit:cover;display:block;filter:" + (o.filter || "saturate(0.85) contrast(1.05)");
    if (o.cap) { var c = AG.el("div", "", p, AG.esc(o.cap)); c.style.cssText = "font-family:var(--f-note);font-size:" + Math.round(o.w * 0.085) + "px;color:#222;text-align:center;margin-top:" + Math.round(o.w * 0.03) + "px;line-height:1"; }
    p.img = img;
    return p;
  };

  // Push pin: red head + shine + cast shadow; `drop` animates it pressing in.
  AG2.pin = function (parent, x, y, color) {
    var g = AG.el("div", "ag2-pin", parent);
    g.style.cssText = "position:absolute;left:" + (x - 22) + "px;top:" + (y - 22) + "px;width:44px;height:44px;z-index:8;";
    var sh = AG.el("div", "", g); sh.style.cssText = "position:absolute;left:14px;top:18px;width:44px;height:44px;border-radius:50%;background:rgba(0,0,0,0.35);filter:blur(4px)";
    var hd = AG.el("div", "", g); hd.style.cssText = "position:absolute;inset:0;border-radius:50%;background:radial-gradient(circle at 34% 30%, #ff8a7a 0 12%, " + (color || "#c3261d") + " 38%, #6d0f0a 100%)";
    g.shadow = sh;
    return g;
  };
  // An item lands on the board: dropped from above-camera, settles with a tilt, shadow tightens, pin presses.
  AG2.pinDrop = function (ctx, el, at, o) {
    o = o || {};
    var r = o.rot || 0;
    ctx.tl.set(el, { opacity: 0 }, 0);
    ctx.tl.set(el, { opacity: 1 }, at);
    ctx.tl.fromTo(el, { scale: 1.22, rotation: r - 7, y: -40, filter: "drop-shadow(0 60px 40px rgba(0,0,0,0.35))" },
      { scale: 1, rotation: r, y: 0, filter: "drop-shadow(0 0px 0px rgba(0,0,0,0))", duration: o.dur || 0.38, ease: "power3.in" }, at);
    ctx.tl.fromTo(el, { rotation: r }, { rotation: r + (o.sway || 1.6), duration: 0.5, ease: "sine.out", yoyo: true, repeat: 1, immediateRender: false }, at + (o.dur || 0.38));
    if (o.pin) {
      ctx.tl.set(o.pin, { opacity: 0 }, 0);
      ctx.tl.set(o.pin, { opacity: 1 }, at + (o.dur || 0.38) - 0.02);
      ctx.tl.fromTo(o.pin, { scale: 1.8 }, { scale: 1, duration: 0.14, ease: "power4.in" }, at + (o.dur || 0.38) - 0.02);
    }
  };
  // Red string between pins: a catenary-ish sag, drawn on like it is being pulled taut.
  AG2.string = function (ctx, svgEl, a, b, at, dur, o) {
    o = o || {};
    var sag = o.sag === undefined ? 60 : o.sag;
    var mx = (a[0] + b[0]) / 2, my = (a[1] + b[1]) / 2 + sag;
    var d = "M" + a[0] + " " + a[1] + " Q" + mx + " " + my + " " + b[0] + " " + b[1];
    var sh = AG.svg("path", { d: d, fill: "none", "stroke-width": 7, "stroke-linecap": "round", transform: "translate(8 12)" }, svgEl);
    sh.style.stroke = "rgba(0,0,0,0.3)";
    var p = AG.svg("path", { d: d, fill: "none", "stroke-width": 6, "stroke-linecap": "round" }, svgEl);
    p.style.stroke = "var(--string)";
    AG.drawOn(ctx, sh, at, dur, "power2.inOut");
    AG.drawOn(ctx, p, at, dur, "power2.inOut");
    return p;
  };
  // Rubber stamp in red ink: hard landing, board shake, ink slightly uneven (mask).
  AG2.inkStamp = function (ctx, parent, o) {
    var st = AG.el("div", "ag2-stamp", parent);
    st.style.cssText = "position:absolute;left:" + o.x + "px;top:" + o.y + "px;z-index:20;transform-origin:50% 50%;border:" + (o.bw || 10) + "px solid var(--accent);color:var(--accent);font-family:var(--f-small);font-size:" + (o.size || 96) + "px;letter-spacing:0.08em;padding:10px 30px 4px;line-height:1;white-space:nowrap;mix-blend-mode:" + (o.blend || "multiply") + ";background:" + (o.fill || "transparent") + ";" +
      "-webkit-mask-image:radial-gradient(circle at 30% 40%, #000 55%, rgba(0,0,0,0.55) 75%, #000 90%);mask-image:radial-gradient(circle at 30% 40%, #000 55%, rgba(0,0,0,0.55) 75%, #000 90%);";
    st.textContent = o.text;
    ctx.tl.set(st, { opacity: 0 }, 0);
    ctx.tl.set(st, { opacity: 1 }, o.at);
    ctx.tl.fromTo(st, { scale: 2.6, rotation: (o.rot || -8) - 8 }, { scale: 1, rotation: o.rot || -8, duration: 0.14, ease: "power4.in" }, o.at);
    if (o.shake) AG.shake(ctx, o.shake, o.at + 0.14, 14);
    return st;
  };

  // Typewriter: characters strike one by one (seeded jitter per char so it reads as struck, not faded).
  AG2.type = function (ctx, el, text, at, cps, o) {
    o = o || {};
    el.innerHTML = "";
    var chars = String(text).split("");
    var spans = chars.map(function (ch, i) {
      var s = AG.el("span", "", el);
      s.textContent = ch;
      if (ch === " ") s.style.whiteSpace = "pre";
      s.style.display = "inline-block";
      ctx.tl.set(s, { opacity: 0 }, 0);
      var t = at + i / cps + (AG.hash(i, 7) - 0.5) * 0.4 / cps;
      ctx.tl.set(s, { opacity: 1, y: (AG.sh(i, 3) * (o.jit || 1.5)).toFixed(1) }, Math.max(0, t));
      return s;
    });
    return { spans: spans, end: at + chars.length / cps };
  };

  // Streaming answer (adapted from the registry's streaming-text primitive): words land in uneven
  // token bursts, arriving grey and settling to ink.
  AG2.stream = function (ctx, el, text, at, wps, o) {
    o = o || {};
    el.innerHTML = "";
    var words = String(text).split(/\s+/);
    var t = at;
    words.forEach(function (w, i) {
      var s = AG.el("span", "", el);
      s.textContent = w;
      s.style.display = "inline-block";
      el.appendChild(document.createTextNode(" "));
      var burst = AG.hash(i, 17) < 0.35 ? 0.2 : 1;
      t += (1 / wps) * burst * (0.6 + AG.hash(i, 19) * 0.8);
      ctx.tl.set(s, { opacity: 0 }, 0);
      ctx.tl.fromTo(s, { opacity: 1, color: o.fresh || "#8a8a8a" }, { opacity: 1, color: o.ink || "#000", duration: 0.35, ease: "none", immediateRender: false }, t);
    });
    return t;
  };

  // ---------------------------------------------------------------- desktop look: window chrome + cursor
  AG2.win = function (parent, o) {
    var w = AG.el("div", "ag2-win", parent);
    w.style.cssText = "position:absolute;left:" + o.x + "px;top:" + o.y + "px;width:" + o.w + "px;height:" + o.h + "px;background:var(--face);z-index:" + (o.z || 10) + ";" +
      "box-shadow:inset -4px -4px 0 var(--dk), inset 4px 4px 0 var(--hi), inset -8px -8px 0 var(--lo), 14px 14px 0 rgba(0,0,0,0.28);padding:10px;display:flex;flex-direction:column;";
    var bar = AG.el("div", "", w);
    bar.style.cssText = "height:" + (o.barH || 62) + "px;flex:0 0 auto;background:linear-gradient(90deg, var(--title), var(--title2));display:flex;align-items:center;justify-content:space-between;padding:0 10px 0 18px;color:#fff;font-family:var(--f-hero);font-size:" + (o.barFont || 34) + "px;";
    var tt = AG.el("div", "", bar, (o.icon ? '<span style="display:inline-block;width:30px;height:30px;margin-right:14px;vertical-align:-3px;background:' + o.icon + ';box-shadow:inset -3px -3px 0 rgba(0,0,0,0.35)"></span>' : "") + AG.esc(o.title));
    tt.style.whiteSpace = "nowrap";
    var btns = AG.el("div", "", bar);
    btns.style.cssText = "display:flex;gap:6px";
    ["_", "□", "x"].forEach(function (c) {
      var b = AG.el("div", "", btns, c);
      b.style.cssText = "width:44px;height:40px;background:var(--face);color:#000;font-family:var(--f-small);font-weight:700;font-size:28px;display:flex;align-items:center;justify-content:center;box-shadow:inset -3px -3px 0 var(--dk), inset 3px 3px 0 var(--hi);";
    });
    var body = AG.el("div", "", w);
    body.style.cssText = "flex:1;position:relative;margin-top:8px;overflow:hidden;" + (o.well ? "background:#fff;box-shadow:inset 4px 4px 0 var(--lo), inset -4px -4px 0 var(--hi), inset 8px 8px 0 var(--dk);" : "");
    w.bar = bar; w.body = body; w.o = o;
    return w;
  };
  // Window opens the way the old OS did it: a dotted outline zooms from the source rect, then the window is there.
  AG2.winOpen = function (ctx, w, at, from) {
    var o = w.o, root = w.parentNode;
    var ol = AG.el("div", "", root);
    ol.style.cssText = "position:absolute;left:0;top:0;border:5px dotted #000;z-index:" + ((o.z || 10) + 1) + ";pointer-events:none;transform-origin:0 0;width:" + o.w + "px;height:" + o.h + "px;";
    ctx.tl.set(ol, { opacity: 0 }, 0);
    ctx.tl.set(ol, { opacity: 1 }, at);
    ctx.tl.fromTo(ol, { x: from[0], y: from[1], scaleX: from[2] / o.w, scaleY: from[3] / o.h }, { x: o.x, y: o.y, scaleX: 1, scaleY: 1, duration: 0.24, ease: "power2.out" }, at);
    ctx.tl.set(ol, { opacity: 0 }, at + 0.25);
    ctx.tl.set(w, { opacity: 0 }, 0);
    ctx.tl.set(w, { opacity: 1 }, at + 0.22);
    ctx.tl.fromTo(w, { scale: 0.985 }, { scale: 1, duration: 0.12, ease: "power2.out" }, at + 0.22);
  };
  // Pixel arrow cursor (adapted from the registry's simulated-cursor: same x/y + click-ring contract).
  AG2.cursor = function (ctx, parent, start) {
    var c = AG.el("div", "ag2-cursor", parent);
    c.style.cssText = "position:absolute;left:0;top:0;width:66px;height:96px;z-index:90;pointer-events:none;";
    c.innerHTML = '<svg viewBox="0 0 11 16" width="66" height="96" shape-rendering="crispEdges" style="filter:drop-shadow(4px 5px 0 rgba(0,0,0,0.35))"><path d="M0 0h1v1h1v1h1v1h1v1h1v1h1v1h1v1h1v1h1v1h1v1h-4v1h1v1h1v2h-2v-1h-1v-1h-1v-1h-1v1h-1v1h-1z" fill="#000"/><path d="M1 2h1v1h1v1h1v1h1v1h1v1h1v1h1v1h-3v1h1v1h1v1h-1v-1h-1v-1h-1v-1h-1v1h-1v1h-1z" fill="#fff"/></svg>';
    var ring = AG.el("div", "", c);
    ring.style.cssText = "position:absolute;left:-30px;top:-30px;width:60px;height:60px;border:5px solid #000;border-radius:50%;opacity:0;";
    ctx.tl.set(c, { x: start[0], y: start[1] }, 0);
    var api = {
      el: c,
      move: function (at, x, y, dur) { ctx.tl.to(c, { x: x, y: y, duration: dur || 0.5, ease: "power2.inOut" }, at); return api; },
      click: function (at) {
        ctx.tl.fromTo(c, { scale: 1 }, { scale: 0.88, duration: 0.07, ease: "power2.in", yoyo: true, repeat: 1, transformOrigin: "0 0", immediateRender: false }, at);
        ctx.tl.fromTo(ring, { opacity: 0.9, scale: 0.3 }, { opacity: 0, scale: 2.2, duration: 0.4, ease: "power2.out", immediateRender: false }, at);
        return api;
      },
    };
    return api;
  };
  // Button press in bevel language: raised -> sunk -> raised.
  AG2.bevelPress = function (ctx, el, at) {
    var up = "inset -4px -4px 0 #000, inset 4px 4px 0 #fff, inset -8px -8px 0 #7b7b7b", dn = "inset 4px 4px 0 #000, inset -4px -4px 0 #fff, inset 8px 8px 0 #7b7b7b";
    ctx.tl.set(el, { boxShadow: dn }, at);
    ctx.tl.set(el, { boxShadow: up }, at + 0.16);
  };

  // ---------------------------------------------------------------- caption engine (the six new looks)
  var CAP = { evidence: { max: 4, gap: 0.45 }, whitemodel: { max: 4, gap: 0.45 }, softui: { max: 4, gap: 0.4 }, desktop: { max: 4, gap: 0.45 }, chart: { max: 4, gap: 0.4 }, opsmap: { max: 4, gap: 0.45 } };
  // Balanced phrase grouping: split at clause punctuation or a pause first, then cut each clause into
  // near-equal cards (5 words at max 4 -> 3 + 2, never 4 + 1), so no card is one orphaned word and no
  // card straddles two clauses.
  AG2.group = function (words, max, gap) {
    var clauses = [], cur = [];
    words.forEach(function (w, i) {
      cur.push(w);
      var next = words[i + 1];
      if (!next || /[.!?,;:]$/.test(w.word) || next.brk || next.start - w.end > gap) { clauses.push(cur); cur = []; }
    });
    // a one-word clause joins its neighbour (the following one if it is short, else the previous)
    for (var i = 0; i < clauses.length; i++) if (clauses[i].length === 1 && clauses.length > 1) {
      var j = i + 1 < clauses.length && clauses[i + 1].length < max ? i + 1 : i - 1;
      if (j < 0) j = i + 1;
      if (j > i) clauses[j] = clauses[i].concat(clauses[j]); else clauses[j] = clauses[j].concat(clauses[i]);
      clauses.splice(i, 1); i--;
    }
    var cards = [];
    clauses.forEach(function (c) {
      var k = Math.ceil(c.length / max), base = Math.floor(c.length / k), extra = c.length % k, at = 0;
      for (var n = 0; n < k; n++) { var size = base + (n < extra ? 1 : 0); cards.push(c.slice(at, at + size)); at += size; }
    });
    return cards;
  };
  // Same grouping law as the base engine: a card is a whole phrase (sentence punctuation, a gap, or the
  // look's max words), never one orphaned word; the outgoing card is fully gone 0.07s before the next lands.
  AG2.captions = function (ctx, parent, words, o) {
    o = o || {};
    var look = ctx.look, tl = ctx.tl, cfg = CAP[look];
    var raw = words.segments || words.words || words;
    words = AG.normWords(words).map(function (w, i) { if (raw[i] && raw[i].brk) w.brk = true; return w; }).filter(function (w) { return (o.from === undefined || w.start >= o.from - 0.001) && (o.to === undefined || w.start < o.to); });
    var host = AG.el("div", "ag2-cap", parent);
    host.style.top = (o.top || 1300) + "px"; host.style.height = (o.height || 300) + "px";
    var cards = AG2.group(words, o.maxWords || cfg.max, cfg.gap);
    var GAP = 0.07;
    cards.forEach(function (c, ci) {
      var t0 = c[0].start, t1 = cards[ci + 1] ? cards[ci + 1][0].start : (o.to !== undefined ? o.to : c[c.length - 1].end + 0.8);
      var tin = Math.max(0, t0 - 0.06), tout = t1 - GAP;
      // an entrance must finish before the card's exit starts, or the word pops back after the exit (seen in r1)
      function fit(at, dur, exitLen) { return Math.max(0.04, Math.min(dur, tout - exitLen - at - 0.01)); }
      var card = AG.el("div", "ag2-card", host);
      (o.dark || []).forEach(function (r) { if (t0 >= r[0] && t0 < r[1]) card.classList.add("dark"); });
      tl.set(card, { opacity: 0 }, 0);
      tl.set(card, { opacity: 1 }, tin);
      var rot = AG.sh(ci, 41) * 1.6;
      if (look === "evidence") {
        var strip = AG.el("div", "strip", card); AG.el("div", "tape", strip);
        tl.fromTo(strip, { x: -160, rotation: rot - 4, opacity: 0 }, { x: 0, rotation: rot, opacity: 1, duration: 0.2, ease: "power3.out" }, tin);
        c.forEach(function (w, i) {
          var s = AG.el("span", "ag2-w" + (w.emph ? " emph" : ""), strip); s.textContent = w.word;
          // typed: the word strikes onto the paper as it is spoken
          tl.set(s, { opacity: 0 }, 0);
          // kit 1.0.0: opacity lives in BOTH vars (a from-only property is reverted by any backward seek past it)
          tl.fromTo(s, { opacity: 0.35, y: 4, scale: 1.05 }, { opacity: 1, y: 0, scale: 1, duration: 0.08, ease: "power2.out", immediateRender: false }, Math.max(tin, w.start - 0.03));
          if (w.emph) {
            var sv = AG.svg("svg", { viewBox: "0 0 100 60", preserveAspectRatio: "none" }, s);
            var pts = []; for (var k = 0; k <= 16; k++) { var a = -2.4 + (k / 16) * Math.PI * 2.15; pts.push([50 + Math.cos(a) * 47, 30 + Math.sin(a) * 26]); }
            var p = AG.stroke(sv, AG.wobblePath(pts, ci * 7 + i, 2.2), { color: "var(--accent)", w: 4 });
            p.setAttribute("vector-effect", "non-scaling-stroke");
            AG.drawOn(ctx, p, w.start + 0.06, 0.32, "power1.inOut");
          }
        });
        tl.to(strip, { y: -34, rotation: rot + 4, opacity: 0, duration: 0.16, ease: "power2.in" }, tout - 0.16);
      } else if (look === "whitemodel") {
        var plate = AG.el("div", "plate", card);
        tl.fromTo(plate, { scale: 0.94, opacity: 0 }, { scale: 1, opacity: 1, duration: 0.2, ease: "power3.out" }, tin);
        c.forEach(function (w, i) {
          var m = AG.el("span", "ag2-wm", plate), s = AG.el("span", "ag2-w" + (w.emph ? " emph" : ""), m); s.textContent = w.word;
          tl.fromTo(s, { yPercent: 105 }, { yPercent: 0, duration: fit(tin + i * 0.035, 0.28, 0.14), ease: "power3.out" }, tin + i * 0.035);
          if (w.emph) { var ul = AG.el("span", "ul", s); tl.fromTo(ul, { scaleX: 0 }, { scaleX: 1, duration: 0.24, ease: "power2.out" }, w.start + 0.04); }
        });
        tl.to(plate, { opacity: 0, y: -14, duration: 0.14, ease: "power1.in" }, tout - 0.14);
      } else if (look === "softui") {
        var row = AG.el("div", "row", card);
        c.forEach(function (w, i) {
          var s = AG.el("span", "ag2-w" + (w.emph ? " emph" : ""), row); s.textContent = w.word;
          var at = Math.max(tin, w.start - 0.05);
          tl.fromTo(s, { opacity: 0, scale: w.emph ? 0.4 : 0.7, y: 18 }, { opacity: 1, scale: 1, y: 0, duration: fit(at, w.emph ? 0.34 : 0.22, 0.14), ease: w.emph ? "back.out(2.4)" : "back.out(1.8)" }, at);
        });
        tl.to(row, { opacity: 0, scale: 0.94, duration: 0.14, ease: "power2.in" }, tout - 0.14);
      } else if (look === "desktop") {
        var tip = AG.el("div", "tip", card);
        c.forEach(function (w, i) {
          var s = AG.el("span", "ag2-w", tip), sel = AG.el("span", "sel", s);
          s.appendChild(document.createTextNode(w.word));
          var nxt = c[i + 1] ? c[i + 1].start : tout;
          tl.set(sel, { scaleX: 0 }, 0);
          tl.to(sel, { scaleX: 1, duration: 0.06, ease: "none" }, w.start - 0.02);
          tl.set(s, { color: "#fff" }, w.start + 0.02);
          tl.set(sel, { scaleX: 0 }, nxt - 0.02);
          tl.set(s, { color: w.emph ? "#c00000" : "#000" }, nxt - 0.02);
        });
        tl.fromTo(tip, { y: 10 }, { y: 0, duration: 0.1, ease: "power1.out" }, tin);
        tl.set(card, { opacity: 0 }, tout - 0.02);
      } else if (look === "chart") {
        var row2 = AG.el("div", "row", card);
        var spans = c.map(function (w) { var m = AG.el("span", "ag2-wm", row2), s = AG.el("span", "ag2-w" + (w.emph ? " emph" : ""), m); s.textContent = w.word; return s; });
        c.forEach(function (w, i) { var a0 = Math.max(tin, w.start - 0.06); tl.fromTo(spans[i], { yPercent: 108 }, { yPercent: 0, duration: fit(a0, 0.26, 0.17), ease: "expo.out" }, a0); });
        spans.forEach(function (s, i) { tl.to(s, { yPercent: 108, duration: 0.14, ease: "power2.in" }, tout - 0.16 + i * 0.01); });
      } else if (look === "opsmap") {
        var tape = AG.el("div", "tape", card);
        tl.fromTo(tape, { x: 220, opacity: 0 }, { x: 0, opacity: 1, duration: 0.2, ease: "power3.out" }, tin);
        c.forEach(function (w, i) {
          var s = AG.el("span", "ag2-w" + (w.emph ? " emph" : ""), tape);
          var chs = w.word.split("");
          var span = Math.min(0.26, Math.max(0.08, (w.end - w.start) * 0.8));
          chs.forEach(function (ch, j) {
            var cs = AG.el("span", "ch", s); cs.textContent = ch;
            tl.set(cs, { opacity: 1 }, Math.max(tin + 0.02, w.start - 0.04) + (j / chs.length) * span);
          });
          if (w.emph) {
            var sv2 = AG.svg("svg", { viewBox: "0 0 100 10", preserveAspectRatio: "none", style: "position:absolute;left:-4%;width:108%;bottom:-0.16em;height:0.22em;overflow:visible" }, s);
            var p2 = AG.stroke(sv2, AG.roughLine(2, 6, 98, 4, ci * 13 + i, 1.2, 2), { color: "var(--accent)", w: 6 });
            p2.setAttribute("vector-effect", "non-scaling-stroke");
            AG.drawOn(ctx, p2, w.start + 0.12, 0.22, "power1.out");
          }
        });
        tl.to(tape, { x: -260, opacity: 0, duration: 0.16, ease: "power2.in" }, tout - 0.16);
      }
    });
    return host;
  };

  // ---------------------------------------------------------------- CTA end card (the six new looks)
  // Same words and same beat as the base CTA: line lands, profile, button idles, press, flips to Following.
  AG2.cta = function (ctx, parent, o) {
    var tl = ctx.tl, look = ctx.look, at = o.at;
    var vars = (window.__hyperframes && window.__hyperframes.getVariables && window.__hyperframes.getVariables()) || {};
    var handle = vars.handle || o.handle || "@AGMM";
    var box = AG.el("div", "ag2-cta", parent);
    tl.set(box, { opacity: 0 }, 0);
    tl.set(box, { opacity: 1 }, at);
    var holder = box;
    if (look === "evidence" || look === "softui" || look === "opsmap") holder = AG.el("div", "card", box);
    if (look === "opsmap") AG.el("div", "hdr", holder, "<span>SIGNAL</span><span>PRIORITY: ROUTINE</span>");
    var line = AG.el("div", "line", holder);
    var parts = [["Follow for", ""], ["one real", ""], ["AI story", "emph"], ["a day", ""]];
    if (look === "desktop") parts = [["Follow for one", ""], ["real AI story", "emph"], ["a day", ""]];
    var pieces = parts.map(function (p) { var m = AG.el("span", "m", line); return AG.el("span", p[1], m, AG.esc(p[0])); });
    var prof = AG.el("div", "prof", holder);
    var av = AG.el("div", "av", prof, look === "evidence" ? "<b>AG</b>" : "AG");
    var hd = AG.el("div", "hd", prof, AG.esc(handle));
    var btn = AG.el("div", "btn", holder);
    var fill = look === "chart" ? AG.el("div", "fill", btn) : null;
    var ba = AG.el("div", "a", btn, look === "opsmap" || look === "evidence" || look === "desktop" ? "FOLLOW" : "Follow");
    var bb = AG.el("div", "b", btn, look === "opsmap" || look === "evidence" || look === "desktop" ? "FOLLOWING ✓" : "Following ✓");
    var pressAt = at + (o.pressDelay || 1.2);
    // entrance, per look
    var enter = {
      evidence: function (s, i) { tl.fromTo(s, { opacity: 0, y: 6 }, { opacity: 1, y: 0, duration: 0.06, ease: "none" }, at + i * 0.06); },
      whitemodel: function (s, i) { tl.fromTo(s, { yPercent: 105 }, { yPercent: 0, duration: 0.34, ease: "power3.out" }, at + i * 0.1); },
      softui: function (s, i) { tl.fromTo(s, { opacity: 0, scale: 0.6 }, { opacity: 1, scale: 1, duration: 0.3, ease: "back.out(2)" }, at + i * 0.07); },
      desktop: function (s, i) { tl.set(s, { opacity: 0 }, 0); tl.set(s, { opacity: 1 }, at + 0.05 + i * 0.08); },
      chart: function (s, i) { tl.fromTo(s, { yPercent: 108 }, { yPercent: 0, duration: 0.3, ease: "expo.out" }, at + i * 0.1); },
      opsmap: function (s, i) { tl.fromTo(s, { opacity: 0, x: -30 }, { opacity: 1, x: 0, duration: 0.16, ease: "power2.out" }, at + i * 0.06); },
    };
    pieces.forEach(function (s, i) { enter[look](s, i); });
    if (holder !== box) {
      if (look === "evidence") AG2.pinDrop(ctx, holder, at, { rot: -1.5 });
      else if (look === "softui") tl.fromTo(holder, { scale: 0.3, borderRadius: 400 }, { scale: 1, borderRadius: 64, duration: 0.42, ease: "back.out(1.4)" }, at);
      else tl.fromTo(holder, { y: 900, rotation: 4 }, { y: 0, rotation: -1, duration: 0.36, ease: "power3.out" }, at);
    }
    if (look === "evidence") {
      var em = holder.querySelector(".emph");
      var sv = AG.svg("svg", { viewBox: "0 0 100 60", preserveAspectRatio: "none", style: "position:absolute;left:-8%;top:-16%;width:116%;height:132%;overflow:visible" }, em);
      var pts = []; for (var k = 0; k <= 16; k++) { var a = -2.4 + (k / 16) * Math.PI * 2.15; pts.push([50 + Math.cos(a) * 48, 30 + Math.sin(a) * 27]); }
      var cp = AG.stroke(sv, AG.wobblePath(pts, 5, 2.2), { color: "var(--accent)", w: 7 }); cp.setAttribute("vector-effect", "non-scaling-stroke");
      AG.drawOn(ctx, cp, at + 0.85, 0.4, "power1.inOut");
    }
    tl.fromTo(prof, { opacity: 0, y: 26 }, { opacity: 1, y: 0, duration: 0.3, ease: "power3.out" }, at + 0.5);
    tl.fromTo(btn, { opacity: 0, scale: 0.85 }, { opacity: 1, scale: 1, duration: 0.26, ease: "back.out(2)" }, at + 0.65);
    tl.to(btn, { scale: 1.04, duration: 0.25, ease: "sine.inOut", yoyo: true, repeat: 1 }, at + 0.92);
    // press, per look
    tl.set(bb, { opacity: 0 }, 0);
    if (look === "desktop") {
      if (o.cursor) { o.cursor.move(at + 0.55, o.cursorAt[0], o.cursorAt[1], 0.6); o.cursor.click(pressAt); }
      tl.set(bb, { opacity: 1 }, pressAt + 0.02); tl.set(ba, { opacity: 0 }, pressAt + 0.02);
    } else if (look === "chart") {
      tl.fromTo(fill, { scaleX: 0 }, { scaleX: 1, duration: 0.4, ease: "power2.inOut" }, pressAt);
      tl.set(bb, { opacity: 1 }, pressAt + 0.3); tl.set(ba, { opacity: 0 }, pressAt + 0.3);
    } else if (look === "evidence" || look === "opsmap") {
      // a rubber stamp comes down on the button
      tl.to(btn, { scale: 0.9, duration: 0.07, ease: "power4.in" }, pressAt);
      tl.to(btn, { scale: 1, duration: 0.3, ease: "back.out(2)" }, pressAt + 0.07);
      tl.fromTo(bb, { opacity: 1, scale: 2.2, rotation: -10 }, { opacity: 1, scale: 1, rotation: -3, duration: 0.12, ease: "power4.in", immediateRender: false }, pressAt);
      tl.set(ba, { opacity: 0 }, pressAt + 0.12);
      AG.shake(ctx, holder, pressAt + 0.12, 12);
    } else {
      tl.to(btn, { scale: 0.92, duration: 0.08, ease: "power2.in" }, pressAt);
      tl.to(btn, { scale: 1, duration: 0.35, ease: "elastic.out(1.1, 0.45)" }, pressAt + 0.08);
      tl.fromTo(bb, { opacity: 1, clipPath: "circle(0% at 50% 50%)" }, { opacity: 1, clipPath: "circle(75% at 50% 50%)", duration: 0.35, ease: "power3.out", immediateRender: false }, pressAt + 0.02);
      tl.set(ba, { opacity: 0 }, pressAt + 0.38);
    }
    // after the press the card keeps living so the end card never freezes
    var tail = (o.end || at + 3) - (pressAt + 0.4);
    if (tail > 0.2) {
      tl.fromTo(holder, { y: 0 }, { y: -30, duration: tail, ease: "sine.inOut", immediateRender: false }, pressAt + 0.4);
      tl.fromTo(av, { scale: 1 }, { scale: 1.16, duration: 0.18, ease: "power2.out", yoyo: true, repeat: 1, immediateRender: false }, pressAt + 0.15);
    }
    return box;
  };
})();
