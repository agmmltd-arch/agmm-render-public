#!/usr/bin/env python3
"""synth.py - free-engine TTS on Actions: paragraphs in (private request), takes + receipts + words + speaker-similarity numbers out (voice-free 20 Oct 2026).

  synth.py --engine chatterbox --request REQUEST.json --private PRIVATE_CHECKOUT --out OUT_DIR

REQUEST.json (lives in the PRIVATE repo, never in this public one: script text must not reach public logs):
  {"label": str, "id": "S95", "ref": "voice-free/ref/....wav", "ref_sims": [paths], "takes": 2, "params": {...},
   "paragraphs": [{"key": "P01", "text": "..."}], "baseline": {"P01": "path of the Mistral PASS paragraph wav"}}
Per paragraph and take: sentence-chunked synthesis (a chunk is 1-2 sentences, the pause between chunks is explicit), 24 kHz mono PCM16, faster-whisper
word timings in the Mistral response shape, the native asr_compare verdict, native and span wpm, render seconds, resemblyzer cosine to Sam's reference
set and to the baseline take. Output files: <key>.t<k>.wav / .words.json / .receipt.json and results.json (numbers only).
"""
import argparse, datetime as dt, json, os, re, sys, time
import numpy as np
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import vf_common as C


class Chatterbox:
    name = "chatterbox"
    version = "chatterbox-tts 0.1.7 (MIT) + ResembleAI/chatterbox weights"

    def __init__(self, ref, params):
        import torch
        from chatterbox.tts import ChatterboxTTS
        torch.set_num_threads(os.cpu_count() or 4)
        self.torch = torch
        self.p = params
        t = time.time()
        self.m = ChatterboxTTS.from_pretrained(device="cpu")
        self.load_s = round(time.time() - t, 1)
        self.m.prepare_conditionals(ref, exaggeration=params.get("exaggeration", 0.5))
        self.sr = self.m.sr

    def synth(self, text, seed):
        self.torch.manual_seed(seed)
        p = self.p
        wav = self.m.generate(text, repetition_penalty=p.get("repetition_penalty", 1.2), min_p=p.get("min_p", 0.05), top_p=p.get("top_p", 1.0),
                              exaggeration=p.get("exaggeration", 0.5), cfg_weight=p.get("cfg_weight", 0.5), temperature=p.get("temperature", 0.8))
        return wav.squeeze(0).cpu().numpy().astype("float32")


class FishSpeech:
    """Not wired. fish_gate.py refuses the only Fish weights that fit a CPU runner (openaudio-s1-mini is CC-BY-NC-SA-4.0 and gated; S2-Pro is Research
    Licence; Drama 3 is 35B). Fill this in only after Sam supplies licensed weights and an HF token (secret HF_TOKEN_FISH)."""
    name = "fish"
    version = "unwired"

    def __init__(self, ref, params):
        raise SystemExit("fish engine not wired: no commercially licensed Fish weights are runnable on a CPU runner (see fish_gate.py)")


ENGINES = {"chatterbox": Chatterbox, "fish": FishSpeech}


def chunks(text, max_words):
    sents = [s.strip() for s in re.split(r"(?<=[.!?])\s+", text.strip()) if s.strip()]
    out, cur = [], []
    for s in sents:
        if cur and len(" ".join(cur + [s]).split()) > max_words:
            out.append(" ".join(cur)); cur = [s]
        else:
            cur.append(s)
    if cur:
        out.append(" ".join(cur))
    return out


def trim(a, sr, floor_db=-42.0, keep=0.04):
    if len(a) == 0:
        return a
    w = int(0.01 * sr)
    n = len(a) // w
    if n < 3:
        return a
    rms = 20 * np.log10(np.sqrt((a[:n * w].reshape(n, w) ** 2).mean(axis=1)) + 1e-9)
    idx = np.where(rms > floor_db)[0]
    if len(idx) == 0:
        return a
    s = max(0, idx[0] * w - int(keep * sr)); e = min(len(a), (idx[-1] + 1) * w + int(keep * sr))
    return a[s:e]


DIGITS = {'zero': '0', 'oh': '0', 'one': '1', 'two': '2', 'three': '3', 'four': '4', 'five': '5', 'six': '6', 'seven': '7', 'eight': '8', 'nine': '9'}


def soft_match(text, asr_text):
    """Same two comparator false-negatives api_queue.soft_match accepts (spacing only; a spelled digit run written as digits)."""
    def alnum(t): return re.sub(r'[^a-z0-9]', '', t.lower())
    if asr_text and alnum(text) == alnum(asr_text):
        return 'spacing-only difference'
    ws = re.findall(r"[a-z0-9']+", text.lower())
    out, run = [], []
    for w in ws + ['']:
        if w in DIGITS:
            run.append(DIGITS[w]); continue
        if run:
            out.append(''.join(run)); run = []
        if w:
            out.append(w)
    if asr_text and alnum(' '.join(out)) == alnum(asr_text) and any(len(x) >= 2 and x.isdigit() for x in out):
        return 'spelled digit run equals transcribed digits'
    return ''


def stretch(path, factor):
    """Pitch-preserving slow-down with ffmpeg atempo (factor < 1 slows). In place, 24 kHz mono PCM16."""
    import subprocess
    tmp = path + ".st.wav"
    subprocess.run(["ffmpeg", "-nostdin", "-v", "error", "-y", "-i", path, "-af", "atempo=%.4f" % factor, "-ar", "24000", "-ac", "1", "-c:a", "pcm_s16le", tmp], check=True)
    os.replace(tmp, path)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--engine", required=True); ap.add_argument("--request", required=True); ap.add_argument("--private", required=True); ap.add_argument("--out", required=True)
    a = ap.parse_args()
    req = json.load(open(a.request))
    os.makedirs(a.out, exist_ok=True)
    P = req.get("params") or {}
    ref = os.path.join(a.private, req["ref"])
    ref_sha = C.sha256_file(ref)
    t_all = time.time()
    eng = ENGINES[a.engine](ref, P)
    print("engine", eng.name, "loaded in", eng.load_s, "s; ref", os.path.basename(ref), flush=True)
    compare = C.load_compare()
    ref_embs = {os.path.basename(p): C.embed(os.path.join(a.private, p)) for p in (req.get("ref_sims") or [req["ref"]])}
    base_emb = {}
    for k, p in (req.get("baseline") or {}).items():
        base_emb[k] = C.embed(os.path.join(a.private, p))
    max_words = int(P.get("chunk_words", 32))
    pause_sent, pause_mid = float(P.get("pause_sentence_s", 0.22)), float(P.get("pause_clause_s", 0.10))
    budget_s = float(req.get("budget_minutes", 45)) * 60
    results = []
    for takei in range(1, int(req.get("takes", 1)) + 1):
        for pi, para in enumerate(req["paragraphs"], 1):
            if time.time() - t_all > budget_s:
                print("time budget reached, stopping", flush=True); break
            key, text = para["key"], para["text"].strip()
            seed = int(P.get("seed", 1234)) + 1000 * takei + pi
            t0 = time.time()
            pieces = []
            cs = chunks(text, max_words)
            for ci, ch in enumerate(cs):
                audio = trim(eng.synth(ch, seed + 97 * ci), eng.sr)
                pieces.append(audio)
                if ci < len(cs) - 1:
                    pieces.append(np.zeros(int(pause_sent * eng.sr), dtype="float32"))
            full = np.concatenate(pieces)
            render_s = round(time.time() - t0, 1)
            stem = "%s.t%d" % (key, takei)
            wav_path = os.path.join(a.out, stem + ".wav")
            C.write_wav24k(wav_path, full, eng.sr)
            info = C.wav_info(wav_path)
            tempo = None
            target = P.get("target_wpm")
            if target:
                raw = len(text.split()) / (info["duration_s"] / 60.0)
                if raw > float(target) * 1.03:
                    tempo = max(float(target) / raw, float(P.get("min_tempo", 0.85)))
                    stretch(wav_path, tempo)
                    info = C.wav_info(wav_path)
            assert (info["channels"], info["rate"], info["width"]) == (1, 24000, 2), info
            # two transcribers, as voice_lead_check does: a paragraph passes if either matches the script (small.en mishears names such as Cora as Quora)
            resp = C.asr_words(wav_path, "medium.en")
            resp_s = C.asr_words(wav_path, "small.en")
            ok_m, detail = compare(text, resp["text"])
            ok_s, detail_s = compare(text, resp_s["text"])
            sm = "" if (ok_m or ok_s) else (soft_match(text, resp["text"]) or soft_match(text, resp_s["text"]))
            ok = bool(ok_m or ok_s or sm)
            if not ok_m and ok_s:
                detail = {"matched_by": "small.en", "medium_en": detail}
            elif sm:
                detail = {"matched_by": "soft rule: " + sm}
            wpm_native = round(len(text.split()) / (info["duration_s"] / 60.0), 1)
            swpm = C.span_wpm(resp, text)
            emb = C.embed(wav_path)
            sims = {n: round(C.cosine(emb, e), 4) for n, e in ref_embs.items()}
            sim_base = round(C.cosine(emb, base_emb[key]), 4) if key in base_emb else None
            receipt = {"paragraph": key, "text": text, "input_sha256": C.sha256_bytes(text.encode()),
                       "free_engine": True, "engine": eng.name, "engine_version": eng.version, "free_route": "github-actions-cpu (public repo, encrypted artifact)",
                       "reference_file": os.path.basename(ref), "reference_sha256": ref_sha,
                       "wav_sha256": C.sha256_file(wav_path), "wav_bytes": os.path.getsize(wav_path), "wav_info": {k: info[k] for k in ("channels", "rate", "width", "frames", "duration_s")},
                       "generated_utc": dt.datetime.now(dt.timezone.utc).isoformat(), "attempt": takei, "wpm": wpm_native, "span_wpm": swpm,
                       "asr_status": "checked", "asr_engine": resp["model"], "asr_text": resp["text"], "asr_match": bool(ok), "asr_compare_detail": detail,
                       "asr_variants": {"small.en": resp_s["text"]}, "asr_match_by": {"medium.en": bool(ok_m), "small.en": bool(ok_s), "soft": sm or None}, "tempo_applied": tempo,
                       "tts_http_status": None, "params": P, "seed": seed, "chunks": len(cs), "render_seconds": render_s,
                       "speaker_sim": sims, "speaker_sim_to_baseline": sim_base,
                       "run": {"id": os.environ.get("GITHUB_RUN_ID"), "attempt": os.environ.get("GITHUB_RUN_ATTEMPT"), "sha": os.environ.get("GITHUB_SHA"),
                               "url": "https://github.com/%s/actions/runs/%s" % (os.environ.get("GITHUB_REPOSITORY", ""), os.environ.get("GITHUB_RUN_ID", ""))}}
            json.dump(resp, open(os.path.join(a.out, stem + ".words.json"), "w"), indent=2, ensure_ascii=False)
            json.dump(receipt, open(os.path.join(a.out, stem + ".receipt.json"), "w"), indent=2, ensure_ascii=False)
            row = {"key": key, "take": takei, "dur_s": info["duration_s"], "wpm_native": wpm_native, "span_wpm": swpm, "asr_match": bool(ok), "render_s": render_s,
                   "rtf": round(render_s / info["duration_s"], 2), "sim_ref": sims, "sim_baseline": sim_base, "chunks": len(cs)}
            results.append(row)
            print(json.dumps(row), flush=True)
    json.dump({"label": req.get("label"), "id": req.get("id"), "engine": eng.name, "engine_version": eng.version, "params": P, "reference_sha256": ref_sha,
               "model_load_s": eng.load_s, "total_s": round(time.time() - t_all, 1), "takes": results}, open(os.path.join(a.out, "results.json"), "w"), indent=1)
    print("done", len(results), "takes in", round(time.time() - t_all), "s", flush=True)


if __name__ == "__main__":
    main()
