#!/usr/bin/env python3
"""Storyboard gate BEFORE render (root, 25 Sep 02:25, after Sam rejected S29 as "ai slop, no micro design").
One frame per beat (headless snap.py), tiled into a sheet next to the approved pilot P1's sheet, submitted to the art
director queue (registry/storyboards/<ID>.json). The writer waits for "approved" before rendering; "returned" carries
the art director's notes. Rendering without an approved storyboard is refused by produce.py's dispatch.
Usage: storyboard.py submit <ID> [--concept-waiver "<reason, 40+ characters>"] [--polish-waiver "<reason, 40+ characters>"] | concept <ID> | status <ID> | approve <ID> [notes] | return <ID> <notes>

6 Oct 2026 (Sam: "be careful not to make the visuals too similar... we're dropping creativity"): `submit` first runs
tools/concept_check.py on specs/<ID>/concept.json (sameness against the last 10 approved shorts, plus a text-only pitch check) and
REFUSES on a FAIL; after the sheet exists it also checks the declared ground against the sheet's pixels. A deliberate exception is
`--concept-waiver "<reason>"`: the reason (40+ characters) and the failed checks are written into the registry history. Root can
switch the gate to advisory with registry/concept-check.off or AGMM_CONCEPT_CHECK=warn. `concept <ID>` runs only the gate.

12 Oct 2026 (Sam: "make sure all motion graphics and all the tiny detail visuals are perfect - each video has been about 85% clean"): `submit` also runs
tools/polish_check.py (frame-by-frame DOM facts on GitHub Actions: pops, flickers, jitter, snaps, linear/too-fast moves, edge clipping, squashed
images ...) and REFUSES on a FAIL. A deliberate exception is `--polish-waiver "<reason>"` (40+ characters, recorded in the registry history).
Root can make it advisory with registry/polish-check.off or AGMM_POLISH_CHECK=warn; a tool error never blocks."""
import glob, json, os, subprocess, sys, time

KIT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
REG = os.path.join(KIT, "registry", "storyboards")
P1_SHEET = os.path.join(REG, "_P1_reference_sheet.jpg")


def sheet_of(ID):
    out = os.path.join(KIT, "out", ID)
    beats = json.load(open(os.path.join(out, "resolved.json")))
    beats = beats.get("beats", beats) if isinstance(beats, dict) else beats
    times = [round((float(b["from"]) + float(b["to"])) / 2, 2) for b in beats] + [0.1]
    subprocess.run(["python3", os.path.join(KIT, "tools", "snap.py"), ID, "--at", ",".join(str(t) for t in sorted(set(times)))], check=True)
    pngs = sorted([f for f in glob.glob(os.path.join(out, "snap", "*", "*.png")) + glob.glob(os.path.join(out, "snap", "*", "*.jpg"))
                   if os.path.basename(f).startswith("frame-")], key=os.path.getmtime)[-len(set(times)):]   # snap.py writes JPG since 28 Sep
    lst = os.path.join(out, "snap", "list.txt")
    open(lst, "w").write("".join("file '%s'\n" % p for p in sorted(pngs)))
    sheet = os.path.join(REG, "%s-storyboard.jpg" % ID)
    subprocess.run(["python3", os.path.join(KIT, "tools", "heavy.py"), "--", "ffmpeg", "-v", "error", "-y", "-f", "concat", "-safe", "0", "-i", lst,
                    "-vf", "scale=270:480,tile=6x%d" % max(2, -(-len(pngs) // 6)), "-frames:v", "1", sheet], check=True)
    try:
        _append_masked(ID, sheet)
    except Exception as e:      # the mask is an aid; it never blocks a submission
        print("storyboard: platform-masked rows skipped (%s)" % e)
    return sheet


def _append_masked(ID, sheet):
    """Row 6, 29 Sep 2026 (Sam: text cut at Instagram's edges and under its UI). Appends the same tiles as the ROUTED
    platform's phone shows them (kit/tools/frame_mask.py: hatched = cropped by the phone, orange = app UI, green dashed =
    text-safe), so the art director sees what the phone hides before anything is rendered."""
    sys.path.insert(0, os.path.join(KIT, "platforms")); sys.path.insert(0, os.path.join(KIT, "tools"))
    import platforms, frame_mask
    from PIL import Image, ImageDraw
    spec = json.load(open(os.path.join(KIT, "specs", ID, "spec.json")))
    name = platforms.routed_platform(ID) or spec.get("platform")
    if not name:
        print("storyboard: no routed platform for %s; no masked rows" % ID); return
    p = platforms.profile(name)
    masked = sheet[:-4] + "-masked.jpg"
    frame_mask.mask_sheet(sheet, p, masked, (270, 480))
    top, bot = Image.open(sheet).convert("RGB"), Image.open(masked).convert("RGB")
    bar = 44
    out = Image.new("RGB", (top.width, top.height + bar + bot.height), (18, 18, 18))
    out.paste(top, (0, 0)); out.paste(bot, (0, top.height + bar))
    ImageDraw.Draw(out).text((12, top.height + 12), "AS SEEN ON %s (%s crop): hatched = cut by the phone, orange = app UI, "
                             "green dashed = text-safe" % (p["key"], p["visible"]["evidence"]), fill=(255, 255, 255),
                             font=frame_mask._font(18))
    out.save(sheet, quality=90)
    print("storyboard: masked rows for %s appended (%s)" % (p["key"], masked))


ARCHIVE_RX = __import__("re").compile(r"(^|/)(_archive|archive|old-|r\d+/)|\.bak|\.r\d+-returned|-returned\.|scenes\.r\d")


def _hash_files(ID, skip_archives):
    import hashlib
    h = hashlib.sha256()
    d = os.path.join(KIT, "specs", ID)
    for f in sorted(glob.glob(os.path.join(d, "**", "*"), recursive=True)):
        rel = os.path.relpath(f, d)
        if os.path.isfile(f) and f.endswith((".json", ".js", ".css", ".html", ".svg")) and "receipt" not in f \
                and os.path.basename(f) != "concept.json" \
                and not os.path.basename(f).startswith("ref-watch") and not (skip_archives and ARCHIVE_RX.search(rel)):
            h.update(rel.encode()); h.update(open(f, "rb").read())
    return h.hexdigest()


def spec_hash(ID):
    """Fingerprint of what the art director judged: the spec and every scene/code file in specs/<ID>/ (not notes).
    craft ledger 28 Sep (crew rule 8): backups and archives inside specs/<ID>/ (*.bak*, _archive*, old-*, r<N>/,
    *-returned.*) no longer change the hash, so archiving a file cannot un-approve a short."""
    return _hash_files(ID, True)


def spec_hash_legacy(ID):
    """the pre-28 Sep hash (every file), so approvals recorded before this change still render."""
    return _hash_files(ID, False)


def stale_build(ID):
    """craft ledger 28 Sep (C10 25 Sep 13:59: a text fix submitted without a rebuild, so the sheet showed old code):
    the newest spec/scene file must not be newer than out/<ID>/resolved.json."""
    d = os.path.join(KIT, "specs", ID)
    res = os.path.join(KIT, "out", ID, "resolved.json")
    if not os.path.exists(res):
        return "no build yet (out/%s/resolved.json missing)" % ID
    newest = max([os.path.getmtime(f) for f in glob.glob(os.path.join(d, "*")) if os.path.isfile(f)
                  and f.endswith((".json", ".js", ".css")) and os.path.basename(f) != "concept.json"      # 6 Oct: a gate input, not render code
                  and not ARCHIVE_RX.search(os.path.relpath(f, d))] or [0])
    if newest > os.path.getmtime(res) + 1:
        return "specs/%s changed after the last build; run `python3 produce.py %s --only build` first" % (ID, ID)
    return None


def density_advisory(ID):
    """craft ledger 28 Sep: 'subject fills 60% / lands full on the cut' was the most returned defect (13 shorts).
    Prints storyboard frames under the approved shorts' 5th-percentile fill (coverage 0.17, measured on 859 approved
    frames). ADVISORY: pixels cannot see a bare field (S39 was returned at 0.43+ on every frame); the look decides."""
    try:
        import numpy as np
        from PIL import Image
    except Exception:
        return
    lst = os.path.join(KIT, "out", ID, "snap", "list.txt")
    if not os.path.exists(lst):
        return
    low = []
    for line in open(lst):
        p = line.strip()[6:-1]
        try:
            x = np.asarray(Image.open(p).convert("L").resize((270, 480)), dtype=np.int16)
        except Exception:
            continue
        cov = float((np.abs(x - np.median(x)) > 18).mean())
        if cov < 0.17:
            low.append("%s %.2f" % (os.path.basename(p), cov))
    if low:
        print("DENSITY ADVISORY (look at these before the art director does): %s" % "; ".join(low), file=sys.stderr)


WAIVER_MIN = 40


def _cc():
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    import concept_check
    return concept_check


def _waiver_arg(argv):
    """the text after --concept-waiver (one quoted argument), or None."""
    if "--concept-waiver" not in argv:
        return None
    i = argv.index("--concept-waiver")
    return argv[i + 1].strip() if i + 1 < len(argv) else ""


def concept_gate(ID, waiver, stage="concept"):
    """Runs concept_check before anything is built or snapped. Returns the dict to merge into this submit's history row.
    Exits (refuses the submit) on a FAIL unless a written waiver is given or the gate is advisory (registry/concept-check.off)."""
    import concept_card
    allowed, why = concept_card.gate_ok(ID)
    if not allowed:
        sys.exit("storyboard.py %s: REFUSED: %s" % (stage, why))
    cc = _cc()
    ok, text, rep = cc.check_for_submit(ID)
    print(text, file=sys.stderr)
    extra = {"concept_check": rep["verdict"], "concept_window": [w["id"] for w in rep.get("window", [])]}
    if ok:
        return extra
    extra["concept_failed"] = rep.get("failed", [])
    if waiver is not None:
        if len(waiver) < WAIVER_MIN:
            sys.exit("storyboard.py submit: --concept-waiver needs a written reason of at least %d characters (what is deliberately the same, and why the story needs it); got %d." % (WAIVER_MIN, len(waiver)))
        extra["concept_waiver"] = {"reason": waiver, "by": os.environ.get("AGMM_REVIEWER_NAME") or os.environ.get("USER") or "unknown",
                                   "failed": rep.get("failed", [])}
        print("storyboard: concept_check FAIL waived by %s: %s" % (extra["concept_waiver"]["by"], waiver), file=sys.stderr)
        return extra
    if cc.enforcement() == "warn":
        print("storyboard: concept_check FAIL is ADVISORY only (registry/concept-check.off or AGMM_CONCEPT_CHECK=warn); continuing.", file=sys.stderr)
        extra["concept_advisory"] = True
        return extra
    sys.exit("storyboard.py submit: REFUSED by concept_check (%s). Fix the concept, or for a deliberate exception re-run with "
             "--concept-waiver \"<reason of %d+ characters>\"." % (", ".join(n[:2] for n in rep.get("failed", [])), WAIVER_MIN))


def sheet_gate(ID, waiver):
    """After the sheet exists: the declared ground must match its pixels (a concept cannot say cream and ship navy)."""
    cc = _cc()
    try:
        errs = cc.verify_sheet(ID)
    except Exception as e:
        print("storyboard: sheet check skipped (%s)" % e, file=sys.stderr)
        return {}
    if not errs:
        return {"concept_sheet": "match"}
    print("concept_check sheet verification FAILED: " + "; ".join(errs), file=sys.stderr)
    if waiver is not None and len(waiver) >= WAIVER_MIN:
        return {"concept_sheet": "mismatch waived", "concept_sheet_errors": errs}
    if cc.enforcement() == "warn":
        return {"concept_sheet": "mismatch advisory", "concept_sheet_errors": errs}
    sys.exit("storyboard.py submit: REFUSED: specs/%s/concept.json does not describe the sheet (%s). Correct concept.json (ground.hex, "
             "ground.beats_fraction, palette) to what you built, or build what it says; then submit again." % (ID, "; ".join(errs)))


def sheet_check_gate(ID, waiver):
    """6 Oct (forge2 v2): sheet_check on the frames just snapped: intra-short variety, subject fill, hero size, source text. A FAIL refuses the submit
    (waiver: --concept-waiver '<40+ chars>' covers it too; AGMM_SHEET_CHECK=warn or registry/sheet-check.off makes it advisory). A tool error never blocks."""
    try:
        sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
        import sheet_check as SC
        r = SC.check(ID, "auto")
    except Exception as e:
        print("storyboard: sheet_check skipped (%s)" % e, file=sys.stderr)
        return {}
    for w in r.get("warns", []):
        print("sheet_check WARN: " + w, file=sys.stderr)
    if r["ok"]:
        return {"sheet_check": "PASS", "sheet_check_nn": r["variety"]["nn_median"]}
    print("sheet_check FAILED:\n  " + "\n  ".join(r["fails"]), file=sys.stderr)
    off = os.path.exists(os.path.join(KIT, "registry", "sheet-check.off")) or os.environ.get("AGMM_SHEET_CHECK") == "warn"
    if waiver is not None and len(waiver) >= WAIVER_MIN:
        return {"sheet_check": "FAIL waived", "sheet_check_fails": r["fails"][:6]}
    if off:
        return {"sheet_check": "FAIL advisory", "sheet_check_fails": r["fails"][:6]}
    sys.exit("storyboard.py submit: REFUSED by sheet_check (variety / subject fill / hero size / source text): %s. Fix the beats it names (python3 kit/tools/sheet_check.py %s), then submit again." % (" | ".join(r["fails"])[:700], ID))


def _arg_after(argv, flag):
    if flag not in argv:
        return None
    i = argv.index(flag)
    return argv[i + 1].strip() if i + 1 < len(argv) else ""


def polish_gate(ID, waiver):
    """12 Oct (card polish-shorts): tools/polish_check.py on the BUILT package. A FAIL refuses the submit (waiver: --polish-waiver '<40+ chars>';
    AGMM_POLISH_CHECK=warn or registry/polish-check.off makes it advisory). WARN and INFO never refuse. A tool error never blocks."""
    out_json = os.path.join(KIT, "out", ID, "polish", "result.json")
    cmd = [sys.executable, os.path.join(KIT, "tools", "polish_check.py"), ID, "--quiet", "--json", out_json]
    if os.environ.get("AGMM_POLISH_RAW"):   # re-judge a saved run (tests, and a re-submit of an unchanged package): no cloud call
        cmd += ["--raw", os.environ["AGMM_POLISH_RAW"]]
    try:
        r = subprocess.run(cmd, cwd=KIT, capture_output=True, text=True, timeout=3000)
    except Exception as e:
        print("storyboard: polish_check skipped (%s)" % e, file=sys.stderr)
        return {"polish_check": "tool-error"}
    print(r.stdout, end="")
    if r.returncode == 0:
        return {"polish_check": "PASS", "polish_result": out_json}
    if r.returncode == 2:
        print("storyboard: polish_check tool error (not blocking): %s" % (r.stderr or "")[-400:], file=sys.stderr)
        return {"polish_check": "tool-error"}
    fails = [ln for ln in r.stdout.splitlines() if ln.startswith("FAIL")]
    extra = {"polish_check": "FAIL", "polish_result": out_json, "polish_fails": fails[:8]}
    if waiver is not None and len(waiver) >= WAIVER_MIN:
        extra["polish_check"] = "FAIL waived"
        extra["polish_waiver"] = {"reason": waiver, "by": os.environ.get("AGMM_REVIEWER_NAME") or os.environ.get("USER") or "unknown"}
        print("storyboard: polish_check FAIL waived: %s" % waiver, file=sys.stderr)
        return extra
    if waiver is not None:
        sys.exit("storyboard.py submit: --polish-waiver needs a written reason of at least %d characters; got %d." % (WAIVER_MIN, len(waiver)))
    if os.path.exists(os.path.join(KIT, "registry", "polish-check.off")) or os.environ.get("AGMM_POLISH_CHECK") == "warn":
        extra["polish_check"] = "FAIL advisory"
        print("storyboard: polish_check FAIL is ADVISORY only (registry/polish-check.off or AGMM_POLISH_CHECK=warn); continuing.", file=sys.stderr)
        return extra
    sys.exit("storyboard.py submit: REFUSED by polish_check (%d FAIL: pops, flickers, jitter, snaps, linear or too-fast moves, edge clipping, squashed images). "
             "Fix them (kit/lib/prologue.js AGP.motion has the standard entrance/exit set; WRITER-BRIEF.md 'Polish pass, 12 Oct'), re-run "
             "`python3 tools/polish_check.py %s --raw out/%s/polish/raw.json` to re-judge without a new cloud run only if the package did not change, "
             "or for a deliberate exception re-submit with --polish-waiver \"<reason of %d+ characters>\". First lines: %s"
             % (len(fails), ID, ID, WAIVER_MIN, " | ".join(f[:140] for f in fails[:3])))


def main():
    os.makedirs(REG, exist_ok=True)
    cmd, ID = sys.argv[1], sys.argv[2]
    rec_p = os.path.join(REG, ID + ".json")
    rec = json.load(open(rec_p)) if os.path.exists(rec_p) else {"id": ID, "history": []}
    extra = {}
    if cmd == "concept":
        concept_gate(ID, _waiver_arg(sys.argv))
        return
    if cmd == "submit":
        waiver = _waiver_arg(sys.argv)
        extra.update(concept_gate(ID, waiver))          # 6 Oct: sameness + pitch gate, before anything is built or snapped
        why = stale_build(ID)
        if why:
            sys.exit("storyboard.py submit: %s" % why)
        # root 13 Oct: S69/S72 (60.9/60.6 s) were approved and rendered before check 7 blocked arming; S70 was submitted at
        # 62.4 s by a maker who skipped precheck_all. The build owns the duration, so submit refuses it here, no waiver.
        try:
            _dur = float(json.load(open(os.path.join(KIT, "out", ID, "BUILD.json"))).get("dur"))
        except Exception:
            _dur = None
        if _dur is not None and _dur > 59.85:
            sys.exit("storyboard.py submit: REFUSED: built duration %.2f s > 59.85 s (gate check 7 WARNs 60-90 s and arming "
                     "takes PASS only). Shorten voice gaps or the end hold; never time-stretch. No waiver." % _dur)
        # 7 Oct, gpt-sol: catch source holds before spending a full render.
        # Qualified on unchanged S87 (known 1.6 s FAIL) and S52 (whole-source PASS),
        # using the existing gate's check-3 measure and public Actions only.
        motion = subprocess.run([sys.executable, os.path.join(KIT, "tools", "static_precheck.py"), ID],
                                cwd=KIT, capture_output=True, text=True)
        print(motion.stdout, end="")
        if motion.stderr:
            print(motion.stderr, end="", file=sys.stderr)
        if motion.returncode:
            sys.exit("storyboard.py submit: REFUSED by static_precheck (rc %d). Fix the named word-tied hold, "
                     "or resolve the capture/source-binding tool error; no waiver bypass. Encoded-master gate remains required." % motion.returncode)
        motion_path = os.path.join(KIT, "out", ID, "static-precheck", "result.json")
        motion_result = json.load(open(motion_path))
        if motion_result.get("verdict") != "PASS" or not motion_result.get("complete_grid") or motion_result.get("source_hash") != spec_hash(ID):
            sys.exit("storyboard.py submit: static_precheck is not a complete PASS bound to the current source")
        extra["source_static_check"] = {"verdict": "PASS", "source_hash": motion_result["source_hash"], "result": motion_path}
        if rec.get("state") == "returned" and rec.get("notes"):
            rec.setdefault("previous_returns", []).append({"decided": rec.get("decided"), "by": rec.get("by"), "notes": rec["notes"]})
        _sheet = sheet_of(ID)
        extra.update(sheet_gate(ID, waiver))
        extra.update(sheet_check_gate(ID, waiver))      # 6 Oct forge2 v2: additive refusal
        extra.update(polish_gate(ID, _arg_after(sys.argv, "--polish-waiver")))   # 12 Oct polish-shorts: additive refusal
        if extra.get("concept_waiver"):
            rec.setdefault("concept_waivers", []).append(dict(extra["concept_waiver"], at=time.strftime("%Y-%m-%dT%H:%M:%S")))
        rec.update(state="submitted", sheet=_sheet, p1_sheet=P1_SHEET, submitted=time.strftime("%Y-%m-%dT%H:%M:%S"),
                   spec_hash=spec_hash(ID))
        rec.pop("approved_hash", None)
        density_advisory(ID)
    elif cmd in ("approve", "return"):
        # only the art director or a reviewer decides (the inspector, 25 Sep: "storyboard.py approve lets anyone approve")
        if os.environ.get("AGMM_REVIEWER") != "1":
            sys.exit("storyboard.py %s: only the art director or a reviewer decides; set AGMM_REVIEWER=1 and AGMM_REVIEWER_NAME." % cmd)
        who = os.environ.get("AGMM_REVIEWER_NAME") or "reviewer"
        sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
        import reviewer_evidence
        _why = reviewer_evidence.check(who, ID, " ".join(sys.argv[3:]))
        if _why:
            sys.exit(_why)
        # root 30 Sep (miss #13): approving a CHANGED spec for a short that is ARMED in a future slot makes arm_ready withdraw the
        # armed version at once, before the new master exists: IG 17:30 + 20:30 went empty. Refuse unless the reviewer says so.
        if cmd == "approve" and os.environ.get("AGMM_REPLACE_ARMED") != "1":
            import glob as _g
            _today = time.strftime("%Y-%m-%d")
            for _pf in _g.glob(os.path.expanduser("~/alfred/auto-poster/carousel_v3/runtime/video-plan-*.json")):
                if _pf[-15:-5] < _today:
                    continue
                try:
                    _rows = json.load(open(_pf)).get("slots", [])
                except Exception:
                    continue
                for _r in _rows:
                    if _r.get("status") == "ARMED" and ("/%s-v2" % ID) in (_r.get("package") or ""):
                        sys.exit("REFUSED: %s is ARMED for %s %s. Approving a changed spec withdraws that post before a new master "
                                 "exists. Build + gate the new version first; if you really mean to replace it, re-run with "
                                 "AGMM_REPLACE_ARMED=1 (the slot empties until the new master passes)." % (ID, _pf[-15:-5], _r.get("slot")))
        rec.update(state="approved" if cmd == "approve" else "returned", notes=" ".join(sys.argv[3:]),
                   decided=time.strftime("%Y-%m-%dT%H:%M:%S"), by=who)
        if cmd == "approve":
            if rec.get("spec_hash") and rec["spec_hash"] != spec_hash(ID):
                sys.exit("storyboard.py approve: %s changed after it was submitted; it must be resubmitted before approval." % ID)
            rec["approved_hash"] = rec.get("spec_hash") or spec_hash(ID)
    rec["history"].append(dict({"at": time.strftime("%H:%M:%S"), "date": time.strftime("%Y-%m-%d"), "state": rec.get("state")}, **extra))
    if cmd != "status":
        json.dump(rec, open(rec_p, "w"), indent=1)
    print(json.dumps({k: rec.get(k) for k in ("id", "state", "by", "sheet", "notes")}, indent=1))


if __name__ == "__main__":
    main()
