"""E voice bake-off: synthesize the 20 neutral test lines per engine on a CPU runner.
Writes <out>/<voice>__Lnn.wav and <out>/timing.json (per-line synth ms = time to a playable line for non-streaming engines).
Usage: synth_e.py ENGINE OUTDIR"""
import sys, json, time, wave, pathlib, os, subprocess, urllib.request
import numpy as np, soundfile as sf
engine, out = sys.argv[1], pathlib.Path(sys.argv[2]); out.mkdir(parents=True, exist_ok=True)
HERE = pathlib.Path(__file__).parent
LINES = json.load(open(HERE / "lines.json"))
timing = {}
def dl(url, dest):
    if not pathlib.Path(dest).exists(): urllib.request.urlretrieve(url, dest)
def save(name, i, a, sr):
    sf.write(out / f"{name}__L{i+1:02d}.wav", np.asarray(a, dtype=np.float32), sr)
def run_voice(name, fn, lines=LINES):
    rows = []
    for i, t in enumerate(lines):
        t0 = time.perf_counter()
        try:
            a, sr = fn(t)
            ms = (time.perf_counter() - t0) * 1000
            save(name, i, a, sr); rows.append({"line": i+1, "first_ms": round(ms), "dur_s": round(len(a)/sr, 2)})
        except Exception as e:
            rows.append({"line": i+1, "error": f"{type(e).__name__}: {str(e)[:100]}"})
            if i == 0: break
        if rows and "first_ms" in rows[-1] and rows[-1]["first_ms"] > 120000: break
    timing[name] = rows
    json.dump(timing, open(out / "timing.json", "w"), indent=1)
    ok = [r for r in rows if "first_ms" in r]
    print(name, len(ok), "ok", sorted(r["first_ms"] for r in ok)[len(ok)//2] if ok else "-", "ms p50", flush=True)

def kokoro_model():
    from kokoro_onnx import Kokoro
    base = "https://github.com/thewh1teagle/kokoro-onnx/releases/download/model-files-v1.0/"
    dl(base + "kokoro-v1.0.onnx", "kokoro-v1.0.onnx"); dl(base + "voices-v1.0.bin", "voices-v1.0.bin")
    return Kokoro("kokoro-v1.0.onnx", "voices-v1.0.bin")

def make_ref():
    k = kokoro_model()
    txt = "Right, so the numbers look fine to me, but I would check the second one again before we send anything out."
    a, sr = k.create(txt, voice="bm_lewis", speed=1.0, lang="en-gb")
    sf.write("ref.wav", a, sr); return "ref.wav", txt

if engine == "kokoro":
    k = kokoro_model(); k.create("warm up", voice="bm_lewis", lang="en-gb")
    for v in ["bm_lewis", "bm_fable", "bm_daniel", "bf_emma", "bf_isabella", "bf_alice", "bf_lily"]:
        run_voice("kokoro-" + v.replace("_", "-"), lambda t, v=v: k.create(t, voice=v, speed=1.0, lang="en-gb"))
elif engine == "piper":
    from piper import PiperVoice
    for path, nm in [("en/en_GB/alan/medium/en_GB-alan-medium", "alan"), ("en/en_GB/northern_english_male/medium/en_GB-northern_english_male-medium", "northern-male"),
                     ("en/en_GB/alba/medium/en_GB-alba-medium", "alba"), ("en/en_GB/cori/high/en_GB-cori-high", "cori-high"), ("en/en_GB/jenny_dioco/medium/en_GB-jenny_dioco-medium", "jenny")]:
        base = "https://huggingface.co/rhasspy/piper-voices/resolve/main/" + path
        f = path.split("/")[-1]
        dl(base + ".onnx", f + ".onnx"); dl(base + ".onnx.json", f + ".onnx.json")
        pv = PiperVoice.load(f + ".onnx")
        def fn(t, pv=pv):
            import io
            buf = io.BytesIO()
            with wave.open(buf, "wb") as wf:
                pv.synthesize_wav(t, wf)
            buf.seek(0); a, sr = sf.read(buf); return a, sr
        run_voice("piper-" + nm, fn)
elif engine in ("chatterbox", "chatterbox-ukref"):
    import torch, torchaudio as ta
    from chatterbox.tts import ChatterboxTTS
    ref = None
    if engine == "chatterbox-ukref": ref, _ = make_ref()
    m = ChatterboxTTS.from_pretrained(device="cpu")
    def fn(t):
        w = m.generate(t, audio_prompt_path=ref, exaggeration=0.5, cfg_weight=0.5)
        return w.squeeze(0).numpy(), m.sr
    run_voice("chatterbox-ukref" if ref else "chatterbox-default", fn)
elif engine == "f5":
    from f5_tts.api import F5TTS
    ref, rt = make_ref(); f5 = F5TTS()
    def fn(t):
        wav, sr, _ = f5.infer(ref_file=ref, ref_text=rt, gen_text=t, remove_silence=False); return wav, sr
    run_voice("f5-tts-ukref", fn)
elif engine == "kyutai":
    subprocess.run(["git", "clone", "--depth", "1", "https://github.com/kyutai-labs/delayed-streams-modeling.git", "dsm"], check=True)
    def fn(t):
        open("in.txt", "w").write(t)
        subprocess.run([sys.executable, "dsm/scripts/tts_pytorch.py", "in.txt", "o.wav", "--device", "cpu"], check=True, capture_output=True, timeout=600)
        return sf.read("o.wav")
    run_voice("kyutai-tts-default", fn, LINES[:4])
