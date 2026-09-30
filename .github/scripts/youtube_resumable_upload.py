#!/usr/bin/env python3
"""Upload one reviewed video to YouTube as PRIVATE via the resumable API.

This is the storage-free bridge from a GitHub Actions master artifact to
YouTube. It deliberately cannot publish: Studio performs the final metadata,
thumbnail and PUBLIC transition only after the private upload receipt exists.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import socket
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path


TOKEN_URL = "https://oauth2.googleapis.com/token"
UPLOAD_URL = (
    "https://www.googleapis.com/upload/youtube/v3/videos"
    "?uploadType=resumable&part=snippet,status"
)
CHUNK = 64 * 1024 * 1024  # 64 MiB; an exact multiple of the required 256 KiB.
RETRIABLE = {500, 502, 503, 504}


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for block in iter(lambda: f.read(8 * 1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def json_error(exc: urllib.error.HTTPError) -> str:
    raw = exc.read(8192).decode("utf-8", errors="replace")
    try:
        payload = json.loads(raw)
        err = payload.get("error") or {}
        return f"HTTP {exc.code}: {err.get('message') or raw[:400]}"
    except json.JSONDecodeError:
        return f"HTTP {exc.code}: {raw[:400]}"


def refresh_access_token() -> str:
    required = ("YOUTUBE_CLIENT_ID", "YOUTUBE_CLIENT_SECRET", "YOUTUBE_REFRESH_TOKEN")
    missing = [key for key in required if not os.environ.get(key)]
    if missing:
        raise RuntimeError(f"missing secret environment variables: {', '.join(missing)}")
    body = urllib.parse.urlencode({
        "client_id": os.environ["YOUTUBE_CLIENT_ID"],
        "client_secret": os.environ["YOUTUBE_CLIENT_SECRET"],
        "refresh_token": os.environ["YOUTUBE_REFRESH_TOKEN"],
        "grant_type": "refresh_token",
    }).encode()
    req = urllib.request.Request(
        TOKEN_URL, data=body,
        headers={"Content-Type": "application/x-www-form-urlencoded"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as response:
            payload = json.loads(response.read())
    except urllib.error.HTTPError as exc:
        raise RuntimeError(f"OAuth refresh failed: {json_error(exc)}") from None
    token = payload.get("access_token")
    if not token:
        raise RuntimeError("OAuth refresh returned no access token")
    return str(token)


def start_session(token: str, video: Path, metadata: dict) -> str:
    body = json.dumps(metadata, separators=(",", ":")).encode()
    req = urllib.request.Request(
        UPLOAD_URL,
        data=body,
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json; charset=UTF-8",
            "Content-Length": str(len(body)),
            "X-Upload-Content-Length": str(video.stat().st_size),
            "X-Upload-Content-Type": "video/mp4",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=60) as response:
            location = response.headers.get("Location")
    except urllib.error.HTTPError as exc:
        raise RuntimeError(f"resumable session creation failed: {json_error(exc)}") from None
    if not location or not location.startswith("https://www.googleapis.com/upload/"):
        raise RuntimeError("YouTube returned no trusted resumable session URL")
    return location


def accepted_end(range_header: str | None) -> int:
    if not range_header:
        return -1
    match = re.fullmatch(r"bytes=0-(\d+)", range_header.strip())
    if not match:
        raise RuntimeError(f"unexpected resumable Range header: {range_header!r}")
    return int(match.group(1))


def request_status(session: str, token: str, total: int) -> tuple[int, dict | None]:
    req = urllib.request.Request(
        session,
        data=b"",
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Length": "0",
            "Content-Range": f"bytes */{total}",
        },
        method="PUT",
    )
    try:
        with urllib.request.urlopen(req, timeout=60) as response:
            return total - 1, json.loads(response.read() or b"{}")
    except urllib.error.HTTPError as exc:
        if exc.code == 308:
            return accepted_end(exc.headers.get("Range")), None
        raise RuntimeError(f"upload status query failed: {json_error(exc)}") from None


def upload_chunks(session: str, token: str, video: Path) -> dict:
    total = video.stat().st_size
    offset = 0
    retries = 0
    with video.open("rb") as source:
        while offset < total:
            source.seek(offset)
            chunk = source.read(min(CHUNK, total - offset))
            if not chunk:
                raise RuntimeError("video ended before its recorded size")
            end = offset + len(chunk) - 1
            req = urllib.request.Request(
                session,
                data=chunk,
                headers={
                    "Authorization": f"Bearer {token}",
                    "Content-Type": "video/mp4",
                    "Content-Length": str(len(chunk)),
                    "Content-Range": f"bytes {offset}-{end}/{total}",
                },
                method="PUT",
            )
            try:
                with urllib.request.urlopen(req, timeout=600) as response:
                    payload = json.loads(response.read() or b"{}")
                    if response.status not in (200, 201):
                        raise RuntimeError(f"unexpected final upload status {response.status}")
                    return payload
            except urllib.error.HTTPError as exc:
                if exc.code == 308:
                    accepted = accepted_end(exc.headers.get("Range"))
                    if accepted < offset:
                        raise RuntimeError("YouTube did not accept the current contiguous chunk")
                    offset = accepted + 1
                    retries = 0
                    print(f"uploaded {offset}/{total} bytes ({offset * 100 / total:.1f}%)", flush=True)
                    continue
                if exc.code not in RETRIABLE:
                    raise RuntimeError(f"video upload failed permanently: {json_error(exc)}") from None
            except (urllib.error.URLError, TimeoutError, socket.timeout):
                pass

            retries += 1
            if retries > 8:
                raise RuntimeError("video upload exceeded retry limit")
            time.sleep(min(2 ** retries, 32))
            accepted, completed = request_status(session, token, total)
            if completed is not None:
                return completed
            offset = accepted + 1
            print(f"resuming at byte {offset} after retry {retries}", flush=True)
    raise RuntimeError("upload loop ended without a YouTube response")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--video", required=True, type=Path)
    ap.add_argument("--metadata", required=True, type=Path)
    ap.add_argument("--approval", required=True, type=Path)
    ap.add_argument("--expected-sha256", required=True)
    ap.add_argument("--source-run-id", required=True)
    ap.add_argument("--out", required=True, type=Path)
    args = ap.parse_args()
    if not args.video.is_file():
        raise FileNotFoundError(args.video)
    actual_sha = sha256(args.video)
    if actual_sha != args.expected_sha256:
        raise RuntimeError(f"master SHA mismatch: expected {args.expected_sha256}, got {actual_sha}")

    metadata = json.loads(args.metadata.read_text())
    approval = json.loads(args.approval.read_text())
    if approval.get("overall") != "PASS" or approval.get("film") != "F07":
        raise RuntimeError("release approval is not a PASS for F07")
    if approval.get("master_sha256") != actual_sha:
        raise RuntimeError("release approval does not cover these master bytes")
    if str(approval.get("source_run_id")) != str(args.source_run_id):
        raise RuntimeError("release approval covers a different source run")

    status = metadata.setdefault("status", {})
    if status.get("privacyStatus") != "private":
        raise RuntimeError("cloud bridge may only upload PRIVATE")
    if status.get("selfDeclaredMadeForKids") is not False:
        raise RuntimeError("made-for-kids declaration must be false")
    if status.get("containsSyntheticMedia") is not True:
        raise RuntimeError("synthetic-media disclosure must be true")

    token = refresh_access_token()
    session = start_session(token, args.video, metadata)
    response = upload_chunks(session, token, args.video)
    video_id = str(response.get("id") or "")
    privacy = str((response.get("status") or {}).get("privacyStatus") or "")
    if not re.fullmatch(r"[A-Za-z0-9_-]{11}", video_id):
        raise RuntimeError("YouTube returned no valid video id")
    if privacy != "private":
        raise RuntimeError(f"cloud bridge expected PRIVATE but YouTube returned {privacy!r}")
    receipt = {
        "kind": "youtube_private_cloud_upload",
        "film": "F07",
        "source_run_id": str(args.source_run_id),
        "master_sha256": actual_sha,
        "master_bytes": args.video.stat().st_size,
        "video_id": video_id,
        "studio_url": f"https://studio.youtube.com/video/{video_id}/edit",
        "watch_url": f"https://www.youtube.com/watch?v={video_id}",
        "privacy_status": privacy,
        "public": False,
        "title": str((metadata.get("snippet") or {}).get("title") or ""),
        "uploaded_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "finalisation_required": "Studio metadata, approved thumbnail, PUBLIC, Studio row and logged-out oEmbed",
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(receipt, indent=2) + "\n")
    print(json.dumps({"status": "PRIVATE_UPLOADED", "video_id": video_id, "receipt": str(args.out)}))


if __name__ == "__main__":
    main()
