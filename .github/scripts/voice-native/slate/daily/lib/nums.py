"""Numbers in scripts and sources, as comparable values.

values(text) -> list of Num(value, kind, raw, approx) where kind is 'pct' | 'money' | 'year' | 'n'.
Handles digits ("£3,265", "9mn", "£1.3bn", "45%", "C$812.02", "1,206", "Q4'25"), and spoken words
("nine million", "forty-five percent", "six hundred and forty pounds", "one in six" -> two numbers).

The check in check_script.py: every number a script says or shows must exist in a saved source with the same
kind and value (exact, or within 5% when the script hedges it: about/nearly/almost/around/roughly/more than/over/
under/up to/just over/just under); 2.5% is tight on purpose: "nearly ninety percent" must not pass on a
source that says 87% (the S39 trap). Bare spoken words zero to twelve with no unit are ignored ("one real AI story
a day", "two sources"): too common in ordinary speech to be claims. Digits are always checked.
"""
import re
from collections import namedtuple

Num = namedtuple("Num", "value kind raw approx pos")

UNITS = {"zero": 0, "one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "seven": 7, "eight": 8,
         "nine": 9, "ten": 10, "eleven": 11, "twelve": 12, "thirteen": 13, "fourteen": 14, "fifteen": 15,
         "sixteen": 16, "seventeen": 17, "eighteen": 18, "nineteen": 19}
TENS = {"twenty": 20, "thirty": 30, "forty": 40, "fifty": 50, "sixty": 60, "seventy": 70, "eighty": 80, "ninety": 90}
SCALES = {"hundred": 100, "thousand": 1e3, "million": 1e6, "billion": 1e9, "trillion": 1e12}
SUFFIX = {"k": 1e3, "thousand": 1e3, "m": 1e6, "mn": 1e6, "mln": 1e6, "million": 1e6, "bn": 1e9, "b": 1e9,
          "billion": 1e9, "tn": 1e12, "trillion": 1e12}
HEDGES = ("about", "nearly", "almost", "around", "roughly", "more than", "over", "under", "up to", "just over",
          "just under", "some", "close to", "approximately", "at least", "less than", "fewer than", "upwards of")
CUR = r"(?:[A-Z]{1,2}\$|US\$|C\$|A\$|\$|£|€)"
NUMWORD = "|".join(list(UNITS) + list(TENS) + list(SCALES) + ["and", "a", "half", "point"])


def _hedged(text, start):
    before = text[max(0, start - 22):start].lower()
    return any(re.search(r"\b" + re.escape(h) + r"\s*$", before) for h in HEDGES)


def _kind_after(text, end):
    after = text[end:end + 14].lower()
    if re.match(r"\s*(%|per ?cent|percent|pc\b|percentage point)", after):
        return "pct"
    if re.match(r"\s*(pounds|pound|dollars|dollar|euros|euro|pence|p\b)", after):
        return "money"
    return None


def words_to_number(ws):
    """['six','hundred','and','forty'] -> 640 ; ['nine','million'] -> 9e6 ; ['one','point','three','billion'] -> 1.3e9"""
    total, cur, dec, in_dec, seen = 0.0, 0.0, "", False, False
    for w in ws:
        w = w.lower()
        if w == "and" or w == "a":
            if w == "a":
                cur = cur or 1
            continue
        if w == "point":
            in_dec = True
            continue
        if in_dec and w in UNITS:
            dec += str(UNITS[w])
            continue
        if w in UNITS:
            cur += UNITS[w]; seen = True
        elif w in TENS:
            cur += TENS[w]; seen = True
        elif w == "hundred":
            cur = (cur or 1) * 100; seen = True
        elif w == "half":
            cur += 0.5; seen = True
        elif w in SCALES:
            if dec:
                cur = float("%d.%s" % (int(cur), dec)); dec, in_dec = "", False
            total += (cur or 1) * SCALES[w]; cur = 0; seen = True
    if dec:
        cur = float("%d.%s" % (int(cur), dec))
    return (total + cur) if seen else None


def values(text, spoken_words=True, keep_small=False):
    out = []
    t = text.replace(" ", " ").replace("’", "'")
    # digits, with optional currency before and suffix after
    rx = re.compile(r"(?<![\w.])(" + CUR + r")?\s?(\d{1,3}(?:,\d{3})+|\d+)(?:\.(\d+))?\s?(k|mn|mln|m|bn|b|tn|thousand|million|billion|trillion)?(?![\w])", re.I)
    for m in rx.finditer(t):
        cur, whole, frac, suf = m.group(1), m.group(2), m.group(3), m.group(4)
        v = float(whole.replace(",", "") + ("." + frac if frac else ""))
        if suf:
            v *= SUFFIX[suf.lower()]
        kind = "money" if cur else (_kind_after(t, m.end()) or None)
        if kind is None:
            iv = v
            kind = "year" if (not frac and not suf and 1900 <= iv <= 2100 and len(whole) == 4) else "n"
        out.append(Num(v, kind, m.group(0).strip(), _hedged(t, m.start()), m.start()))
    # ratios: "one in six", "1 in 5"
    small = dict(UNITS, **TENS)
    for m in re.finditer(r"\b(\d+|" + "|".join(small) + r")\s+(?:in|out of)\s+(\d+|" + "|".join(small) + r")\b", t, re.I):
        a, b = m.group(1).lower(), m.group(2).lower()
        a = float(a) if a.isdigit() else small.get(a)
        b = float(b) if b.isdigit() else small.get(b)
        if a and b and a < b:
            out.append(Num(round(a / b, 4), "ratio", m.group(0), _hedged(t, m.start()), m.start()))
    if spoken_words:
        wrx = re.compile(r"\b((?:(?:" + NUMWORD + r")[\s-]+)*(?:" + "|".join(list(UNITS) + list(TENS) + list(SCALES) + ["half"]) + r"))\b", re.I)
        for m in wrx.finditer(t):
            ws = [w for w in re.split(r"[\s-]+", m.group(1)) if w]
            while ws and ws[0].lower() in ("and", "a", "point"):
                ws.pop(0)
            if not ws:
                continue
            if all(w.lower() in SCALES for w in ws) and not re.search(r"\ba\s+$", t[max(0, m.start() - 3):m.start()], re.I):
                continue  # "9 MILLION": the scale word belongs to the digits before it (or stands alone)
            v = words_to_number(ws)
            if v is None:
                continue
            kind = _kind_after(t, m.end())
            pre = t[max(0, m.start() - 2):m.start()]
            if re.search(CUR + r"\s?$", pre):
                kind = "money"
            if kind is None:
                if v <= 12 and not keep_small and not any(w.lower() in SCALES for w in ws):
                    continue  # bare small word: ordinary speech, not a claim
                kind = "n"
            out.append(Num(v, kind, m.group(1), _hedged(t, m.start()), m.start()))
    return out


def same(a, b, tol=0.0):
    if a.value == b.value:
        return True
    if b.value == 0:
        return False
    return abs(a.value - b.value) / abs(b.value) <= tol


def compatible_kind(sk, ok):
    """script kind sk may be matched by source kind ok. A percentage must be a percentage in the source (a bare
    "90" elsewhere on the page proves nothing). Money may match a bare source number (tables print "812.02"),
    as may a year; a bare script number matches any kind."""
    if sk == ok or sk == "n":
        return True
    if sk == "ratio":
        return False
    if sk in ("money", "year"):
        return ok == "n"
    return False


def find_in(num, pool, tol_hedged=0.025):
    tol = tol_hedged if num.approx else 0.0015
    hits = [p for p in pool if compatible_kind(num.kind, p.kind) and same(num, p, tol)]
    if num.kind == "ratio":  # "one in six" may be printed as 17% or 16.7%
        hits += [p for p in pool if p.kind == "pct" and abs(p.value / 100 - num.value) <= 0.006]
    return hits
