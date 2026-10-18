/* AGMM short-form kit lib v1.0.0 — kit3.js: the component catalogue and the spec runtime.
   Loads after ds/kit.js (AG) and ds2/kit2.js (AG2). build_short.py writes window.AGK_SPEC (every time already
   resolved to seconds on the voice clock) and window.AGK_PART ({off, dur}); AGK.run() builds the whole short.

   Pilot lessons baked in (each one cost a render round in P1/P2/P3 or the design-system rounds):
   - frame 0 is the hook and never blank: nothing that starts at t<=0.05 gets an opacity-0/opacity-1 pair (r5/r6 bug),
     and hook elements enter with a visible "settle" instead of from-invisible.
   - reported figures SLAM in; no component counts through intermediate numbers (P2 r1, P3 "242 on the way to 250").
   - captions are phrase cards of 1-4 words, the outgoing card clears 0.07s before the next (AG/AG2 engines).
   - no blank transitions: every scene is built before its seam, fields always carry texture, content lands <=0.1s
     after the seam; whips are opt-in only (P3 r4 near-blank blurred frames); flashes are 2 frames at <=24%.
   - nothing under 42px: every text setter clamps to K.MIN_PX; build_short.py rejects lines that would need less.
   - every scene camera drifts, so no frame holds still for 1.5s (gate check 3).
   Every effect is a pure function of timeline time: no Math.random, no clocks. */
(function () {
  "use strict";
  var AG = window.AG, AG2 = window.AG2;
  window.__timelines = window.__timelines || {};
  var K = (window.AGK = {});
  K.VERSION = "1.0.0";
  K.MIN_PX = 42;
  K.sig = K.sig || {};   // signature modules register here: AGK.sig["name"] = function (ctx, S, p, beat, K) {}

  // ---------------------------------------------------------------- look table
  // enter: entrance grammar; field: default background; tx: default seam; cap: caption engine; img: how a still is shown;
  // cw: average glyph width of the hero face in em (text fitting); onField: text straight on the field, or on a card
  K.LOOKS = {
    dossier:    { enter: "rise",  field: "black",    tx: "cut",   cap: "ag",  img: "full",   grain: 0.07, cw: 0.66, dark: 1, onField: "text", flash: 0 },
    newsroom:   { enter: "slam",  field: "red",      tx: "flash", cap: "ag",  img: "full",   grain: 0.05, cw: 0.45, dark: 1, onField: "text", flash: 1 },
    explainer:  { enter: "pop",   field: "paper",    tx: "push",  cap: "ag",  img: "card",   grain: 0,    cw: 0.58, dark: 0, onField: "text", flash: 0 },
    cinematic:  { enter: "blur",  field: "night",    tx: "fade",  cap: "ag",  img: "depth",  grain: 0.12, cw: 0.46, dark: 1, onField: "text", flash: 0 },
    evidence:   { enter: "pin",   field: "cork",     tx: "push",  cap: "ag2", img: "print",  grain: 0.05, cw: 0.56, dark: 1, onField: "card", flash: 0 },
    whitemodel: { enter: "pop",   field: "white",    tx: "push",  cap: "ag2", img: "card",   grain: 0,    cw: 0.56, dark: 0, onField: "text", flash: 0 },
    softui:     { enter: "pop",   field: "soft",     tx: "push",  cap: "ag2", img: "card",   grain: 0,    cw: 0.56, dark: 0, onField: "text", flash: 0 },
    desktop:    { enter: "win",   field: "teal",     tx: "cut",   cap: "ag2", img: "window", grain: 0,    cw: 0.78, dark: 1, onField: "card", flash: 0 },
    chart:      { enter: "rise",  field: "graph",    tx: "push",  cap: "ag2", img: "card",   grain: 0.04, cw: 0.55, dark: 1, onField: "text", flash: 0 },
    opsmap:     { enter: "stamp", field: "mapsheet", tx: "push",  cap: "ag2", img: "print",  grain: 0.06, cw: 0.44, dark: 1, onField: "text", flash: 0 },
  };

  // ---------------------------------------------------------------- small helpers
  function el(tag, cls, parent, html) { return AG.el(tag, cls, parent, html); }
  K.el = el;
  K.show = function (ctx, e, t) { if (t > 0.05) { ctx.tl.set(e, { opacity: 0 }, 0); ctx.tl.set(e, { opacity: 1 }, t); } };
  K.hide = function (ctx, e, t, d) { if (d) ctx.tl.to(e, { opacity: 0, duration: d, ease: "power1.in" }, t - d); else ctx.tl.set(e, { opacity: 0 }, t); };
  // font size for one line of text that must fit `width` px: never above max, never below K.MIN_PX
  K.fit = function (text, width, max, cw) {
    var n = Math.max(1, String(text).length);
    return Math.max(K.MIN_PX, Math.min(max, Math.floor(width / (n * (cw || 0.55)))));
  };
  K.setText = function (e, text, width, max, cw) { e.textContent = text; e.style.fontSize = K.fit(text, width, max, cw) + "px"; return e; };
  // Entrances. t<=0.05 is the hook frame: a visible settle, never from-invisible.
  K.enter = function (ctx, e, t, kind, o) {
    o = o || {}; var tl = ctx.tl;
    K.show(ctx, e, t);
    if (t <= 0.05) { tl.fromTo(e, { scale: o.hookScale || 1.08, transformOrigin: o.origin || "50% 50%" }, { scale: 1, duration: 0.45, ease: "power2.out" }, 0); return; }
    var org = o.origin || "50% 50%";
    switch (kind) {
      case "slam":
        // craft ledger 28 Sep (S33 $1M over "Roughly", S29 39 over THAT'S THE, S04 REGULATOR over THE DATA): with
        // kit_defaults a slam starts at <= 1.1x from a top-left anchor, so it grows down and right, never up or off frame.
        if (ctx.spec && ctx.spec.kit_defaults && String(ctx.spec.kit_defaults) >= "2026-09-28") {
          tl.fromTo(e, { scale: Math.min(o.s || 1.1, 1.1), rotation: -2, transformOrigin: o.origin || "0% 0%" }, { scale: 1, rotation: o.rot || 0, duration: 0.2, ease: "power3.out" }, t); break;
        }
        tl.fromTo(e, { scale: o.s || 2.1, rotation: -4, transformOrigin: org }, { scale: 1, rotation: o.rot || 0, duration: 0.22, ease: "back.out(1.7)" }, t); break;
      case "rise": tl.fromTo(e, { y: 70, clipPath: "inset(0% 0% 100% 0%)" }, { y: 0, clipPath: "inset(0% 0% -20% 0%)", duration: 0.38, ease: "expo.out" }, t); break;
      case "pop": tl.fromTo(e, { scale: 0.5, rotation: (o.rot || 0) + 6, transformOrigin: org }, { scale: 1, rotation: o.rot || 0, duration: 0.28, ease: "back.out(2.2)" }, t); break;
      case "blur": tl.fromTo(e, { opacity: 0, filter: "blur(14px)", scale: 1.04 }, { opacity: 1, filter: "blur(0px)", scale: 1, duration: 0.6, ease: "sine.out" }, t); break;
      case "pin": tl.fromTo(e, { y: -260, rotation: (o.rot || 0) - 7, scale: 1.12 }, { y: 0, rotation: o.rot || 0, scale: 1, duration: 0.34, ease: "power3.out" }, t); break;
      case "win": tl.fromTo(e, { scale: 0.55, transformOrigin: org }, { scale: 1, duration: 0.16, ease: "steps(4)" }, t); break;
      case "stamp": tl.fromTo(e, { scale: 2.6, rotation: (o.rot || 0) + 8, transformOrigin: org }, { scale: 1, rotation: o.rot || 0, duration: 0.16, ease: "power4.in" }, t); break;
      case "wipe": tl.fromTo(e, { clipPath: "inset(0% 100% 0% 0%)" }, { clipPath: "inset(0% 0% 0% 0%)", duration: 0.2, ease: "power4.out" }, t); break;
      default: tl.fromTo(e, { opacity: 0, y: 30 }, { opacity: 1, y: 0, duration: 0.25, ease: "power3.out" }, t);
    }
    if (o.shake) AG.shake(ctx, o.shake, t + 0.2, o.amp || 14);
  };
  K.breathe = function (ctx, e, t, dur, amt) { if (dur > 0.2) ctx.tl.to(e, { scale: 1 + (amt || 0.03), duration: dur, ease: "sine.inOut" }, t); };
  K.img = function (ctx, key) { var m = (ctx.spec.images || {})[key]; return m ? m.src : null; };

  // ---------------------------------------------------------------- fields (every one carries texture: a near-uniform frame reads as blank)
  K.field = function (ctx, S, kind, B) {
    var f = el("div", "k3-field k3-f-" + kind, S.cam);
    var from = B.from, dur = Math.max(0.2, B.to - B.from);
    if (kind === "red" || kind === "rays") {
      var r = el("div", "k3-rays", f); el("div", "k3-vig", f);
      ctx.tl.fromTo(r, { rotation: 0 }, { rotation: (B.i % 2 ? -1 : 1) * 18 * dur, duration: dur, ease: "none" }, from);
    } else {
      var d = el("div", "k3-tex", f);
      ctx.tl.fromTo(d, { x: 0, y: 0 }, { x: 34 * Math.round(dur), y: 34 * Math.round(dur), duration: dur, ease: "none" }, from);
      el("div", "k3-vig", f);
    }
    return f;
  };
  // A still behind or inside the beat, shown the look's way.
  K.plate = function (ctx, S, key, B, o) {
    o = o || {}; var src = K.img(ctx, key); if (!src) return null;
    var L = ctx.L, mode = o.mode || L.img, tl = ctx.tl, dur = Math.max(0.3, B.to - B.from);
    if (mode === "depth") return AG.depthPlate(ctx, S.cam, { src: src, from: B.from, to: B.to, motes: 22 });
    if (mode === "full") {
      var p = el("div", "k3-plate", S.cam), im = el("img", "", p); im.src = src;
      if (o.shade !== false) el("div", "k3-shade", S.cam);
      tl.fromTo(p, { scale: 1.2 }, { scale: 1.0, duration: 0.35, ease: "power3.out" }, B.from);
      tl.fromTo(im, { scale: 1, x: 0 }, { scale: 1.14, x: -34, duration: dur, ease: "none" }, B.from);
      return p;
    }
    // card / print / window: the still is an object on the field
    var box = el("div", "k3-still k3-still-" + mode, S.cam);
    box.style.top = (o.top || 250) + "px"; box.style.height = (o.h || 760) + "px";
    if (mode === "window") el("div", "k3-winbar", box, "<i></i><i></i><i></i><span>" + AG.esc(o.title || "image.jpg") + "</span>");
    var fr = el("div", "k3-still-img", box), im2 = el("img", "", fr); im2.src = src;
    if (mode === "print" && o.cap) el("div", "k3-still-cap", box, AG.esc(o.cap));
    K.enter(ctx, box, B.from + (o.delay || 0), mode === "print" ? "pin" : L.enter === "win" ? "win" : "pop", { rot: mode === "print" ? -2 : 0 });
    tl.fromTo(im2, { scale: 1.02 }, { scale: 1.12, duration: dur, ease: "none" }, B.from);
    return box;
  };
  // A cut-out object (keyed PNG) that drops in and floats.
  K.object = function (ctx, S, key, B, o) {
    var src = K.img(ctx, key); if (!src) return null;
    var w = el("div", "k3-obj" + (o.plain ? " plain" : ""), S.cam), im = el("img", "", w); im.src = src;
    w.style.left = (o.x !== undefined ? o.x : 140) + "px"; w.style.top = (o.y !== undefined ? o.y : 300) + "px"; w.style.width = (o.w || 800) + "px";
    var t = o.at !== undefined ? o.at : B.from;
    K.show(ctx, w, t);
    if (t > 0.05) ctx.tl.fromTo(w, { y: o.fromY || 900, rotation: -14 }, { y: 0, rotation: o.rot || 3, duration: 0.32, ease: "back.out(1.4)" }, t);
    ctx.tl.to(w, { rotation: -(o.rot || 3) / 2, y: -24, duration: Math.max(0.3, B.to - t - 0.35), ease: "sine.inOut" }, t + 0.33);
    return w;
  };

  // ---------------------------------------------------------------- shared furniture
  K.kicker = function (ctx, S, text, t, o) {
    o = o || {}; var k = el("div", "k3-kick" + (o.alt ? " alt" : ""), S.cam);
    K.setText(k, text, 960, o.size || 64, 0.5);
    k.style.top = (o.top || 170) + "px";
    K.enter(ctx, k, t, ctx.L.enter === "slam" ? "wipe" : ctx.L.enter === "blur" ? "blur" : "wipe");
    return k;
  };
  K.source = function (ctx, S, text, t, o) {
    o = o || {}; var s = el("div", "k3-src", S.cam);
    s.textContent = text; s.style.fontSize = Math.max(K.MIN_PX, o.size || 42) + "px";
    s.style.top = (o.top || 1180) + "px";
    K.enter(ctx, s, t, "wipe");
    return s;
  };
  K.stamp = function (ctx, S, o) {
    var st = el("div", "k3-stamp", S.cam), inner = el("div", "k3-stamp-in", st, AG.esc(o.text));
    inner.style.fontSize = K.fit(o.text, 900, o.size || 220, ctx.L.cw) + "px";
    st.style.top = (o.top || 820) + "px";
    K.show(ctx, st, o.at);
    var rot = o.rot === undefined ? -9 : o.rot;
    if (o.at <= 0.05) {   // hook frame: readable on frame 0, so a small settle instead of the 3x slam
      ctx.tl.fromTo(st, { xPercent: -50, scale: 1.14, rotation: rot - 3 }, { xPercent: -50, scale: 1, rotation: rot, duration: 0.2, ease: "power4.in" }, 0);
      AG.shake(ctx, S.cam, 0.2, 18);
    } else {
      ctx.tl.fromTo(st, { xPercent: -50, scale: 3.0, rotation: rot - 6 }, { xPercent: -50, scale: 1, rotation: rot, duration: 0.16, ease: "power4.in" }, o.at);
      AG.shake(ctx, S.cam, o.at + 0.16, 20);
    }
    ctx.tl.to(st, { scale: 1.05, duration: 1.2, ease: "sine.inOut" }, o.at + 0.2);
    if (o.grey) ctx.tl.to(S.cam, { filter: "grayscale(0.9) brightness(0.8)", duration: 0.2 }, o.at + 0.1);
    return st;
  };
  K.sticker = function (ctx, S, o) {
    var s = el("div", "k3-sticker" + (o.style ? " " + o.style : ""), S.cam);
    K.setText(s, o.text, 900, o.size || 100, ctx.L.cw);
    if (o.x !== undefined) s.style.left = o.x + "px"; else s.style.right = "60px";
    s.style.top = (o.y || 1040) + "px";
    K.enter(ctx, s, o.at, ctx.L.enter === "slam" ? "pop" : ctx.L.enter, { rot: o.rot === undefined ? 5 : o.rot, shake: S.cam, amp: 10 });
    return s;
  };
  K.overlays = function (ctx, S, list) {
    (list || []).forEach(function (o) {
      if (o.type === "stamp") K.stamp(ctx, S, o);
      else if (o.type === "sticker") K.sticker(ctx, S, o);
      else if (o.type === "source") K.source(ctx, S, o.text, o.at, o);
      else if (o.type === "kicker") K.kicker(ctx, S, o.text, o.at, o);
      else if (o.type === "object") K.object(ctx, S, o.image, S.beat, o);
      else if (o.type === "dim") { var d = el("div", "k3-dim", S.cam); d.style.zIndex = o.z || 35; K.show(ctx, d, o.at); if (o.at <= 0.05) d.style.opacity = 1; }
    });
  };
  // Big hero line on the field (or on a card where the look puts all text on paper).
  K.hero = function (ctx, S, text, t, o) {
    o = o || {}; var L = ctx.L;
    var wrap = el("div", "k3-hero" + (L.onField === "card" || o.card ? " on-card" : "") + (o.accent ? " acc" : ""), S.cam);
    var line = el("div", "k3-hero-t", wrap);
    K.setText(line, text, o.width || 960, o.size || 260, L.cw);
    wrap.style.top = (o.top || 300) + "px";
    if (o.align === "center") wrap.classList.add("center");
    K.enter(ctx, wrap, t, o.enter || (L.enter === "rise" ? "rise" : L.enter === "blur" ? "blur" : L.enter === "pin" ? "pin" : L.enter === "win" ? "win" : "slam"), { origin: "0% 100%", s: 1.6, shake: o.shake === false ? null : S.cam, amp: 16, rot: o.rot });
    return wrap;
  };
  K.label = function (ctx, S, text, t, o) {
    o = o || {}; var b = el("div", "k3-label" + (o.style ? " " + o.style : ""), S.cam);
    K.setText(b, text, o.width || 960, o.size || 84, ctx.L.cw * 0.95);
    b.style.top = (o.top || 600) + "px";
    if (o.x !== undefined) b.style.left = o.x + "px";
    K.enter(ctx, b, t, ctx.L.enter === "blur" ? "blur" : ctx.L.enter === "pin" ? "pin" : "wipe");
    return b;
  };
  // Seeded decorative rain (bills / coins / docs) that lands in stacks: money arriving, piles of paper.
  K.rain = function (ctx, S, kind, t, o) {
    o = o || {}; var st = el("div", "k3-rain k3-rain-" + kind, S.cam); st.style.top = (o.top || 760) + "px";
    var heights = o.heights || [7, 10, 13, 9, 12, 8], bi = 0;
    heights.forEach(function (h, ci) {
      var col = el("div", "k3-col", st); col.style.left = (ci * 158) + "px";
      for (var k = 0; k < h; k++) {
        var b = el("div", "k3-bill", col); b.style.bottom = (k * 30) + "px";
        var tt = t + bi * 0.02 + (k > 5 ? 0.35 : 0);
        K.show(ctx, b, tt);
        ctx.tl.fromTo(b, { y: -900 - k * 20, rotation: AG.sh(bi, 5) * 10 }, { y: 0, rotation: AG.sh(bi, 6) * 3, duration: 0.28, ease: "power3.in" }, tt);
        bi++;
      }
    });
    K.breathe(ctx, st, t + 1.4, 1.6, 0.03);
    return st;
  };
  // Words that ink in as they are spoken (quote / document bodies). sync: [[word, t, highlight]]
  K.inkWords = function (ctx, parent, sync, cls) {
    sync.forEach(function (w) {
      var s = el("span", "k3-iw", parent, AG.esc(w[0]));
      ctx.tl.fromTo(s, { opacity: 0.22 }, { opacity: 1, duration: 0.08, ease: "none" }, Math.max(0, w[1] - 0.03));
      if (w[2]) { var mk = el("b", "k3-mk", s); ctx.tl.set(mk, { scaleX: 0 }, 0); ctx.tl.to(mk, { scaleX: 1, duration: 0.22, ease: "power2.out" }, w[1] + 0.04); }
      parent.appendChild(document.createTextNode(" "));
    });
  };

  // ---------------------------------------------------------------- component catalogue
  var C = (K.C = {});

  // hook-frame: frame 0. The named subject + the huge number, readable on frame 0 with motion from frame 0.
  C["hook-frame"] = function (ctx, S, p, B) {
    var t0 = B.from;
    if (p.image) K.plate(ctx, S, p.image, B, { mode: p.imageMode || (ctx.L.img === "depth" ? "depth" : ctx.L.img === "card" || ctx.L.img === "window" || ctx.L.img === "print" ? ctx.L.img : "full"), top: 700, h: 760 });
    if (p.object) K.object(ctx, S, p.object, B, { x: p.objX || 140, y: p.objY || 640, w: p.objW || 800, at: t0, plain: p.objPlain });
    if (p.mark) {
      var m = el("div", "k3-mark", S.cam, AG.esc(p.mark)); m.setAttribute("data-layout-allow-overlap", "");
      ctx.tl.fromTo(m, { scale: 1.12 }, { scale: 0.97, duration: Math.max(0.5, B.to - B.from), ease: "power2.out" }, t0);
    }
    var stack = el("div", "k3-hook", S.cam); stack.style.top = (p.top || 160) + "px";
    if (p.kicker) { var k = el("div", "k3-hook-k", stack); K.setText(k, p.kicker, 960, 64, 0.5); }
    (p.lines || []).forEach(function (ln, i) {
      var cls = i === 0 ? "k3-hook-big" : (p.highlight === i ? "k3-hook-hl" : "k3-hook-sub");
      var e = el("div", cls, stack); K.setText(e, ln, 960, i === 0 ? (p.size || 214) : 128, ctx.L.cw);
      if (t0 <= 0.05) ctx.tl.fromTo(e, { x: i ? -30 : 0, scale: i ? 1 : 1.08, transformOrigin: "0% 50%" }, { x: 0, scale: 1, duration: 0.3, ease: "power4.out" }, 0.02 * i);
      else K.enter(ctx, e, t0 + i * 0.12, ctx.L.enter, { origin: "0% 50%", s: 1.5 });
    });
    if (p.stamp) K.stamp(ctx, S, { text: p.stamp.text, at: p.stamp.at !== undefined ? p.stamp.at : t0, top: p.stamp.top || 1000, rot: -9, size: p.stamp.size || 200 });
    K.breathe(ctx, stack, t0 + 0.5, Math.max(0.3, B.to - t0 - 0.6), 0.025);
  };

  // big-number-slam: a reported figure lands on its word. Never counts through intermediate numbers.
  C["big-number-slam"] = function (ctx, S, p, B) {
    if (p.image) K.plate(ctx, S, p.image, B, { top: 780, h: 520 });
    if (p.kicker) K.kicker(ctx, S, p.kicker, p.kickerAt !== undefined ? p.kickerAt : B.from + 0.05, { top: p.top ? p.top - 110 : 190 });
    var hv = K.hero(ctx, S, p.value, p.at, { top: p.top || 300, size: p.size || 330, accent: p.accent });
    if (p.label) K.label(ctx, S, p.label, p.labelAt !== undefined ? p.labelAt : p.at + 0.45, { top: (p.top || 300) + (p.size || 330) * 0.95 + 20, size: p.labelSize || 84, style: p.loss ? "down" : "hl" });
    if (p.source) K.source(ctx, S, p.source, p.sourceAt !== undefined ? p.sourceAt : p.at + 0.7, { top: p.sourceTop || (p.top || 300) + (p.size || 330) * 0.95 + 150 });
    if (p.deco && p.deco !== "none") K.rain(ctx, S, p.deco, p.decoAt !== undefined ? p.decoAt : B.from + 0.05, { top: p.decoTop || 760 });
    if (p.object) K.object(ctx, S, p.object, B, { x: p.objX || 560, y: p.objY || 700, w: p.objW || 480, at: p.objAt !== undefined ? p.objAt : p.at + 0.3 });
    K.breathe(ctx, hv, p.at + 0.3, Math.max(0.3, B.to - p.at - 0.4), 0.03);
  };

  // entity-card: the named company / person (monogram or cut-out, never an identifiable face for an allegation)
  C["entity-card"] = function (ctx, S, p, B) {
    if (p.image) K.plate(ctx, S, p.image, B, { top: 220, h: 700 });
    if (p.object) K.object(ctx, S, p.object, B, { x: p.objX || 130, y: p.objY || 230, w: p.objW || 820, at: B.from + 0.08 });
    var tag = el("div", "k3-ent", S.cam); tag.style.top = (p.top || 900) + "px";
    var k = p.kicker ? el("div", "k3-ent-k", tag) : null; if (k) K.setText(k, p.kicker, 900, 58, 0.5);
    if (p.monogram) { var mono = el("div", "k3-ent-mono", tag, AG.esc(p.monogram)); K.enter(ctx, mono, B.from + 0.05, "pop"); }
    var n = el("div", "k3-ent-n", tag); K.setText(n, p.name, 940, p.size || 190, ctx.L.cw);
    var r = p.role ? el("div", "k3-ent-r", tag) : null; if (r) K.setText(r, p.role, 940, 60, 0.52);
    if (k) K.enter(ctx, k, B.from + 0.1, "wipe");
    K.enter(ctx, n, p.at !== undefined ? p.at : B.from + 0.2, ctx.L.enter === "slam" ? "slam" : ctx.L.enter, { origin: "0% 50%", s: 1.7, shake: S.cam, amp: 12 });
    if (r) K.enter(ctx, r, p.roleAt !== undefined ? p.roleAt : (p.at || B.from) + 0.5, "wipe");
    K.breathe(ctx, tag, B.from + 0.6, Math.max(0.3, B.to - B.from - 0.7), 0.02);
  };

  // quote-card / clipping: an attributed statement whose words ink in as they are spoken.
  C["quote-card"] = function (ctx, S, p, B) {
    if (p.image) K.plate(ctx, S, p.image, B, {});
    if (p.image && ctx.L.img === "full") { var dk = el("div", "k3-dim", S.cam); dk.style.opacity = 0.45; dk.style.zIndex = 3; }
    if (p.year) { var yr = K.hero(ctx, S, p.year, p.yearAt !== undefined ? p.yearAt : B.from + 0.1, { top: 230, size: 360 }); ctx.tl.to(yr, { scale: 0.9, opacity: 0.55, duration: 0.3, transformOrigin: "0% 0%" }, (p.at || B.from) + 0.2); }
    else if (p.kicker) K.kicker(ctx, S, p.kicker, B.from + 0.05, {});
    var card = el("div", "k3-quote", S.cam); card.style.top = (p.top || (p.year ? 680 : 420)) + "px";
    var src = el("div", "k3-quote-src", card, AG.esc(p.source || ""));
    var body = el("div", "k3-quote-body", card);
    var n = (p.sync || []).reduce(function (a, w) { return a + w[0].length + 1; }, 0);
    body.style.fontSize = Math.max(K.MIN_PX, Math.min(p.size || 92, Math.floor(Math.sqrt((940 * 560) / Math.max(1, n) / 0.55)))) + "px";
    K.inkWords(ctx, body, p.sync || [], "");
    var t = p.at !== undefined ? p.at : B.from + 0.15;
    K.enter(ctx, card, t, ctx.L.enter === "slam" ? "pop" : ctx.L.enter, { rot: -1.5 });
    ctx.tl.to(card, { rotation: 0.5, y: -20, duration: Math.max(0.3, B.to - t - 0.3), ease: "sine.inOut" }, t + 0.3);
    if (!p.source) src.style.display = "none";
  };

  // statement: 1-3 huge words that slam on their spoken word ("Here's / THE LESSON").
  C["statement"] = function (ctx, S, p, B) {
    var box = el("div", "k3-stmt", S.cam); box.style.top = (p.top || 560) + "px";
    (p.lines || []).forEach(function (ln, i) {
      var e = el("div", "k3-stmt-l" + (ln.style ? " " + ln.style : i === (p.lines.length - 1) ? " acc" : ""), box);
      K.setText(e, ln.text, 960, ln.size || (i === p.lines.length - 1 ? 176 : 120), ctx.L.cw);
      K.enter(ctx, e, ln.at, ctx.L.enter === "blur" ? "blur" : ctx.L.enter === "rise" ? "rise" : "slam", { s: 2.2, shake: i === p.lines.length - 1 ? S.cam : null, amp: 18 });
    });
    K.breathe(ctx, box, (p.lines[p.lines.length - 1] || {}).at + 0.3, Math.max(0.3, B.to - B.from - 0.8), 0.04);
  };

  // comparison: A vs B. Both values slam; the winner gets the accent.
  C["comparison"] = function (ctx, S, p, B) {
    if (p.title) K.kicker(ctx, S, p.title, B.from + 0.05, {});
    var wrap = el("div", "k3-cmp", S.cam); wrap.style.top = (p.top || 330) + "px";
    [p.a, p.b].forEach(function (s, i) {
      var col = el("div", "k3-cmp-col" + ((p.winner === "a" && i === 0) || (p.winner === "b" && i === 1) ? " win" : ""), wrap);
      var bar = el("div", "k3-cmp-bar", col); bar.style.height = Math.round(120 + 620 * (s.h === undefined ? 0.5 : s.h)) + "px";
      var v = el("div", "k3-cmp-v", col); K.setText(v, s.value, 440, 170, ctx.L.cw);
      var l = el("div", "k3-cmp-l", col); K.setText(l, s.label, 440, 60, 0.52);
      var at = s.at !== undefined ? s.at : B.from + 0.2 + i * 0.4;
      K.show(ctx, col, at);
      ctx.tl.fromTo(bar, { scaleY: 0, transformOrigin: "50% 100%" }, { scaleY: 1, duration: 0.4, ease: "expo.out" }, at);
      K.enter(ctx, v, at + 0.15, "slam", { s: 1.8 });
      if (at > 0.05) ctx.tl.fromTo(l, { opacity: 0 }, { opacity: 1, duration: 0.2 }, at + 0.25);
    });
    if (p.source) K.source(ctx, S, p.source, (p.b.at || B.from + 0.6) + 0.5, { top: (p.top || 330) + 1000 });
  };

  // chart: line (rise / crash with a dot riding the draw front) or bars. Labels land on their words.
  C["chart"] = function (ctx, S, p, B) {
    if (p.image) K.plate(ctx, S, p.image, B, {});
    if (p.image && ctx.L.img === "full") { var dk = el("div", "k3-dim", S.cam); dk.style.opacity = 0.5; dk.style.zIndex = 3; }
    if (p.kicker) K.kicker(ctx, S, p.kicker, B.from + 0.05, {});
    if (p.tag) K.label(ctx, S, p.tag, p.tagAt !== undefined ? p.tagAt : B.from + 0.2, { top: 262, size: 120, style: "box" });
    var top = p.top || 470;
    var card = el("div", "k3-chart-card", S.cam); card.style.top = top + "px";
    if (p.title) { var tt = el("div", "k3-chart-t", card); K.setText(tt, p.title, 900, 58, 0.5); }
    var at = p.at !== undefined ? p.at : B.from + 0.25;
    K.enter(ctx, card, B.from + 0.05, ctx.L.enter === "slam" ? "wipe" : ctx.L.enter);
    if ((p.kind || "line") === "line") {
      var st = getComputedStyle(ctx.root);
      AG.lineChart(ctx, S.cam, { at: at, top: top + 140, left: 110, w: 860, h: 420, upDur: p.upDur || 0.7, downAt: p.downAt, downDur: p.downDur || 0.3, peak: p.peak,
        pts: p.pts || [[0, 0.06], [1, 0.9]], upColor: "var(--k3-up)", downColor: "var(--k3-down)", grid: "var(--k3-grid)",
        labels: (p.labels || []).map(function (L) { return { x: L.x, y: L.y, text: L.text, at: L.at, style: L.down ? "background:var(--k3-down);color:#fff" : "" }; }) });
    } else {
      var bars = p.bars || [], bw = Math.floor(820 / Math.max(1, bars.length));
      var max = Math.max.apply(null, bars.map(function (b) { return b.h || 0.5; }));
      bars.forEach(function (b, i) {
        var col = el("div", "k3-bar" + (b.accent ? " acc" : ""), card);
        col.style.left = (40 + i * bw + bw * 0.12) + "px"; col.style.width = Math.floor(bw * 0.76) + "px"; col.style.height = Math.round(440 * (b.h || 0.5) / max) + "px";
        var v = el("div", "k3-bar-v", col); K.setText(v, b.text || "", bw * 1.1, 76, ctx.L.cw);
        var l = el("div", "k3-bar-l", col); K.setText(l, b.label || "", bw * 1.1, 46, 0.5);
        var bt = b.at !== undefined ? b.at : at + i * 0.3;
        K.show(ctx, col, bt);
        ctx.tl.fromTo(col, { scaleY: 0, transformOrigin: "50% 100%" }, { scaleY: 1, duration: 0.45, ease: "expo.out" }, bt);
        if (bt > 0.05) ctx.tl.fromTo(v, { opacity: 0, y: 20 }, { opacity: 1, y: 0, duration: 0.2 }, bt + 0.35);
      });
    }
    if (p.source) K.source(ctx, S, p.source, p.sourceAt !== undefined ? p.sourceAt : at + 0.6, { top: p.sourceTop || 222 });
  };

  // map: Natural Earth land, a route draws place to place, the camera rides it and lands on the pin.
  C["map"] = function (ctx, S, p, B) {
    var M = window.AG_MAP; if (!M) return;
    var wrap = el("div", "k3-map", S.cam), plane = el("div", "k3-map-plane", wrap);
    var sv = AG.svg("svg", { width: M.w, height: M.h, viewBox: "0 0 " + M.w + " " + M.h }, plane);
    for (var lon = -180; lon <= 180; lon += 10) { var x = M.project(lon, 0)[0]; AG.svg("line", { x1: x, x2: x, y1: 0, y2: M.h, class: "k3-map-grid" }, sv); }
    for (var lat = -60; lat <= 80; lat += 10) { var y = M.project(0, lat)[1]; AG.svg("line", { x1: 0, x2: M.w, y1: y, y2: y, class: "k3-map-grid" }, sv); }
    AG.svg("path", { d: M.land, class: "k3-map-land" }, sv);
    var pts = (p.places || []).map(function (q) { return { q: q, xy: M.project(q.lon, q.lat) }; });
    var route = null, a = pts[0], b = pts[pts.length - 1];
    if (pts.length > 1 && p.route !== false) {
      var mid = [(a.xy[0] + b.xy[0]) / 2, (a.xy[1] + b.xy[1]) / 2 - Math.hypot(b.xy[0] - a.xy[0], b.xy[1] - a.xy[1]) * 0.25];
      route = AG.svg("path", { d: "M" + a.xy[0] + " " + a.xy[1] + " Q" + mid[0] + " " + mid[1] + " " + b.xy[0] + " " + b.xy[1], class: "k3-map-route" }, sv);
    }
    pts.forEach(function (P, i) {
      var c = AG.svg("circle", { cx: P.xy[0], cy: P.xy[1], r: 9, class: i === pts.length - 1 ? "k3-map-pin acc" : "k3-map-pin" }, sv);
      var tx = AG.svg("text", { x: P.xy[0] + 16, y: P.xy[1] - 16, class: "k3-map-lbl" }, sv); tx.textContent = P.q.label || "";
      var at = P.q.at !== undefined ? P.q.at : B.from + 0.1 + i * 0.6;
      K.show(ctx, c, at); K.show(ctx, tx, at);
      if (at > 0.05) ctx.tl.fromTo(c, { attr: { r: 40 } }, { attr: { r: 9 }, duration: 0.3, ease: "back.out(2)" }, at);
    });
    var RS = p.routeAt !== undefined ? p.routeAt : B.from + 0.3, RE = RS + (p.routeDur || 1.4);
    if (route) AG.drawOn(ctx, route, RS, RE - RS, "power1.inOut");
    // camera: frame both places, then push onto the destination
    var z0 = p.zoomFrom || 1.2, z1 = p.zoomTo || 3.2, lenR = route ? route.getTotalLength() : 0, E = AG.ease("power1.inOut");
    AG.onFrame(ctx, function (t) {
      var u = E(AG.clamp((t - RS) / (RE - RS), 0, 1));
      var hx = a.xy[0], hy = a.xy[1];
      if (route) { var h = route.getPointAtLength(lenR * u); hx = h.x; hy = h.y; }
      var push = AG.clamp((t - RE) / Math.max(0.3, B.to - RE), 0, 1);
      var sc = z0 + (z1 - z0) * (u * 0.5 + push * 0.5);
      plane.style.transform = "translate(" + (540 - hx * sc).toFixed(1) + "px," + (820 - hy * sc).toFixed(1) + "px) scale(" + sc.toFixed(3) + ")";
    });
    el("div", "k3-map-fade", wrap);
    if (p.kicker) K.kicker(ctx, S, p.kicker, B.from + 0.1, {});
    if (p.title) K.label(ctx, S, p.title, p.titleAt !== undefined ? p.titleAt : RE, { top: 1120, size: 96, style: "box" });
  };

  // call-grid: a live video call (tiles with webcam grade, name chips, mic icons). No real faces: stills are generated.
  C["call-grid"] = function (ctx, S, p, B) {
    var n = (p.tiles || []).length || 4, cols = n > 4 ? 3 : 2, tw = Math.floor((960 - (cols - 1) * 20) / cols), th = Math.floor(tw * 1.1);
    var g = el("div", "k3-grid", S.cam); g.style.top = (p.top || 300) + "px";
    if (p.kicker) K.kicker(ctx, S, p.kicker, B.from + 0.05, {});
    (p.tiles || []).forEach(function (T, i) {
      var tile = el("div", "k3-tile", g);
      tile.style.left = ((i % cols) * (tw + 20)) + "px"; tile.style.top = (Math.floor(i / cols) * (th + 20)) + "px"; tile.style.width = tw + "px"; tile.style.height = th + "px";
      var src = T.image ? K.img(ctx, T.image) : null;
      if (src) { var im = el("img", "", tile); im.src = src; } else el("div", "k3-tile-mono", tile, AG.esc((T.label || "?").slice(0, 2).toUpperCase()));
      var chip = el("div", "k3-tile-chip", tile); chip.textContent = T.label || ""; chip.style.fontSize = "42px";
      var at = T.at !== undefined ? T.at : B.from + 0.1 + i * 0.25;
      K.enter(ctx, tile, at, "pop");
      AG.onFrame(ctx, function (t) { var f = Math.floor(t * 30); tile.style.filter = "brightness(" + (0.95 + 0.07 * AG.hash(f + i * 17, 3)).toFixed(3) + ") contrast(1.05)"; });
      if (T.tag) { var tg = el("div", "k3-tile-tag", tile, AG.esc(T.tag)); var ta = T.tagAt !== undefined ? T.tagAt : at + 0.6; K.show(ctx, tg, ta); if (ta > 0.05) ctx.tl.fromTo(tg, { scale: 1.6 }, { scale: 1, duration: 0.18, ease: "power4.in" }, ta); }
    });
    if (p.banner) K.label(ctx, S, p.banner.text, p.banner.at, { top: (p.top || 300) + Math.ceil(n / cols) * (th + 20) + 20, size: 88, style: "down" });
  };

  // document: browser / paper / email / phone / terminal. Typed prompt, inked body, a badge, verdict stickers, strike, click.
  C["document"] = function (ctx, S, p, B) {
    var kind = p.kind || "browser", tl = ctx.tl;
    if (p.kicker) K.kicker(ctx, S, p.kicker, B.from + 0.05, { top: 150 });
    var d = el("div", "k3-doc k3-doc-" + kind, S.cam); d.style.top = (p.top || (kind === "phone" ? 250 : 260)) + "px";
    if (kind === "phone") { el("div", "k3-notch", d); }
    else { var bar = el("div", "k3-doc-bar", d, "<i></i><i></i><i></i>"); if (p.title) el("span", "", bar, AG.esc(p.title)); }
    var body = el("div", "k3-doc-body", d);
    K.show(ctx, d, B.from);
    if (B.from > 0.05) tl.fromTo(d, { y: kind === "phone" ? 700 : -900, rotation: kind === "phone" ? 6 : 0 }, { y: 0, rotation: kind === "phone" ? -2 : 0, duration: 0.3, ease: "back.out(1.2)" }, B.from);
    tl.to(d, { rotation: kind === "phone" ? 1 : 0, y: -14, duration: Math.max(0.3, B.to - B.from - 0.35), ease: "sine.inOut" }, B.from + 0.35);
    if (p.from || p.subject) { var hd = el("div", "k3-doc-head", body); if (p.from) el("b", "", hd, AG.esc(p.from)); if (p.subject) el("span", "", hd, AG.esc(p.subject)); }
    if (p.badge) { var bg = el("div", "k3-badge", body, AG.esc(p.badge.text)); K.enter(ctx, bg, p.badge.at, "pop", { rot: -2 }); tl.fromTo(bg, { boxShadow: "0 0 30px var(--k3-glow)" }, { boxShadow: "0 0 110px var(--k3-glow)", duration: 0.6, ease: "sine.inOut", yoyo: true, repeat: 3 }, p.badge.at + 0.3); }
    if (p.prompt) {
      var bub = el("div", "k3-bubble", body); var msg = p.prompt.text, pa = p.prompt.at, pd = p.prompt.dur || 1.5;
      K.show(ctx, bub, pa);
      tl.fromTo(bub, { scale: 0.4, transformOrigin: "100% 100%" }, { scale: 1, duration: 0.18, ease: "back.out(2)" }, pa);
      AG.onFrame(ctx, function (t) { var q = AG.clamp((t - pa - 0.1) / pd, 0, 1); bub.textContent = msg.slice(0, Math.max(1, Math.round(q * msg.length))); });
    }
    if (p.sync && p.sync.length) { var tx = el("div", "k3-doc-text", body); tx.style.fontSize = (p.size || 64) + "px"; K.inkWords(ctx, tx, p.sync, ""); }
    for (var i = 0; i < (p.lines || 0); i++) { var ln = el("div", "k3-doc-line", body); ln.style.width = (40 + 50 * AG.hash(i, 31)) + "%"; }
    if (p.build) {
      [["head", -500], ["card", 500], ["btn", -500]].forEach(function (bk, j) {
        var e = el("div", "k3-ui k3-ui-" + bk[0], body); var at = p.build.at + j * 0.17;
        K.show(ctx, e, at); tl.fromTo(e, { x: bk[1], rotation: bk[1] > 0 ? 10 : -10 }, { x: 0, rotation: 0, duration: 0.22, ease: "back.out(1.6)" }, at);
      });
    }
    if (p.strike) {
      var sv = AG.svg("svg", { viewBox: "0 0 100 100", preserveAspectRatio: "none", class: "k3-strike" }, d);
      var x1 = AG.stroke(sv, "M6 6 L94 94", { color: "var(--k3-down)", w: 7 }), x2 = AG.stroke(sv, "M94 6 L6 94", { color: "var(--k3-down)", w: 7 });
      AG.drawOn(ctx, x1, p.strike.at, 0.14, "power3.out"); AG.drawOn(ctx, x2, p.strike.at + 0.14, 0.14, "power3.out");
    }
    if (p.click) {
      var cur = AG.svg("svg", { viewBox: "0 0 90 120", class: "k3-cursor" }, S.cam);
      AG.svg("path", { d: "M6 4 L6 96 L30 74 L46 112 L62 104 L46 68 L80 66 Z", fill: "#fff", stroke: "#0d0d0d", "stroke-width": 7, "stroke-linejoin": "round" }, cur);
      K.show(ctx, cur, p.click.at - 0.7);
      tl.fromTo(cur, { x: 980, y: 1500 }, { x: p.click.x || 640, y: p.click.y || 610, duration: 0.65, ease: "power3.out" }, p.click.at - 0.7);
      tl.to(cur, { scale: 0.85, duration: 0.06, yoyo: true, repeat: 1 }, p.click.at);
    }
    (p.stickers || []).forEach(function (s) { K.sticker(ctx, S, s); });
  };

  // checklist: "what to do" items tick as they are spoken.
  C["checklist"] = function (ctx, S, p, B) {
    var ck = el("div", "k3-check", S.cam); ck.style.top = (p.top || 270) + "px";
    var ttl = el("div", "k3-check-t", ck); K.setText(ttl, p.title || "What to do", 900, 110, ctx.L.cw);
    K.show(ctx, ck, B.from + 0.05);
    ctx.tl.fromTo(ck, { y: 1300 }, { y: 0, duration: 0.3, ease: "back.out(1.3)" }, B.from + 0.05);
    ctx.tl.fromTo(ttl, { scaleX: 0, transformOrigin: "0% 50%" }, { scaleX: 1, duration: 0.22, ease: "power3.out" }, B.from + 0.2);
    (p.items || []).forEach(function (it, i) {
      var row = el("div", "k3-check-it", ck), bx = el("div", "k3-check-bx", row), tx = el("div", "k3-check-tx", row, AG.esc(it.text));
      tx.style.fontSize = Math.max(K.MIN_PX, Math.min(72, Math.floor(1900 / Math.max(20, it.text.length)))) + "px";
      var sv = AG.svg("svg", { viewBox: "0 0 100 100" }, bx), pth = AG.stroke(sv, "M14 52 L42 82 L94 8", { color: "var(--k3-up)", w: 16 });
      var at = it.at !== undefined ? it.at : B.from + 0.5 + i * 0.8, tick = it.tickAt !== undefined ? it.tickAt : at + 0.3;
      K.show(ctx, row, at);
      ctx.tl.fromTo(row, { x: 700 }, { x: 0, duration: 0.2, ease: "power4.out" }, at);
      AG.drawOn(ctx, pth, tick, 0.18, "power3.out");
      ctx.tl.fromTo(bx, { scale: 1.35 }, { scale: 1, duration: 0.22, ease: "back.out(3)" }, tick + 0.1);
    });
    var last = (p.items || []).slice(-1)[0];
    K.breathe(ctx, ck, (last && last.tickAt ? last.tickAt : B.from + 1) + 0.3, Math.max(0.3, B.to - B.from - 2), 0.035);
  };

  // cta-card: the programme CTA in the look's own button language, tapped on its word.
  C["cta-card"] = function (ctx, S, p, B) {
    var at = p.at !== undefined ? p.at : B.from + 0.03;
    var box = (ctx.L.cap === "ag2" ? AG2.cta : AG.cta)(ctx, S.cam, { at: at, pressDelay: p.pressDelay || 1.5, end: B.to, handle: p.handle || "@agmm" });
    if (p.sub) { var s = el("div", "k3-cta-sub", box, AG.esc(p.sub.text)); K.show(ctx, s, p.sub.at); ctx.tl.fromTo(s, { y: 40 }, { y: 0, duration: 0.25, ease: "back.out(2)" }, p.sub.at); }
    // 25 Sep: reviewers held S11/S29 because the card said less than the voice and never showed the audit link.
    // `line` = the spoken CTA sentence (word-synced when lineWords is given); `link` = the audit URL, on by default.
    if (p.line) {
      var ln = el("div", "k3-cta-line", box, "");
      if (p.lineWords && K.syncInk) { K.syncInk(ctx, ln, p.line, p.lineWords); }
      else { ln.textContent = p.line; K.show(ctx, ln, p.lineAt !== undefined ? p.lineAt : at); }
    }
    if (p.link !== false) {
      var lk = el("div", "k3-cta-link", box, AG.esc(p.link || "agmm.co.uk/ai-constraint-audit"));
      var lat = p.linkAt !== undefined ? p.linkAt : at + (p.pressDelay || 1.5) + 0.2;
      K.show(ctx, lk, lat); ctx.tl.fromTo(lk, { y: 30, opacity: 0 }, { y: 0, opacity: 1, duration: 0.3, ease: "power3.out" }, lat);
    }
  };

  // custom / scene: bespoke code written for THIS short (specs/<ID>/scenes.js registers AGK.scenes[name]).
  // The catalogue above is infrastructure; a production short is mostly scenes (build_short.py enforces >=60%).
  K.scenes = K.scenes || {};
  C["custom"] = C["scene"] = function (ctx, S, p, B) {
    var name = p.scene || p.module, f = K.scenes[name] || K.sig[name];
    if (!f) throw new Error("scene not loaded: " + name);
    f(ctx, S, p, B, K);
  };

  // ---------------------------------------------------------------- transitions (content-safe: both scenes are built)
  K.flash = function (ctx, t, peak) {
    var f = el("div", "k3-flash", ctx.root);
    ctx.tl.set(f, { opacity: 0 }, 0);
    ctx.tl.set(f, { opacity: Math.min(0.24, peak || 0.24) }, t);
    ctx.tl.to(f, { opacity: 0, duration: 0.06, ease: "power1.out" }, t + 1 / 30);
  };
  K.seam = function (ctx, t, A, B, kind) {
    if (!A || kind === "none") return;
    if (kind === "flash") { K.flash(ctx, t); return; }
    if (kind === "push") { AG.tx.push(ctx, t, A, B, { dur: 0.46, dir: (Math.round(t * 10) % 2) ? "left" : "up" }); return; }
    if (kind === "whip") { AG.tx.whip(ctx, t, A, B, { dur: 0.42 }); return; }
    if (kind === "glitch") { AG.tx.glitch(ctx, t, A, B, { half: 0.08 }); return; }
    if (kind === "fade") { ctx.tl.set(B, { opacity: 1, zIndex: 0 }, t - 0.3); ctx.tl.set(A, { zIndex: 5 }, t - 0.3); ctx.tl.fromTo(A, { opacity: 1 }, { opacity: 0, duration: 0.3, ease: "sine.inOut", immediateRender: false }, t - 0.3); ctx.tl.set(A, { zIndex: 0 }, t + 0.01); return; }
    // "cut": hard cut, nothing to add
  };

  // ---------------------------------------------------------------- the runtime
  K.run = function (spec) {
    var ctx = AG.init(spec.id);
    ctx.spec = spec; ctx.L = K.LOOKS[spec.look];
    if (!ctx.L) throw new Error("unknown look " + spec.look);
    var scenes = [];
    if (spec.world && K.scenes[spec.world]) K.scenes[spec.world](ctx, spec, K);   // a whole-short world (one board, one camera)
    spec.beats.forEach(function (B, i) {
      var next = spec.beats[i + 1];
      // craft ledger 28 Sep: 34 text-on-text seams on 11 shorts came from this 0.5 s default hold. With
      // spec.kit_defaults >= "2026-09-28" the outgoing scene is hidden ON the cut unless the beat sets "hold".
      var KD = !!(spec.kit_defaults && String(spec.kit_defaults) >= "2026-09-28");
      var hold = B.hold !== undefined ? B.hold : (KD ? 0.001 : 0.5);
      var S = AG.scene(ctx, B.id, B.from, next ? next.from + hold : null, { drift: false });
      S.beat = B;
      // continuous camera drift: no held stills (gate check 3); a scene that runs its own camera sets drift:false
      if (B.drift !== false) AG.drift(ctx, S.cam, B.from, B.to, { s0: 1.0, s1: B.zoom || 1.045, y1: -18, x1: (i % 2 ? 12 : -12) });
      if (B.field !== "none") K.field(ctx, S, B.field || ctx.L.field, B);
      if (B.bg) K.plate(ctx, S, B.bg, B, { mode: B.bgMode });
      var comp = C[B.comp];
      if (!comp) throw new Error("unknown component " + B.comp);
      comp(ctx, S, B.props || {}, B);
      if (B.extend) {   // bespoke layer on a catalogue beat (counts the beat as modified)
        var xf = K.scenes[B.extend];
        if (!xf) throw new Error("extend scene not loaded: " + B.extend);
        xf(ctx, S, B.props || {}, B, K);
      }
      K.overlays(ctx, S, B.overlays);
      scenes.push(S);
    });
    // seams after every scene exists (an incoming scene is never empty at its seam)
    spec.beats.forEach(function (B, i) { if (i > 0) K.seam(ctx, B.from, scenes[i - 1], scenes[i], B.tx || ctx.L.tx); });
    (ctx.after || []).forEach(function (f) { f(); });   // world finalisers (e.g. one camera path built from every beat's keys)
    // captions: one phrase track per window where the picture is not already the words
    var W = spec.words;
    (spec.captions || []).forEach(function (w) {
      if (ctx.L.cap === "ag2") AG2.captions(ctx, ctx.stage, W, { from: w.from, to: w.to, top: w.top || 1290, height: w.height || 300 });
      else AG.captions(ctx, ctx.stage, W, { from: w.from, to: w.to, top: w.top || 1290, height: w.height || 260 });
    });
    if (ctx.L.grain) AG.grain(ctx, ctx.root, ctx.L.grain);
    var tl = AG.finish(ctx, spec.dur);
    // part window: this project renders [off, off+dur) of the story clock; parts join by stream copy
    var P = window.AGK_PART || { off: 0, dur: spec.dur };
    var cur = 0;
    var proxy = { u: function (v) { if (v === undefined) return cur; cur = v; tl.time(P.off + v); } };
    var outer = gsap.timeline({ paused: true });
    outer.to(proxy, { u: P.dur, duration: P.dur, ease: "none" }, 0);
    // force the window's first frame now (a seek(0) on a timeline at 0 renders nothing) WITHOUT visiting the end:
    // the P1 warm-up progress(1)/progress(0) reverted every fromTo whose property lives only in its from-vars, and
    // S11 r1 rendered every typed caption word invisible (proved in the browser, 24 Sep)
    proxy.u(Math.min(0.001, P.dur)); proxy.u(0);
    window.__storyTL = tl;
    window.__timelines[spec.id] = outer;
    return ctx;
  };
})();
