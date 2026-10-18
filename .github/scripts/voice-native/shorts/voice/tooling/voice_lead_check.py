#!/usr/bin/env python3
"""Voice lead's release check for one voiced short (25 Sep). Run with the yt-engine venv (faster_whisper), through
kit/tools/heavy.py because it runs local whisper:
  kit/tools/heavy.py -- ~/alfred/yt-engine/.venv/bin/python voice_lead_check.py <voice_dir> ID [ID...]

Checks (each can fail; FAIL blocks release):
 1. RESULT.json status FINISHED; the selected take's 3-pass listening scores (naturalness, emphasis >= 6.5 as
    run_short's bar; flow, pace reported) and robotic votes (FAIL if 2+ of 3 say robotic).
 2. Pace, measured two ways and both compared with the approved pilots measured the same way:
    - span wpm = words / (last end - first start) * 60 on <ID>.words.json (gaps included). Pilots P1 / P2-v2 / P3-v2:
      158.5 / 161.4 / 161.6 -> band 156-166.
    - speaking wpm = the assembled receipt's wpm_speaking_final (gaps excluded). Pilots 164.9 / 172.0 / 169.8 -> band
      164-173. (A paragraph receipt's own wpm is NOT a pace measure.)
 3. Land-and-restart / hidden stutter (S04 lesson): every gap > 0.45 s between two words of ONE sentence (previous word
    has no . ? ! : ; ending) whose audio RMS inside the gap is above -30 dBFS -> FAIL (speech energy where no word is
    timed = a false start the ASR hid). Quiet mid-sentence gaps > 0.6 s are reported as WARN (a dead pause).
 4. Independent ASR: faster-whisper small.en on EVERY paragraph take, compared with the script (UK/US spelling folded,
    number values folded). Mistral's own per-paragraph check is also read. A paragraph passes if either transcriber
    matches; both missing -> FAIL (SUSPECT). Results for failed-Mistral paragraphs are MERGED into ASR-TRIAGE.json
    (read-modify-write for these IDs only; asr_triage.py rewrites the whole file and would wipe other shorts).
 5. Names: RESULT namecheck (isolated clips, listening model) must have no name missing or marked incorrect.
Writes <ID>/<ID>.voicelead.json and prints one line per short.

root 6 Oct (card voice-perf), items 2 and 3 are REPLACED, see voice_pace.py and buzz-gap/fix-voice-perf.md:
 - per-paragraph pace is now the SCRIPT's word count (digits spelled as spoken) over the take's own aligned span, every paragraph
   including one-line CTAs; the old ASR-token count undercounted number-heavy paragraphs and skipped paragraphs under 8 tokens.
   The 200 wpm FAIL is gone (it failed S52 P04, Sam's model, at 208 and missed C13 P03 at 210-216 by token count). FAIL needs
   syllable evidence: syllables/s of speech (pauses of 150 ms+ excluded) >= 6.6 AND >= 190 script wpm. Word rate alone is WARN.
 - a paragraph with script words but no word timings FAILS (C26 P02).
 - an energy-bearing mid-sentence gap is classified locally (no Gemini): a voiced run touching neither neighbour FAILS as a
   stray utterance; the previous word's tail / next word's onset (ASR timing) and breath are WARN. Gemini only if VOICE_GAP_GEMINI=1.
 - terminal pitch lift on one-line paragraphs (Praat, separate venv) is WARN only.
"""
import glob, json, os, re, subprocess, sys, wave
os.environ.setdefault("HF_HUB_OFFLINE", "1")   # root 6 Oct: the hub update check hung on a dead CloudFront socket for 90 min while holding a heavy slot; the model is cached
import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from asr_compare import compare  # noqa: E402
from asr_triage import fold  # noqa: E402
import voice_pace as vp  # noqa: E402  (script-word pace, local pace, pauses, gap profile; root 6 Oct voice-perf)
from prepare import voicelead_prerequisite_issues, voicelead_runtime_issue

ORD = {1: "first", 2: "second", 3: "third", 4: "fourth", 5: "fifth", 6: "sixth", 7: "seventh", 8: "eighth", 9: "ninth",
       10: "tenth", 11: "eleventh", 12: "twelfth", 13: "thirteenth", 14: "fourteenth", 15: "fifteenth", 16: "sixteenth",
       17: "seventeenth", 18: "eighteenth", 19: "nineteenth", 20: "twentieth", 30: "thirtieth"}


def ffold(s):
    # transcribers write "10th" where the script says "tenth": fold ordinals before the value comparator sees them
    s = re.sub(r"\b(\d{1,2})(st|nd|rd|th)\b", lambda m: ORD.get(int(m.group(1)), m.group(0)), s)
    s = s.replace("\u2019", "'")
    s = re.sub(r"(\w)'(s)?(?!\w)", lambda m: m.group(1) + ("s" if m.group(2) else ""), s)  # clinicians' = clinician's
    s = re.sub(r"\b(buy|bye)\b", "by", s, flags=re.I)  # homophones a transcriber cannot tell apart
    # "all of its hundred and eighty-five thousand" -> the value parser needs "one hundred"
    s = re.sub(r"\b(?!(?:one|two|three|four|five|six|seven|eight|nine|a)\b)([A-Za-z]+) hundred\b", r"\1 one hundred", s)
    return fold(s)


def toks(s):
    return re.findall(r"[a-z0-9]+", ffold(s).lower())


def real_stumble(v, text):
    # a listen's stumble vote counts only if what it HEARD departs from the script: a word the paragraph does not
    # contain, or a word said twice in a row where the script does not repeat it ("go, right go").
    if not v.get("stumble"):
        return False
    h, sc = toks(v.get("heard") or ""), toks(text)
    scs, pairs = set(sc), set(zip(sc, sc[1:]))
    extra = [w for w in h if w not in scs and not w.isdigit()]
    rep = [a for a, b in zip(h, h[1:]) if a == b and (a, b) not in pairs]
    return bool(extra or rep)


WATCH = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))),
                     "tooling", "gemini_watch.py")
GAP_PROMPT = ("""You are checking a short excerpt of a voice-over for delivery faults. The excerpt comes from this script
paragraph: "{text}". The excerpt should contain only: "... {w0} ... {w1} ..." and the words between them in the script.
Listen closely. Does the speaker stumble anywhere in the excerpt: repeat a word, restart a phrase, say a word that is
not in the script, or make a glitch or non-speech sound (a breath is fine)? Return ONLY JSON:
{{"stumble": true|false, "heard": "<exactly the words you hear>", "problem": "<short>"}}""")


def gap_listen(a, sr, w0, w1, text, tmpdir):
    s0 = max(0.0, w0["start"] - 0.5); s1 = w1["end"] + 0.5
    wav = os.path.join(tmpdir, "gap.wav"); mp4 = os.path.join(tmpdir, "gap.mp4")
    clip = (a[int(s0 * sr): int(s1 * sr)] * 32767).astype(np.int16)
    with wave.open(wav, "w") as w:
        w.setnchannels(1); w.setsampwidth(2); w.setframerate(sr); w.writeframes(clip.tobytes())
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", "color=black:s=320x240:r=5", "-i", wav, "-shortest",
                    "-c:v", "libx264", "-x264-params", "threads=2", "-tune", "stillimage", "-c:a", "aac", "-b:a", "128k", mp4],
                   check=True)
    votes = []
    if os.environ.get("VOICE_GAP_GEMINI") != "1":   # root 6 Oct: Gemini quota is gone; the local gap_profile decides (opt-in only)
        return {"listens": [], "stumble": False, "heard_by": 0}
    for _ in range(2):  # two listens; with whisper's words-in-the-gap, one stumble vote fails it
        # root 6 Oct: with the Gemini quota gone this call hung with no timeout, holding a heavy slot until heavy.py's
        # 30-min stop and blocking every voice check in the queue. Two minutes, then the listener counts as unavailable.
        try:
            r = subprocess.run(["python3", WATCH, mp4, GAP_PROMPT.format(text=text, w0=w0["word"], w1=w1["word"]), "--json"],
                               capture_output=True, text=True, timeout=120)
            votes.append(json.loads(r.stdout))
        except Exception:
            votes.append(None)
            break   # an unavailable listener will not answer the second listen either
    got = [v for v in votes if isinstance(v, dict)]
    # whisper already heard words inside this pause, so ONE listen hearing a stumble makes two signals of three: FAIL
    return {"listens": got, "stumble": any(real_stumble(v, text) for v in got), "heard_by": len(got)}


def whisper_text(path_or_array):
    segs, _ = model().transcribe(path_or_array, beam_size=5, language="en", vad_filter=False)
    return " ".join(s.text.strip() for s in segs).strip()


PACE_SPAN = (156.0, 166.0)
SYL_FAIL, SYL_WARN = 6.7, 6.5      # syllables per second of speech (pauses >= 150 ms excluded); approved max 6.48 (acronyms spelled letter by letter), known-bad 6.99-7.19
CTA_FAIL_WPM, CTA_WARN_WPM = 210.0, 185.0   # the closing one-liner (<= 16 words), script wpm. 7 approved CTAs: 120-195 wpm; S46's returned CTA 223; S50's old one 196 (indistinguishable from approved S37's 195, so only WARN)
WPM_FAIL_MIN, WPM_WARN = 190.0, 210.0   # script wpm: FAIL also needs this much; WARN above the approved max of 208
PITCH_PY = os.path.expanduser("~/alfred/venvs/pitch/bin/python")
PITCH_LIFT_WARN = 4.0              # semitones the last voiced frame sits above the paragraph median (S02 old CTA 6.8; its fix -7.6)
PACE_SPEAK = (164.0, 173.0)
BAR = 6.5
_model = None


def model():
    global _model
    if _model is None:
        from faster_whisper import WhisperModel
        _model = WhisperModel("small.en", device="cpu", compute_type="int8", cpu_threads=2)
    return _model


def read_wav(p):
    with wave.open(p) as w:
        sr, n, ch, sw = w.getframerate(), w.getnframes(), w.getnchannels(), w.getsampwidth()
        a = np.frombuffer(w.readframes(n), dtype=np.int16 if sw == 2 else np.int32).astype(np.float64)
    if ch > 1:
        a = a.reshape(-1, ch).mean(axis=1)
    return a / (32768.0 if sw == 2 else 2147483648.0), sr


def rms_db(a):
    if len(a) == 0:
        return -120.0
    return 20 * np.log10(np.sqrt(np.mean(a * a)) + 1e-12)


def pace_findings(pace):
    """FAIL/WARN lines for the per-paragraph pace features of vp.analyse_take(). Thresholds and their evidence: see the constants."""
    fails, warns = [], []
    real = [q for q in sorted(pace) if not pace[q].get("missing_tokens")]
    cta_p = real[-1] if real and pace[real[-1]].get("n_words", 99) <= 16 else None
    for p, f in sorted(pace.items()):
        if f.get("missing_tokens"):
            fails.append("%s has %d script words and NO word timings in words.json (its script was not aligned to audio)" % (p, f.get("n_words", 0)))
            continue
        if f.get("alignment_suspect"):
            warns.append("%s script alignment suspect (%d script words vs %d tokens): pace figures unreliable" % (p, f["n_words"], f["tokens"]))
        wpm, sr_, span = f["wpm_script"], f.get("syl_rate"), f["span_s"]
        if p == cta_p:
            # the CTA is under 4 s, so the paragraph rule never applies; it has its own bar, calibrated on the approved CTAs (report
            # fix-voice-perf.md, section 8). Sam's model is S52's "Follow for the next real story." at 120 wpm over 3.0 s.
            ctag = "%s (the CTA) %d words in %.2f s = %d script wpm, %.2f syl/s" % (p, f["n_words"], span, round(wpm), sr_ or 0)
            if wpm >= CTA_FAIL_WPM:
                fails.append("%s: hurried, above every approved CTA (max 195 wpm); say it in 2.5 s or more" % ctag)
            elif wpm >= CTA_WARN_WPM:
                warns.append("%s: at the top of the approved CTAs (195 wpm); the S52 model is 120 wpm" % ctag)
            continue
        tag = "%s %d script wpm (%d by ASR tokens), %.2f syl/s speaking, %d pauses" % (p, round(wpm), round(f["wpm_tokens"]), sr_ or 0, f.get("n_pauses") or 0)
        # labelled evidence (n is tiny; report fix-voice-perf.md): Sam's bad C13 P03 = 210/216 wpm, 6.99/7.19 syl/s; his model S52 P04 =
        # 208 wpm, 5.37 syl/s; 43 approved paragraphs (S52 S36 S37 S83 S67 S45 S41) top out at 6.48 syl/s and 208 wpm.
        if sr_ is not None and sr_ >= SYL_FAIL and wpm >= WPM_FAIL_MIN and span >= 4.0:
            fails.append("%s: rushed (known-bad C13 P03 was 6.99-7.19 syl/s; the 43 approved paragraphs top out at 6.48)" % tag)
        elif (sr_ is not None and sr_ >= SYL_WARN) or wpm >= WPM_WARN:
            warns.append("%s: fast in %s" % (tag, "words only" if (sr_ or 0) < SYL_WARN else "syllables"))
    return fails, warns


def check(vdir, sid):
    issues = voicelead_prerequisite_issues(vdir, sid)
    if issues:
        raise RuntimeError("VOICE_PREREQUISITE_HOLD: " + "; ".join(issues))
    if why := voicelead_runtime_issue():
        raise RuntimeError(why)
    d = os.path.join(vdir, sid)
    out = {"id": sid, "fails": [], "warns": []}
    res = json.load(open(os.path.join(d, "RESULT.json")))
    fin = res.get("final") or {}
    out["result_status"] = res.get("status")
    out["scores"] = {k: fin.get(k) for k in ("naturalness", "flow", "pace", "emphasis", "robotic_votes")}
    # 13 Oct 2026 LOCAL MODE: a short voiced through the Voxtral WEB route (Mistral TTS/ASR API 402, Gemini dead) has a RESULT.json from
    # run_short.py --from-existing (status FINISHED_LOCAL_CHECKS_PASS, listening_review UNJUDGED). The listening scores do not exist, so
    # that check is reported as UNJUDGED (never as a pass); every other check below still runs and can still fail.
    local = str(res.get("status", "")).startswith("FINISHED_LOCAL") or res.get("listening_review") == "UNJUDGED"
    out["listening_review"] = "UNJUDGED (local mode: no Gemini)" if local else "judged"
    if local:
        if res.get("status") != "FINISHED_LOCAL_CHECKS_PASS":
            out["fails"].append("RESULT status %s" % res.get("status"))
    else:
        if res.get("status") != "FINISHED":
            out["fails"].append("RESULT status %s" % res.get("status"))
        if (fin.get("naturalness") or 0) < BAR or (fin.get("emphasis") or 0) < BAR:
            out["fails"].append("listening scores under %.1f: nat %s emph %s" % (BAR, fin.get("naturalness"), fin.get("emphasis")))
        if sum(1 for v in (fin.get("robotic_votes") or []) if v) >= 2:
            out["fails"].append("robotic cadence: %s" % fin.get("robotic_votes"))

    words = json.load(open(os.path.join(d, sid + ".words.json")))["words"]
    span = words[-1]["end"] - words[0]["start"]
    wpm = round(len(words) / span * 60, 1)
    out["pace_wpm_span"] = wpm
    out["duration_s"] = round(words[-1]["end"], 2)
    rc = json.load(open(os.path.join(d, sid + ".receipt.json")))
    speak = rc.get("wpm_speaking_final")
    out["pace_wpm_speaking"] = speak
    # speaking wpm is the programme's canonical pace (craft standard 165-172; pilots 164.9-172.0) and is the hard gate.
    # Span pace is reported against the pilots' finals; up to 4 wpm beyond their band is a WARN (assemble lands on the
    # band's upper edge with shorter gaps than the pilots had), further out FAILS.
    # root 6 Oct: Sam rejected FAST delivery; re-voicing rushed paragraphs leaves some takes a little slow overall
    # (S73 149.8, C13 151.5). Fast side unchanged; the slow side fails only below 145 (warns 145-156).
    if wpm > PACE_SPAN[1] + 4 or wpm < 145:
        out["fails"].append("span pace %.1f wpm far outside pilots' %s" % (wpm, PACE_SPAN))
    elif not (PACE_SPAN[0] <= wpm <= PACE_SPAN[1]):
        out["warns"].append("span pace %.1f wpm just outside pilots' %s" % (wpm, PACE_SPAN))
    if speak is None or not (PACE_SPEAK[0] <= speak <= PACE_SPEAK[1]):
        out["fails"].append("speaking pace %s wpm outside pilots' %s" % (speak, PACE_SPEAK))

    # per-paragraph pace on the assembled take (root 6 Oct, voice-perf): SCRIPT words (digits spelled as spoken) over the span of the
    # take's own word timings, every paragraph, one-line CTAs included. See voice_pace.py for the definitions.
    per = {}
    for x in words:
        per.setdefault(x.get("paragraph"), []).append(x)
    pace = vp.analyse_take(d, sid)
    out["paragraph_pace"] = {p: {k: v for k, v in f.items() if k not in ("pauses",)} for p, f in pace.items()}
    out["paragraph_wpm"] = {p: round(f["wpm_script"]) for p, f in pace.items() if "wpm_script" in f}
    out["paragraph_wpm_tokens"] = {p: round(len(v) / (v[-1]["end"] - v[0]["start"]) * 60) for p, v in per.items() if len(v) >= 2}
    # Sam, 6 Oct: the standalone CTA "Follow, we track this every week." comes out pitched up and wonky in every short that
    # uses it (S02 and others). Banned: the CTA is a full sentence spoken in flow.
    script_txt = " ".join(str(x.get("word") or x.get("text") or "") for x in words).lower()
    if "we track this every week" in script_txt:
        out["fails"].append("banned CTA 'Follow, we track this every week.' (Sam: pitches up, wonky); use a full-sentence CTA")
    pf, pw = pace_findings(pace)
    out["fails"] += pf
    out["warns"] += pw

    # terminal pitch lift on one-line paragraphs (the CTA): WARN only. One confirmed-bad take (S02 old CTA, +6.8 st) ranks first of 43,
    # the other 11 old-CTA takes are unconfirmed, so this cannot be a FAIL (report fix-voice-perf.md).
    short = [[p, per[p][0]["start"], per[p][-1]["end"]] for p, f in pace.items()
             if not f.get("missing_tokens") and f.get("n_words", 99) <= 12 and p in per]
    out["pitch"] = {}
    if short and os.path.exists(PITCH_PY):
        try:
            r = subprocess.run(["nice", "-n", "15", PITCH_PY, os.path.join(os.path.dirname(os.path.abspath(__file__)), "voice_pitch.py"),
                                os.path.join(d, sid + ".wav"), json.dumps(short)], capture_output=True, text=True, timeout=120)
            out["pitch"] = json.loads(r.stdout)
        except Exception as e:
            out["pitch"] = {"error": repr(e)[:120]}
        for p_, f_ in (out["pitch"] or {}).items():
            if isinstance(f_, dict) and (f_.get("last_minus_med") or 0) >= PITCH_LIFT_WARN:
                out["warns"].append("%s ends %.1f semitones above its own median pitch (slope %s st/s): a lifted last word, the S02 CTA signature (WARN only, n=1 confirmed)"
                                    % (p_, f_["last_minus_med"], f_.get("final_slope_st_s")))

    a, sr = read_wav(os.path.join(d, sid + ".wav"))
    paratext = {"P%02d" % (i + 1): x.strip() for i, x in
                enumerate(open(os.path.join(d, "paragraphs.txt")).read().strip().split("\n\n"))}
    gaps = []
    fdb, fhop = vp.frame_db(a, sr)
    lvl = {}
    for p_, v_ in per.items():
        sg = fdb[int(v_[0]["start"] / fhop): int(v_[-1]["end"] / fhop)]
        lvl[p_] = float(np.percentile(sg, 90)) if len(sg) else -15.0
    for w0, w1 in zip(words, words[1:]):
        g = w1["start"] - w0["end"]
        if g <= 0.45 or re.search(r"[.?!:;]['\"]?$", w0["word"]) or w0.get("paragraph") != w1.get("paragraph"):
            continue
        seg = a[int((w0["end"] + 0.05) * sr): int((w1["start"] - 0.05) * sr)]
        db = float(round(rms_db(seg), 1))
        rec = {"after": w0["word"], "before": w1["word"], "at": round(w0["end"], 2), "gap_s": round(g, 2), "rms_db": db}
        # root 6 Oct: local gap profile replaces the Gemini listen (quota gone). Where is the energy: the previous word's own tail,
        # the next word's onset (both = the ASR timed that word short or late), breath, or a voiced run touching neither (stray).
        prof = vp.gap_profile(a, sr, fdb, fhop, w0, w1, lvl.get(w0.get("paragraph"), -15.0))
        rec["profile"] = {"kind": prof["kind"], "runs": [{k: r[k] for k in ("from", "len", "db", "voicing", "cls")} for r in prof["runs"]]}
        isnum = bool(re.search(r"\d", w0["word"]))
        if prof["kind"] == "stray":
            r0 = next(r for r in prof["runs"] if r["cls"] == "stray")
            out["fails"].append("stray utterance inside a pause: voiced run %.2f s at +%.2f s into the %.2f s gap, %.1f dB, touching neither word %s"
                                % (r0["len"], r0["from"], g, r0["db"], rec))
        elif db > -30:
            # energy inside a pause: breath, or a false start the ASR hid (S04). Transcribe the span on its own.
            clip = a[int((w0["end"] + 0.02) * sr): int((w1["start"] - 0.02) * sr)].astype(np.float32)
            if sr != 16000:
                idx = np.linspace(0, len(clip) - 1, int(len(clip) * 16000 / sr)).astype(int)
                clip = clip[idx]
            heard = whisper_text(np.concatenate([np.zeros(8000, np.float32), clip, np.zeros(8000, np.float32)]))
            rec["heard_in_gap"] = heard
            tl = [r for r in prof["runs"] if r["cls"] in ("tail", "onset")]
            if tl:
                what = ("number token '%s' timed %.2f s short (its own spoken words continue after the ASR end)" % (w0["word"], max(r["len"] for r in tl)) if isnum and tl[0]["cls"] == "tail"
                        else "previous word's tail" if tl[0]["cls"] == "tail" else "next word's onset")
                out["warns"].append("ASR word timing: the gap holds the %s, %.2f s of speech, whisper heard %r; no stray utterance %s" % (what, max(r["len"] for r in tl), heard, rec))
            elif re.search(r"[A-Za-z]", heard):
                gl = gap_listen(a, sr, w0, w1, paratext.get(w0.get("paragraph"), ""), d)
                rec["listen"] = gl
                if gl["stumble"]:
                    out["fails"].append("stumble inside a pause (whisper + a listen) %s" % rec)
                else:
                    out["warns"].append("words heard inside a pause but no voiced run of its own (breath/noise level) %s" % rec)
            else:
                out["warns"].append("breath/noise inside a pause, no words heard %s" % rec)
        elif g > 0.6 and not w0["word"].endswith(","):
            out["warns"].append("quiet mid-sentence pause %s" % rec)
        gaps.append(rec)
    out["mid_sentence_gaps"] = gaps

    tri_p = os.path.join(vdir, "ASR-TRIAGE.json")
    paras = {}
    for rp in sorted(glob.glob(os.path.join(d, "P*.receipt.json"))):
        r = json.load(open(rp))
        p = os.path.basename(rp).split(".")[0]
        script = ffold(r["text"])
        wtext = whisper_text(os.path.join(d, p + ".wav"))
        wok, wdet = compare(script, ffold(wtext))
        mok = bool(r.get("asr_match")) or (bool(r.get("asr_text")) and compare(script, ffold(r["asr_text"]))[0])
        paras[p] = {"mistral_match": mok, "mistral_raw_match": r.get("asr_match"), "whisper_match": wok, "whisper": wtext,
                    "whisper_detail": None if wok else wdet}
        if not (mok or wok):
            # root 6 Oct: a reviewer's written CLEAN ruling on THIS exact take (sha-bound in ASR-TRIAGE.json, by != the machine)
            # downgrades the miss to a WARN; a re-voice changes the sha and the ruling no longer applies.
            import hashlib as _h
            _wp = os.path.join(d, p + ".wav")
            _take = _h.sha256(open(_wp, "rb").read()).hexdigest()[:16] if os.path.exists(_wp) else None
            _man = (json.load(open(tri_p)) if os.path.exists(tri_p) else {}).get(sid, {}).get(p) or {}
            if _take and _man.get("verdict") == "CLEAN" and _man.get("take_sha") == _take and \
                    _man.get("by") not in (None, "voice_lead_check") and _man.get("why"):
                out["warns"].append("%s both transcribers miss, but %s ruled this take CLEAN: %s" % (p, _man["by"], _man["why"][:160]))
            else:
                out["fails"].append("%s SUSPECT: both transcribers miss the script (%s)" % (p, json.dumps(wdet)[:160]))
        elif not wok:
            out["warns"].append("%s whisper differs, Mistral matches (%s)" % (p, json.dumps(wdet)[:160]))
    out["paragraph_asr"] = paras
    # merge triage verdicts for Mistral-failed paragraphs (the queue reads these)
    # root 5 Oct 19:05: a verdict now carries the sha of the take it judged. A stale machine SUSPECT on a superseded take
    # (S103 P03 after m5's re-voice) held the render; an entry for a different take is replaced, and a machine SUSPECT is
    # cleared by a real match. Manual verdicts on the SAME take are never touched.
    import hashlib, triage_store
    tri = triage_store.read(vdir)
    upd = {}
    for p, v in paras.items():
        if v["mistral_raw_match"] is not False:
            continue
        wavp = os.path.join(d, p + ".wav")
        take = hashlib.sha256(open(wavp, "rb").read()).hexdigest()[:16] if os.path.exists(wavp) else None
        cur = tri.get(sid, {}).get(p)
        ok = bool(v["whisper_match"] or v["mistral_match"])
        entry = {"verdict": "CLEAN" if ok else "SUSPECT",
                 "why": "folded comparison (ordinals, possessives, homophones)" if v["mistral_match"] else None,
                 "whisper": v["whisper"], "whisper_detail": v["whisper_detail"], "by": "voice_lead_check", "take_sha": take}
        if cur is None:
            upd[p] = entry
        elif cur.get("take_sha") and take and cur["take_sha"] != take:
            upd[p] = entry                                          # judged a different take
        elif ok and cur.get("verdict") == "SUSPECT" and cur.get("by") == "voice_lead_check":
            upd[p] = entry                                          # a real match clears a machine SUSPECT
    if upd:
        triage_store.update(vdir, {sid: upd})

    nc = res.get("namecheck_summary") or {}
    if local and not nc.get("expected"):   # local mode: the names to check are names.txt; the isolated-clip whisper pass below decides
        nc = {"expected": [l.strip() for l in open(os.path.join(d, "names.txt")) if l.strip()]}
    # Handle case where verdicts might be strings instead of dicts
    verdicts = nc.get("verdicts") or []
    if verdicts and isinstance(verdicts[0], str):
        # If verdicts are strings, treat non-"correct" as bad
        bad = [{"expected": "", "heard": "", "note": ""} for v in verdicts if v != "correct"]
    else:
        # Original logic expecting dicts
        bad = [v for v in verdicts if v.get("correct") is False]
    flagged = set(nc.get("missing_from_audio") or []) | {v.get("expected") for v in bad}
    # second opinion on every name: cut the name from the assembled take by its word timings (+/-0.35 s) and let
    # whisper transcribe that isolated clip. A name the listening model flagged passes only if whisper hears it here.
    iso = {}
    # root 6 Oct: fold spelling variants on both sides (S01 "Peter Ruis" is always transcribed "Ruiz", same sound)
    toks = [re.sub(r"[^a-z0-9]", "", fold(x["word"]).lower().replace("’", "'").split("'")[0]) for x in words]
    for name in [l.strip() for l in open(os.path.join(d, "names.txt")) if l.strip()]:
        nt = [re.sub(r"[^a-z0-9]", "", fold(x).lower()) for x in name.split()]
        hit = next((i for i in range(len(toks) - len(nt) + 1) if toks[i:i + len(nt)] == nt), None)
        if hit is None:
            iso[name] = {"found_in_timings": False}; continue
        s0 = max(0.0, words[hit]["start"] - 0.35); s1 = words[hit + len(nt) - 1]["end"] + 0.35
        clip = a[int(s0 * sr): int(s1 * sr)].astype(np.float32)
        if sr != 16000:
            idx = np.linspace(0, len(clip) - 1, int(len(clip) * 16000 / sr)).astype(int); clip = clip[idx]
        heard = whisper_text(np.concatenate([np.zeros(8000, np.float32), clip, np.zeros(8000, np.float32)]))
        hn = re.sub(r"[^a-z0-9 ]", "", fold(heard).lower())
        ok = all(x in hn.replace(" ", "") or x in hn for x in nt) or name.lower().replace(" ", "") in hn.replace(" ", "")
        iso[name] = {"at": round(s0, 2), "heard": heard, "ok": ok, "para": words[hit].get("paragraph")}
    out["names"] = {"expected": nc.get("expected"), "listening_flagged": sorted(x for x in flagged if x),
                    "listening_incorrect": [(v.get("expected"), v.get("heard"), v.get("note")) for v in bad],
                    "isolated_whisper": iso}
    for name, v in iso.items():
        if not v.get("ok"):
            # root 6 Oct (S30 "Rhysida"): small.en cannot transcribe a rare name even from the right audio ("Vice de Clendid"), so when the
            # listening namecheck flagged it the FAIL used to rest on whisper alone. A TAKE-BOUND third opinion overrides: asr_listen
            # (Gemini, 2 runs) judged this paragraph CLEAN with this name among its targets, and the triage entry's take_sha is the
            # sha of the paragraph wav the take was built from.
            third = None
            try:
                e_ = tri.get(sid, {}).get(v.get("para"), {}) or {}
                wavp_ = os.path.join(d, str(v.get("para")) + ".wav")
                sha_ = hashlib.sha256(open(wavp_, "rb").read()).hexdigest()[:16] if os.path.exists(wavp_) else None
                lt_ = e_.get("listen") or {}
                if lt_.get("verdict") == "CLEAN" and e_.get("take_sha") and e_.get("take_sha") == sha_ and \
                        any(fold(str(t_)).lower() == fold(name).lower() or fold(name).lower() in fold(str(t_)).lower() for t_ in (lt_.get("targets") or [])):
                    third = "asr_listen CLEAN on this exact take (%s)" % e_.get("by")
            except Exception:
                third = None
            _NUMW = {"zero","one","two","three","four","five","six","seven","eight","nine","ten","eleven","twelve","thirteen",
                     "fourteen","fifteen","sixteen","seventeen","eighteen","nineteen","twenty","thirty","forty","fifty","sixty",
                     "seventy","eighty","ninety","hundred","thousand","million","billion","half","quarter","per","cent","percent"}
            _toks = [t for t in re.split(r"[\s\-]+", str(name).lower()) if t]
            if _toks and all(t in _NUMW for t in _toks):
                # root 7 Oct (S27 "Forty-six"): a sentence-initial number word is not a name; pace/ASR checks cover numbers.
                out["warns"].append("name %s: a number word, not a name (namecheck flag ignored; whisper heard %r)" % (name, v.get("heard")))
                continue
            if third and name in flagged:
                out["warns"].append("name %s: namecheck flagged it and whisper heard %r, but %s: not failed" % (name, v.get("heard"), third))
            elif name in flagged:
                out["fails"].append("name %s: listening model flagged it and whisper on the isolated clip heard %r"
                                    % (name, v.get("heard")))
            else:
                out["warns"].append("name %s: isolated whisper heard %r (listening model OK)" % (name, v.get("heard")))
        elif name in flagged:
            out["warns"].append("name %s: listening model flagged it but the isolated clip reads %r (clip mislabel)"
                                % (name, v.get("heard")))
    if not nc.get("expected"):
        out["fails"].append("name check did not run")
    out["verdict"] = "PASS" if not out["fails"] else "FAIL"
    json.dump(out, open(os.path.join(d, sid + ".voicelead.json"), "w"), indent=1, ensure_ascii=False)
    return out


def pace_only(d, sid):
    """pace verdict for ANY assembled take directory (e.g. an archived superseded-* take that has no RESULT.json): no whisper."""
    if why := voicelead_runtime_issue():
        raise RuntimeError(why)
    pace = vp.analyse_take(d, sid)
    f, w = pace_findings(pace)
    fp = [(v.get("syl_rate") or 0, q, v) for q, v in pace.items() if "wpm_script" in v]
    print(sid, "PACE-" + ("FAIL" if f else "PASS"), "| fails:", f, "| warns:", len(w))
    for q, v in sorted(pace.items()):
        if "wpm_script" in v:
            print("   %s %3d script wpm  %.2f syl/s speaking  win3 %d wpm  pauses %d  sentence-pause %s ms  jump %s" % (
                q, round(v["wpm_script"]), v.get("syl_rate") or 0, v.get("win3_wpm") or 0, v.get("n_pauses") or 0, v.get("sent_pause_ms"), v.get("jump_wpm")))
    return f, w


def main():
    if len(sys.argv) > 1 and sys.argv[1] == "--pace-only":
        pace_only(os.path.abspath(sys.argv[2]), sys.argv[3]); return
    vdir = os.path.abspath(sys.argv[1])
    failed = False
    for sid in sys.argv[2:]:
        try:
            o = check(vdir, sid)
        except Exception as e:  # a short that is not voiced yet
            failed = True
            import traceback
            print(sid, "ERROR", repr(e)[:200])
            traceback.print_exc()
            continue
        failed = failed or o["verdict"] != "PASS"
        pp = [(f.get("syl_rate") or 0, q, f) for q, f in o.get("paragraph_pace", {}).items() if "wpm_script" in f]
        worst = max(pp, key=lambda t: t[0]) if pp else None
        print(sid, o["verdict"], "wpm span/speaking", o["pace_wpm_span"], o["pace_wpm_speaking"], "scores", o["scores"], "| fails:", o["fails"],
              "| warns:", len(o["warns"]),
              ("| fastest para %s %d script wpm %.2f syl/s" % (worst[1], round(worst[2]["wpm_script"]), worst[0])) if worst else "", flush=True)
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
