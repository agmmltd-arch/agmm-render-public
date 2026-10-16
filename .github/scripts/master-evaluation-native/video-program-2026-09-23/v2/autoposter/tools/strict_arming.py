"""Create and consume the strict better-than-last release receipt.

This module is intentionally independent of media tooling. The comparator owns its
metrics; this layer freezes the final target platform and binds the decision to the
candidate's source, FINAL, resolved build, reviewer approval and staged bytes.
"""
from __future__ import annotations

import hashlib
import json
import subprocess
import sys
from datetime import datetime
from pathlib import Path

SCHEMA = "agmm-strict-better-than-last-arm-receipt-v1"
RECEIPT_NAME = "strict-better-than-last-arm-receipt.json"
PLATFORMS = ("instagram", "facebook", "linkedin", "tiktok", "youtube")
# Baton 13 Oct (S40/S63/S82/C13 refused "no dimension is AHEAD"): better_than_last ahead_of_latest_status() returns 'n/a'
# when every metric the candidate shares with the latest same-platform short is an advisory one (the voice critic rows and
# the gate critic / density_cov rows made advisory on 6 Oct), and records it under exactly this advisory string. The
# comparator, not this layer, owns which metrics are advisory; the string is only written in that branch, so a hard metric
# compared with no AHEAD still emits the strict failure ahead_of_latest:none and is already refused by the strict-failures
# check in _eligible. If the comparator ever renames the advisory this fails CLOSED (back to refusing), never open.
AHEAD_NA_ADVISORY = "ahead_of_latest:not_applicable_all_compared_rows_advisory"


def _ahead_not_applicable(output: dict) -> bool:
    advisories = output.get("advisories")
    return isinstance(advisories, list) and AHEAD_NA_ADVISORY in advisories


def sha_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def canonical_sha(value) -> str:
    raw = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(raw).hexdigest()


# Claude 5 Oct: the comparator reports its platform KEY (youtube_shorts, linkedin_feed, instagram_reels, facebook_reels,
# tiktok) while arming freezes the short name (youtube, linkedin, ...). Comparing them raw refused every fresh short except
# TikTok with "identity does not match" (S02, S12 at 17:19). Normalise both sides before comparing.
_PKEY = {"youtube_shorts": "youtube", "linkedin_feed": "linkedin", "instagram_reels": "instagram",
         "facebook_reels": "facebook"}


def _plat(name) -> str:
    return _PKEY.get(str(name or ""), str(name or ""))


def _eligible(output: dict, sid: str, platform: str) -> tuple[bool, str]:
    if not isinstance(output, dict) or output.get("id") != sid or _plat(output.get("platform")) != _plat(platform):
        return False, "strict output identity does not match short and frozen platform"
    if output.get("strict_verdict") != "PASS":
        return False, "strict comparator did not PASS"
    latest = output.get("latest_same_platform")
    if not isinstance(latest, dict) or not latest.get("id") or latest.get("id") == sid:
        return False, "latest approved same-platform baseline is absent or is the candidate"
    rows = output.get("latest_rows")
    if not isinstance(rows, list) or not rows:
        return False, "same-platform comparison rows are absent"
    failures = output.get("strict_failures")
    if not isinstance(failures, list):
        return False, "strict failures are malformed"
    exception = output.get("exception")
    exception_ok = isinstance(exception, dict) and exception.get("valid") is True
    if failures and not exception_ok:
        return False, "strict failures remain without a valid comparator exception"
    if not any(row.get("verdict") == "AHEAD" for row in rows) and not exception_ok \
            and not _ahead_not_applicable(output):
        return False, "no dimension is AHEAD"
    # Sensory gaps are advisories in the comparator since 5 Oct (critic_sound had no producer after Jev was retired, so a
    # hard [] requirement blocked every master forever). The gate's own audio checks 12/13/15 and the reviewer still apply.
    if not isinstance(output.get("sensory_missing"), list):
        return False, "post-FINAL sensory metrics are malformed"
    return True, ""


def produce_receipt(*, sid: str, platform: str, source: Path, final: Path, resolved: Path,
                    item: dict, review_entry: dict, arm_started_at: str, comparator: Path,
                    scoreboard: Path, runner=None, now_fn=None) -> tuple[dict | None, str]:
    """Run strict comparator on an explicit final platform and bind its PASS to current artifacts."""
    if platform not in PLATFORMS:
        return None, "frozen platform is invalid"
    reviewer = str(review_entry.get("reviewer") or "").strip()
    maker = str(review_entry.get("maker") or "").strip()
    verdict = str(review_entry.get("verdict") or "").strip().upper()
    if not reviewer or not maker or reviewer.casefold() == maker.casefold() or not verdict.startswith("PASS"):
        return None, "latest independent reviewer PASS is missing or reviewer equals maker"
    try:
        if not source.is_file() or not final.is_file() or not resolved.is_file():
            return None, "source, FINAL, or resolved.json is missing"
        source_hash, final_hash, resolved_hash = (sha_file(source), sha_file(final), sha_file(resolved))
        if item.get("source_sha256") != source_hash:
            return None, "maker source hash differs from the current item record"
    except OSError as exc:
        return None, f"cannot hash candidate inputs: {exc}"
    command = [sys.executable, str(comparator), sid, "--refresh", "--strict", "--json", "--platform", platform]
    run = runner or subprocess.run
    try:
        done = run(command, capture_output=True, text=True, timeout=240)
    except (OSError, subprocess.TimeoutExpired) as exc:
        return None, f"strict comparator failed: {exc}"
    if done.returncode != 0:
        return None, f"strict comparator exit {done.returncode}: {(done.stderr or done.stdout)[-500:]}"
    try:
        strict_output = json.loads(done.stdout)
    except (TypeError, ValueError):
        return None, "strict comparator did not return JSON"
    ok, why = _eligible(strict_output, sid, platform)
    if not ok:
        return None, why
    # Re-hash after the comparator: a concurrent edit must not inherit the comparator's PASS.
    try:
        if (sha_file(source), sha_file(final), sha_file(resolved)) != (source_hash, final_hash, resolved_hash):
            return None, "source, FINAL, or resolved.json changed during strict comparison"
        board = json.loads(scoreboard.read_text(encoding="utf-8"))
        baseline_id = strict_output["latest_same_platform"]["id"]
        baseline = next((r for r in board.get("rows", []) if r.get("id") == baseline_id), None)
        if not baseline or baseline.get("state") != "approved" or not baseline.get("first_approved"):
            return None, "current same-platform baseline approval record is missing"
        if baseline.get("first_approved") != strict_output["latest_same_platform"].get("first_approved"):
            return None, "baseline approval record changed during comparison"
        checked_at = (now_fn() if now_fn else datetime.now().astimezone()).isoformat(timespec="seconds")
        receipt = {
            "schema": SCHEMA, "short_id": sid, "platform": platform,
            "source_sha256": source_hash, "final_sha256": final_hash, "resolved_sha256": resolved_hash,
            "staged_video_sha256": final_hash,
            "source_path": str(source), "final_path": str(final), "resolved_path": str(resolved),
            "strict_command": command, "strict_output": strict_output, "checked_at": checked_at,
            "arm_pass_started_at": arm_started_at,
            "independent_review": {"reviewer": reviewer, "maker": maker, "verdict": review_entry.get("verdict"),
                                   "at": review_entry.get("at"), "record_sha256": canonical_sha(review_entry)},
            "baseline_approval": {"short_id": baseline_id, "platform": platform,
                                  "first_approved": baseline.get("first_approved"),
                                  "scoreboard_sha256": sha_file(scoreboard),
                                  "record_sha256": canonical_sha(baseline)},
        }
        if datetime.fromisoformat(checked_at) < datetime.fromisoformat(arm_started_at):
            return None, "strict receipt predates this arming pass"
        return receipt, ""
    except (OSError, ValueError, StopIteration) as exc:
        return None, f"cannot bind current baseline approval record: {exc}"


def validate_saved_receipt(package: Path, expected_platform: str, expected_video_sha: str,
                           arm_started_at: str) -> tuple[bool, str, dict | None]:
    """Validate the canonical package receipt and exact staged video before arm/pre-post transitions."""
    path = package / "receipts" / RECEIPT_NAME
    try:
        receipt = json.loads(path.read_text(encoding="utf-8"))
        video = package / "video.mp4"
        if receipt.get("schema") != SCHEMA:
            return False, "strict receipt schema is missing or invalid", None
        if receipt.get("platform") != expected_platform or receipt.get("staged_video_sha256") != expected_video_sha:
            return False, "strict receipt platform or staged hash does not match the arm row", None
        if not video.is_file() or sha_file(video) != expected_video_sha:
            return False, "staged video hash does not match the strict receipt", None
        if receipt.get("source_sha256") != sha_file(Path(receipt["source_path"])):
            return False, "strict receipt source hash is stale", None
        if receipt.get("final_sha256") != sha_file(Path(receipt["final_path"])):
            return False, "strict receipt FINAL hash is stale", None
        if receipt.get("resolved_sha256") != sha_file(Path(receipt["resolved_path"])):
            return False, "strict receipt resolved hash is stale", None
        checked = datetime.fromisoformat(receipt.get("checked_at", ""))
        started = datetime.fromisoformat(arm_started_at)
        if checked < started or receipt.get("arm_pass_started_at") != arm_started_at:
            return False, "strict receipt is stale for this arming pass", None
        ok, why = _eligible(receipt.get("strict_output"), receipt.get("short_id"), expected_platform)
        if not ok:
            return False, why, None
        review = receipt.get("independent_review") or {}
        if (not review.get("reviewer") or not review.get("maker")
                or review["reviewer"].casefold() == review["maker"].casefold()):
            return False, "strict receipt lacks a distinct independent reviewer", None
        baseline = receipt.get("baseline_approval") or {}
        if (baseline.get("platform") != expected_platform or not baseline.get("short_id")
                or not baseline.get("record_sha256") or not baseline.get("scoreboard_sha256")):
            return False, "strict receipt lacks its same-platform baseline approval record", None
        return True, "", receipt
    except (OSError, ValueError, KeyError, TypeError) as exc:
        return False, f"strict receipt is missing, malformed, or unreadable: {exc}", None


# ---------------------------------------------------------------------------------------------------------------------
# Cross-post hygiene (Claude/root, autonomy-ops card, 6 Oct 2026). ADDITIVE: nothing above this line changed.
#
# Sam, 6 Oct: the standalone CTA "Follow, we track this every week." comes out pitched up and wonky (voice_lead_check bans it for
# every NEW take). Shorts posted with that CTA before the ban (S04, S20, S23 on 6 Oct) still sit in the "already public" pool that
# the fallback cross-poster (slot_filler.py -> arm_ready.py --crosspost) re-posts to other platforms. A cross-post publishes the
# SAME BYTES, so the question is "what does the audio of THESE posted bytes say", answered only from evidence bound to those bytes:
#   1. resolved.json of the build whose FINAL.mp4 is byte-identical to the posted video (its `words` are the voice words the master
#      was built from); only when resolved.json is not newer than that FINAL (a later rebuild's words say nothing about it);
#   2. the gate's own CTA-window text (GATE.json check "CTA (last 8s)"), bound by the gate probe's exact byte size + duration;
#   3. the voice take's words.json, only when it is not newer than that FINAL (a later revoice is not what was rendered).
# BANNED = any bound evidence carries the phrase. CLEAN = bound evidence exists and none does. UNKNOWN = nothing is bound to the
# posted bytes: cross-posting refuses UNKNOWN too (a check that cannot see is not a pass).
BANNED_CTA_PHRASES = ("we track this every week",)
_V2 = Path(__file__).resolve().parents[2]
_BANNED_HINT = "voice_lead_check.py bans it (Sam 6 Oct: pitches up, wonky); only a full-sentence CTA is allowed"


def _spoken(text) -> str:
    """lower-case words only, so 'Follow, we track this every week.' and ASR/caption variants compare equal."""
    import re
    return " ".join(re.sub(r"[^a-z0-9']+", " ", str(text or "").lower()).split())


def banned_phrase_in(text) -> str | None:
    s = _spoken(text)
    for phrase in BANNED_CTA_PHRASES:
        if phrase in s:
            return phrase
    return None


def _jload(path: Path):
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def _words_text(words) -> str:
    if isinstance(words, dict):
        words = words.get("words") or []
    parts = []
    for w in words or []:
        parts.append(str((w.get("word") or w.get("text") or "") if isinstance(w, dict) else w))
    return " ".join(parts)


def _sha_cached(path: Path, cache: dict | None) -> str:
    """sha256 of a file; with a cache dict keyed by path -> {size, mtime_ns, sha} the 100-200 MB masters are hashed once."""
    st = Path(path).stat()
    key = str(path)
    if cache is not None:
        hit = cache.get(key)
        if hit and hit.get("size") == st.st_size and hit.get("mtime_ns") == st.st_mtime_ns:
            return hit["sha"]
    digest = sha_file(Path(path))
    if cache is not None:
        cache[key] = {"size": st.st_size, "mtime_ns": st.st_mtime_ns, "sha": digest}
    return digest


def framing_master(sid: str, record: dict, *, package=None, sha_cache: dict | None = None) -> tuple:
    """Resolve exact armed bytes for OCR; an archived master may use its already-public package.
    A present but changed master is refused. This proves byte identity, never release or taste approval.
    """
    expected = str(record.get("video_sha256") or "")
    if len(expected) != 64 or any(c not in "0123456789abcdef" for c in expected):
        return None, "no valid arming master hash"
    master = Path(record["master"]) if record.get("master") else None
    try:
        if master and master.exists():
            if master.is_file() and _sha_cached(master, sha_cache) == expected:
                return str(master), "ledger master matches armed bytes"
            return None, "present ledger master differs from armed bytes"
        pkg = Path(package or record.get("package") or "")
        manifest = _jload(pkg / "package.json")
        if not isinstance(manifest, dict) or manifest.get("film") != sid:
            return None, "posted package identity does not match"
        video = manifest.get("video")
        if not isinstance(video, dict) or video.get("file") != "video.mp4" or video.get("sha256") != expected:
            return None, "posted package manifest does not bind armed bytes"
        public = False
        for platform in PLATFORMS:
            receipt = _jload(pkg / "receipts" / (platform + ".json"))
            if (isinstance(receipt, dict) and receipt.get("public_status") == "publicly_available"
                    and isinstance(receipt.get("post_url"), str) and receipt["post_url"].startswith("https://")):
                public = True
                break
        if not public:
            return None, "no canonical public receipt with URL for posted package"
        candidate = pkg / "video.mp4"
        if candidate.is_file() and _sha_cached(candidate, sha_cache) == expected:
            return str(candidate), "archived master recovered from identical public package bytes"
        return None, "posted package bytes differ from arming hash"
    except OSError as exc:
        return None, "master resolution failed: %s" % str(exc)[:100]


def posted_audio_cta(sid: str, video_sha256: str, *, video_path=None, master=None, gate_json=None,
                     sha_cache: dict | None = None, v2: Path | None = None) -> dict:
    """Verdict on the audio CTA of the exact posted bytes `video_sha256`. See the block comment above.
    video_path: the staged/posted video.mp4 (hash-verified here); master / gate_json: the arming ledger's recorded paths."""
    v2 = Path(v2) if v2 else _V2
    out = {"id": sid, "verdict": "UNKNOWN", "phrase": None, "evidence": [], "video_sha256": video_sha256}
    if not video_sha256:
        out["reason"] = "no posted-bytes hash to bind evidence to"
        return out
    size = None
    for cand in (video_path, master):
        try:
            if cand and Path(cand).is_file() and _sha_cached(Path(cand), sha_cache) == video_sha256:
                size = Path(cand).stat().st_size
                break
        except OSError:
            continue
    dirs = []
    for d in (v2 / "kit" / "out" / sid, v2 / "pilot" / "build" / sid):
        if d.is_dir():
            dirs.append(d)
    if master and Path(master).name == "FINAL.mp4" and Path(master).parent.is_dir() and Path(master).parent not in dirs:
        dirs.append(Path(master).parent)

    def add(source, path, bound_by, text):
        hit = banned_phrase_in(text)
        out["evidence"].append({"source": source, "path": str(path), "bound_by": bound_by, "hit": bool(hit),
                                "tail": " ".join(_spoken(text).split()[-12:])})
        return hit

    hits = []
    for d in dirs:
        final = d / "FINAL.mp4"
        final_bound, final_mtime = False, None
        try:
            if final.is_file() and _sha_cached(final, sha_cache) == video_sha256:
                final_bound, final_mtime = True, final.stat().st_mtime
                size = size or final.stat().st_size
        except OSError:
            pass
        if final_bound:
            res = d / "resolved.json"
            rj = _jload(res)
            if isinstance(rj, dict) and rj.get("words") and res.stat().st_mtime <= final_mtime + 120:
                hits.append(add("resolved.words", res, "FINAL.mp4 sha256 == posted sha256; resolved.json not newer than FINAL", _words_text(rj["words"])))
            vw = v2 / "shorts" / "voice" / sid / ("%s.words.json" % sid)
            vj = _jload(vw)
            if vj and vw.stat().st_mtime <= final_mtime + 120:
                hits.append(add("voice.words", vw, "FINAL.mp4 sha256 == posted sha256; voice take not newer than FINAL", _words_text(vj)))
    gates = []
    for d in dirs:
        gates += sorted(d.glob("gate/*/GATE.json")) + [d / "GATE.json"]
    if gate_json:
        gates.append(Path(gate_json))
    seen = set()
    for g in gates:
        if str(g) in seen or not g.is_file():
            continue
        seen.add(str(g))
        gj = _jload(g)
        probe = (gj or {}).get("probe") or {}
        if size is None or probe.get("size_bytes") != size:
            continue
        for chk in (gj or {}).get("checks", []):
            if str(chk.get("name", "")).upper().startswith("CTA"):
                text = " ".join(str(x) for x in (chk.get("details") or []))
                hits.append(add("gate.cta_window", g, "gate probe size_bytes == posted bytes", text))
    # root/Claude 12 Oct: the 38 already-public shorts whose FINAL/gate/voice were archived were all UNKNOWN, so the fallback pool was
    # empty and 10-12 Oct posted nothing. cta_asr_evidence.py transcribes the tail of the POSTED video.mp4 itself; the record is
    # accepted only when its video_sha256 equals the posted sha256. Conservative on purpose: "track" + "every week" in the tail
    # also counts as BANNED (ASR may mangle the exact phrase), so this source can only add refusals' certainty, never relax one.
    asr_dir = v2 / "autoposter" / "arming" / "cta-asr"
    for rec_path in sorted(asr_dir.glob("%s-%s*.json" % (sid, video_sha256[:12]))) if video_sha256 else []:
        rec = _jload(rec_path)
        if (isinstance(rec, dict) and rec.get("schema") == "agmm-cta-asr-evidence-v1" and rec.get("id") == sid
                and rec.get("video_sha256") == video_sha256 and rec.get("text")):
            text = str(rec["text"])
            hit = banned_phrase_in(text)
            if not hit and "every week" in _spoken(text) and "track" in _spoken(text):
                hit = "track ... every week (ASR variant)"
            out["evidence"].append({"source": "asr.tail", "path": str(rec_path), "bound_by": rec.get("bound_by"),
                                    "hit": bool(hit), "tail": " ".join(_spoken(text).split()[-12:])})
            hits.append(hit)
    out["phrase"] = next((h for h in hits if h), None)
    if out["phrase"]:
        out["verdict"] = "BANNED"
        out["reason"] = "bound evidence carries the banned CTA %r (%s)" % (out["phrase"], _BANNED_HINT)
    elif out["evidence"]:
        out["verdict"] = "CLEAN"
        out["reason"] = "%d piece(s) of evidence bound to the posted bytes, none carries a banned CTA" % len(out["evidence"])
    else:
        out["reason"] = "no evidence bound to the posted bytes (FINAL/gate/voice not byte-matched or archived)"
    return out


def crosspost_hygiene(sid: str, record: dict, *, package=None, sha_cache: dict | None = None, v2: Path | None = None) -> tuple:
    """(ok, reason, detail) for re-posting `sid`'s already-posted bytes to another platform. `record` is the arming ledger's
    item (video_sha256, master, gate_json, package). Refuses BANNED and UNKNOWN."""
    pkg = Path(package or record.get("package") or "")
    vpath = pkg / "video.mp4" if str(pkg) not in ("", ".") else None
    res = posted_audio_cta(sid, record.get("video_sha256") or "", video_path=vpath, master=record.get("master"),
                           gate_json=record.get("gate_json"), sha_cache=sha_cache, v2=v2)
    if res["verdict"] == "CLEAN":
        return True, "", res
    if res["verdict"] == "BANNED":
        return False, "crosspost hygiene: %s posted audio carries the banned CTA 'Follow, we track this every week.' " \
                      "(%s); never cross-post it again" % (sid, res["reason"]), res
    return False, "crosspost hygiene: cannot prove %s's posted audio is free of the banned CTA (%s)" % (sid, res["reason"]), res
