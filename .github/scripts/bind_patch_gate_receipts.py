#!/usr/bin/env python3
"""Bind hosted static/audio/decode and OCR gates to exact patched-master hashes."""
from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from typing import Any

import patch_master_segments as patcher


def write_receipt(content: dict[str, Any], output: Path) -> dict[str, Any]:
    receipt = dict(content)
    receipt["receipt_sha256"] = patcher.sha256_bytes(patcher.canonical_bytes(receipt))
    output.write_text(json.dumps(receipt, indent=2) + "\n")
    return receipt


def patch_receipt(args: argparse.Namespace) -> dict[str, Any]:
    request = patcher.load_request(args.request)
    provenance = patcher.load_download_provenance(args.download_provenance, request)
    integrity = json.loads(args.integrity.read_text())
    patch_provenance = json.loads(args.patch_provenance.read_text())
    audit = json.loads(args.audit.read_text())
    master_hash = patcher.sha256(args.master)
    review_hash = patcher.sha256(args.review)
    if integrity.get("patch_request_sha256") != request["request_sha256"]:
        raise ValueError("REMOTE-INTEGRITY is bound to a different patch request")
    if integrity.get("download_provenance_sha256") != provenance["provenance_sha256"]:
        raise ValueError("REMOTE-INTEGRITY is bound to different downloaded artifacts")
    patch_provenance_content = {key: value for key, value in patch_provenance.items()
                                if key != "provenance_sha256"}
    patch_provenance_hash = patcher.sha256_bytes(patcher.canonical_bytes(patch_provenance_content))
    if (patch_provenance.get("provenance_sha256") != patch_provenance_hash
            or patch_provenance.get("request_sha256") != request["request_sha256"]
            or patch_provenance.get("download_provenance_sha256") != provenance["provenance_sha256"]
            or integrity.get("patch_provenance_sha256") != patch_provenance_hash):
        raise ValueError("patch provenance receipt does not bind the request, downloads and integrity report")
    outputs = integrity.get("outputs", {})
    if outputs.get("master_sha256") != master_hash or outputs.get("derived_sha256") != review_hash:
        raise ValueError("REMOTE-INTEGRITY output hashes differ from the patched master files")
    required_checks = {
        "patch_request_format_and_uniqueness": "PASS",
        "exact_repository_and_source_runs": "PASS",
        "selected_artifact_archives_and_members": "PASS",
        "sealed_source_audio_hash_binding": "PASS",
        "all_hosted_segment_receipts": "PASS",
        "master_full_decode": "PASS",
        "derived_full_decode": "PASS",
        "source_audio_gain_and_aac_encode": "PASS",
        "encoded_audio_loudness_and_true_peak": "PASS",
    }
    checks = integrity.get("checks", {})
    for key, expected in required_checks.items():
        if checks.get(key) != expected:
            raise ValueError(f"REMOTE-INTEGRITY check {key} is not {expected}")
    expected_patch_ids = [row["i"] for row in request["patches"]]
    if checks.get("patched_segment_ids") != expected_patch_ids:
        raise ValueError("REMOTE-INTEGRITY patched segment set differs from the request")
    audit_checks_pass = (
        audit.get("technical_pass") is True
        and audit.get("full_decode_pass") is True
        and audit.get("profile_pass") is True
        and audit.get("duration_pass") is True
        and audit.get("static_detector", {}).get("pass") is True
        and audit.get("audio", {}).get("pass") is True
    )
    if (not audit_checks_pass or audit.get("video_sha256") != review_hash
            or str(audit.get("source_run_id")) != str(args.workflow_run_id)):
        raise ValueError("full-duration audit did not pass for this exact review master")
    if not re.fullmatch(r"[0-9a-f]{40}", args.workflow_commit):
        raise ValueError("workflow_commit must be a full lowercase Git commit SHA")
    return write_receipt({
        "schema": 1,
        "kind": "hosted_master_patch_gate_receipt",
        "workflow_run_id": patcher.validate_run_id(args.workflow_run_id, "workflow_run_id"),
        "workflow_commit": args.workflow_commit,
        "request_sha256": request["request_sha256"],
        "download_provenance_sha256": provenance["provenance_sha256"],
        "patch_provenance_sha256": patch_provenance_hash,
        "patch_provenance_file_sha256": patcher.sha256(args.patch_provenance),
        "remote_integrity_sha256": patcher.sha256(args.integrity),
        "full_duration_audit_sha256": patcher.sha256(args.audit),
        "master_sha256": master_hash,
        "review_master_sha256": review_hash,
        "patches": request["patches"],
        "checks": {
            "request_and_download_provenance": "PASS",
            "segment_receipts_and_replacement_scope": "PASS",
            "master_and_review_full_decode": "PASS",
            "profile_and_frame_count": "PASS",
            "audio_loudness_and_true_peak": "PASS",
            "full_duration_static_audit": "PASS",
            "native_vision_ocr": "PENDING_SEPARATE_HOSTED_JOB",
        },
        "editorial_gate": "NOT_RUN",
        "release_approval": "NOT_GRANTED",
    }, args.out)


def ocr_receipt(args: argparse.Namespace) -> dict[str, Any]:
    patch_gate = json.loads(args.patch_gate_receipt.read_text())
    recorded_hash = patch_gate.get("receipt_sha256")
    content = {key: value for key, value in patch_gate.items() if key != "receipt_sha256"}
    if recorded_hash != patcher.sha256_bytes(patcher.canonical_bytes(content)):
        raise ValueError("patch gate receipt self-hash mismatch")
    review_hash = patcher.sha256(args.review)
    if patch_gate.get("review_master_sha256") != review_hash:
        raise ValueError("OCR review master differs from the passed patch-gate master")
    check = json.loads(args.ocr_check.read_text())
    result = check.get("check", {})
    if result.get("status") != "PASS":
        raise ValueError("native Vision OCR check did not pass")
    if not isinstance(args.overlay_sha256, str) or not re.fullmatch(r"[0-9a-f]{64}", args.overlay_sha256):
        raise ValueError("overlay_sha256 must be 64 lowercase hexadecimal characters")
    return write_receipt({
        "schema": 1,
        "kind": "hosted_master_patch_ocr_receipt",
        "workflow_run_id": patcher.validate_run_id(args.workflow_run_id, "workflow_run_id"),
        "patch_gate_receipt_sha256": recorded_hash,
        "review_master_sha256": review_hash,
        "ocr_check_sha256": patcher.sha256(args.ocr_check),
        "qa_overlay_sha256": args.overlay_sha256,
        "native_vision_ocr": "PASS",
        "editorial_gate": "INCOMPLETE",
        "release_approval": "NOT_GRANTED",
    }, args.out)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    subparsers = parser.add_subparsers(dest="command", required=True)
    patch = subparsers.add_parser("patch")
    patch.add_argument("--request", required=True, type=Path)
    patch.add_argument("--download-provenance", required=True, type=Path)
    patch.add_argument("--integrity", required=True, type=Path)
    patch.add_argument("--patch-provenance", required=True, type=Path)
    patch.add_argument("--master", required=True, type=Path)
    patch.add_argument("--review", required=True, type=Path)
    patch.add_argument("--audit", required=True, type=Path)
    patch.add_argument("--workflow-run-id", required=True)
    patch.add_argument("--workflow-commit", required=True)
    patch.add_argument("--out", required=True, type=Path)
    ocr = subparsers.add_parser("ocr")
    ocr.add_argument("--patch-gate-receipt", required=True, type=Path)
    ocr.add_argument("--review", required=True, type=Path)
    ocr.add_argument("--ocr-check", required=True, type=Path)
    ocr.add_argument("--overlay-sha256", required=True)
    ocr.add_argument("--workflow-run-id", required=True)
    ocr.add_argument("--out", required=True, type=Path)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    receipt = patch_receipt(args) if args.command == "patch" else ocr_receipt(args)
    print(json.dumps({"status": "PASS", "kind": receipt["kind"],
                      "receipt_sha256": receipt["receipt_sha256"]}))


if __name__ == "__main__":
    main()
