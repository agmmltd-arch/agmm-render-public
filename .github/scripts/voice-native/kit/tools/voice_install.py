#!/usr/bin/env python3
"""voice_install.py <ID> | --status ID   (21 Oct 2026, root: "make produce install the sealed take itself")

The free voice route SEALS a take into crew/voice-hosted/receipts/<ID>.json (a pointer: run id, artifact id, artifact sha256, receipt sha256) and leaves the media in the 7-day
-GENERATED Actions artifact of the public render repo. The local gates (extract_story needs shorts/voice/<ID>/<ID>.words.json, precheck_all's voice step needs the wav and the
voicelead.json) read the take from shorts/voice/<ID>/. This installs it there, the way crew/intake_hosted_voice.py does, but deterministic and light (one artifact download, no
queue transition, no approval written):

  1. read the pointer; refuse unless voice_checks_complete and it names an artifact;
  2. one GitHub API read of the artifact (must exist, not expired, name == <intent>-GENERATED, digest == the pointer's);
  3. download the zip with `gh api` into crew/voice-hosted/intake/<intent>/generated.zip (kept; reused on a re-run) and verify its sha256 against the pointer's artifact_digest;
  4. inside: RECEIPT.json sha256 == the pointer's receipt_sha256; RESULT.json status FINISHED* (the free route writes FINISHED_LOCAL_CHECKS_PASS, listening UNJUDGED) with no hard_fail; <ID>.voicelead.json verdict PASS with no fails; every file named by the receipt's
     `generated` inventory is extracted, its size and sha256 checked against the inventory, and its producer mtime restored;
  5. install new-only (os.link, never overwrite; an existing file with the same sha is accepted, a different one refuses), RESULT.json last;
  6. CURRENT-TRIAGE.json (if the artifact carries one, sha checked) goes to triage_store.update exactly as the intake does; prepare.voicelead_prerequisite_issues must then be empty.
Never prints a secret; `gh` carries its own auth. Library: install(sid) -> dict; status(sid) -> (installed, sealed, reason)."""
import hashlib, json, os, re, subprocess, sys, zipfile

HERE = os.path.dirname(os.path.abspath(__file__))
KIT = os.path.dirname(HERE)
V2 = os.path.dirname(KIT)
PUBLIC = "agmmltd-arch/agmm-render-public"
ROOT = os.path.join(V2, "crew", "voice-hosted")
VOICE = os.path.join(V2, "shorts", "voice")


class InstallError(Exception):
    pass


def need(v, why):
    if not v:
        raise InstallError(why)


def sha(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for b in iter(lambda: f.read(1 << 20), b""):
            h.update(b)
    return h.hexdigest()


def pointer(sid):
    p = os.path.join(ROOT, "receipts", sid + ".json")
    try:
        return json.load(open(p))
    except (OSError, ValueError):
        return None


def status(sid):
    """(installed, sealed, reason): installed = wav + words.json + a PASS voicelead + RESULT FINISHED already under shorts/voice/<ID>; sealed = a complete pointer exists"""
    d = os.path.join(VOICE, sid)
    inst = all(os.path.exists(os.path.join(d, f)) for f in (sid + ".wav", sid + ".words.json", sid + ".voicelead.json", "RESULT.json"))
    ptr = pointer(sid)
    sealed = bool(ptr and ptr.get("voice_checks_complete") is True and ptr.get("artifact_id") and ptr.get("artifact_digest"))
    return inst, sealed, ("installed" if inst else ("sealed in crew/voice-hosted, not installed" if sealed else "no sealed take"))


def gh_json(path):
    r = subprocess.run(["gh", "api", path], capture_output=True, text=True, timeout=90)
    need(r.returncode == 0, "gh api %s failed: %s" % (path, (r.stderr or "")[:160]))
    return json.loads(r.stdout)


def download(ptr, work):
    arch = os.path.join(work, "generated.zip")
    if os.path.exists(arch) and "sha256:" + sha(arch) == ptr["artifact_digest"]:
        return arch
    art = gh_json("repos/%s/actions/artifacts/%s" % (PUBLIC, ptr["artifact_id"]))
    need(not art.get("expired"), "the sealed take's artifact has expired (7 days): re-seal the voice")
    need(art.get("name") == ptr["intent"] + "-GENERATED" and art.get("digest") == ptr["artifact_digest"], "artifact name or digest differs from the pointer")
    os.makedirs(work, exist_ok=True)
    tmp = arch + ".download-partial"
    with open(tmp, "wb") as out:
        r = subprocess.run(["gh", "api", "repos/%s/actions/artifacts/%s/zip" % (PUBLIC, ptr["artifact_id"])], stdout=out, stderr=subprocess.PIPE, timeout=900)
    need(r.returncode == 0, "artifact download failed: %s" % (r.stderr or b"")[:160])
    need("sha256:" + sha(tmp) == ptr["artifact_digest"], "downloaded artifact sha256 differs from the pointer's artifact_digest")
    os.replace(tmp, arch)
    return arch


def install(sid):
    need(sys.platform != "darwin", "hosted-only media policy: do not install programme audio on this Mac")
    ptr = pointer(sid)
    need(ptr and ptr.get("id") == sid, "no receipt pointer crew/voice-hosted/receipts/%s.json" % sid)
    need(ptr.get("voice_checks_complete") is True, "the sealed voice has not completed its checks")
    inst, _, _ = status(sid)
    if inst:
        return {"id": sid, "installed": "already", "files": []}
    work = os.path.join(ROOT, "intake", ptr["intent"])
    arch = download(ptr, work)
    with zipfile.ZipFile(arch) as z:
        names = [i.filename for i in z.infolist()]
        need(all(not n.startswith("/") and ".." not in n.split("/") for n in names), "unsafe archive member")
        raw = z.read("RECEIPT.json")
        need(hashlib.sha256(raw).hexdigest() == ptr["receipt_sha256"], "RECEIPT.json sha256 differs from the pointer's receipt_sha256")
        receipt = json.loads(raw)
        need(receipt.get("id") == sid, "receipt names another short")
        result = json.loads(z.read("generated/RESULT.json"))
        lead = json.loads(z.read("generated/%s.voicelead.json" % sid))
        need(str(result.get("status")).startswith("FINISHED") and not result.get("hard_fail") and lead.get("verdict") == "PASS" and not lead.get("fails"),
             "the sealed take is not FINISHED (local checks pass) / voicelead PASS (status %r)" % result.get("status"))
        rows = {r["path"]: r for r in receipt["generated"]}
        req = {sid + s for s in (".wav", ".words.json", ".receipt.json", ".voicelead.json")} | {"RESULT.json"}
        need(req <= rows.keys(), "the receipt inventory lacks %s" % sorted(req - rows.keys()))
        allowed = {n: r for n, r in rows.items() if "/" not in n and (re.fullmatch(r"P[0-9]{2}\.(?:wav|words\.json|receipt\.json)", n) or n == "RESULT.json"
                                                                     or (n.startswith(sid + ".") and n.endswith((".json", ".wav", ".txt"))))}
        staged = os.path.join(work, "files")
        os.makedirs(staged, exist_ok=True)
        order = sorted(allowed, key=lambda n: (n == "RESULT.json", n))
        for n in order:
            r = allowed[n]
            t = os.path.join(staged, n)
            if not os.path.exists(t):
                with z.open("generated/" + n) as src, open(t, "xb") as out:
                    while b := src.read(1 << 20):
                        out.write(b)
            need(os.path.getsize(t) == r["bytes"] and sha(t) == r["sha256"], "generated file %s differs from the receipt inventory" % n)
            if isinstance(r.get("original_mtime_ns"), int) and r["original_mtime_ns"] > 0:
                os.utime(t, ns=(r["original_mtime_ns"], r["original_mtime_ns"]))
        triage = {}
        if "CURRENT-TRIAGE.json" in names and receipt.get("triage_sha256"):
            rawt = z.read("CURRENT-TRIAGE.json")
            need(hashlib.sha256(rawt).hexdigest() == receipt["triage_sha256"], "triage sha256 differs from the receipt")
            triage = json.loads(rawt)
            need(set(triage) <= {sid}, "a foreign triage entry")
    piece = os.path.join(VOICE, sid)
    os.makedirs(piece, exist_ok=True)
    done = []
    for n in order:
        dst = os.path.join(piece, n)
        if os.path.exists(dst):
            need(sha(dst) == allowed[n]["sha256"], "%s already exists with other content: never replaced" % n)
            continue
        os.link(os.path.join(staged, n), dst)           # new-only; RESULT.json last
        done.append(n)
    sys.path[:0] = [os.path.join(VOICE, "tooling")]
    if triage:
        import triage_store
        triage_store.update(VOICE, triage)
    import prepare
    issues = prepare.voicelead_prerequisite_issues(VOICE, sid)
    need(not issues, "voice prerequisites reject the installed take: " + "; ".join(issues))
    return {"id": sid, "installed": "new", "files": done, "run_id": ptr.get("run_id")}


def main():
    a = sys.argv[1:]
    if not a:
        print(__doc__)
        return 2
    if a[0] == "--status":
        print(status(a[1]))
        return 0
    try:
        print(json.dumps(install(a[0]), indent=1))
        return 0
    except InstallError as e:
        print("voice_install REFUSED %s: %s" % (a[0], e))
        return 1


if __name__ == "__main__":
    sys.exit(main())
