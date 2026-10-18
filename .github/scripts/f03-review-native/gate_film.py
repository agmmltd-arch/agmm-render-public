#!/usr/bin/env python3
"""Full gate for a long-form film master at 1920x1080: qa/gate.py (checks 1-10) + kit check 11 SHARPNESS + kit check 12
NOISE FLOOR + kit check 13 FX/MUSIC LEVEL vs VOICE (fxlevel.py, on the master's own audio) + film check 14 MUSIC IN
GAPS + SHIPPED MIX, all written into one GATE.json/GATE.md.

Usage: gate_film.py <master.mp4> --build <film build dir> --tag r2 --out <gate dir> [--look NAME] [--bed ID]
  --script defaults to <build>/gate_script_full.txt; words to <build>/audio/words_full.json.
Check 14 runs the film's own tools/gap_check.py on the stems (bed_full.wav, voice_full.wav, mix.wav) AND proves the
master carries that exact mix: the master's audio is decoded and compared with renders/<tag>/pkg/audio/mix.flac
(integrated level within 0.5 dB, waveform correlation >= 0.98 after AAC). A master with a different mix fails.
Captions: the films carry no burned-in captions, so gate captions are phrase groups built from words_full.json."""
import argparse, json, os, subprocess, sys
import numpy as np

V2 = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(V2, "kit", "tools"))


def append(gdir, check):
    gj = os.path.join(gdir, "GATE.json")
    g = json.load(open(gj))
    g["checks"] = [c for c in g["checks"] if c.get("id") != check["id"]] + [check]
    g["overall"] = "FAIL" if any(c["status"] == "FAIL" for c in g["checks"]) else "PASS"
    json.dump(g, open(gj, "w"), indent=1)
    with open(os.path.join(gdir, "GATE.md"), "a") as fh:
        fh.write("\n| %s | %s | %s | %s |\n" % (check["id"], check["name"], check["status"], check["summary"]))
    return g


def pcm(path, sr=16000):
    p = subprocess.run(["nice", "-n", "15", "ffmpeg", "-v", "error", "-threads", "2", "-i", path, "-vn", "-ac", "1", "-ar", str(sr), "-f", "f32le", "-"],
                       capture_output=True)
    return np.frombuffer(p.stdout, dtype=np.float32)


def check14(master, build, mixfile):
    p = subprocess.run(["python3", os.path.join(build, "tools", "gap_check.py")], capture_output=True, text=True)
    txt = p.stdout.strip()
    gap_ok = "RESULT: PASS" in txt
    a, b = pcm(master), pcm(mixfile)
    n = min(len(a), len(b))
    # AAC adds a priming delay; find the lag (<= 100 ms) that best aligns the two before correlating
    best = (0, -1.0)
    seg_a, seg_b = a[16000 * 30:16000 * 90], b[16000 * 30:16000 * 90]
    for lag in range(-1600, 1601, 8):
        x = seg_a[max(0, lag):len(seg_a) + min(0, lag)]; y = seg_b[max(0, -lag):len(seg_b) - max(0, lag)]
        m = min(len(x), len(y)); c = float(np.corrcoef(x[:m], y[:m])[0, 1])
        if c > best[1]:
            best = (lag, c)
    lag = best[0]
    x = a[max(0, lag):n]; y = b[max(0, -lag):n]; m = min(len(x), len(y))
    corr = float(np.corrcoef(x[:m], y[:m])[0, 1])
    lvl = 10 * np.log10(np.mean(a[:n] ** 2) + 1e-12) - 10 * np.log10(np.mean(b[:n] ** 2) + 1e-12)
    same = corr >= 0.98 and abs(lvl) <= 0.5
    ok = gap_ok and same
    lines = [l for l in txt.splitlines() if l.startswith(("gaps measured", "worst bed", "bed under", "gaps over", "RESULT"))]
    return {"id": "14", "name": "MUSIC IN VOICE GAPS + SHIPPED MIX", "status": "PASS" if ok else "FAIL",
            "summary": "%s; master audio = sealed mix (corr %.4f, level %+.2f dB, lag %d ms)" % ("; ".join(lines), corr, lvl, lag * 1000 // 16000),
            "details": {"gap_check_stdout": txt, "master_vs_mix_corr": round(corr, 4), "master_vs_mix_db": round(float(lvl), 2), "lag_samples_16k": lag}}


def captions(words, path):
    W = json.load(open(words)); W = W["words"] if isinstance(W, dict) else W
    out, cur = [], []
    for k, w in enumerate(W):
        cur.append(w)
        nxt = W[k + 1] if k + 1 < len(W) else None
        if len(cur) >= 7 or w["word"].rstrip().endswith((".", ",", "?", "!", ":")) or nxt is None or nxt["start"] - w["end"] > 0.35:
            out.append({"start": round(cur[0]["start"], 3), "end": round(cur[-1]["end"], 3), "text": " ".join(x["word"] for x in cur)})
            cur = []
    json.dump(out, open(path, "w"), indent=1)
    return path


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("master"); ap.add_argument("--build", required=True); ap.add_argument("--tag", required=True)
    ap.add_argument("--out", required=True); ap.add_argument("--script"); ap.add_argument("--words")
    ap.add_argument("--look", default=None); ap.add_argument("--bed", default=None); ap.add_argument("--platform", default="youtube")
    ap.add_argument("--video-id", default=None)
    ap.add_argument("--mix", default=None, help="the mix the master should carry (default: the sealed package's)")
    a = ap.parse_args()
    b = os.path.abspath(a.build); os.makedirs(a.out, exist_ok=True)
    script = a.script or os.path.join(b, "gate_script_full.txt")
    words = a.words or os.path.join(b, "audio", "words_full.json")
    cap = captions(words, os.path.join(a.out, "captions-from-words.json"))
    cmd = ["python3", os.path.join(V2, "qa", "gate.py"), a.master, "--script", script, "--captions", cap, "--kind", "long", "--out", a.out,
           "--platform", a.platform, "--format", "film", "--window", "1000"]
    if a.look: cmd += ["--look", a.look]
    if a.bed: cmd += ["--bed", a.bed]
    cmd = ["python3", os.path.join(V2, "kit", "tools", "heavy.py"), "--"] + cmd       # 2 machine-wide slots for heavy local jobs
    p = subprocess.run(cmd, capture_output=True, text=True)
    open(os.path.join(a.out, "gate.stdout.txt"), "w").write(p.stdout + p.stderr)
    # checks 2 (OCR) and 9 (critic) send a downscaled copy to Gemini inline, capped at 18 MB. qa/gate.py's copy of an
    # 8-9 minute film comes out over the cap (150 kbps floor + 96 kbps audio), so both checks failed with ">18MB" on F01
    # r3 without looking at anything. Re-run them here on a 360p, 110 kbps, 48 kbps mono copy (about 10 MB for 8:37),
    # through qa/gate.py's own check functions so the criteria are identical.
    gj = json.load(open(os.path.join(a.out, "GATE.json")))
    # 28 Sep: check 9 may now come back from qa/gate.py's Qwen frames-only fallback (Gemini quota / >18MB). When the
    # fallback fired because the copy was >18MB, re-run on the 360p copy so Gemini (which hears the sound) gets its turn;
    # if Gemini is out of quota there too, the same fallback runs again and the 720p-frames result is kept.
    QWEN = "Qwen 3.8 frames-only fallback"
    need = [c["id"] for c in gj["checks"] if c["id"] in ("2", "9") and ">18MB" in json.dumps(c)
            and (c["status"] == "FAIL" or (c["id"] == "9" and QWEN in c.get("summary", "")))]
    prev9 = next((c for c in gj["checks"] if c["id"] == "9"), None)
    if need:
        import importlib.util
        spec = importlib.util.spec_from_file_location("agmm_gate", os.path.join(V2, "qa", "gate.py"))
        G = importlib.util.module_from_spec(spec); spec.loader.exec_module(G)
        small = os.path.join(a.out, "film_for_gemini_360p.mp4")
        subprocess.run(["python3", os.path.join(V2, "kit", "tools", "heavy.py"), "--", "nice", "-n", "15", "ffmpeg", "-v", "error", "-y", "-threads", "2",
                        "-i", a.master, "-vf", "scale=-2:360", "-c:v", "libx264", "-b:v", "110k", "-maxrate", "140k", "-bufsize", "280k",
                        "-x264-params", "threads=2", "-c:a", "aac", "-ac", "1", "-b:a", "48k", small], check=True)
        if os.path.getsize(small) > G.GEMINI_MAX_BYTES:
            sys.exit("film copy for Gemini still over the cap: %d bytes" % os.path.getsize(small))
        if "2" in need:
            r2, _ = G.run_check2_ocr(a.master, G.probe_info(a.master), small, a.out, False)
            append(a.out, r2)
        if "9" in need:
            r9 = G.run_check9_gemini_critic(small, a.out)
            if not (QWEN in r9.get("summary", "") and prev9 and QWEN in prev9.get("summary", "")):
                append(a.out, r9)     # same fallback either way; keep the sharper 720p-frames verdict if both were Qwen
    import sharpness, noisefloor
    append(a.out, sharpness.check(a.master, 48))
    append(a.out, noisefloor.check(a.master, words))
    import fxlevel
    append(a.out, fxlevel.check(a.master, os.path.join(b, "audio", "voice_full.wav")))     # kit check 13, on the shipped audio
    # film check 15 FRAME FLICKER over the whole master, in 8.6 s windows (a render worker that captured blank WebGL
    # frames left 2 of every 3 frames black in F01 r2 SEG16; every sampled contact sheet missed it)
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    import render_codespace_film as rcf
    raw = subprocess.run(["nice", "-n", "15", "ffmpeg", "-v", "error", "-threads", "2", "-i", a.master, "-vf", "scale=64:36,format=gray", "-f", "rawvideo", "-"],
                         capture_output=True).stdout
    x = np.frombuffer(raw, dtype=np.uint8).reshape(-1, 36, 64).astype(float).mean(axis=(1, 2))
    iso = np.zeros(len(x), bool)
    for i in range(1, len(x) - 1):
        iso[i] = (x[i] - x[i - 1]) * (x[i] - x[i + 1]) > 0 and min(abs(x[i] - x[i - 1]), abs(x[i] - x[i + 1])) > 8
    win = 258; bad = [(round(k / 30.0, 1), round(100.0 * iso[k:k + win].mean(), 1)) for k in range(0, len(x), win) if iso[k:k + win].mean() * 100 > rcf.FLICKER_MAX]
    append(a.out, {"id": "15", "name": "FRAME FLICKER", "status": "FAIL" if bad else "PASS",
                   "summary": ("windows over %.0f%% isolated flicker frames: %s" % (rcf.FLICKER_MAX, bad)) if bad else
                   "%d frames, %d isolated flicker frames (%.2f%%), no 8.6 s window over %.0f%%" % (len(x), int(iso.sum()), 100.0 * iso.mean(), rcf.FLICKER_MAX),
                   "details": {"bad_windows": bad}})
    g = append(a.out, check14(a.master, b, a.mix or os.path.join(b, "renders", a.tag, "pkg", "audio", "mix.flac")))
    for c in g["checks"]:
        print("check %-3s %-36s %s  %s" % (c["id"], c["name"], c["status"], c["summary"][:220]))
    print("OVERALL", g["overall"])
    return 0 if g["overall"] == "PASS" else 1


if __name__ == "__main__":
    sys.exit(main())
