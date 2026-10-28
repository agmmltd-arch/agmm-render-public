#!/usr/bin/env python3
"""fe_layout.py: text metrics and geometry for the format engine (kit/tools/format_engine.py). Python 3.9, stdlib + PIL (already used by compose.py).

Everything a browser would otherwise decide is decided here, with the kit's own font files, so the engine can PROVE (offline, in the selftest) that every text box sits
inside the universal safe zone (kit/platforms/universal.json) before a single frame is snapped:
  tw()        width in px of a string (PIL, the same woff2/ttf files kit.css loads; +1.5% like compose.py), letter-spacing counted per glyph as Chrome does
  wrap()      greedy word wrap to a width -> lines; fit_block() picks the largest font size whose wrapped block fits a box
  Box         x0 y0 x1 y1 with the zone tests (text_problems / hero_problems from kit/platforms/universal.py, so the engine and dom_lint use ONE definition)
"""
import os, sys, math

HERE = os.path.dirname(os.path.abspath(__file__))
KIT = os.path.dirname(HERE)
LIB = os.path.join(KIT, "lib")
sys.path.insert(0, os.path.join(KIT, "platforms"))
import universal  # noqa: E402

# (face, weight) -> (file under kit/lib, variable-axis weight or None)
FONT_FILES = {
    ("serif", 400): ("ds/fonts/sourceserif-var.woff2", 400), ("serif", 600): ("ds/fonts/sourceserif-var.woff2", 600), ("serif", 800): ("ds/fonts/sourceserif-var.woff2", 800),
    ("sans", 400): ("ds/fonts/spacegrotesk-var.woff2", 400), ("sans", 500): ("ds/fonts/spacegrotesk-var.woff2", 500), ("sans", 700): ("ds/fonts/spacegrotesk-var.woff2", 700),
    ("cond", 400): ("ds2/fonts/BigShoulders-Regular.ttf", None), ("cond", 700): ("ds2/fonts/BigShoulders-Bold.ttf", None),
    ("mono", 400): ("ds2/fonts/JetBrainsMono-Regular.ttf", None), ("mono", 700): ("ds2/fonts/JetBrainsMono-Bold.ttf", None),
}
_CACHE = {}
SAFETY = 1.015      # compose.py measures within 1%; one more half percent so a wrap decided here never overflows in Chrome


def _font(face, wt):
    from PIL import ImageFont
    k = (face, wt)
    if k not in _CACHE:
        path, axis = FONT_FILES[k]
        f = ImageFont.truetype(os.path.join(LIB, path), 100)
        if axis:
            try:
                f.set_variation_by_axes([axis])
            except Exception:
                pass
        _CACHE[k] = f
    return _CACHE[k]


def tw(text, face, wt, fs, ls=0.0, caps=False):
    """rendered width in px of one line"""
    t = text.upper() if caps else text
    return (_font(face, wt).getlength(t) * fs / 100.0) * SAFETY + ls * fs * len(t)


def wrap(text, face, wt, fs, maxw, ls=0.0, caps=False):
    """greedy wrap -> lines. A single word wider than maxw stays on its own line (the caller's width check then fails loudly)."""
    words = text.split()
    lines, cur = [], ""
    for w in words:
        trial = (cur + " " + w).strip()
        if cur and tw(trial, face, wt, fs, ls, caps) > maxw:
            lines.append(cur)
            cur = w
        else:
            cur = trial
    if cur:
        lines.append(cur)
    # no widow: a last line of one short word is pulled up with the word before it when the pair still fits
    if len(lines) >= 2 and len(lines[-1].split()) == 1 and len(lines[-2].split()) >= 3:
        a, b = lines[-2].rsplit(" ", 1)
        if tw(b + " " + lines[-1], face, wt, fs, ls, caps) <= maxw:
            lines[-2], lines[-1] = a, b + " " + lines[-1]
    return lines


def block_h(lines, fs, lh):
    return len(lines) * fs * lh


def fit_block(text, face, wt, maxw, maxh, fs_max, fs_min, lh=1.1, ls=0.0, caps=False, step=2):
    """the largest fs in [fs_min, fs_max] whose wrapped block fits maxw x maxh -> (fs, lines, height) or None"""
    fs = fs_max
    while fs >= fs_min:
        lines = wrap(text, face, wt, fs, maxw, ls, caps)
        if lines and block_h(lines, fs, lh) <= maxh and max(tw(l, face, wt, fs, ls, caps) for l in lines) <= maxw:
            return fs, lines, block_h(lines, fs, lh)
        fs -= step
    return None


def fit_line(text, face, wt, maxw, fs_max, fs_min, ls=0.0, caps=False):
    """largest single-line font size <= fs_max that fits maxw, or None if even fs_min does not"""
    w100 = tw(text, face, wt, 100.0, ls, caps)
    if w100 <= 0:
        return fs_max
    fs = min(fs_max, int(math.floor(maxw / w100 * 100.0)))
    return fs if fs >= fs_min else None


class Box(object):
    __slots__ = ("x0", "y0", "x1", "y1")

    def __init__(self, x0, y0, x1, y1):
        self.x0, self.y0, self.x1, self.y1 = float(x0), float(y0), float(x1), float(y1)

    @property
    def w(self):
        return self.x1 - self.x0

    @property
    def h(self):
        return self.y1 - self.y0

    def tuple(self):
        return (self.x0, self.y0, self.x1, self.y1)

    def shifted(self, dx, dy):
        return Box(self.x0 + dx, self.y0 + dy, self.x1 + dx, self.y1 + dy)

    def inflate(self, d):
        return Box(self.x0 - d, self.y0 - d, self.x1 + d, self.y1 + d)

    def overlap(self, o):
        w = min(self.x1, o.x1) - max(self.x0, o.x0)
        h = min(self.y1, o.y1) - max(self.y0, o.y0)
        return max(0.0, w) * max(0.0, h)

    def __repr__(self):
        return "Box(%.0f,%.0f,%.0f,%.0f)" % (self.x0, self.y0, self.x1, self.y1)


def text_box(x, y, lines, face, wt, fs, lh, al="l", w=None, ls=0.0, caps=False):
    """ink box of a text block: widest line x lines*fs*lh. al: l (x is the left edge), c (x is the centre), r (x is the right edge)."""
    mw = max([tw(l, face, wt, fs, ls, caps) for l in lines] or [0.0])
    if al == "c":
        x0 = x - mw / 2.0
    elif al == "r":
        x0 = x - mw
    else:
        x0 = x
    return Box(x0, y, x0 + mw, y + block_h(lines, fs, lh))


def zone():
    return universal.zone()


def text_ok(box, margin=0):
    """[] when the text box is inside the universal zone (+ the float margin shrinks the zone), else the problems"""
    z = dict(zone())
    if margin:
        z = dict(z, x0=z["x0"] + margin, y0=z["y0"] + margin, x1=z["x1"] - margin, y1=z["y1"] - margin)
        z["notches"] = [dict(n, x0=n["x0"] - margin, y0=n["y0"] - margin) for n in z.get("notches", [])]
    return universal.text_problems(box.tuple() if hasattr(box, "tuple") else box, z, tol=universal.TOL_PX)


def hero_ok(box):
    return universal.hero_problems(box.tuple() if hasattr(box, "tuple") else box)
