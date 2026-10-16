#!/usr/bin/env python3
"""Release validator: refuses to mark any row releasable unless every one of these holds.

  1. APPROVAL  approvals/APPROVALS.json has an entry for the ID with sam_approved == true (a JSON boolean,
               not a string), approved_by == "sam", and an approved_at timestamp.
  2. MP4       the approved `src` file exists and its sha256 equals the approval's mp4_sha256.
  3. SPEC      ffprobe on that file: 1080x1920, 30-60 s (gate.py SHORT_DUR_PASS), an audio stream.
  4. GATE      the approval's gate_json exists, says overall == "PASS", and was run on THIS file: its `video`
               path resolves to a file with the same sha256, or (if that path no longer resolves) its probe
               size_bytes equals the file size and its duration is within 0.05 s.
  5. CAPTIONS  every platform caption, with {music_credit} filled from the beds the approved build records,
               re-passes tools/caption_lint.py now (the stored lint result is not trusted); no placeholder is
               left; every CC BY bed is credited (title, author, source, licence; the compact music.json
               `credit_compact` form or the older long `credit` string) and no track is credited that is not a
               bed in the mix (tools/credits.py, 29 Sep); the YouTube title passes too.
  6. SCRIPT    the script file still has the sha256 the captions were written from (a changed script means
               the captions must be rewritten and re-read).
  7. MASTER    not a web copy: no "web" in the file name, at least 5 Mbit/s, and not the same bytes as the
               card's review copy (`src`). The web copies are 1-8 Mbit/s re-encodes nobody gated.

Approval comes from ONE of two sources, never a mix:
  a. Sam: an entry in approvals/APPROVALS.json (check 1 above). Only entries of that shape are read from the file.
  b. A reviewer (25 Sep 2026, CRAFT-STANDARD section 8 step 4): derived LIVE by reviewer_approval() from
     v2/qa/cards.json and v2/qa/review-log.json, never from a file anyone can write. It needs the card at
     exactly "Ready to post", the LATEST review-log entry for the ID a clean PASS (no NOT FINAL, SUPERSEDED,
     PRE-REVIEW, HOLD ...), a named reviewer who is not the maker, a review time no earlier than the master
     file's last change (a PASS on an earlier render does not cover a re-render), and the card's own
     master + gate_json + recorded music bed.

Gate binding (check 4) was hardened on 25 Sep: S22's r2 GATE.json names kit/out/S22/FINAL.mp4, and r3 was
later written to that same path, so "sha of the gate's video == sha of the master" compared the file with
itself and passed. Now, when the gate's recorded size exists it must equal the file's, and when the gate's
video IS the master path, the file must not have changed after the gate ran.

It writes release-check.json and never edits the intake, a runtime plan or the live autoposter.
Exit 0 only when every requested row is releasable.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import subprocess
import sys
from datetime import datetime
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
V2 = HERE.parents[1]
BUILD = V2.parent
sys.path.insert(0, str(HERE))

import caption_lint as cl  # noqa: E402
import credits as cr  # noqa: E402

PLACEHOLDER = "{music_credit}"
DUR = (30.0, 60.0)
DIMS = (1080, 1920)
MIN_MASTER_BPS = 5_000_000          # web copies measured 1.1-7.9 Mbit/s; P3's master (lowest) is 6.6
GATE_MTIME_GRACE_S = 120
CARDS = V2 / "qa" / "cards.json"
REVIEW_LOG = V2 / "qa" / "review-log.json"
READY = "Ready to post"
# A verdict counts only if it starts with PASS and carries none of these words.
DISQUALIFY = ("NOT FINAL", "SUPERSEDED", "PRE-REVIEW", "PROVISIONAL", "WITHDRAWN", "HOLD", "FAIL", "PENDING",
              "UNJUDGED", "RE-REVIEW")
REVIEW_GRACE_S = 90                  # review-log times have minute precision


def sha_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def ffprobe(path: Path) -> dict:
    done = subprocess.run(["ffprobe", "-v", "error", "-show_entries",
                           "stream=codec_type,width,height,duration:format=bit_rate,size", "-of", "json",
                           str(path)], capture_output=True, text=True)
    if done.returncode:
        return {"ok": False, "error": done.stderr.strip()[:300]}
    data = json.loads(done.stdout)
    streams = data.get("streams", [])
    fmt = data.get("format") or {}
    v = next((s for s in streams if s.get("codec_type") == "video"), {})
    return {"ok": True, "width": int(v.get("width") or 0), "height": int(v.get("height") or 0),
            "duration": float(v.get("duration") or 0), "has_audio": any(s.get("codec_type") == "audio" for s in streams),
            "bit_rate": int(fmt.get("bit_rate") or 0)}


def parse_local(value: str) -> datetime | None:
    """Review-log and gate times: '2026-09-25T11:49', '2026-09-25 01:35', optional seconds. Local, naive."""
    m = re.match(r"^(\d{4}-\d{2}-\d{2})[T ](\d{2}:\d{2}(?::\d{2})?)", str(value or "").strip())
    if not m:
        return None
    t = m.group(2) if m.group(2).count(":") == 2 else m.group(2) + ":00"
    try:
        return datetime.fromisoformat(f"{m.group(1)}T{t}")
    except ValueError:
        return None


# autonomy-ops 6 Oct (root 13:10): a master PASS that arms a post must come from a Claude reviewer. A crew persona (Hound, Forge, Marshal,
# Scout, Baton, Brain, Clef, Jev) or any unknown name is refused: 30 Sep, Hound's four unreviewed approvals were all reverted.
# Sam's 7 Oct operator brief authorises GPT reviewers during the Claude handover.
# Keep crew personas refused, including a persona disguised with a trusted prefix.
CLAUDE_REVIEWER_RE = re.compile(r"^(root|claude-root|sonnet-[a-z0-9._-]+|opus-[a-z0-9._-]+)$", re.I)
CREW_PERSONA_RE = re.compile(r"(?<![a-z])(hound|forge|marshal|scout|baton|brain|clef|jev)(?![a-z])", re.I)


# conductor 6 Oct 2026 (Sam 14:40: "make sure Buzz actually handles the posts and production" while Claude is out of weekly budget):
# "machine:<claude-reviewer>" is a master pass issued by qa/machine_pass.py, never by a person or a crew agent. It is accepted ONLY when
# kit/out/<ID>/machine-pass/RECEIPT.json exists, is sealed, is for this exact master sha, names the same Claude approver, every one of its
# checks was ok, its immutable evidence files still have the sha they had, and the storyboard is still approved by that approver at the
# same approved hash. A bare "machine" string, "machine:Hound", "machine:" and "machine:machine:root" are all still refused.
MACHINE_PREFIX = "machine:"
MACHINE_RECEIPT = "RECEIPT.json"


def machine_receipt_seal(body: dict) -> str:
    """sha256 over the canonical JSON of the receipt without its own `seal` key (tamper evidence, not a signature)."""
    b = {k: v for k, v in body.items() if k != "seal"}
    return hashlib.sha256(json.dumps(b, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")).hexdigest()


def machine_receipt_ok(sid: str, approver: str, master_sha: str, v2: Path | None = None) -> tuple[bool, str]:
    v2 = v2 or V2
    rp = v2 / "kit" / "out" / sid / "machine-pass" / MACHINE_RECEIPT
    try:
        r = json.loads(rp.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return False, f"no machine-pass receipt at {rp}"
    if r.get("seal") != machine_receipt_seal(r):
        return False, "machine-pass receipt seal does not match its body (edited by hand?)"
    if r.get("kind") != "agmm_machine_pass_receipt" or r.get("verdict") != "PASS" or r.get("id") != sid:
        return False, f"receipt is not a PASS for {sid}"
    if r.get("master_sha256") != master_sha:
        return False, f"receipt is for master {str(r.get('master_sha256'))[:16]}, not {str(master_sha)[:16]}"
    if r.get("approver") != approver:
        return False, f"receipt names approver {r.get('approver')!r}, the review names {approver!r}"
    bad = [c.get("name") for c in r.get("checks", []) if not c.get("ok")]
    if bad or not r.get("checks"):
        return False, f"receipt has failed or no checks: {bad}"
    for ev in r.get("evidence", []):
        if ev.get("immutable"):
            fp = v2.parent / ev["path"]
            try:
                now = sha_file(fp)
            except OSError:
                return False, f"evidence file is gone: {ev['path']}"
            if now != ev.get("sha256"):
                return False, f"evidence file changed since the pass: {ev['path']}"
    try:
        sb = json.loads((v2 / "kit" / "registry" / "storyboards" / f"{sid}.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return False, "storyboard record unreadable"
    if sb.get("state") != "approved" or sb.get("by") != approver or sb.get("approved_hash") != r.get("approved_hash"):
        return False, "storyboard is no longer approved by that approver at the receipt's hash"
    return True, "machine-pass receipt valid"


def known_claude_reviewer(name, sid: str | None = None, master_sha: str | None = None) -> bool:
    n = str(name or "").strip()
    if n.lower().startswith(MACHINE_PREFIX):
        inner = n[len(MACHINE_PREFIX):].strip()
        if not (CLAUDE_REVIEWER_RE.match(inner) and not CREW_PERSONA_RE.search(inner)):
            return False
        if not sid or not master_sha:
            return False
        return machine_receipt_ok(sid, inner, master_sha)[0]
    return bool(CLAUDE_REVIEWER_RE.match(n)) and not CREW_PERSONA_RE.search(n)


def clean_pass(verdict: str) -> bool:
    v = str(verdict or "").strip().upper()
    return bool(re.match(r"^PASS\b", v)) and not any(w in v for w in DISQUALIFY)


def latest_review(sid: str, log: list) -> dict | None:
    """The newest entry for this ID (by time, then by position): an old PASS never outranks a later HOLD."""
    entries = [(parse_local(e.get("at")) or datetime.min, i, e) for i, e in enumerate(log) if e.get("id") == sid]
    return max(entries, key=lambda t: (t[0], t[1]))[2] if entries else None


def _abs(p: str | None) -> Path | None:
    if not p:
        return None
    q = Path(p)
    return q if q.is_absolute() else BUILD / q


def recorded_beds(master: Path) -> list[str]:
    """The bed the build actually mixed: kit/out/<ID>/audio/bed-envelope.json {"bed": ...}."""
    env = master.parent / "audio" / "bed-envelope.json"
    if not env.is_file():
        # mix2 builds (25 Sep r3 sound) write no bed-envelope.json; the bed they mixed is audio/mix_spec.json music.src
        ms = master.parent / "audio" / "mix_spec.json"
        if ms.is_file():
            src = (json.loads(ms.read_text(encoding="utf-8")).get("music") or {}).get("src")
            return [Path(src).stem] if src else []
        return []
    bed = json.loads(env.read_text(encoding="utf-8")).get("bed")
    return [bed] if isinstance(bed, str) and bed else [b for b in (bed or []) if isinstance(b, str)]


def master_from_approved_spec(sid, master):
    """Root 5 Oct 23:20: C13 (pan pass) and S37 (visual lift) were re-edited and re-approved tonight, but arming staged their
    OLD masters: strict excludes render metrics while the spec is newer than FINAL, so it measured the new spec and posted
    the old video. A master may arm only while its storyboard is approved and it was built from the approved spec."""
    kit = Path(__file__).resolve().parents[2] / "kit"
    try:
        sb = json.loads((kit / "registry" / "storyboards" / f"{sid}.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return False, "no storyboard record"
    if sb.get("state") != "approved":
        return False, f"storyboard state is {sb.get('state')!r}: the spec is being changed"
    if not master or not master.is_file():
        return False, "no master"
    # root 6 Oct 07:55: S02 armed its OLD master while m3's re-edit (new CTA + bed) sat on disk unsubmitted: the record
    # still said approved with the old hash. The spec on disk must BE the approved spec (no edit in progress).
    try:
        import importlib.util as _u
        _spec = _u.spec_from_file_location("storyboard_hash", str(kit / "tools" / "storyboard.py"))
        _sb = _u.module_from_spec(_spec); _spec.loader.exec_module(_sb)
        cur = _sb.spec_hash(sid)
        if sb.get("approved_hash") and cur != sb.get("approved_hash"):
            return False, "the spec on disk differs from the approved spec (an edit is in progress); resubmit first"
    except SystemExit:
        pass
    except Exception as exc:  # noqa: BLE001
        return False, f"cannot hash the current spec: {exc}"
    spec_files = [p for p in (kit / "specs" / sid).glob("*") if p.suffix in (".js", ".json") and p.is_file() and p.name != "concept.json"]   # 6 Oct: concept.json is a gate input, not render code
    newest = max([p.stat().st_mtime for p in spec_files] or [0])
    if newest <= master.stat().st_mtime + 60:
        return True, "master is newer than every spec file"
    cols = sorted((kit / "out" / sid / "cloud-dispatch").glob("*/COLLECTED.json"), key=lambda p: p.stat().st_mtime)
    if cols:
        try:
            req = json.loads((cols[-1].parent / "REQUEST.json").read_text(encoding="utf-8"))
            col = json.loads(cols[-1].read_text(encoding="utf-8"))
            if ((req.get("approval") or {}).get("approved_hash") == sb.get("approved_hash")
                    and master.stat().st_size == col.get("bytes")):
                return True, "hosted master built from the approved hash"
        except (OSError, ValueError):
            pass
    return False, "spec changed after this master was built; re-render and re-gate first"


def reviewer_approval(sid: str, cards: list | None = None, log: list | None = None) -> tuple[dict | None, list[dict]]:
    """Derive a release approval from the review page and the review log. Returns (approval, checks)."""
    cards = json.loads(CARDS.read_text(encoding="utf-8")) if cards is None else cards
    log = json.loads(REVIEW_LOG.read_text(encoding="utf-8")) if log is None else log
    checks = []

    def add(code, ok, detail):
        checks.append({"code": code, "ok": bool(ok), "detail": str(detail)[:300]})

    card = next((c for c in cards if c.get("id") == sid), None)
    add("card_ready_to_post", bool(card) and card.get("status") == READY,
        f"status={card.get('status') if card else None!r}")
    entry = latest_review(sid, log)
    ok = bool(entry) and clean_pass(entry.get("verdict"))
    add("reviewer_pass_is_latest_verdict", ok,
        f"latest={entry.get('reviewer') if entry else None}: {str(entry.get('verdict') if entry else None)[:120]!r}")
    reviewer = str((entry or {}).get("reviewer") or "").strip()
    maker = str((entry or {}).get("maker") or "").strip()
    add("reviewer_is_not_maker", bool(reviewer) and reviewer.lower() != maker.lower(),
        f"reviewer={reviewer!r} maker={maker!r}")
    master = _abs((card or {}).get("master"))
    _msha = None
    if reviewer.lower().startswith(MACHINE_PREFIX) and master and master.is_file():
        _msha = sha_file(master)     # only a machine pass needs the master's sha here (receipt binding)
    add("reviewer_is_known_claude", known_claude_reviewer(reviewer, sid, _msha),
        f"reviewer={reviewer!r}: only root, claude-root, sonnet-*, opus-*, or machine:<one of those> with a valid machine-pass receipt for this master may pass a master that arms a post (a crew persona or unknown name may not)")
    add("card_master_exists", bool(master) and master.is_file(), str(master))
    at = parse_local((entry or {}).get("at"))
    if master and master.is_file() and at:
        changed = datetime.fromtimestamp(master.stat().st_mtime)
        add("review_not_older_than_master", (changed - at).total_seconds() <= REVIEW_GRACE_S,
            f"reviewed {at.isoformat()} master last changed {changed.isoformat(timespec='seconds')}")
    else:
        add("review_not_older_than_master", False, f"review at={at} master={master}")
    if not str(sid).startswith("F"):   # films have no storyboard record; their gate binding is checked by arm_film
        ok_spec, why_spec = master_from_approved_spec(sid, master)
        add("master_from_approved_spec", ok_spec, why_spec)
    if not all(c["ok"] for c in checks):
        return None, checks
    src = _abs(card.get("src"))
    approval = {
        "approval_kind": "reviewer_pass", "approved_by": f"reviewer:{reviewer}",
        "approved_at": entry.get("at"), "src": str(master), "mp4_sha256": sha_file(master),
        "gate_json": str(_abs(card.get("gate_json")) or ""), "music_beds": recorded_beds(master),
        "review_copy": str(src) if src else None,
        "review_entry": {**{k: entry.get(k) for k in ("reviewer", "maker", "verdict", "at")},
                         "master_sha256": entry.get("master_sha256") or sha_file(master)},
        "_reviewer_checks": checks,
    }
    return approval, checks



def root_waived(gate_path) -> set:
    """root 6 Oct: check ids root waived for THIS gate run after looking at the frames, from ROOT-WAIVER.json beside
    GATE.json: {"checks": ["11"], "gate_sha256": <sha of GATE.json>, "by": "root", "reason": ..., "at": ...}.
    Bound to the gate file's bytes, so a re-run gate needs a new waiver."""
    try:
        gp = Path(gate_path)
        w = json.loads((gp.parent / "ROOT-WAIVER.json").read_text(encoding="utf-8"))
        if w.get("by") != "root" or w.get("gate_sha256") != sha_file(gp) or not w.get("reason"):
            return set()
        return {str(c) for c in w.get("checks", [])}
    except (OSError, ValueError, TypeError):
        return set()


def gate_passes(gate, gate_path=None) -> bool:
    """overall PASS, or the only failing check is 9 (the advisory critic) failing for lack of free quota (root 28 Sep).
    That short still needs a reviewer PASS by eye, which the reviewer checks enforce separately."""
    if not gate:
        return False
    if gate.get("overall") == "PASS":
        return True
    fails = [c for c in gate.get("checks", []) if c.get("status") == "FAIL"]
    waived = root_waived(gate_path) if gate_path else set()
    fails = [c for c in fails if str(c.get("id")) not in waived]
    if not fails and waived:
        return True
    return bool(fails) and all(c.get("id") == "9" and re.search(r"429|quota|rate.?limit|tokens per day|TPD", str(c.get("summary", "")), re.I)
                               for c in fails)

def resolve_gate_video(gate_path: Path, video: str) -> Path | None:
    p = Path(video)
    # root 28 Sep: gate_film records the video relative to where it ran (films/), so walk every ancestor, not three.
    candidates = [p] if p.is_absolute() else [a / p for a in gate_path.resolve().parents]
    return next((c for c in candidates if c.is_file()), None)


def check_row(row: dict, approval: dict | None, catalogue: dict, probe=ffprobe) -> dict:
    sid = row["id"]
    checks = []

    def add(code, ok, detail):
        checks.append({"code": code, "ok": bool(ok), "detail": detail})

    # 1 approval: Sam's entry, or a reviewer PASS derived live by reviewer_approval() (its own checks, re-listed)
    if (approval or {}).get("approval_kind") == "reviewer_pass":
        rchecks = approval.get("_reviewer_checks") or []
        if not rchecks:
            add("reviewer_pass", False, "reviewer approval without its derivation checks")
        for c in rchecks:
            add(c["code"], c["ok"], c["detail"])
    else:
        ok = bool(approval) and approval.get("sam_approved") is True and approval.get("approved_by") == "sam" \
            and bool(approval.get("approved_at"))
        add("sam_approval", ok, "approved" if ok else f"no valid approval entry: {approval!r}"[:200])
    approval = approval or {}

    # 2 mp4
    src = Path(approval.get("src") or "")
    actual_sha = sha_file(src) if approval.get("src") and src.is_file() else ""
    add("approved_mp4_exists", bool(actual_sha), str(src) if actual_sha else f"missing: {approval.get('src')!r}")
    add("approved_mp4_sha256", bool(actual_sha) and actual_sha == approval.get("mp4_sha256"),
        f"declared={approval.get('mp4_sha256')} actual={actual_sha or None}")

    # 3 spec
    if actual_sha:
        pr = probe(src)
        spec_ok = pr.get("ok") and (pr["width"], pr["height"]) == DIMS and DUR[0] <= pr["duration"] <= DUR[1] \
            and pr["has_audio"]
        add("mp4_spec_1080x1920_30_60s_audio", spec_ok, json.dumps(pr))
        # 7 master, never a web copy
        bps = pr.get("bit_rate") or (src.stat().st_size * 8 / pr["duration"] if pr.get("duration") else 0)
        why = []
        if "web" in src.name.lower():
            why.append(f"file name {src.name!r} is a web copy")
        if bps < MIN_MASTER_BPS:
            # root 28 Sep: flat-graphics masters can encode below the floor (S33 r10: 4.9 Mbit/s). The kit's own FINAL.mp4
            # still counts as the master when its folder holds a <ID>-web.mp4 that is smaller: that sibling IS the web copy.
            sibs = list(src.parent.glob("*-web.mp4"))
            kit_master = src.name == "FINAL.mp4" and sibs and all(p.stat().st_size < src.stat().st_size for p in sibs)
            if not kit_master:
                why.append(f"{bps / 1e6:.1f} Mbit/s is below the {MIN_MASTER_BPS / 1e6:.0f} Mbit/s master floor")
        rc = Path(approval.get("review_copy") or "")
        if approval.get("review_copy") and rc.is_file() and rc.resolve() != src.resolve() and "web" in rc.name.lower() \
                and sha_file(rc) == actual_sha:
            why.append(f"same bytes as the review copy {rc.name}")
        if approval.get("review_copy") and rc.is_file() and rc.resolve() == src.resolve() and "web" in rc.name.lower():
            why.append("the master IS the card's review copy")
        add("master_not_web_copy", not why, "; ".join(why) or f"{bps / 1e6:.1f} Mbit/s, {src.name}")
    else:
        add("mp4_spec_1080x1920_30_60s_audio", False, "no file to probe")
        add("master_not_web_copy", False, "no file to probe")

    # 4 gate
    gpath = Path(approval.get("gate_json") or "")
    gate = None
    if approval.get("gate_json") and gpath.is_file():
        try:
            gate = json.loads(gpath.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            add("gate_json_readable", False, f"unparseable: {exc}")
    add("gate_json_exists", gate is not None, str(gpath) if gate is not None else f"missing: {approval.get('gate_json')!r}")
    add("gate_overall_pass", gate_passes(gate), f"overall={(gate or {}).get('overall')}")
    bound, how = False, "no gate or no file"
    if gate and actual_sha:
        gv = resolve_gate_video(gpath, str(gate.get("video", "")))
        gp = gate.get("probe") or {}
        if gv is not None:
            gsha = sha_file(gv)
            bound, how = gsha == actual_sha, f"gate video {gv} sha={gsha[:16]}"
            if gp.get("size_bytes") is not None and gp.get("size_bytes") != src.stat().st_size:
                bound, how = False, (f"gate recorded size {gp.get('size_bytes')} but the file is "
                                     f"{src.stat().st_size} bytes: the gate ran on an earlier render at this path")
            gen = parse_local(gate.get("generated_at"))
            if bound and gen and os.path.samefile(gv, src):
                changed = datetime.fromtimestamp(src.stat().st_mtime)
                if (changed - gen).total_seconds() > GATE_MTIME_GRACE_S:
                    bound, how = False, (f"file changed {changed.isoformat(timespec='seconds')}, after the gate "
                                         f"ran {gen.isoformat()} on the same path")
        else:
            gp = gate.get("probe") or {}
            size_ok = gp.get("size_bytes") == src.stat().st_size
            dur_ok = abs(float(gp.get("duration") or -99) - probe(src).get("duration", -1)) <= 0.05
            bound, how = size_ok and dur_ok, f"gate probe size={gp.get('size_bytes')} dur={gp.get('duration')} vs file size={src.stat().st_size}"
    add("gate_ran_on_this_mp4", bound, how)

    # 5 captions
    beds = approval.get("music_beds") or row.get("music_bed_chosen") or []
    unknown = [b for b in beds if b not in catalogue]
    add("music_beds_recorded", bool(beds) and not unknown,
        f"beds={beds} unknown={unknown}" if beds else "approved build records no bed id")
    # Sam 29 Sep: new captions get the compact credit ("Music: "<title>" by <artist> (<source>), CC BY 4.0").
    credit = cr.compact_music_credit(beds, catalogue)
    allowed = set(approval.get("numbers_in_script") or row.get("_numbers") or [])
    for p, c in row["platforms"].items():
        text = c["caption"].replace(PLACEHOLDER, credit) if credit else c["caption"]
        problems = []
        if PLACEHOLDER in text:
            problems.append("music credit placeholder not filled")
        if beds:
            problems += [f"music credit: {m}" for m in cr.music_credit_problems(text, beds, catalogue)]
        lint = cl.lint_caption(p, text, allowed, cr.credit_lines(text) or credit, c.get("title"))
        problems += lint["problems"]
        add(f"caption_{p}", not problems, "; ".join(problems) or f"{len(text)} chars, lint clean")

    # 6 script unchanged
    sfile = Path(row["source_file"])
    now = sha_file(sfile) if sfile.is_file() else ""
    add("script_unchanged_since_captions", now == row["source_sha256"],
        f"intake={row['source_sha256'][:16]} now={now[:16] or None}")

    releasable = all(c["ok"] for c in checks)
    return {"id": sid, "releasable": releasable,
            "failed": [c["code"] for c in checks if not c["ok"]], "checks": checks}


def load_item(item_path: Path) -> dict:
    """Rebuild one row from its own folder: item.json plus captions.json. Never a shared file."""
    item = json.loads(item_path.read_text(encoding="utf-8"))
    caps = json.loads((item_path.parent / item.get("captions_file", "captions.json")).read_text(encoding="utf-8"))
    for p, c in caps.items():
        item["platforms"].setdefault(p, {}).update(c)
    return item


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--intake", default=str(ROOT / "intake-v2.json"))
    ap.add_argument("--approvals", default=str(ROOT / "approvals" / "APPROVALS.json"))
    ap.add_argument("--ids", nargs="*", help="only these IDs (default: all)")
    ap.add_argument("--out", default=str(ROOT / "release-check.json"))
    ap.add_argument("--sam-only", action="store_true", help="ignore reviewer PASSes; Sam's approvals file only")
    args = ap.parse_args()
    manifest = json.loads(Path(args.intake).read_text(encoding="utf-8"))
    approvals = json.loads(Path(args.approvals).read_text(encoding="utf-8")).get("approvals", {}) \
        if Path(args.approvals).is_file() else {}
    index = {r["id"]: r for r in json.loads((ROOT / "script-index.json").read_text())["rows"]}
    catalogue = {i["id"]: i for i in json.loads((V2 / "sound" / "music.json").read_text())["items"]}
    # Only Sam-shaped entries are read from the approvals file; a reviewer approval is never read from a file.
    approvals = {k: v for k, v in approvals.items() if v.get("approval_kind", "sam") == "sam"}
    cards = json.loads(CARDS.read_text(encoding="utf-8")) if CARDS.is_file() else []
    log = json.loads(REVIEW_LOG.read_text(encoding="utf-8")) if REVIEW_LOG.is_file() else []
    results = []
    for entry in manifest["items"]:
        if args.ids and entry["id"] not in args.ids:
            continue
        row = load_item(ROOT / entry["item"])
        row["_numbers"] = index[row["id"]]["numbers_in_file"]
        approval = approvals.get(row["id"])
        if approval is None and not args.sam_only:
            derived, rchecks = reviewer_approval(row["id"], cards, log)
            approval = derived or {"approval_kind": "reviewer_pass", "_reviewer_checks": rchecks}
        results.append(check_row(row, approval, catalogue))
    summary = {"checked": len(results), "releasable": [r["id"] for r in results if r["releasable"]],
               "held": len([r for r in results if not r["releasable"]])}
    Path(args.out).write_text(json.dumps({"summary": summary, "results": results}, indent=1) + "\n")
    print(json.dumps(summary | {"first_failures": {r["id"]: r["failed"] for r in results[:5]}}, indent=1))
    return 0 if results and summary["held"] == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
