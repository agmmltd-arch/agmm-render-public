"""vf_common.py - shared helpers for the voice-free Actions workflows (20 Oct 2026). Code only: audio never enters this repo.

Public-log hygiene: this repo is PUBLIC, so nothing here prints script text or transcripts, only numbers and ids.
"""
import hashlib, json, os, re, subprocess, sys, time

HERE = os.path.dirname(os.path.abspath(__file__))
NATIVE_TOOLING = os.path.normpath(os.path.join(HERE, "..", "voice-native", "shorts", "voice", "tooling"))


def sha256_file(path):
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for b in iter(lambda: fh.read(1 << 20), b""):
            h.update(b)
    return h.hexdigest()


def sha256_bytes(b):
    return hashlib.sha256(b).hexdigest()


def wav_info(path):
    import soundfile as sf
    i = sf.info(path)
    return {"channels": i.channels, "rate": i.samplerate, "width": 2 if i.subtype == "PCM_16" else None, "subtype": i.subtype,
            "frames": i.frames, "duration_s": round(i.frames / i.samplerate, 6)}


def write_wav24k(path, audio, sr):
    """audio: 1-D float numpy array at sr. Writes 24 kHz mono PCM16 (the downstream contract: gen_paragraphs asserts (1, 24000, 2))."""
    import numpy as np, soundfile as sf
    a = np.asarray(audio, dtype="float32").reshape(-1)
    if sr != 24000:
        import librosa
        a = librosa.resample(a, orig_sr=sr, target_sr=24000)
    a = np.clip(a, -1.0, 1.0)
    sf.write(path, a, 24000, subtype="PCM_16")


_WHISPER = {}


def whisper_model(name="small.en"):
    if name not in _WHISPER:
        from faster_whisper import WhisperModel
        _WHISPER[name] = WhisperModel(name, device="cpu", compute_type="int8", cpu_threads=os.cpu_count() or 4)
    return _WHISPER[name]


def asr_words(path, name="small.en", prompt=None):
    """Word-timed transcript in the shape the native chain reads from Mistral: {text, segments:[{type:'transcription_segment', text, start, end}]}.
    assemble.py takes resp['segments'] entries of type transcription_segment (one per word); api_queue.span_wpm reads segments[].start/end."""
    m = whisper_model(name)
    segs, info = m.transcribe(path, language="en", beam_size=5, word_timestamps=True, vad_filter=False, condition_on_previous_text=False,
                                initial_prompt=prompt)
    words = []
    for s in segs:
        for w in (s.words or []):
            t = w.word.strip()
            if t:
                words.append({"type": "transcription_segment", "text": t, "start": round(float(w.start), 3), "end": round(float(w.end), 3)})
    return {"model": "faster-whisper-%s (CTranslate2 int8, CPU)" % name, "language": "en", "text": " ".join(w["text"] for w in words), "segments": words}


def span_wpm(resp, text):
    segs = resp.get("segments") or []
    if not segs:
        return None
    span = segs[-1]["end"] - segs[0]["start"]
    return round(len(text.split()) / span * 60, 1) if span > 0 else None


_ENC = {}


def encoder():
    if "e" not in _ENC:
        from resemblyzer import VoiceEncoder
        _ENC["e"] = VoiceEncoder("cpu")
    return _ENC["e"]


def embed(path, start=None, end=None):
    import numpy as np
    from resemblyzer import preprocess_wav
    wav = preprocess_wav(path)          # 16 kHz, trimmed of long silences, volume-normalised
    if start is not None:
        wav = wav[int(start * 16000):int(end * 16000)]
    return encoder().embed_utterance(wav)


def cosine(a, b):
    import numpy as np
    return float(np.dot(a, b) / (np.linalg.norm(a) * np.linalg.norm(b)))


def load_compare():
    sys.path.insert(0, NATIVE_TOOLING)
    from asr_compare import compare
    return compare


def pack_encrypt(src_dir, out_file):
    """tar | AES-256-CBC (PBKDF2). The passphrase is the repo secret VOICEFREE_PASS read from the environment, never an argument."""
    if not os.environ.get("VOICEFREE_PASS"):
        raise SystemExit("VOICEFREE_PASS missing: refusing to upload unencrypted audio from a public repo")
    cmd = "tar -C %s -cf - . | openssl enc -aes-256-cbc -pbkdf2 -salt -pass env:VOICEFREE_PASS -out %s" % (src_dir, out_file)
    subprocess.run(["bash", "-o", "pipefail", "-c", cmd], check=True)
    return os.path.getsize(out_file)
