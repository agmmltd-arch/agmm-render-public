"""Fail-closed text queue adoption for the hosted YouTube Studio schedule route.

This does not download or inspect media. The Ubuntu workflow owns byte hashing,
Studio scheduling and its provider receipt. This module only binds text pins and
that receipt to one unique future YouTube slot.
"""
from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

HEX = re.compile(r"^[0-9a-f]{64}$")
LONDON = ZoneInfo("Europe/London")


def valid_youtube_identity(video_id, url):
    return (isinstance(video_id, str) and bool(re.fullmatch(r"[A-Za-z0-9_-]{11}", video_id))
            and url == f"https://www.youtube.com/watch?v={video_id}")


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _need(condition: bool, message: str) -> None:
    if not condition:
        raise ValueError(message)


def london_slot(day: str, slot: str) -> datetime:
    """Resolve a UK wall-clock slot only when it names one real instant."""
    _need(bool(re.fullmatch(r"\d{2}:\d{2}", slot)), "invalid slot")
    naive = datetime.fromisoformat(f"{day}T{slot}:00")
    variants = [naive.replace(tzinfo=LONDON, fold=fold) for fold in (0, 1)]
    valid = [v for v in variants if v.astimezone(timezone.utc).astimezone(LONDON).replace(tzinfo=None) == naive]
    instants = {v.astimezone(timezone.utc) for v in valid}
    _need(len(instants) == 1, "UK slot is ambiguous or nonexistent at clock change")
    return valid[0]


def occupied_youtube_slot(row: dict, day: str, slot: str) -> bool:
    """Recognize native plan rows as well as hosted queue rows, without guessing dates."""
    _need(isinstance(row, dict), "existing row must be an object")
    if row.get("slot") and not row.get("date"):
        raise ValueError("existing row slot requires its plan date")
    platforms = row.get("platforms") or []
    _need(isinstance(platforms, list), "existing row platforms must be a list")
    youtube = row.get("platform") == "youtube" or "youtube" in platforms
    return youtube and row.get("date") == day and row.get("slot") == slot


def earliest_slot(day: str, candidates: list[str], existing_rows: list[dict],
                  now: datetime) -> str:
    """Select the earliest future, unoccupied offered slot (Studio requires 15m lead)."""
    _need(bool(candidates), "no candidate slots")
    _need(now.tzinfo is not None and now.utcoffset() is not None, "current time requires timezone")
    now = now.astimezone(timezone.utc)
    for slot in sorted(set(candidates)):
        _need(bool(re.fullmatch(r"\d{2}:\d{2}", slot)), "invalid candidate slot")
        when = london_slot(day, slot).astimezone(timezone.utc)
        if when <= now or any(occupied_youtube_slot(r, day, slot) for r in existing_rows):
            continue
        if (when - now).total_seconds() >= 15 * 60:
            return slot
    raise ValueError("no earliest future unoccupied YouTube slot with 15-minute lead")


def validate_approval(approval: dict, *, master_sha256: str,
                      source_run_id: str) -> None:
    _need(HEX.fullmatch(master_sha256) is not None, "invalid master sha256")
    _need(approval.get("overall") == "PASS", "independent approval is not PASS")
    _need(approval.get("master_sha256") == master_sha256, "approval master mismatch")
    _need(str(approval.get("source_run_id")) == str(source_run_id), "approval source run mismatch")
    _need(approval.get("reviewer_id") and approval.get("maker_id"), "reviewer/maker identity missing")
    _need(approval["reviewer_id"] != approval["maker_id"], "maker cannot approve own work")
    av = approval.get("audiovisual_review") or {}
    for key in ("continuous_visual", "continuous_audio", "motion", "pilot_craft", "thumbnail"):
        _need(av.get(key) == "PASS", f"independent {key} review missing or not PASS")


def make_queue_row(*, approval: dict, provider_receipt: dict | None,
                   source_run_id: str, artifact_name: str, video_name: str,
                   master_sha256: str, approval_sha256: str, metadata_sha256: str,
                   caption_sha256: str,
                   thumbnail_sha256: str, day: str, slot: str, post_id: str,
                   existing_rows: list[dict]) -> dict:
    """Return a held row, or ARMED only on the exact verified Studio receipt."""
    validate_approval(approval, master_sha256=master_sha256,
                      source_run_id=source_run_id)
    _need(artifact_name and source_run_id.isdigit(), "artifact/run pin missing")
    _need(video_name.endswith(".mp4") and "/" not in video_name, "video must be one exact artifact MP4 basename")
    _need(HEX.fullmatch(metadata_sha256) is not None, "invalid metadata sha256")
    _need(HEX.fullmatch(approval_sha256) is not None, "invalid approval sha256")
    _need(HEX.fullmatch(caption_sha256) is not None, "invalid caption sha256")
    _need(HEX.fullmatch(thumbnail_sha256) is not None, "invalid thumbnail sha256")
    _need(bool(re.fullmatch(r"\d{2}:\d{2}", slot)), "invalid slot")
    _need(approval.get("date") == day, "approval date differs from requested plan date")
    _need(post_id, "post_id missing")
    for row in existing_rows:
        _need(row.get("post_id") != post_id, "duplicate post_id")
        _need(not occupied_youtube_slot(row, day, slot), "duplicate YouTube slot")
        _need(row.get("master_sha256") != master_sha256 and row.get("video_sha256") != master_sha256,
              "master already queued")

    base = {
        "schema": "agmm-hosted-youtube-queue-row-v1",
        "platform": "youtube",
        "route": "public-ubuntu-youtube-studio",
        "post_id": post_id,
        "date": day,
        "slot": slot,
        "status": "HELD_AWAITING_PROVIDER_SCHEDULE",
        "source_run_id": str(source_run_id),
        "artifact_name": artifact_name,
        "video_name": video_name,
        "master_sha256": master_sha256,
        "approval_sha256": approval_sha256,
        "metadata_sha256": metadata_sha256,
        "caption_sha256": caption_sha256,
        "thumbnail_sha256": thumbnail_sha256,
    }
    if provider_receipt is None:
        return base
    _need(provider_receipt.get("schema") == "agmm-youtube-cloud-studio-scheduled-v1",
          "unsupported provider receipt schema")
    _need(provider_receipt.get("overall") == "SCHEDULED_VERIFIED", "provider schedule not verified")
    _need(provider_receipt.get("master_sha256") == master_sha256, "provider receipt master mismatch")
    _need(str(provider_receipt.get("source_run_id")) == str(source_run_id), "provider receipt run mismatch")
    _need(provider_receipt.get("thumbnail_sha256") == thumbnail_sha256, "provider receipt thumbnail mismatch")
    _need(provider_receipt.get("scheduled_evidence", {}).get("ok") is True,
          "provider schedule evidence missing")
    scheduled = datetime.fromisoformat(provider_receipt["scheduled_for"])
    _need(scheduled.tzinfo is not None and scheduled.utcoffset() is not None, "provider schedule timezone missing")
    _need(scheduled.isoformat() == provider_receipt["scheduled_for"], "non-canonical scheduled instant")
    local = scheduled.astimezone(LONDON)
    _need(local.date().isoformat() == day, "provider schedule date differs from plan date")
    _need(scheduled.astimezone(timezone.utc) == london_slot(day, slot).astimezone(timezone.utc),
          "provider scheduled time differs from queue slot")
    base.update(status="ARMED", provider_video_id=provider_receipt.get("video_id"),
                provider_url=provider_receipt.get("post_url"),
                provider_scheduled_for=provider_receipt["scheduled_for"],
                provider_receipt_sha256=sha256_bytes(json.dumps(provider_receipt, sort_keys=True).encode()))
    _need(valid_youtube_identity(base["provider_video_id"], base["provider_url"]), "provider identity invalid")
    base.update(route="hosted_youtube_studio", kind="hosted_remote", platforms=["youtube"],
                video_sha256=master_sha256, hosted_source_run_id=str(source_run_id),
                hosted_thumbnail_sha256=thumbnail_sha256, provider_receipt=provider_receipt,
                held_reason="")
    return base
