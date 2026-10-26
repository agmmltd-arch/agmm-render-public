#!/usr/bin/env python3
"""audio_remix_audit.py - rebuild one engine short's audio with the new SFX library and run the repo's own native audits on it (Actions only).

Input dir (private repo) = a V2 subtree: sound/v2/{mix2,audio_core,voice_chain}.py + audio_rules.json, sound/audit_sound.py, kit/tools/fxlevel.py,
the bed mp3, the library json (merged) with the cue wavs, kit/out/<ID>/{resolved.json, audio/{voice-padded.wav, cues.json, mix_spec.json}}, the words json.
Steps: mix2 render (4 stems + master, deterministic) -> sound/audit_sound.py on the master (kit gate check 15: loudness, bed rows, swells, density, overlap,
ONSETS within one frame measured from the audio, stereo, banned) with AUDIT_SOUND_LIBJSON = the merged library -> fxlevel.py (kit gate check 13: effects / music
level against the voice). Output: audit.json, fxlevel.json, run.log, SUMMARY.md. Exit 1 if either fails.
"""
import json, os, subprocess, sys
from pathlib import Path


def run(cmd, env, log):
    r = subprocess.run(cmd, capture_output=True, text=True, env=env)
    log.write("$ %s\n%s%s\n" % (" ".join(map(str, cmd)), r.stdout[-6000:], r.stderr[-6000:]))
    log.flush()
    return r


def main():
    src, sid, out = Path(sys.argv[1]).resolve(), sys.argv[2], Path(sys.argv[3])
    out.mkdir(parents=True, exist_ok=True)
    v2 = src / "v2"
    log = open(out / "run.log", "w")
    env = dict(os.environ, AGMM_SFX_SOURCE="openverse")
    spec_p = v2 / "kit/out" / sid / "audio/mix_spec.json"
    txt = spec_p.read_text().replace("/Users/samwall/alfred/builds/video-program-2026-09-23/v2", str(v2))
    spec_p.write_text(txt)
    adir = v2 / "kit/out" / sid / "audio"
    r = run([sys.executable, str(v2 / "sound/v2/mix2.py"), "render", str(spec_p), "--out", str(adir / "mix2")], env, log)
    if r.returncode:
        print("mix2 failed", r.stderr[-800:])
        return 2
    master = adir / "mix2/master.wav"
    os.environ["AUDIT_SOUND_LIBJSON"] = str(v2 / "sound/library.earshot-merged.json")
    sys.path.insert(0, str(v2 / "sound"))
    sys.path.insert(0, str(v2 / "kit/tools"))
    import audit_sound, fxlevel
    c15 = audit_sound.check(str(master), build=str(v2 / "kit/out" / sid))
    json.dump(c15, open(out / "audit.json", "w"), indent=1, default=str)
    c13 = fxlevel.check(str(master), str(adir / "mix2/stems/voice.wav"))
    json.dump(c13, open(out / "fxlevel.json", "w"), indent=1, default=str)
    lines = ["# audio remix audit %s with the SFX library" % sid, "",
             "- mix2 render: ok (%s)" % master.name,
             "- gate check 15 SOUND AUDIT (audit_sound.check): %s | %s" % (c15.get("status"), str(c15.get("summary"))[:400]),
             "- gate check 13 FX/MUSIC LEVEL vs VOICE (fxlevel.check): %s | %s" % (c13.get("status"), str(c13.get("summary"))[:400])]
    det = c15.get("details") or {}
    if isinstance(det, dict):
        for k, v in det.items():
            lines.append("  - %s: %s" % (k, json.dumps(v, default=str)[:260]))
    (out / "SUMMARY.md").write_text("\n".join(lines) + "\n")
    print("\n".join(lines))
    return 0 if c15.get("status") != "FAIL" and c13.get("status") != "FAIL" else 1


if __name__ == "__main__":
    sys.exit(main())
