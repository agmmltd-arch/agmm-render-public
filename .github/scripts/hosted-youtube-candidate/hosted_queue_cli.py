#!/usr/bin/env python3
"""Create a text queue-row artifact from exact pins and a real Studio receipt."""
import argparse
import json
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from queue_contract import earliest_slot, make_queue_row, sha256_bytes


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--approval", type=Path, required=True)
    p.add_argument("--receipt", type=Path)
    p.add_argument("--existing-rows", type=Path, required=True)
    p.add_argument("--source-run-id", required=True)
    p.add_argument("--artifact-name", required=True)
    p.add_argument("--video-name", required=True)
    p.add_argument("--master-sha256", required=True)
    p.add_argument("--metadata-sha256", required=True)
    p.add_argument("--caption-sha256", required=True)
    p.add_argument("--thumbnail-sha256", required=True)
    p.add_argument("--date", required=True)
    p.add_argument("--candidate-slots", required=True, help="JSON array of allowed London slot labels")
    p.add_argument("--selected-slot", help="Previously selected slot; required for receipt reconciliation")
    p.add_argument("--post-id", required=True)
    p.add_argument("--out", type=Path, required=True)
    args = p.parse_args()
    approval_bytes = args.approval.read_bytes()
    approval = json.loads(approval_bytes)
    rows = json.loads(args.existing_rows.read_text())
    if not isinstance(rows, list):
        raise SystemExit("existing rows must be a JSON array")
    receipt_bytes = args.receipt.read_bytes() if args.receipt else None
    receipt = json.loads(receipt_bytes) if receipt_bytes else None
    candidates = json.loads(args.candidate_slots)
    if receipt is not None:
        if not args.selected_slot or args.selected_slot not in candidates:
            raise SystemExit("receipt reconciliation requires the originally selected slot")
        slot = args.selected_slot
    else:
        if args.selected_slot:
            raise SystemExit("selected slot is only valid for receipt reconciliation")
        slot = earliest_slot(args.date, candidates, rows,
                             datetime.now(ZoneInfo("Europe/London")))
    result = make_queue_row(
        approval=approval, provider_receipt=receipt,
        source_run_id=args.source_run_id, artifact_name=args.artifact_name,
        video_name=args.video_name, master_sha256=args.master_sha256,
        approval_sha256=sha256_bytes(approval_bytes), metadata_sha256=args.metadata_sha256,
        caption_sha256=args.caption_sha256,
        thumbnail_sha256=args.thumbnail_sha256, day=args.date, slot=slot, post_id=args.post_id,
        existing_rows=rows,
    )
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n")
    print(json.dumps({"status": result["status"], "post_id": result["post_id"],
                      "slot": result["slot"], "provider_video_id": result.get("provider_video_id")}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
