#!/usr/bin/env python3
"""Voice pace and pause measurement for one assembled take (root card voice-perf, 6 Oct 2026).

Why this exists: voice_lead_check counted ASR tokens ("2.3", "$40", "25%" are one token each) over the paragraph span,
so it undercounted number-heavy paragraphs (C13 P03: 180-185 by tokens, 215 by the script's own words) and it skipped every
paragraph under 8 tokens (the CTA). This module measures from the SCRIPT's words (numbers spelled as spoken) over the span
the take's own word timings give, and adds local pace and pause structure read from the audio itself.

No heavy dependencies: numpy plus the stdlib. Pure functions; voice_lead_check imports `analyse_take`.

Definitions (all per paragraph, on the assembled take that the listener hears):
  n_words        script words, whitespace-split (the receipt convention the pilot bands use), digits spelled as spoken
  span_s         first token start .. last token end, from <ID>.words.json
  wpm_script     n_words / span_s * 60
  pauses         runs of audio frames more than PAUSE_DB under the paragraph's loud level, at least 150 ms, strictly inside
                 the span (leading/trailing silence excluded)
  artic_wpm      n_words / (span_s - sum of pauses) * 60            (articulation rate: how fast the words themselves go)
  syl_rate       syllables per second of speech (same denominator)  (immune to how a number word is counted)
  win3_wps       the fastest 3-second window in words per second (the whole span when the paragraph is shorter than 3 s)
  run_max_s      the longest stretch of speech with no pause of 150 ms or more
  sent_pause_ms  mean low-energy gap (>= 60 ms) at the sentence-final boundaries inside the paragraph
  pause_per_sent pauses of 150 ms+ per sentence boundary inside the paragraph (the "pause deficit" is its shortfall)
"""
import difflib, json, math, os, re, wave

import numpy as np

PAUSE_MIN_S = 0.150
PAUSE_DB = 24.0          # "silent" = this far under the paragraph's p90 frame level (pause floors sit near -45 dB, speech p90 near -13; 32 missed every pause)

# ---------------------------------------------------------------- numbers as spoken
_ONES = ["zero", "one", "two", "three", "four", "five", "six", "seven", "eight", "nine", "ten", "eleven", "twelve",
         "thirteen", "fourteen", "fifteen", "sixteen", "seventeen", "eighteen", "nineteen"]
_TENS = ["", "", "twenty", "thirty", "forty", "fifty", "sixty", "seventy", "eighty", "ninety"]
_ORD = {"one": "first", "two": "second", "three": "third", "five": "fifth", "eight": "eighth", "nine": "ninth",
        "twelve": "twelfth"}


def _below100(n):
    if n < 20:
        return [_ONES[n]]
    t, o = divmod(n, 10)
    return [_TENS[t] + ("-" + _ONES[o] if o else "")]


def _below1000(n):
    out = []
    h, r = divmod(n, 100)
    if h:
        out += [_ONES[h], "hundred"]
        if r:
            out.append("and")
    if r or not h:
        out += _below100(r)
    return out


def int_words(n):
    """spoken words of a non-negative integer (British 'and' kept; hyphenated compounds are one word)"""
    if n < 1000:
        return _below1000(n)
    out = []
    for scale, name in ((10 ** 9, "billion"), (10 ** 6, "million"), (1000, "thousand")):
        q, n = divmod(n, scale)
        if q:
            out += _below1000(q) + [name]
    if n:
        out += (["and"] if n < 100 else []) + _below1000(n)
    return out


def year_words(n):
    if 2000 <= n <= 2009:
        return int_words(n)
    a, b = divmod(n, 100)
    return _below100(a) + (_below100(b) if b >= 10 else (["oh", _ONES[b]] if b else ["hundred"]))


def spoken(token):
    """spoken-word list for ONE whitespace token. Plain words come back as [token]; digits are spelled."""
    t = token.strip()
    core = t.strip(".,;:!?\"'()[]")
    if not re.search(r"\d", core):
        return [t]
    pre = ""
    if core[:1] in "£$€":
        cur = {"£": "pounds", "$": "dollars", "€": "euros"}[core[0]]
        core = core[1:]
    else:
        cur = ""
    pct = core.endswith("%")
    core = core.rstrip("%")
    m = re.fullmatch(r"(\d[\d,]*)(\.\d+)?(st|nd|rd|th)?", core)
    if not m:                         # 5G, 3D, 20VC, GPT-4o, COVID-19: digits read one by one, letters as a word
        return [w for w in re.split(r"[-\s]", re.sub(r"(\d)", r" \1 ", core).replace("  ", " ")) if w]
    whole, frac, suf = m.group(1).replace(",", ""), m.group(2), m.group(3)
    n = int(whole)
    if not frac and not suf and not cur and not pct and len(whole) == 4 and 1100 <= n <= 2099 and "," not in m.group(1):
        out = year_words(n)
    else:
        out = int_words(n)
    if frac:
        out += ["point"] + [_ONES[int(c)] for c in frac[1:]]
    if suf:
        last = out[-1]
        head, _, tail = last.rpartition("-")
        base = tail or head
        ordw = _ORD.get(base, base[:-1] + "ieth" if base.endswith("y") else base + "th")
        out[-1] = (head + "-" if head and tail else "") + ordw
    if pct:
        out += ["per", "cent"]
    if cur:
        out.append(cur)
    return out


def n_ws_words(text):
    """script word count in the receipt convention: whitespace tokens, digit tokens expanded, hyphenated compounds one word"""
    n = 0
    for tok in text.split():
        if re.fullmatch(r"[—–-]+", tok):
            continue
        n += len(spoken(tok)) if re.search(r"\d", tok) else 1
    return n


def _vowel_groups(w):
    return len(re.findall(r"[aeiouy]+", w))


def syllables(word):
    out = 0
    for raw in re.split(r"[-\s]", word):
        letters = re.sub(r"[^A-Za-z]", "", raw)
        if 2 <= len(letters) <= 5 and letters.isupper():
            out += len(letters)          # an acronym is spoken letter by letter ("AI" is 2 syllables; the vowel-group count said 1)
            continue
        w = raw.lower()
        w = re.sub(r"[^a-z]", "", w)
        if not w:
            continue
        n = _vowel_groups(w)
        if w.endswith("e") and not w.endswith(("le", "ee", "ye")) and n > 1:
            n -= 1
        if re.search(r"(ed)$", w) and not re.search(r"[td]ed$", w) and n > 1:
            n -= 1
        out += max(1, n)
    return out


def _norm(w):
    return re.sub(r"[^a-z0-9']", "", w.lower().replace("’", "'"))


def _fold_names(w):
    return w


# ---------------------------------------------------------------- script <-> take alignment
def script_units(text):
    """list of dicts, one per whitespace token of the script: spoken words, syllables, end punctuation"""
    out = []
    for tok in text.split():
        if re.fullmatch(r"[—–-]+", tok):
            continue
        sp = spoken(tok)
        out.append({"tok": tok, "words": [_norm(x) for w in sp for x in w.split("-")], "n": len(sp) if re.search(r"\d", tok) else 1,
                    "syl": sum(syllables(x) for x in sp), "end": tok[-1] if tok[-1] in ".?!,;:" else ""})
    return out


def align_paragraphs(tokens, script_text):
    """Split the script into the take's paragraphs using the take's own tokens.
    tokens: words.json 'words' (word, start, end, paragraph). Returns {para: [script units]} by aligning the expanded ASR
    tokens against the expanded script with difflib (monotonic)."""
    units = script_units(script_text)
    sw, sidx = [], []
    for i, u in enumerate(units):
        for w in u["words"]:
            sw.append(w); sidx.append(i)
    tw, tpara = [], []
    for t in tokens:
        for w in [_norm(x) for s in spoken(t["word"]) for x in s.split("-")]:
            if w:
                tw.append(w); tpara.append(t["paragraph"])
    sm = difflib.SequenceMatcher(None, tw, sw, autojunk=False)
    anchor = {}
    for a, b, size in sm.get_matching_blocks():
        for k in range(size):
            anchor[a + k] = b + k
    # script position of each token-word (interpolate unmatched ones)
    pos, last = [], -1
    ks = sorted(anchor)
    for i in range(len(tw)):
        if i in anchor:
            last = anchor[i]; pos.append(last)
        else:
            nxt = next((anchor[k] for k in ks if k > i), len(sw) - 1)
            pos.append(min(max(last + 1, 0), nxt))
            last = pos[-1]
    paras, order = {}, []
    for p in tpara:
        if p not in order:
            order.append(p)
    bounds = {}
    for p in order:
        idx = [i for i, q in enumerate(tpara) if q == p]
        bounds[p] = (pos[idx[0]], pos[idx[-1]])
    # paragraph p owns script words from its first to the word before the next paragraph's first
    for n, p in enumerate(order):
        lo = bounds[p][0] if n else 0
        hi = bounds[order[n + 1]][0] if n + 1 < len(order) else len(sw)
        us = sorted({sidx[j] for j in range(lo, hi) if j < len(sidx)})
        paras[p] = [units[i] for i in us]
    return paras


# ---------------------------------------------------------------- audio
def read_wav(p):
    with wave.open(p) as w:
        sr, n, ch, sw = w.getframerate(), w.getnframes(), w.getnchannels(), w.getsampwidth()
        a = np.frombuffer(w.readframes(n), dtype=np.int16 if sw == 2 else np.int32).astype(np.float64)
    if ch > 1:
        a = a.reshape(-1, ch).mean(axis=1)
    return a / (32768.0 if sw == 2 else 2147483648.0), sr


def frame_db(a, sr, hop=0.010, win=0.025):
    h, w = int(sr * hop), int(sr * win)
    n = max(0, (len(a) - w) // h + 1)
    if n == 0:
        return np.zeros(0), hop
    c = np.concatenate([[0.0], np.cumsum(a * a)])
    idx = np.arange(n) * h
    ms = (c[idx + w] - c[idx]) / w
    return 10 * np.log10(ms + 1e-12), hop


def silent_runs(db, hop, lo, hi, thr, min_s):
    """[(start_s, end_s)] runs of frames below thr inside frames [lo, hi), at least min_s long"""
    runs, s = [], None
    for i in range(lo, hi):
        if db[i] < thr:
            if s is None:
                s = i
        elif s is not None:
            if (i - s) * hop >= min_s - 1e-9:
                runs.append((s * hop, i * hop))
            s = None
    if s is not None and (hi - s) * hop >= min_s - 1e-9:
        runs.append((s * hop, hi * hop))
    return runs


def para_features(toks, units, db, hop):
    """toks: this paragraph's ASR tokens; units: its script units; db: frame dB of the whole take"""
    t0, t1 = toks[0]["start"], toks[-1]["end"]
    span = t1 - t0
    n = sum(u["n"] for u in units) or len(toks)
    syl = sum(u["syl"] for u in units) or n
    lo, hi = int(t0 / hop), min(len(db), int(math.ceil(t1 / hop)))
    seg = db[lo:hi]
    f = {"n_words": n, "span_s": round(span, 3), "wpm_script": round(n / span * 60, 1), "tokens": len(toks),
         "wpm_tokens": round(len(toks) / span * 60, 1),
         "syl": syl, "syl_span": round(syl / span, 2)}
    if len(seg) < 5:
        return f
    thr = float(np.percentile(seg, 90)) - PAUSE_DB
    # strictly inside: ignore the first/last 80 ms (token edges are quantised to ~98 ms)
    runs = [r for r in silent_runs(db, hop, lo, hi, thr, PAUSE_MIN_S) if r[0] > t0 + 0.08 and r[1] < t1 - 0.08]
    pt = sum(b - a for a, b in runs)
    f["pauses"] = [[round(a, 2), round(b - a, 2)] for a, b in runs]
    f["n_pauses"] = len(runs)
    f["pause_total_s"] = round(pt, 2)
    f["pause_max_s"] = round(max([b - a for a, b in runs], default=0.0), 2)
    f["artic_wpm"] = round(n / max(span - pt, 0.5) * 60, 1)
    f["syl_rate"] = round(syl / max(span - pt, 0.5), 2)
    # longest unbroken run of speech
    edges = [t0] + [x for r in runs for x in r] + [t1]
    f["run_max_s"] = round(max(edges[i + 1] - edges[i] for i in range(0, len(edges), 2)), 2)
    # fastest 3 s window: distribute each script unit's words over the ASR tokens' times by token syllable weight
    w_tok = np.array([max(1, sum(syllables(x) for s in spoken(t["word"]) for x in s.split("-"))) for t in toks], float)
    w_tok = w_tok / w_tok.sum() * n
    best, W = 0.0, min(3.0, span)
    grid = np.arange(t0, t1 - W + 1e-9, 0.1) if span > W else np.array([t0])
    for g in grid:
        c = 0.0
        for t, w in zip(toks, w_tok):
            ov = min(g + W, t["end"]) - max(g, t["start"])
            if ov > 0 and t["end"] > t["start"]:
                c += w * ov / (t["end"] - t["start"])
        best = max(best, c / W)
    f["win3_wps"] = round(best, 2)
    f["win3_wpm"] = round(best * 60)
    # sentence-final boundaries inside the paragraph: low-energy gap length (>= 60 ms) around the token's end
    sp = []
    nsent = 0
    for t in toks[:-1]:
        if re.search(r"[.?!]['\"]?$", t["word"]):
            nsent += 1
            e = t["end"]
            l2, h2 = max(0, int((e - 0.15) / hop)), min(len(db), int((e + 0.45) / hop))
            rr = silent_runs(db, hop, l2, h2, thr, 0.06)
            sp.append(max([b - a for a, b in rr], default=0.0))
    f["sentences_inside"] = nsent
    f["sent_pause_ms"] = round(1000 * float(np.mean(sp)), 0) if sp else None
    f["sent_pause_min_ms"] = round(1000 * float(min(sp)), 0) if sp else None
    f["pause_per_sent"] = round(len(runs) / nsent, 2) if nsent else None
    # token-timing gaps (the take's own word timings): gap > 150 ms between consecutive tokens
    tg = [toks[i + 1]["start"] - toks[i]["end"] for i in range(len(toks) - 1)]
    f["token_gaps_150"] = sum(1 for g in tg if g > PAUSE_MIN_S)
    f["token_gap_max_s"] = round(max(tg, default=0.0), 2)
    return f


def _expanded(text_or_tokens):
    out = []
    for t in text_or_tokens:
        out += [w for w in (_norm(x) for s in spoken(t) for x in s.split("-")) if w]
    return out


def _receipt_units(d, tokens_by_para):
    """per-paragraph script units from the take's own P*.receipt.json, only when each paragraph's text matches that
    paragraph's tokens (difflib ratio >= 0.85): a receipt can describe an older take. None when any paragraph fails."""
    units = {}
    for p, toks in tokens_by_para.items():
        rp = os.path.join(d, p + ".receipt.json")
        if not os.path.exists(rp):
            return None
        text = json.load(open(rp)).get("text") or ""
        u = script_units(text)
        sw = [w for x in u for w in x["words"]]
        tw = _expanded([t["word"] for t in toks])
        if toks and difflib.SequenceMatcher(None, tw, sw, autojunk=False).ratio() < 0.85:
            return None
        units[p] = u
    return units


def analyse_take(d, sid, script_text=None):
    """d: directory holding <sid>.words.json and <sid>.wav. Script per paragraph: the take's own P*.receipt.json texts when
    they match the take's tokens, else the assembled receipt's full_script_text (or paragraphs.txt, or `script_text`)
    aligned to the take's tokens. A paragraph with NO tokens in words.json is reported as {"missing_tokens": True}
    (C26: P02 had no word timings and the next paragraph swallowed its script)."""
    words = json.load(open(os.path.join(d, sid + ".words.json")))["words"]
    a, sr = read_wav(os.path.join(d, sid + ".wav"))
    db, hop = frame_db(a, sr)
    per = {}
    for x in words:
        per.setdefault(x.get("paragraph"), []).append(x)
    units = None if script_text else _receipt_units(d, per)
    how = "receipts"
    if units is None:
        how = "aligned"
        if script_text is None:
            script_text = ""
            rp = os.path.join(d, sid + ".receipt.json")
            if os.path.exists(rp):
                script_text = json.load(open(rp)).get("full_script_text") or ""
            if not script_text and os.path.exists(os.path.join(d, "paragraphs.txt")):
                script_text = " ".join(open(os.path.join(d, "paragraphs.txt")).read().split())
        units = align_paragraphs(words, script_text)
    out = {}
    for p, toks in per.items():
        out[p] = para_features(toks, units.get(p, []), db, hop)
        out[p]["text"] = " ".join(u["tok"] for u in units.get(p, []))
        out[p]["script_from"] = how
        if how == "aligned" and out[p]["n_words"] > 1.5 * len(toks) + 6:
            out[p]["alignment_suspect"] = True
    # paragraphs the script has but the tokens lack
    if how == "receipts":
        for rp in sorted(glob_receipts(d)):
            p = os.path.basename(rp).split(".")[0]
            if p not in out:
                out[p] = {"missing_tokens": True, "n_words": n_ws_words(json.load(open(rp)).get("text") or "")}
    for p, f in out.items():
        if f.get("missing_tokens"):
            continue
        others = [g["wpm_script"] for q, g in out.items() if q != p and g.get("span_s", 0) >= 6]
        f["jump_wpm"] = round(f["wpm_script"] - float(np.median(others)), 1) if others else None
    return out


def glob_receipts(d):
    import glob
    return glob.glob(os.path.join(d, "P??.receipt.json"))


# ---------------------------------------------------------------- pauses that hold energy (local fallback for the listener)
def _voicing(x, sr):
    """best normalised autocorrelation in 70-400 Hz over 40 ms frames of x: ~0.6+ voiced speech, under 0.3 breath/noise"""
    n = int(0.04 * sr)
    best = []
    lo, hi = int(sr / 400), int(sr / 70)
    for s in range(0, max(1, len(x) - n - hi), max(1, n // 2)):
        f = x[s:s + n + hi]
        a = f[:n] - f[:n].mean()
        e0 = float(np.dot(a, a)) + 1e-12
        if e0 < 1e-9:
            continue
        c = np.correlate(a, f[:n + hi] - f[:n + hi].mean(), "full")[len(a) - 1 + lo: len(a) - 1 + hi]
        best.append(float(c.max() / e0))
    return min(1.0, float(np.median(best))) if best else 0.0


def _flatness(x):
    if len(x) < 256:
        return 1.0
    sp = np.abs(np.fft.rfft(x * np.hanning(len(x)))) ** 2 + 1e-18
    return float(np.exp(np.mean(np.log(sp))) / np.mean(sp))


GAP_SPEECH_DB = 24.0     # a frame is speech-like when within this of the paragraph's p90 level (same scale as PAUSE_DB)
GAP_STRAY_DB = 14.0      # a stray utterance is within this of the paragraph's p90 level; anything quieter is breath or noise
GAP_EDGE_S = 0.05        # a run starting/ending within this of the gap's edge touches the neighbouring word


def gap_profile(a, sr, db, hop, w0, w1, level):
    """Where in a gap (w0.end .. w1.start) is the energy, and is it a stray utterance or the neighbours' own tail/onset?
    level = the paragraph's p90 frame dB. Returns runs of speech-like frames (>= 60 ms) with timing, level, voicing and
    flatness, plus `kind`:
      empty    no speech-like run (room noise only)
      tail     a run that starts at the gap's start: the previous word's own tail (its ASR end time is early)
      onset    a run that ends at the gap's end: the next word's own onset (its ASR start time is late)
      stray    a voiced run (>= 120 ms) that touches neither word: an utterance the ASR did not time (false start, extra word)
      breath   an isolated run that is not voiced (autocorrelation under 0.35): breath or noise, never speech
    """
    g0, g1 = w0["end"], w1["start"]
    lo, hi = int(g0 / hop), int(g1 / hop)
    thr = level - GAP_SPEECH_DB
    runs = silent_runs(-db, hop, lo, hi, -thr, 0.02)   # frames with db > thr
    merged = []
    for s_, e_ in runs:                                  # a stop closure inside a word dips for <120 ms: one unit of speech
        if merged and s_ - merged[-1][1] < 0.12:
            merged[-1] = (merged[-1][0], e_)
        else:
            merged.append((s_, e_))
    runs = [(s_, e_) for s_, e_ in merged if e_ - s_ >= 0.06]
    out = []
    for s, e in runs:
        seg = a[int(s * sr): int(e * sr)]
        v = _voicing(seg, sr)
        out.append({"from": round(s - g0, 2), "len": round(e - s, 2), "db": round(float(np.mean(db[int(s / hop): int(e / hop)])), 1),
                    "voicing": round(min(v, 1.0), 2), "flat": round(_flatness(seg[: int(0.064 * sr)]), 3),
                    "touches_prev": s - g0 <= GAP_EDGE_S, "touches_next": g1 - e <= GAP_EDGE_S})
    for r in out:
        if r["touches_prev"]:
            r["cls"] = "tail"
        elif r["touches_next"]:
            r["cls"] = "onset"
        elif r["voicing"] >= 0.35 and r["len"] >= 0.12 and r["db"] >= level - GAP_STRAY_DB:
            r["cls"] = "stray"
        else:
            r["cls"] = "breath"
    cls = {r["cls"] for r in out}
    kind = next((k for k in ("stray", "tail", "onset", "breath") if k in cls), "empty")
    return {"kind": kind, "classes": sorted(cls), "runs": out, "gap_s": round(g1 - g0, 2)}
