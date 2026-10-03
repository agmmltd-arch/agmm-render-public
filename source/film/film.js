/* F07 OCTOPUS ENERGY, "Who Wrote the Better Email?" Full film on the locked voice (film clock from tools/edit_voice_full.py).
   One source of truth for the film clock T:
     SHOTS   the shot list: scene, t0 (t1 = next t0), camera keys (3D) or sc keys (2D screens), ease, focus, split
     state   pure functions of T read by the sets (world3d.js, sets_*.js)
     full    one paused GSAP timeline of every DOM overlay, driven to T each frame
   A render segment (window.F07_SEG = {t0, len}) plays T = t0 + local time. */
(function () {
  "use strict";
  var FULL = window.F07_DUR || 623.37;          // the composition's own clock (shots, overlays, words.js)
  // 29 Sep: re-voiced paragraphs can be longer than the old ones. film/warp.js (tools/splice_revoice.py) maps film time
  // onto the composition clock: linear inside each re-voiced span, shifted by the accumulated difference after it.
  var WARP = window.F07_WARP || null;
  var FILMDUR = WARP ? WARP.film_duration : FULL;
  function toComp(T) {
    if (!WARP) return T;
    var off = 0;
    for (var i = 0; i < WARP.spans.length; i++) { var w = WARP.spans[i];
      if (T < w[0]) return T - off;
      if (T <= w[1]) return w[2] + (T - w[0]) * (w[3] - w[2]) / (w[1] - w[0]);
      off = w[1] - w[3]; }
    return T - off;
  }
  var SEG = window.F07_SEG || { t0: 0, len: FILMDUR };
  var clamp = function (v, a, b) { return Math.max(a, Math.min(b, v)); };
  var prog = function (t, a, d) { return clamp((t - a) / d, 0, 1); };
  var hash = function (n, s) { var x = Math.sin(n * 127.1 + (s || 1) * 311.7) * 43758.5453; return x - Math.floor(x); };
  var eo = function (p) { return 1 - Math.pow(1 - p, 3); };
  var eio = function (p) { return p < 0.5 ? 4 * p * p * p : 1 - Math.pow(-2 * p + 2, 3) / 2; };
  var needle = function (p) { return p >= 1 ? 1 : 1 - Math.exp(-6.5 * p) * Math.cos(9.5 * p); };
  var inR = function (T, a, b) { return T >= a && T < b; };
  var lerp = function (a, b, p) { return a + (b - a) * p; };
  // word lookup on the film clock: at("P05", "250") -> start of the first "250" in paragraph P05 ("P38b" = the CTA half)
  var WD = window.F07_WORDS || [];
  function at(p, w, n) { var k = 0; for (var i = 0; i < WD.length; i++) { var r = WD[i]; var par = r[3] === "P38" && r[0] >= 1517 ? "P38b" : r[3];
    if (par === p && r[4] === w) { if (!n || ++k > n) return r[1]; } } return null; }

  function C(p, l, fov, roll) { return { p: p, l: l, fov: fov || 40, roll: roll || 0 }; }
  var FOC = function (x, y, w, h, b) { return [x, y, w, h, b || 7]; };
  // HQ reference points
  var HX = 3.68, HZ = -4.5;   // hero adviser seat (sets_hq: the seat at (3.68, -4.5))
  var SHOTS = [
    // ============================================================ COLD OPEN
    { id: "S01", scene: "press", t0: 0.0, cam: [C([-7.0, 4.4, 0.6], [-3.2, 1.3, -3.2], 42), C([-3.0, 4.1, 0.4], [0.8, 1.3, -3.2], 42)], ease: "lin" },
    // r3 (root 30 Sep): 2-12 s was dead (press, small stack, tiny page). From the hook straight into the dials rising out
    // of the column, filling the frame; the build moved from 9.6 to 3.2 s, the needles still land on the voice (16.1, 22.7)
    { id: "S02", scene: "studio", t0: 3.0, cam: [C([0.0, 2.2, 4.0], [0, 0.35, -0.3], 38), C([0.0, 1.95, 3.5], [0, 0.35, -0.3], 38)] },
    { id: "S03", scene: "studio", t0: 6.2, cam: [C([-2.0, 1.7, 3.0], [-0.6, 0.3, -0.3], 38), C([-1.6, 1.6, 2.7], [-0.5, 0.3, -0.3], 38)] },
    { id: "S04", scene: "studio", t0: 9.3, cam: [C([2.0, 1.7, 3.0], [0.6, 0.3, -0.3], 38), C([1.6, 1.6, 2.7], [0.5, 0.3, -0.3], 38)] },
    { id: "S05", scene: "studio", t0: 12.4, cam: [C([-2.2, 2.9, 3.4], [-1.05, 0.2, -0.3], 38), C([-1.5, 3.0, 2.5], [-1.05, 0.2, -0.3], 38)] },
    { id: "S06", scene: "studio", t0: 15.5, cam: [C([-1.05, 3.1, 2.1], [-1.05, 0.2, -0.3], 38), C([-1.05, 2.6, 1.7], [-1.05, 0.2, -0.3], 38)] },
    { id: "S07", scene: "studio", t0: 19.0, cam: [C([0.5, 2.6, 5.6], [0, 0.3, -0.3], 40), C([-0.3, 2.3, 5.2], [0, 0.3, -0.3], 40)] },
    { id: "S08", scene: "studio", t0: 21.3, cam: [C([1.05, 3.1, 2.1], [1.05, 0.2, -0.3], 38), C([1.05, 2.6, 1.75], [1.05, 0.2, -0.3], 38)] },
    { id: "S09", scene: "studio", t0: 23.7, cam: [C([0.55, 1.5, 6.4], [0.1, 1.28, 3.2], 34), C([0.45, 1.42, 5.6], [0.1, 1.28, 3.2], 34)], focus: FOC(49, 52, 22, 46, 9) },
    { id: "S10", scene: "screen", t0: 26.6, sc: [[960, 600, 1.05], [960, 700, 1.3]] },
    { id: "S11", scene: "studio", t0: 29.4, cam: [C([0.45, 1.42, 5.6], [0.1, 1.28, 3.2], 34), C([1.2, 3.2, 9.6], [0, 0.4, 0], 38)], ease: "io" },
    { id: "S12", scene: "brand", t0: 33.9, cam: [C([0, 0.8, 9.2], [0.6, 0.6, 0], 40), C([0, 0.7, 8.4], [0.6, 0.6, 0], 40)] },
    { id: "S13", scene: "black", t0: 38.1, cam: [C([0, 0, 1], [0, 0, 0])] },
    { id: "S14", scene: "studio", t0: 41.4, cam: [C([-1.9, 1.5, 2.2], [0, 1.6, -2.5], 40), C([-1.1, 1.55, 1.5], [0.1, 1.65, -2.5], 38)] },   // r3: the page fills the frame
    { id: "S15", scene: "press", t0: 44.4, cam: [C([4.2, 2.2, 2.4], [6.8, 1.2, -1.2], 40), C([4.6, 2.9, 2.0], [6.8, 1.6, -1.2], 40)] },
    { id: "S16", scene: "map", t0: 49.1, cam: [C([0.6, 17, 8.5], [0.5, 0, -0.3], 38), C([0.6, 14.5, 7.2], [0.5, 0, -0.3], 38)] },
    { id: "S17", scene: "map", t0: 53.6, cam: [C([2.6, 6.2, 7.2], [1.4, 0, 1.6], 40), C([3.0, 5.4, 6.4], [1.6, 0, 2.0], 40)] },
    { id: "S18", scene: "map", t0: 56.6, cam: [C([0.4, 11, 11], [0.3, 0, 0], 42), C([0.3, 13.5, 13.5], [0.2, 0, 0], 44)] },
    { id: "TITLE", scene: "studio", t0: 59.0, cam: [C([0.01, 9.5, 1.0], [0, 0, -0.1], 40), C([0.01, 8.4, 1.3], [0, 0, -0.1], 40)] },
    // ============================================================ PART ONE: THE COLUMN
    { id: "C1", scene: "studio", t0: 62.9, cam: [C([3.8, 1.6, 5.8], [0, 0.4, -0.3], 40), C([2.6, 1.5, 6.2], [0, 0.4, -0.3], 40)] },
    { id: "S19", scene: "paper", t0: 64.7 },
    { id: "S20", scene: "paper", t0: 66.7 },
    { id: "S21", scene: "hq", t0: 71.7, cam: [C([-6.5, 2.2, 7.5], [0, 1.9, 0], 40), C([-4.6, 1.8, 7.8], [0, 2.0, 0], 40)] },
    { id: "S22", scene: "hq", t0: 74.0, cam: [C([3.6, 4.6, 8.4], [1.8, 1.6, 0.4], 42), C([5.2, 4.2, 8.0], [2.4, 1.4, 0.5], 42)] },
    { id: "S23", scene: "studio", t0: 77.0, cam: [C([-1.05, 2.9, 2.3], [-1.05, 0.2, -0.3], 38), C([-0.8, 2.5, 1.9], [-1.05, 0.2, -0.3], 38)] },
    { id: "S23b", scene: "studio", t0: 79.3, cam: [C([0.01, 9.0, 1.2], [0, 0, -0.1], 40), C([0.4, 8.2, 1.3], [0, 0, -0.1], 40)], focus: FOC(50, 50, 1, 1, 16), qbg: 0.86 },
    { id: "S24", scene: "studio", t0: 84.7, cam: [C([0, 3.4, 4.8], [0, 0.4, -0.3], 40), C([0.3, 3.1, 4.4], [0, 0.4, -0.3], 40)] },
    { id: "S25", scene: "studio", t0: 86.9, cam: [C([-0.6, 1.1, 4.3], [0, 0.35, 0.6], 38), C([-0.2, 1.0, 3.9], [0, 0.35, 0.6], 38)] },
    { id: "S26", scene: "hq", t0: 89.4, cam: [C([0, 3.4, 9.5], [0, 1.2, 0], 40), C([0.8, 3.8, 9.8], [0, 1.0, 0], 40)] },
    { id: "S27", scene: "hq", t0: 93.5, cam: [C([-2.2, 3.6, 9.4], [-0.6, 1.5, 0], 40), C([-1.4, 3.3, 8.6], [-0.8, 1.5, 0], 40)] },
    { id: "S28", scene: "studio", t0: 97.5, cam: [C([0, 3.4, 4.8], [0, 0.4, -0.3], 40), C([0, 3.1, 4.3], [0, 0.4, -0.3], 40)], qbg: 0.55 },
    { id: "S29", scene: "studio", t0: 101.3, cam: [C([-2.5, 7.8, 3.6], [0, 0, -0.3], 40), C([2.2, 7.6, 3.8], [0, 0, -0.3], 40)] },
    { id: "S30", scene: "studio", t0: 104.4, cam: [C([-1.0, 2.6, 7.6], [1.2, 0.4, -0.3], 42), C([2.6, 2.3, 7.0], [3.4, 0.4, -0.3], 42)] },
    // ============================================================ PART TWO: WHO PRESSED SEND
    { id: "S31", scene: "hq", t0: 108.9, cam: [C([6.8, 1.6, 5.2], [3.2, 0.8, -1.6], 42), C([7.6, 2.4, 6.8], [1.0, 1.0, -4], 44)] },
    { id: "S32", scene: "hq", t0: 113.3, cam: [C([-9, 2.4, -1.5], [0, 1.1, -9], 44), C([-5, 2.2, -2.2], [4, 1.1, -9], 44)] },
    { id: "S33", scene: "hq", t0: 116.4, cam: [C([HX + 0.75, 1.55, HZ + 0.95], [HX - 0.05, 1.12, HZ - 0.8], 40), C([HX + 0.55, 1.5, HZ + 0.6], [HX - 0.02, 1.12, HZ - 0.8], 38)], focus: FOC(46, 42, 30, 40, 6) },
    { id: "S34", scene: "screen", t0: 119.9, sc: [[960, 540, 1.0], [1150, 560, 1.2]] },
    { id: "S35", scene: "hq", t0: 122.5, cam: [C([-9, 2.4, -1.5], [0, 1.1, -9], 44), C([-7, 2.3, -1.9], [2, 1.1, -9], 44)], focus: FOC(50, 50, 1, 1, 16), qbg: 0.7 },
    { id: "S36", scene: "screen", t0: 126.3, sc: [[1200, 600, 1.35], [1300, 720, 1.5]] },
    { id: "S37", scene: "hq", t0: 131.4, cam: [C([0.5, 5.5, 8.5], [0, 0.9, -6], 44), C([-1.5, 4.8, 7.6], [0, 0.9, -7], 44)] },
    { id: "S38", scene: "hq", t0: 135.3, cam: [C([-12, 1.45, -3.3], [-6, 1.0, -6.8], 40), C([-7, 1.45, -3.3], [-1, 1.0, -6.8], 40)], ease: "lin" },
    { id: "S39", scene: "hq", t0: 139.0, cam: [C([7.4, 2.4, 4.8], [4.3, 0.4, 1.1], 40), C([6.6, 2.0, 4.2], [4.3, 0.4, 1.1], 38)] },
    { id: "S40", scene: "hq", t0: 144.0, cam: [C([2, 3.5, 9], [0, 1, -3], 44), C([4, 26, 22], [0, 0, -3], 48)], ease: "io" },
    { id: "S41", scene: "map", t0: 147.0, cam: [C([1.8, 3.2, 5.4], [1.6, 0, 2.2], 40), C([0.6, 13, 11], [0.4, 0, -0.2], 42)], ease: "io" },
    { id: "S42", scene: "map", t0: 150.0, cam: [C([0.6, 13, 11], [0.4, 0, -0.2], 42), C([0.6, 11.5, 9.8], [0.4, 0, -0.2], 42)], focus: FOC(50, 50, 1, 1, 12), qbg: 0.62 },
    { id: "S43", scene: "hq", t0: 153.2, cam: [C([HX - 1.4, 1.5, HZ + 1.6], [HX, 1.0, HZ - 0.6], 40), C([HX - 1.0, 1.45, HZ + 1.3], [HX, 1.0, HZ - 0.6], 40)] },
    { id: "S44", scene: "hq", t0: 157.0, cam: [C([HX + 0.3, 1.36, HZ + 0.1], [HX - 0.02, 1.12, HZ - 0.8], 34), C([HX + 0.22, 1.3, HZ - 0.12], [HX - 0.02, 1.12, HZ - 0.8], 32)], focus: FOC(50, 50, 40, 50, 5) },
    { id: "S45", scene: "screen", t0: 160.9, sc: [[1200, 720, 1.2], [1000, 760, 1.35]] },
    // ============================================================ MID-ROLL
    { id: "S46", scene: "hq", t0: 166.2, split: [
        { scene: "hq", cam: [C([-3, 7, 10], [0, 0.5, -6], 46), C([-1.5, 6.4, 9], [0, 0.5, -6], 46)] },
        { scene: "uk", cam: [C([3.6, 2.4, 4.6], [0, 1.0, -0.6], 46), C([3.0, 2.2, 4.2], [0, 1.0, -0.6], 46)] }] },
    { id: "S47", scene: "uk", t0: 170.0, cam: [C([-2.6, 2.2, 3.6], [0.2, 1.0, -0.8], 42), C([-1.8, 2.0, 3.8], [0.2, 1.0, -0.8], 42)] },
    { id: "S48", scene: "screen", t0: 173.3, sc: [[960, 500, 1.0], [900, 560, 1.15]] },
    { id: "S49", scene: "uk", t0: 176.3, cam: [C([1.3, 1.45, 1.7], [-0.3, 1.0, -0.4], 38), C([1.0, 1.4, 1.4], [-0.3, 1.0, -0.4], 38)], focus: FOC(46, 50, 36, 46, 5) },
    { id: "S50", scene: "screen", t0: 180.0, sc: [[1300, 560, 1.05], [1400, 540, 1.2]] },
    { id: "S51", scene: "uk", t0: 183.0, cam: [C([4.2, 2.6, 5.0], [0.6, 1.0, -0.8], 42), C([3.4, 2.3, 4.8], [0.6, 1.0, -0.8], 42)] },
    { id: "S52", scene: "uk", t0: 187.3, cam: [C([-1.2, 1.8, 3.6], [1.4, 1.1, -1.2], 40), C([-0.4, 1.7, 3.8], [1.8, 1.1, -1.2], 40)] },
    // ============================================================ PART THREE: THE OTHER ANNOUNCEMENT
    { id: "S53", scene: "globe", t0: 193.1, cam: [C([0, 1.5, 17], [0, 0, 0], 40), C([0, 1.8, 15.5], [0, 0.3, 0], 40)] },
    { id: "S54", scene: "globe", t0: 197.9, cam: [C([2.5, 5.2, 10.5], [0.6, 3.2, 2.2], 38), C([2.0, 5.0, 9.4], [0.4, 3.2, 2.4], 36)] },
    { id: "S55", scene: "globe", t0: 201.3, cam: [C([-1.5, 3.5, 13.5], [-1.2, 2.0, 0], 40), C([-4, 3.8, 12.8], [-2, 2.2, 0], 40)] },
    { id: "S56", scene: "paper", t0: 204.6 },
    { id: "S57", scene: "hq", t0: 208.4, cam: [C([-9, 7.5, 12], [0, 0, 0], 44), C([-7, 9.5, 10], [0, -1.5, 0], 44)] },
    { id: "S58", scene: "hq", t0: 211.9, cam: [C([1.5, 9, 6.5], [0, -4, 0], 46), C([0.8, 7.2, 5.0], [0, -5, 0], 46)] },
    { id: "S59", scene: "hq", t0: 215.0, cam: [C([6, -3.2, 9], [0, -5, 0], 46), C([9, -5.5, 5], [0, -6, 0], 46)] },
    { id: "S60", scene: "hq", t0: 219.7, cam: [C([14, -6, 28], [0, -6, 0], 50), C([22, -4, 30], [0, -6, -4], 52)] },
    { id: "S61", scene: "hq", t0: 223.9, cam: [C([3.5, 1.3, 13], [0, 0.2, 0], 42), C([1.5, 0.8, 12], [0, 0.0, 0], 42)] },
    { id: "S62", scene: "hq", t0: 228.3, cam: [C([4, -2.5, 12], [0, -5, 0], 46), C([-4, -3.0, 12], [0, -5.5, 0], 46)] },
    { id: "S63", scene: "hq", t0: 232.0, cam: [C([-18, 7, 26], [8, 3, -3], 46), C([-22, 9, 32], [10, 5, -4], 46)] },
    { id: "S64", scene: "paper", t0: 236.2 },
    { id: "S65", scene: "paper", t0: 240.7 },
    { id: "S66", scene: "hq", t0: 246.9, cam: [C([30, 13, 26], [14, 8, -5], 44), C([44, 18, 38], [12, 6, -4], 46)], ease: "io" },
    { id: "S67", scene: "hq", t0: 252.3, cam: [C([34, 12, 22], [16, 9, -6], 42), C([28, 11.5, 16], [16, 9.5, -6], 40)] },
    // ============================================================ PART FOUR: THE RULES
    { id: "C4", scene: "studio", t0: 256.6, cam: [C([-2.5, 8.5, 4], [0, 0, -0.3], 40), C([2.5, 8.2, 4.2], [0, 0, -0.3], 40)] },
    { id: "S69", scene: "paper", t0: 260.0 },
    { id: "S70", scene: "paper", t0: 263.6 },
    { id: "S71", scene: "studio", t0: 267.3, cam: [C([0, 6.2, 9.2], [0, 0, 3.4], 40), C([0.4, 6.0, 8.8], [0, 0, 3.6], 40)] },
    { id: "S72", scene: "studio", t0: 270.2, cam: [C([-2.2, 3.4, 7.4], [-0.6, 0, 4.2], 40), C([-1.8, 3.2, 7.1], [-0.4, 0, 4.2], 40)] },
    { id: "S73", scene: "studio", t0: 272.2, cam: [C([2.4, 3.4, 7.4], [0.6, 0, 4.2], 40), C([2.0, 3.2, 7.1], [0.6, 0, 4.2], 40)] },
    { id: "S74", scene: "studio", t0: 275.0, cam: [C([3.6, 3.2, 7.2], [2.0, 0, 4.2], 40), C([0.4, 5.4, 9.0], [0, 0, 3.8], 40)] },
    { id: "S75", scene: "studio", t0: 278.5, cam: [C([0, 5.8, 8.8], [0, 0, 1.6], 40), C([0, 5.2, 7.6], [0, 0, 1.2], 40)] },
    { id: "S76", scene: "studio", t0: 281.6, cam: [C([-2.6, 2.4, 5.2], [0.2, 0.2, 0.9], 40), C([-1.8, 2.2, 5.4], [0.6, 0.2, 0.9], 40)] },
    // ============================================================ PART FIVE: THE SECOND TEST
    { id: "C5", scene: "hq", t0: 284.6, cam: [C([-6, 5, 13], [-1.5, 0.8, 3.5], 44), C([-5, 4.6, 12], [-1.5, 0.8, 3.8], 44)] },
    { id: "S77", scene: "paper", t0: 286.6 },
    { id: "S78", scene: "hq", t0: 289.4, cam: [C([-2.0, 2.4, 10.5], [-1.4, 1.0, 5.2], 38), C([-1.2, 2.2, 9.2], [-1.4, 1.0, 5.2], 36)] },
    { id: "S79", scene: "hq", t0: 293.7, cam: [C([-5.5, 3.2, 7.5], [0, 2.2, 0], 40), C([-4.2, 3.6, 6.8], [0, 2.6, 0], 40)] },
    { id: "S80", scene: "hq", t0: 298.0, cam: [C([1.6, 4.6, 3.4], [0, 3.3, 0], 38), C([1.2, 4.3, 2.9], [0, 3.3, 0], 36)] },
    { id: "S81", scene: "hq", t0: 302.8, split: [
        { scene: "hq", ov: { tower: "third", mag: 1, tray: false, arlo: false }, cam: [C([-3.4, 2.6, 7.2], [0, 2.0, 0], 42), C([-3.0, 2.5, 6.8], [0, 2.0, 0], 42)] },
        { scene: "hq", ov: { tower: "sliver", mag: 1, tray: false, arlo: false }, cam: [C([3.4, 2.6, 7.2], [0, 2.0, 0], 42), C([3.0, 2.5, 6.8], [0, 2.0, 0], 42)] }] },
    { id: "S82", scene: "hq", t0: 307.4, cam: [C([-8.5, 3.8, 10.5], [-4.5, 0.8, 5.2], 42), C([-6.8, 3.4, 10.2], [-3.6, 0.8, 5.2], 42)] },
    { id: "S83", scene: "hq", t0: 310.3, cam: [C([-2.6, 1.7, 7.0], [-1.6, 1.0, 5.2], 38), C([-2.3, 1.6, 6.6], [-1.6, 1.0, 5.2], 36)], focus: FOC(52, 48, 40, 48, 5) },
    { id: "S84", scene: "hq", t0: 313.0, cam: [C([-7.6, 2.6, 8.4], [-4.5, 0.9, 5.2], 40), C([-5.6, 2.4, 8.2], [-2.8, 0.9, 5.2], 40)], ease: "lin" },
    { id: "S85", scene: "hq", t0: 316.2, cam: [C([-4.2, 2.8, 9.8], [-5.8, 1.0, 5.8], 40), C([-3.6, 2.6, 9.4], [-5.8, 1.0, 6.0], 40)] },
    { id: "S86", scene: "screen", t0: 320.8, sc: [[960, 420, 1.2], [1100, 330, 1.45]] },
    { id: "S87", scene: "screen", t0: 324.0, sc: [[960, 700, 1.25], [960, 820, 1.55]] },
    { id: "S88", scene: "studio", t0: 327.3, cam: [C([0, 4.6, 7.8], [0, 0, 1.8], 40), C([0, 4.2, 7.2], [0, 0, 1.6], 40)] },
    { id: "S89", scene: "studio", t0: 332.0, cam: [C([-1.9, 2.2, 5.0], [-1.1, 0.2, 1.6], 38), C([-1.5, 1.8, 4.3], [-1.1, 0.3, 1.6], 36)] },
    { id: "S90", scene: "studio", t0: 336.4, cam: [C([0, 3.6, 8.4], [0, 0.3, -0.2], 42), C([0.8, 3.4, 8.8], [0.8, 0.3, -0.2], 42)] },
    { id: "S91", scene: "studio", t0: 339.4, cam: [C([1.7, 2.9, 2.7], [1.7, 0.08, -0.05], 38), C([1.7, 2.5, 2.4], [1.7, 0.08, -0.05], 38)] },
    { id: "S92", scene: "studio", t0: 343.5, cam: [C([3.3, 2.9, 2.7], [3.3, 0.08, -0.05], 38), C([3.3, 2.5, 2.4], [3.3, 0.08, -0.05], 38)] },
    { id: "S93", scene: "studio", t0: 347.9, cam: [C([5.6, 0.6, 4.4], [2.45, 0.35, -0.1], 40), C([5.0, 0.55, 3.9], [2.45, 0.35, -0.1], 38)] },
    { id: "S94", scene: "studio", t0: 352.0, cam: [C([0, 3.2, 8.2], [0, 0.3, -0.1], 42), C([0, 2.9, 7.4], [0, 0.3, -0.1], 42)] },
    { id: "S95", scene: "studio", t0: 355.8, cam: [C([0, 9.5, 3.2], [0, 0, -0.3], 42), C([0, 8.6, 3.0], [0, 0, -0.3], 42)] },
    { id: "S96", scene: "studio", t0: 359.9, cam: [C([-3.6, 1.2, 6.2], [0, 0.4, 0.4], 42), C([-2.4, 1.1, 6.6], [0, 0.4, 0.4], 42)] },
    { id: "S97", scene: "studio", t0: 363.4, cam: [C([0, 3.2, 8.2], [0, 0.3, -0.1], 42), C([0, 2.9, 7.2], [0, 0.3, -0.1], 42)], qbg: 0.45 },
    { id: "S98", scene: "paper", t0: 367.3 },
    { id: "S99", scene: "hq", t0: 371.1, cam: [C([-6, 5, 13], [-1.5, 0.8, 3.5], 44), C([-4.8, 4.6, 12.2], [-1.5, 0.8, 3.8], 44)], focus: FOC(50, 50, 1, 1, 16), qbg: 0.7 },
    { id: "S100", scene: "hq", t0: 375.5, cam: [C([-2.6, 1.7, 7.0], [-1.6, 1.0, 5.2], 38), C([-2.3, 1.6, 6.6], [-1.6, 1.0, 5.2], 36)], focus: FOC(50, 50, 1, 1, 16), qbg: 0.7 },
    { id: "S101", scene: "hq", t0: 379.0, cam: [C([-12, 6, 12], [-2, 0.5, 0], 44), C([-10, 5.4, 12.6], [-1, 0.5, 0], 44)] },
    { id: "S102", scene: "hq", t0: 382.4, cam: [C([-12.6, 1.4, -5.6], [-9.6, 1.05, -7.8], 38), C([-12.0, 1.4, -5.3], [-9.2, 1.05, -7.8], 38)], focus: FOC(60, 48, 40, 50, 5) },
    { id: "S103", scene: "hq", t0: 385.6, cam: [C([12, 1.45, -3.3], [6, 1.0, -6.8], 40), C([9, 1.45, -3.3], [3, 1.0, -6.8], 40)], focus: FOC(50, 50, 1, 1, 16), qbg: 0.7 },
    { id: "S104", scene: "hq", t0: 389.9, cam: [C([-12, 6, 12], [-2, 0.5, 0], 44), C([-11, 5.6, 12.4], [-1.5, 0.5, 0], 44)], focus: FOC(50, 50, 1, 1, 16), qbg: 0.7 },
    { id: "S105", scene: "hq", t0: 392.3, cam: [C([0, 6.5, 6], [0, 0.8, -9], 46), C([2, 6.0, 5.4], [2, 0.8, -9], 46)] },
    { id: "S106", scene: "hq", t0: 397.0, cam: [C([12, 1.45, -3.3], [6, 1.0, -6.8], 40), C([7, 1.45, -3.3], [1, 1.0, -6.8], 40)], ease: "lin" },
    { id: "S107", scene: "hq", t0: 401.4, cam: [C([HX + 1.3, 1.45, HZ + 1.1], [HX, 1.2, HZ - 0.2], 38), C([HX + 0.95, 1.42, HZ + 0.8], [HX, 1.2, HZ - 0.2], 38)], focus: FOC(46, 46, 36, 50, 5) },
    // ============================================================ PART SIX: THE COMPLAINTS
    { id: "C6", scene: "screen", t0: 406.2, sc: [[960, 540, 0.9], [960, 600, 1.0]] },
    { id: "S109", scene: "screen", t0: 410.4, sc: [[960, 500, 1.1], [960, 560, 1.2]] },
    { id: "S110", scene: "screen", t0: 414.0, sc: [[960, 720, 1.35], [960, 760, 1.5]] },
    { id: "S111", scene: "screen", t0: 418.0, sc: [[960, 600, 1.3], [960, 640, 1.45]] },
    { id: "S112", scene: "screen", t0: 422.6, sc: [[960, 500, 1.05], [960, 540, 1.15]] },
    { id: "S113", scene: "screen", t0: 426.5, sc: [[960, 640, 1.35], [960, 690, 1.5]] },
    { id: "S114", scene: "studio", t0: 431.8, cam: [C([2.5, 2.6, 5.8], [2.5, 0.3, -0.1], 40), C([2.5, 2.3, 5.2], [2.5, 0.3, -0.1], 40)] },
    { id: "S115", scene: "studio", t0: 435.3, cam: [C([6.2, 1.4, 4.6], [2.5, 0.3, -0.1], 40), C([5.6, 1.3, 4.0], [2.5, 0.3, -0.1], 40)] },
    { id: "S116", scene: "paper", t0: 438.6 },
    { id: "S117", scene: "paper", t0: 442.0 },
    { id: "S118", scene: "paper", t0: 446.6 },
    { id: "S119", scene: "hq", t0: 450.2, cam: [C([-4.5, 3.4, 12.5], [-1, 1.0, 2.5], 42), C([-3.5, 3.2, 12.0], [-0.6, 1.0, 2.5], 42)] },
    { id: "S120", scene: "hq", t0: 453.4, cam: [C([-3.5, 3.2, 12.0], [-0.6, 1.0, 2.5], 42), C([-6, 9, 20], [0, 0.5, 0], 46)], ease: "io" },
    // ============================================================ PART SEVEN: WHY HERE
    { id: "C7", scene: "screen", t0: 458.9, sc: [[960, 600, 1.0], [960, 640, 1.08]] },
    { id: "S122", scene: "screen", t0: 463.0, sc: [[960, 700, 1.2], [960, 700, 1.05]] },
    { id: "S123", scene: "hq", t0: 466.5, cam: [C([-4.5, 3.4, 12.5], [-1, 1.0, 2.5], 42), C([-3.8, 3.2, 12.0], [-0.8, 1.0, 2.5], 42)], focus: FOC(50, 50, 1, 1, 16), qbg: 0.86 },
    { id: "S124", scene: "paper", t0: 470.2 },
    { id: "S125", scene: "paper", t0: 474.8 },
    { id: "S126", scene: "hq", t0: 480.3, cam: [C([0.6, 7.5, 2.2], [0, 3.2, 0], 44), C([0.5, 3.6, 1.9], [0, 0.8, 0], 46), C([0.4, 0.6, 1.8], [0, -2.5, 0], 48)], ease: "io" },
    { id: "S127", scene: "hq", t0: 484.4, cam: [C([0.4, -0.6, 2.4], [0, -3.5, 0], 50), C([3.5, -4.0, 6.5], [0, -3.0, 0], 50)], ease: "out" },
    { id: "S128", scene: "hq", t0: 488.6, cam: [C([3.5, -4.0, 6.5], [0, -3.4, 0], 50), C([-4, -3.2, 7.5], [0, -3.4, 0], 50)] },
    { id: "S129", scene: "hq", t0: 494.7, cam: [C([1.8, 0.4, 3.0], [0, -1.2, 0], 44), C([1.2, -2.4, 2.8], [0, -3.6, 0], 44)] },
    { id: "S130", scene: "hq", t0: 498.7, cam: [C([10, -7, 12], [0, -6, 0], 48), C([14, -5, 10], [0, -6, 0], 48)] },
    { id: "S131", scene: "hq", t0: 503.2, cam: [C([8, -1.0, 12], [0, -1.5, 0], 46), C([6, 4.5, 11], [0, 1.2, 0], 44)], ease: "io" },
    { id: "S132", scene: "hq", t0: 507.6, cam: [C([-6.5, 3.2, 6], [0, 2.4, 0], 40), C([-5.6, 3.6, 5.2], [0, 2.8, 0], 40)] },
    { id: "S133", scene: "hq", t0: 511.2, cam: [C([4.8, 5.8, 6.2], [0, 2.6, 0], 42), C([6.4, 4.6, 7.4], [0, 2.2, 0], 42)] },
    // ============================================================ PART EIGHT: WHAT THIS MEANS FOR YOUR BUSINESS
    { id: "C8", scene: "uk", t0: 517.3, cam: [C([4.6, 2.8, 5.6], [0, 1.0, -0.8], 42), C([3.8, 2.5, 5.0], [0, 1.0, -0.8], 42)] },
    { id: "S135", scene: "screen", t0: 521.3, sc: [[960, 500, 1.0], [700, 420, 1.3]] },
    { id: "S136", scene: "uk", t0: 526.0, cam: [C([-3.4, 2.2, 3.4], [0, 1.0, -0.6], 42), C([-2.6, 2.0, 3.8], [0.2, 1.0, -0.6], 42)] },
    { id: "S137", scene: "uk", t0: 530.4, cam: [C([1.6, 1.6, 1.9], [0.3, 1.0, -0.4], 38), C([1.25, 1.5, 1.5], [0.4, 1.0, -0.3], 36)], focus: FOC(56, 52, 36, 46, 5) },
    { id: "R1", scene: "paper", t0: 536.5 },
    { id: "S139", scene: "uk", t0: 540.5, cam: [C([-1.0, 2.4, 4.6], [-1.4, 0.6, 0.6], 40), C([-0.8, 2.2, 4.2], [-1.3, 0.6, 0.6], 40)] },
    { id: "S140", scene: "uk", t0: 545.3, cam: [C([-1.2, 2.6, 5.2], [-1.3, 0.5, 1.0], 42), C([-1.5, 2.4, 4.8], [-1.3, 0.5, 1.0], 42)] },
    { id: "S141", scene: "uk", t0: 550.9, cam: [C([1.9, 1.6, 1.6], [0.5, 1.0, -0.3], 38), C([1.6, 1.55, 1.3], [0.5, 1.0, -0.3], 36)] },
    { id: "R2", scene: "paper", t0: 556.0 },
    { id: "S143", scene: "screen", t0: 559.9, sc: [[1200, 640, 1.05], [1300, 760, 1.25]] },
    { id: "S144", scene: "uk", t0: 563.9, cam: [C([3.8, 2.3, 4.6], [0, 1.0, -0.6], 42), C([3.0, 2.1, 4.2], [0, 1.0, -0.6], 42)] },
    { id: "S145", scene: "uk", t0: 567.2, cam: [C([-0.5, 1.5, 1.4], [0, 1.15, -0.72], 36), C([-0.35, 1.45, 1.1], [0, 1.15, -0.72], 34)] },
    { id: "R3", scene: "paper", t0: 570.5 },
    { id: "S147", scene: "hq", t0: 574.2, cam: [C([-5.5, 3.2, 7.5], [0, 2.4, 0], 40), C([-4.4, 3.6, 6.6], [0, 2.8, 0], 40)] },
    { id: "S148", scene: "hq", t0: 577.3, cam: [C([-4.2, 2.8, 9.8], [-5.8, 1.0, 5.8], 40), C([-3.8, 2.6, 9.3], [-5.8, 1.0, 6.0], 40)] },
    { id: "S149", scene: "screen", t0: 580.9, sc: [[960, 560, 1.0], [960, 640, 1.15]] },
    { id: "S150", scene: "uk", t0: 585.2, cam: [C([2.6, 1.8, 3.0], [0.2, 1.1, -0.2], 40), C([2.1, 1.7, 2.6], [0.2, 1.15, -0.1], 40)] },
    { id: "R4", scene: "paper", t0: 590.4 },
    // ============================================================ CLOSE AND CTA
    { id: "S152", scene: "studio", t0: 592.4, cam: [C([0, 2.9, 7.4], [0, 0.3, -0.1], 42), C([0, 4.2, 10.2], [0, 0.3, -0.1], 44)] },
    { id: "S153", scene: "hq", t0: 596.7, cam: [C([12, 3.0, 12], [0, -0.6, 0], 44), C([13.5, 3.6, 14], [0, -0.4, 0], 44)] },
    { id: "S154", scene: "studio", t0: 600.3, cam: [C([0, 2.9, 7.0], [0, 0.3, -0.1], 42), C([-2.0, 2.4, 7.8], [0, 0.3, -0.1], 42)] },
    { id: "E1", scene: "studio", t0: 604.2, cam: [C([-4, 2.2, 8], [0, 0.3, -0.1], 42), C([-2.5, 2.0, 8.4], [0, 0.3, -0.1], 42)] },
    { id: "E2", scene: "studio", t0: 608.6, cam: [C([-2.5, 2.0, 8.4], [0, 0.3, -0.1], 42), C([-0.8, 1.9, 8.2], [0.4, 0.3, -0.1], 42)] },
    { id: "E3", scene: "studio", t0: 613.2, cam: [C([-0.8, 1.9, 8.2], [0.4, 0.3, -0.1], 42), C([0.8, 1.9, 8.0], [0.8, 0.3, -0.1], 42)] },
    { id: "E4", scene: "studio", t0: 618.0, cam: [C([0.8, 1.9, 8.0], [0.8, 0.3, -0.1], 42), C([2.2, 2.0, 8.2], [1.0, 0.3, -0.1], 42)] }
  ];
  SHOTS.forEach(function (s, i) { s.t1 = i < SHOTS.length - 1 ? SHOTS[i + 1].t0 : FULL; if (s.drift === undefined) s.drift = 1; });
  function shotAt(T) { for (var i = 0; i < SHOTS.length; i++) if (T < SHOTS[i].t1 - 1e-6) return SHOTS[i]; return SHOTS[SHOTS.length - 1]; }

  // ============================================================ state (pure functions of T)
  var CLIMAX = 336.6;
  function studio(T) {
    var cp = eio(prog(T, CLIMAX, 1.8));
    var b01 = eo(prog(T, 2.9, 2.3)), b02 = eo(prog(T, 3.1, 2.3));   // r3: the dials rise from the column at 3.2 s
    var b2 = T < 106 ? 0 : (T < 337.6 ? 0.3 * prog(T, 106.0, 1.0) : lerp(0.3, 1, prog(T, 337.6, 2.2)));
    var b3 = T < 106.25 ? 0 : (T < 337.9 ? 0.3 * prog(T, 106.25, 1.0) : lerp(0.3, 1, prog(T, 337.9, 2.2)));
    var v0 = 80 * needle(prog(T, 15.95, 0.95)), v1 = 65 * needle(prog(T, 22.35, 0.85));
    var v2 = 76 * needle(prog(T, 340.25, 0.85)), v3 = 72 * needle(prog(T, 346.25, 0.85));
    if (inR(T, 347.9, 352.0)) { v2 = 76 * eo(prog(T, 348.3, 2.6)); v3 = 72 * eo(prog(T, 348.7, 2.6)); }   // the replay, slowed
    var dials = [
      { vis: true, build: b01, v: v0, x: lerp(-1.05, -3.3, cp), z: lerp(-0.3, 0, cp), s: lerp(1, 0.78, cp) },
      { vis: true, build: b02, v: v1, x: lerp(1.05, -1.62, cp), z: lerp(-0.3, 0, cp), s: lerp(1, 0.78, cp) },
      { vis: b2 > 0, build: b2, v: T > 339 ? v2 : 0, x: lerp(3.4, 1.62, cp), z: lerp(-0.3, 0, cp), s: 0.78 },
      { vis: b3 > 0, build: b3, v: T > 339 ? v3 : 0, x: lerp(5.1, 3.3, cp), z: lerp(-0.3, 0, cp), s: 0.78 }];
    var cards = [268.6, 270.7, 272.4, 276.0].map(function (t, i) {
      var p = prog(T, t, 0.75), sl = eio(prog(T, 279.2 + i * 0.15, 1.5)), off = eio(prog(T, CLIMAX, 1.2));
      var lit = (i === 0 && T >= 329.9) || (i === 1 && T >= 331.6);
      var lift = (lit && inR(T, 332.0, 336.6)) ? eo(prog(T, 332.3 + i * 0.3, 0.8)) * 0.18 : 0;
      return { vis: T >= t - 0.05 && off < 1, p: p, x: lerp(-2.25 + i * 1.5, -1.6 + i * 1.07, sl), z: lerp(4.4, 1.75, sl) + off * 6, ry: (hash(i, 3) - 0.5) * 0.14, lit: lit ? 1 : 0, y: lift };
    });
    var ph = null;
    if (inR(T, 23.7, 33.9)) ph = { vis: true, x: 0.1, y: 1.28, z: 3.2, chat: chatState(T), tap: typingTap(T) };
    return { page: { vis: true, stand: inR(T, 41.0, 44.5) ? eo(prog(T, 41.0, 0.4)) : 0 }, dials: dials, years: T > 101 ? 1 : 0,
      mag: { vis: inR(T, 84.7, 86.9), x: lerp(-2.8, 2.6, eio(prog(T, 84.8, 2.0))), z: -0.1 }, cards: cards, phone: ph || { vis: false } };
  }
  // the hook chat: "human", "HUMAN", "speak to a human" (each typed, then sent; the bot answers with grey lines)
  var CHAT = [{ text: "human", t0: 24.4, t1: 25.05, sent: 25.25, bot: 25.85 }, { text: "HUMAN", t0: 26.55, t1: 27.1, sent: 27.3, bot: 27.85 },
              { text: "speak to a human", t0: 28.1, t1: 28.95, sent: 29.15, bot: 99 }];
  // the bot's replies: our own ILLUSTRATION wording (same text as screens.js MAIL.bot; the phone header carries the label)
  var BOT = ["Hi, I'm the virtual assistant. How can I help today?", "I can help with most questions. What do you need?", "Sorry, I didn't catch that. Could you ask another way?"];
  function chatState(T) {
    var msgs = [{ who: "bot", text: BOT[0] }], typing = "";
    CHAT.forEach(function (c, i) {
      if (T >= c.sent) msgs.push({ who: "me", text: c.text, big: c.text === "HUMAN" });
      else if (T >= c.t0) typing = c.text.slice(0, Math.round(c.text.length * prog(T, c.t0, c.t1 - c.t0)));
      if (T >= c.bot) msgs.push({ who: "bot", text: BOT[Math.min(i + 1, 2)] });
    });
    return { mode: "chat", msgs: msgs.slice(-5), typing: typing, t: Math.round(T * 10) / 10 };
  }
  function typingTap(T) { for (var i = 0; i < CHAT.length; i++) { var c = CHAT[i]; if (inR(T, c.t0, c.sent + 0.1)) { var n = c.text.length; var k = (T - c.t0) / ((c.t1 - c.t0) / n); return 0.5 + 0.5 * Math.cos((k % 1) * Math.PI * 2); } } return 0; }

  function hq(T) {
    var st = { tower: "peel", mag: 1, peelT0: 74.9, tray: true };
    if (T < 74.0) { st.tower = "third"; st.mag = 0; }
    else if (T < 89.4) { st.mag = prog(T, 74.1, 0.6); }
    else if (T < 97.5) { st.tower = "piles"; st.split = prog(T, 89.6, 1.8); st.mag = prog(T, 93.6, 1.4); st.tray = false; }
    if (T >= 286.6) { st.tower = "sliver"; st.mag = inR(T, 293.7, 302.8) ? prog(T, 295.3, 0.6) : (inR(T, 574.2, 577.3) ? prog(T, 575.4, 0.5) : 1); st.sliverL = 2.4; st.tray = false; }
    st.hideRows = T < 110.6;
    st.advOp = T < 110.6 ? 0 : (T < 131.6 ? 0.45 * eo(prog(T, 110.8, 1.4)) : lerp(0.45, 1, eo(prog(T, 131.6, 1.2))));
    st.advTurn = T < 132.4 ? 0 : eio(prog(T, 132.4, 2.0));
    st.drafts = inR(T, 135.3, 139.0) ? 0.45 : (T >= 392.3 && T < 406.2 ? prog(T, 392.6, 3.4) : (T > 286.6 ? 0.3 : (T > 139 ? 0.3 : 0)));
    st.glass = inR(T, 208.4, 256.6) ? eo(prog(T, 208.6, 1.8)) : (T >= 480.3 && T < 517.3 ? eo(prog(T, 480.8, 1.7)) : (T >= 596.7 ? 1 : 0));
    st.wipe = inR(T, 208.4, 212) ? prog(T, 208.6, 1.8) : (inR(T, 480.3, 484) ? prog(T, 480.8, 1.7) : (inR(T, 596.7, 598.5) ? prog(T, 596.7, 1.6) : 0));
    st.kraken = inR(T, 208.4, 256.6) ? Math.max(0.001, T - 208.8) : (T >= 480.3 && T < 517.3 || T >= 596.7 ? 40 : 0);
    st.glow = inR(T, 228.3, 232.0) ? 1.4 : 1;
    st.lift = inR(T, 232.0, 256.6) ? prog(T, 232.6, 2.8) : 0;
    st.mini = T > 246.5 && T < 256.6;
    st.licensees = inR(T, 217.0, 232.6) || (T >= 480.3 && T < 517.3);
    st.arlo = T >= 286.6;
    st.picks = inR(T, 313.0, 321.0) ? [{ kind: "heart", tp: 316.7 }, { kind: "tangled", tp: 317.95 }, { kind: "tangled", tp: 319.15 }] : (inR(T, 577.3, 581.0) ? [{ kind: "heart", tp: 577.9 }, { kind: "tangled", tp: 579.1 }] : []);
    st.ring = inR(T, 503.2, 517.3) || inR(T, 596.7, 600.3);
    st.wires = T >= 481.5 && T < 517.3 ? prog(T, 481.5, 2.5) : (T >= 596.7 ? 1 : 0);
    return st;
  }
  // the adviser's screen (hero monitor and full-frame draft shots share it)
  function draftState(T) {
    if (T < 150) {
      var cur = null;
      if (T >= 119.9) {
        var p1 = eio(prog(T, 120.2, 1.6)), p2 = eio(prog(T, 128.2, 0.8)), p3 = eio(prog(T, 129.6, 0.7));
        var x = lerp(lerp(1500, 1320, p1), 1580, p3), y = lerp(lerp(980, 700, p1), 912, p3); if (p2 > 0 && p3 === 0) { x = lerp(1320, 1180, p2); y = lerp(700, 610, p2); }
        cur = [Math.round(x), Math.round(y)];
      }
      return { mode: "draft", who: "octopus", draftP: Math.round(prog(T, 116.6, 1.6) * 30) / 30, review: Math.round(prog(T, 128.5, 0.4) * 10) / 10, edit: Math.round(prog(T, 129.1, 1.0) * 20) / 20,
        send: Math.round(prog(T, 130.4, 0.25) * 10) / 10, sent: Math.round(prog(T, 130.62, 0.5) * 10) / 10, cursor: cur };
    }
    if (T < 500) return { mode: "draft", who: "octopus", draftP: Math.round(prog(T, 157.2, 1.8) * 30) / 30, review: Math.round(prog(T, 160.2, 0.4) * 10) / 10, edit: 0,
      send: Math.round(prog(T, 160.9, 0.25) * 10) / 10, sent: Math.round(prog(T, 161.1, 0.5) * 10) / 10, rating: Math.round(prog(T, 163.6, 0.5) * 10) / 10,
      cursor: T > 159.5 ? [Math.round(lerp(1300, 1580, eio(prog(T, 159.6, 1.1)))), Math.round(lerp(760, 912, eio(prog(T, 159.6, 1.1))))] : null };
    return { mode: "draft", who: "uk", draftP: Math.round(prog(T, 559.9, 1.2) * 30) / 30, review: Math.round(prog(T, 561.2, 0.4) * 10) / 10, edit: Math.round(prog(T, 561.4, 0.8) * 20) / 20,
      send: Math.round(prog(T, 562.6, 0.25) * 10) / 10, sent: Math.round(prog(T, 562.85, 0.5) * 10) / 10,
      cursor: [Math.round(lerp(1250, 1580, eio(prog(T, 561.6, 0.9)))), Math.round(lerp(700, 912, eio(prog(T, 561.6, 0.9))))] };
  }
  function heroScreen(T) { var d = draftState(T); if (T < 116.4) d.draftP = 0; return d; }
  function inboxState(T) {
    return { mode: "inbox", count: 214, scroll: Math.round((T % 60) * 38), draft: inR(T, 180.0, 183.0) ? Math.round(prog(T, 180.2, 0.7) * 20) / 20 : 0 };
  }
  function screen(T, shot) {
    if (inR(T, 26.6, 29.4)) return Object.assign(chatState(T), { bgCss: "#e9e6e1" });
    if (inR(T, 458.9, 466.5)) { var c = chatState(24.4 + 5.0 + prog(T, 459.0, 3.0) * 0.1); c.msgs = [{ who: "bot", text: BOT[0] }, { who: "me", text: "human" }, { who: "bot", text: BOT[1] }, { who: "me", text: "HUMAN", big: true }, { who: "bot", text: BOT[2] }, { who: "me", text: "speak to a human" }].slice(0, T < 462.05 ? 0 : 1 + Math.min(5, Math.floor(prog(T, 462.1, 2.6) * 6)));
      c.typing = ""; c.dim = Math.round(prog(T, 465.0, 1.4) * 20) / 20; return c; }
    if (inR(T, 406.2, 422.6)) return { mode: "forum", variant: 0, show: Math.round(prog(T, 409.45, 0.4) * 10) / 10, scroll: Math.round((T - 406.2) * 52), sharpen: T > 420.1 ? [7] : [], bgCss: "#f4f5f7" };
    if (inR(T, 422.6, 431.8)) return { mode: "forum", variant: 1, scroll: Math.round((T - 422.6) * 48), sharpen: T > 426.9 ? [6] : [], bgCss: "#f4f5f7" };
    if (inR(T, 119.9, 166.2) || inR(T, 559.9, 563.9)) return draftState(T);
    if (inR(T, 173.3, 183.0) || inR(T, 521.3, 526.0)) return inboxState(T);
    if (inR(T, 320.8, 327.3) || inR(T, 580.9, 585.2)) {
      var base = T > 500 ? 580.9 : 320.8, lab = T > 500 ? prog(T, 581.0, 0.35) : prog(T, 322.1, 0.35), btn = T > 500 ? prog(T, 582.8, 0.4) : prog(T, 324.2, 0.4);
      var cur = T > 500 ? null : (T > 324.6 ? [Math.round(lerp(1300, 1010, eio(prog(T, 324.7, 1.2)))), Math.round(lerp(980, 880, eio(prog(T, 324.7, 1.2))))] : null);
      return { mode: "arlo", label: Math.round(lab * 20) / 20, button: Math.round(btn * 20) / 20, glow: Math.round((0.5 + 0.5 * Math.sin(T * 4)) * 10) / 10 * (btn > 0.9 ? 1 : 0), cursor: cur };
    }
    return { mode: "inbox", count: 214 };
  }
  function press(T) { return { run: 1, stack: T < 44.4 ? 8 : 8 + (T - 44.4) * 10, page: true }; }
  function map(T) { return { lit: T >= 147 ? 1 : prog(T, 51.9, 3.6), offices: T >= 147 ? prog(T, 147.2, 2.3) : 0, dials: inR(T, 56.6, 59.1) ? prog(T, 56.8, 1.4) : 0 }; }
  function globe(T) { return { rot: lerp(0.05, 0.84, eio(prog(T, 193.1, 11.5))), tilt: 0.36, arc: prog(T, 201.8, 1.9) }; }
  function uk(T) {
    var s = inR(T, 170, 193.1) ? inboxState(T) : (T > 517 ? inboxState(T) : { mode: "inbox", count: 214, scroll: Math.round((T % 60) * 38) });
    if (inR(T, 180.0, 193.1)) s.draft = 1;
    return { screen: s, pile: 34, phone: prog(T, 589.3, 0.9), systems: inR(T, 540.5, 556.0) ? 1 : 0,
      merge: T < 545.3 ? prog(T, 543.2, 1.0) : 1 - prog(T, 545.5, 0.8), ai: inR(T, 534.7, 556.0) ? prog(T, 534.7, 0.6) : 0 };
  }
  function brand(T) { return { rise: prog(T, 33.3, 1.5), x: 3.3 }; }   // r2: already rising at the 33.9 cut

  var F = window.F07 = { shots: SHOTS, shotAt: shotAt, anchors: [], duration: FULL, at: at,
    state: { studio: studio, hq: hq, heroScreen: heroScreen, screen: screen, press: press, map: map, globe: globe, uk: uk, brand: brand } };

  // ============================================================ DOM overlays on one paused timeline
  function build() {
  try {
  var root = document.getElementById("root");
  var L = root.querySelector(".layer");
  function hide(e) { e.style.opacity = "0"; }
  function el(tag, cls, parent, html) { var e = document.createElement(tag); if (cls) e.className = cls; if (html !== undefined) e.innerHTML = html; (parent || L).appendChild(e); return e; }
  var full = gsap.timeline({ paused: true });
  function show(e, a, b, o) {
    o = o || {}; hide(e);
    full.fromTo(e, { opacity: 0, filter: "blur(" + (o.blur === undefined ? 10 : o.blur) + "px)", y: o.y || 0, x: o.x || 0, scale: o.s0 || 1 },
      { opacity: 1, filter: "blur(0px)", y: 0, x: 0, scale: 1, duration: o.din || 0.45, ease: o.ein || "power2.out", immediateRender: false }, a);
    if (b !== undefined) full.to(e, { opacity: 0, filter: "blur(8px)", duration: o.dout || 0.3, ease: "power1.in" }, b - (o.dout || 0.3));
  }
  function slam(e, a, s0) { hide(e); full.fromTo(e, { opacity: 0, scale: s0 || 1.28, filter: "blur(10px)" }, { opacity: 1, scale: 1, filter: "blur(0px)", duration: 0.2, ease: "power3.out", immediateRender: false }, a); }
  function stamp(text, a, b, cls) { var s = el("div", "stamp" + (cls ? " " + cls : ""), L, '<span class="tick"></span><span>' + text + "</span>"); show(s, a, b, { blur: 8, x: -24 }); return s; }
  function plate(text, a, b, cls) {
    var p = el("div", "plate" + (cls ? " " + cls : ""), L, '<div class="in">' + text + (cls && cls.indexOf("ul") >= 0 ? '<div class="ul"></div>' : "") + "</div>");
    hide(p);
    full.fromTo(p, { opacity: 0, y: 28 }, { opacity: 1, y: 0, duration: 0.26, ease: "power3.out", immediateRender: false }, a);
    var ul = p.querySelector(".ul"); if (ul) full.fromTo(ul, { scaleX: 0 }, { scaleX: 1, duration: 0.35, ease: "power2.out", immediateRender: false }, a + 0.16);
    full.to(p, { opacity: 0, y: -14, duration: 0.22, ease: "power2.in" }, b - 0.22);
    return p;
  }
  function chapter(k, n, a, b) {
    var c = el("div", "chap", L, '<div class="k">' + k + '</div><div class="bar"></div><div class="n">' + n + "</div>");
    hide(c); full.fromTo(c, { opacity: 0, x: -60 }, { opacity: 1, x: 0, duration: 0.5, ease: "power3.out", immediateRender: false }, a);
    full.fromTo(c.querySelector(".bar"), { scaleY: 0 }, { scaleY: 1, duration: 0.5, ease: "power2.out", immediateRender: false }, a + 0.12);
    full.fromTo(c.querySelector(".n"), { letterSpacing: "0.06em" }, { letterSpacing: "-0.01em", duration: b - a, ease: "none", immediateRender: false }, a);
    full.to(c, { opacity: 0, x: 40, duration: 0.3, ease: "power2.in" }, b - 0.3);
  }
  function bubble(scene, p, html, a, b, cls) {
    var an = el("div", "anch", L); var bub = el("div", "bub" + (cls ? " " + cls : ""), an, html);
    hide(bub);
    full.fromTo(bub, { opacity: 0, scale: 0.4 }, { opacity: 1, scale: 1, duration: 0.3, ease: "back.out(2.2)", immediateRender: false }, a);
    full.to(bub, { opacity: 0, scale: 0.9, duration: 0.2 }, b - 0.2);
    F.anchors.push({ scene: scene, p: p, el: an });
  }
  // a dial readout: slams in when its needle lands, then shows only inside the windows where the dials are the subject
  function readout(p, text, a, wins, cls) {
    var an = el("div", "anch", L); var r = el("div", "readout" + (cls ? " " + cls : ""), an, text);
    slam(r, a, 1.45);
    wins.forEach(function (w, i) { if (w[0] > a) full.set(r, { opacity: 1 }, w[0]); full.set(r, { opacity: 0 }, w[1]); });
    F.anchors.push({ scene: "studio", p: p, el: an });
  }
  function rstamp(scene, p, text, a, b) {
    var an = el("div", "anch", L);
    var s = el("div", "bub", an, text);
    s.style.cssText = "background:rgba(255,255,255,0.95);color:#d8382a;border:7px solid #d8382a;font-family:var(--heavy);font-weight:800;font-size:58px;letter-spacing:0.06em;text-transform:uppercase;border-radius:14px;box-shadow:none;bottom:-30px";
    s.className = "bub rs"; hide(s);
    full.fromTo(s, { opacity: 0, scale: 2.2, rotation: -14 }, { opacity: 1, scale: 1, rotation: -5, duration: 0.18, ease: "power4.in", immediateRender: false }, a);
    full.to(s, { opacity: 0, duration: 0.2 }, b - 0.2);
    F.anchors.push({ scene: scene, p: p, el: an });
  }
  function figure(num, lab, a, aLab, b, cls) {
    var f = el("div", "fig" + (cls ? " " + cls : ""), L, '<div class="num">' + num + '</div><div class="lab">' + lab + "</div>");
    slam(f.querySelector(".num"), a); slam(f.querySelector(".lab"), aLab);
    full.to(f, { opacity: 0, filter: "blur(10px)", duration: 0.3 }, b - 0.3);
  }
  function dim(a, b, v, din, cls) { var d = el("div", cls || "dim", L); hide(d); full.to(d, { opacity: v, duration: din || 0.25 }, a); full.to(d, { opacity: 0, duration: 0.25 }, b - 0.25); return d; }
  function l3(name, role, a, b) {
    var l = el("div", "l3", L, '<div class="name">' + name + '</div><div class="rule"></div><div class="role">' + role + "</div>");
    show(l, a, b, { blur: 8, x: -30 }); full.fromTo(l.querySelector(".rule"), { scaleX: 0 }, { scaleX: 1, duration: 0.6, ease: "power2.inOut", immediateRender: false }, a + 0.1);
  }
  // quote card: words either all at once or synced to the voice ([[word, t], ...]); `ul` underlines a span at a time
  function quote(o) {
    var q = el("div", "quote", L, '<div class="qt"></div><div class="qw"><span class="tick"></span>' + o.who + '</div><div class="qs">' + o.src + "</div>");
    var qt = q.querySelector(".qt");
    if (o.words) {
      o.words.forEach(function (w) { var sp = el("span", "w", qt, w[0] + " "); if (w[2]) { sp.innerHTML = "<u>" + w[0] + "</u> "; }
        full.set(sp, { opacity: 0.3 }, o.a); full.fromTo(sp, { opacity: 0.3 }, { opacity: 1, duration: 0.22, ease: "power2.out", immediateRender: false }, w[1]); });
    } else { qt.innerHTML = o.html; }
    show(q, o.a, o.b, { blur: 14, din: 0.6 });
    if (o.ul) o.ul.forEach(function (u) { var e = qt.querySelectorAll("u")[u[0]]; if (e) full.fromTo(e, { "--u": "0%" }, { "--u": "100%", duration: 0.55, ease: "power2.out", immediateRender: false }, u[1]); });
    (o.moves || [[o.a, 1], [o.b, 1.04]]).forEach(function (m, i, arr) { if (i === 0) full.set(qt, { scale: m[1], x: m[2] || 0, y: m[3] || 0 }, o.a); else full.to(qt, { scale: m[1], x: m[2] || 0, y: m[3] || 0, duration: m[0] - arr[i - 1][0], ease: "sine.inOut" }, arr[i - 1][0]); });
    return q;
  }
  // document card: verbatim headline + lines; the camera (a transform on the sheet) travels across it
  function doc(o) {
    var d = el("div", "doc", L); var sh = el("div", "sheet", d,
      '<div class="src"><span>' + o.src[0] + "</span><span>" + o.src[1] + "</span></div>" + (o.kick ? '<div class="kick">' + o.kick + "</div>" : "") +
      '<div class="h1">' + o.h1 + "</div>" + (o.lines || []).map(function (l) { return '<div class="line">' + l + "</div>"; }).join("") +
      '<div class="body">' + "<i></i><i></i><i></i><i class='s'></i><i></i><i></i><i></i><i class='s'></i><i></i><i></i>" + "</div>");
    hide(d); full.to(d, { opacity: 1, duration: 0.18 }, o.a); full.to(d, { opacity: 0, duration: 0.18 }, o.b - 0.18);
    o.moves.forEach(function (m, i, arr) { if (i === 0) full.set(sh, { scale: m[1], x: m[2], y: m[3], rotation: m[4] || 0 }, m[0]); else full.to(sh, { scale: m[1], x: m[2], y: m[3], rotation: m[4] || 0, duration: m[0] - arr[i - 1][0], ease: m[5] || "sine.inOut" }, arr[i - 1][0]); });
    (o.ul || []).forEach(function (u) { var e = sh.querySelectorAll("u")[u[0]]; if (e) full.fromTo(e, { "--u": "0%" }, { "--u": "100%", duration: 0.5, ease: "power2.out", immediateRender: false }, u[1]); });
    (o.hl || []).forEach(function (h) { var e = sh.querySelectorAll(".hl")[h[0]]; if (e) { full.fromTo(e, { "--h": "0%" }, { "--h": "100%", duration: 0.6, ease: "power2.out", immediateRender: false }, h[1]); full.set(e, { attr: { class: "hl on" } }, h[1] + 0.3); } });
    return sh;
  }
  function typed(text, a, b, cls, dt) {
    var t = el("div", "typed" + (cls ? " " + cls : ""), L, "");
    text.split("").forEach(function (ch, i) { var sp = el("span", "", t, ch === " " ? "&nbsp;" : ch); full.set(sp, { opacity: 1 }, a + i * (dt || 0.045)); });
    full.fromTo(t, { scale: 1 }, { scale: 1.05, duration: b - a, ease: "none", immediateRender: false }, a);
    full.to(t, { opacity: 0, duration: 0.25 }, b - 0.25);
  }
  function focus(s) { var f = el("div", "focus", L); hide(f); full.set(f, { opacity: 1, "--fx": s.focus[0] + "%", "--fy": s.focus[1] + "%", "--fw": s.focus[2] + "%", "--fh": s.focus[3] + "%", "--fb": s.focus[4] + "px" }, s.t0); full.set(f, { opacity: 0 }, s.t1); }
  SHOTS.forEach(function (s) { if (s.focus) focus(s); });
  (function () { var run = null; SHOTS.concat([{}]).forEach(function (s) {   // one dim per run of consecutive quote-backdrop shots
    if (s.qbg && run && Math.abs(run[1] - s.t0) < 1e-6) { run[1] = s.t1; return; }
    if (run) dim(run[0], run[1], run[2], 0.15); run = s.qbg ? [s.t0, s.t1, s.qbg] : null; }); })();

  // ================= COLD OPEN
  // HOOK (29 Sep): frame 0 carries the stake in huge type over the running press: the column's two numbers
  (function () {
    var d = dim(0, 3.0, 0.5, 0.01); full.set(d, { opacity: 0.5 }, 0);
    var h = el("div", "hook", L, '<div class="c m"><div class="n">80%</div><div class="l">AI emails</div></div><div class="vs">vs</div><div class="c"><div class="n">65%</div><div class="l">Trained staff</div></div><div class="k">Customer satisfaction · one newspaper column</div>');
    full.set(h, { opacity: 1 }, 0);
    full.fromTo(h, { scale: 1.0 }, { scale: 1.07, duration: 3.0, ease: "none", immediateRender: true }, 0);
    full.fromTo(h.querySelector(".c.m .n"), { y: 0 }, { y: -6, duration: 0.2, yoyo: true, repeat: 1, immediateRender: false }, 0.1);
    full.to(h, { opacity: 0, filter: "blur(8px)", duration: 0.2 }, 2.8);
  })();
  stamp("May 2023 · London", 0.25, 5.6);
  // dial readouts (slam when the needle lands); small versions after the climax re-layout
  var W23 = [[16.85, 23.7], [84.7, 89.4], [101.3, 108.9]], W4 = [[339.4, 363.4], [431.8, 435.3], [592.4, 596.7]];
  readout("dialTop0", "80%", 19.0, [[19.0, 21.3], [84.7, 89.4], [101.3, 108.9]], "mag");   // r2: not in the close-ups (clipped at the top)
  readout("dialTop1", "65%", 84.7, [[84.7, 89.4], [101.3, 108.9]]);
  var W4b = [[339.4, 347.9], [352.0, 363.4], [592.4, 596.7]];   // r2: not in the 432 oblique (clipped at the left edge)   // hidden in the low-angle replay (they collide)
  readout("dialTop0", "80%", 339.4, W4b, "mag sm");
  readout("dialTop1", "65%", 339.4, W4b, "sm");
  readout("dialTop2", "76%", 341.05, W4, "mag sm");
  readout("dialTop3", "72%", 347.05, W4, "sm");
  // r3: the film's central question, full-frame (was a small plate)
  (function () { var d = dim(31.9, 33.85, 0.9, 0.12); var q = el("div", "qcard", L, "Prefer the <span class='m'>machine?</span>"); slam(q, 31.95, 1.25);
    full.fromTo(q, { scale: 1 }, { scale: 1.04, duration: 1.7, ease: "none", immediateRender: false }, 32.15); full.to(q, { opacity: 0, duration: 0.15 }, 33.45); })();   // the card is gone before the dim lifts off the phone
  (function () {
    var w = el("div", "wordmark", L, '<img src="img/octopus-logo-white.svg" alt=""><div class="sub">Chief executive: Greg Jackson</div>'); hide(w);
    var sub = w.querySelector(".sub"); hide(sub);
    full.fromTo(w, { opacity: 0, scale: 1.12, filter: "blur(14px)" }, { opacity: 1, scale: 1, filter: "blur(0px)", duration: 0.35, ease: "power3.out", immediateRender: false }, 34.55);
    full.fromTo(w.querySelector("img"), { scale: 1 }, { scale: 1.05, duration: 3.6, ease: "none", immediateRender: false }, 34.55);
    full.fromTo(sub, { opacity: 0, y: 16 }, { opacity: 1, y: 0, duration: 0.3, immediateRender: false }, 37.2);
    full.to(w, { opacity: 0, duration: 0.2 }, 37.9);
  })();
  (function () {
    var ph = el("div", "photo", L, '<div class="fr"><img src="img/greg-jackson.jpg" alt=""></div><div class="credit">Photo: Octopus Energy, via Wikimedia Commons, CC BY-SA 4.0</div>'); hide(ph);
    full.set(ph, { opacity: 1 }, 38.1);
    full.fromTo(ph.querySelector("img"), { scale: 1.0, x: 0 }, { scale: 1.09, x: -30, duration: 3.3, ease: "none", immediateRender: false }, 38.1);
    full.to(ph, { opacity: 0, duration: 0.15 }, 41.25);
  })();
  l3("Greg Jackson", "Chief executive · Octopus Energy", 38.25, 41.3);
  plate("An advert in The Times?", 46.5, 49.0, "ul");
  stamp("April 2026 · Great Britain", 52.1, 58.95);
  figure("8,000,000", "customers", 55.3, 55.9, 58.9);
  plate("Britain's biggest energy supplier", 57.1, 58.95, "light");
  (function () {
    dim(59.0, 62.9, 0.72, 0.2, "wash");
    var t = el("div", "title", L, '<div class="t">Who wrote<br>the better <span class="m">email?</span></div>'); hide(t);
    full.fromTo(t, { opacity: 0 }, { opacity: 1, duration: 0.05, immediateRender: false }, 59.05);
    full.fromTo(t.querySelector(".t"), { letterSpacing: "0.12em", filter: "blur(16px)" }, { letterSpacing: "-0.02em", filter: "blur(0px)", duration: 1.0, ease: "power2.out", immediateRender: false }, 59.05);
    full.fromTo(t.querySelector(".t"), { scale: 1 }, { scale: 1.06, duration: 3.8, ease: "none", immediateRender: false }, 59.05);
    full.to(t, { opacity: 0, filter: "blur(10px)", duration: 0.3 }, 62.6);
  })();
  // ================= PART ONE
  chapter("Part one", "The column", 62.95, 64.65);
  doc({ a: 64.7, b: 71.7, src: ["Business Insider", "9 May 2023"],
    h1: "AI is doing the work of <u>250 people</u> at an energy company and satisfying customers better than trained workers, CEO says",
    moves: [[64.7, 0.8, 0, 120], [66.7, 0.86, 0, 60], [66.72, 1.3, -40, 210], [71.7, 1.4, -120, 240]], ul: [[0, 68.9]] });
  plate("More than a third", 74.25, 76.95, "mag");
  quote({ a: 79.3, b: 84.65, who: "Greg Jackson, in The Times", src: "May 2023 · as quoted by Business Insider",
    words: [["“…comfortably", 79.5, 1], ["better", 80.0, 1], ["than", 80.8], ["the", 81.0], ["65%", 81.2], ["achieved", 81.8], ["by", 82.1], ["skilled,", 82.3], ["trained", 83.1], ["people.”", 83.4]],
    ul: [[0, 79.6], [1, 80.05]], moves: [[79.3, 1], [81.9, 1.02], [81.92, 1.1, -60, -30], [84.65, 1.14, -70, -30]] });
  rstamp("studio", "pair23", "Source: Octopus", 87.85, 89.35);
  bubble("hq", "pileA", "Easy", 91.3, 97.4, "light");
  bubble("hq", "pileB", "Hard", 91.9, 97.4);
  (function () { var q = el("div", "typed", L, "A real result?"); slam(q, 98.1, 1.3); full.fromTo(q, { scale: 1 }, { scale: 1.05, duration: 2.7, ease: "none", immediateRender: false }, 98.3); full.to(q, { opacity: 0, duration: 0.25 }, 101.0); })();
  plate("Or a lucky number?", 101.6, 104.3, "ul");
  bubble("studio", [4.25, 0.5, 0.9], "2026", 107.2, 108.85, "light");
  // ================= PART TWO
  chapter("Part two", "Who pressed send", 109.0, 112.1);
  bubble("hq", "rows", "250 people", 112.0, 113.25, "light");
  quote({ a: 122.5, b: 126.25, who: "Octopus Energy representative", src: "to Business Insider · May 2023",
    html: "“Our team <u>supervises</u> the answers AI provides”", ul: [[0, 123.9]], moves: [[122.5, 1], [126.25, 1.05]] });
  (function () {   // DRAFT / REVIEW / SEND steps
    var s = el("div", "splitlab", L, ""); s.style.cssText = "position:absolute;left:640px;top:950px;display:flex;justify-content:flex-start;gap:26px";
    ["Draft", "Review", "Send"].forEach(function (w, i) { var p = el("div", "", s, w); p.style.cssText = "padding:14px 34px;border-radius:40px;font-family:var(--ui);font-weight:700;font-size:46px;background:rgba(17,20,25,0.12);color:#111419";
      hide(p); full.fromTo(p, { opacity: 0, y: -20 }, { opacity: 1, y: 0, duration: 0.25, immediateRender: false }, 126.35 + i * 0.15);
      full.to(p, { backgroundColor: i === 0 ? "#e0157f" : "#111419", color: "#ffffff", duration: 0.2 }, [126.4, 129.3, 130.4][i]); });
    full.to(s, { opacity: 0, duration: 0.2 }, 131.2);
  })();
  plate("Unlikely to cost jobs", 133.6, 135.25, "light");
  plate("Work the AI had taken on", 139.6, 142.4, "mag");
  plate("Not people let go", 142.55, 143.95, "light");
  (function () {
    quote({ a: 150.0, b: 153.15, who: "Greg Jackson", src: "to The Times · May 2023",
      words: [["“huge", 150.1, 1], ["and", 150.6, 1], ["rapid", 150.8, 1], ["dislocation”", 151.1, 1]], ul: [[0, 151.6], [1, 151.75], [2, 151.9], [3, 152.05]], moves: [[150.0, 1.0], [153.15, 1.06]] });
  })();
  stamp("Summer 2023", 153.4, 156.95);
  bubble("hq", "hero", "The AI wrote", 158.95, 160.85, "mag");
  stamp("According to Octopus", 162.2, 166.05, "src");
  // ================= MID-ROLL
  (function () { var a = el("div", "splitlab", L, '<div class="sl">Octopus: a whole team</div><div class="sr">Most UK businesses</div><div class="bar"></div>'); show(a, 166.3, 169.95, { blur: 8 }); })();
  bubble("uk", "monitor", "One shared inbox", 172.2, 173.25, "light");
  bubble("uk", "person", "Always behind", 175.0, 176.25);
  (function () {
    dim(183.0, 193.0, 0.5, 0.4);
    var c = el("div", "midroll", L, '<div class="k">Free guide</div><div class="t">5 jobs AI can take off a small business</div><div class="s">and how to start without upsetting a single customer</div><div class="d"><span class="arrow"></span>Linked in the description</div>');
    hide(c); full.fromTo(c, { opacity: 0, x: -60, filter: "blur(12px)" }, { opacity: 1, x: 0, filter: "blur(0px)", duration: 0.55, ease: "power3.out", immediateRender: false }, 183.1);
    [".t", ".s", ".d"].forEach(function (sel, i) { var x = c.querySelector(sel); hide(x); full.fromTo(x, { opacity: 0, y: 24 }, { opacity: 1, y: 0, duration: 0.4, immediateRender: false }, [183.35, 187.4, 190.0][i]); });   // 29 Sep: the title lands with the card (no empty card at the cut)
    full.fromTo(c, { scale: 1 }, { scale: 1.03, duration: 9.8, ease: "none", immediateRender: false }, 183.1);
    full.to(c, { opacity: 0, x: 40, duration: 0.35 }, 192.7);
  })();
  // ================= PART THREE
  chapter("Part three", "The other announcement", 193.2, 196.4);
  stamp("7 June 2023", 196.6, 204.5);
  bubble("globe", "london", "Kraken", 199.1, 201.25, "light");
  bubble("globe", "us", "United States", 203.3, 204.55, "light");
  doc({ a: 204.6, b: 208.4, src: ["Octopus Energy press release", "7 June 2023"],
    h1: "Energy tech giant Kraken lands first US licensing deal with energy manager <u>Tenaska Power Services</u>",
    moves: [[204.6, 0.86, 0, 100], [208.4, 1.06, -60, 140]], ul: [[0, 206.1]] });
  figure("30,000,000", "energy accounts", 212.2, 212.6, 214.95);
  plate("The software that runs customer accounts", 215.7, 219.6, "light");
  bubble("hq", [-30, 3.5, -16], "Other companies", 218.0, 219.65, "light");
  bubble("hq", "trunk", "The system", 224.3, 228.2, "light");
  bubble("hq", "top", "The AI", 226.2, 228.2, "mag");
  stamp("18 September 2025", 230.0, 236.1);
  plate("Spun off as its own company", 233.4, 236.1, "light");
  stamp("29 December 2025", 236.35, 246.8);
  doc({ a: 236.2, b: 246.9, src: ["Kraken press release", "29 December 2025"],
    h1: "Octopus Energy Group to spin out Kraken at valuation of <u>$8.65bn</u>",
    lines: ["<span class='hl'>$1bn</span> Kraken investment round brings world-class investors"],
    moves: [[236.2, 0.86, 0, 120], [240.7, 0.9, 0, 90], [240.72, 1.35, 60, 330], [246.9, 1.45, 80, 340]], ul: [[0, 244.3]], hl: [[0, 239.2]] });
  bubble("hq", "krTop", "AI emails", 248.3, 252.2, "mag");
  bubble("hq", "krMid", "Kraken", 250.3, 256.5, "light");
  // ================= PART FOUR
  chapter("Part four", "The rules", 256.7, 259.9);
  stamp("5 February 2026", 257.3, 263.5);
  doc({ a: 260.0, b: 267.3, src: ["Ofgem blog", "5 February 2026"],
    h1: "Understanding AI in the energy sector: the benefits, the risks and your rights",
    lines: ["This joint blog post from <span class='hl'>Ofgem and the Energy Ombudsman</span> helps consumers understand the benefits and risks of AI"],
    moves: [[260.0, 0.86, 0, 110], [263.6, 0.9, 0, 80], [263.62, 1.3, 60, -40], [267.3, 1.36, 40, -60]], hl: [[0, 261.2]] });
  // ================= PART FIVE
  chapter("Part five", "The second test", 284.7, 286.55);
  stamp("7 July 2026", 285.0, 291.2);
  doc({ a: 286.6, b: 289.4, src: ["Octopus Energy press release", "7 July 2026"],
    h1: "Octopus Energy’s AI trial wins customer approval",
    lines: ["Customers are giving Octopus Energy’s new AI customer service assistant, Arlo, a big thumbs up"],
    moves: [[286.6, 0.9, 0, 100], [289.4, 0.98, -20, 110]] });
  bubble("hq", "arlo", "Arlo", 292.7, 293.65, "mag big");
  figure("8,000", "emails a week", 296.2, 296.5, 297.95, "dark");
  figure("4%", "of UK customer emails", 298.5, 298.9, 302.75, "dark");
  (function () { var a = el("div", "splitlab", L, '<div class="sl">2023: more than a third</div><div class="sr">2026: 4%</div><div class="bar"></div>'); show(a, 302.9, 307.35, { blur: 8 }); })();
  bubble("hq", "limits", "The limits, written down", 311.6, 312.95, "light");
  bubble("hq", "arlo", "Routine questions", 314.2, 316.15, "mag");
  bubble("hq", [-6.0, 1.6, 5.2], "Vulnerable customers", 316.4, 317.85, "light");
  bubble("hq", [-6.0, 1.6, 5.2], "Sensitive cases", 317.9, 319.05, "light");
  bubble("hq", [-6.0, 1.6, 5.2], "Complex complaints", 319.1, 320.75, "light");
  plate("Written into how it works", 332.6, 336.2, "mag");
  // ================= CLIMAX
  stamp("2023 · 2026", 336.7, 339.3);
  plate("AI ahead, both times", 353.8, 355.7, "light");
  (function () {
    dim(357.3, 359.85, 0.8, 0.3, "wash");
    var g = el("div", "gap", L, '<span class="a">15</span><span class="arr">→</span><span class="b">4</span><div class="l">points between AI and staff</div>'); hide(g);
    full.to(g, { opacity: 1, duration: 0.2 }, 357.5);
    slam(g.querySelector(".a"), 357.7); slam(g.querySelector(".arr"), 358.4, 1.1); slam(g.querySelector(".b"), 358.9); slam(g.querySelector(".l"), 359.0, 1.05);
    full.to(g, { opacity: 0, duration: 0.25 }, 359.6);
  })();
  rstamp("studio", "all", "Source: Octopus", 360.45, 363.35);
  (function () { var q = el("div", "typed sm", L, "No independent audit found"); slam(q, 364.75, 1.2); full.fromTo(q, { scale: 1 }, { scale: 1.04, duration: 2.1, ease: "none", immediateRender: false }, 364.95); full.to(q, { opacity: 0, duration: 0.25 }, 367.05); })();
  doc({ a: 367.3, b: 371.1, src: ["Octopus Energy press release", "7 July 2026"], h1: "Octopus Energy’s AI trial wins customer approval",
    lines: ["<span class='hl'>Early feedback from customers has been overwhelmingly positive.</span>"],
    moves: [[367.3, 1.2, 0, -240], [371.1, 1.3, -40, -300]], hl: [[0, 369.0]] });
  quote({ a: 371.1, b: 378.95, who: "Kelly, a customer from Wales", src: "quoted by Octopus Energy · July 2026",
    html: "“I was very impressed with the response I received, <u>especially as it was a bot</u> who responded!”", ul: [[0, 375.6]],
    moves: [[371.1, 0.92], [375.4, 0.95], [375.5, 1.1, -40, -20], [378.95, 1.14, -50, -20]] });
  l3("Ashley Firth", "Deputy CTO · Octopus Energy", 382.5, 385.5);
  quote({ a: 385.6, b: 389.85, who: "Ashley Firth, Deputy CTO, Octopus Energy", src: "press release · 7 July 2026",
    words: [["“Too", 385.8], ["many", 385.9], ["chatbots", 386.1], ["have", 386.7], ["been", 386.8], ["built", 387.0], ["to", 387.2], ["keep", 387.4, 1], ["customers", 387.7, 1], ["away", 388.1, 1], ["from", 388.3, 1], ["people.”", 388.5, 1]],
    ul: [[0, 388.7], [1, 388.8], [2, 388.9], [3, 389.0], [4, 389.1]] });
  quote({ a: 389.9, b: 392.25, who: "Ashley Firth, Deputy CTO, Octopus Energy", src: "press release · 7 July 2026",
    words: [["“We", 390.1], ["wanted", 390.2], ["to", 390.5], ["build", 390.6], ["one", 390.8], ["that", 391.1], ["does", 391.2], ["the", 391.3, 1], ["opposite.”", 391.5, 1]], ul: [[0, 391.7], [1, 391.8]] });
  plate("Removing the repetitive things", 401.5, 404.95, "light");
  // ================= PART SIX
  chapter("Part six", "The complaints", 406.3, 409.4);
  stamp("January 2026 · Reddit", 410.6, 422.4);
  plate("Complex questions handled badly", 416.0, 417.95);
  stamp("June 2026 · Facebook group", 422.8, 431.6);
  plate("Posts online, not a failure rate", 432.0, 435.2, "light");
  plate("Published figures: AI ahead", 436.4, 438.5, "light");
  stamp("17 March 2026", 438.8, 446.4);
  doc({ a: 438.6, b: 442.0, src: ["The Guardian", "17 March 2026"], h1: "UK energy: about 14m households getting ‘below-average’ service",
    lines: ["Ecotricity ranked top in Citizens Advice survey, followed by Outfox, <span class='hl'>Octopus</span> and Co-operative"],
    moves: [[438.6, 0.9, 0, 100], [442.0, 1.0, -30, 60]], hl: [[0, 440.2]] });
  (function () {   // Citizens Advice: 16 suppliers, Octopus third. r2: the four the Guardian names (17 Mar 2026, doc card above),
    // then the other twelve as one line (unnamed rows read as placeholder bars and ran over the date stamp)
    var r = el("div", "rank", L, '<div class="h">Citizens Advice · customer service · 16 suppliers</div>'); hide(r);
    ["Ecotricity", "Outfox the Market", "Octopus Energy", "Co-operative Energy"].forEach(function (nm, k) {
      var row = el("div", "r big", r, '<b></b><span class="n">' + (k + 1) + '</span><span class="lab' + (k === 2 ? "" : " dk") + '">' + nm + "</span>");
      if (k === 2) { var f = el("div", "f", row, ""); f.style.width = "1260px"; row.appendChild(row.querySelector(".lab"));
        full.fromTo(f, { scaleX: 0 }, { scaleX: 1, duration: 0.5, ease: "power3.out", immediateRender: false }, 445.85); }
      full.fromTo(row.querySelector("b"), { scaleX: 0 }, { scaleX: 1, duration: 0.3, ease: "power2.out", immediateRender: false }, 442.2 + k * 0.12);
      full.fromTo(row.querySelector(".lab"), { opacity: 0 }, { opacity: 1, duration: 0.2, immediateRender: false }, k === 2 ? 446.2 : 442.4 + k * 0.12); });
    var more = el("div", "more", r, "+ 12 more suppliers, 5th to 16th"); full.fromTo(more, { opacity: 0 }, { opacity: 1, duration: 0.3, immediateRender: false }, 443.0);
    full.to(r, { opacity: 1, duration: 0.2 }, 442.0);
    full.fromTo(r, { scale: 1, x: 0, y: 0 }, { scale: 1.05, duration: 4.6, ease: "none", immediateRender: false }, 442.0);
    full.to(r, { scale: 1.3, x: 60, y: 40, duration: 3.5, ease: "sine.inOut" }, 446.65);
    full.to(r, { opacity: 0, duration: 0.2 }, 450.0);
  })();
  bubble("hq", [-8, 1.8, -3], "People", 451.9, 453.35, "light");
  bubble("hq", "arlo", "Machines", 452.4, 453.35, "mag");
  plate("Can't settle it on its own", 454.6, 458.8, "light");
  // ================= PART SEVEN
  chapter("Part seven", "Why here", 459.0, 462.0);
  quote({ a: 466.5, b: 470.15, who: "Ashley Firth", src: "July 2026", html: "“Too many chatbots have been built to <u>keep customers away from people.</u>”", ul: [[0, 468.0]], moves: [[466.5, 0.9], [470.15, 0.94]] });
  doc({ a: 470.2, b: 480.3, src: ["Octopus Energy press release", "7 July 2026"], h1: "Octopus Energy’s AI trial wins customer approval",
    lines: ["New AI customer support chatbot, Arlo, achieved a 76% customer satisfaction score vs. 72% from comparable human responses",
      "<span class='hl'>Built on the Kraken operating system</span> to work alongside Octopus’ award-winning customer service team…"],
    moves: [[470.2, 0.88, 0, 100], [474.8, 0.94, 0, 60], [474.82, 1.35, 40, -330], [480.3, 1.5, 40, -380]], hl: [[0, 475.5]] });
  plate("The software the AI works on", 486.8, 488.55, "mag");
  plate("Our reading", 488.8, 492.0, "light");
  bubble("hq", "trunk", "Built to run customer accounts", 498.8, 501.0, "light");
  bubble("hq", "kr", "There before the AI", 501.1, 503.15, "light");
  bubble("hq", [0, 3.8, 0], "Keeps people close", 506.0, 507.55, "light");
  bubble("hq", [-1.2, 3.6, -0.6], "Only routine emails", 509.3, 511.15, "mag");
  bubble("hq", [1.2, 3.6, 0.6], "Says what it is", 511.3, 513.2, "mag");
  bubble("hq", [0, 3.7, 0], "Ask for a person", 513.3, 517.2, "light big");
  // ================= PART EIGHT
  chapter("Part eight", "What this means for your business", 517.4, 520.7);
  bubble("uk", "ai", "Start with the AI?", 535.2, 536.45, "mag");
  (function () {
    var rb = el("div", "rules", L, "");
    var ICO = ['<svg width="220" height="200" viewBox="0 0 220 200"><path d="M10 40h70l20 22h110v128H10z" fill="#111419"/><rect x="10" y="80" width="200" height="110" rx="10" fill="#2b3038"/></svg>',
      '<svg width="240" height="200" viewBox="0 0 240 200"><rect x="20" y="30" width="120" height="150" rx="12" fill="none" stroke="#e0157f" stroke-width="12"/><path d="M40 70h80M40 100h80M40 130h50" stroke="#e0157f" stroke-width="10"/><circle cx="190" cy="90" r="30" fill="#111419"/><path d="M140 190c0-40 22-62 50-62s50 22 50 62z" fill="#111419"/></svg>',
      '<svg width="200" height="200" viewBox="0 0 200 200"><circle cx="100" cy="100" r="88" fill="#dfe2e6"/><path d="M100 100L100 12A88 88 0 0 1 121 14.5z" fill="#e0157f"/></svg>'];
    var TXT = [["Get the history in one place", "Orders, bills and past emails where the AI can see them."],
      ["Let the AI draft. A person sends.", "Then rate both kinds of reply, side by side."],
      ["Start small. Write the limits down.", "Upset customers and unusual questions go to a person."]];
    var cards = TXT.map(function (t, i) { return el("div", "rc", rb, '<div class="no">0' + (i + 1) + '</div><div class="ico">' + ICO[i] + "</div><h4>" + t[0] + "</h4><p>" + t[1] + "</p>"); });
    hide(rb);
    [[536.5, 540.5], [556.0, 559.9], [570.5, 574.2], [590.4, 592.4]].forEach(function (w) { full.to(rb, { opacity: 1, duration: 0.2 }, w[0]); full.to(rb, { opacity: 0, duration: 0.2 }, w[1] - 0.2);
      full.fromTo(rb, { scale: 0.97 }, { scale: 1.0, duration: w[1] - w[0], ease: "none", immediateRender: false }, w[0]); });
    // r2: card 01 lands on the 536.5 cut (the frame was empty for 2 s)
    [536.6, 556.05, 570.6].forEach(function (t, i) { var c = cards[i]; hide(c); full.fromTo(c, { opacity: 0, y: 80, rotation: 3 }, { opacity: 1, y: 0, rotation: 0, duration: 0.45, ease: "power3.out", immediateRender: false }, t); });
    full.to(cards[0], { opacity: 0.45, duration: 0.2 }, 556.0); full.to(cards[1], { opacity: 0.45, duration: 0.2 }, 570.5); full.to(cards[0], { opacity: 0.45, duration: 0.2 }, 570.5);
    full.to(cards, { opacity: 1, duration: 0.2 }, 590.4);
    full.to(cards, { x: function (i) { return [556, 0, -556][i]; }, rotation: function (i) { return [-4, 0, 4][i]; }, duration: 0.45, ease: "power3.inOut" }, 590.6);
    var st = el("div", "stampr", rb, "Customer email rulebook"); hide(st);
    full.fromTo(st, { opacity: 0, scale: 2.4, rotation: -14 }, { opacity: 1, scale: 1, rotation: -4, duration: 0.2, ease: "power4.in", immediateRender: false }, 591.1);
  })();
  bubble("uk", "sys0", "Orders", 546.0, 550.8, "light");
  bubble("uk", "sys1", "Bills", 547.1, 550.8, "light");
  bubble("uk", "sys2", "Emails", 548.5, 550.8, "light");
  bubble("uk", "desk", "One place", 543.8, 545.2, "mag");
  bubble("uk", "ai", "Guessing", 552.5, 555.9, "mag");
  plate("Rate both, side by side", 565.0, 567.1, "light");
  plate("Instead of hoping", 569.3, 570.4, "ul");
  figure("4%", "of its emails", 575.7, 576.0, 577.25, "dark");
  plate("A person answers", 589.7, 590.35, "light");
  // ================= CLOSE AND CTA
  bubble("hq", "trunk", "The software underneath", 597.0, 600.25, "light");
  bubble("hq", [3.4, 2.1, 3.0], "The people behind it", 597.9, 600.25, "light");
  (function () {
    var blk = el("div", "black", L); hide(blk); full.to(blk, { opacity: 1, duration: 1.0, ease: "sine.in" }, 603.1); full.to(blk, { opacity: 0, duration: 0.6 }, 604.2);
    dim(604.2, FULL, 0.74, 0.5);
    var nw = el("div", "", L, ""); nw.style.cssText = "position:absolute;inset:0";   // wrapper carries the move; the tile inside fades in
    var n = el("div", "nexttile", nw, '<div class="k">Next week</div><div class="img"><div class="env" style="left:60px;top:70px;transform:rotate(-8deg)"></div><div class="env" style="left:200px;top:40px;transform:rotate(5deg)"></div><div class="env" style="left:320px;top:90px;transform:rotate(-3deg)"></div></div><div class="t">The company that handed its customer service to AI</div>');
    show(n, 601.3, FULL, { blur: 12, din: 0.6, y: 40 });
    full.set(nw, { x: -540, y: 60, scale: 1.3, transformOrigin: "1510px 400px" }, 0);
    full.to(nw, { x: 0, y: 0, scale: 1, duration: 0.8, ease: "power2.inOut" }, 608.4);
    var e = el("div", "endcard", L, '<div class="brand">AGMM</div><div class="t">Book a free 30&#8209;minute call</div><div class="u">agmm.co.uk/ai-constraint-audit</div><div class="btn">Book your call</div><div class="lk">Link below</div>');
    hide(e); full.to(e, { opacity: 1, duration: 0.2 }, 608.6);
    [".brand", ".t", ".u", ".btn", ".lk"].forEach(function (sel, i) { var x = e.querySelector(sel); hide(x); full.fromTo(x, { opacity: 0, y: 30, filter: "blur(10px)" }, { opacity: 1, y: 0, filter: "blur(0px)", duration: 0.45, immediateRender: false }, [608.7, 614.7, 617.1, 617.7, 619.7][i]); });
    var b = e.querySelector(".btn"); for (var k = 0; k < 2; k++) full.to(b, { scale: 1.06, duration: 0.35, yoyo: true, repeat: 1, ease: "sine.inOut" }, 618.4 + k * 2.0);
    var fin = el("div", "black", L); hide(fin); full.to(fin, { opacity: 1, duration: 0.6, ease: "sine.in" }, FULL - 0.62);
  })();

  // ------------------------------------------------------------------ grain (seek-safe) + frame driver
  var grain = root.querySelector(".grain");
  function frame(Tfilm) {
    var T = toComp(Tfilm);
    full.totalTime(Math.min(T, FULL - 0.0001), true);
    var f = Math.floor(T * 30);
    grain.style.transform = "translate(" + (-Math.floor(hash(f, 3) * 40)) + "px," + (-Math.floor(hash(f, 9) * 40)) + "px)";
    if (window.__f07Render) window.__f07Render(T);
    window.__f07T = T;
  }
  var tl = gsap.timeline({ paused: true });
  tl.set({}, {}, SEG.len);
  tl.eventCallback("onUpdate", function () { frame(SEG.t0 + tl.time()); });
  window.__f07Frame = function () { frame(SEG.t0 + tl.time()); };
  window.__f07Seek = function (T) { frame(T); };
  frame(SEG.t0);
  window.__F07TL = tl;
  if (window.__timelines) window.__timelines["f07"] = tl;
  } catch (err) { window.__f07Err = String(err && err.stack || err); if (window.__dbgErr) window.__dbgErr(window.__f07Err); throw err; }
  }
  if (document.getElementById("root") && document.querySelector("#root .layer")) build();
  else document.addEventListener("DOMContentLoaded", build);
})();
