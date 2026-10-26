#!/usr/bin/env python3
"""sfx_remeasure.py DIR OUT.json : the repo's own onset / peak definition for every wav under DIR (numpy + soundfile only; Actions only).

sound/audit_sound.py (gate check 15 ONSETS) measures a cue's landing from the FILE: onset = first sample >= 6% of the file's peak, peak = loudest 20 ms RMS
window. mix2 places a cue by the library's onset_ms (anchor_ms for peak-anchored sounds). Both must be the same number, or a sound with a soft attack lands
more than one frame (33.3 ms) off its scene event (S264 audit, 26 Oct: a paper sound landed 37 ms late). So every library sound is re-measured with the
audit's definition and that number is what the registry stores."""
import json, sys
from pathlib import Path
import numpy as np
import soundfile as sf


def facts(p):
    x, sr = sf.read(str(p), dtype="float64", always_2d=True)
    if sr != 48000:
        import soxr
        x = soxr.resample(x, sr, 48000)
        sr = 48000
    m = np.abs(x).max(axis=1)
    pk = float(m.max()) if len(m) else 0.0
    if pk <= 0:
        return {"onset_ms": 0.0, "peak_ms": 0.0}
    on = int(np.argmax(m >= 0.06 * pk))
    w = int(0.02 * sr)
    rms = np.sqrt(np.convolve((x ** 2).mean(axis=1), np.ones(w) / w, mode="same"))
    return {"onset_ms": round(on / sr * 1000, 2), "peak_ms": round(int(np.argmax(rms)) / sr * 1000, 2), "duration_s": round(len(x) / sr, 4)}


def main():
    root, out = Path(sys.argv[1]), Path(sys.argv[2])
    res = {p.stem: facts(p) for p in sorted(root.rglob("*.wav"))}
    out.parent.mkdir(parents=True, exist_ok=True)
    json.dump(res, open(out, "w"), indent=0)
    print("remeasured", len(res), "files")


if __name__ == "__main__":
    main()
