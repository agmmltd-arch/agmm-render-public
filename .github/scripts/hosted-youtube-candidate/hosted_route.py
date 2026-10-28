"""Read-only reconciliation branch for a remotely scheduled YouTube row."""
from __future__ import annotations

from datetime import datetime, timezone
from zoneinfo import ZoneInfo
from queue_contract import london_slot

LONDON = ZoneInfo("Europe/London")


def hosted_route_result(row: dict, now: datetime) -> dict | None:
    """Return a visible state for hosted rows; never call a local media adapter."""
    if row.get("route") != "hosted_youtube_studio":
        return None
    if row.get("platforms") != ["youtube"] or row.get("status") != "ARMED":
        return {"status": "hosted_route_invalid_row", "ok": False,
                "detail": "hosted route requires one ARMED YouTube destination"}
    receipt = row.get("provider_receipt")
    if not isinstance(receipt, dict):
        return {"status": "hosted_schedule_receipt_missing", "ok": False,
                "detail": "no provider schedule receipt; no local publisher call"}
    if receipt.get("schema") != "agmm-youtube-cloud-studio-scheduled-v1" or \
       receipt.get("overall") != "SCHEDULED_VERIFIED" or \
       receipt.get("scheduled_evidence", {}).get("ok") is not True:
        return {"status": "hosted_schedule_receipt_invalid", "ok": False,
                "detail": "provider did not verify schedule; no local publisher call"}
    for row_key, rec_key in (("video_sha256", "master_sha256"),
                             ("hosted_source_run_id", "source_run_id"),
                             ("hosted_thumbnail_sha256", "thumbnail_sha256")):
        if str(row.get(row_key) or "") != str(receipt.get(rec_key) or ""):
            return {"status": "hosted_schedule_binding_mismatch", "ok": False,
                    "detail": f"{row_key} does not match provider receipt"}
    if not receipt.get("video_id") or not receipt.get("post_url"):
        return {"status": "hosted_schedule_identity_missing", "ok": False,
                "detail": "provider receipt has no video identity"}
    try:
        when = datetime.fromisoformat(str(receipt.get("scheduled_for")))
        if when.tzinfo is None or when.utcoffset() is None or now.tzinfo is None or now.utcoffset() is None:
            raise ValueError("timezone missing")
        expected = london_slot(row['date'], row['slot'])
    except (ValueError, KeyError, TypeError):
        return {"status": "hosted_schedule_time_mismatch", "ok": False,
                "detail": "invalid or ambiguous scheduled instant"}
    if when.astimezone(timezone.utc) != expected.astimezone(timezone.utc):
        return {"status": "hosted_schedule_time_mismatch", "ok": False,
                "detail": "provider schedule differs from exact plan date/slot"}
    now = now.astimezone(timezone.utc)
    if now < when.astimezone(timezone.utc):
        return {"status": "scheduled_awaiting_public", "ok": True,
                "detail": f"YouTube owns scheduled publication at {when.isoformat()}",
                "provider_video_id": receipt["video_id"], "provider_url": receipt["post_url"]}
    return {"status": "hosted_schedule_due_requires_publication_receipt", "ok": False,
            "detail": "scheduled instant has arrived; obtain public-state proof before completion",
            "provider_video_id": receipt["video_id"], "provider_url": receipt["post_url"]}
