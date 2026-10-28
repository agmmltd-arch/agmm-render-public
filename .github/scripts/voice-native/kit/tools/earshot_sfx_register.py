#!/usr/bin/env python3
"""earshot_sfx_register.py - put earshot's code-made, measured SFX into the kit's registries (26 Oct 2026).

  earshot_sfx_register.py import ART_DIR   ART_DIR = the Actions artifact of `agmm-earshot-check.yml kind=sfx` (earshot-sfx-registry.json + takes/)
  earshot_sfx_register.py check            prove the registry: files exist, sha256 match, onset/peak/end measured, merged library consistent

Writes
  sound/library/earshot/*.wav              the takes (earshot 0.4.0, MIT, synthesised in code; no recording, no model)
  sound/library-earshot.json               library-schema items (id es_<role>_NN, onset_ms, anchor_ms, anchor, true_peak_db, sha256, licence)
  sound/library.earshot-merged.json        library.json + the earshot items (GENERATED; what mix2 reads when AGMM_SFX_SOURCE=earshot)
  kit/registry/earshot-sfx.json            role -> ids with measured onset / peak / end; engine kind -> role map. The engine and fetch_assets read this.
sound/library.json itself is never touched: the hosted sound audit pins its sha256.
"""
import hashlib, json, os, shutil, sys

TOOLS = os.path.dirname(os.path.abspath(__file__))
KIT = os.path.dirname(TOOLS)
V2 = os.path.dirname(KIT)
SOUND = os.path.join(V2, "sound")
REG = os.path.join(KIT, "registry", "earshot-sfx.json")
LIB_ES = os.path.join(SOUND, "library-earshot.json")
LIB_MERGED = os.path.join(SOUND, "library.earshot-merged.json")
VERSION = "earshot-0.4.0-2026-10-26"

# the format engine's cue kinds -> earshot launch-kit roles (kinds with no earshot role keep the Sonniss / synthesised library)
KIND_ROLE = {"whoosh": ["whoosh.short"], "tick": ["tick"], "pop": ["pop"], "stamp": ["hit"], "ping": ["click.confirm"], "slam": ["drop", "land"],
             "click": ["click"], "type": ["key"], "count": ["text"]}
PEAK_ROLES = {"whoosh.short", "whoosh.long", "riser", "swell"}      # the registry's own align for these is the peak


PER_ROLE_CAP = 80
LIB_OV = os.path.join(SOUND, "library-openverse.json")
LIB_ESV = os.path.join(SOUND, "library-earshot-var.json")      # seed variants of the code-made bank (second source), unique takes
REG_LIB = os.path.join(KIT, "registry", "sfx-library.json")
# earshot bank role (launch kit) -> library role(s) it serves as the SECOND source
BANK_ROLE = {"whoosh.short": ["whoosh"], "tick": ["tick"], "tick.crisp": ["tick"], "pop": ["pop"], "hit": ["stamp", "impact"], "drop": ["impact"], "land": ["impact", "stamp"],
             "click.confirm": ["ding"], "key": ["typing"], "key.space": ["typing"], "click": ["tick"], "riser": ["riser"]}


def rebuild_merged():
    """library.json + library-earshot.json + library-openverse.json -> library.earshot-merged.json (GENERATED; what mix2 / build_short read when AGMM_SFX_SOURCE is earshot or openverse)"""
    base = json.load(open(os.path.join(SOUND, "library.json")))
    extra = []
    for p in (LIB_ES, LIB_ESV, LIB_OV):
        if os.path.exists(p):
            extra += json.load(open(p))["items"]
    merged = dict(base)
    merged["items"] = [i for i in base["items"] if not (i["id"].startswith("es_") or i["id"].startswith("ov_"))] + extra
    merged["count"] = len(merged["items"])
    merged["generated_by"] = "earshot_sfx_register.py: library.json + library-earshot.json + library-openverse.json, never edit"
    json.dump(merged, open(LIB_MERGED, "w"), indent=1)
    return len(merged["items"])


def slug(role):
    return role.replace(".", "_")


def do_import(art):
    reg = json.load(open(os.path.join(art, "earshot-sfx-registry.json")))
    dst_dir = os.path.join(SOUND, "library", "earshot")
    os.makedirs(dst_dir, exist_ok=True)
    items, roles = [], {}
    for role, spec in reg["roles"].items():
        ids = []
        for n, t in enumerate(spec["takes"], 1):
            sid = "es_%s_%02d" % (slug(role), n)
            src = os.path.join(art, "takes", t["file"])
            fn = sid + ".wav"
            shutil.copyfile(src, os.path.join(dst_dir, fn))
            sha = hashlib.sha256(open(os.path.join(dst_dir, fn), "rb").read()).hexdigest()
            assert sha == t["sha256"], "sha mismatch " + sid
            on, pk, en = round(t["onset_s"] * 1000, 2), round(t["peak_s"] * 1000, 2), round(t["end_s"] * 1000, 2)
            anchor = "peak" if spec.get("align") == "peak" else "onset"
            items.append({"id": sid, "category": "es_" + slug(role), "path": "library/earshot/" + fn,
                          "license": "MIT (earshot 0.4.0); synthesised in code, no recording", "licence": "MIT (earshot 0.4.0); synthesised in code, no recording",
                          "license_url": "https://github.com/Leonxlnx/earshot/blob/591fa3e028032e6dce56620a20e932e35667e8d8/LICENSE",
                          "source_url": "https://github.com/Leonxlnx/earshot", "source_path": None,
                          "derived_technique": "earshot forge bank %s, kit launch role %s, seed %s%s" % (spec["sound"], role, t.get("seed"), (", pitch " + str(t["pitch"])) if t.get("pitch") else ""),
                          "pan_hint": 0.0, "library_version": VERSION, "note": spec.get("note"), "layers": None,
                          "duration_s": round(t["dur_s"], 4), "duration": round(t["dur_s"], 4), "onset_ms": on, "peak_ms": pk, "end_ms": en,
                          "anchor": anchor, "anchor_ms": pk if anchor == "peak" else on, "true_peak_db": t.get("true_peak_dbtp"),
                          "lufs_integrated": t.get("lufs"), "lufs": t.get("lufs"), "lufs_reliable": t.get("lufs") is not None, "l50_lufs": t.get("l50_lufs"),
                          "mean_volume_dbfs": None, "sha256": sha, "audit_flags": t.get("checks") or [], "pitch": t.get("pitch"),
                          "measured_by": "earshot kit render (onset / peak / end), earshot measure (true peak, LUFS)"})
            ids.append(sid)
        roles[role] = {"ids": ids, "sound": spec["sound"], "align": spec.get("align"), "offset_ms": spec.get("offset_ms"), "bed_db": spec.get("bed_db"),
                       "level_db": spec.get("level_db"), "min_gap_ms": spec.get("min_gap_ms")}
    json.dump({"version": VERSION, "count": len(items), "items": items}, open(LIB_ES, "w"), indent=1)
    rebuild_merged()
    os.makedirs(os.path.dirname(REG), exist_ok=True)
    json.dump({"version": VERSION, "source": reg["source"], "licence": reg["licence"], "default": "off (AGMM_SFX_SOURCE=earshot turns it on)",
               "kinds": {k: [i for r in rs for i in roles[r]["ids"]] for k, rs in KIND_ROLE.items()}, "roles": roles,
               "items": {i["id"]: {k: i[k] for k in ("category", "onset_ms", "peak_ms", "end_ms", "anchor", "anchor_ms", "true_peak_db", "l50_lufs", "duration_s", "sha256")} for i in items}},
              open(REG, "w"), indent=1)
    print("imported %d takes, %d roles; kinds %s" % (len(items), len(roles), {k: len(v) for k, v in json.load(open(REG))["kinds"].items()}))


def do_import_ov(roots):
    """roots = directories holding one folder per artifact (accepted.json, rejected.json, summary.json, wav/). Openverse folders are merged per role across roots;
    a folder whose entries come from earshot-bank is the seed-variant second source. Writes sound/library/openverse/*.wav (USABLE only), sound/library-openverse.json,
    sound/library/earshot/*.wav + sound/library-earshot-var.json and kit/registry/sfx-library.json.
    USABLE = cc0 / pdm (root, 26 Oct: CC BY needs the attribution in the posted caption, not wired for every platform yet) or the MIT code-made bank.
    BY / BY-SA files stay in the registry, usable=false, so the licence record is complete but the engine can never pick them."""
    import glob
    rules = json.load(open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "sfx-roles.json")))
    dst_dir = os.path.join(SOUND, "library", "openverse")
    es_dir = os.path.join(SOUND, "library", "earshot")
    os.makedirs(dst_dir, exist_ok=True)
    os.makedirs(es_dir, exist_ok=True)
    for f in glob.glob(os.path.join(dst_dir, "*.wav")):
        os.remove(f)                  # the openverse folder is rebuilt from the artifacts every import
    items, lib_items, rejected, summary, var_items = {}, [], {}, {}, []
    per_role, bank_acc = {}, []
    for root in roots:
        for d in sorted(glob.glob(os.path.join(root, "*"))):
            if not os.path.exists(os.path.join(d, "accepted.json")):
                continue
            acc = json.load(open(os.path.join(d, "accepted.json")))
            sm = json.load(open(os.path.join(d, "summary.json")))
            if acc and acc[0]["source"].get("provider") == "earshot-bank":
                bank_acc += [dict(a, _dir=d) for a in acc]
                continue
            rej = json.load(open(os.path.join(d, "rejected.json")))
            role = sm["role"]
            for r in acc:
                per_role.setdefault(role, {})[r["id"]] = dict(r, _dir=d)
            summary.setdefault(role, {"role": role, "candidates": 0, "accepted": 0, "rejected": 0, "reasons": {}})
            S_ = summary[role]
            S_["candidates"] += sm["candidates"]; S_["accepted"] += sm["accepted"]; S_["rejected"] += sm["rejected"]
            for k, v in sm["reasons"].items():
                S_["reasons"][k] = S_["reasons"].get(k, 0) + v
            rejected.setdefault(role, {})
            for r in rej:
                rejected[role].setdefault(r["reason"], []).append({"id": r["id"], "detail": r["detail"], "landing_url": r["landing_url"]})
    for role, recs in per_role.items():
        allr = sorted(recs.values(), key=lambda r: -r["role_match"]["z"])
        usable = [r for r in allr if r["source"]["licence_slug"] in ("cc0", "pdm")]
        keep = usable[:PER_ROLE_CAP]
        keep_ids = {r["id"] for r in keep}
        summary[role].update(usable=len(usable), kept=len(keep), by_unusable=len(allr) - len(usable), surplus=len(usable) - len(keep))
        for r in allr:
            S = r["source"]
            if S["licence_slug"] not in ("cc0", "pdm", "by", "by-sa"):
                raise SystemExit("refusing licence %s on %s" % (S["licence_slug"], r["id"]))
            anchor = "peak" if role == "riser" else "onset"
            base = dict(r, source_kind="openverse", anchor=anchor, anchor_ms=r["peak_ms"] if anchor == "peak" else r["onset_ms"], usable=r["id"] in keep_ids)
            base.pop("_dir", None)
            if r["id"] not in keep_ids:
                if S["licence_slug"] not in ("cc0", "pdm"):
                    base["unusable_reason"] = "CC BY attribution is not wired into the posted caption on every platform (root, 26 Oct)"
                    items[r["id"]] = base
                continue
            fn = r["id"] + ".wav"
            shutil.copyfile(os.path.join(r["_dir"], "wav", r["file"]), os.path.join(dst_dir, fn))
            sha = hashlib.sha256(open(os.path.join(dst_dir, fn), "rb").read()).hexdigest()
            assert sha == r["sha256_trim"], "sha mismatch " + r["id"]
            base["sha256"] = sha
            lib_items.append({"id": r["id"], "category": "ov_" + role, "path": "library/openverse/" + fn, "license": S["licence"], "licence": S["licence"], "license_url": S["licence_url"],
                              "source_url": S["source_url"], "landing_url": S["landing_url"], "creator": S["creator"], "attribution": S["attribution"], "derived_technique": "Openverse (%s) trimmed and measured by earshot" % S["provider"],
                              "pan_hint": 0.0, "library_version": VERSION, "note": r["description"][:160], "layers": None, "duration_s": r["duration_s"], "duration": r["duration_s"],
                              "onset_ms": r["onset_ms"], "peak_ms": r["peak_ms"], "end_ms": r["end_ms"], "anchor": anchor, "anchor_ms": base["anchor_ms"],
                              "true_peak_db": r["true_peak_db"], "lufs_integrated": r["lufs"], "lufs": r["lufs"], "lufs_reliable": r["lufs"] is not None, "l50_lufs": r["l50_lufs"],
                              "mean_volume_dbfs": None, "sha256": sha, "measured_by": "earshot find / measure / describe / match"})
            items[r["id"]] = base
    json.dump({"version": VERSION, "count": len(lib_items), "items": lib_items}, open(LIB_OV, "w"), indent=1)
    # the code-made bank: the 72 kit takes (no scores) and the seed variants (scored), both MIT and usable
    done = set()
    for a in bank_acc:
        sid = a["id"]
        if sid not in done:
            done.add(sid)
            fn = sid + ".wav"
            shutil.copyfile(os.path.join(a["_dir"], "wav", a["file"]), os.path.join(es_dir, fn))
            sha = hashlib.sha256(open(os.path.join(es_dir, fn), "rb").read()).hexdigest()
            assert sha == a["sha256_trim"], "sha mismatch " + sid
            var_items.append({"id": sid, "category": "es2_" + sid.split("_")[1], "path": "library/earshot/" + fn, "license": "MIT (earshot 0.4.0); synthesised in code, no recording",
                              "licence": "MIT (earshot 0.4.0); synthesised in code, no recording", "license_url": "https://github.com/Leonxlnx/earshot/blob/591fa3e028032e6dce56620a20e932e35667e8d8/LICENSE",
                              "source_url": "https://github.com/Leonxlnx/earshot", "derived_technique": "earshot forge bank %s, seed %s" % (a["bank_member"], a["seed"]), "pan_hint": 0.0,
                              "library_version": VERSION, "duration_s": a["duration_s"], "duration": a["duration_s"], "onset_ms": a["onset_ms"], "peak_ms": a["peak_ms"], "end_ms": a["end_ms"],
                              "anchor": "peak" if a["role"] == "riser" else "onset", "anchor_ms": a["peak_ms"] if a["role"] == "riser" else a["onset_ms"], "true_peak_db": a["true_peak_db"],
                              "lufs_integrated": a["lufs"], "lufs": a["lufs"], "lufs_reliable": a["lufs"] is not None, "l50_lufs": a["l50_lufs"], "mean_volume_dbfs": None, "sha256": sha,
                              "measured_by": "earshot bank render + measure + match"})
        r_ = a["role"]
        anchor = "peak" if r_ == "riser" else "onset"
        items[sid + "@" + r_] = dict(a, source_kind="earshot-bank", usable=True, anchor=anchor, anchor_ms=a["peak_ms"] if anchor == "peak" else a["onset_ms"], sha256=a["sha256_trim"])
        items[sid + "@" + r_].pop("_dir", None)
    json.dump({"version": VERSION, "count": len(var_items), "items": var_items}, open(LIB_ESV, "w"), indent=1)
    es_reg = json.load(open(REG)) if os.path.exists(REG) else {"roles": {}, "items": {}}
    for brole, spec in es_reg.get("roles", {}).items():
        for lr in BANK_ROLE.get(brole, []):
            for sid in spec["ids"]:
                m = es_reg["items"][sid]
                items.setdefault(sid + "@" + lr, {"id": sid, "role": lr, "source_kind": "earshot-bank", "usable": True, "file": sid + ".wav", "onset_ms": m["onset_ms"], "peak_ms": m["peak_ms"], "end_ms": m["end_ms"],
                                                  "anchor": m["anchor"], "anchor_ms": m["anchor_ms"], "l50_lufs": m["l50_lufs"], "true_peak_db": m["true_peak_db"], "duration_s": m["duration_s"], "sha256": m["sha256"],
                                                  "role_match": None, "source": {"licence": "MIT (earshot 0.4.0), made in code", "licence_slug": "mit", "provider": "earshot"}})
    kind_role = {k: r for r, v in rules.items() for k in v["kinds"]}
    json.dump({"version": VERSION, "generated": __import__("time").strftime("%Y-%m-%dT%H:%M:%S"), "default": "off (AGMM_SFX_SOURCE=openverse turns it on)",
               "usable_licences": ["cc0", "pdm", "mit"], "sources": {"openverse": "cc0 / pdm only are usable (by / by-sa recorded, usable=false); trimmed + measured by earshot on Actions", "earshot-bank": "code-made, MIT: the 72 kit takes + seed variants"},
               "roles": rules, "kind_role": kind_role, "summary": summary,
               "rejected": {r: {k: {"n": len(v), "examples": v[:3]} for k, v in d_.items()} for r, d_ in rejected.items()}, "items": items}, open(REG_LIB, "w"), indent=1)
    n = rebuild_merged()
    cnt = {r: [sum(1 for i in items.values() if i["role"] == r and i["source_kind"] == "openverse" and i["usable"]), sum(1 for i in items.values() if i["role"] == r and i["source_kind"] == "earshot-bank")] for r in rules}
    print("usable Openverse / bank per role: %s; merged library %d items" % (cnt, n))


def do_apply_remeasure(path):
    """remeasured.json (Actions, sfx_remeasure.py) -> onset_ms / peak_ms / anchor_ms by the audit's own definition (first sample >= 6% of peak; loudest 20 ms RMS),
    in library-openverse / library-earshot(-var) / registry/sfx-library.json / registry/earshot-sfx.json, then the merged library. The earshot value stays as onset_ms_earshot."""
    rem = json.load(open(path))
    n = 0

    def upd(it, key):
        nonlocal n
        r = rem.get(key)
        if not r:
            return
        it.setdefault("onset_ms_earshot", it.get("onset_ms"))
        it.setdefault("peak_ms_earshot", it.get("peak_ms"))
        it["onset_ms"], it["peak_ms"] = r["onset_ms"], r["peak_ms"]
        if "anchor_ms" in it:
            it["anchor_ms"] = r["peak_ms"] if it.get("anchor") == "peak" else r["onset_ms"]
        n += 1
    for p in (LIB_OV, LIB_ES, LIB_ESV):
        if os.path.exists(p):
            d = json.load(open(p))
            for it in d["items"]:
                upd(it, it["id"])
            json.dump(d, open(p, "w"), indent=1)
    for p in (REG_LIB, REG):
        if os.path.exists(p):
            d = json.load(open(p))
            for k, it in d["items"].items():
                upd(it, it.get("id") if isinstance(it, dict) and it.get("id") else k.split("@")[0])
            json.dump(d, open(p, "w"), indent=1)
    print("remeasured %d entries; merged library %d items" % (n, rebuild_merged()))


def do_apply_thin(path):
    """verdict.json (Actions, sfx_thin_check.py) -> registry items: usable=false with reason "thin-vs-pilots" / "harsh-vs-pilots" plus the measured fullness / harshness.
    Never touches library json files: an unusable sound is simply never picked. Idempotent: earlier thin verdicts are cleared first, so a re-run on a larger set stays true."""
    v = json.load(open(path))
    d = json.load(open(REG_LIB))
    n_bad = n = 0
    for k, it in d["items"].items():
        if it.get("unusable_reason", "").endswith("-vs-pilots"):
            it["usable"] = True
            it.pop("unusable_reason", None)
        row = v.get(k)
        if not row:
            continue
        n += 1
        it["fullness_db"], it["harshness_db"] = row["fullness_db"], row["harshness_db"]
        if not row["usable"] and it.get("usable", True):
            it["usable"] = False
            it["unusable_reason"] = "%s (%s)" % (row["reason"], row["detail"])
            n_bad += 1
    json.dump(d, open(REG_LIB, "w"), indent=1)
    cnt = {}
    for it in d["items"].values():
        if it.get("usable"):
            c = cnt.setdefault(it["role"], [0, 0])
            c[0 if it["source_kind"] == "openverse" else 1] += 1
    print("thin check: %d judged, %d newly unusable; usable [openverse, bank] per role: %s" % (n, n_bad, cnt))


def problems(reg, es, merged, base):
    bad = []
    for sid, m in reg["items"].items():
        it = es.get(sid)
        if not it or sid not in merged:
            bad.append("missing " + sid); continue
        p = os.path.join(SOUND, it["path"])
        if not os.path.exists(p) or hashlib.sha256(open(p, "rb").read()).hexdigest() != m["sha256"]:
            bad.append("file/sha " + sid)
        o, e = it.get("onset_ms"), it.get("end_ms")
        if o is None or it.get("peak_ms") is None or e is None or not e > o >= 0:
            bad.append("unmeasured " + sid)
        if it["anchor"] == "peak" and it["anchor_ms"] != it.get("peak_ms"):
            bad.append("anchor " + sid)
        if sid in base:
            bad.append("id collides with library.json " + sid)
    for k, ids in reg["kinds"].items():
        if not ids or any(i not in es for i in ids):
            bad.append("kind %s has an unknown id" % k)
    return bad


def do_check():
    import copy
    reg = json.load(open(REG))
    es = {i["id"]: i for i in json.load(open(LIB_ES))["items"]}
    merged = {i["id"]: i for i in json.load(open(LIB_MERGED))["items"]}
    base = {i["id"] for i in json.load(open(os.path.join(SOUND, "library.json")))["items"]}
    bad = problems(reg, es, merged, base)
    # the check must be able to fail: unmeasure one onset, break one anchor, drop one id from the merged library
    sid = sorted(es)[0]
    es2, mg2 = copy.deepcopy(es), copy.deepcopy(merged)
    es2[sid]["onset_ms"] = None
    pk = next(i for i in sorted(es2) if es2[i]["anchor"] == "peak")
    es2[pk]["anchor_ms"] = -1.0
    del mg2[sorted(es)[1]]
    mut = problems(reg, es2, mg2, base)
    caught = sum(1 for m in mut if m.startswith(("unmeasured", "anchor", "missing")))
    print("earshot sfx registry: %d items, %d kinds, problems %s; mutation probe caught %d of 3: %s" % (len(es), len(reg["kinds"]), bad, caught, mut))
    return 0 if not bad and caught == 3 else 1


if __name__ == "__main__":
    if len(sys.argv) >= 3 and sys.argv[1] == "import":
        do_import(sys.argv[2])
    elif len(sys.argv) >= 3 and sys.argv[1] == "import-ov":
        do_import_ov(sys.argv[2:])
    elif len(sys.argv) >= 3 and sys.argv[1] == "apply-thin":
        do_apply_thin(sys.argv[2])
    elif len(sys.argv) >= 3 and sys.argv[1] == "apply-remeasure":
        do_apply_remeasure(sys.argv[2])
    elif len(sys.argv) >= 2 and sys.argv[1] == "check":
        sys.exit(do_check())
    else:
        print(__doc__)
