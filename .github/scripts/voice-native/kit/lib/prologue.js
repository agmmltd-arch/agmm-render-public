/* AGMM scene prologue (kit/lib/prologue.js), extracted 6 Oct 2026 from the copy-pasted head of the approved scenes.js files
   (S83 is the reference: the helpers below are its own, byte-for-byte in behaviour; the proof is in
   buzz-gap/fix-world-modules.md: S83 rebuilt on this file, frames diffed against the original package).

   What it is: the 40-70 line block that 76 hand-built scenes.js files re-type: el, pos, clamp, lerp, ease, eout, H, seg,
   showAt, hideAt, float, fit/fitNow, boot (fonts + fit loop), hero, kick, plus the CSS for hero and kick.
   What it is NOT: a look. Colours, fonts and the halo come in as a theme, so two shorts built on it do not share a style.

   Load order in spec.json "code": ["lib/prologue.js", ...worlds, "specs/<ID>/scenes.js"]  (paths are relative to kit/).

   Use:
     var P = AGP.make("x12", { ink: "#0d2340", accent: { r: "#d5281b", b: "#005eb8", g: "#0b7a45" },
                               heroFont: "AG Anton", kickFont: "AG Plex Mono", halo: "238,245,250", right: 856 });
     P.hero(ctx, S, B, 'UNDER <span class="r">4</span> MINUTES', 96, 388, 260, { w: 760, slam: true });
     P.kick(ctx, S, B, "NHS AI SCRIBE", 96, 328, { size: 46, color: P.theme.accent.b });
   Every function is a pure function of timeline time (no Math.random, no clocks). */
(function (root) {
  "use strict";
  var AGP = root.AGP = root.AGP || {};

  // ------------------------------------------------------------------ small helpers (identical to the S83 head)
  function el(tag, cls, parent, html) { return AG.el(tag, cls, parent, html); }
  function sv(tag, attrs, parent) { return AG.svg(tag, attrs, parent); }
  function pos(e, x, y, w, h) { e.style.left = x + "px"; e.style.top = y + "px"; if (w !== undefined) e.style.width = w + "px"; if (h !== undefined) e.style.height = h + "px"; if (!e.style.position) e.style.position = "absolute"; return e; }
  function H(n, s) { return AG.hash(n, s || 3); }
  function clamp(v, a, b) { return Math.max(a, Math.min(b, v)); }
  function lerp(a, b, p) { return a + (b - a) * p; }
  function ease(p) { p = clamp(p, 0, 1); return 0.5 - 0.5 * Math.cos(Math.PI * p); }
  function eout(p) { p = clamp(p, 0, 1); return 1 - Math.pow(1 - p, 3); }
  function seg(t, a, b) { return clamp((t - a) / Math.max(1e-6, b - a), 0, 1); }
  function f1(v) { return v.toFixed(1); }
  function live(B, t) { return t >= B.from - 0.05 && t <= B.to + 0.1; }
  // visible from time t (frame-0 safe: at t <= 0.05 it is simply visible)
  function showAt(ctx, e, t) { if (t <= 0.05) { e.style.opacity = 1; return; } ctx.tl.set(e, { opacity: 0 }, 0); ctx.tl.set(e, { opacity: 1 }, t); }
  // hidden exactly on t (the seam: the incoming layer shows at the same instant)
  function hideAt(ctx, e, t) { ctx.tl.set(e, { opacity: 0 }, t); }
  function onCut(S, at) { return Math.abs(at - (S.from === undefined ? -9 : S.from)) < 0.06; }
  // visibility-based show/hide (S83 style): at/until are absolute story seconds
  function show(ctx, e, at, until) { if (at !== undefined && at > 0) { ctx.tl.set(e, { visibility: "hidden" }, 0); ctx.tl.set(e, { visibility: "visible" }, at); } if (until !== undefined) ctx.tl.set(e, { visibility: "hidden" }, until); }
  // everything the beat holds floats a little (two sines per axis, set via left/top so no camera transform is touched)
  function float(ctx, B, e, a) { a = a || 1; AG.onFrame(ctx, function (t) { if (!live(B, t)) return; e.style.left = f1((Math.sin(t * 0.9 + B.from) * 7 + Math.sin(t * 2.3 + 1.1) * 3) * a) + "px"; e.style.top = f1((Math.sin(t * 0.7 + 0.5) * 6 + Math.sin(t * 1.9) * 3) * a) + "px"; }); }

  AGP.util = { el: el, sv: sv, pos: pos, H: H, clamp: clamp, lerp: lerp, ease: ease, eout: eout, seg: seg, f1: f1, live: live,
               showAt: showAt, hideAt: hideAt, onCut: onCut, show: show, float: float };

  // ------------------------------------------------------------------ polish set (12 Oct 2026, card "polish-shorts"; tools/polish_check.py is the check that fails without it)
  // Sam, 12 Oct: "make sure all motion graphics and all the tiny detail visuals are perfect - each video has been about 85% clean."
  // The 15% was measured on 8 posted shorts (monday-recovery/polish-shorts.md). The commonest micro-defects and their fix here:
  //   pop      an element appears or leaves in ONE frame mid-beat      -> AGP.motion.enter / exit / swap (6-10 frames, eased, never a bare opacity set)
  //   linear / snap   a move at constant speed, or arriving in 1-3 frames -> the same helpers: ease-out-cubic in, ease-in cubic out
  //   widow    a wrapped block ends on ONE word                        -> AGP.motion.widow(el)  (glues the last two words)
  //   drift    stacked siblings that miss a shared edge by 1-6 px     -> AGP.motion.align(els, "left"|"center", x)  (one left/centre for the group)
  //   cut jump a persisting object shifts at a beat cut                -> AGP.motion.carry(prevCamEnd) : start the next scene's camera exactly where the last one ended
  // Frames, not seconds, are the unit: 30 fps, so 6 frames = 0.2 s, 10 frames = 0.333 s. Everything is a pure function of timeline time.
  var FR = 1 / 30;
  var M = AGP.motion = {
    FR: FR,
    // the standard durations (frames): ENTER 8 (min 6), EXIT 6 (min 4), SWAP 7
    ENTER: 8 * FR, EXIT: 6 * FR, SWAP: 7 * FR,
    // GSAP eases: enter = ease-out-cubic, exit = ease-in-cubic, swap = in-out sine (never "none"/"linear" on a visible entrance)
    EASE_IN: "power3.out", EASE_OUT: "power3.in", EASE_SWAP: "sine.inOut",
    // enter(ctx, e, t, o): fades 0 -> 1 while it travels `dist` px (default 28) from `from` ("up" rises, "down", "left", "right", "scale", "blur", "none"),
    //   over o.dur (default 8 frames, never under 6). Hidden until t. At t <= 0.05 (the hook frame) it is simply visible: frame 0 is never blank.
    enter: function (ctx, e, t, o) {
      o = o || {}; var d = Math.max(6 * FR, o.dur || M.ENTER), dist = o.dist === undefined ? 28 : o.dist, tl = ctx.tl, from = o.from || "up";
      if (t <= 0.05) { return; }
      var f = { opacity: 0 }, to = { opacity: 1, duration: d, ease: o.ease || M.EASE_IN, immediateRender: false, overwrite: false };
      if (from === "up") f.y = dist; else if (from === "down") f.y = -dist; else if (from === "left") f.x = dist; else if (from === "right") f.x = -dist;
      else if (from === "scale") { f.scale = o.s || 0.92; f.transformOrigin = o.origin || "50% 50%"; to.scale = 1; }
      else if (from === "blur") { f.filter = "blur(10px)"; to.filter = "blur(0px)"; }
      if (f.y !== undefined) to.y = 0; if (f.x !== undefined) to.x = 0;
      tl.set(e, { opacity: 0 }, 0);
      tl.fromTo(e, f, to, t);
    },
    // exit(ctx, e, t, o): 1 -> 0 over o.dur (default 6 frames, never under 4) with a small drift, ease-in. t is when it STARTS to leave.
    exit: function (ctx, e, t, o) {
      o = o || {}; var d = Math.max(4 * FR, o.dur || M.EXIT), dist = o.dist === undefined ? 14 : o.dist, to = { opacity: 0, duration: d, ease: o.ease || M.EASE_OUT, immediateRender: false };
      var dir = o.to || "up"; if (dir === "up") to.y = -dist; else if (dir === "down") to.y = dist; else if (dir === "left") to.x = -dist; else if (dir === "right") to.x = dist; else if (dir === "scale") to.scale = o.s || 0.96;
      ctx.tl.to(e, to, t);
    },
    // swap(ctx, a, b, t, o): a leaves while b arrives over the same SWAP window, in the same place (a card whose text changes, a state change).
    //   a/b are the two elements (b is hidden until t). Replaces the one-frame opacity swap that polish_check calls a pop.
    swap: function (ctx, a, b, t, o) {
      o = o || {}; var d = Math.max(6 * FR, o.dur || M.SWAP);
      ctx.tl.set(b, { opacity: 0 }, 0);
      ctx.tl.to(a, { opacity: 0, duration: d, ease: M.EASE_SWAP, immediateRender: false }, t);
      ctx.tl.to(b, { opacity: 1, duration: d, ease: M.EASE_SWAP, immediateRender: false }, t);
    },
    // blurIn(ctx, e, t, o): the reveal for "this was hidden, now it is shown" (a blurred card that sharpens): blur 10px -> 0 + fade over 10 frames.
    blurIn: function (ctx, e, t, o) { M.enter(ctx, e, t, { from: "blur", dur: (o && o.dur) || 10 * FR, ease: "sine.out" }); },
    // widow(el): the last two words stay together, so a wrapped block never ends on ONE word (4+ words only).
    widow: function (e) {
      var tx = e.textContent; if (!tx) return e; var w = tx.trim().split(/\s+/); if (w.length < 4) return e;
      var last = w.pop(), prev = w.pop(); e.textContent = w.join(" ") + (w.length ? " " : "") + prev + " " + last; return e;
    },
    // align(els, "left"|"center"|"right", x, w): one shared edge for a stacked group, whole pixels (no 1-6 px near-misses).
    //   "left": left = x.  "right": right edge at x (right = x px from the stage's left via left = x - w).  "center": centred on x in a box w wide (default 760).
    align: function (els, how, x, w) {
      [].concat(els).forEach(function (e) {
        e.style.position = e.style.position || "absolute"; w = w || 760;
        if (how === "center") { e.style.width = w + "px"; e.style.left = Math.round(x - w / 2) + "px"; e.style.textAlign = "center"; }
        else if (how === "right") { e.style.width = w + "px"; e.style.left = Math.round(x - w) + "px"; e.style.textAlign = "right"; }
        else { e.style.left = Math.round(x) + "px"; e.style.textAlign = "left"; }
      });
    },
    // grid(v): snap a spacing/size to the 8 px grid (gaps between stacked siblings should be equal and on-grid)
    grid: function (v) { return Math.round(v / 8) * 8; },
    // carry(prev): when an object PERSISTS across a beat cut, give the next scene's camera the transform the last one ended on, so the object does
    //   not step. prev = {scale, x, y} (read the end values of the previous beat's camera tween). Returns the CSS for S.cam.
    carry: function (prev) { prev = prev || {}; return "scale(" + (prev.scale || 1) + ") translate(" + (prev.x || 0) + "px," + (prev.y || 0) + "px)"; },
    // press(ctx, e, t, o): a chip or key lights: colour ramps over 4 frames instead of switching in one (colour pop). from/to are CSS colours.
    lit: function (ctx, e, t, from, to, o) {
      o = o || {}; ctx.tl.set(e, { backgroundColor: from }, 0); ctx.tl.to(e, { backgroundColor: to, duration: Math.max(4 * FR, o.dur || 5 * FR), ease: "power2.out", immediateRender: false }, t);
    }
  };

  // ------------------------------------------------------------------ the themed bundle
  // theme: ink, accent {r,b,g,...} (span classes .r .b .g ...), heroFont, kickFont, heroWeight, kickWeight, heroLine, heroTrack,
  //        halo "r,g,b" (the soft glow under type so it reads on any ground), right (px: the right edge of the text box),
  //        fonts (families to preload), grain (true: the film-grain overlay S83 uses), z (z-index of type, default 30)
  AGP.make = function (prefix, theme) {
    theme = theme || {};
    var T = {
      ink: theme.ink || "#111111", accent: theme.accent || { r: "#d5281b", b: "#005eb8", g: "#0b7a45" },
      heroFont: theme.heroFont || "AG Anton", heroWeight: theme.heroWeight || 400, heroLine: theme.heroLine || 0.98, heroTrack: theme.heroTrack === undefined ? ".01em" : theme.heroTrack,
      heroUpper: theme.heroUpper === false ? "none" : "uppercase",
      kickFont: theme.kickFont || "AG Plex Mono", kickWeight: theme.kickWeight || 600, kickSize: theme.kickSize || 46,
      halo: theme.halo || "238,245,250", right: theme.right || 856, z: theme.z || 30, grain: !!theme.grain,
      fonts: theme.fonts || [theme.heroFont || "AG Anton", theme.kickFont || "AG Plex Mono"]
    };
    // css (the two type classes, per prefix; colours from the theme)
    var css = [
      "." + prefix + "-h{position:absolute;z-index:" + T.z + ";font-family:'" + T.heroFont + "',sans-serif;font-weight:" + T.heroWeight + ";line-height:" + T.heroLine + ";letter-spacing:" + T.heroTrack + ";color:" + T.ink + ";white-space:nowrap;text-transform:" + T.heroUpper + ";text-shadow:0 0 16px rgba(" + T.halo + ",.95)}"
    ];
    var ak = []; for (var k in T.accent) ak.push("." + prefix + "-h ." + k + "{color:" + T.accent[k] + "}");
    css.push(ak.join(""));
    css.push("." + prefix + "-k{position:absolute;z-index:" + T.z + ";font-family:'" + T.kickFont + "',monospace;font-weight:" + T.kickWeight + ";font-size:" + T.kickSize + "px;line-height:1.1;letter-spacing:.03em;color:" + T.ink + ";white-space:nowrap;text-transform:uppercase;text-shadow:0 0 12px rgba(" + T.halo + ",.95)}");
    var st = document.createElement("style"); st.textContent = css.join("\n"); document.head.appendChild(st);

    var P = { theme: T, prefix: prefix, FITS: [] };
    var FITS = P.FITS;
    // fit: a line never runs past w (re-fitted every frame until fonts are ready); min is the smallest px allowed
    P.fit = function (e, w, min) { FITS.push({ e: e, w: w, min: min || 42 }); return e; };
    P.fitNow = function () { for (var i = 0; i < FITS.length; i++) { var f = FITS[i]; if (!f.orig) f.orig = parseFloat(getComputedStyle(f.e).fontSize); f.e.style.fontSize = f.orig + "px"; var w = f.e.scrollWidth; if (!w) continue; if (w > f.w) f.e.style.fontSize = Math.max(f.min, Math.floor(f.orig * f.w / w)) + "px"; } };
    var booted = false;
    P.boot = function (ctx) {
      if (booted) return; booted = true; ctx.after = ctx.after || []; ctx.after.push(P.fitNow); AG.onFrame(ctx, function () { P.fitNow(); });
      var fl = document.createElement("div"); fl.style.cssText = "position:absolute;left:-9999px;top:0;font-size:1px"; ctx.root.appendChild(fl);
      T.fonts.forEach(function (f) { var s = document.createElement("span"); s.style.fontFamily = "'" + f + "'"; s.style.fontWeight = "800"; s.textContent = "AaBb0123"; fl.appendChild(s); if (document.fonts && document.fonts.load) document.fonts.load("800 20px '" + f + "'"); });
      if (document.fonts && document.fonts.ready) document.fonts.ready.then(P.fitNow);
      if (document.fonts && document.fonts.addEventListener) document.fonts.addEventListener("loadingdone", P.fitNow);
      if (T.grain) {
        var g = el("div", "", ctx.root); g.style.cssText = "position:absolute;inset:0;z-index:90;pointer-events:none;opacity:.05;mix-blend-mode:multiply;background-image:repeating-radial-gradient(circle at 23% 37%,rgba(0,0,0,.5) 0 1px,rgba(0,0,0,0) 1px 3px),repeating-radial-gradient(circle at 71% 64%,rgba(0,0,0,.6) 0 1px,rgba(0,0,0,0) 1px 4px)";
        AG.onFrame(ctx, function (t) { var f = Math.floor(t * 15); g.style.backgroundPosition = (H(f, 5) * 40).toFixed(0) + "px " + (H(f, 6) * 40).toFixed(0) + "px," + (H(f, 7) * 40).toFixed(0) + "px " + (H(f, 8) * 40).toFixed(0) + "px"; });
      }
    };
    // hero: a big line. o: {w (max width), min (smallest px), at (absolute second it lands; later than B.from = a 1.06x slam, the
    // accent spans change colour on the word), slam (a 1.07x slam from the cut), from/until (absolute seconds shown)}
    P.hero = function (ctx, S, B, html, x, y, size, o) {
      o = o || {}; var h = el("div", prefix + "-h", S.cam, html); pos(h, x, y); h.style.fontSize = size + "px"; P.fit(h, o.w || (T.right - x), o.min || 60);
      var t = o.at === undefined ? B.from : o.at;
      if (t > B.from + 0.01) {
        var ys = h.querySelectorAll(Object.keys(T.accent).map(function (c) { return "." + c; }).join(","));
        if (ys.length) [].forEach.call(ys, function (e) { var c = getComputedStyle(e).color; ctx.tl.set(e, { color: T.ink }, 0); ctx.tl.set(e, { color: c }, t); });
        ctx.tl.fromTo(h, { scale: 1.06, transformOrigin: "0% 0%" }, { scale: 1, duration: 0.18, ease: "power4.out", immediateRender: false }, t);
      } else if (o.slam) ctx.tl.fromTo(h, { scale: 1.07, transformOrigin: "0% 0%" }, { scale: 1, duration: 0.16, ease: "power4.out", immediateRender: true }, t);
      if (o.from !== undefined) show(ctx, h, o.from, o.until); else if (o.until !== undefined) ctx.tl.set(h, { visibility: "hidden" }, o.until);
      return h;
    };
    // kick: the small mono line over/under a hero. o: {size, color, w, from, until}
    P.kick = function (ctx, S, B, text, x, y, o) {
      o = o || {}; var k = el("div", prefix + "-k", S.cam); k.textContent = text; pos(k, x, y); if (o.size) k.style.fontSize = o.size + "px"; if (o.color) k.style.color = o.color; P.fit(k, o.w || (T.right - x), 36);
      if (o.from !== undefined) show(ctx, k, o.from, o.until);
      return k;
    };
    // cta: the closing card (spoken line in hero type, FOLLOW press at p.pressAt, the audit link). o: {x, y, w, line, link, card, ink, btn, ok}
    P.cta = function (ctx, S, B, o) {
      o = o || {}; var x = o.x === undefined ? 74 : o.x, y = o.y === undefined ? 340 : o.y, w = o.w || 790, ci = o.ink || T.ink;   // ci: ink for type ON the card
      var c = el("div", "", S.cam); c.style.cssText = "position:absolute;z-index:40;left:" + x + "px;top:" + y + "px;width:" + w + "px;height:850px;border-radius:14px;background:" + (o.card || "#fbf7ea") + ";box-shadow:0 36px 70px rgba(0,0,0,.4);overflow:hidden";
      var l = el("div", "", c); l.style.cssText = "position:absolute;left:44px;top:34px;width:" + (w - 102) + "px;font-family:'" + T.heroFont + "',sans-serif;font-weight:" + T.heroWeight + ";font-size:92px;line-height:1.0;color:" + ci + ";text-transform:" + T.heroUpper + ";letter-spacing:.01em";
      (o.sync || []).forEach(function (wd) { var sp = el("span", "k3-iw", l, AG.esc(wd[0])); ctx.tl.set(sp, { color: ci }, 0); ctx.tl.set(sp, { color: o.hi || T.accent.r || "#d5281b" }, Math.max(0, wd[1] - 0.03)); ctx.tl.set(sp, { color: ci }, wd[1] + 0.45); l.appendChild(document.createTextNode(" ")); });
      if (!(o.sync || []).length) l.textContent = o.line || "";
      var au = el("div", "", c); au.style.cssText = "position:absolute;left:28px;top:520px;width:" + (w - 56) + "px;border-top:6px solid " + ci + ";padding-top:16px";
      var a1 = el("div", "", au, AG.esc(o.title || "AI CONSTRAINT AUDIT")); a1.style.cssText = "font-family:'" + T.heroFont + "',sans-serif;font-weight:" + T.heroWeight + ";font-size:54px;color:" + ci; a1.style.whiteSpace = "nowrap"; P.fit(a1, w - 56, 42);
      var a2 = el("div", "", au); a2.textContent = o.link || "agmm.co.uk/ai-constraint-audit"; a2.style.cssText = "font-family:'" + T.kickFont + "',monospace;font-weight:600;font-size:44px;letter-spacing:-.04em;color:" + (o.hi || T.accent.r || "#a02a1c") + ";white-space:nowrap;margin-top:12px"; P.fit(a2, w - 56, 42);
      var bt = el("div", "", c); bt.style.cssText = "position:absolute;left:44px;top:700px;width:420px;height:112px;border-radius:12px;background:" + ci + ";color:#fff;display:flex;align-items:center;justify-content:center;font-family:'" + T.kickFont + "',monospace;font-weight:800;font-size:56px;overflow:hidden";
      bt.textContent = "FOLLOW"; var on = el("div", "", bt, "FOLLOWING"); on.style.cssText = "position:absolute;inset:0;background:" + (o.ok || "#0b7a45") + ";color:#fff;display:flex;align-items:center;justify-content:center;font-size:52px";
      ctx.tl.set(on, { clipPath: "inset(0 100% 0 0)" }, 0); ctx.tl.to(on, { clipPath: "inset(0 0% 0 0)", duration: 0.25, ease: "power2.out" }, o.pressAt || B.from + 1);
      ctx.tl.fromTo(bt, { scale: 1 }, { scale: 0.94, duration: 0.08, yoyo: true, repeat: 1, ease: "power1.inOut", immediateRender: false }, o.pressAt || B.from + 1);
      ctx.tl.fromTo(c, { y: 24, rotation: -0.6 }, { y: 0, rotation: 0, duration: 0.35, ease: "power3.out", immediateRender: true }, B.from);
      ctx.tl.to(c, { y: -10, duration: Math.max(0.5, B.to - B.from - 0.4), ease: "sine.inOut" }, B.from + 0.4);
      return c;
    };
    P.util = AGP.util;
    return P;
  };
})(typeof window !== "undefined" ? window : this);
