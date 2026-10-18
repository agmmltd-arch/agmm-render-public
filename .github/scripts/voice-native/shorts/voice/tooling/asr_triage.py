#!/usr/bin/env python3
"""Second-opinion triage for voice paragraphs that failed the Mistral ASR word check but were kept anyway.

Root cause (24 Sep): gen_paragraphs.py retries a paragraph 3 times on an ASR mismatch, then KEEPS the last take
with asr_match=False, and run_short.py never blocks on it. 33 of the first 52 shorts carried at least one such
paragraph. Most are ASR spelling noise (license/licence, Ruiz/Ruis), but some are real: S11 says "KMP" for KNP.

For every paragraph with asr_match False, transcribe the take again with an independent model (faster-whisper
small.en, local, 2 threads) and compare both transcripts to the script after folding UK/US spelling variants:
  CLEAN    - either transcriber matches the script once spelling variants are folded
  SUSPECT  - both transcribers disagree with the script: the audio is probably wrong; regenerate the paragraph
Run with the yt-engine venv (has faster_whisper):
  ~/alfred/yt-engine/.venv/bin/python asr_triage.py <voice_dir> [IDs...]
Writes <voice_dir>/ASR-TRIAGE.json and prints the SUSPECT list.
"""
import glob, json, os, re, sys
os.environ.setdefault("HF_HUB_OFFLINE", "1")   # root 6 Oct: the hub update check hung on a dead CloudFront socket for 90 min while holding a heavy slot; the model is cached

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from asr_compare import compare  # noqa: E402

# ASR engines write US spellings; the scripts are British. Fold both sides to one form before comparing.
VARIANTS = {
    "ruiz": "ruis",   # root 6 Oct: Peter Ruis (John Lewis) is always transcribed "Ruiz" (S01)
    # root 6 Oct (voice-perf card): names that every engine spells the common way. Both sides are folded, so the key is the
    # engine's spelling and the value is the script's. Add a name here only after hearing the isolated clip say it right.
    "mcmillan": "mcmillon", "macmillan": "mcmillon",   # Doug McMillon (Walmart, S50): Mistral and whisper both write McMillan
    "reissida": "rhysida", "riced": "rhysida", "risida": "rhysida", "rizida": "rhysida",   # Rhysida ransomware group (S30): Mistral "Reissida", whisper "riced"
    "license": "licence", "licenses": "licences", "advisor": "adviser", "advisors": "advisers",
    "judgment": "judgement", "inquiries": "enquiries", "inquiry": "enquiry", "organizations": "organisations",
    "organization": "organisation", "organize": "organise", "organized": "organised", "analyze": "analyse",
    "bargain": "bargains",
    "analyzed": "analysed", "color": "colour", "behavior": "behaviour", "program": "programme",
    "center": "centre", "defense": "defence", "favorite": "favourite", "realize": "realise", "realized": "realised",
    "recognize": "recognise", "prioritize": "prioritise", "optimize": "optimise", "labor": "labour",
    "catalog": "catalogue", "traveling": "travelling", "canceled": "cancelled", "modeling": "modelling",
}


def fold(text):
    def rep(m):
        w = m.group(0); low = w.lower()
        return VARIANTS.get(low, w)
    return re.sub(r"[A-Za-z]+", rep, text)


def whisper_model():
    from faster_whisper import WhisperModel
    return WhisperModel("small.en", device="cpu", compute_type="int8", cpu_threads=2)


def main():
    vdir = os.path.abspath(sys.argv[1]); ids = sys.argv[2:]
    if not ids:
        ids = sorted(os.path.basename(d) for d in glob.glob(os.path.join(vdir, "[SC][0-9][0-9]"))
                     if os.path.exists(os.path.join(d, "RESULT.json")))
    model = None; out = {}
    for sid in ids:
        for rp in sorted(glob.glob(os.path.join(vdir, sid, "P*.receipt.json"))):
            r = json.load(open(rp))
            if r.get("asr_match") is not False:
                continue
            para = os.path.basename(rp).split(".")[0]
            wav = os.path.join(vdir, sid, para + ".wav")
            script = fold(r["text"])
            mistral_ok = compare(script, fold(r.get("asr_text") or ""))[0] if r.get("asr_text") else False
            if model is None:
                model = whisper_model()
            segs, _ = model.transcribe(wav, beam_size=5, language="en", vad_filter=False)
            wtext = " ".join(s.text.strip() for s in segs)
            wok, wdet = compare(script, fold(wtext))
            verdict = "CLEAN" if (mistral_ok or wok) else "SUSPECT"
            out.setdefault(sid, {})[para] = {"verdict": verdict, "script": r["text"], "mistral": r.get("asr_text"),
                                             "whisper": wtext, "whisper_detail": wdet if not wok else None,
                                             "mistral_detail": r.get("asr_compare_detail")}
            print("%s %s %s" % (sid, para, verdict), flush=True)
    # Claude 5 Oct: this used to overwrite ASR-TRIAGE.json with ONLY the shorts in this run, wiping every other short's
    # verdicts (S25 lost its CLEAN P01/P03 twice in one afternoon). Merge per short/paragraph under a lock, atomically.
    import fcntl, tempfile
    tp = os.path.join(vdir, "ASR-TRIAGE.json")
    with open(tp + ".lock", "w") as lk:
        fcntl.flock(lk, fcntl.LOCK_EX)
        try:
            merged = json.load(open(tp))
        except Exception:
            merged = {}
        for sid_, paras in out.items():
            merged.setdefault(sid_, {}).update(paras)
        fd, tmp = tempfile.mkstemp(dir=vdir, prefix=".asr-triage-")
        with os.fdopen(fd, "w") as fh:
            json.dump(merged, fh, indent=1, ensure_ascii=False)
        os.replace(tmp, tp)
    sus = [(s, p) for s, ps in out.items() for p, v in ps.items() if v["verdict"] == "SUSPECT"]
    print("\nSUSPECT %d of %d failed paragraphs:" % (len(sus), sum(len(v) for v in out.values())))
    for s, p in sus:
        v = out[s][p]
        print(" %s %s  whisper: %s" % (s, p, json.dumps(v["whisper_detail"])[:220]))


if __name__ == "__main__":
    main()
