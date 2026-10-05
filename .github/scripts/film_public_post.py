#!/usr/bin/env python3
"""Fail-closed hosted F02/F07 publication gate and posted_cards receipt exporter.

All programme bytes are handled by the public Ubuntu workflow. Approval inputs
come only from a pinned protected Git commit; callers select a film and date,
never approval fields or hashes.
"""
from __future__ import annotations
import argparse, hashlib, json, re, subprocess
from datetime import datetime
from pathlib import Path, PurePosixPath
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parent
sys_path = ROOT
PROTECTED_REPO = "agmmltd-arch/agmm-video-render"
INPUT_MAP = "v2/autoposter/films/hosted-publication-inputs-v1.json"
CHANNEL_ID = "UChbp0G1KDjCnruAhxfmzEXg"
LONDON = ZoneInfo("Europe/London")
FILMS = {"F02", "F07"}
FILES = {"package": "package.json", "video": "video.mp4", "thumbnail": "thumbnail.jpg"}


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for block in iter(lambda: f.read(8 * 1024 * 1024), b""): h.update(block)
    return h.hexdigest()


def fail_if(condition: bool, message: str) -> None:
    if condition: raise ValueError(message)


def protected_map(source: Path, commit: str) -> dict:
    fail_if(not re.fullmatch(r"[0-9a-f]{40}", commit), "source commit must be a full SHA")
    source = source.resolve()
    def git(*args):
        p = subprocess.run(["git", "-C", str(source), *args], capture_output=True, text=True)
        if p.returncode: raise ValueError("protected Git source validation failed")
        return p.stdout.strip()
    origin = git("remote", "get-url", "origin").removesuffix(".git")
    fail_if(origin not in {f"https://github.com/{PROTECTED_REPO}", f"git@github.com:{PROTECTED_REPO}"},
            "wrong protected source origin")
    fail_if(git("rev-parse", "HEAD") != commit, "checkout differs from trusted protected commit")
    path = source / INPUT_MAP
    fail_if(not path.is_file() or path.is_symlink(), "protected film publication map is missing or unsafe")
    blob = subprocess.run(["git", "-C", str(source), "show", f"{commit}:{INPUT_MAP}"], capture_output=True)
    fail_if(blob.returncode or blob.stdout != path.read_bytes(), "film publication map differs from pinned Git blob")
    doc = json.loads(blob.stdout)
    fail_if(doc.get("schema") != "agmm-longform-hosted-publication-map-v1", "wrong protected film map schema")
    fail_if(doc.get("channel_id") != CHANNEL_ID, "wrong YouTube Studio profile/channel")
    return doc


def verify_native_text(source: Path, commit: str, row: dict) -> dict:
    """Verify each declared text input equals a blob in the trusted protected commit."""
    entries = row.get("native_files")
    fail_if(not isinstance(entries, dict) or not entries, "native source file map missing")
    out = {}
    for name, rec in entries.items():
        rel = PurePosixPath(str(rec.get("path", "")))
        fail_if(rel.is_absolute() or ".." in rel.parts, f"unsafe protected source path: {name}")
        fail_if(rel.suffix.lower() in {".mp4", ".mov", ".wav", ".mp3", ".aac", ".jpg", ".jpeg", ".png", ".webp"},
                f"programme media must be downloaded only as a pinned producer artifact: {name}")
        expected = str(rec.get("sha256", ""))
        fail_if(not re.fullmatch(r"[0-9a-f]{64}", expected), f"native text hash missing: {name}")
        path = source / Path(*rel.parts)
        fail_if(not path.is_file() or path.is_symlink(), f"native text missing: {name}")
        data = path.read_bytes()
        fail_if(sha(data) != expected, f"native text hash mismatch: {name}")
        blob = subprocess.run(["git", "-C", str(source), "show", f"{commit}:{rel.as_posix()}"], capture_output=True)
        fail_if(blob.returncode or blob.stdout != data, f"native text differs from Git blob: {name}")
        out[name] = (path, json.loads(data) if path.suffix == ".json" else data.decode("utf-8"), sha(data))
    required = {"approval", "review", "rights", "metadata", "script", "thumbnail_approval"}
    fail_if(set(out) != required, "protected source map must bind exactly approval, review, rights, metadata, script, thumbnail approval")
    return out


def validate_plan_identity(doc: dict, row: dict, film_id: str, target_date: str) -> None:
    fail_if(film_id not in FILMS or row.get("film_id") != film_id, "film identity mismatch")
    fail_if(row.get("status") != "Ready to post", "film card is not exactly Ready to post")
    fail_if(row.get("target_date") != target_date, "date mismatch with protected film plan")
    fail_if(row.get("channel_id") != CHANNEL_ID or doc.get("channel_id") != CHANNEL_ID,
            "film targets wrong YouTube profile/channel")
    validate_not_duplicate(doc, film_id, str(row.get("master_sha256", "")))


def validate_not_duplicate(doc: dict, film_id: str, master_sha256: str) -> None:
    existing = doc.get("posted") or []
    fail_if(any(p.get("film_id") == film_id or p.get("master_sha256") == master_sha256 for p in existing),
            "duplicate film or master already has a protected public receipt")


def validate_av_review(review: dict, film_id: str, master_sha256: str) -> None:
    _pass(review, "latest independent AV review")
    fail_if(review.get("film_id") != film_id or review.get("master_sha256") != master_sha256,
            "AV review does not bind exact film master")
    fail_if(review.get("reviewer_id") in (None, "") or review.get("reviewer_id") == review.get("maker_id"),
            "reviewer is absent or is the maker")
    av = review.get("audiovisual_review") or {}
    for gate in ("continuous_visual", "continuous_audio", "motion", "pilot_craft", "thumbnail", "rights"):
        fail_if(av.get(gate) != "PASS", f"independent AV review missing {gate} PASS")


def _pass(doc: dict, label: str) -> None:
    fail_if(not isinstance(doc, dict) or doc.get("overall") != "PASS", f"{label} is not PASS")


def validate_approval_freshness(approval: dict, review: dict, master_created_at: str) -> None:
    """Ensure review follows master completion, approval follows review, and neither is future-dated."""
    try:
        created = datetime.fromisoformat(str(master_created_at).replace("Z", "+00:00")).astimezone(LONDON)
        reviewed = datetime.fromisoformat(str(review.get("reviewed_at")).replace("Z", "+00:00")).astimezone(LONDON)
        approved = datetime.fromisoformat(str(approval.get("approved_at")).replace("Z", "+00:00")).astimezone(LONDON)
    except Exception as exc:
        raise ValueError("master/review/approval timestamps missing or invalid") from exc
    now = datetime.now(LONDON)
    fail_if(created > now or reviewed > now or approved > now, "master/review/approval timestamp is in the future")
    fail_if(reviewed < created, "AV review predates completion of the exact master")
    fail_if(approved < reviewed, "approval predates the AV review")


def prepare(source: Path, commit: str, film_id: str, target_date: str,
            artifact_root: Path, now: datetime | None = None) -> dict:
    fail_if(film_id not in FILMS, "only F02/F07 can use this candidate route")
    today = (now or datetime.now(LONDON)).astimezone(LONDON).date().isoformat()
    fail_if(target_date != today, "target date differs from current Europe/London production date")
    doc = protected_map(source, commit)
    row = (doc.get("films") or {}).get(film_id)
    fail_if(not isinstance(row, dict), "film is absent from protected publication map")
    validate_plan_identity(doc, row, film_id, target_date)
    native = verify_native_text(source.resolve(), commit, row)
    approval, review, rights = native["approval"][1], native["review"][1], native["rights"][1]
    metadata, script = native["metadata"][1], native["script"][1]
    thumb_approval = native["thumbnail_approval"][1]
    _pass(approval, "independent film approval")
    _pass(review, "latest independent AV review")
    _pass(rights, "rights review")
    _pass(thumb_approval, "thumbnail approval")
    validate_approval_freshness(approval, review, str(row.get("master_created_at") or ""))
    master_sha = str(row.get("master_sha256", "")); thumb_sha = str(row.get("thumbnail_sha256", ""))
    fail_if(not re.fullmatch(r"[0-9a-f]{64}", master_sha) or not re.fullmatch(r"[0-9a-f]{64}", thumb_sha),
            "master/thumbnail SHA pin invalid")
    fail_if(approval.get("film_id") != film_id or approval.get("master_sha256") != master_sha,
            "approval does not bind exact film master")
    validate_av_review(review, film_id, master_sha)
    fail_if(approval.get("review_sha256") != native["review"][2],
            "approval does not hash-bind the exact AV review")
    fail_if(approval.get("thumbnail_sha256") != thumb_sha or thumb_approval.get("thumbnail_sha256") != thumb_sha,
            "thumbnail approval hash mismatch")
    fail_if(rights.get("film_id") != film_id or rights.get("master_sha256") != master_sha
            or rights.get("thumbnail_sha256") != thumb_sha, "rights record does not bind exact master and thumbnail")
    fail_if(not str(script).strip(), "full script is empty")
    fail_if(metadata.get("film_id") != film_id or metadata.get("master_sha256") != master_sha,
            "metadata does not bind exact film master")
    title, description = metadata.get("title"), metadata.get("description")
    fail_if(not isinstance(title, str) or not isinstance(description, str) or not title or not description,
            "full title/description missing")
    fail_if(metadata.get("script_sha256") != sha(str(script).encode()), "metadata does not bind full script")
    fail_if(metadata.get("description_sha256") != sha(description.encode()), "description hash mismatch")
    fail_if(metadata.get("thumbnail_sha256") != thumb_sha, "metadata thumbnail hash mismatch")
    # Existing film contract: title/description grammar, chapters, audit link and thumbnail geometry.
    from longform_contract import check_title, check_description, check_altered_content, check_thumbnail, check_video_shape
    probs = check_title(title) + check_description(description, film_id, float(metadata.get("duration_seconds") or 0))
    probs += check_altered_content(metadata.get("altered_content"))
    fail_if(bool(probs), "long-form copy/disclosure contract failed: " + "; ".join(probs))
    prefix=PurePosixPath(str(row.get("artifact_prefix",film_id)))
    fail_if(prefix.is_absolute() or ".." in prefix.parts or not prefix.parts or any(ord(c)<32 for c in str(prefix)),"unsafe artifact prefix")
    package_dir=(artifact_root.resolve()/Path(*prefix.parts)).resolve()
    fail_if(artifact_root.resolve() not in package_dir.parents,"artifact path escapes root")
    for key, filename in FILES.items():
        p = package_dir / filename
        fail_if(not p.is_file() or p.is_symlink(), f"producer artifact missing {filename}")
    package = json.loads((package_dir / FILES["package"]).read_text())
    video_sha, thumbnail_sha = sha_file(package_dir / FILES["video"]), sha_file(package_dir / FILES["thumbnail"])
    fail_if(video_sha != master_sha or package.get("video", {}).get("sha256") != master_sha,
            "producer master hash mismatch")
    fail_if(thumbnail_sha != thumb_sha or package.get("thumbnail", {}).get("sha256") != thumb_sha,
            "producer thumbnail hash mismatch")
    contract = check_thumbnail(package_dir / FILES["thumbnail"], thumb_sha)
    video = package.get("video") or {}
    contract += check_video_shape(int(video.get("width") or 0), int(video.get("height") or 0),
                                  float(video.get("duration_seconds") or 0), bool(video.get("has_audio")))
    fail_if(bool(contract), "long-form AV/container shape failed: " + "; ".join(contract))
    fail_if(package.get("film") != film_id or package.get("kind") != "longform", "wrong package film identity or kind")
    fail_if((package.get("titles") or {}).get("youtube") != title, "package title differs from approved metadata")
    fail_if(package.get("date") != target_date, "package publication date mismatch")
    cap=PurePosixPath(str((package.get("captions") or {}).get("youtube", {}).get("file") or ""))
    fail_if(cap.is_absolute() or ".." in cap.parts or not cap.parts or any(ord(c)<32 for c in str(cap)),"unsafe caption path")
    desc_path=(package_dir/Path(*cap.parts)).resolve()
    fail_if(package_dir.resolve() not in desc_path.parents,"caption escapes package")
    fail_if(not desc_path.is_file() or desc_path.is_symlink(), "package full description missing")
    desc = desc_path.read_text(encoding="utf-8").strip()
    fail_if(desc != description, "package description differs from reviewed description")
    artifact = row.get("artifact") or {}
    fail_if(not re.fullmatch(r"\d{6,}", str(artifact.get("source_run_id", ""))), "producer source run ID missing")
    fail_if(not re.fullmatch(r"[A-Za-z0-9._-]{1,120}", str(artifact.get("name", ""))), "producer artifact name invalid")
    fail_if(artifact.get("master_sha256") != master_sha, "artifact source run is not pinned to approved master")
    validate_not_duplicate(doc, film_id, master_sha)
    fail_if((package_dir / "receipts/youtube.json").exists(), "package already contains a YouTube publication receipt")
    return {"schema": "agmm-longform-publication-request-v1", "film_id": film_id,
            "post_id": str(row.get("post_id") or ""), "target_date": target_date,
            "source_commit": commit, "source_run_id": str(artifact["source_run_id"]),
            "artifact_name": artifact["name"], "master_sha256": master_sha,
            "thumbnail_sha256": thumb_sha, "title": title, "description": description,
            "channel_id": CHANNEL_ID, "package_dir": str(package_dir),
            "metadata": metadata, "package": package, "approval": approval,
            "rights": rights, "review": review, "native_files": {k: v[0].relative_to(source).as_posix() for k,v in native.items()}}


def validate_public_result(request: dict, result: dict) -> dict:
    fail_if(result.get("schema") != "agmm-youtube-cloud-studio-public-v1" or result.get("overall") != "PUBLIC_VERIFIED",
            "native YouTube Studio public receipt missing")
    fail_if(result.get("studio_state") != "PUBLIC", "Studio state is not PUBLIC")
    fail_if(result.get("master_sha256") != request["master_sha256"], "public receipt master hash mismatch")
    fail_if(str(result.get("source_run_id")) != request["source_run_id"], "public receipt source run mismatch")
    fail_if(result.get("title") != request["title"], "public receipt title mismatch")
    fail_if(result.get("thumbnail_sha256") != request["thumbnail_sha256"], "public receipt thumbnail hash mismatch")
    fail_if((result.get("oembed") or {}).get("author_name", "").strip().lower() != "agmm"
            or (result.get("oembed") or {}).get("title") != request["title"], "logged-out oEmbed identity/title mismatch")
    fail_if(float(result.get("studio_thumbnail_mean_abs_distance", 999)) > 24.0,
            "Studio custom thumbnail does not match approved thumbnail")
    video_id = str(result.get("video_id") or "")
    url = str(result.get("post_url") or "")
    fail_if(not re.fullmatch(r"[A-Za-z0-9_-]{11}", video_id)
            or url != f"https://www.youtube.com/watch?v={video_id}", "canonical YouTube public URL invalid")
    fail_if(request.get("channel_id") != CHANNEL_ID or result.get("channel_id") != CHANNEL_ID,"actual Studio channel/profile not verified")
    return {"schema": "agmm-youtube-cloud-studio-public-v1", **result,
            "channel_id": CHANNEL_ID, "protected_source_commit": request["source_commit"],
            "film_id": request["film_id"], "post_id": request["post_id"]}


def export_posted_cards_receipt(request: dict, result: dict, destination: Path, published_at: str) -> dict:
    verified = validate_public_result(request, result)
    package = request["package"]
    desc = request["description"]
    receipt = {"schema": "agmm-video-publication-receipt-v1", "lane": "30ways-native-video",
        "run_date": request["target_date"], "slot": "immediate", "film": request["film_id"],
        "post_id": request["post_id"], "package": request["package_dir"],
        "producer_artifact": {"repository": "agmmltd-arch/agmm-render-public",
            "run_id": request["source_run_id"], "name": request["artifact_name"]}, "platform": "youtube",
        "format": "longform", "public_status": "publicly_available", "platform_post_id": verified["video_id"],
        "post_url": verified["post_url"], "published_at": published_at,
        "video": {"file": "video.mp4", "sha256": request["master_sha256"],
                  "declared_sha256": package["video"]["sha256"], "hash_bound": True,
                  "width": package["video"].get("width"), "height": package["video"].get("height"),
                  "duration_seconds": package["video"].get("duration_seconds"),
                  "has_audible_audio": package["video"].get("has_audio")},
        "caption": {"text": desc, "sha256": sha(desc.encode()), "variant": "youtube",
                    "bundle": package.get("bundle_path")},
        "identity": {"channel_id": CHANNEL_ID, "channel": "AGMM", "verified_by": "studio_public_plus_logged_out_oembed"},
        "verification": {"studio_state": "PUBLIC", "logged_out_oembed_author_and_title_match": True,
                         "native_provider_receipt": verified,
                         "protected_source_commit": request["source_commit"],
                         "review_sha256": request["approval"]["review_sha256"],
                         "rights_sha256": sha(json.dumps(request["rights"], sort_keys=True, separators=(",", ":")).encode())}}
    destination.parent.mkdir(parents=True, exist_ok=True)
    fail_if(destination.exists(), "refusing to overwrite canonical YouTube receipt")
    destination.write_text(json.dumps(receipt, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return receipt


def main():
    p = argparse.ArgumentParser()
    p.add_argument("mode", choices=("prepare", "export"))
    p.add_argument("--source", type=Path); p.add_argument("--commit"); p.add_argument("--film-id")
    p.add_argument("--target-date"); p.add_argument("--artifact-root", type=Path)
    p.add_argument("--request", type=Path); p.add_argument("--provider-result", type=Path)
    p.add_argument("--output", type=Path)
    a=p.parse_args()
    try:
        if a.mode == "prepare":
            result=prepare(a.source,a.commit,a.film_id,a.target_date,a.artifact_root)
            a.output.write_text(json.dumps(result,indent=2)+"\n")
        else:
            req=json.loads(a.request.read_text()); provider=json.loads(a.provider_result.read_text())
            export_posted_cards_receipt(req,provider,a.output,datetime.now(LONDON).isoformat())
        print(json.dumps({"status":"READY" if a.mode == "prepare" else "PUBLIC_RECEIPT_EXPORTED",
                          "film_id": a.film_id if a.mode == "prepare" else None},sort_keys=True))
        return 0
    except Exception as exc:
        print(json.dumps({"status":"HELD_LONGFORM_PUBLICATION","reason":str(exc)[:300]},sort_keys=True))
        return 2

if __name__ == "__main__":
    import sys
    sys.exit(main())
