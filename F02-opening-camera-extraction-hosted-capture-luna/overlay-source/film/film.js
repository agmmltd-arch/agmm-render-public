/* F02 KLARNA, "The Work of 700 People", full film (651.6 s) on the locked voice (audio/words_full.json, film clock).
     SHOTS   shot list: scene, t0 (t1 = next t0), two camera keys (+ ease, dof, ss shadow size, split, trans, shake)
     state   pure functions of T read by the sets (core.js, sets_a/b/c.js)
     full    one paused GSAP timeline of every DOM overlay, driven to T each frame
   A render segment (window.F02_SEG = {t0, len}) plays T = t0 + local time.
   Dev only (ignored by the renderer): ?t=, ?scene=&cam=&st= (free camera), ?fit=1, window.__batch(list) snapshots. */
(function () {
  "use strict";
  var FULL = 651.6;
  var SEG = window.F02_SEG || { t0: 0, len: FULL };
  var clamp = function (v, a, b) { return Math.max(a, Math.min(b, v)); };
  var prog = function (t, a, d) { return clamp((t - a) / d, 0, 1); };
  var eo = function (p) { return 1 - Math.pow(1 - p, 3); };
  var eio = function (p) { return p < 0.5 ? 4 * p * p * p : 1 - Math.pow(-2 * p + 2, 3) / 2; };
  var inR = function (T, a, b) { return T >= a && T < b; };
  var hash = function (n, s) { var x = Math.sin(n * 127.1 + (s || 1) * 311.7) * 43758.5453; return x - Math.floor(x); };
  function C(p, l, fov, roll) { return { p: p, l: l, fov: fov || 40, roll: roll || 0 }; }

  // ---------------------------------------------------------------- places (see sets_*.js)
  var HX = -0.875, HZ = 25.8;                         // the hero desk on the support floor
  var H = function (dx, dy, dz) { return [HX + dx, dy, HZ + dz]; };
  var BX = [-8.8, -4.38, 0.04, 4.46, 8.88], BY = 5.55; // scoreboard slot centres
  var BS = function (i, dist, dy, dx, fov) { return C([BX[i] + (dx || 0), BY + (dy || 0), dist], [BX[i], BY - 0.1, 0], fov || 38); };
  var PHN = [0.38, 0.84, 0.38];
  var OSA = C([0.52, 1.6, -0.62], PHN, 40), OSB = C([0.47, 1.52, -0.5], PHN, 40), PCA = C([0.43, 1.24, 0.0], PHN, 30), PCB = C([0.41, 1.18, 0.08], PHN, 30);
  var DOF = [0.3, 0.24, 7], DOFS = [0.26, 0.2, 5], TILT = [0.34, 0.28, 5];

  // ---------------------------------------------------------------- the shot list: [t0, scene, camA, camB, opts]
  var L = [
    // ======== COLD OPEN
    [0.0, "release", C([0.25, 1.72, -0.39], [0.25, 0.90, -0.445], 9), C([0.25, 1.68, -0.39], [0.25, 0.90, -0.445], 9), { dof: DOFS, id: "S01" }],
    [2.4, "release", C([0.55, 1.62, 0.10], [0.25, 0.90, -0.36], 22), C([0.52, 1.58, 0.03], [0.25, 0.90, -0.36], 22), { ss: 3, id: "S02" }],
    [5.3, "release", C([0.25, 1.70, -0.39], [0.25, 0.90, -0.44], 9), C([0.25, 1.66, -0.39], [0.25, 0.90, -0.44], 9), { id: "S03" }],
    [7.8, "release", C([0.25, 1.70, -0.39], [0.25, 0.90, -0.44], 9), C([0.25, 1.68, -0.39], [0.25, 0.90, -0.44], 9), { ease: "io", id: "S04" }],
    [10.3, "release", C([0.25, 1.72, -0.26], [0.25, 0.90, -0.31], 9), C([0.25, 1.70, -0.26], [0.25, 0.90, -0.31], 9), { id: "S05" }],
    // Hold the same source-page close-up through the complete spoken 700 phrase.
    [12.34, "release", C([0.25, 1.72, -0.26], [0.25, 0.90, -0.31], 9), C([0.25, 1.72, -0.26], [0.25, 0.90, -0.31], 9), { id: "S06" }],
    [13.2666666667, "floor", C([0, 58, 44], [0, 0, 2], 42), C([0, 52, 36], [0, 0, 0], 42), { ss: 40, id: "S07" }],
    [16.2, "floor", C([-14, 11, 38], [0, 1, 10], 40), C([-24, 19, 52], [0, 1, 6], 40), { ss: 40 }],
    [18.2, "black", null, null, { id: "LOGO" }],
    [19.3, "floor", C([12, 7, 42], [-1, 1, 24], 40), C([8, 5.5, 38], [-1, 1, 25], 40), { ss: 14 }],
    [22.9, "floor", C([1.2, 1.75, 29.2], [-0.8, 1.15, 25.9], 40), C([0.8, 1.62, 28.4], [-0.8, 1.2, 25.9], 40), { ss: 6, dof: DOF }],
    [26.3, "floor", C([-0.4, 1.62, 27.2], [-0.78, 1.52, 26.35], 30), C([-0.5, 1.6, 26.95], [-0.78, 1.52, 26.35], 30), { ss: 4, dof: DOFS }],
    [29.6, "globe", C([0, 6, 36], [0, 1, 0], 38), C([2, 5, 31], [0, 1, 0], 38), {}],
    [33.3, "home", OSA, OSB, { ss: 3 }],
    [36.4, "black", null, null, { id: "DOC-OPENAI" }],
    [40.5, "uk", C([0.75, 1.42, 0.85], [0.0, 1.12, -0.2], 36), C([0.5, 1.36, 0.6], [0.0, 1.13, -0.2], 36), { ss: 3, dof: DOFS }],
    [43.4, "floor", C([22, 16, 40], [0, 2, 16], 40), C([16, 13, 36], [-1, 2, 18], 40), { ss: 30 }],
    [46.2, "floor", C([4, 3.2, 31], [-1, 1, 25], 40), C([3, 2.8, 30], [-1, 1, 25], 40), { ss: 12 }],
    [48.9, "black", null, null, { id: "TITLE" }],
    // ======== PART ONE: THE SCOREBOARD
    [52.2, "home", C([2.4, 1.3, 2.8], [0.1, 0.9, -0.2], 40), C([2.0, 1.25, 2.4], [0.1, 0.9, -0.2], 40), { ss: 4 }],
    [55.4, "home", PCA, PCB, { ss: 2, dof: DOFS }],
    [58.0, "home", C([1.6, 1.1, 2.6], [0.1, 1.4, -0.1], 44), C([1.9, 1.3, 2.4], [0.1, 1.8, -0.2], 44), { ss: 4 }],
    [61.6, "home", C([0.9, 2.1, 1.4], [0.2, 2.2, -0.2], 38), C([0.7, 2.4, 1.2], [0.2, 2.6, -0.3], 38), { ss: 4 }],
    [64.8, "globe", C([-6, 9, 26], [0, 2, 0], 36), C([0, 7, 25], [0, 2, 0], 36), {}],
    [68.4, "globe", C([4, 4, 22], [0, 3, 0], 36), C([2, 5, 20], [0, 3, 0], 36), {}],
    [71.6, "globe", C([0, 3, 30], [0, 2, 0], 38), C([0, 3, 27], [0, 2, 0], 38), {}],
    [75.3, "board", C([-3, 4.2, 22], [0, 5.2, 0], 42), C([2, 4.6, 18], [0, 5.3, 0], 42), {}],
    [79.7, "board", BS(0, 9, -0.6, -2.2, 40), BS(0, 7.5, -0.4, -1.4, 40), {}],
    [82.5, "board", BS(0, 4.6, 0, 0.8, 34), BS(0, 4.0, 0, 0.3, 34), {}],
    [85.3, "board", BS(1, 7, -0.7, 2, 40), BS(1, 5.6, -0.5, 1.2, 40), {}],
    [89.3, "board", BS(1, 4.0, 0.1, -0.6, 34), BS(1, 3.6, 0.1, -0.2, 34), {}],
    [90.8, "floor", C([0, 30, 48], [0, 0, 6], 42), C([0, 27, 44], [0, 0, 6], 42), { ss: 40, trans: { type: "dissolve", d: 0.25 } }],
    [92.2, "board", BS(1, 5.2, -0.2, 0.3, 36), BS(1, 5.6, -0.2, 0.6, 36), { trans: { type: "dissolve", d: 0.25 } }],
    [93.2, "board", C([-2, 4.8, 14], [-3, 5.3, 0], 42), C([2, 5, 12], [0.5, 5.3, 0], 42), {}],
    [96.0, "board", BS(2, 4.2, 0.05, 0.9, 34), BS(2, 3.8, 0.05, 0.4, 34), {}],
    [99.9, "sort", C([-3.6, 2.4, 3.2], [1.6, 1.3, 0], 42), C([-2.0, 2.1, 2.9], [2.2, 1.3, 0], 42), { ss: 6 }],
    [103.2, "board", C([6, 3.6, 13], [2, 5.4, 0], 42), C([8, 4.2, 11], [3.8, 5.4, 0], 42), {}],
    [105.8, "board", BS(3, 4.4, 0.1, -0.9, 34), BS(3, 3.9, 0.05, -0.4, 34), {}],
    [110.7, "black", null, null, { id: "Q-BETTER" }],
    [116.2, "home", PCA, PCB, { ss: 2, dof: DOFS }],
    [119.4, "board", C([0, 5.3, 20], [0, 5.3, 0], 42), C([0, 5.35, 16.5], [0, 5.35, 0], 42), {}],
    [124.0, "board", C([2, 5.2, 14], [2, 5.3, 0], 42), C([7.5, 5.4, 9], [8.3, 5.4, 0], 40), { ease: "io" }],
    [128.3, "board", BS(4, 3.4, 0, 0, 30), BS(4, 2.6, 0, 0, 30), {}],
    [131.7, "floor", C([-16, 9, 40], [0, 1, 14], 40), C([-12, 8, 36], [0, 1, 14], 40), { ss: 30 }],
    [134.4, "floor", C([0, 38, 42], [0, 0, 0], 42), C([0, 34, 38], [0, 0, 0], 42), { ss: 40 }],
    [138.9, "black", null, null, { id: "FACT-2022" }],
    [142.3, "floor", null, null, { split: [{ scene: "floor", cam: [C([-14, 13, 40], [0, 1, 10], 44), C([-12, 12, 37], [0, 1, 10], 44)], st: "grey" },
                                           { scene: "floor", as: "floor2", cam: [C([14, 13, 40], [0, 1, 10], 44), C([12, 12, 37], [0, 1, 10], 44)] }] }],
    [146.0, "black", null, null, { id: "700x2" }],
    [148.6, "floor", C([0, 22, 48], [0, 0, 8], 40), C([0, 40, 60], [0, 0, 4], 40), { ss: 40 }],
    [152.2, "floor", C([-26, 26, 30], [0, 0, 0], 42), C([-30, 34, 40], [0, 0, 0], 42), { ss: 40 }],
    // ======== PART TWO: HAPPENING NOW
    [155.9, "studio", C([-8, 3.4, 11], [-8, 1.4, -1], 40), C([-8, 2.9, 9.4], [-8, 1.3, -1], 40), {}],
    [159.9, "studio", C([-5.6, 1.5, 3.6], [-8.4, 1.05, 0], 36), C([-5.9, 1.45, 3.2], [-8.4, 1.05, 0], 36), { dof: DOF }],
    [162.9, "studio", C([-4.2, 2.1, 4.4], [-8.2, 1.0, 0], 38), C([-4.6, 2.0, 4.0], [-8.2, 1.0, 0], 38), {}],
    [166.0, "black", null, null, { id: "Q-NOW" }],
    [171.0, "scales", C([0, 2.6, 8.5], [0, 1.7, 0], 40), C([0, 2.4, 7.4], [0, 1.7, 0], 40), {}],
    [174.4, "scales", C([2.8, 2.3, 4.6], [1.6, 1.4, 0], 38), C([2.5, 2.2, 4.1], [1.6, 1.4, 0], 38), { dof: DOF }],
    [178.0, "scales", C([0, 2.2, 6.4], [0, 1.5, 0], 38), C([0, 2.1, 6.0], [0, 1.5, 0], 38), {}],
    [181.4, "scales", C([3.4, 2.5, 5.6], [0.8, 1.5, 0], 44), C([3.0, 2.35, 5.0], [0.8, 1.5, 0], 42), { dof: DOF }],
    [184.6, "scales", C([-0.4, 2.2, 5.0], [-1.3, 1.5, 0], 36), C([-1.3, 1.9, 2.9], [-1.6, 1.45, 0], 34), { ease: "io" }],
    [187.9, "scales", C([-1.3, 1.9, 2.9], [-1.6, 1.45, 0], 34), C([-1.5, 1.85, 2.4], [-1.6, 1.45, 0], 34), { dof: DOF }],
    [190.5, "sort", C([-8, 3.2, 5], [-2, 1.1, 0], 42), C([-6.5, 3.0, 4.6], [-1, 1.1, 0], 42), { ss: 8 }],
    [194.0, "sort", C([7.4, 3.8, 5.2], [3.6, 0.8, 0], 42), C([6.6, 3.5, 4.8], [3.6, 0.8, 0], 42), { ss: 6 }],
    [197.6, "sort", C([9.5, 3.4, -4.2], [4.8, 1.5, -0.6], 44), C([9.3, 3.6, -2.6], [4.8, 2.0, -0.8], 44), { ss: 7 }],
    [200.6, "sort", C([5.8, 2.4, 4.4], [4.0, 0.6, 1.3], 36), C([5.4, 2.2, 3.9], [4.0, 0.6, 1.3], 36), { ss: 4, dof: DOF }],
    // ======== MID-ROLL
    [204.3, "globe", null, null, { split: [{ scene: "globe", cam: [C([0, 3, 30], [0, 2, 0], 40), C([0, 3, 28], [0, 2, 0], 40)] },
                                            { scene: "uk", cam: [C([4.6, 2.6, 5.2], [0, 0.9, -0.6], 46), C([4.1, 2.4, 4.8], [0, 0.9, -0.6], 46)] }] }],
    [207.8, "uk", C([0.55, 1.35, 0.55], [0, 1.14, -0.2], 34), C([0.45, 1.3, 0.45], [0, 1.14, -0.2], 34), { ss: 3, dof: DOFS }],
    [211.4, "uk", C([-4.5, 2.6, 4.5], [-2.05, 1.0, 0.4], 42), C([-4.0, 2.35, 4.0], [-2.05, 1.0, 0.4], 42), { ss: 5 }],
    [214.6, "uk", C([2.75, 1.25, 0.85], [2.35, 0.9, 0.02], 34), C([2.65, 1.2, 0.72], [2.35, 0.9, 0.02], 34), { ss: 3, dof: DOFS }],
    [216.6, "uk", C([2.2, 2.0, 2.8], [0.5, 0.95, 0.1], 40), C([1.9, 2.1, 2.5], [0.5, 1.2, 0.1], 40), { ss: 4 }],
    [220.9, "uk", C([4.4, 2.4, 4.6], [-0.4, 1.0, -0.6], 44), C([3.4, 2.2, 4.2], [-0.4, 1.0, -0.6], 44), { ss: 6 }],
    [225.5, "uk", C([-4.5, 2.3, 3.8], [0.5, 1.0, -0.8], 44), C([-3.6, 2.1, 3.6], [0.5, 1.0, -0.8], 44), { ss: 6 }],
    [230.6, "black", null, null, { id: "CAREFULLY" }],
    [234.0, "globe", C([0, 4, 32], [0, 2, 0], 38), C([0, 7, 20], [0, 5, 0], 30), { ease: "io" }],
    // ======== PART THREE: THE MACHINE KEEPS WORKING
    [237.2, "studio", C([13, 3.6, 8], [8, 1.2, -0.5], 46), C([12.2, 3.25, 7.2], [8, 1.2, -0.5], 44), {}],
    [241.0, "studio", C([8.95, 1.52, 1.35], [8.5, 1.35, 0.35], 32), C([8.85, 1.5, 1.2], [8.5, 1.35, 0.35], 32), { dof: DOFS }],
    [244.3, "floor", C([-20, 14, 44], [0, 1, 14], 40), C([-14, 12, 40], [0, 1, 14], 40), { ss: 30 }],
    [249.8, "floor", C([0, 26, -32], [0, 0, -18], 42), C([0, 30, -26], [0, 0, -16], 42), { ss: 40 }],
    [253.6, "sort", C([8.6, 3.6, 6.2], [4.6, 1.2, 0.6], 42), C([7.8, 3.3, 5.6], [4.6, 1.2, 0.6], 42), { ss: 6 }],
    [257.4, "sort", C([6.2, 2.8, 3.8], [4.0, 0.9, 1.3], 36), C([5.8, 2.6, 3.4], [4.0, 0.9, 1.3], 36), { ss: 4, dof: DOF }],
    [261.0, "sort", C([9.6, 2.6, 2.4], [5.2, 1.6, 0.3], 40), C([9.2, 2.4, 1.6], [5.2, 1.6, 0.2], 40), { ss: 5 }],
    [264.8, "board", C([-1, 5, 15], [-1.5, 5.3, 0], 42), C([-3, 5.2, 12], [-3.5, 5.3, 0], 42), {}],
    [268.0, "board", C([4, 4.4, 13], [6, 5.3, 0], 42), C([6, 4.7, 10], [8, 5.4, 0], 40), {}],
    [273.0, "board", BS(4, 4.6, -0.3, -0.8, 34), BS(4, 3.9, -0.3, -0.3, 34), {}],
    [276.4, "black", null, null, { id: "TURN" }],
    // ======== PART FOUR: THE TURN
    [278.4, "black", null, null, { id: "PHOTO-A" }],
    [291.3, "floor", C([0.2, 1.5, 27.0], [-0.95, 0.8, 25.85], 32), C([0.05, 1.45, 26.8], [-0.95, 0.8, 25.85], 32), { ss: 3, dof: DOFS }],
    [293.0, "black", null, null, { id: "Q-FUTURE" }],
    [298.6, "floor", C([-2.2, 1.3, 26.9], [-0.9, 0.85, 25.85], 34), C([-2.0, 1.28, 26.7], [-0.9, 0.85, 25.85], 34), { ss: 3, dof: DOF }],
    [301.9, "home", C([1.9, 1.05, 2.1], [0.1, 0.95, -0.1], 38), C([1.7, 1.02, 1.9], [0.1, 0.92, -0.1], 38), { ss: 3 }],
    [305.4, "floor", C([6, 4.5, 34], [-1, 1, 24], 40), C([4.5, 4, 32], [-1, 1, 24], 40), { ss: 14 }],
    [308.3, "black", null, null, { id: "HEAD-FORBES" }],
    [313.8, "black", null, null, { id: "PHOTO-B" }],
    [322.5, "floor", C([22, 3.2, 12], [27, 1.6, 1], 44), C([20.5, 3.0, 11], [27, 1.5, 1], 44), { ss: 10 }],
    [326.0, "floor", C([8, 6, 30], [10, 0.8, 18], 42), C([6.5, 5.5, 28.5], [10, 0.8, 18], 42), { ss: 12 }],
    [330.0, "black", null, null, { id: "CAL-10SEP" }],
    [332.4, "nyse", C([0, 1.4, 18], [3, 4, -10], 50), C([0, 1.6, 14], [5, 30, -30], 50), { ss: 40, ease: "io" }],
    [335.4, "nyse", C([-2, 2, 6], [14, 9, -19], 44), C([0, 2.2, -2], [14, 9, -19], 44), { ss: 30 }],
    // ======== PART FIVE: THE BELL
    [339.8, "nyse", C([-6, 0.8, 30], [4, 10, -20], 50), C([-4, 1.0, 24], [5, 11, -20], 50), { ss: 40 }],
    [343.4, "nyse", C([-92, 7, 12], [-80, 3, -6], 46), C([-89, 6.4, 10], [-80, 3, -6], 46), { ss: 20 }],
    [346.9, "nyse", C([-84, 8.6, -4.5], [-80, 9.1, -11.8], 40), C([-79.5, 7.6, -5.2], [-78.2, 6.8, -10.8], 40), { ss: 10, ease: "io" }],
    [350.2, "black", null, null, { id: "HEAD-AJ" }],
    [353.6, "nyse", C([-76.4, 6.6, -8.4], [-77.6, 6.2, -10.6], 36), C([-76.8, 6.5, -8.9], [-77.6, 6.2, -10.6], 36), { ss: 5, dof: DOF }],
    [357.0, "nyse", C([-66, 8, 12], [-80, 2, -4], 46), C([-70, 7, 10], [-80, 2, -4], 46), { ss: 20 }],
    [360.4, "nyse", C([-2, 1.5, -4], [16, 9, -19], 46), C([-6, 2.5, 12], [16, 9, -19], 46), { ss: 40 }],
    // ======== PART SIX: THE CHEAP OPTION
    [363.3, "floor", C([-22, 18, 44], [0, 0, 10], 42), C([-18, 16, 40], [0, 0, 10], 42), { ss: 40 }],
    [366.8, "floor", C([0, 44, 20], [0, 0, 0], 42), C([0, 42, 18], [0, 0, 0], 42), { ss: 40, id: "HEADCOUNT" }],
    [370.6, "floor", C([-24, 20, 30], [0, 0, 0], 42), C([-22, 19, 28], [0, 0, 0], 42), { ss: 40 }],
    [374.3, "floor", C([24, 20, 30], [0, 0, 0], 42), C([22, 19, 28], [0, 0, 0], 42), { ss: 40 }],
    [378.0, "floor", C([0, 44, 20], [0, 0, 0], 42), C([0, 40, 16], [0, 0, -1], 42), { ss: 40 }],
    [384.9, "outsource", C([22, 13, 26], [0, 4, 0], 40), C([18, 11, 23], [0, 4, 0], 40), { ss: 16 }],
    [388.9, "outsource", C([3, 5.2, 7.5], [-1, 3.8, -1], 40), C([1.6, 5.0, 6.6], [-1.5, 3.8, -1], 40), { ss: 8, dof: DOF }],
    [393.9, "black", null, null, { id: "Q-EYE" }],
    [398.6, "studio", C([12.5, 3.2, 6], [8, 1.2, -0.5], 40), C([11.8, 2.9, 5.2], [8, 1.2, -0.5], 40), {}],
    [400.6, "studio", C([7.2, 1.45, 1.55], [7.6, 1.35, 0.3], 32), C([7.3, 1.45, 1.4], [7.6, 1.35, 0.3], 32), { dof: DOFS }],
    [404.6, "black", null, null, { id: "Q-CHEAP" }],
    [412.4, "floor", C([-3, 30, 44], [0, 0, 8], 42), C([-2, 26, 40], [0, 0, 8], 42), { ss: 40 }],
    [417.3, "black", null, null, { id: "Q-HUMAN" }],
    [424.4, "board", C([0, 1.4, 17], [0, 5.3, 0], 46), C([-6, 1.6, 13], [-8.8, 5.5, 0], 42), { ease: "io" }],
    [427.4, "board", C([-7.2, 2.4, 6.2], [-8.8, 5.5, 0], 38), C([-7.6, 2.6, 5.4], [-8.8, 5.5, 0], 38), {}],
    [429.9, "board", C([-2.8, 2.4, 6.2], [-4.38, 5.5, 0], 38), C([-3.2, 2.6, 5.4], [-4.38, 5.5, 0], 38), {}],
    [433.6, "board", C([1.6, 2.4, 6.2], [0.04, 5.5, 0], 38), C([1.2, 2.6, 5.4], [0.04, 5.5, 0], 38), {}],
    [436.4, "board", C([6.0, 2.4, 6.2], [4.46, 4.9, 0], 38), C([5.6, 2.6, 5.4], [4.46, 4.9, 0], 38), {}],
    [439.8, "board", C([0, 1.8, 19], [0, 5.3, 0], 44), C([5, 2.6, 15], [6, 5.4, 0], 42), { ease: "io" }],
    [443.5, "board", C([9.6, 3.6, 4.4], [8.88, 5.5, 0], 34), C([9.2, 4.0, 3.6], [8.88, 5.5, 0], 34), {}],
    [447.0, "black", null, null, { id: "HEAD-RETRO" }],
    [451.4, "kitchen", C([0, 2.2, 7.5], [0, 1.6, 0], 40), C([0, 2.0, 6.4], [0, 1.6, 0], 40), { ss: 6 }],
    [455.0, "kitchen", C([1.6, 2.6, 2.6], [0, 2.4, 0.1], 36), C([1.3, 2.7, 2.2], [0, 2.6, 0.1], 36), { ss: 4 }],
    [458.0, "kitchen", C([0.5, 1.6, 1.6], [-0.5, 1.2, 6], 42), C([-0.5, 1.6, 1.4], [-1.5, 1.2, 6], 42), { ss: 6, dof: [0.5, 0.5, 8], ease: "io" }],
    [460.5, "scales", C([-0.6, 2.0, 3.6], [-1.6, 1.5, 0], 36), C([-0.9, 1.95, 3.1], [-1.6, 1.5, 0], 36), { dof: DOF }],
    [464.0, "scales", C([-3.2, 1.6, 2.2], [-1.6, 1.45, 0], 34), C([-2.9, 1.6, 1.9], [-1.6, 1.45, 0], 34), { dof: DOF }],
    [467.9, "board", BS(4, 4.2, 0, 0, 32), BS(4, 3.1, 0, 0, 32), {}],
    [472.4, "black", null, null, { id: "DOC-PAR" }],
    [477.5, "black", null, null, { id: "DOCS-FLIP" }],
    [481.8, "black", null, null, { id: "OCTOPUS" }],
    [485.0, "black", null, null, { id: "SPLIT-WORD" }],
    [489.2, "floor", C([2, 3, 32], [-1, 1, 24], 40), C([6, 9, 40], [-1, 1, 22], 40), { ss: 16 }],
    [494.4, "floor", C([-18, 10, 40], [0, 1, 18], 40), C([-14, 9, 37], [0, 1, 18], 40), { ss: 26 }],
    [498.4, "home", OSA, OSB, { ss: 2 }],
    [501.9, "home", PCA, PCB, { ss: 2, dof: DOFS }],
    [504.0, "floor", C([0.9, 1.7, 28.4], [-0.85, 1.35, 26.2], 34), C([0.6, 1.66, 28.0], [-0.85, 1.35, 26.2], 34), { ss: 5, dof: DOF }],
    // ======== PART SEVEN: WHAT THIS MEANS FOR YOUR BUSINESS
    [506.2, "uk", C([4.8, 2.6, 5.6], [-0.2, 0.9, -0.6], 46), C([4.2, 2.4, 5.0], [-0.2, 0.9, -0.6], 46), { ss: 7 }],
    [509.2, "uk", C([-4.6, 1.7, 3.2], [0.5, 1.1, -0.6], 42), C([-4.1, 1.6, 2.9], [0.5, 1.1, -0.6], 42), { ss: 7 }],
    [514.9, "black", null, null, { id: "PITCH" }],
    [519.0, "board", C([0, 4.2, 22], [0, 5.3, 0], 42), C([0, 4.8, 17], [0, 5.3, 0], 42), {}],
    [522.8, "uk", C([6.5, 3.6, -3.6], [0, 0.8, -12], 44), C([5.5, 3.3, -4.2], [0, 0.8, -12], 44), { ss: 10 }],
    [525.8, "floor", null, null, { split: [{ scene: "floor", cam: [C([3, 3.5, 33], [-1, 1, 24], 44), C([2.5, 3.2, 32], [-1, 1, 24], 44)] },
                                          { scene: "nyse", cam: [C([-2, 2, 6], [14, 9, -19], 44), C([-1, 2, 3], [14, 9, -19], 44)] }] }],
    [530.8, "uk", C([-6.5, 3.4, -3.8], [0, 0.8, -12], 44), C([-5.6, 3.1, -4.4], [0, 0.8, -12], 44), { ss: 10 }],
    [534.6, "home", PCA, PCB, { ss: 2, dof: DOFS }],
    [536.6, "uk", C([0.5, 1.33, 0.5], [0, 1.14, -0.2], 34), C([0.42, 1.3, 0.42], [0, 1.14, -0.2], 34), { ss: 3, dof: DOFS }],
    [538.6, "uk", C([1.8, 1.5, -6.5], [0.9, 0.8, -8.4], 40), C([1.6, 1.45, -6.8], [0.9, 0.8, -8.4], 40), { ss: 5, dof: DOF }],
    [541.4, "black", null, null, { id: "HEAD-VICE" }],
    [549.9, "uk", C([4.8, 2.6, 5.6], [-0.2, 0.9, -0.6], 46), C([4.3, 2.45, 5.1], [-0.2, 0.9, -0.6], 46), { ss: 7, id: "LESSON" }],
    [552.8, "floor", C([0, 40, 30], [0, 0, 4], 42), C([0, 36, 27], [0, 0, 4], 42), { ss: 40 }],
    [555.5, "uk", C([0.55, 1.35, 0.55], [0, 1.14, -0.2], 34), C([0.45, 1.3, 0.45], [0, 1.14, -0.2], 34), { ss: 3 }],
    [558.9, "uk", C([-1.95, 1.5, 1.25], [-2.05, 0.77, 0.4], 36), C([-2.0, 1.42, 1.1], [-2.05, 0.77, 0.4], 36), { ss: 3 }],
    [562.3, "uk", C([2.75, 1.25, 0.85], [2.35, 0.9, 0.02], 34), C([2.65, 1.2, 0.72], [2.35, 0.9, 0.02], 34), { ss: 3 }],
    [564.9, "uk", C([0.5, 1.33, 0.5], [0, 1.14, -0.2], 34), C([0.42, 1.3, 0.42], [0, 1.14, -0.2], 34), { ss: 3 }],
    [567.3, "corridor", C([0, 1.4, 4], [0, 0.6, -4], 44), C([0, 1.3, 3], [0, 0.6, -4], 44), {}],
    [570.2, "corridor", C([1.5, 0.8, -1.5], [0, 0.5, -4.2], 42), C([1.3, 0.85, -1.9], [0, 0.6, -4.2], 42), {}],
    [574.4, "black", null, null, { id: "TWO-SLOTS" }],
    [579.1, "sort", C([-1.5, 4.2, 8], [3, 0.8, 0], 45), C([-0.8, 3.9, 7.2], [3, 0.8, 0], 45), { ss: 7 }],
    [583.9, "floor", C([0.9, 1.7, 28.4], [-0.85, 1.35, 26.2], 34), C([0.7, 1.68, 28.1], [-0.85, 1.35, 26.2], 34), { ss: 5, dof: DOF }],
    [588.4, "home", PCA, PCB, { ss: 2, dof: DOFS }],
    [591.0, "black", null, null, { id: "HUMANS" }],
    [593.6, "floor", C([5, 4, 33], [-1, 1, 24], 40), C([4, 3.6, 32], [-1, 1, 24], 40), { ss: 14 }],
    [599.5, "floor", C([-3, 30, 44], [0, 0, 8], 42), C([-2, 27, 40], [0, 0, 8], 42), { ss: 40, id: "LESSON3" }],
    [603.2, "board", C([0, 1.6, 17], [0, 5.3, 0], 44), C([2, 1.8, 15], [1, 5.3, 0], 44), {}],
    [607.0, "uk", C([6.5, 3.6, -3.6], [0, 0.8, -12], 44), C([5.8, 3.4, -4.0], [0, 0.8, -12], 44), { ss: 10 }],
    [610.6, "floor", C([5, 4, 33], [-1, 1, 24], 40), C([4.2, 3.7, 32], [-1, 1, 24], 40), { ss: 14 }],
    [613.0, "board", BS(3, 4.4, 0.1, 0, 34), BS(3, 3.9, 0.05, 0, 34), {}],
    [615.4, "board", C([0, 5.3, 19], [0, 5.3, 0], 42), C([0, 5.3, 21], [0, 5.3, 0], 42), {}],
    [619.6, "board", C([0, 5.3, 21], [0, 5.3, 0], 42), C([0, 5.3, 26], [0, 5.3, 0], 42), {}],
    [623.9, "black", null, null, { id: "END-BLACK" }],
    [625.4, "black", null, null, { id: "NEXT" }],
    [632.9, "floor", C([1.4, 2.0, 29.2], [-0.85, 1.3, 26.0], 36), C([1.0, 1.9, 28.6], [-0.85, 1.3, 26.0], 36), { ss: 6, id: "END" }],
    [638.3, "floor", C([6, 5, 36], [-1, 1, 22], 40), C([4.5, 4.4, 34], [-1, 1, 22], 40), { ss: 16 }],
    [643.6, "floor", C([-1.8, 1.7, 28.6], [-0.85, 1.3, 26.0], 36), C([-1.5, 1.65, 28.2], [-0.85, 1.3, 26.0], 36), { ss: 6 }],
  ];
  var SHOTS = L.map(function (r, i) {
    var o = r[4] || {}; var s = { id: o.id || ("S" + (i + 1)), scene: r[1], t0: r[0], t1: i + 1 < L.length ? L[i + 1][0] : FULL, cam: r[2] ? [r[2], r[3] || r[2]] : [C([0, 0, 1], [0, 0, 0])] };
    for (var k in o) if (k !== "id") s[k] = o[k];
    if (o.split) { s.scene = o.split[0].scene; s.split = o.split.map(function (h) { return { scene: h.scene, cam: h.cam, as: h.as }; }); }
    return s;
  });
  // the split shot's right half renders the same floor in its 2024 look: a second state entry keyed by "floor2"
  var qs = new URLSearchParams(location.search);
  var DEV = null;
  if (qs.get("scene")) { var c0 = (qs.get("cam") || "0,30,60,0,0,0,40").split(",").map(Number); DEV = { id: "DEV", scene: qs.get("scene"), t0: 0, t1: FULL, cam: [C(c0.slice(0, 3), c0.slice(3, 6), c0[6] || 40)], ss: Number(qs.get("ss") || 0) || undefined }; }
  if (qs.get("fit")) document.addEventListener("DOMContentLoaded", function () { var r = document.getElementById("root"); var k = Math.min(innerWidth / 1920, innerHeight / 1080); r.style.transform = "scale(" + k + ")"; r.style.transformOrigin = "0 0"; });
  var cur = 0;
  var DEVL = window.F02_DEV || null;
  function devAt(T) { var k = Math.max(0, Math.min(DEVL.length - 1, Math.floor(T))); var d = DEVL[k]; var c = d.cam;
    ST = d.st || null; d._shot = d._shot || { id: "DEV" + k, scene: d.scene, t0: k, t1: k + 1, cam: [C(c.slice(0, 3), c.slice(3, 6), c[6] || 40), C((d.cam2 || c).slice(0, 3), (d.cam2 || c).slice(3, 6), (d.cam2 || c)[6] || 40)], ss: d.ss, dof: d.dof }; return d._shot; }
  function shotAt(T) {
    if (DEVL) return devAt(T);
    if (DEV) return DEV;
    if (SHOTS[cur] && T >= SHOTS[cur].t0 && T < SHOTS[cur].t1) return SHOTS[cur];
    for (var i = 0; i < SHOTS.length; i++) if (T >= SHOTS[i].t0 && T < SHOTS[i].t1) { cur = i; return SHOTS[i]; }
    return SHOTS[SHOTS.length - 1];
  }
  function prevShot(s) { var i = SHOTS.indexOf(s); return i > 0 ? SHOTS[i - 1] : null; }

  // ---------------------------------------------------------------- STATE (pure functions of T)
  var ST = null; try { if (qs.get("st")) ST = JSON.parse(qs.get("st")); } catch (e) {}
  function ov(name, fn) { return function (T) { if (DEVL) { var d = DEVL[Math.max(0, Math.min(DEVL.length - 1, Math.floor(T)))]; if (d.st && d.st[name]) return d.st[name]; return fn(d.t !== undefined ? d.t : T); } return ST && ST[name] ? ST[name] : fn(T); }; }
  var r2 = function (v) { return Math.round(v * 100) / 100; };

  function release(T) {
    if (T < 2.4) return { out: 1 };
    if (T < 5.3) return { out: r2(eio(prog(T, 2.5, 2.6))) };
    return { out: 1 };
  }
  // the support floor (the recurring set)
  var ROWS = 25;
  function floor(T) {
    var s = { rise: 1, people: 1, gs: 0, emptyRows: 0, extra: 0, pods: 0, lit: 0, bubble: 0, screens: "idle", hero: {} };
    if (T < 19.3) {                                                     // cold open: rows rise, people vanish, one bubble
      s.rise = r2(prog(T, 13.2666666667, 2.4)); s.people = r2(1 - prog(T, 15.2, 0.8)); s.bubble = r2(prog(T, 15.4, 0.6)); s.screens = T > 15.6 ? "chat" : "idle";
      s.hero = { lamp: 0, screen: 0 }; return s;
    }
    if (T < 29.6) {                                                     // 15 months later: one desk relights, someone sits down
      s.people = 0; s.bubble = r2(1 - prog(T, 19.4, 0.6)); s.screens = "off";
      s.hero = { lamp: r2(prog(T, 21.5, 0.5)), screen: T > 21.6 ? 1 : 0, arrive: T < 21.0 ? -1 : r2(prog(T, 21.0, 4.6)) };
      return s;
    }
    if (T < 46.2) { s.bubble = 1; s.screens = "chat"; s.people = 0; s.hero = {}; return s; }        // Klarna was the proof
    if (T < 48.9) { s.people = 1; s.emptyRows = ROWS; s.lit = T > 46.5 ? (T > 47.2 ? 3 : 2) : 1; s.screens = "off"; s.hero = { lamp: 1, screen: 1, arrive: 1 }; return s; }
    if (T < 131.7) { s.screens = "chat"; s.bubble = 0.8; s.people = 0.0; s.hero = {}; return s; }    // the 700 flash (Part One)
    if (T < 157) {                                                      // 2022: grey desks empty row by row
      s.gs = 1; s.emptyRows = r2(prog(T, 136.2, 3.4) * ROWS); s.hero = {};
      if (T >= 148.6) { s.gs = 0; s.emptyRows = 0; s.people = 0; s.screens = "chat"; s.bubble = 0.8; }
      return s;
    }
    if (T < 291) {                                                      // 2025: machines at the desks, the 800
      s.people = 1; s.pods = 1; s.screens = "chat"; s.extra = r2(prog(T, 250.2, 2.6)); s.hero = {}; return s;
    }
    if (T < 305.4) { s.people = 0; s.screens = "off"; s.hero = { lamp: T > 298.6 ? 0.6 : 0, screen: 0 }; return s; }   // a headset on an empty desk
    if (T < 322.5) { s.people = 1; s.emptyRows = ROWS; s.screens = "off"; s.lit = Math.round(1 + prog(T, 305.6, 2.4) * 9); s.hero = { lamp: 1, screen: 1, arrive: 1 }; return s; }
    if (T < 363) { s.people = 1; s.emptyRows = ROWS; s.screens = "off"; s.lit = 10; s.walk = r2(prog(T, 322.7, 7.2)); s.hero = { lamp: 1, screen: 1, arrive: 1 }; return s; }
    if (T < 378) { s.people = 1; s.pods = 0.6; s.screens = "chat"; s.hero = {}; return s; }
    if (T < 384.9) { s.gs = r2(0.5 + 0.5 * Math.sin(T * 0.0)); s.people = 1; s.emptyRows = 13; s.screens = "off"; s.hero = {}; return s; }
    if (T < 489.2) { s.people = 1; s.pods = 1; s.screens = "chat"; s.hero = {}; return s; }
    if (T < 494.4) { s.people = 1; s.emptyRows = ROWS; s.lit = Math.round(12 + prog(T, 489.3, 4.5) * 50); s.screens = "off"; s.hero = { lamp: 1, screen: 1, arrive: 1 }; return s; }
    if (T < 504) { s.people = 1; s.pods = 0.5; s.screens = "chat"; s.hero = { lamp: 1, screen: 1, arrive: 1 }; return s; }
    if (T < 525.8 || T >= 530) { s.people = 1; s.emptyRows = ROWS; s.lit = 60; s.screens = "off"; s.hero = { lamp: 1, screen: 1, arrive: 1, typing: 1 }; return s; }
    s.people = 1; s.emptyRows = ROWS; s.lit = 60; s.hero = { lamp: 1, screen: 1, arrive: 1 }; return s;
  }
  function floor2(T) { var s = floor(T); if (inR(T, 142.3, 146)) { s.gs = 0; s.emptyRows = 0; s.people = 1; s.screens = "chat"; s.bubble = 0; } return s; }
  function globe(T) {
    if (T < 40) return { spin: r2(-0.2 + T * 0.012), lights: r2(0.15 + 0.85 * eo(prog(T, 29.7, 3.2))), pins: 0, tilt: 0.3 };
    if (T < 80) return { spin: r2(-0.3 + (T - 64) * 0.01), lights: 1, pins: r2(prog(T, 65.2, 6.2) * 23), tilt: 0.42 };
    return { spin: r2(-0.18 + (T - 204) * 0.004), lights: 1, pins: 23, tilt: 0.48 };
  }
  function home(T) {
    // the customer's phone: checkout (instalments), chat (the assistant), the human button, a call nobody answers
    if (T < 52) return { screen: { mode: "checkout", split: 1 }, lift: 1, bubbles: 0 };
    if (T < 58) return { screen: { mode: "checkout", split: r2(prog(T, 53.0, 2.2)), tap: T > 56.9 && T < 57.4 }, lift: 1, bubbles: 0 };
    if (T < 66) return { screen: { mode: "checkout", split: 1 }, lift: 1, bubbles: r2(prog(T, 58.2, 7.0)) };
    if (T < 125) {
      var n = T >= 116.2 ? 2 : 0;
      var lines = [">Can I move my payment date?"]; if (n >= 2) lines.push("Yes. Tap Manage, then Change date.");
      return { screen: { mode: "chat", lines: lines, typing: n === 1 }, lift: 1 };
    }
    if (T < 306) return { screen: { mode: "chat", lines: [">Can I move my payment date?", "Yes. Tap Manage, then Change date."] }, lift: 1, lower: r2(prog(T, 302.4, 1.6)) };
    if (T < 504) {
      var hb = T >= 501.9;
      return { screen: { mode: "chat", lines: [">My refund never arrived", "I can help with that.", ">It's been three weeks"], button: hb, human: T >= 502.15 }, lift: 1 };
    }
    if (T < 538) return { screen: { mode: "call", label: "Calling", sub: T > 535.6 ? "NO ANSWER" : "RINGING", hang: T > 535.8 }, lift: 1, lower: r2(prog(T, 535.9, 0.6)) };
    return { screen: { mode: "chat", lines: [">Something's wrong with my order", "I'm sorry to hear that."], button: T >= 588.4 }, lift: 1 };
  }
  // the scoreboard: keyframes per slot {t, to, lamp, sub}; each flip takes 0.55 s, no intermediate characters
  var boardFigureWindows = [];
  var B0 = [[75.25, "?", 0, "RESOLUTION TIME"], [82.6, "11 MIN", 0, "RESOLUTION TIME"], [84.2, "<2 MIN", 0, "WAS 11 MIN"], [84.7, null, 1],
            [425.3, "", 0, ""], [428.3, "11 MIN", 0, "RESOLUTION TIME"], [429.3, "<2 MIN", 0, "WAS 11 MIN"], [429.8, null, 1]];
  var B1 = [[75.25, "?", 0, "CHATS IN MONTH ONE"], [87.6, "2.3M", 0, "CHATS IN MONTH ONE"], [91.4, "700", 0, "FULL-TIME AGENTS' WORK"], [91.9, null, 1], [265.6, "800", 1, "AGENTS' WORK, MAY 2025"],
            [425.3, "", 0, ""], [431.1, "700", 0, "FULL-TIME AGENTS' WORK"], [432.8, "800", 0, "AGENTS' WORK, MAY 2025"], [433.2, null, 1]];
  var B2 = [[75.25, "?", 0, "REPEAT QUESTIONS DOWN"], [98.3, "-25%", 0, "REPEAT QUESTIONS DOWN"], [98.8, null, 1], [425.3, "", 0, ""], [434.9, "-25%", 0, "REPEAT QUESTIONS DOWN"], [435.3, null, 1]];
  var B3 = [[75.25, "?", 0, "EXPECTED PROFIT, 2024"], [108.2, "$40M", 0, "EXPECTED PROFIT, 2024"], [108.7, null, 1], [425.3, "", 0, ""], [436.7, "$40M", 0, "EXPECTED PROFIT, 2024"], [437.1, null, 1]];
  var B4 = [[125.6, "?", 0, "CLAIMED. NO NUMBER GIVEN"], [126.8, null, 0.35], [425.3, null, 0]];
  var BK = [B0, B1, B2, B3, B4], BON = [75.25, 75.45, 75.65, 75.85, 125.2];
  function slot(i, T) {
    var ks = BK[i], val = "", prev = "", tf = -99, lamp = 0, sub = "";
    for (var k = 0; k < ks.length; k++) { var e = ks[k]; if (T < e[0]) break;
      if (e[1] !== null) { prev = val; val = e[1]; tf = e[0]; }
      if (e[2] !== undefined) lamp = e[2]; if (e[3] !== undefined) sub = e[3]; }
    var p = tf < -90 ? 1 : r2(prog(T, tf, 0.55));
    if (val === "" ) p = 1;
    var q = { on: r2(eo(prog(T, BON[i], i === 4 ? 0.9 : 0.4))), from: prev, to: val, p: p, lamp: lamp, sub: sub };
    if (i === 4) {
      q.cross = r2(prog(T, 470.4, 0.35));
      if (inR(T, 271.4, 272.1) || inR(T, 275.2, 275.7)) { q.lamp = Math.floor(T * 14) % 2 ? 1 : 0.1; q.amber = true; }
    }
    if (i === 1 && T >= 265.6 && T < 425.3) { q.from = "700"; }
    return q;
  }
  function board(T) { return { headers: boardFigureWindows.some(function (w) { return T >= w[0] && T < w[1]; }) ? 0 : 1, slots: [0, 1, 2, 3, 4].map(function (i) { return slot(i, T); }) }; }
  function scales(T) {
    var drops = [], tilt = 0;
    if (T < 200) { drops = [{ side: 1, t: 178.2 }, { side: 0, t: 180.1 }, { side: 1, t: 182.5, stack: 1 }, { side: 1, t: 183.4, stack: 2 }];
      tilt = -0.25 * prog(T, 178.4, 0.4) + 0.12 * prog(T, 180.3, 0.4) - 0.2 * prog(T, 182.7, 0.4) - 0.15 * prog(T, 183.6, 0.4); }
    else { drops = [{ side: 1, t: 0 }, { side: 0, t: 0 }, { side: 1, t: 0, stack: 1 }, { side: 1, t: 0, stack: 2 }]; tilt = -0.48; }
    return { drops: drops, tilt: r2(-tilt) };
  }
  function sort(T) {
    if (T < 150) return { flow: 1, rate: 1.2, fillR: 0.5, fillH: 0.3 };
    if (T < 253) return { flow: 1, rate: 1.4, fillR: r2(0.2 + prog(T, 190.5, 8) * 0.8), fillH: r2(0.1 + prog(T, 190.5, 10) * 0.3), lift: r2(prog(T, 197.8, 2.8)), binGone: T > 200.6 };
    if (T < 300) return { flow: 1, rate: 1.4, fillR: 0.3, fillH: 0.6, reach: r2(prog(T, 255.2, 7.2)) };
    return { flow: 1, rate: 1.2, fillR: 0.7, fillH: 0.5, lift: r2(prog(T, 580.6, 3.0)) };
  }
  function studio(T) { return { live: inR(T, 240, 246) || inR(T, 400.5, 405) ? 1 : -1 }; }
  function uk(T) {
    if (T < 60) return { inbox: { word: "CHATBOT?" }, missed: 0 };
    if (T < 230) return { inbox: { n: T < 208.4 ? 0 : T < 209.3 ? 1 : T < 210.2 ? 2 : 3 }, missed: T < 214.9 ? 0 : T < 215.3 ? 1 : T < 215.7 ? 2 : 3,
      formsTwice: T > 213.7, bin: { on: r2(prog(T, 216.8, 0.6)), lift: r2(prog(T, 219.6, 1.2)), fill: r2(prog(T, 217.2, 1.8)) } };
    if (T < 536) return { inbox: { n: 3 }, missed: 3, formsTwice: true, ring: inR(T, 509, 514) ? 1 : 0 };
    if (T >= 549 && T < 564.9) return { inbox: { n: 3 }, missed: 3, formsTwice: true, ring: 0 };
    return { inbox: { card: true, grey: T > 537.4 }, missed: 3, ring: 0 };
  }
  function nyse(T) { return { bell: T < 352 ? 348.3 : 354.0 }; }
  function outsource(T) { return { plain: r2(prog(T, 391.0, 2.6)) }; }
  function kitchen(T) { var rate = T < 455 ? 0.7 : 0.7 + prog(T, 455, 3) * 1.6; var secs = T < 455 ? 48 : 48 - prog(T, 455, 4.5) * 30; return { rate: r2(rate), secs: Math.round(secs) }; }
  function corridor(T) { return { roll: r2(eo(prog(T, 568.8, 3.4))), trip: r2(prog(T, 572.35, 0.2)) }; }

  var F = window.F02 = { shots: SHOTS, shotAt: shotAt, prevShot: prevShot, anchors: [], duration: FULL, state: {
    release: ov("release", release), floor: ov("floor", floor), floor2: ov("floor2", floor2), globe: ov("globe", globe), home: ov("home", home),
    board: ov("board", board), scales: ov("scales", scales), sort: ov("sort", sort), studio: ov("studio", studio), uk: ov("uk", uk), nyse: ov("nyse", nyse),
    outsource: ov("outsource", outsource), kitchen: ov("kitchen", kitchen), corridor: ov("corridor", corridor) } };

  // ---------------------------------------------------------------- DOM overlays on one paused timeline
  function build() {
  try {
  var root = document.getElementById("root");
  var LY = root.querySelector(".layer");
  var full = gsap.timeline({ paused: true });
  function hide(e) { e.style.opacity = "0"; }
  function el(tag, cls, parent, html) { var e = document.createElement(tag); if (cls) e.className = cls; if (html !== undefined) e.innerHTML = html; (parent || LY).appendChild(e); return e; }
  function show(e, a, b, o) {
    o = o || {}; hide(e);
    full.fromTo(e, { opacity: 0, filter: "blur(" + (o.blur === undefined ? 10 : o.blur) + "px)", y: o.y || 0, scale: o.s0 || 1 },
      { opacity: 1, filter: "blur(0px)", y: 0, scale: 1, duration: o.din || 0.45, ease: o.ein || "power2.out", immediateRender: false }, a);
    if (b !== undefined) full.to(e, { opacity: 0, filter: "blur(6px)", duration: o.dout || 0.3, ease: "power1.in" }, b - (o.dout || 0.3));
    return e;
  }
  function cut(e, a, b) { hide(e); full.set(e, { opacity: 1 }, a); if (b !== undefined) full.set(e, { opacity: 0 }, b); return e; }
  function dim(a, b, v, din) { var d = el("div", "dim"); hide(d); full.to(d, { opacity: v, duration: din || 0.2 }, a); full.to(d, { opacity: 0, duration: 0.2 }, b - 0.2); return d; }
  function flash(a) { var f = el("div", "flash"); hide(f); full.fromTo(f, { opacity: 0.85 }, { opacity: 0, duration: 0.22, ease: "power2.out", immediateRender: false }, a); }
  // a stamp types on, one character every 28 ms
  function stamp(text, a, b, src) {
    var s = el("div", "stamp" + (src ? " src" : ""), LY, '<div class="tab"></div><div class="tx"></div>'); var tx = s.querySelector(".tx");
    var chs = text.split("").map(function (c) { return el("span", "ch", tx, c === " " ? "&nbsp;" : c); });
    hide(s); full.set(s, { opacity: 1 }, a);
    if (a <= 0) chs.forEach(function (c) { full.set(c, { opacity: 1 }, 0); });
    else chs.forEach(function (c, i) { full.set(c, { opacity: 1 }, a + 0.05 + i * 0.028); });
    full.to(s, { opacity: 0, duration: 0.25 }, b - 0.25);
  }
  function plate(text, a, b, kind, top) {
    var p = el("div", "plate" + (kind ? " " + kind : ""), LY, '<div class="in">' + text + (kind === "ul" || kind === "red ul" ? '<div class="ul"></div>' : "") + "</div>");
    if (top) p.style.top = top + "px";
    hide(p);
    full.fromTo(p, { opacity: 0, y: 24 }, { opacity: 1, y: 0, duration: 0.26, ease: "power3.out", immediateRender: false }, a);
    var ul = p.querySelector(".ul"); if (ul) full.fromTo(ul, { scaleX: 0 }, { scaleX: 1, duration: 0.35, ease: "power2.out", immediateRender: false }, a + 0.2);
    full.to(p, { opacity: 0, y: -12, duration: 0.22, ease: "power2.in" }, b - 0.22);
    return p;
  }
  function l3(kick, name, role, a, b) {
    var l = el("div", "l3", LY, '<div class="bar"></div><div class="kick">' + kick + '</div><div class="name">' + name + '</div><div class="role">' + role + "</div>");
    show(l, a, b, { blur: 8, din: 0.4, y: 16 });
  }
  function slam(e, a) { hide(e); full.fromTo(e, { opacity: 0, scale: 1.25, filter: "blur(10px)" }, { opacity: 1, scale: 1, filter: "blur(0px)", duration: 0.18, ease: "power3.out", immediateRender: false }, a); }
  function fig(num, lab, a, aLab, b, pink, top, clearBoardHeaders) {
    if (clearBoardHeaders) boardFigureWindows.push([a - 0.04, b]);
    var f = el("div", "fig" + (pink ? " pink" : ""), LY, '<div class="num">' + num + '</div><div class="lab">' + lab + "</div>");
    if (top) f.style.top = top + "px";
    slam(f.querySelector(".num"), a); slam(f.querySelector(".lab"), aLab);
    full.to(f, { opacity: 0, filter: "blur(8px)", duration: 0.25 }, b - 0.25);
  }
  function chapter(n, t, a, b) {
    var c = el("div", "chap", LY, '<div class="n">' + n + '</div><div class="t"><div class="k">Part ' + ["one", "two", "three", "four", "five", "six", "seven"][Number(n) - 1] + '</div><div class="h">' + t + "</div></div>");
    hide(c); full.set(c, { opacity: 1 }, a);
    full.fromTo(c.querySelector(".n"), { opacity: 0, x: -40 }, { opacity: 1, x: 0, duration: 0.5, ease: "power3.out", immediateRender: false }, a);
    full.fromTo(c.querySelector(".t"), { opacity: 0, x: -20, filter: "blur(8px)" }, { opacity: 1, x: 0, filter: "blur(0px)", duration: 0.5, ease: "power2.out", immediateRender: false }, a + 0.15);
    full.to(c, { opacity: 0, duration: 0.3 }, b - 0.3);
  }
  function anchor(scene, p, html, a, b, kind) {
    var mm = /^(pink|red|blue):/.exec(html); if (mm) { kind = mm[1]; html = html.slice(mm[0].length); }
    var an = el("div", "anch"); var bub = el("div", "bub" + (kind ? " " + kind : ""), an, html);
    hide(bub);
    full.fromTo(bub, { opacity: 0, scale: 0.6 }, { opacity: 1, scale: 1, duration: 0.26, ease: "back.out(2)", immediateRender: false }, a);
    full.to(bub, { opacity: 0, duration: 0.2 }, b - 0.2);
    F.anchors.push({ scene: scene, p: p, el: an });
  }
  function question(text, a, b) { var q = el("div", "q", LY, "<span>" + text + "</span>"); show(q, a, b, { blur: 12, din: 0.5, y: 10 }); }
  // a quote whose words land with the voice: words = [[word, t], ...]; ul = words to underline in red
  function quote(words, who, src, a, b, ul) {
    var q = el("div", "quote", LY, '<div class="qt"></div><div class="qw">' + who + '</div><div class="qs">' + src + "</div>");
    var qt = q.querySelector(".qt");
    hide(q); full.set(q, { opacity: 1 }, a); full.to(q, { opacity: 0, duration: 0.3 }, b - 0.3);
    words.forEach(function (w, i) {
      var isU = ul && ul.indexOf(i) >= 0;
      var sp = el("span", "w" + (isU ? " u" : ""), qt, w[0] + (isU ? "<i></i>" : ""));
      qt.appendChild(document.createTextNode(" "));
      full.fromTo(sp, { opacity: 0, y: 8 }, { opacity: 1, y: 0, duration: 0.18, ease: "power2.out", immediateRender: false }, w[1]);
      if (isU) full.to(sp.querySelector("i"), { scaleX: 1, duration: 0.35, ease: "power2.out" }, w[1] + 0.25);
    });
    full.fromTo(q.querySelector(".qw"), { opacity: 0 }, { opacity: 1, duration: 0.4, immediateRender: false }, a + 0.2);
    full.fromTo(q.querySelector(".qs"), { opacity: 0 }, { opacity: 1, duration: 0.4, immediateRender: false }, a + 0.4);
    full.fromTo(qt, { scale: 0.985 }, { scale: 1.02, duration: b - a, ease: "none", immediateRender: false }, a);
    return q;
  }
  // words with film times, taken from the voice's own word timings
  function wq(text, t0, t1) { var ws = text.split(" "); return ws.map(function (w, i) { return [w, t0 + (t1 - t0) * i / ws.length]; }); }
  function head(outlet, date, htxt, note, a, b, mark) {
    var logos = { "Forbes": "img/forbes.svg", "Al Jazeera": "img/aljazeera.svg", "Vice": "img/vice.svg" };
    var masthead = logos[outlet] ? '<img src="' + logos[outlet] + '" alt="' + outlet + '">' : '<span>' + outlet + '</span>';
    var h = el("div", "head", LY, '<div class="o"><span class="masthead">' + masthead + '</span><span>' + date + '</span></div><div class="r"></div><div class="h">' + htxt + '</div>' + (note ? '<div class="n">' + note + "</div>" : ""));
    hide(h); full.set(h, { opacity: 1 }, a);
    full.fromTo(h, { y: 60, rotation: -1.2, scale: 0.94 }, { y: 0, rotation: -0.4, scale: 1.0, duration: 0.7, ease: "power3.out", immediateRender: false }, a);
    full.fromTo(h, { scale: 1.0 }, { scale: 1.05, duration: b - a - 0.7, ease: "none", immediateRender: false }, a + 0.7);
    full.fromTo(h.querySelector(".r"), { scaleX: 0 }, { scaleX: 1, duration: 0.5, ease: "power2.out", immediateRender: false }, a + 0.2);
    var m = h.querySelector(".m"); if (m && mark) full.fromTo(m, { backgroundSize: "0% 100%" }, { backgroundSize: "100% 100%", duration: 0.6, ease: "power2.out", immediateRender: false }, mark);
    full.to(h, { opacity: 0, duration: 0.25 }, b - 0.25);
    return h;
  }
  function solo(text, a, b, serif, typed) {
    var s = el("div", "solo" + (serif ? " serif" : ""), LY, "<span></span>"); var sp = s.querySelector("span");
    hide(s); full.set(s, { opacity: 1 }, a);
    if (typed) { text.split("").forEach(function (ch, i) { var c = el("b", "", sp, ch); c.style.fontWeight = "inherit"; hide(c); full.set(c, { opacity: 1 }, a + 0.05 + i * 0.06); }); }
    else { sp.textContent = text; full.fromTo(sp, { opacity: 0, scale: 1.1, filter: "blur(10px)" }, { opacity: 1, scale: 1, filter: "blur(0px)", duration: 0.4, immediateRender: false }, a); }
    full.fromTo(sp, { scale: 1 }, { scale: 1.06, duration: b - a, ease: "none", immediateRender: false }, a);
    full.to(s, { opacity: 0, duration: 0.25 }, b - 0.25);
    return s;
  }

  // ================================================================== COLD OPEN
  // Date and source type remain printed on the page; avoid duplicating them as overlays.
  (function () { // The floor's 700 appears only after the source-page phrase and the 13.2667s shot cut.
    var f = el("div", "fig", LY, '<div class="num">700</div><div class="lab">full-time agents’ work</div>'); f.style.top = "250px";
    slam(f.querySelector(".num"), 13.2666666667); var lab = f.querySelector(".lab"); hide(lab); full.set(lab, { opacity: 1, scale: 1.04, filter: "blur(0px)" }, 13.801); full.to(lab, { scale: 1, duration: 0.18, ease: "power3.out" }, 13.801); full.to(f, { opacity: 0, filter: "blur(8px)", duration: 0.3 }, 15.9);
  })();
  anchor("floor", "bubble", "pink:AI assistant", 15.9, 18.2);
  (function () { var w = el("div", "wordmark", LY, '<img src="img/klarna-badge.svg" alt=""><div class="cap">Klarna press material</div>'); cut(w, 18.2, 19.3);
    full.fromTo(w.querySelector("img"), { scale: 1.08 }, { scale: 1.0, duration: 0.35, ease: "power3.out", immediateRender: false }, 18.2);
    full.fromTo(w.querySelector("img"), { scale: 1.0 }, { scale: 1.04, duration: 0.75, ease: "none", immediateRender: false }, 18.55); })();
  (function () { // the months flick from FEB 2024 to MAY 2025
    var m = el("div", "months", LY, ""); var ms = ["FEB 2024", "MAY 2024", "AUG 2024", "NOV 2024", "FEB 2025", "MAY 2025"];
    hide(m); full.set(m, { opacity: 1 }, 19.35); full.to(m, { opacity: 0, duration: 0.25 }, 22.6);
    ms.forEach(function (t, i) { var sp = el("span", "", m, t); hide(sp); sp.style.position = "absolute"; sp.style.left = "50%"; sp.style.transform = "translateX(-50%)";
      full.set(sp, { opacity: 1 }, 19.4 + i * 0.22); if (i < ms.length - 1) full.set(sp, { opacity: 0 }, 19.4 + (i + 1) * 0.22);
      if (i === ms.length - 1) full.fromTo(sp, { scale: 1.2 }, { scale: 1, duration: 0.3, immediateRender: false }, 19.4 + i * 0.22); });
  })();
  plate("15 months later", 20.5, 22.8);
  question("Why bring the people back?", 27.4, 29.6);
  fig("150 million", "people use Klarna’s app", 31.38, 31.6, 33.25);
  (function () { // OpenAI customer story, using the published headline and reported figures
    var d = el("div", "doc evidence-doc openai-story", LY, '<div class="pg"><div class="src">openai.com/index/klarna/</div><div class="kick"><img class="openai-logo" src="img/openai-official.png" alt="OpenAI">CUSTOMER STORY</div>' +
      '<div class="hl"><span class="mark">Klarna’s AI assistant</span> does the work of 700 full-time agents</div>' +
      '<div class="evidence-row"><b>2.3m</b><span>conversations in month one</span><b>23</b><span>markets</span><b>35+</b><span>languages</span></div>' +
      '<div class="by">Reported result: resolution time fell from 11 minutes to under 2 minutes</div></div>');
    cut(d, 36.4, 40.5); var pg = d.querySelector(".pg");
    full.fromTo(pg, { x: 160, y: 70, scale: 1.0, rotation: -0.4 }, { x: 140, y: 45, scale: 1.025, rotation: -0.2, duration: 4.1, ease: "sine.inOut", immediateRender: false }, 36.4);
    full.fromTo(d.querySelector(".mark"), { backgroundColor: "rgba(255,179,199,0)" }, { backgroundColor: "rgba(255,179,199,1)", duration: 0.5, immediateRender: false }, 37.0);
  })();
  plate("Hand the phones to a chatbot?", 41.0, 43.35);
  plate("Klarna was the proof", 44.5, 46.15, "pink");
  plate("Then Klarna changed course", 46.6, 48.85, "red ul");
  (function () { // title
    var t = el("div", "title", LY, '<div class="k">Klarna · 2024 to 2026</div><div class="t">The work of <b>700</b> people</div>'); hide(t);
    full.set(t, { opacity: 1 }, 48.9);
    full.fromTo(t.querySelector(".t"), { letterSpacing: "0.12em", filter: "blur(14px)", opacity: 0 }, { letterSpacing: "-0.01em", filter: "blur(0px)", opacity: 1, duration: 1.0, ease: "power2.out", immediateRender: false }, 48.95);
    full.fromTo(t.querySelector(".k"), { opacity: 0 }, { opacity: 1, duration: 0.6, immediateRender: false }, 49.4);
    full.fromTo(t, { scale: 1 }, { scale: 1.05, duration: 3.3, ease: "none", immediateRender: false }, 48.9);
    full.to(t, { opacity: 0, filter: "blur(8px)", duration: 0.3 }, 51.9);
  })();
  // ================================================================== PART ONE
  chapter("1", "The scoreboard", 52.35, 55.2);
  stamp("Klarna, 2024", 55.5, 60.8);
  anchor("home", "phone", "blue:Pay later", 56.2, 57.9, "blue");
  plate("Every question: an errand", 62.4, 64.75, "pink");
  plate("Built with OpenAI · live one month", 65.2, 68.35);
  (function () { var c = el("div", "clock", LY, '<i></i><i class="m"></i><b></b><div class="lb">24 / 7</div>'); show(c, 68.6, 71.5, { blur: 6, din: 0.3 });
    full.fromTo(c.querySelector("i"), { rotation: 0 }, { rotation: 720, duration: 2.9, ease: "none", immediateRender: false }, 68.6);
    full.fromTo(c.querySelector(".m"), { rotation: 0 }, { rotation: 60, duration: 2.9, ease: "none", immediateRender: false }, 68.6); })();
  fig("23 markets", "around the clock", 71.47, 71.6, 73.4, false, 330);
  (function () { var l = el("div", "langs", LY, ""); var ls = ["English", "Svenska", "Deutsch", "Français", "Español", "Italiano", "Nederlands", "Polski", "Suomi", "Dansk", "Norsk", "Português"];
    hide(l); full.set(l, { opacity: 1 }, 72.7); full.set(l, { opacity: 0 }, 75.2);
    ls.forEach(function (t, i) { var s = el("span", "", l, t); s.style.top = ((i % 4) * 110) + "px"; s.style.left = ((Math.floor(i / 4) * 360) + (i % 2) * 60) + "px"; full.set(s, { opacity: 1 }, 72.75 + i * 0.16); full.set(s, { opacity: 0 }, 72.75 + i * 0.16 + 0.5); });
  })();
  fig("35+ languages", "one assistant", 73.49, 73.6, 75.25, false, 600);
  plate("Four numbers", 75.25, 78.2);
  anchor("board", "s0", "Speed", 80.0, 82.4);
  anchor("board", "s1", "Volume", 85.5, 87.4);
  anchor("board", "s2", "Repeat questions", 93.5, 95.9);
  plate("More accurate answers", 100.3, 103.15);
  anchor("board", "s3", "Money", 103.5, 105.7, "pink");
  quote(wq("“superior experiences for our customers at better prices”", 112.2, 116.0), "Sebastian Siemiatkowski, CEO, Klarna", "Klarna press release, 27 February 2024", 110.75, 116.15, [6, 7]);
  plate("Every number went the right way", 120.8, 123.95);
  anchor("board", "s4", "red:A fifth claim", 125.9, 128.25, "red");
  plate("Never given a number", 126.9, 128.25, "red ul");
  stamp("23 May 2022", 131.8, 138.8);
  (function () { // May 2022: a fact card (not a headline)
    var f = el("div", "head", LY, '<div class="o"><span>May 2022</span><span>Klarna</span></div><div class="r"></div><div class="h">About <span class="m">700 jobs cut</span>, roughly 10% of its global workforce</div><div class="n">Klarna cited the economy · Source: Entrepreneur</div>');
    hide(f); full.set(f, { opacity: 1 }, 138.9); full.fromTo(f, { y: 50, scale: 0.95 }, { y: 0, scale: 1, duration: 0.6, ease: "power3.out", immediateRender: false }, 138.9);
    full.fromTo(f.querySelector(".m"), { backgroundSize: "0% 100%" }, { backgroundSize: "100% 100%", duration: 0.5, immediateRender: false }, 139.5);
    full.to(f, { opacity: 0, duration: 0.2 }, 142.1);
  })();
  (function () { var a = el("div", "splitlab", LY, '<div class="sl">May 2022 · 700 laid off</div><div class="sr">Feb 2024 · 700 agents’ work</div><div class="bar"></div>'); show(a, 142.35, 146.0, { blur: 6 }); })();
  (function () { // the two 700s slide together and overlap
    var w = el("div", "solo", LY, ""); w.innerHTML = '<span class="a" style="position:absolute;color:#9ea4ac">700</span><span class="b" style="position:absolute">700</span>';
    cut(w, 146.0, 148.6); var a = w.querySelector(".a"), b = w.querySelector(".b");
    full.fromTo(a, { x: -440 }, { x: 0, duration: 1.5, ease: "power2.inOut", immediateRender: false }, 146.1);
    full.fromTo(b, { x: 440 }, { x: 0, duration: 1.5, ease: "power2.inOut", immediateRender: false }, 146.1);
    full.to(a, { opacity: 0, duration: 0.3 }, 147.6);
  })();
  question("How many jobs did the AI really take?", 148.9, 155.5);
  // ================================================================== PART TWO
  chapter("2", "Happening now", 156.2, 159.6);
  stamp("5 March 2024", 157.3, 162.8);
  l3("CBS News · 5 March 2024", "Sebastian Siemiatkowski", "Chief executive, Klarna", 160.1, 162.8);
  plate("The effect of AI on work", 163.2, 165.9);
  quote(wq("“isn’t something that’s happening in the future, it’s happening now”", 166.1, 170.3), "Sebastian Siemiatkowski", "CBS News, March 2024", 166.0, 170.95, [8, 9]);
  plate("How Klarna judged it", 172.2, 174.35);
  (function () { var q = el("div", "plate", LY, '<div class="in" style="text-transform:none;font-family:var(--serif);font-weight:400;font-size:58px">“making sure it makes fewer mistakes, on average, than humans do”</div>'); q.style.top = "90px"; show(q, 176.0, 181.3, { blur: 8 }); })();
  anchor("scales", "right", "Human agent", 178.2, 181.3);
  anchor("scales", "left", "pink:The assistant", 179.8, 181.3, "pink");
  plate("People make mistakes too", 181.8, 184.5);
  plate("Tests the answer", 186.3, 190.45, "ul");
  anchor("sort", "repeat", "Repeat", 194.3, 197.5);
  anchor("sort", "hard", "red:Hard", 195.0, 197.5, "red");
  plate("That part holds up", 198.5, 200.55);
  plate("Hard cases stay with people", 201.0, 204.25, "red");
  // ================================================================== MID-ROLL
  (function () { var a = el("div", "splitlab", LY, '<div class="sl">Klarna</div><div class="sr">A business in the UK</div><div class="bar"></div>'); show(a, 204.35, 207.75, { blur: 6 }); })();
  anchor("uk", "inbox", "red:Same question, again", 209.4, 211.35, "red");
  anchor("uk", "forms", "Same form, twice", 213.8, 214.55);
  anchor("uk", "phone", "red:Missed calls", 215.2, 216.55, "red");
  plate("Carefully", 220.2, 220.85, "ul");
  (function () {
    var c = el("div", "midroll", LY, '<div class="k">Free guide</div><div class="t">5 jobs AI can take off a small business</div><div class="s">and how to start without breaking anything</div><div class="d"><span class="ar"></span>In the description</div>' +
      '<div class="cv"><div class="n">5</div><div class="c">Jobs AI can take off a small business</div></div>');
    show(c, 221.2, 230.5, { blur: 12, din: 0.55, y: 30 });
    full.fromTo(c.querySelector(".cv"), { x: 120, rotation: 6, opacity: 0 }, { x: 0, rotation: 3, opacity: 1, duration: 0.6, ease: "power3.out", immediateRender: false }, 222.3);
    full.fromTo(c.querySelector(".d .ar"), { y: -10 }, { y: 6, duration: 0.5, yoyo: true, repeat: 5, ease: "sine.inOut", immediateRender: false }, 229.4 - 5.4);
  })();
  dim(221.1, 230.6, 0.45, 0.3);
  solo("Carefully", 230.6, 234.0, true, false);
  // ================================================================== PART THREE
  chapter("3", "The machine keeps working", 237.4, 240.6);
  stamp("16 May 2025", 238.2, 243.9);
  l3("Big Technology podcast · May 2025", "Sebastian Siemiatkowski", "Chief executive, Klarna", 241.2, 244.2);
  fig("1.3 million", "errands a month", 247.57, 247.8, 249.75);
  fig("~800", "people’s work", 251.61, 251.8, 253.55);
  anchor("sort", "hard", "red:Level two", 259.5, 261.0, "red");
  plate("The harder cases", 261.6, 264.75);
  plate("The machine hadn’t broken", 266.0, 267.95);
  plate("More work. Harder work.", 269.1, 272.9);
  // ================================================================== PART FOUR
  chapter("4", "The turn", 276.6, 278.3);
  (function () { // the photograph, first appearance; the words appear beside it
    var p = el("div", "photo", LY, '<div class="fr"><img src="img/siemiatkowski.jpg" alt=""></div><div class="credit">Photo: TechCrunch, CC BY 2.0, via Wikimedia Commons</div>' +
      '<div class="side"><div class="k">Sebastian Siemiatkowski · May 2025</div><div class="t"></div></div>');
    cut(p, 278.4, 291.3); var img = p.querySelector("img"), fr = p.querySelector(".fr");
    full.fromTo(fr, { opacity: 0 }, { opacity: 1, duration: 0.6, immediateRender: false }, 278.45);
    full.fromTo(img, { scale: 1.0, y: 0 }, { scale: 1.08, y: 10, duration: 4.6, ease: "none", immediateRender: false }, 278.4);
    full.set(img, { scale: 1.35, y: 70 }, 283.0); full.to(img, { scale: 1.45, y: 80, duration: 4.2, ease: "none" }, 283.0);
    full.set(img, { scale: 1.12, y: 20 }, 287.2); full.to(img, { scale: 1.2, y: 30, duration: 4.1, ease: "none" }, 287.2);
    var t = p.querySelector(".side .t"); var txt = "Lower quality";
    txt.split("").forEach(function (ch, i) { var c = el("span", "ch", t, ch === " " ? "&nbsp;" : ch); full.set(c, { opacity: 1 }, 290.15 + i * 0.04); });
    var k = p.querySelector(".side .k"); hide(k); full.to(k, { opacity: 1, duration: 0.4 }, 279.2);
  })();
  stamp("CX Today, reporting Bloomberg", 279.3, 290.9, true);
  plate("Too heavy a focus on cost", 285.6, 289.9, "red");
  quote(wq("“Really investing in the quality of the human support is the way of the future…”", 293.05, 297.9), "Sebastian Siemiatkowski", "May 2025, as reported by CX Today", 293.0, 298.55, [7]);
  plate("Always a human, if they want one", 302.0, 305.3, "ul");
  plate("Hiring people again", 305.8, 308.2, "pink");
  head("Forbes", "18 May 2025", "Klarna reverses on AI, says <span class=\"m\">customers like talking to people</span>", "", 308.3, 313.8, 310.9);
  (function () { // the photograph again, tighter
    var p = el("div", "photo", LY, '<div class="fr"><img src="img/siemiatkowski.jpg" alt=""></div><div class="credit">Photo: TechCrunch, CC BY 2.0, via Wikimedia Commons</div>' +
      '<div class="side"><div class="k">His words</div><div class="t">Too much focus on <span class="cst" style="position:relative">cost<i style="position:absolute;left:0;right:0;bottom:6px;height:10px;background:#e0412f;transform-origin:0 50%;transform:scaleX(0)"></i></span></div></div>');
    cut(p, 313.8, 322.5); var img = p.querySelector("img");
    full.fromTo(img, { scale: 1.55, y: 110 }, { scale: 1.68, y: 120, duration: 4.6, ease: "none", immediateRender: false }, 313.8);
    full.set(img, { scale: 1.25, y: 40 }, 318.4); full.to(img, { scale: 1.32, y: 50, duration: 4.1, ease: "none" }, 318.4);
    var tt = p.querySelector(".side .t"); hide(tt); full.to(tt, { opacity: 1, duration: 0.4 }, 314.3);
    full.to(p.querySelector(".cst i"), { scaleX: 1, duration: 0.4, ease: "power2.out" }, 321.9);
  })();
  plate("He didn’t say the AI failed", 316.8, 318.35);
  stamp("September 2025", 322.6, 329.9);
  stamp("Source: Business Insider", 326.1, 329.9, true);
  anchor("floor", "doorE", "Engineering", 323.4, 325.9);
  anchor("floor", "doorM", "Marketing", 326.9, 329.9);
  (function () { var c = el("div", "datehero", LY, '<div class="d">10</div><div class="m">September 2025</div><div class="e">Klarna lists on the NYSE</div>');
    show(c, 330.0, 332.35, { blur: 6, din: 0.25, y: -24 }); full.fromTo(c.querySelector(".d"), { rotationX: 90 }, { rotationX: 0, duration: 0.35, immediateRender: false }, 330.2); })();
  dim(330.0, 332.4, 0.65, 0.15);
  question("Did the U-turn cost Klarna its moment?", 336.4, 339.75);
  // ================================================================== PART FIVE
  chapter("5", "The bell", 340.0, 343.3);
  stamp("New York · 10 September 2025", 341.9, 346.8);
  anchor("nyse", "ticker", "pink:KLAR", 348.3, 350.15, "pink");
  head("Al Jazeera", "10 Sep 2025", "Buy now, pay later company Klarna goes public in <span class=\"m\">largest IPO of 2025</span>", "", 350.2, 353.6, 351.6);
  fig("$1.37bn", "raised", 354.58, 354.8, 356.95, true);
  fig("$15bn", "valuation", 358.84, 359.0, 360.35, true);
  plate("The listing went ahead", 360.9, 363.25);
  // ================================================================== PART SIX
  chapter("6", "The cheap option", 363.5, 366.7);
  stamp("February 2026", 366.9, 372.7);
  (function () { // the headcount: two bars slam in (no counting), then the gap and the two labels
    dim(366.8, 378.0, 0.8, 0.2);
    var h = el("div", "hc", LY, '<div class="row"><div class="yr">2022</div><div class="bar" style="width:1300px"></div></div><div class="row"><div class="yr">2026</div><div class="bar" style="width:557px"></div></div>' +
      '<div class="v1" style="position:absolute;left:210px;top:-120px;font-family:var(--heavy);font-weight:900;font-size:96px">about 7,000</div>' +
      '<div class="v2" style="position:absolute;left:210px;top:300px;font-family:var(--heavy);font-weight:900;font-size:96px">about 3,000</div>' +
      '<div class="gap" style="left:767px;width:743px"></div>' +
      '<div class="gl" style="position:absolute;left:800px;top:320px;display:flex;gap:26px"><span class="plate" style="position:relative;left:0;top:0;transform:none"><span class="in">Layoffs</span></span><span class="qm" style="font-family:var(--heavy);font-weight:900;font-size:96px;line-height:1">?</span><span class="plate" style="position:relative;left:0;top:0;transform:none"><span class="in">Not replaced</span></span></div>');
    hide(h); full.set(h, { opacity: 1 }, 366.85); full.to(h, { opacity: 0, duration: 0.25 }, 377.75);
    var bars = h.querySelectorAll(".bar");
    full.fromTo(bars[0], { scaleX: 0 }, { scaleX: 1, duration: 0.3, ease: "power3.out", immediateRender: false }, 371.3);
    slam(h.querySelector(".v1"), 371.45);
    full.fromTo(bars[1], { scaleX: 0 }, { scaleX: 1, duration: 0.3, ease: "power3.out", immediateRender: false }, 374.2);
    slam(h.querySelector(".v2"), 374.37);
    var g = h.querySelector(".gap"); hide(g); full.to(g, { opacity: 1, duration: 0.3 }, 375.1);
    var gl = h.querySelector(".gl"); hide(gl); full.fromTo(gl, { opacity: 0, y: 20 }, { opacity: 1, y: 0, duration: 0.3, immediateRender: false }, 375.8);
  })();
  stamp("Source: Business Insider, February 2026", 367.2, 377.7, true);
  plate("Split unknown", 379.8, 384.8, "red");
  anchor("outsource", "sign", "Not Klarna’s own staff", 386.3, 388.8);
  plate("Moved to other work", 392.0, 393.85);
  quote(wq("“Nobody lost their job, but it was like an eye opener for us.”", 395.03, 397.8), "Sebastian Siemiatkowski", "February 2026, as reported by Customer Experience Dive", 393.95, 398.55);
  stamp("20VC podcast · February 2026", 398.7, 404.5);
  plate("His fullest answer", 401.8, 404.5);
  (function () { // the cheap quote: words in time, then CHEAP alone in the one true silence
    var q = quote(wq("“if AI can do customer service, it means it’s going to be the cheap customer service”", 405.2, 410.1), "Sebastian Siemiatkowski", "20VC, as reported by Customer Experience Dive", 404.65, 410.55, [13]);
    var s = el("div", "solo serif", LY, "<span><i>cheap</i></span>"); cut(s, 410.55, 412.4);
    full.fromTo(s.querySelector("span"), { scale: 1 }, { scale: 1.12, duration: 1.85, ease: "none", immediateRender: false }, 410.55);
  })();
  plate("Too much focus on cost", 413.9, 417.2, "red ul");
  quote(wq("“we have to rethink this and make customer service this human part of what Klarna is”", 417.45, 423.45), "Sebastian Siemiatkowski", "20VC, as reported by Customer Experience Dive", 417.35, 424.35, [10]);
  plate("Now go back to the scoreboard", 425.2, 427.3);
  fig("11 min → under 2", "speed", 427.6, 427.8, 429.85, false, 110, true);
  fig("700 → 800", "agents’ work", 431.2, 431.4, 433.55, false, 110, true);
  fig("-25%", "repeat questions", 435.0, 435.2, 436.35, false, 110, true);
  plate("The AI hit every number", 440.6, 443.4, "ul");
  plate("Quality fell", 445.8, 446.95, "red ul");
  head("Forbes", "16 Jul 2026", "How Klarna’s AI agent strategy <span class=\"m\">backfired</span> but became a useful lesson", "", 447.0, 451.4, 448.4);
  anchor("kitchen", "watch", "Speed", 452.6, 454.9);
  anchor("kitchen", "dining", "Happy?", 458.8, 460.45);
  plate("Tests the answer", 461.3, 467.85, "ul");
  plate("Not the customer", 466.6, 467.85, "red", 920);
  plate("Never given a number", 469.8, 472.35, "red ul");
  (function () { // the release, again: the fifth claim in Klarna's own words
    var d = el("div", "doc evidence-doc", LY, '<div class="pg"><div class="src">klarna.com · press</div><img class="klarna-mark" src="img/klarna-badge.svg" alt="Klarna"><div class="kick">Press release</div><div class="dt">27 February 2024</div>' +
      '<div class="hl release-title">Klarna AI assistant handles two-thirds of customer service chats in its first month</div><div class="line"><div class="hi"></div><span>“It is on par with human agents in regard to customer satisfaction score”</span></div><div class="by">Klarna press release · claim quoted exactly</div></div>');
    cut(d, 472.4, 477.5); var pg = d.querySelector(".pg");
    full.fromTo(pg, { x: 150, y: 60, scale: 0.98, rotation: -1 }, { x: 110, y: -20, scale: 1.04, rotation: -0.4, duration: 5.1, ease: "sine.inOut", immediateRender: false }, 472.4);
    full.fromTo(d.querySelector(".hi"), { scaleX: 0 }, { scaleX: 1, duration: 0.8, ease: "power2.out", immediateRender: false }, 474.2);
  })();
  (function () { // explicit research finding; no fictional report stack
    var w = el("div", "evidence-check", LY, '<div class="eyebrow">PUBLIC EVIDENCE CHECK</div><div class="big">No published customer-satisfaction score located</div>' +
      '<div class="scope">Reviewed public company material and cited reporting</div><div class="chips"><span>Press material</span><span>Investor material</span><span>News reporting</span></div><div class="qual">No independent figure was located in the reviewed sources.</div>');
    cut(w, 477.5, 481.8); full.fromTo(w, { opacity: 0, y: 30 }, { opacity: 1, y: 0, duration: 0.4, ease: "power3.out", immediateRender: false }, 477.55);
  })();
  (function () { // Octopus, from the last film, beside Klarna's empty slot
    var w = el("div", "doc", LY, '<div style="position:absolute;left:180px;top:250px;width:700px;padding:44px;background:#fbfaf7;border-radius:10px;box-shadow:0 30px 80px rgba(0,0,0,.4)"><div class="kick">Last film · Octopus Energy</div><div class="hl" style="font-size:66px;margin-top:20px">AI emails: 80% satisfied</div><div class="by">vs 65% for skilled staff · its own figures, published</div></div>' +
      '<div style="position:absolute;left:1040px;top:250px;width:700px;padding:44px;background:#fbfaf7;border-radius:10px;box-shadow:0 30px 80px rgba(0,0,0,.4)"><div class="kick">Klarna</div><div class="hl" style="font-size:66px;margin-top:20px">On par with humans: <span style="position:relative;color:#e0412f">?</span></div><div class="by">no score published, no independent figure</div></div>');
    w.style.background = "#0f1216"; cut(w, 481.8, 485.0);
    full.fromTo(w.children[0], { x: -80, opacity: 0 }, { x: 0, opacity: 1, duration: 0.4, immediateRender: false }, 481.85);
    full.fromTo(w.children[1], { x: 80, opacity: 0 }, { x: 0, opacity: 1, duration: 0.4, immediateRender: false }, 482.3);
  })();
  stamp("Source: Octopus Energy via Business Insider", 482.0, 484.9, true);
  (function () { // his word / then they hired
    var p = el("div", "photo", LY, '<div class="fr" style="left:120px;right:auto;width:720px;height:900px"><img src="img/siemiatkowski.jpg" alt="" style="width:720px;height:900px"></div><div class="credit" style="left:120px;right:auto">Photo: TechCrunch, CC BY 2.0, via Wikimedia Commons</div>' +
      '<div class="side" style="left:1000px;top:330px;width:800px"><div class="t" style="font-size:110px">His word</div><div class="t t2" style="font-size:110px;color:#ffb3c7">Then they hired</div></div>');
    cut(p, 485.0, 489.2); var img = p.querySelector("img");
    full.fromTo(img, { scale: 1.3, y: 60 }, { scale: 1.38, y: 70, duration: 4.2, ease: "none", immediateRender: false }, 485.0);
    var t1 = p.querySelector(".side .t"), t2 = p.querySelector(".t2"); hide(t1); hide(t2);
    full.fromTo(t1, { opacity: 0, x: 30 }, { opacity: 1, x: 0, duration: 0.4, immediateRender: false }, 487.9);
    full.fromTo(t2, { opacity: 0, x: 30 }, { opacity: 1, x: 0, duration: 0.4, immediateRender: false }, 488.5);
  })();
  plate("Which was to hire people", 491.3, 494.3, "pink");
  plate("Klarna didn’t give up on AI", 494.8, 498.3);
  plate("What it’s for", 503.2, 505.9, "ul");
  // ================================================================== PART SEVEN
  chapter("7", "What this means for your business", 506.4, 509.1);
  plate("A UK business · £1m to £50m a year", 510.6, 514.8);
  (function () { // the sales slide: SPEED and COST
    var d = el("div", "doc", LY, '<div class="pg" style="width:1500px;height:780px;left:210px;top:150px;display:flex;flex-direction:column;justify-content:center;align-items:center"><div class="kick">Every AI pitch</div><div style="display:flex;gap:90px;margin-top:40px"><div class="w1" style="font-family:var(--heavy);font-weight:900;font-size:230px;line-height:1">SPEED</div><div class="w2" style="font-family:var(--heavy);font-weight:900;font-size:230px;line-height:1;color:#e0412f">COST</div></div></div>');
    d.style.background = "#1b1f26"; cut(d, 514.9, 519.0);
    slam(d.querySelector(".w1"), 515.3); slam(d.querySelector(".w2"), 516.4);
  })();
  plate("Exactly the numbers Klarna hit", 520.3, 522.75, "ul");
  plate("Less room than Klarna", 523.4, 525.75, "red");
  (function () { var a = el("div", "splitlab", LY, '<div class="sl">People back on the phones</div><div class="sr">Still listed</div><div class="bar"></div>'); show(a, 525.85, 530.75, { blur: 6 }); })();
  fig("$15bn", "valuation", 529.29, 529.45, 530.75, true, 380);
  plate("A firm of 40 people", 531.4, 534.5);
  plate("Nobody can reach a person", 535.0, 536.55, "red");
  plate("No second go", 537.1, 538.55, "red ul");
  head("Vice", "19 May 2025", "This company replaced workers with AI, now they’re <span class=\"m\">looking for humans again</span>", "Survey by Orgvue", 541.4, 545.3, 542.8);
  (function () { // the bar filling just past halfway: over half regret it
    var b = el("div", "doc", LY, '<div style="position:absolute;left:260px;top:360px;width:1400px"><div class="kick" style="color:#cfd3d8">UK business leaders who replaced jobs with AI</div>' +
      '<div style="position:relative;margin-top:40px;height:150px;background:#2a2f37;border-radius:6px;overflow:hidden"><div class="fl" style="position:absolute;left:0;top:0;bottom:0;width:100%;background:#e0412f;transform-origin:0 50%"></div><div style="position:absolute;left:50%;top:-20px;bottom:-20px;width:4px;background:#fff"></div></div>' +
      '<div class="lb" style="margin-top:40px;font-family:var(--heavy);font-weight:900;font-size:110px;color:#fff;text-transform:uppercase">Over half regret it</div><div class="kick" style="color:#9ca3af;margin-top:16px">Source: Vice, 19 May 2025 · survey by Orgvue</div></div>');
    b.style.background = "#0f1216"; cut(b, 545.3, 549.9);
    full.fromTo(b.querySelector(".fl"), { scaleX: 0 }, { scaleX: 0.56, duration: 0.9, ease: "power3.out", immediateRender: false }, 545.5);
    slam(b.querySelector(".lb"), 548.55);
  })();
  (function () { // the lesson: three cards, the clipboard ticks, the two-slot board, the calendar, the chart
    dim(549.9, 567.3, 0.55, 0.25); var w = el("div", "doc", LY, ""); w.style.background = "transparent"; cut(w, 549.9, 567.3);
    var ls = el("div", "lesson", w, ""); ls.style.left = "90px"; ls.style.top = "110px"; ls.style.width = "780px";
    var h0 = el("div", "", ls, '<div style="font-family:var(--heavy);font-weight:900;font-size:84px;text-transform:uppercase;line-height:1;color:#fff">3 things before AI answers a customer</div>');
    hide(h0); full.fromTo(h0, { opacity: 0, y: 20 }, { opacity: 1, y: 0, duration: 0.4, immediateRender: false }, 550.3);
    full.to(h0, { opacity: 0, duration: 0.3 }, 555.2);
    var c1 = el("div", "card", ls, '<div class="n">1</div><div class="h">Write down 3 numbers</div><div class="l"><div><b></b>Same question twice</div><div><b></b>Complaints</div><div><b></b>Customers who leave</div></div>');
    c1.style.marginTop = "-60px"; hide(c1); full.fromTo(c1, { opacity: 0, x: -80 }, { opacity: 1, x: 0, duration: 0.45, ease: "power3.out", immediateRender: false }, 555.55);
    var rows = c1.querySelectorAll(".l div"); [561.8, 564.2, 566.0].forEach(function (t, i) { hide(rows[i]); full.fromTo(rows[i], { opacity: 0, x: -20 }, { opacity: 1, x: 0, duration: 0.3, immediateRender: false }, t - 0.2); full.to(rows[i], { "--ck": 1, duration: 0.2 }, t + 0.2); });
    full.fromTo(c1, { scale: 1 }, { scale: 1.08, duration: 11.5, ease: "none", immediateRender: false }, 555.8);
  })();
  plate("A tripwire", 567.6, 570.1, "red");
  plate("The rollout stops until someone knows why", 572.4, 574.35, "red");
  (function () { // money slot + customer slot
    var w = el("div", "doc", LY, '<div style="position:absolute;left:330px;top:300px;display:flex;gap:60px">' +
      '<div style="width:560px;padding:40px;background:#1b2027;border-radius:10px;color:#f4f2ec"><div class="kick" style="color:#cfd3d8">Money</div><div style="font-family:var(--mono);font-weight:500;font-size:130px;margin-top:20px">$40M</div><div style="width:40px;height:40px;border-radius:50%;background:#2fd27a;margin-top:20px"></div></div>' +
      '<div style="width:560px;padding:40px;background:#1b2027;border-radius:10px;color:#f4f2ec"><div class="kick" style="color:#cfd3d8">Customers</div><div class="cu" style="font-family:var(--mono);font-weight:500;font-size:130px;margin-top:20px">?</div><div class="lp" style="width:40px;height:40px;border-radius:50%;background:#3a3f47;margin-top:20px"></div></div></div>' +
      '<div class="yb" style="position:absolute;left:330px;top:190px;font-family:var(--heavy);font-weight:900;font-size:64px;text-transform:uppercase;color:#fff">Klarna had a money number</div>');
    w.style.background = "#0f1216"; cut(w, 574.4, 579.1);
    var cu = w.querySelector(".cu"); full.set(cu, { innerHTML: "✓" }, 578.1); full.set(w.querySelector(".lp"), { backgroundColor: "#2fd27a" }, 578.2);
    full.set(w.querySelector(".yb"), { innerHTML: "Get a customer number too" }, 577.3);
  })();
  (function () { var c = el("div", "card", LY, '<div class="n">2</div><div class="h">Repeat questions to the machine. People on the rest.</div>'); c.style.position = "absolute"; c.style.left = "90px"; c.style.top = "80px"; c.style.width = "760px"; show(c, 579.3, 583.85, { blur: 8, y: -20 }); })();
  plate("The upset ones, the ones who are struggling", 585.4, 588.35);
  (function () { // the route to a person, everywhere
    var w = el("div", "doc", LY, ""); w.style.background = "#e9ebee"; cut(w, 591.0, 593.6);
    var web = el("div", "", w, '<div style="position:absolute;left:120px;top:160px;width:900px;height:640px;background:#fbfaf7;border-radius:10px;box-shadow:0 30px 80px rgba(0,0,0,.25)"><div style="height:70px;background:#14171c;border-radius:10px 10px 0 0"></div><div class="bars" style="padding:40px"><i></i><i class="s"></i><i></i></div><div style="position:absolute;left:0;right:0;bottom:0;height:150px;background:#eef0f2;border-radius:0 0 10px 10px"></div></div>');
    var b1 = el("div", "human", w, "Talk to a person"); b1.style.left = "330px"; b1.style.top = "690px";
    var menu = el("div", "", w, '<div style="position:absolute;left:1160px;top:200px;width:620px;padding:40px;background:#14171c;border-radius:14px;color:#fff;font-family:var(--mono);font-size:44px;line-height:1.8">PRESS 1 · PAYMENTS<br>PRESS 2 · REFUNDS<br><span class="z" style="color:#9fb8ff">PRESS 0 · A PERSON</span></div>');
    slam(b1, 591.7); var z = menu.querySelector(".z"); full.fromTo(z, { color: "#9fb8ff" }, { color: "#2f6bff", duration: 0.2, immediateRender: false }, 592.4);
    full.fromTo(z, { backgroundColor: "rgba(47,107,255,0)" }, { backgroundColor: "rgba(47,107,255,0.25)", duration: 0.2, immediateRender: false }, 592.4);
  })();
  plate("Always a human if you want one", 597.3, 599.45, "ul");
  (function () { // 3: don't bank the saving; the calendar and the two lines
    dim(599.5, 615.4, 0.72, 0.25); var w = el("div", "doc", LY, ""); w.style.background = "transparent"; cut(w, 599.5, 615.4);
    var c = el("div", "card", w, '<div class="n">3</div><div class="h">Don’t bank the saving until you’ve seen the quality</div>'); c.style.position = "absolute"; c.style.left = "90px"; c.style.top = "90px"; c.style.width = "760px";
    hide(c); full.fromTo(c, { opacity: 0, x: -60 }, { opacity: 1, x: 0, duration: 0.4, immediateRender: false }, 600.0);
    var lock = el("div", "", w, '<div style="position:absolute;left:300px;top:520px;width:260px;height:200px;background:#f6f4ef;border-radius:24px"></div><div style="position:absolute;left:350px;top:400px;width:160px;height:180px;border:26px solid #f6f4ef;border-bottom:0;border-radius:90px 90px 0 0;box-sizing:border-box"></div><div style="position:absolute;left:405px;top:580px;width:50px;height:80px;background:#e0412f;border-radius:25px"></div><div style="position:absolute;left:230px;top:760px;font-family:var(--heavy);font-weight:900;font-size:60px;text-transform:uppercase;color:#fff">Saved?</div>');
    hide(lock); full.fromTo(lock, { opacity: 0, scale: 0.9 }, { opacity: 1, scale: 1, duration: 0.35, immediateRender: false }, 601.6); full.to(lock, { opacity: 0, duration: 0.3 }, 604.0);
    var ch = el("div", "chart", w, '<div class="k">Three months, side by side</div><svg width="720" height="330" viewBox="0 0 720 330"><path class="p1" d="M0,290 C120,270 240,200 360,160 S600,80 720,60" stroke="#2f6bff" stroke-width="10" fill="none" stroke-linecap="round"/><path class="p2" d="M0,280 C120,250 240,210 360,175 S600,110 720,90" stroke="#e0412f" stroke-width="10" fill="none" stroke-linecap="round"/></svg><div class="lg"><span><i style="background:#2f6bff"></i>Customers</span><span><i style="background:#e0412f"></i>Cost</span></div>');
    hide(ch); full.to(ch, { opacity: 1, duration: 0.3 }, 604.2);
    [ch.querySelector(".p1"), ch.querySelector(".p2")].forEach(function (p) { p.style.strokeDasharray = "1000"; full.fromTo(p, { strokeDashoffset: 1000 }, { strokeDashoffset: 0, duration: 6.5, ease: "none", immediateRender: false }, 604.8); });
    var cal = el("div", "cal", w, '<div class="top">MONTH</div><div class="d">1</div><div class="st">Klarna announced here</div>'); cal.style.left = "380px"; cal.style.top = "540px";
    var d = cal.querySelector(".d"), stp = cal.querySelector(".st"); hide(cal); hide(stp);
    full.to(cal, { opacity: 1, duration: 0.3 }, 604.5);
    full.set(d, { innerHTML: "2" }, 607.0); full.set(d, { innerHTML: "3" }, 609.2);
    full.set(d, { innerHTML: "1" }, 612.15); full.fromTo(stp, { opacity: 0, scale: 1.35 }, { opacity: 1, scale: 1, duration: 0.18, ease: "power4.in", immediateRender: false }, 612.28);
    full.to([c, ch, cal], { opacity: 0, duration: 0.22 }, 612.62);
  })();
  // ================================================================== CLOSE AND CTA
  plate("Every test it was given", 617.4, 619.5, "ul");
  plate("The one that mattered was never published", 620.1, 623.8, "red");
  dim(621.6, 625.4, 1.0, 2.2);
  (function () { var p = el("div", "proofgap", LY, '<div class="k">CUSTOMER SATISFACTION</div><div class="v">NO PUBLIC SCORE</div><div class="s">The fifth slot stayed unmeasured</div>'); cut(p, 623.75, 625.4); })();
  (function () {
    var n = el("div", "nexttile", LY, '<div class="k">Tomorrow · 18:00</div><div class="img"><div class="rep"><i></i><i></i><i></i><i></i><i></i><i></i><i></i><i></i><div class="qm">”</div></div></div><div class="t">A consultancy report the government paid for, with a court quote nobody ever said</div>');
    show(n, 625.5, 632.85, { blur: 10, din: 0.5, y: 40 });
    full.fromTo(n.querySelector(".qm"), { opacity: 0.3 }, { opacity: 1, duration: 0.25, yoyo: true, repeat: 5, immediateRender: false }, 629.4);
  })();
  dim(632.9, FULL, 0.32, 0.35);
  (function () {
    var e = el("div", "endcard", LY, '<div class="brand">AGMM</div><div class="t">Book a free 30-minute call</div><div class="u">agmm.co.uk/ai-constraint-audit</div><div class="btn">Book your call</div><div class="lk">Link below</div>');
    hide(e); full.set(e, { opacity: 1 }, 633.0);
    [".brand", ".t", ".u"].forEach(function (sel) { full.set(e.querySelector(sel), { opacity: 1, y: 0, filter: "blur(0px)" }, 633.0); });
    [".btn", ".lk"].forEach(function (sel, i) { var x = e.querySelector(sel); hide(x);
      full.fromTo(x, { opacity: 0, y: 18 }, { opacity: 1, y: 0, duration: 0.35, immediateRender: false }, [634.0, 634.5][i]); });
    var b = e.querySelector(".btn"); for (var k = 0; k < 2; k++) full.to(b, { scale: 1.06, duration: 0.35, yoyo: true, repeat: 1, ease: "sine.inOut" }, 645.2 + k * 2.2);
  })();
  var blk = el("div", "black"); hide(blk); full.to(blk, { opacity: 1, duration: 0.6, ease: "sine.in" }, FULL - 0.65);

  // depth of field band per shot (backdrop blur outside the focus band)
  var dof = el("div", "dof"); root.insertBefore(dof, LY); hide(dof);
  SHOTS.forEach(function (s) { var d = s.dof; full.set(dof, d ? { opacity: 1, "--dt": (d[0] * 100) + "%", "--db": (d[1] * 100) + "%", "--dbl": d[2] + "px" } : { opacity: 0 }, s.t0); });

  // ------------------------------------------------------------------ grain (seek-safe) + frame driver
  var grain = root.querySelector(".grain");
  function frame(T) {
    full.totalTime(Math.min(T, FULL - 0.0001), true);
    var f = Math.floor(T * 30);
    grain.style.transform = "translate(" + (-Math.floor(hash(f, 3) * 40)) + "px," + (-Math.floor(hash(f, 9) * 40)) + "px)";
    if (window.__f02Render) window.__f02Render(T);
    window.__f02T = T;
  }
  var tl = gsap.timeline({ paused: true });
  tl.set({}, {}, SEG.len);
  tl.eventCallback("onUpdate", function () { frame(SEG.t0 + tl.time()); });
  window.__f02Frame = function () { frame(qs.get("t") ? Number(qs.get("t")) : SEG.t0 + tl.time()); };
  window.__f02Set = function (T) { frame(T); };
  window.__F02TL = tl;
  if (window.__timelines) window.__timelines[root.getAttribute("data-composition-id") || "f02"] = tl;
  frame(qs.get("t") ? Number(qs.get("t")) : SEG.t0);
  // dev helpers (never called by the renderer)
  window.__batch = async function (list) {
    var done = [];
    for (var i = 0; i < list.length; i++) { var b = list[i];
      if (b.cam) { var c = b.cam; DEV = { id: "DEV", scene: b.scene, t0: 0, t1: FULL, cam: [C(c.slice(0, 3), c.slice(3, 6), c[6] || 40)], ss: b.ss }; ST = b.st || null; } else { DEV = null; ST = null; }
      frame(b.t || 1); frame(b.t || 1); done.push(await window.__snap(b.name)); }
    return done.join(",");
  };
  window.__snap = function (name) { var c = document.getElementById("w3d"); return fetch("/snap/" + name, { method: "POST", body: c.toDataURL("image/png") }).then(function (r) { return r.text(); }); };
  } catch (err) { window.__f02Err = String(err && err.stack || err); if (window.__dbgErr) window.__dbgErr(window.__f02Err); throw err; }
  }
  if (document.getElementById("root") && document.querySelector("#root .layer")) build();
  else document.addEventListener("DOMContentLoaded", build);
})();
