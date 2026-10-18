/* AGMM short-form kit lib v1.0.0 (kit/lib/ds/kit.js): the design-system r7 engine + pilot fixes consolidated
   (P2 balanced DP caption grouping + captionCards export, P3 w.brk phrase breaks + pencil grey #a39b8e + push
   darkening 0.88, P1 cardBreak, 1-4 words per caption card for every look per PRODUCTION-RULES).
   AGMM V2 short-form design system: shared component engine.
   One paused GSAP timeline per composition (ctx.tl). Every procedural effect
   (counters, boil, glitch jitter, grain, three.js sync) is a pure function of
   timeline time registered through AG.onFrame, so any frame renders the same
   pixels whenever it is sought. No Math.random, no clocks.

   Components (all styled per look by kit.css tokens, choreographed per look here):
     AG.captions   word-synced caption engine (word timing JSON, emphasis flags)
     AG.bigNumber  big-number counter
     AG.entity     named-entity card (photo/logo + name + role)
     AG.quote      quote card
     AG.compare    A vs B comparison (bars / dials / split)
     AG.checklist  "what to do" card
     AG.cta        end card with animated follow button
     AG.tx.*       transitions: glitch, whip, match, push
*/
(function () {
  "use strict";
  var AG = (window.AG = {});
  var NS = "http://www.w3.org/2000/svg";

  // ---------------------------------------------------------------- basics
  AG.hash = function (n, seed) {
    var x = Math.sin(n * 127.1 + (seed || 1) * 311.7) * 43758.5453;
    return x - Math.floor(x);
  };
  AG.sh = function (n, seed) { return AG.hash(n, seed) * 2 - 1; };
  AG.clamp = function (v, a, b) { return Math.max(a, Math.min(b, v)); };
  AG.el = function (tag, cls, parent, html) {
    var e = document.createElement(tag);
    if (cls) e.className = cls;
    if (html !== undefined) e.innerHTML = html;
    if (parent) parent.appendChild(e);
    return e;
  };
  AG.svg = function (tag, attrs, parent) {
    var e = document.createElementNS(NS, tag);
    for (var k in attrs) e.setAttribute(k, attrs[k]);
    if (parent) parent.appendChild(e);
    return e;
  };
  AG.esc = function (s) { return String(s).replace(/&/g, "&amp;").replace(/</g, "&lt;"); };

  AG.init = function (id) {
    var root = document.getElementById("root");
    var tl = gsap.timeline({ paused: true });
    var ctx = { tl: tl, root: root, look: root.getAttribute("data-look"), id: id, W: 1080, H: 1920, fps: 30, frames: [] };
    tl.eventCallback("onUpdate", function () {
      var t = tl.time();
      for (var i = 0; i < ctx.frames.length; i++) ctx.frames[i](t);
    });
    ctx.stage = root.querySelector(".ag-stage") || AG.el("div", "ag-stage", root);
    return ctx;
  };
  AG.onFrame = function (ctx, fn) { ctx.frames.push(fn); fn(0); };
  AG.finish = function (ctx, duration) {
    // pad the timeline to the full duration so late onFrame effects keep firing
    ctx.tl.set({}, {}, duration);
    return ctx.tl;
  };
  AG.ease = function (name) { return gsap.parseEase(name); };
  AG.prog = function (t, at, dur, ease) {
    var p = AG.clamp((t - at) / dur, 0, 1);
    return ease ? AG.ease(ease)(p) : p;
  };

  // A scene is a full-frame layer that the timeline shows between [from, to].
  AG.scene = function (ctx, id, from, to, opts) {
    opts = opts || {};
    var s = AG.el("div", "ag-scene", ctx.stage);
    s.id = ctx.id + "-" + id;
    var cam = AG.el("div", "ag-cam", s);
    // A scene that starts at 0 must never get an opacity-0 set at 0: two zero-duration sets at the
    // same instant resolve to the first one on the initial seek, which rendered frame 0 blank (r5/r6).
    if (from > 0) {
      ctx.tl.set(s, { opacity: 0 }, 0);
      ctx.tl.set(s, { opacity: 1 }, from);
    }
    if (to !== undefined && to !== null) ctx.tl.set(s, { opacity: 0 }, to);
    if (opts.drift !== false) AG.drift(ctx, cam, from, to || from + 4, opts.drift || {});
    s.cam = cam; s.from = from; s.to = to;
    return s;
  };
  // Continuous camera drift so no frame is ever a held still (scale + travel, sine.inOut).
  AG.drift = function (ctx, el, from, to, o) {
    var s0 = o.s0 !== undefined ? o.s0 : 1.0, s1 = o.s1 !== undefined ? o.s1 : 1.06;
    var x0 = o.x0 || 0, x1 = o.x1 || 0, y0 = o.y0 || 0, y1 = o.y1 !== undefined ? o.y1 : -24, r0 = o.r0 || 0, r1 = o.r1 || 0;
    ctx.tl.fromTo(el, { scale: s0, x: x0, y: y0, rotation: r0 }, { scale: s1, x: x1, y: y1, rotation: r1, duration: Math.max(0.1, to - from), ease: o.ease || "sine.inOut" }, from);
  };

  // Seek-safe animated grain: tile jumps to a seeded offset every frame.
  AG.grain = function (ctx, parent, opacity, blend) {
    var g = AG.el("div", "ag-grain", parent || ctx.root);
    g.style.opacity = opacity;
    if (blend) g.style.mixBlendMode = blend;
    AG.onFrame(ctx, function (t) {
      var f = Math.floor(t * 30);
      g.style.backgroundPosition = Math.floor(AG.hash(f, 3) * 384) + "px " + Math.floor(AG.hash(f, 9) * 384) + "px";
    });
    return g;
  };

  // Text split into masked words. Returns {el, words:[spans]}.
  AG.maskWords = function (parent, text, cls) {
    var out = [];
    String(text).split(/\s+/).filter(Boolean).forEach(function (w, i, arr) {
      var m = AG.el("span", "ag-wm", parent);
      var s = AG.el("span", "ag-w" + (cls ? " " + cls : ""), m);
      s.textContent = w;
      out.push(s);
      if (i < arr.length - 1) parent.appendChild(document.createTextNode(" "));
    });
    return out;
  };

  // Number formatting shared by every counter.
  AG.fmt = function (v, o) {
    o = o || {};
    var d = o.decimals || 0;
    var n = d ? v.toFixed(d) : String(Math.round(v));
    if (o.sep !== false) {
      var parts = n.split(".");
      parts[0] = parts[0].replace(/\B(?=(\d{3})+(?!\d))/g, ",");
      n = parts.join(".");
    }
    return (o.prefix || "") + n + (o.suffix || "");
  };
  AG.count = function (ctx, el, o) {
    var ease = AG.ease(o.ease || "power3.out");
    AG.onFrame(ctx, function (t) {
      var p = AG.clamp((t - o.at) / o.dur, 0, 1);
      var v = o.from + (o.to - o.from) * ease(p);
      el.textContent = AG.fmt(v, o);
    });
  };

  // Odometer reel: every digit rolls through a strip and lands on its final value, left to right.
  // Digits whose landing time is <= 0 are already settled on frame 0, so a hook frame can show
  // the magnitude immediately while the tail digits are still rolling.
  AG.reel = function (ctx, el, text, o) {
    o = o || {};
    var at = o.at || 0, stagger = o.stagger || 0.07, roll = o.roll || 0.55, cycles = o.cycles || 2;
    el.innerHTML = "";
    el.style.display = "inline-flex";
    var strips = [];
    var digitIdx = 0;
    String(text).split("").forEach(function (ch) {
      if (/[0-9]/.test(ch)) {
        var win = AG.el("span", "ag-reel-win", el);
        win.style.cssText = "display:inline-block;overflow:hidden;height:1em;line-height:1em;vertical-align:top;padding:0 0.01em";
        var strip = AG.el("span", "ag-reel-strip", win);
        strip.style.cssText = "display:flex;flex-direction:column";
        var d = +ch, seq = "";
        for (var k = 0; k <= cycles * 10 + d; k++) seq += '<span style="display:block;height:1em">' + (k % 10) + "</span>";
        strip.innerHTML = seq;
        strips.push({ s: strip, n: cycles * 10 + d, land: at + digitIdx * stagger });
        digitIdx++;
      } else {
        var c = AG.el("span", "", el, AG.esc(ch));
        c.style.cssText = "display:inline-block;height:1em;line-height:1em";
      }
    });
    var ease = AG.ease(o.ease || "power3.out");
    AG.onFrame(ctx, function (t) {
      for (var i = 0; i < strips.length; i++) {
        var p = ease(AG.clamp((t - (strips[i].land - roll)) / roll, 0, 1));
        strips[i].s.style.transform = "translateY(" + (-p * strips[i].n) + "em)";
      }
    });
    return strips;
  };

  // ---------------------------------------------------------------- hand-drawn helpers (explainer look)
  AG.wobblePath = function (pts, seed, amp, closed) {
    // pts: [[x,y],...] -> smooth quadratic chain with seeded wobble
    var p = pts.map(function (q, i) { return [q[0] + AG.sh(i * 7 + 1, seed) * amp, q[1] + AG.sh(i * 7 + 2, seed) * amp]; });
    var d = "M" + p[0][0].toFixed(1) + " " + p[0][1].toFixed(1);
    for (var i = 1; i < p.length - 1; i++) {
      var mx = (p[i][0] + p[i + 1][0]) / 2, my = (p[i][1] + p[i + 1][1]) / 2;
      d += " Q" + p[i][0].toFixed(1) + " " + p[i][1].toFixed(1) + " " + mx.toFixed(1) + " " + my.toFixed(1);
    }
    var last = p[p.length - 1];
    d += " L" + last[0].toFixed(1) + " " + last[1].toFixed(1);
    if (closed) d += " L" + (p[0][0] + 6).toFixed(1) + " " + (p[0][1] + 3).toFixed(1);
    return d;
  };
  AG.roughRect = function (w, h, seed, amp) {
    amp = amp === undefined ? 5 : amp;
    var pts = [], n = 5, i;
    for (i = 0; i <= n; i++) pts.push([(w * i) / n, 0]);
    for (i = 1; i <= n; i++) pts.push([w, (h * i) / n]);
    for (i = 1; i <= n; i++) pts.push([w - (w * i) / n, h]);
    for (i = 1; i <= n; i++) pts.push([0, h - (h * i) / n]);
    pts.push([w * 0.12, -2]);
    return AG.wobblePath(pts, seed, amp, false);
  };
  AG.roughLine = function (x1, y1, x2, y2, seed, amp, bow) {
    var pts = [], n = 6;
    for (var i = 0; i <= n; i++) {
      var f = i / n, b = Math.sin(f * Math.PI) * (bow || 0);
      var nx = -(y2 - y1), ny = x2 - x1, L = Math.hypot(nx, ny) || 1;
      pts.push([x1 + (x2 - x1) * f + (nx / L) * b, y1 + (y2 - y1) * f + (ny / L) * b]);
    }
    return AG.wobblePath(pts, seed, amp === undefined ? 3 : amp, false);
  };
  AG.stroke = function (svgEl, d, o) {
    o = o || {};
    var p = AG.svg("path", { d: d, fill: "none", "stroke-width": o.w || 6, "stroke-linecap": "round", "stroke-linejoin": "round", opacity: o.opacity || 1 }, svgEl);
    p.style.stroke = o.color || "var(--ink)";
    return p;
  };
  // Draw-on with a pen-like ease; length measured once at setup.
  AG.drawOn = function (ctx, path, at, dur, ease) {
    var L = path.getTotalLength() + 2;
    path.style.strokeDasharray = L + " " + L;
    if (at > 0) { ctx.tl.set(path, { opacity: 0 }, 0); ctx.tl.set(path, { opacity: 1 }, at); }
    ctx.tl.fromTo(path, { strokeDashoffset: L }, { strokeDashoffset: 0, duration: dur, ease: ease || "power2.inOut" }, at);
    return L;
  };
  // Boil: hand-drawn jitter re-posed every 3 frames (on twos-and-threes, like cel animation).
  AG.boil = function (ctx, els, amp, rot, seed) {
    els = [].concat(els);
    AG.onFrame(ctx, function (t) {
      var step = Math.floor((t * 30) / 3);
      for (var i = 0; i < els.length; i++) {
        els[i].style.transform = "translate(" + (AG.sh(step * 3 + i * 97, seed || 1) * amp).toFixed(2) + "px," + (AG.sh(step * 3 + 1 + i * 97, seed || 1) * amp).toFixed(2) + "px) rotate(" + (AG.sh(step * 3 + 2 + i * 97, seed || 1) * rot).toFixed(3) + "deg)";
      }
    });
  };
  AG.arrow = function (svgEl, x1, y1, x2, y2, seed, o) {
    o = o || {};
    var g = AG.svg("g", {}, svgEl);
    var shaft = AG.stroke(g, AG.roughLine(x1, y1, x2, y2, seed, 2.5, o.bow || 30), o);
    var a = Math.atan2(y2 - y1, x2 - x1) + (o.bow ? -0.25 : 0), hl = o.head || 34;
    var h1 = [x2 - Math.cos(a - 0.5) * hl, y2 - Math.sin(a - 0.5) * hl], h2 = [x2 - Math.cos(a + 0.5) * hl, y2 - Math.sin(a + 0.5) * hl];
    var head = AG.stroke(g, "M" + h1[0].toFixed(1) + " " + h1[1].toFixed(1) + " L" + x2 + " " + y2 + " L" + h2[0].toFixed(1) + " " + h2[1].toFixed(1), o);
    return { g: g, shaft: shaft, head: head };
  };
  AG.drawArrow = function (ctx, ar, at, dur) {
    AG.drawOn(ctx, ar.shaft, at, dur, "power2.inOut");
    AG.drawOn(ctx, ar.head, at + dur * 0.92, 0.14, "power1.out");
  };

  // ---------------------------------------------------------------- caption engine
  // words: [{word, start, end, emph?}]  (Voxtral segments {text,start,end} also accepted)
  AG.normWords = function (words) {
    var arr = words.segments || words.words || words;
    return arr.map(function (w) {
      return { word: String(w.word || w.text || "").trim(), start: +w.start, end: +w.end, emph: !!(w.emph || w.emphasis), brk: w.brk, cardBreak: !!w.cardBreak };
    }).filter(function (w) { return w.word; });
  };
  // P2 fix (caption collisions / orphan words): split at clause punctuation or a pause first, then cut each
  // clause into BALANCED chunks (7 words -> 4+3, never 3+3+1), capped by characters so a card never wraps past
  // two lines, then fold any remaining one-word clause into its neighbour when the pause between them is short.
  AG.groupWords = function (words, maxWords, maxGap, maxChars) {
    maxChars = maxChars || 26;
    function chars(a) { return a.reduce(function (n, w) { return n + w.word.length + 1; }, -1); }
    var clauses = [], cur = [];
    words.forEach(function (w, i) {
      cur.push(w);
      var next = words[i + 1];
      var gap = next ? next.start - w.end : 99;
      if (/[.!?,;:]$/.test(w.word) || gap > maxGap || !next || next.cardBreak) { clauses.push(cur); cur = []; }
    });
    // fold one-word clauses into a neighbour (prefer the following clause) when it fits and the pause is short
    for (var i = 0; i < clauses.length; i++) {
      if (clauses[i].length !== 1) continue;
      var w = clauses[i][0], nx = clauses[i + 1], pv = clauses[i - 1];
      if (nx && nx[0].start - w.end < 0.6 && !/[.!?]$/.test(w.word) && chars(nx) + w.word.length + 1 <= maxChars * 2) { clauses[i + 1] = [w].concat(nx); clauses.splice(i, 1); i--; }
      else if (pv && w.start - pv[pv.length - 1].end < 0.6 && !/[.!?]$/.test(pv[pv.length - 1].word) && pv.length < maxWords * 2) { pv.push(w); clauses.splice(i, 1); i--; }
    }
    // cut each clause with a small DP: fewest cards, no one-word cards, never end a card on a function word,
    // prefer cutting where the voice pauses
    var STOP = /^(a|an|the|of|on|in|to|at|by|for|and|or|is|was|were|it|its|it's|that|their|your|our|how|what|as|so)$/i;
    var cards = [];
    clauses.forEach(function (c) {
      var n = c.length, best = [0], back = [0];
      for (var j = 1; j <= n; j++) {
        best[j] = Infinity;
        for (var i2 = Math.max(0, j - maxWords); i2 < j; i2++) {
          var ch = c.slice(i2, j), len = chars(ch);
          if (len > maxChars && ch.length > 1) continue;
          var cost = 100 + (ch.length === 1 && n > 1 ? 400 : 0) + (j < n && STOP.test(ch[ch.length - 1].word.replace(/[^A-Za-z']/g, "")) ? 160 : 0);
          if (j < n) cost -= Math.min(0.5, c[j].start - ch[ch.length - 1].end) * 200;
          cost += Math.abs(len - 16) * 2;
          if (best[i2] + cost < best[j]) { best[j] = best[i2] + cost; back[j] = i2; }
        }
      }
      var cuts = [], j2 = n;
      while (j2 > 0) { cuts.unshift([back[j2], j2]); j2 = back[j2]; }
      cuts.forEach(function (r) { cards.push(c.slice(r[0], r[1])); });
    });
    return cards;
  };
  var CAP = {
    dossier: { max: 4, gap: 0.45, chars: 24 },
    newsroom: { max: 4, gap: 0.35, chars: 26 },
    explainer: { max: 4, gap: 0.45, chars: 26 },
    cinematic: { max: 4, gap: 0.5, chars: 26 },
  };
  // Phrase-first captions: a card always shows its whole phrase (or its whole bridge line), never
  // a lone orphan word; the spoken word is marked by the look's own emphasis mechanic. The outgoing
  // card has fully cleared 0.07s before the next one lands, so two phrases never overprint.
  AG.captions = function (ctx, parent, words, o) {
    o = o || {};
    var look = ctx.look, tl = ctx.tl, cfg = CAP[look];
    words = AG.normWords(words).filter(function (w) { return (o.from === undefined || w.start >= o.from - 0.001) && (o.to === undefined || w.start < o.to); });
    var host = AG.el("div", "ag-cap-host pos-" + (o.pos || "lower"), parent);
    if (o.top !== undefined) { host.style.top = o.top + "px"; host.style.bottom = "auto"; host.style.height = (o.height || 500) + "px"; }
    // P3: explicit phrase breaks (w.brk) win over the heuristic
    var cards;
    if (words.some(function (w) { return w.brk !== undefined; })) {
      cards = []; var cur0 = [];
      words.forEach(function (w, i) { cur0.push(w); if (w.brk || i === words.length - 1) { cards.push(cur0); cur0 = []; } });
    } else cards = AG.groupWords(words, o.maxWords || cfg.max, cfg.gap, o.maxChars || cfg.chars);
    ctx.captionCards = (ctx.captionCards || []).concat(cards.map(function (c) { return { start: c[0].start, end: c[c.length - 1].end, text: c.map(function (w) { return w.word; }).join(' ') }; }));
    var GAP = 0.07;
    cards.forEach(function (c, ci) {
      var t0 = c[0].start, lastEnd = c[c.length - 1].end;
      var t1 = cards[ci + 1] ? cards[ci + 1][0].start : o.to !== undefined ? o.to : lastEnd + 0.8;
      var isLast = ci === cards.length - 1;
      var card = AG.el("div", "ag-card", host);
      var tin = Math.max(0, t0 - 0.06);
      if (tin > 0) { tl.set(card, { opacity: 0 }, 0); tl.set(card, { opacity: 1 }, tin); }
      var spans = [];
      if (look === "dossier") {
        // strict hierarchy: emphasised words get their own huge line; bridge words ride together as one small line
        var lines = [], line = null, lineBig = null;
        c.forEach(function (w) {
          var big = w.emph;
          if (!line || lineBig !== big || big) { line = AG.el("div", "ag-line " + (big ? "big" : "small"), card); lineBig = big; lines.push({ el: line, big: big, words: [] }); }
          var m = AG.el("span", "ag-wm", line), s = AG.el("span", "ag-w" + (w.emph ? " emph" : ""), m);
          s.textContent = w.word; spans.push(s); lines[lines.length - 1].words.push({ w: w, s: s });
        });
        lines.forEach(function (L) {
          if (L.big) {
            var q = L.words[0];
            tl.fromTo(q.s, { yPercent: 108, rotation: 5, transformOrigin: "0% 100%" }, { yPercent: 0, rotation: 0, duration: 0.42, ease: "expo.out" }, q.w.start - 0.05);
            tl.fromTo(q.s, { scale: 1.12 }, { scale: 1, duration: 0.6, ease: "power3.out" }, q.w.start - 0.05);
          } else {
            var ls = L.words[0].w.start - 0.05;
            L.words.forEach(function (q, k) { tl.fromTo(q.s, { yPercent: 110 }, { yPercent: 0, duration: 0.3, ease: "expo.out" }, ls + k * 0.035); });
          }
        });
        if (!isLast || !o.keepLast) tl.to(card, { y: -46, opacity: 0, duration: 0.16, ease: "power2.in" }, t1 - GAP - 0.16);
      } else if (look === "newsroom") {
        var ln = AG.el("div", "ag-line", card);
        c.forEach(function (w) {
          var s = AG.el("span", "ag-w" + (w.emph ? " emph" : ""), ln);
          var box = AG.el("span", "ag-hlbox", s);
          s.appendChild(document.createTextNode(w.word.toUpperCase()));
          spans.push(s); s.box = box;
        });
        tl.fromTo(card, { scale: 0.72, rotation: -2 }, { scale: 1, rotation: 0, duration: 0.2, ease: "back.out(2.6)" }, tin);
        var SH = "0 5px 0 #000, 0 -3px 0 #000, 4px 0 0 #000, -4px 0 0 #000, 5px 5px 0 #000, -5px 5px 0 #000";
        c.forEach(function (w, i) {
          var s = spans[i], nextStart = c[i + 1] ? c[i + 1].start : t1;
          tl.set(s.box, { scaleX: 0 }, 0);
          tl.to(s.box, { scaleX: 1, duration: 0.08, ease: "power2.out" }, w.start - 0.02);
          tl.set(s, { color: "#0d0d0d", textShadow: "none" }, w.start + 0.05);
          tl.set(s.box, { scaleX: 0 }, nextStart - 0.02);
          tl.set(s, { color: w.emph ? "#ffd400" : "#ffffff", textShadow: SH }, nextStart - 0.02);
        });
        tl.set(card, { opacity: 0 }, t1 - GAP - 0.02);
      } else if (look === "explainer") {
        // the whole phrase is on the paper at once in pencil grey; each word inks in as it is spoken
        var le = AG.el("div", "ag-line", card);
        c.forEach(function (w, i) {
          var s = AG.el("span", "ag-w" + (w.emph ? " emph" : ""), le);
          s.textContent = w.word; spans.push(s);
          tl.fromTo(s, { opacity: 0, y: 16 }, { opacity: 1, y: 0, duration: 0.22, ease: "power2.out" }, tin + i * 0.03);
          tl.fromTo(s, { color: "#a39b8e" }, { color: w.emph ? "#2b59ff" : "#1d1b18", duration: 0.12, ease: "none" }, w.start - 0.02);
          if (w.emph) {
            var sv = AG.svg("svg", { class: "ag-under", viewBox: "0 0 100 20", preserveAspectRatio: "none" }, s);
            var p = AG.stroke(sv, AG.roughLine(2, 12, 98, 9, ci * 11 + i, 1.4, 3), { color: "var(--accent)", w: 5 });
            AG.drawOn(ctx, p, w.start + 0.08, 0.3, "power1.inOut");
          }
        });
        if (!isLast || !o.keepLast) tl.to(card, { opacity: 0, y: -20, duration: 0.14, ease: "power1.in" }, t1 - GAP - 0.14);
      } else {
        var lc = AG.el("div", "ag-line", card);
        c.forEach(function (w, i) {
          var s = AG.el("span", "ag-w" + (w.emph ? " emph" : ""), lc);
          s.textContent = w.word; spans.push(s);
          tl.fromTo(s, { opacity: 0, filter: "blur(10px)", y: 10 }, { opacity: 1, filter: "blur(0px)", y: 0, duration: 0.45, ease: "sine.out" }, tin + i * 0.05);
        });
        if (!isLast || !o.keepLast) tl.to(card, { opacity: 0, filter: "blur(6px)", duration: 0.25, ease: "sine.in" }, t1 - GAP - 0.25);
      }
    });
    return host;
  };

  // ---------------------------------------------------------------- big number
  AG.bigNumber = function (ctx, parent, o) {
    var tl = ctx.tl, look = ctx.look;
    var box = AG.el("div", "ag-num", parent);
    box.style.top = (o.top || 700) + "px";
    var kick = o.kicker ? AG.el("div", "ag-num-kicker", box) : null;
    if (kick) kick.textContent = o.kicker;
    var valM = AG.el("div", "ag-mask", box);
    var val = AG.el("div", "ag-num-val ag-in", valM);
    if (o.size) val.style.fontSize = o.size + "px";
    var rule = AG.el("div", "ag-num-rule", box);
    var lab = o.label ? AG.el("div", "ag-num-label", box) : null;
    if (lab) lab.textContent = o.label;
    var at = o.at, dur = o.dur || 1.2;
    AG.count(ctx, val, { at: at, dur: dur, from: o.from || 0, to: o.to, prefix: o.prefix, suffix: o.suffix, decimals: o.decimals, ease: o.ease || (look === "cinematic" ? "power1.inOut" : "expo.out") });
    tl.set(box, { opacity: 0 }, 0);
    tl.set(box, { opacity: 1 }, at - 0.1);
    if (look === "dossier") {
      if (kick) tl.fromTo(kick, { opacity: 0, x: -30 }, { opacity: 1, x: 0, duration: 0.3, ease: "power3.out" }, at - 0.1);
      tl.fromTo(val, { yPercent: 100 }, { yPercent: 0, duration: 0.45, ease: "expo.out" }, at - 0.1);
      tl.fromTo(val, { letterSpacing: "0.04em" }, { letterSpacing: "-0.045em", duration: dur, ease: "power3.out" }, at - 0.1);
      tl.fromTo(rule, { scaleX: 0 }, { scaleX: 1, duration: dur, ease: "expo.out" }, at);
      tl.fromTo(val, { color: "#3ce37a" }, { color: "#f3f3ef", duration: 0.5, ease: "power1.out" }, at + dur);
      if (lab) tl.fromTo(lab, { opacity: 0, y: 24 }, { opacity: 1, y: 0, duration: 0.3, ease: "power3.out" }, at + dur * 0.5);
    } else if (look === "newsroom") {
      tl.fromTo(val, { scale: 2.4, rotation: -6 }, { scale: 1, rotation: 0, duration: 0.24, ease: "back.out(1.6)" }, at - 0.1);
      AG.shake(ctx, box, at + 0.14, 16);
      if (lab) tl.fromTo(lab, { scaleX: 0, transformOrigin: "0% 50%" }, { scaleX: 1, duration: 0.18, ease: "power3.out" }, at + 0.2);
    } else if (look === "explainer") {
      tl.fromTo(val, { opacity: 0, y: 30 }, { opacity: 1, y: 0, duration: 0.3, ease: "back.out(2)" }, at - 0.1);
      var sv = AG.svg("svg", { width: 760, height: 330, viewBox: "0 0 760 330", style: "position:absolute;left:50%;margin-left:-380px;top:" + (kick ? 20 : -40) + "px;overflow:visible" }, box);
      var pts = [];
      for (var i = 0; i <= 18; i++) { var a = -2.2 + (i / 18) * Math.PI * 2.12; pts.push([380 + Math.cos(a) * 350, 165 + Math.sin(a) * 140]); }
      var circ = AG.stroke(sv, AG.wobblePath(pts, 5, 6), { color: "var(--accent)", w: 7 });
      AG.drawOn(ctx, circ, at + dur * 0.6, 0.6, "power1.inOut");
      AG.boil(ctx, sv, 1.6, 0.4, 4);
      if (lab) tl.fromTo(lab, { opacity: 0, rotation: -3 }, { opacity: 1, rotation: 0, duration: 0.3, ease: "power2.out" }, at + dur * 0.5);
    } else {
      if (kick) tl.fromTo(kick, { opacity: 0, letterSpacing: "0.5em" }, { opacity: 1, letterSpacing: "0.22em", duration: 1.2, ease: "sine.out" }, at - 0.1);
      tl.fromTo(val, { opacity: 0, filter: "blur(16px)", scale: 1.06 }, { opacity: 1, filter: "blur(0px)", scale: 1, duration: 0.9, ease: "sine.out" }, at - 0.1);
      if (lab) tl.fromTo(lab, { opacity: 0 }, { opacity: 1, duration: 0.8, ease: "sine.out" }, at + 0.4);
    }
    if (o.out) tl.to(box, { opacity: 0, y: -40, duration: 0.25, ease: "power2.in" }, o.out - 0.25);
    box.val = val;
    return box;
  };

  // Deterministic three-to-six-frame landing shake.
  AG.shake = function (ctx, el, at, amp) {
    var n = 6;
    for (var i = 0; i < n; i++) {
      var k = 1 - i / n;
      ctx.tl.set(el, { x: AG.sh(i, 11) * amp * k, y: AG.sh(i, 23) * amp * k }, at + i / 30);
    }
    ctx.tl.set(el, { x: 0, y: 0 }, at + n / 30);
  };

  // ---------------------------------------------------------------- entity card
  AG.entity = function (ctx, parent, o) {
    var tl = ctx.tl, look = ctx.look, at = o.at;
    var box = AG.el("div", "ag-entity", parent);
    if (o.top !== undefined) box.style.top = o.top + "px";
    if (o.bottom !== undefined) box.style.bottom = o.bottom + "px";
    tl.set(box, { opacity: 0 }, 0);
    tl.set(box, { opacity: 1 }, at);
    if (look === "dossier") {
      var imgW = AG.el("div", "ag-e-img", box);
      if (o.img) AG.el("img", "", imgW).src = o.img;
      else { imgW.style.display = "flex"; imgW.style.alignItems = "center"; imgW.style.justifyContent = "center"; imgW.innerHTML = '<span style="font-family:var(--f-hero);font-weight:900;font-size:120px">' + AG.esc(o.mono || o.name[0]) + "</span>"; }
      var scan = AG.el("div", "", imgW); scan.style.cssText = "position:absolute;left:0;right:0;height:6px;background:var(--accent);top:0";
      var txt = AG.el("div", "", box);
      var k = o.kicker ? AG.el("div", "ag-e-kicker", txt, AG.esc(o.kicker)) : null;
      var nm = AG.el("div", "ag-mask", txt); var nmi = AG.el("div", "ag-e-name ag-in", nm, AG.esc(o.name));
      var rl = AG.el("div", "ag-e-role", txt, AG.esc(o.role || ""));
      tl.fromTo(imgW, { clipPath: "inset(0 0 100% 0)" }, { clipPath: "inset(0 0 0% 0)", duration: 0.45, ease: "expo.out" }, at);
      tl.fromTo(scan, { y: 0 }, { y: 244, duration: 0.8, ease: "power2.inOut" }, at);
      tl.to(scan, { opacity: 0, duration: 0.2 }, at + 0.8);
      if (k) tl.fromTo(k, { opacity: 0, x: -20 }, { opacity: 1, x: 0, duration: 0.3, ease: "power3.out" }, at + 0.08);
      tl.fromTo(nmi, { yPercent: 105 }, { yPercent: 0, duration: 0.42, ease: "expo.out" }, at + 0.12);
      tl.fromTo(rl, { opacity: 0, y: 16 }, { opacity: 1, y: 0, duration: 0.3, ease: "power3.out" }, at + 0.3);
      if (o.img) tl.fromTo(imgW.querySelector("img"), { scale: 1.25 }, { scale: 1.02, duration: 2.4, ease: "power2.out" }, at);
    } else if (look === "newsroom") {
      var ph = o.img ? AG.el("div", "ag-e-img", box) : null;
      if (ph) { AG.el("img", "", ph).src = o.img; if (o.imgBottom !== undefined) ph.style.bottom = o.imgBottom + "px"; }
      var tag = AG.el("div", "ag-e-tag", box);
      var kk = o.kicker ? AG.el("div", "ag-e-kicker", tag, AG.esc(o.kicker)) : null;
      var nn = AG.el("div", "ag-e-name", tag, AG.esc(o.name));
      var rr = AG.el("div", "ag-e-role", tag, AG.esc(o.role || ""));
      if (ph) {
        tl.fromTo(ph, { scale: 0.3, rotation: -14, y: 200 }, { scale: 1, rotation: -3, y: 0, duration: 0.32, ease: "back.out(1.8)" }, at);
        tl.to(ph, { rotation: 2, y: -18, duration: 2.6, ease: "sine.inOut" }, at + 0.32);
      }
      if (kk) tl.fromTo(kk, { xPercent: -110 }, { xPercent: 0, duration: 0.18, ease: "power4.out" }, at + 0.1);
      tl.fromTo(nn, { xPercent: -104 }, { xPercent: 0, duration: 0.2, ease: "power4.out" }, at + 0.16);
      tl.fromTo(rr, { xPercent: -104 }, { xPercent: 0, duration: 0.2, ease: "power4.out" }, at + 0.24);
      tag.style.overflow = "visible";
    } else if (look === "explainer") {
      var cardE = AG.el("div", "ag-e-card", box);
      var fr = AG.svg("svg", { class: "ag-frame", viewBox: "0 0 880 420", preserveAspectRatio: "none" }, cardE);
      var fp = AG.stroke(fr, AG.roughRect(880, 420, 7, 5), { w: 6 });
      fp.setAttribute("vector-effect", "non-scaling-stroke");
      var ek = o.kicker ? AG.el("div", "ag-e-kicker", cardE, AG.esc(o.kicker)) : null;
      var row = AG.el("div", "ag-e-row", cardE);
      var mono = AG.el("div", "ag-e-mono", row, AG.esc(o.mono || o.name[0]));
      if (o.img) { mono.innerHTML = ""; var im = AG.el("img", "", mono); im.src = o.img; im.style.cssText = "width:100%;height:100%;object-fit:cover;border-radius:50%"; }
      var col = AG.el("div", "", row);
      var en = AG.el("div", "ag-e-name", col, AG.esc(o.name));
      var er = AG.el("div", "ag-e-role", col, AG.esc(o.role || ""));
      tl.fromTo(cardE, { rotation: -4, y: 60, opacity: 0 }, { rotation: -1.2, y: 0, opacity: 1, duration: 0.45, ease: "back.out(1.6)" }, at);
      AG.drawOn(ctx, fp, at + 0.05, 0.7, "power1.inOut");
      tl.fromTo(mono, { scale: 0 }, { scale: 1, duration: 0.4, ease: "back.out(2.2)" }, at + 0.25);
      if (ek) tl.fromTo(ek, { opacity: 0, x: -20 }, { opacity: 1, x: 0, duration: 0.3 }, at + 0.2);
      tl.fromTo(en, { opacity: 0, x: 30 }, { opacity: 1, x: 0, duration: 0.35, ease: "power3.out" }, at + 0.35);
      tl.fromTo(er, { opacity: 0 }, { opacity: 1, duration: 0.3 }, at + 0.5);
      AG.boil(ctx, fr, 1.4, 0.3, 12);
    } else {
      var ck = AG.el("div", "ag-e-kicker", box, (o.kicker ? '<span class="ag-e-dot"></span>' + AG.esc(o.kicker) : ""));
      var rule = AG.el("div", "ag-e-rule", box);
      var cn = AG.el("div", "ag-mask", box); var cni = AG.el("div", "ag-e-name ag-in", cn, AG.esc(o.name));
      var cr = AG.el("div", "ag-e-role", box, AG.esc(o.role || ""));
      tl.fromTo(ck, { opacity: 0, letterSpacing: "0.4em" }, { opacity: 0.9, letterSpacing: "0.22em", duration: 1.0, ease: "sine.out" }, at);
      tl.fromTo(rule, { scaleX: 0 }, { scaleX: 1, duration: 1.1, ease: "power2.inOut" }, at + 0.1);
      tl.fromTo(cni, { yPercent: 100, opacity: 0 }, { yPercent: 0, opacity: 1, duration: 0.9, ease: "power3.out" }, at + 0.3);
      tl.fromTo(cr, { opacity: 0 }, { opacity: 1, duration: 0.8, ease: "sine.out" }, at + 0.7);
    }
    if (o.out) tl.to(box, { opacity: 0, duration: look === "cinematic" ? 0.5 : 0.2, ease: "power1.in" }, o.out - (look === "cinematic" ? 0.5 : 0.2));
    return box;
  };

  // ---------------------------------------------------------------- quote card
  AG.quote = function (ctx, parent, o) {
    var tl = ctx.tl, look = ctx.look, at = o.at;
    var box = AG.el("div", "ag-quote", parent);
    box.style.top = (o.top || 560) + "px";
    tl.set(box, { opacity: 0 }, 0);
    tl.set(box, { opacity: 1 }, at);
    var emph = (o.emph || []).map(function (s) { return s.toLowerCase(); });
    var inner = box;
    if (look === "newsroom") {
      AG.el("div", "ag-q-src", box, "<span>" + AG.esc(o.source || "") + "</span><span>" + AG.esc(o.date || "") + "</span>");
    }
    if (look === "explainer") {
      inner = AG.el("div", "ag-q-bubble", box);
      var fr = AG.svg("svg", { class: "ag-frame", viewBox: "0 0 900 520", preserveAspectRatio: "none" }, inner);
      var d = AG.roughRect(900, 520, 21, 6) + " M120 520 L96 600 L210 522";
      var fp = AG.stroke(fr, d, { w: 6 }); fp.setAttribute("vector-effect", "non-scaling-stroke");
      AG.drawOn(ctx, fp, at, 0.8, "power1.inOut");
      AG.boil(ctx, fr, 1.3, 0.25, 21);
    }
    var mark = AG.el("div", "ag-q-mark", inner, "“");
    var text = AG.el("div", "ag-q-text", inner);
    var words = String(o.text).split(/\s+/);
    var spans = words.map(function (w, i) {
      var clean = w.toLowerCase().replace(/[^a-z0-9%$']/g, "");
      var isE = emph.indexOf(clean) >= 0;
      var s;
      if (look === "dossier") { var m = AG.el("span", "ag-wm", text); s = AG.el("span", "ag-w" + (isE ? " emph" : ""), m); s.textContent = w; }
      else { s = AG.el("span", "ag-w" + (isE ? " emph" : ""), text); s.textContent = w; if (look === "newsroom" && isE) { var mk = AG.el("span", "ag-mk", s); s.insertBefore(mk, s.firstChild); s.mk = mk; } }
      if (i < words.length - 1) text.appendChild(document.createTextNode(" "));
      s.isE = isE;
      return s;
    });
    var by = o.by ? AG.el("div", "ag-q-by", inner, AG.esc(o.by)) : null;
    var step = o.step || (look === "cinematic" ? 0.16 : 0.09);
    if (look === "dossier") {
      tl.fromTo(mark, { scale: 0, rotation: -20 }, { scale: 1, rotation: 0, duration: 0.4, ease: "back.out(2)", transformOrigin: "0% 100%" }, at);
      spans.forEach(function (s, i) { tl.fromTo(s, { yPercent: 108 }, { yPercent: 0, duration: 0.34, ease: "expo.out" }, at + 0.15 + i * step); });
    } else if (look === "newsroom") {
      tl.fromTo(box, { rotation: 8, scale: 0.4, y: 300 }, { rotation: -1.5, scale: 1, y: 0, duration: 0.3, ease: "back.out(1.5)" }, at);
      tl.to(box, { rotation: 0.8, duration: 3, ease: "sine.inOut" }, at + 0.3);
      spans.forEach(function (s, i) { if (s.mk) { tl.set(s.mk, { scaleX: 0 }, 0); tl.to(s.mk, { scaleX: 1, duration: 0.22, ease: "power2.out" }, at + 0.45 + i * 0.05); } });
    } else if (look === "explainer") {
      tl.fromTo(inner, { scale: 0.85, rotation: 2, opacity: 0 }, { scale: 1, rotation: -0.8, opacity: 1, duration: 0.4, ease: "back.out(1.8)" }, at);
      spans.forEach(function (s, i) { tl.fromTo(s, { opacity: 0 }, { opacity: 1, duration: 0.05 }, at + 0.3 + i * step); });
    } else {
      spans.forEach(function (s, i) { tl.fromTo(s, { opacity: 0, filter: "blur(12px)" }, { opacity: 1, filter: "blur(0px)", duration: 0.7, ease: "sine.out" }, at + i * step); });
    }
    if (by) tl.fromTo(by, { opacity: 0, y: 14 }, { opacity: 1, y: 0, duration: 0.4, ease: "power2.out" }, at + 0.3 + spans.length * step);
    if (o.out) tl.to(box, { opacity: 0, duration: 0.25, ease: "power1.in" }, o.out - 0.25);
    return box;
  };

  // ---------------------------------------------------------------- comparison
  AG.compare = function (ctx, parent, o) {
    var tl = ctx.tl, look = ctx.look, at = o.at;
    var box = AG.el("div", "ag-cmp", parent);
    box.style.top = (o.top || 520) + "px";
    tl.set(box, { opacity: 0 }, 0);
    tl.set(box, { opacity: 1 }, at);
    var title = o.title ? AG.el("div", "ag-c-title", box, AG.esc(o.title)) : null;
    var cols = AG.el("div", "ag-c-cols", box);
    var items = [o.a, o.b];
    var maxV = Math.max(o.a.value, o.b.value, o.max || 0);
    var labelsRow = look === "newsroom" ? null : null;
    var built = items.map(function (it, i) {
      if (look === "cinematic" && i === 1) AG.el("div", "ag-c-div", cols);
      var col = AG.el("div", "ag-c-col" + ((o.winner === "a" && i === 0) || (o.winner === "b" && i === 1) ? " win" : ""), cols);
      var r = { col: col };
      if (look === "explainer") {
        var sv = AG.svg("svg", { class: "ag-dial", viewBox: "0 0 420 280" }, col);
        var arcPts = []; for (var k = 0; k <= 16; k++) { var a = Math.PI + (k / 16) * Math.PI; arcPts.push([210 + Math.cos(a) * 180, 230 + Math.sin(a) * 180]); }
        r.arc = AG.stroke(sv, AG.wobblePath(arcPts, 30 + i, 3), { w: 7 });
        for (var tk = 0; tk <= 4; tk++) { var ta = Math.PI + (tk / 4) * Math.PI; r["t" + tk] = AG.stroke(sv, "M" + (210 + Math.cos(ta) * 150).toFixed(1) + " " + (230 + Math.sin(ta) * 150).toFixed(1) + " L" + (210 + Math.cos(ta) * 178).toFixed(1) + " " + (230 + Math.sin(ta) * 178).toFixed(1), { w: 5 }); }
        r.needleG = AG.svg("g", {}, sv);
        r.needle = AG.stroke(r.needleG, "M210 230 L210 78", { w: 9, color: col.classList.contains("win") ? "var(--accent)" : "var(--ink)" });
        AG.svg("circle", { cx: 210, cy: 230, r: 16, style: "fill: var(--ink)" }, r.needleG);
        r.sv = sv;
        r.val = AG.el("div", "ag-c-val", col);
        r.lab = AG.el("div", "ag-c-label", col, AG.esc(it.label));
      } else if (look === "newsroom") {
        r.val = AG.el("div", "ag-c-val", col);
        r.bar = AG.el("div", "ag-c-bar", col);
        r.bar.style.height = Math.round((it.value / maxV) * 470) + "px";
      } else {
        r.val = AG.el("div", "ag-c-val", col);
        r.bar = AG.el("div", "ag-c-bar", col);
        if (look === "dossier") r.bar.style.height = Math.round((it.value / maxV) * 620) + "px";
        r.lab = AG.el("div", "ag-c-label", col, AG.esc(it.label));
      }
      return r;
    });
    if (look === "newsroom") {
      var lr = AG.el("div", "ag-c-labels", box);
      items.forEach(function (it) { AG.el("div", "ag-c-label", lr, AG.esc(it.label)); });
      tl.fromTo(box, { y: 260, rotation: 3, opacity: 0 }, { y: 0, rotation: 0, opacity: 1, duration: 0.28, ease: "back.out(1.4)" }, at);
    }
    if (title) tl.fromTo(title, { opacity: 0, y: -20 }, { opacity: 1, y: 0, duration: 0.3, ease: "power2.out" }, at);
    built.forEach(function (r, i) {
      var it = items[i], s = it.at !== undefined ? it.at : at + 0.2 + i * (look === "cinematic" ? 0.5 : 0.25);
      var dur = look === "cinematic" ? 1.4 : 0.9;
      AG.count(ctx, r.val, { at: s, dur: dur, from: 0, to: it.value, suffix: it.suffix || "", prefix: it.prefix || "", ease: look === "cinematic" ? "power1.inOut" : "power3.out" });
      if (r.bar) tl.fromTo(r.bar, { scaleY: 0 }, { scaleY: 1, duration: dur, ease: look === "newsroom" ? "power4.out" : look === "cinematic" ? "power1.inOut" : "expo.out" }, s);
      if (look === "explainer") {
        AG.drawOn(ctx, r.arc, at + i * 0.15, 0.6, "power1.inOut");
        for (var tk = 0; tk <= 4; tk++) tl.fromTo(r["t" + tk], { opacity: 0 }, { opacity: 1, duration: 0.1 }, at + 0.3 + tk * 0.05 + i * 0.15);
        var deg = -90 + (it.value / 100) * 180;
        tl.fromTo(r.needleG, { rotation: -90, svgOrigin: "210 230" }, { rotation: deg, svgOrigin: "210 230", duration: 1.0, ease: "elastic.out(1, 0.55)" }, s + 0.1);
        AG.boil(ctx, r.sv, 1.5, 0.35, 40 + i);
        tl.fromTo(r.lab, { opacity: 0, y: 20 }, { opacity: 1, y: 0, duration: 0.3 }, s);
      }
      if (look === "explainer") { tl.set(r.val, { opacity: 0 }, 0); tl.set(r.val, { opacity: 1 }, s); }
      if (look === "dossier") { tl.fromTo(r.lab, { opacity: 0 }, { opacity: 1, duration: 0.3 }, s + 0.2); tl.fromTo(r.val, { yPercent: 40, opacity: 0 }, { yPercent: 0, opacity: 1, duration: 0.3, ease: "expo.out" }, s); }
      if (look === "cinematic") { tl.fromTo(r.lab, { opacity: 0 }, { opacity: 1, duration: 0.8 }, s + 0.2); tl.fromTo(r.val, { opacity: 0, filter: "blur(12px)" }, { opacity: 1, filter: "blur(0px)", duration: 0.8, ease: "sine.out" }, s); }
    });
    if (look === "cinematic") tl.fromTo(box.querySelector(".ag-c-div"), { scaleY: 0 }, { scaleY: 1, duration: 1.2, ease: "power2.inOut" }, at);
    if (look === "newsroom" && o.winner) { var w = built[o.winner === "a" ? 0 : 1]; AG.shake(ctx, box, at + 1.15, 10); }
    if (o.out) tl.to(box, { opacity: 0, duration: 0.25, ease: "power1.in" }, o.out - 0.25);
    return box;
  };

  // ---------------------------------------------------------------- checklist
  AG.checklist = function (ctx, parent, o) {
    var tl = ctx.tl, look = ctx.look, at = o.at, step = o.step || (look === "cinematic" ? 0.8 : 0.55);
    var box = AG.el("div", "ag-check", parent);
    box.style.top = (o.top || 520) + "px";
    tl.set(box, { opacity: 0 }, 0);
    tl.set(box, { opacity: 1 }, at);
    var title = AG.el("div", "ag-k-title", box, AG.esc(o.title || "What to do"));
    if (look === "dossier") tl.fromTo(title, { yPercent: 60, opacity: 0 }, { yPercent: 0, opacity: 1, duration: 0.4, ease: "expo.out" }, at);
    else if (look === "newsroom") { tl.fromTo(box, { y: 200, opacity: 0 }, { y: 0, opacity: 1, duration: 0.24, ease: "back.out(1.5)" }, at); tl.fromTo(title, { scaleX: 0, transformOrigin: "0% 50%" }, { scaleX: 1, duration: 0.2, ease: "power3.out" }, at + 0.08); }
    else if (look === "explainer") { tl.fromTo(title, { opacity: 0, rotation: -3 }, { opacity: 1, rotation: 0, duration: 0.35, ease: "back.out(2)" }, at); }
    else tl.fromTo(title, { opacity: 0, letterSpacing: "0.5em" }, { opacity: 1, letterSpacing: "0.24em", duration: 1.0, ease: "sine.out" }, at);
    (o.items || []).forEach(function (txt, i) {
      var s = at + 0.35 + i * step;
      var it = AG.el("div", "ag-k-item", box);
      if (look === "dossier") {
        var idx = AG.el("div", "ag-k-idx", it, (i < 9 ? "0" : "") + (i + 1));
        var tx = AG.el("div", "ag-k-text", it, AG.esc(txt));
        var sv = AG.svg("svg", { class: "ag-k-tick", viewBox: "0 0 70 70" }, it);
        var p = AG.stroke(sv, "M10 38 L28 55 L62 14", { color: "var(--accent)", w: 9 });
        tl.fromTo(it, { opacity: 0, x: -40 }, { opacity: 1, x: 0, duration: 0.35, ease: "expo.out" }, s);
        tl.fromTo(idx, { color: "#3ce37a" }, { color: "#8b8b86", duration: 0.6 }, s);
        AG.drawOn(ctx, p, s + 0.25, 0.22, "power2.out");
      } else if (look === "newsroom") {
        var bx = AG.el("div", "ag-k-box", it);
        AG.el("div", "ag-k-text", it, AG.esc(txt));
        var sv2 = AG.svg("svg", { class: "ag-k-tick", viewBox: "0 0 100 100" }, bx);
        var p2 = AG.stroke(sv2, "M14 52 L42 82 L94 8", { color: "var(--up)", w: 16 });
        tl.fromTo(it, { opacity: 0, x: 60 }, { opacity: 1, x: 0, duration: 0.16, ease: "power4.out" }, s);
        AG.drawOn(ctx, p2, s + 0.15, 0.16, "power3.out");
        tl.fromTo(bx, { scale: 1.3 }, { scale: 1, duration: 0.2, ease: "back.out(3)" }, s + 0.3);
      } else if (look === "explainer") {
        var sv3 = AG.svg("svg", { class: "ag-k-box", viewBox: "0 0 84 84" }, it);
        var bp = AG.stroke(sv3, AG.roughRect(74, 74, 50 + i, 3), { w: 5 }); bp.setAttribute("transform", "translate(5 5)");
        var tk = AG.stroke(sv3, AG.wobblePath([[14, 44], [26, 56], [36, 66], [58, 30], [86, -6]], 60 + i, 2), { color: "var(--accent)", w: 9 });
        var t3 = AG.el("div", "ag-k-text", it, AG.esc(txt));
        AG.drawOn(ctx, bp, s, 0.35, "power1.inOut");
        tl.fromTo(t3, { opacity: 0, x: 20 }, { opacity: 1, x: 0, duration: 0.3, ease: "power2.out" }, s + 0.1);
        AG.drawOn(ctx, tk, s + 0.35, 0.25, "power2.out");
        AG.boil(ctx, sv3, 1.2, 0.8, 70 + i);
      } else {
        var ci = AG.el("div", "ag-k-idx", it, "0" + (i + 1));
        var ct = AG.el("div", "ag-k-text", it, AG.esc(txt));
        var ru = AG.el("div", "ag-k-rule", it);
        tl.fromTo(ru, { scaleX: 0 }, { scaleX: 1, duration: 0.9, ease: "power2.inOut" }, s - 0.1);
        tl.fromTo(ci, { opacity: 0 }, { opacity: 1, duration: 0.6 }, s);
        tl.fromTo(ct, { opacity: 0, y: 20, filter: "blur(8px)" }, { opacity: 1, y: 0, filter: "blur(0px)", duration: 0.8, ease: "sine.out" }, s + 0.05);
      }
    });
    if (o.out) tl.to(box, { opacity: 0, duration: 0.25, ease: "power1.in" }, o.out - 0.25);
    return box;
  };

  // ---------------------------------------------------------------- CTA end card
  AG.cta = function (ctx, parent, o) {
    var tl = ctx.tl, look = ctx.look, at = o.at;
    var vars = (window.__hyperframes && window.__hyperframes.getVariables && window.__hyperframes.getVariables()) || {};
    var handle = vars.handle || o.handle || "@AGMM";
    var box = AG.el("div", "ag-cta", parent);
    tl.set(box, { opacity: 0 }, 0);
    tl.set(box, { opacity: 1 }, at);
    var line = AG.el("div", "ag-cta-line", box);
    // "Follow for one real AI story a day"
    var parts;
    if (look === "dossier") parts = [["Follow for", "ag-small"], ["one real", ""], ["AI story", "emph"], ["a day", "ag-small"]];
    else if (look === "newsroom") parts = [["Follow for", ""], ["one real AI story", "emph"], ["a day", ""]];
    else if (look === "explainer") parts = [["Follow for", ""], ["one real", ""], ["AI story", "emph"], ["a day", ""]];
    else parts = [["Follow for one", ""], ["real AI story", "emph"], ["a day", ""]];
    var pieces = parts.map(function (p) {
      var m = AG.el("span", "ag-mask", line);
      var s = AG.el("span", "ag-in " + p[1], m, AG.esc(p[0]));
      if (look === "newsroom" || look === "cinematic" || look === "explainer") m.style.display = "block";
      return s;
    });
    var prof = AG.el("div", "ag-cta-profile", box);
    var av = AG.el("div", "ag-cta-avatar", prof, look === "cinematic" ? "A" : "AG");
    var hd = AG.el("div", "ag-cta-handle", prof, AG.esc(handle));
    var btn = AG.el("div", "ag-cta-btn", box);
    var ba = AG.el("div", "ag-b-a", btn, "Follow");
    var bb = AG.el("div", "ag-b-b", btn, (look === "cinematic" ? "Following" : "Following ✓"));
    var tap = AG.el("div", "ag-cta-tap", btn);
    var pressAt = at + (o.pressDelay || 1.25);
    // entrance per look
    pieces.forEach(function (s, i) {
      if (look === "dossier") tl.fromTo(s, { yPercent: 110 }, { yPercent: 0, duration: 0.38, ease: "expo.out" }, at + i * 0.12);
      else if (look === "newsroom") tl.fromTo(s, { scale: 0.4, opacity: 0 }, { scale: 1, opacity: 1, duration: 0.2, ease: "back.out(2.5)" }, at + i * 0.1);
      else if (look === "explainer") tl.fromTo(s, { yPercent: 100 }, { yPercent: 0, duration: 0.4, ease: "back.out(1.6)" }, at + i * 0.12);
      else tl.fromTo(s, { opacity: 0, filter: "blur(12px)" }, { opacity: 1, filter: "blur(0px)", duration: 0.8, ease: "sine.out" }, at + i * 0.22);
    });
    if (look === "explainer") {
      var em = box.querySelector(".emph");
      var sv = AG.svg("svg", { viewBox: "0 0 100 20", preserveAspectRatio: "none", style: "position:absolute;left:-3%;width:106%;bottom:-0.12em;height:0.3em;overflow:visible" }, em);
      var ul = AG.stroke(sv, AG.roughLine(2, 12, 98, 8, 88, 1.5, 3), { color: "var(--accent)", w: 6 });
      AG.drawOn(ctx, ul, at + 0.6, 0.4, "power1.inOut");
    }
    tl.fromTo(prof, { opacity: 0, y: 30 }, { opacity: 1, y: 0, duration: 0.35, ease: "power3.out" }, at + 0.45);
    tl.fromTo(av, { scale: 0.5 }, { scale: 1, duration: 0.4, ease: "back.out(2)" }, at + 0.45);
    tl.fromTo(btn, { opacity: 0, scale: 0.8 }, { opacity: 1, scale: 1, duration: 0.3, ease: "back.out(2)" }, at + 0.65);
    // idle breath before the press so the button is never a held still
    tl.to(btn, { scale: 1.05, duration: 0.3, ease: "sine.inOut", yoyo: true, repeat: 1 }, at + 0.95 - 0.3 + 0.3);
    // finger / press
    tl.to(btn, { scale: 0.92, duration: 0.08, ease: "power2.in" }, pressAt);
    tl.to(btn, { scale: 1, duration: 0.35, ease: "elastic.out(1.1, 0.45)" }, pressAt + 0.08);
    tl.fromTo(tap, { scale: 0, opacity: 0.9 }, { scale: 9, opacity: 0, duration: 0.55, ease: "power2.out" }, pressAt);
    tl.fromTo(bb, { clipPath: "circle(0% at 50% 50%)" }, { clipPath: "circle(75% at 50% 50%)", duration: 0.35, ease: "power3.out" }, pressAt + 0.02);
    tl.set(ba, { opacity: 0 }, pressAt + 0.38);
    // after the press: the line keeps living (accent sweep) so the end card never freezes
    var tail = (o.end || at + 3) - (pressAt + 0.4);
    if (tail > 0.2) {
      if (look === "cinematic") tl.fromTo(line, { scale: 1 }, { scale: 1.04, duration: tail, ease: "sine.inOut" }, pressAt + 0.4);
      else tl.fromTo(box, { y: 0 }, { y: -26, duration: tail, ease: "sine.inOut" }, pressAt + 0.4);
      tl.fromTo(av, { scale: 1 }, { scale: 1.18, duration: 0.18, ease: "power2.out", yoyo: true, repeat: 1 }, pressAt + 0.15);
    }
    return box;
  };

  // ---------------------------------------------------------------- stamp (impact moment)
  AG.stamp = function (ctx, parent, o) {
    var tl = ctx.tl, at = o.at;
    var st = AG.el("div", "ag-stamp", parent);
    st.style.cssText = "position:absolute;left:50%;top:" + (o.top || 820) + "px;z-index:45;transform-origin:50% 50%;";
    var inner = AG.el("div", "ag-stamp-in", st, AG.esc(o.text));
    if (o.size) inner.style.fontSize = o.size + "px";
    if (o.sub) AG.el("div", "ag-stamp-sub", inner, AG.esc(o.sub));
    tl.set(st, { opacity: 0 }, 0);
    tl.set(st, { opacity: 1 }, at);
    tl.fromTo(st, { xPercent: -50, scale: 3.2, rotation: o.rot === undefined ? -14 : o.rot + 6 }, { xPercent: -50, scale: 1, rotation: o.rot === undefined ? -9 : o.rot, duration: 0.16, ease: "power4.in" }, at);
    AG.shake(ctx, o.shake || parent, at + 0.16, 22);
    tl.fromTo(st, { scale: 1 }, { scale: 1.06, duration: 1.4, ease: "sine.inOut" }, at + 0.2);
    if (o.out) tl.to(st, { opacity: 0, duration: 0.15 }, o.out - 0.15);
    return st;
  };

  // ---------------------------------------------------------------- line chart (draws on; green up, red down)
  AG.lineChart = function (ctx, parent, o) {
    var tl = ctx.tl, at = o.at, w = o.w || 920, h = o.h || 520;
    var box = AG.el("div", "ag-chart", parent);
    box.style.cssText = "position:absolute;left:" + (o.left || 80) + "px;top:" + (o.top || 400) + "px;width:" + w + "px;height:" + h + "px;z-index:22;";
    var sv = AG.svg("svg", { width: w, height: h, viewBox: "0 0 " + w + " " + h, style: "overflow:visible" }, box);
    for (var g = 0; g <= 4; g++) { var gl = AG.svg("line", { x1: 0, x2: w, y1: (h * g) / 4, y2: (h * g) / 4, "stroke-width": 2, style: "stroke:" + (o.grid || "rgba(255,255,255,0.18)") }, sv); }
    var pts = o.pts.map(function (p) { return [p[0] * w, h - p[1] * h]; });
    var peak = o.peak !== undefined ? o.peak : pts.length - 1;
    function seg(a, b, col, width) {
      var d = "M" + pts.slice(a, b + 1).map(function (p) { return p[0].toFixed(1) + " " + p[1].toFixed(1); }).join(" L");
      var p = AG.svg("path", { d: d, fill: "none", "stroke-width": width || 12, "stroke-linejoin": "round", "stroke-linecap": "round" }, sv);
      p.style.stroke = col;
      return p;
    }
    var up = seg(0, peak, o.upColor || "var(--up)");
    var down = peak < pts.length - 1 ? seg(peak, pts.length - 1, o.downColor || "var(--down)", 14) : null;
    var dot = AG.svg("circle", { r: 18, cx: pts[0][0], cy: pts[0][1], style: "fill:#fff" }, sv);
    var upDur = o.upDur || 0.9, downDur = o.downDur || 0.35, downAt = o.downAt || at + upDur + 0.3;
    AG.drawOn(ctx, up, at, upDur, "power2.inOut");
    if (down) AG.drawOn(ctx, down, downAt, downDur, "power4.in");
    // dot rides the draw front
    var upL = up.getTotalLength(), downL = down ? down.getTotalLength() : 0;
    var eU = AG.ease("power2.inOut"), eD = AG.ease("power4.in");
    AG.onFrame(ctx, function (t) {
      var pt;
      if (!down || t < downAt) pt = up.getPointAtLength(upL * eU(AG.clamp((t - at) / upDur, 0, 1)));
      else pt = down.getPointAtLength(downL * eD(AG.clamp((t - downAt) / downDur, 0, 1)));
      dot.setAttribute("cx", pt.x.toFixed(1)); dot.setAttribute("cy", pt.y.toFixed(1));
    });
    if (o.labels) o.labels.forEach(function (L) {
      var lb = AG.el("div", "ag-chart-label", box, AG.esc(L.text));
      lb.style.cssText = "position:absolute;left:" + (L.x * w) + "px;top:" + (h - L.y * h) + "px;transform:translate(-50%,-130%);white-space:nowrap;" + (L.style || "");
      tl.fromTo(lb, { opacity: 0, y: 20 }, { opacity: 1, y: 0, duration: 0.2, ease: "back.out(2)" }, L.at);
    });
    tl.set(box, { opacity: 0 }, 0);
    tl.set(box, { opacity: 1 }, at);
    if (o.out) tl.to(box, { opacity: 0, duration: 0.2 }, o.out - 0.2);
    return box;
  };

  // ---------------------------------------------------------------- cinematic depth plate (2.5D parallax)
  // One still becomes three depth planes: the far plane pushes slowly, a feathered near band of the
  // same still (usually the bottom: water, floor, desk) travels faster and larger, and fog + dust
  // motes ride between and in front. The parallax between planes is what makes it read as a camera
  // move rather than a flat Ken Burns pan.
  AG.depthPlate = function (ctx, parent, o) {
    var tl = ctx.tl, from = o.from, to = o.to, dur = to - from;
    var wrap = AG.el("div", "ag-layer", parent);
    wrap.style.overflow = "hidden";
    var far = AG.el("div", "ag-layer", wrap); var fi = AG.el("img", "ag-fill", far); fi.src = o.src;
    var near = AG.el("div", "ag-layer", wrap); var ni = AG.el("img", "ag-fill", near); ni.src = o.src;
    var split = o.split || 0.62, feather = o.feather || 0.14;
    var m = o.nearSide === "top"
      ? "linear-gradient(180deg, #000 0%, #000 " + (split - feather) * 100 + "%, transparent " + split * 100 + "%)"
      : "linear-gradient(180deg, transparent " + (split - feather) * 100 + "%, #000 " + split * 100 + "%, #000 100%)";
    near.style.webkitMaskImage = m; near.style.maskImage = m;
    var push = o.push || [1.08, 1.2];
    var sway = o.sway || 40;
    tl.fromTo(far, { scale: push[0], x: 0, y: 0 }, { scale: push[0] + (push[1] - push[0]) * 0.55, x: -sway * 0.35, y: -sway * 0.25, duration: dur, ease: o.ease || "sine.inOut" }, from);
    tl.fromTo(near, { scale: push[0] + 0.02, x: 0, y: 0 }, { scale: push[1] + 0.06, x: -sway, y: sway * 0.6, duration: dur, ease: o.ease || "sine.inOut" }, from);
    if (o.nearBlur) near.style.filter = "blur(" + o.nearBlur + "px)";
    if (o.fog) {
      var fog = AG.el("div", "ag-layer", wrap); var fg = AG.el("img", "ag-fill", fog); fg.src = o.fog;
      fog.style.mixBlendMode = "screen"; fog.style.opacity = o.fogOpacity || 0.45;
      tl.fromTo(fog, { scale: 1.6, x: 260, y: 120 }, { scale: 1.9, x: -300, y: -60, duration: dur, ease: "none" }, from);
    }
    // dust motes: three depth tiers, positions are pure functions of time
    var motes = [];
    var n = o.motes === undefined ? 34 : o.motes;
    for (var i = 0; i < n; i++) {
      var tier = i % 3, d = AG.el("div", "", wrap);
      var size = [4, 7, 13][tier];
      d.style.cssText = "position:absolute;left:0;top:0;width:" + size + "px;height:" + size + "px;border-radius:50%;background:rgba(255,236,210," + [0.35, 0.5, 0.4][tier] + ");filter:blur(" + [0.5, 1.2, 3.5][tier] + "px)";
      motes.push({ el: d, x: AG.hash(i, 61) * 1180 - 50, y: AG.hash(i, 62) * 2000, vx: (AG.hash(i, 63) - 0.5) * 30 * (tier + 1), vy: -(10 + AG.hash(i, 64) * 25) * (tier + 1), ph: AG.hash(i, 65) * 6.28 });
    }
    AG.onFrame(ctx, function (t) {
      var lt = t - from;
      for (var k = 0; k < motes.length; k++) {
        var q = motes[k];
        var y = ((q.y + q.vy * lt) % 2000 + 2000) % 2000 - 40;
        var x = q.x + q.vx * lt + Math.sin(lt * 1.3 + q.ph) * 12;
        q.el.style.transform = "translate(" + x.toFixed(1) + "px," + y.toFixed(1) + "px)";
      }
    });
    var vig = AG.el("div", "ag-layer", wrap);
    vig.style.background = "radial-gradient(ellipse 75% 60% at 50% 45%, rgba(0,0,0,0) 45%, rgba(0,0,0,0.72) 100%)";
    return { wrap: wrap, far: far, near: near };
  };

  // Film gate weave: sub-pixel per-frame jitter of a layer (seeded), like a projected print.
  AG.weave = function (ctx, el, amp) {
    AG.onFrame(ctx, function (t) {
      var f = Math.floor(t * 30);
      el.style.translate = (AG.sh(f, 71) * amp).toFixed(2) + "px " + (AG.sh(f, 72) * amp).toFixed(2) + "px";
    });
  };

  // ---------------------------------------------------------------- transitions
  AG.tx = {};
  // Glitch: RGB split + slice jitter + tear bars, hard swap at t. Seek-safe (all from time).
  AG.tx.glitch = function (ctx, t, A, B, o) {
    o = o || {};
    var tl = ctx.tl, half = o.half || 0.1;
    var id = ctx.id + "-rgb" + Math.round(t * 100);
    var defs = AG.svg("svg", { class: "ag-hidden-def" }, ctx.root);
    var f = AG.svg("filter", { id: id, x: "-10%", y: "-10%", width: "120%", height: "120%", "color-interpolation-filters": "sRGB" }, defs);
    AG.svg("feColorMatrix", { in: "SourceGraphic", type: "matrix", values: "1 0 0 0 0  0 0 0 0 0  0 0 0 0 0  0 0 0 1 0", result: "r" }, f);
    var offR = AG.svg("feOffset", { in: "r", dx: 0, dy: 0, result: "ro" }, f);
    AG.svg("feColorMatrix", { in: "SourceGraphic", type: "matrix", values: "0 0 0 0 0  0 1 0 0 0  0 0 0 0 0  0 0 0 1 0", result: "g" }, f);
    AG.svg("feColorMatrix", { in: "SourceGraphic", type: "matrix", values: "0 0 0 0 0  0 0 0 0 0  0 0 1 0 0  0 0 0 1 0", result: "b" }, f);
    var offB = AG.svg("feOffset", { in: "b", dx: 0, dy: 0, result: "bo" }, f);
    AG.svg("feBlend", { in: "ro", in2: "g", mode: "screen", result: "rg" }, f);
    AG.svg("feBlend", { in: "rg", in2: "bo", mode: "screen" }, f);
    var bars = [];
    for (var i = 0; i < 5; i++) { var b = AG.el("div", "ag-tear", ctx.root); b.style.opacity = 0; bars.push(b); }
    var flash = AG.el("div", "ag-flash", ctx.root); flash.style.opacity = 0;
    AG.onFrame(ctx, function (time) {
      var d = time - t;
      var on = Math.abs(d) < half;
      var k = on ? 1 - Math.abs(d) / half : 0;
      var fr = Math.floor(time * 30);
      var target = d < 0 ? A : B;
      var other = d < 0 ? B : A;
      if (on) {
        var dx = (AG.sh(fr, 5) * 34 + 18) * k;
        offR.setAttribute("dx", dx.toFixed(1)); offB.setAttribute("dx", (-dx).toFixed(1));
        offR.setAttribute("dy", (AG.sh(fr, 6) * 6 * k).toFixed(1));
        target.style.filter = "url(#" + id + ")";
        target.style.transform = "translate(" + (AG.sh(fr, 7) * 40 * k).toFixed(1) + "px," + (AG.sh(fr, 8) * 10 * k).toFixed(1) + "px) skewX(" + (AG.sh(fr, 9) * 8 * k).toFixed(2) + "deg)";
        other.style.filter = ""; other.style.transform = "";
        for (var j = 0; j < bars.length; j++) {
          var vis = AG.hash(fr * 5 + j, 12) < 0.3 + 0.6 * k;
          bars[j].style.opacity = vis ? (0.6 + 0.4 * AG.hash(fr + j, 13)).toFixed(2) : 0;
          bars[j].style.top = Math.floor(AG.hash(fr * 3 + j, 14) * 1880) + "px";
          bars[j].style.height = Math.floor(6 + AG.hash(fr * 7 + j, 15) * 90 * k) + "px";
          bars[j].style.transform = "translateX(" + Math.floor(AG.sh(fr + j * 3, 16) * 120) + "px)";
        }
      } else {
        if (A.style.filter.indexOf(id) >= 0) { A.style.filter = ""; A.style.transform = ""; }
        if (B.style.filter.indexOf(id) >= 0) { B.style.filter = ""; B.style.transform = ""; }
        for (var q = 0; q < bars.length; q++) bars[q].style.opacity = 0;
        flash.style.opacity = 0;
      }
    });
  };
  // Whip: both scenes ride one velocity-matched move with directional motion blur peaking at the seam.
  AG.tx.whip = function (ctx, t, A, B, o) {
    o = o || {};
    var tl = ctx.tl, dur = o.dur || 0.5, dir = o.dir === "right" ? -1 : 1, W = ctx.W;
    var id = ctx.id + "-whip" + Math.round(t * 100);
    var defs = AG.svg("svg", { class: "ag-hidden-def" }, ctx.root);
    var f = AG.svg("filter", { id: id, x: "-20%", y: "0%", width: "140%", height: "100%" }, defs);
    var gb = AG.svg("feGaussianBlur", { stdDeviation: "0 0" }, f);
    var ease = AG.ease("power3.inOut");
    var wrapA = A.cam || A, wrapB = B.cam || B;
    var dirty = false;
    AG.onFrame(ctx, function (time) {
      var p = AG.clamp((time - (t - dur / 2)) / dur, 0, 1);
      var active = time > t - dur / 2 && time < t + dur / 2;
      var e = ease(p);
      if (active) {
        var blur = Math.sin(p * Math.PI) * 34;
        gb.setAttribute("stdDeviation", blur.toFixed(1) + " 0");
        A.style.transform = "translateX(" + (-dir * e * W).toFixed(1) + "px)";
        B.style.transform = "translateX(" + (dir * (1 - e) * W).toFixed(1) + "px)";
        A.style.filter = B.style.filter = "url(#" + id + ")";
        dirty = true;
      } else if (dirty) {
        A.style.filter = ""; B.style.filter = ""; A.style.transform = ""; B.style.transform = "";
        dirty = false;
      }
    });
    // scene visibility windows are owned by AG.scene; extend them across the whip
    ctx.tl.set(B, { opacity: 1 }, t - dur / 2);
    ctx.tl.set(A, { opacity: 0 }, t + dur / 2);
  };
  // Push: incoming scene pushes the outgoing one off (vertical by default), outgoing darkens and lags.
  AG.tx.push = function (ctx, t, A, B, o) {
    o = o || {};
    var tl = ctx.tl, dur = o.dur || 0.55, H = ctx.H;
    var axis = o.dir === "left" || o.dir === "right" ? "x" : "y";
    var sgn = o.dir === "down" || o.dir === "right" ? -1 : 1;
    var size = axis === "x" ? ctx.W : H;
    var s = t - dur / 2;
    tl.set(B, { opacity: 1, zIndex: 5 }, s);
    var fromB = {}, toB = {}, toA = {};
    fromB[axis] = sgn * size; toB[axis] = 0; toA[axis] = -sgn * size * 0.35;
    tl.fromTo(B, fromB, Object.assign(toB, { duration: dur, ease: "expo.inOut" }), s);
    tl.fromTo(A, { filter: "brightness(1)" }, Object.assign(toA, { filter: "brightness(0.88)", duration: dur, ease: "expo.inOut" }), s);
    tl.set(A, { opacity: 0 }, s + dur);
    var reset = {}; reset[axis] = 0; reset.filter = "none";
    tl.set(A, reset, s + dur + 0.01);
    tl.set(B, { zIndex: 0 }, s + dur + 0.01);
  };
  // Match cut: element a accelerates into element b's position/scale (power4.in), hard swap at t,
  // element b continues out of that same pose (power4.out). Pass geometry in stage pixels.
  AG.tx.match = function (ctx, t, A, B, o) {
    var tl = ctx.tl, lead = o.lead || 0.35, tail = o.tail || 0.45;
    tl.to(o.fromEl, Object.assign({ duration: lead, ease: "power4.in" }, o.fromTo), t - lead);
    tl.fromTo(o.toEl, o.toFrom, Object.assign({ duration: tail, ease: "power4.out" }, o.toTo || { x: 0, y: 0, scale: 1, rotation: 0 }), t);
    tl.set(A, { opacity: 0 }, t);
    tl.set(B, { opacity: 1 }, t);
  };
})();
