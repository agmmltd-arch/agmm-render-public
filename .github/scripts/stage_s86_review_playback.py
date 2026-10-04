#!/usr/bin/env python3
"""Stage the exact existing S86 1080 master as review-only public playback.

All archive operations are guarded to the public GitHub Actions Ubuntu runner.
This copies and hashes the existing MP4; it does not render, transcode, or infer
editorial approval.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import platform
from pathlib import Path, PurePosixPath
import re
import urllib.error
import urllib.parse
import urllib.request
import zipfile
from datetime import datetime, timezone
from typing import Any, Mapping


REPOSITORY = "agmmltd-arch/agmm-render-public"
RENDER_RUN_ID = 37171852324
RENDER_HEAD = "fddd199eecae2a4774bfc9f7c041320619cfce0f"
REVIEW_TAG = "S86-review-playback-37171852324"
MASTER_NAME = "S86-FINAL-1080.mp4"
MASTER_SHA256 = "9bca09769370e520db8063ae6d70d13482ad5fe58310e6f03cfc4d2369ed3d1c"
MASTER_BYTES = 120_848_750
MASTER_ARTIFACT_ID = 11292320586
MASTER_ARTIFACT_NAME = "S86-quote-final-20261004-FINAL-MASTERS"
MASTER_ARTIFACT_BYTES = 383_964_779
MASTER_ARTIFACT_SHA256 = "940096ef373f68f7ec0515e005ec02cb1bacc6720e67a782fa029ea16c2483b3"
INPUT_ARTIFACT_ID = 11291104171
INPUT_ARTIFACT_NAME = "S86-quote-final-20261004-EXACT-INPUT"
INPUT_ARTIFACT_BYTES = 27_276_224
INPUT_ARTIFACT_SHA256 = "b187a1c98a088b10cc6475cd95ec19a236cd7b86a1b58c2e41287918c50c3793"
SOURCE_SHA256 = "666a90579d57f2bd5c2abed41e55b5dad3fff790f93707d79b2929bddf1c93b6"
SOURCE_BYTES = 9_817_800
PARTS_SHA256 = "e995d9d0354b808714bf89e2a082a98200a8ef92733d1896181635dfecffbb88"
MIX_SHA256 = "0c252cdf6e412fc2ccadcdb29b940d6a23b7c527276ebf79da468b7f633df436"
PARTS_BYTES = 699
MIX_BYTES = 17_452_902
EXPECTED_DURATION = 60.6
EXPECTED_FRAMES = 1818
MAX_ARTIFACT_UNPACKED = 500_000_000
MIN_REMAINING_ARTIFACT_SECONDS = 900
RELEASE_ASSET_NAMES = frozenset({
    MASTER_NAME,
    "REVIEW-PLAYBACK-RECEIPT.json",
    "INPUT-RECEIPT.json",
    "TECHNICAL-EVIDENCE.json",
    "SHA256SUMS.txt",
})
FINAL_RELEASE_ASSET_NAMES = RELEASE_ASSET_NAMES | frozenset({
    "PLAYBACK-TRANSPORT-VERIFICATION.json", "HOSTED-MEDIA-MANIFEST.json",
})
REVIEW_URL = (
    f"https://github.com/{REPOSITORY}/releases/download/{REVIEW_TAG}/{MASTER_NAME}"
)
ALLOWED_REDIRECT_HOSTS = frozenset({
    "github.com", "release-assets.githubusercontent.com", "objects.githubusercontent.com",
})


class ReviewStageError(ValueError):
    pass


def _positive_int(value: Any) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and value > 0


def require_hosted_runner(env: Mapping[str, str], system: str) -> None:
    """Call before opening artifact/source paths or making release API calls."""
    if system != "Linux" or env.get("RUNNER_OS") != "Linux" or env.get("GITHUB_ACTIONS") != "true":
        raise ReviewStageError("S86 review playback staging is public-GitHub-Actions-Linux-only")
    if env.get("GITHUB_REPOSITORY") != REPOSITORY:
        raise ReviewStageError("unexpected repository; refusing artifact or release access")
    if env.get("GITHUB_REF") != "refs/heads/main" or env.get("GITHUB_EVENT_NAME") != "workflow_dispatch":
        raise ReviewStageError("manual main-branch dispatch required")
    if not re.fullmatch(r"[0-9a-f]{40}", env.get("GITHUB_SHA", "")):
        raise ReviewStageError("workflow source commit is missing or malformed")


def _validate_artifact(row: Mapping[str, Any], *, artifact_id: int, name: str,
                       size: int, digest: str, now: datetime) -> None:
    if row.get("id") != artifact_id or row.get("name") != name:
        raise ReviewStageError("artifact ID/name is not the exact pinned S86 artifact")
    if row.get("size_in_bytes") != size or row.get("digest") != f"sha256:{digest}":
        raise ReviewStageError("artifact size or digest differs from the native pin")
    if row.get("expired") is not False:
        raise ReviewStageError("pinned Actions artifact is expired or expiry is unverified")
    expires = row.get("expires_at")
    if not isinstance(expires, str):
        raise ReviewStageError("artifact expiry is missing")
    try:
        expiry = datetime.fromisoformat(expires.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ReviewStageError("artifact expiry is malformed") from exc
    if expiry.tzinfo is None or (expiry - now).total_seconds() < MIN_REMAINING_ARTIFACT_SECONDS:
        raise ReviewStageError("artifact expired or too close to expiry for safe staging")
    workflow = row.get("workflow_run")
    if not isinstance(workflow, dict) or workflow.get("id") != RENDER_RUN_ID:
        raise ReviewStageError("artifact is not attached to the exact successful render run")


def validate_metadata(repository: Mapping[str, Any], main_ref: Mapping[str, Any],
                      run: Mapping[str, Any], input_artifact: Mapping[str, Any],
                      master_artifact: Mapping[str, Any], *, current_head: str,
                      now: datetime | None = None) -> None:
    now = now or datetime.now(timezone.utc)
    if (repository.get("full_name") != REPOSITORY or repository.get("private") is not False
            or repository.get("visibility") != "public"):
        raise ReviewStageError("expected the public render repository")
    main_sha = main_ref.get("object", {}).get("sha") if isinstance(main_ref.get("object"), dict) else None
    if main_sha != current_head:
        raise ReviewStageError("workflow checkout is not the live public main commit")
    if (run.get("id") != RENDER_RUN_ID or run.get("status") != "completed"
            or run.get("conclusion") != "success" or run.get("head_sha") != RENDER_HEAD):
        raise ReviewStageError("render run is not the exact completed S86 run")
    if run.get("html_url") != f"https://github.com/{REPOSITORY}/actions/runs/{RENDER_RUN_ID}":
        raise ReviewStageError("render run URL is not the pinned public run")
    _validate_artifact(input_artifact, artifact_id=INPUT_ARTIFACT_ID,
                       name=INPUT_ARTIFACT_NAME, size=INPUT_ARTIFACT_BYTES,
                       digest=INPUT_ARTIFACT_SHA256, now=now)
    _validate_artifact(master_artifact, artifact_id=MASTER_ARTIFACT_ID,
                       name=MASTER_ARTIFACT_NAME, size=MASTER_ARTIFACT_BYTES,
                       digest=MASTER_ARTIFACT_SHA256, now=now)


def validate_input_receipt(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict) or value.get("kind") != "agmm_short_exact_input_receipt":
        raise ReviewStageError("exact-input artifact lacks the native producer receipt")
    expected = {
        "source_sha256": SOURCE_SHA256, "source_bytes": SOURCE_BYTES,
        "parts_sha256": PARTS_SHA256, "parts_bytes": PARTS_BYTES,
        "mix_sha256": MIX_SHA256, "mix_bytes": MIX_BYTES,
        "duration": EXPECTED_DURATION, "frames": EXPECTED_FRAMES,
        "part_count": 4, "render_4k": True,
    }
    for key, wanted in expected.items():
        if value.get(key) != wanted:
            raise ReviewStageError(f"native input receipt mismatch at {key}")
    return value


def _safe_archive_names(zf: zipfile.ZipFile, *, kind: str) -> dict[str, zipfile.ZipInfo]:
    infos: dict[str, zipfile.ZipInfo] = {}
    total = 0
    for info in zf.infolist():
        raw = info.filename
        if raw.endswith("/"):
            continue
        path = PurePosixPath(raw)
        if "\\" in raw or path.is_absolute() or ".." in path.parts:
            raise ReviewStageError("artifact ZIP contains an unsafe path")
        mode = (info.external_attr >> 16) & 0xFFFF
        if mode and (mode & 0o170000) not in (0, 0o100000):
            raise ReviewStageError("artifact ZIP contains a non-regular file")
        parts = list(path.parts)
        expected_prefix = "exact-input" if kind == "input" else "remote-final"
        if parts and parts[0] == expected_prefix:
            parts = parts[1:]
        base = path.name
        if base in infos:
            raise ReviewStageError(f"artifact ZIP contains duplicate {base}")
        if kind == "input":
            if len(parts) != 1:
                raise ReviewStageError("exact-input member has an unexpected nested path")
            if base not in {"INPUT-RECEIPT.json", "MATRIX.json", "NORMALISED-PARTS.json",
                            "source.tar.gz", "parts.json", "mix.wav"}:
                raise ReviewStageError(f"unexpected exact-input artifact member: {raw}")
        else:
            permitted = {"FINAL.mp4", "FINAL-4K.mp4", "TECHNICAL-EVIDENCE.json", "SHA256SUMS.txt"}
            core = len(parts) == 1 and base in permitted
            review = len(parts) == 2 and parts[0] == "review" and base.lower().endswith(".jpg")
            if not (core or review):
                raise ReviewStageError(f"unexpected final-masters artifact member: {raw}")
        total += info.file_size
        if info.file_size < 0 or total > MAX_ARTIFACT_UNPACKED:
            raise ReviewStageError("artifact expanded size exceeds the bounded allowance")
        infos[base] = info
    return infos


def _extract_verified(zip_path: Path, info: zipfile.ZipInfo, destination: Path,
                      expected_size: int | None = None, expected_sha256: str | None = None) -> dict[str, Any]:
    digest = hashlib.sha256()
    count = 0
    destination.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(zip_path, "r") as zf, zf.open(info, "r") as source, destination.open("wb") as target:
        while True:
            chunk = source.read(1 << 20)
            if not chunk:
                break
            count += len(chunk)
            digest.update(chunk)
            target.write(chunk)
    actual = digest.hexdigest()
    if expected_size is not None and count != expected_size:
        destination.unlink(missing_ok=True)
        raise ReviewStageError(f"extracted {info.filename} has the wrong byte count")
    if expected_sha256 is not None and actual != expected_sha256:
        destination.unlink(missing_ok=True)
        raise ReviewStageError(f"extracted {info.filename} SHA-256 mismatch")
    return {"archive_path": info.filename, "bytes": count, "sha256": actual}


def _zip_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _read_text_member(zip_path: Path, info: zipfile.ZipInfo) -> Any:
    with zipfile.ZipFile(zip_path, "r") as zf, zf.open(info) as stream:
        if info.file_size > 2_000_000:
            raise ReviewStageError("receipt/manifest member is unexpectedly large")
        return json.loads(stream.read().decode("utf-8"))


def _read_bytes_member(zip_path: Path, info: zipfile.ZipInfo) -> bytes:
    with zipfile.ZipFile(zip_path, "r") as zf, zf.open(info) as stream:
        if info.file_size > 2_000_000:
            raise ReviewStageError("receipt/manifest member is unexpectedly large")
        return stream.read()


def _sum_map(data: bytes) -> dict[str, str]:
    rows = {}
    for raw in data.decode("utf-8").splitlines():
        match = re.fullmatch(r"([0-9a-f]{64})  (.+)", raw)
        if not match or match.group(2) in rows:
            raise ReviewStageError("master SHA256SUMS format is invalid or duplicated")
        rows[match.group(2)] = match.group(1)
    return rows


def validate_technical_evidence(value: Any, sums: Mapping[str, str]) -> dict[str, Any]:
    if not isinstance(value, dict) or value.get("technical_status") != "PASS":
        raise ReviewStageError("native technical evidence is absent or not PASS")
    if value.get("editorial_status") != "NOT_REVIEWED":
        raise ReviewStageError("unexpected editorial status in native evidence")
    rows = value.get("masters")
    if not isinstance(rows, list):
        raise ReviewStageError("native master list is missing")
    exact = [r for r in rows if isinstance(r, dict) and r.get("file") == "FINAL.mp4"]
    if len(exact) != 1:
        raise ReviewStageError("expected exactly one native FINAL.mp4 evidence row")
    row = exact[0]
    if (row.get("sha256") != MASTER_SHA256 or row.get("bytes") != MASTER_BYTES
            or row.get("resolution") != "1080" or row.get("frames") != EXPECTED_FRAMES
            or row.get("full_decode") != "PASS"):
        raise ReviewStageError("native FINAL.mp4 evidence does not match the exact S86 master")
    if row.get("probe", {}).get("format", {}).get("duration") not in ("60.600000", 60.6):
        raise ReviewStageError("native final master duration changed")
    streams = row.get("probe", {}).get("streams", [])
    video = [s for s in streams if isinstance(s, dict) and s.get("codec_type") == "video"]
    audio = [s for s in streams if isinstance(s, dict) and s.get("codec_type") == "audio"]
    if (len(video) != 1 or len(audio) != 1 or video[0].get("width") != 1080
            or video[0].get("height") != 1920 or video[0].get("nb_read_frames") != "1818"
            or audio[0].get("codec_name") != "aac" or audio[0].get("sample_rate") != "48000"
            or audio[0].get("channels") != 2):
        raise ReviewStageError("S86 exact master stream/frame contract mismatch")
    if sums.get("FINAL.mp4") != MASTER_SHA256:
        raise ReviewStageError("SHA256SUMS does not bind the exact S86 1080 master")
    return row


def extract_review_assets(input_zip: Path, master_zip: Path, input_metadata: Mapping[str, Any],
                         master_metadata: Mapping[str, Any], out: Path) -> dict[str, Any]:
    if _zip_sha256(input_zip) != INPUT_ARTIFACT_SHA256:
        raise ReviewStageError("downloaded exact-input artifact archive digest mismatch")
    if _zip_sha256(master_zip) != MASTER_ARTIFACT_SHA256:
        raise ReviewStageError("downloaded final-masters artifact archive digest mismatch")
    with zipfile.ZipFile(input_zip, "r") as zf:
        input_members = _safe_archive_names(zf, kind="input")
    if set(input_members) != {"INPUT-RECEIPT.json", "MATRIX.json", "NORMALISED-PARTS.json",
                              "source.tar.gz", "parts.json", "mix.wav"}:
        raise ReviewStageError("exact-input artifact member inventory differs from native receipt")
    input_raw = _read_bytes_member(input_zip, input_members["INPUT-RECEIPT.json"])
    input_receipt = validate_input_receipt(json.loads(input_raw.decode("utf-8")))
    with zipfile.ZipFile(master_zip, "r") as zf:
        master_members = _safe_archive_names(zf, kind="master")
    for required in ("FINAL.mp4", "FINAL-4K.mp4", "TECHNICAL-EVIDENCE.json", "SHA256SUMS.txt"):
        if required not in master_members:
            raise ReviewStageError(f"final-masters artifact lacks {required}")
    if (input_metadata.get("id") != INPUT_ARTIFACT_ID or master_metadata.get("id") != MASTER_ARTIFACT_ID
            or input_metadata.get("workflow_run", {}).get("id") != RENDER_RUN_ID
            or master_metadata.get("workflow_run", {}).get("id") != RENDER_RUN_ID):
        raise ReviewStageError("artifact IDs are not bound to the pinned render run")
    tech_raw = _read_bytes_member(master_zip, master_members["TECHNICAL-EVIDENCE.json"])
    tech = json.loads(tech_raw.decode("utf-8"))
    with zipfile.ZipFile(master_zip, "r") as zf, zf.open(master_members["SHA256SUMS.txt"]) as stream:
        sums = _sum_map(stream.read(100_000))
    tech_row = validate_technical_evidence(tech, sums)
    out.mkdir(parents=True, exist_ok=False)
    copied = _extract_verified(master_zip, master_members["FINAL.mp4"], out / MASTER_NAME,
                               MASTER_BYTES, MASTER_SHA256)
    (out / "INPUT-RECEIPT.json").write_bytes(input_raw)
    (out / "TECHNICAL-EVIDENCE.json").write_bytes(tech_raw)
    sum_rows = []
    for name in (MASTER_NAME, "INPUT-RECEIPT.json", "TECHNICAL-EVIDENCE.json"):
        path = out / name
        sum_rows.append(f"{_file_sha256(path)}  {name}")
    (out / "SHA256SUMS.txt").write_text("\n".join(sum_rows) + "\n", encoding="ascii")
    receipt = {
        "schema": "agmm-s86-review-playback-v1",
        "status": "PUBLIC_REVIEW_PLAYBACK_ONLY",
        "repository": REPOSITORY,
        "render_run_id": RENDER_RUN_ID,
        "render_head_sha": RENDER_HEAD,
        "render_run_url": f"https://github.com/{REPOSITORY}/actions/runs/{RENDER_RUN_ID}",
        "source": {"sha256": SOURCE_SHA256, "bytes": SOURCE_BYTES,
                   "parts_sha256": PARTS_SHA256, "mix_sha256": MIX_SHA256},
        "input_artifact": {"id": INPUT_ARTIFACT_ID, "name": INPUT_ARTIFACT_NAME,
                           "bytes": INPUT_ARTIFACT_BYTES, "sha256": INPUT_ARTIFACT_SHA256},
        "master_artifact": {"id": MASTER_ARTIFACT_ID, "name": MASTER_ARTIFACT_NAME,
                            "bytes": MASTER_ARTIFACT_BYTES, "sha256": MASTER_ARTIFACT_SHA256},
        "master": {**copied, "asset_name": MASTER_NAME, "resolution": "1080x1920",
                   "duration_seconds": EXPECTED_DURATION, "frames": EXPECTED_FRAMES,
                   "video_codec": "h264", "audio_codec": "aac", "audio_sample_rate": 48000,
                   "audio_channels": 2, "native_full_decode": tech_row["full_decode"]},
        "playback_url": REVIEW_URL,
        "playback_transport": "UNVERIFIED_UNTIL_PUBLIC_RANGE_CHECK",
        "editorial_status": "NOT_REVIEWED",
        "full_master_visual_review": "OPEN",
        "every_frame_and_motion_review": "OPEN",
        "audio_and_narration_listening": "OPEN",
        "pilot_level_craft_review": "OPEN",
        "thumbnail_review": "OPEN",
        "ready_approval": "NOT_GRANTED",
        "release_approval": "NOT_GRANTED",
        "scope_note": "Exact native 1080 master copied without rendering/transcoding. Publishing this review-only asset does not grant Ready or editorial approval.",
    }
    (out / "REVIEW-PLAYBACK-RECEIPT.json").write_text(json.dumps(receipt, indent=2) + "\n", encoding="utf-8")
    return receipt


def asset_inventory(directory: Path, *, finalized: bool = False) -> dict[str, dict[str, Any]]:
    """Return exact release asset sizes/digests for the staged allowlist."""
    files = sorted(p for p in directory.iterdir() if p.is_file())
    expected_names = FINAL_RELEASE_ASSET_NAMES if finalized else RELEASE_ASSET_NAMES
    if {p.name for p in files} != set(expected_names):
        raise ReviewStageError("staging directory differs from the exact release asset allowlist")
    out = {}
    for path in files:
        h = hashlib.sha256(); size = 0
        with path.open("rb") as stream:
            for block in iter(lambda: stream.read(1 << 20), b""):
                h.update(block); size += len(block)
        out[path.name] = {"size": size, "digest": f"sha256:{h.hexdigest()}"}
    if out[MASTER_NAME] != {"size": MASTER_BYTES, "digest": f"sha256:{MASTER_SHA256}"}:
        raise ReviewStageError("staged release master no longer matches its exact identity")
    return out


def finalize_playback_manifest(directory: Path, range_result: Mapping[str, Any]) -> dict[str, Any]:
    if range_result.get("status") != 206 or range_result.get("content_range") != f"bytes 0-0/{MASTER_BYTES}" or range_result.get("bytes_read") != 1:
        raise ReviewStageError("cannot create library manifest without exact hosted range verification")
    transport = {
        "schema": "agmm-public-playback-transport-check-v1",
        "status": "RANGE_RESPONSE_VERIFIED_ONLY",
        "review_url": REVIEW_URL,
        "master_sha256": MASTER_SHA256,
        "master_bytes": MASTER_BYTES,
        "http_status": 206,
        "content_range": f"bytes 0-0/{MASTER_BYTES}",
        "bytes_read_on_public_github_actions_linux": 1,
        "final_host": range_result.get("final_host"),
        "content_type": range_result.get("content_type"),
        "full_playback_verified": False,
        "human_visual_audio_review": "OPEN",
        "ready_approval": "NOT_GRANTED",
        "release_approval": "NOT_GRANTED",
    }
    manifest = [{"cardID": "S86", "url": REVIEW_URL, "sha256": MASTER_SHA256,
                 "size": MASTER_BYTES, "status": "review-pending"}]
    (directory / "PLAYBACK-TRANSPORT-VERIFICATION.json").write_text(json.dumps(transport, indent=2) + "\n", encoding="utf-8")
    (directory / "HOSTED-MEDIA-MANIFEST.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    return transport


def release_absence_result(status: int, body: Any, tag: str = REVIEW_TAG) -> bool:
    """Return True only for a proven exact-tag HTTP 404; ambiguity always fails."""
    if status == 404:
        if body not in (None, {}, ""):
            message = body.get("message") if isinstance(body, dict) else str(body)
            if message != "Not Found":
                raise ReviewStageError("404 body is not GitHub's exact not-found response")
        return True
    if status == 200:
        if not isinstance(body, dict) or body.get("tag_name") != tag:
            raise ReviewStageError("tag lookup returned a different release")
        raise ReviewStageError("review release tag already exists; refusing duplicate or overwrite")
    raise ReviewStageError(f"tag absence ambiguous (HTTP {status}); do not create release")


def release_list_absence(pages: Any, tag: str = REVIEW_TAG) -> bool:
    if not isinstance(pages, list):
        raise ReviewStageError("release-list response is not paginated JSON")
    for page in pages:
        if not isinstance(page, list):
            raise ReviewStageError("release-list page has unexpected schema")
        if any(isinstance(row, dict) and row.get("tag_name") == tag for row in page):
            raise ReviewStageError("an exact-tag release or draft already exists; refusing create")
    return True


def select_exact_draft(pages: Any, tag: str = REVIEW_TAG) -> int:
    if not isinstance(pages, list):
        raise ReviewStageError("release listing is not a paginated JSON list")
    rows = []
    for page in pages:
        if isinstance(page, list):
            rows.extend(page)
        else:
            raise ReviewStageError("unexpected release-list page schema")
    matches = [r for r in rows if isinstance(r, dict) and r.get("tag_name") == tag]
    if len(matches) != 1:
        raise ReviewStageError(f"expected one exact draft tag, found {len(matches)}")
    row = matches[0]
    rid = row.get("id")
    if row.get("draft") is not True or not _positive_int(rid):
        raise ReviewStageError("exact release tag is not a valid draft")
    return rid


def validate_release_by_id(release: Mapping[str, Any], release_id: int,
                           expected_assets: Mapping[str, Mapping[str, Any]] | None = None,
                           *, published: bool = False) -> None:
    if (release.get("id") != release_id or release.get("tag_name") != REVIEW_TAG
            or release.get("draft") is not (not published) or release.get("prerelease") is not True):
        raise ReviewStageError("by-ID release is not the exact review-only release state")
    assets = release.get("assets")
    if not isinstance(assets, list):
        raise ReviewStageError("release asset metadata is missing")
    names = [a.get("name") for a in assets if isinstance(a, dict)]
    target_names = FINAL_RELEASE_ASSET_NAMES if published else RELEASE_ASSET_NAMES
    if set(names) != set(target_names) or len(names) != len(target_names):
        raise ReviewStageError("release assets differ from the exact review-only allowlist")
    if expected_assets is not None and set(expected_assets) != set(target_names):
        raise ReviewStageError("expected release asset inventory is not the exact allowlist")
    for asset in assets:
        if not isinstance(asset, dict) or asset.get("state") != "uploaded" or not _positive_int(asset.get("id")):
            raise ReviewStageError("release asset is not uploaded or has invalid ID")
        if expected_assets is not None:
            expected = expected_assets[asset["name"]]
            if asset.get("size") != expected["size"] or asset.get("digest") != expected["digest"]:
                raise ReviewStageError(f"release asset size/digest mismatch: {asset['name']}")


class _AllowedRedirects(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        parsed = urllib.parse.urlsplit(newurl)
        if parsed.scheme != "https" or parsed.hostname not in ALLOWED_REDIRECT_HOSTS or parsed.port not in (None, 443):
            raise ReviewStageError("public asset redirect left the HTTPS GitHub allowlist")
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def verify_public_range(url: str = REVIEW_URL, opener=None) -> dict[str, Any]:
    """Hosted-only 1-byte range probe; no media is stored by the caller."""
    parsed = urllib.parse.urlsplit(url)
    if (parsed.scheme != "https" or parsed.hostname != "github.com"
            or parsed.path != f"/{REPOSITORY}/releases/download/{REVIEW_TAG}/{MASTER_NAME}"):
        raise ReviewStageError("playback URL differs from exact S86 review asset URL")
    if opener is None:
        opener = urllib.request.build_opener(_AllowedRedirects())
    request = urllib.request.Request(url, headers={"Range": "bytes=0-0", "Accept-Encoding": "identity"}, method="GET")
    try:
        with opener.open(request, timeout=20) as response:
            final = urllib.parse.urlsplit(response.geturl())
            if final.scheme != "https" or final.hostname not in ALLOWED_REDIRECT_HOSTS:
                raise ReviewStageError("final playback host is not allowlisted")
            content_range = response.headers.get("Content-Range")
            content_type = response.headers.get("Content-Type", "").split(";", 1)[0].lower()
            body = response.read(2)
            if (response.status != 206 or content_range != f"bytes 0-0/{MASTER_BYTES}"
                    or content_type not in ("video/mp4", "application/octet-stream") or len(body) != 1):
                raise ReviewStageError("public review asset failed its exact single-byte range response")
            return {"status": response.status, "content_range": content_range,
                    "content_type": content_type, "final_host": final.hostname,
                    "bytes_read": len(body), "full_playback_verified": False}
    except (OSError, urllib.error.URLError, urllib.error.HTTPError) as exc:
        raise ReviewStageError(f"public playback range check failed: {type(exc).__name__}") from exc


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="command", required=True)
    check = sub.add_parser("validate-metadata")
    check.add_argument("repository", type=Path); check.add_argument("main_ref", type=Path)
    check.add_argument("run", type=Path); check.add_argument("input_artifact", type=Path)
    check.add_argument("master_artifact", type=Path); check.add_argument("--current-head", required=True)
    prepare = sub.add_parser("prepare")
    prepare.add_argument("repository", type=Path); prepare.add_argument("main_ref", type=Path)
    prepare.add_argument("run", type=Path); prepare.add_argument("input_artifact", type=Path)
    prepare.add_argument("master_artifact", type=Path); prepare.add_argument("--current-head", required=True)
    prepare.add_argument("--input-zip", type=Path, required=True)
    prepare.add_argument("--master-zip", type=Path, required=True)
    prepare.add_argument("--out", type=Path, required=True)
    receipt = sub.add_parser("validate-input-receipt"); receipt.add_argument("path", type=Path)
    absent = sub.add_parser("check-release-absence")
    absent.add_argument("--http-status", required=True, type=int); absent.add_argument("body", type=Path)
    list_absent = sub.add_parser("check-release-list-absence"); list_absent.add_argument("pages", type=Path)
    ref_absent = sub.add_parser("check-tag-ref-absence")
    ref_absent.add_argument("--http-status", required=True, type=int); ref_absent.add_argument("body", type=Path)
    draft = sub.add_parser("select-draft"); draft.add_argument("pages", type=Path)
    release = sub.add_parser("validate-release"); release.add_argument("release", type=Path)
    release.add_argument("inventory", type=Path); release.add_argument("--release-id", type=int, required=True)
    release.add_argument("--published", action="store_true")
    final = sub.add_parser("finalize-playback"); final.add_argument("directory", type=Path)
    args = ap.parse_args(argv)
    if args.command == "validate-metadata":
        now = datetime.now(timezone.utc)
        validate_metadata(*(json.loads(p.read_text(encoding="utf-8")) for p in
                            (args.repository,args.main_ref,args.run,args.input_artifact,args.master_artifact)),
                          current_head=args.current_head, now=now)
        print("S86 pinned public run/artifact/expiry metadata PASS")
    elif args.command == "prepare":
        require_hosted_runner(os.environ, platform.system())
        docs = [json.loads(p.read_text(encoding="utf-8")) for p in
                (args.repository,args.main_ref,args.run,args.input_artifact,args.master_artifact)]
        validate_metadata(*docs, current_head=args.current_head, now=datetime.now(timezone.utc))
        receipt = extract_review_assets(args.input_zip, args.master_zip, docs[3], docs[4], args.out)
        assets = asset_inventory(args.out)
        (args.out.parent / "RELEASE-ASSET-INVENTORY.json").write_text(json.dumps(assets, indent=2) + "\n", encoding="utf-8")
        print(json.dumps({"prepared": True, "tag": REVIEW_TAG,
                          "master_sha256": receipt["master"]["sha256"],
                          "asset_names": sorted(assets)}))
    elif args.command == "finalize-playback":
        require_hosted_runner(os.environ, platform.system())
        range_result = verify_public_range()
        receipt = finalize_playback_manifest(args.directory, range_result)
        assets = asset_inventory(args.directory, finalized=True)
        (args.directory.parent / "FINAL-RELEASE-ASSET-INVENTORY.json").write_text(json.dumps(assets, indent=2) + "\n", encoding="utf-8")
        print(json.dumps({"range_probe": receipt, "final_asset_names": sorted(assets)}))
    elif args.command == "validate-input-receipt":
        validate_input_receipt(json.loads(args.path.read_text(encoding="utf-8")))
        print("S86 native source/input receipt PASS")
    elif args.command == "check-release-absence":
        body = json.loads(args.body.read_text(encoding="utf-8")) if args.body.exists() and args.body.stat().st_size else None
        release_absence_result(args.http_status, body)
        print("Exact review-release tag absent (HTTP 404) PASS")
    elif args.command == "check-release-list-absence":
        release_list_absence(json.loads(args.pages.read_text(encoding="utf-8")))
        print("No matching release or draft in complete authenticated release listing PASS")
    elif args.command == "check-tag-ref-absence":
        body = json.loads(args.body.read_text(encoding="utf-8")) if args.body.exists() and args.body.stat().st_size else None
        if args.http_status != 404 or (body not in (None, {}, "") and
                                       (not isinstance(body, dict) or body.get("message") != "Not Found")):
            raise ReviewStageError("Git tag absence is ambiguous or tag already exists")
        print("Exact Git tag absence (HTTP 404) PASS")
    elif args.command == "select-draft":
        print(select_exact_draft(json.loads(args.pages.read_text(encoding="utf-8"))))
    elif args.command == "validate-release":
        validate_release_by_id(json.loads(args.release.read_text(encoding="utf-8")), args.release_id,
                               json.loads(args.inventory.read_text(encoding="utf-8")),
                               published=args.published)
        print("Exact by-ID release and asset inventory PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
