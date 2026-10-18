#!/usr/bin/env python3
"""kit_bridge.py: turn a kit short's music spec + cue list into a mix2 mix_spec, so build_short.py can swap
sound/mix.py for mix2.py with a few lines (see AUDIO-KIT.md).

In build_short.py, after `cues = pick_sfx(...)` and `mres = resolve_times(music, R, 0)`:

    sys.path.insert(0, os.path.join(SOUND, "v2")); import kit_bridge
    ms = kit_bridge.mix_spec_from_kit(mres, os.path.join(SOUND, bed["path"]), voice_pad, cues,
                                      words_path=<the words json on the delivered clock>, duration_s=dur, spec_id=sid)
    json.dump(ms, open(os.path.join(adir, "mix_spec.json"), "w"), indent=1)
    run(["python3", os.path.join(SOUND, "v2/mix2.py"), "render", os.path.join(adir, "mix_spec.json"), "--out", os.path.join(adir, "mix2")])
    shutil.copy(os.path.join(adir, "mix2/master.wav"), os.path.join(adir, "mix.wav"))   # what produce.py muxes

Test on a real built short, writing only under sound/v2/kit-test/<ID>/:
    python3 kit_bridge.py <kit ID>        (e.g. S11: uses kit/specs/S11/spec.json and kit/out/S11/audio/)
"""
import json
import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
SOUND = os.path.dirname(HERE)
V2 = os.path.dirname(SOUND)
KIT = os.path.join(V2, "kit")



def _bed_under(music):
    """audio_rules.json r3 (Sam 22:40, 25 Sep): the bed median sits 12-18 LU under the voice, target 15. The old
    max(18, under_lu) floor predates r3 and made check 15 (BED_TOO_QUIET, median > 18) unpassable for every kit build."""
    import json as _j
    m = _j.load(open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "audio_rules.json")))["mixer"]
    lo, dflt = float(m.get("music_under_voice_lu_min", 12.0)), float(m.get("music_under_voice_lu_default", 15.0))
    return min(18.0, max(lo, float(music.get("under_lu", dflt))))

def mix_spec_from_kit(music, bed_path, voice_path, cues, words_path=None, duration_s=None, spec_id="kit", rooms=None,
                      studio=True):
    """music: the kit spec's "music" block with times already resolved to seconds (resolve_times output).
    Kit semantics carried over: swells {from,to,db} (kit caps 3 dB), drops {from,to,db}, under_lu, gap_rise_db,
    intro_db / outro_db. mix2 then enforces the rules itself (lookahead duck, guard, static master)."""
    # 25 Sep sound upgrade: swells up to the craft standard's 6 dB cap, and mix2 now lets them act only inside true
    # pauses (>= 0.4 s); the bed sits >= 18 LU under the voice during speech (default 19).
    swells = [{"t0": float(s["from"]), "t1": float(s["to"]), "gain_db": min(float(s.get("db", 3.0)), 6.0), "fade_s": 0.4,
               "label": s.get("label", "kit swell")} for s in music.get("swells", [])]
    drops = [{"t0": float(d["from"]), "t1": float(d["to"]), "gain_db": min(float(d.get("db", -18.0)), 0.0), "fade_s": 0.25,
              "label": d.get("label", "kit drop")} for d in music.get("drops", [])]
    cc = []
    for c in cues:
        c = dict(c)
        c["designed_hit"] = bool(c.get("designed_hit")) or c["sfx_id"].startswith(("impact_", "riser_", "reverse_swell", "foley_stamp"))
        cc.append(c)
    spec = {"id": spec_id,
            "voice": {"src": os.path.abspath(voice_path), "studio": bool(studio)},
            "music": {"src": os.path.abspath(bed_path), "under_voice_lu": _bed_under(music),
                      "level_bed": True},
            "ducking": {"gap_rise_db": min(3.0, float(music.get("gap_rise_db", 2.0))), "hold_ms": 150, "release_ms": 600,
                        "attack_ms": 120, "head_db": min(3.0, float(music.get("intro_db", 2.0))),
                        "tail_db": min(3.0, float(music.get("outro_db", 3.0)))},
            "swells": swells, "drops": drops,
            "sfx": {"library": os.path.join(SOUND, "library.json"), "cues": cc, "protect_words": True},
            "ambience": {"regions": list(rooms or [])},
            "master": {"integrated_lufs": -14.0, "true_peak_dbtp": -1.0}}
    if words_path:
        spec["words"] = os.path.abspath(words_path)
    if duration_s:
        spec["duration_s"] = float(duration_s)
    return spec


def test(kid):
    sys.path.insert(0, KIT)
    import build_short as bs   # read-only use of the kit's own word-reference resolver
    ks = json.load(open(os.path.join(KIT, "specs", kid, "spec.json")))
    wp = ks["voice"]["words"]
    wp = wp if os.path.isabs(wp) else os.path.join(V2, wp)
    wj = json.load(open(wp))
    words = wj["words"] if isinstance(wj, dict) else wj
    R = bs.Resolver(words)
    mres = bs.resolve_times(json.loads(json.dumps(ks.get("music", {}))), R, 0)
    adir = os.path.join(KIT, "out", kid, "audio")
    mitems = {m["id"]: m for m in json.load(open(os.path.join(SOUND, "music.json")))["items"]}
    bed = os.path.join(SOUND, mitems[mres["bed"]]["path"])
    cues = json.load(open(os.path.join(adir, "cues.json")))["cues"]
    out = os.path.join(HERE, "kit-test", kid)
    os.makedirs(out, exist_ok=True)
    ms = mix_spec_from_kit(mres, bed, os.path.join(adir, "voice-padded.wav"), cues, words_path=wp, spec_id=kid + "-mix2")
    sp = os.path.join(out, "mix_spec.json")
    json.dump(ms, open(sp, "w"), indent=1)
    subprocess.run(["python3", os.path.join(HERE, "mix2.py"), "render", sp, "--out", os.path.join(out, "mix2")], check=True)
    p = subprocess.run(["python3", os.path.join(HERE, "audio_report.py"), os.path.join(out, "mix2/master.wav"), "--stems",
                        os.path.join(out, "mix2/stems"), "--spec", sp, "--out", os.path.join(out, "report"), "--no-gemini",
                        "--label", kid + " via kit_bridge + mix2"], capture_output=True, text=True)
    print(p.stdout)
    return p.returncode


if __name__ == "__main__":
    sys.exit(test(sys.argv[1]) if len(sys.argv) > 1 else print(__doc__))
