#!/usr/bin/env python3
"""Probe for hosted-only Gemini Files audiovisual transport (part p11).

This module probes the Gemini Files API workflow for audiovisual grounding
using only hosted Linux runners in GitHub Actions, never processing media
locally or on Mac.

It downloads a public pilot video via the Gemini Files API, performs
blind audiovisual grounding with gemini-3.7-flash, and returns a minimal
JSON provenance result without any video/audio artifacts.
"""

from __future__ import annotations

import datetime
import hashlib
import json
import os
import platform
import sys
import time
import urllib.request
import urllib.error
from typing import TypedDict

# Constants from the problem statement
EXPECTED_SIZE = 38040764
EXPECTED_SHA256 = "0ed30928dcd77ba3fbc565e832a0e31064c11a2f308e3d0a863956cc07f3277e"
PILOT_URL = "https://agmm-content-share.pages.dev/media/P1-0ed30928dcd7?utm_source=qa&utm_campaign=qa_release_audit"
API = "https://generativelanguage.googleapis.com"
MODEL = "gemini-3.7-flash"

# Questions to ask the model (without ground truth)
QUESTIONS = [
    "first8spokenwords: What are the exact first 8 spoken words in the video?",
    "finalspokenCTA: What is the final spoken CTA (call to action) in the video?",
    "visiblelogos+timestamps: What are the visible logos and their corresponding timestamps?",
    "musiccharacter: Describe the music character (style, mood, instrumentation).",
    "duration: What is the duration of the video?",
    "inability: Identify any inability to analyze specific video/audio features."
]


class ProbeResult(TypedDict):
    """Minimal JSON result from the probe."""
    actualmodelVersion: str
    usage: dict
    sourcehash: str
    input_provenance: dict
    NOT_RELEASE_APPROVAL: bool
    release_approval: str
    candidates_text: str
    file_provenance: dict
    limitations: str


class ProviderHTTPError(RuntimeError):
    def __init__(self, status):
        self.status = status
        super().__init__(f"Provider HTTP {status}")


class UploadRefused(RuntimeError):
    """An upload this module will not attempt."""


def _guard_environment() -> None:
    """Refuse if not running on Linux in GitHub Actions."""
    if not (platform.system() == "Linux" and os.getenv("GITHUB_ACTIONS") == "true"):
        raise UploadRefused(
            f"Hosted Linux runner required: system={platform.system()}, "
            f"GITHUB_ACTIONS={os.getenv('GITHUB_ACTIONS')}"
        )


def _http(method: str, url: str, headers: dict, data: bytes = b"", timeout: int = 120, max_bytes: int | None = None) -> tuple:
    """Make an HTTP request and return (status, headers, body)."""
    _guard_environment()
    
    req = urllib.request.Request(url, method=method, data=data, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as response:
            content_length_str = response.headers.get("Content-Length")
            if content_length_str and max_bytes is not None:
                try:
                    cl = int(content_length_str)
                    if cl > max_bytes:
                        raise UploadRefused(f"Response Content-Length {cl} exceeds maximum allowed size of {max_bytes}")
                except ValueError:
                    pass
                    
            body = b""
            bytes_read = 0
            chunk_size = 65536
            while True:
                chunk = response.read(chunk_size)
                if not chunk:
                    break
                bytes_read += len(chunk)
                if max_bytes is not None and bytes_read > max_bytes:
                    raise UploadRefused(f"Response body exceeded maximum allowed size of {max_bytes}")
                body += chunk
                
            return (
                response.status,
                {k.lower(): v for k, v in response.headers.items()},
                body,
            )
    except urllib.error.HTTPError as e:
        raise ProviderHTTPError(e.code) from None
    except Exception as e:
        err_msg = str(e)
        key_val = headers.get("x-goog-api-key")
        if key_val and key_val in err_msg:
            err_msg = err_msg.replace(key_val, "[REDACTED]")
        raise RuntimeError(f"HTTP request failed: {err_msg}") from None


def _guard_key_name(key_name: str) -> None:
    """Validate that the key name is approved for hosted uploads."""
    approved_keys = (
        "OLD_ACCOUNT",
        "GEMINI_KEY_B",
        "GEMINI_API_KEY_OLD_ACCOUNT", 
        "GEMINI_UPLOAD_KEY"
    )
    forbidden_keys = ("GEMINI_API_KEY",)
    
    if key_name in forbidden_keys:
        raise UploadRefused(f"prepay key {key_name} is refused for hosted uploads")
    if key_name not in approved_keys:
        raise UploadRefused(f"unapproved upload key name {key_name!r}")


def is_expired(expiration_str: str) -> bool:
    """Parse ISO 8601 string and check if the current time is past expiration."""
    if not expiration_str:
        return True
    try:
        clean_str = expiration_str.replace('Z', '+00:00')
        exp_dt = datetime.datetime.fromisoformat(clean_str)
        now_dt = datetime.datetime.now(datetime.timezone.utc)
        return now_dt >= exp_dt
    except Exception:
        return True


def _download_and_validate_pilot() -> bytes:
    """Download the pilot video and validate its size and hash."""
    _guard_environment()
    
    headers = {"User-Agent": "Mozilla/5.0 AGMM-Probe/1.0"}
    max_bytes = 100 * 1024 * 1024  # Enforce maximum 100MB download
    
    status, _, body = _http("GET", PILOT_URL, headers, timeout=60, max_bytes=max_bytes)
    
    if status != 200:
        raise UploadRefused(f"Failed to download pilot: HTTP {status}")
    
    # Validate size
    if len(body) != EXPECTED_SIZE:
        raise UploadRefused(
            f"Size mismatch: expected {EXPECTED_SIZE}, got {len(body)}"
        )
    
    # Validate SHA-256
    actual_hash = hashlib.sha256(body).hexdigest()
    if actual_hash != EXPECTED_SHA256:
        raise UploadRefused(
            f"Hash mismatch: expected {EXPECTED_SHA256}, got {actual_hash}"
        )
    
    return body


def _upload_to_gemini_files(data: bytes, key_name: str, key_value: str) -> dict:
    """Upload bytes to Gemini Files API using resumable upload."""
    _guard_environment()
    _guard_key_name(key_name)
    
    if isinstance(data, str) and data.startswith("/"):
        raise UploadRefused("local media path is refused")
    if not isinstance(data, (bytes, bytearray)):
        raise UploadRefused("data must be bytes")
    
    size = len(data)
    start_headers = {
        "x-goog-api-key": key_value,
        "X-Goog-Upload-Protocol": "resumable",
        "X-Goog-Upload-Command": "start",
        "X-Goog-Upload-Header-Content-Length": str(size),
        "X-Goog-Upload-Header-Content-Type": "video/mp4",
        "Content-Type": "application/json",
    }
    start_body = json.dumps({"file": {"display_name": "pilot.mp4"}}).encode()
    
    _, headers, _ = _http(
        "POST", 
        f"{API}/upload/v1beta/files",
        start_headers,
        start_body,
        timeout=120
    )
    
    upload_url = headers.get("x-goog-upload-url")
    if not upload_url:
        raise UploadRefused("Files API returned no resumable upload URL")
    
    upload_headers = {
        "Content-Length": str(size),
        "X-Goog-Upload-Offset": "0",
        "X-Goog-Upload-Command": "upload, finalize",
    }
    
    _, _, response_body = _http(
        "POST",
        upload_url,
        upload_headers,
        data,
        timeout=900  # 15 minutes for large file upload
    )
    
    upload_result = json.loads(response_body or b"{}")
    file_info = upload_result.get("file", {})
    
    if not file_info:
        raise UploadRefused("Files API upload failed: no file info returned")
        
    return {
        "source": "hosted-file-api",
        "sha256": hashlib.sha256(data).hexdigest(),
        "size": len(data),
        "content_type": "video/mp4",
        "display_name": "pilot.mp4",
        "uri": file_info.get("uri"),
        "name": file_info.get("name"),
        "state": file_info.get("state"),
        "expires_at_str": file_info.get("expirationTime", "unknown"),
        "key_name": key_name,
    }


def _poll_file_active(name: str, key_value: str) -> dict:
    """Poll Files API until the file is ACTIVE, bounded."""
    _guard_environment()
    poll_count = 0
    max_polls = 12  # Bounded, e.g. 12 attempts
    poll_interval = 10  # 10 seconds between polls, total 2 minutes maximum
    
    while poll_count < max_polls:
        if poll_count > 0:
            print(f"Waiting {poll_interval} seconds before next poll...", file=sys.stderr)
            time.sleep(poll_interval)
            
        poll_count += 1
        url = f"{API}/v1beta/{name}"
        headers = {"x-goog-api-key": key_value}
        
        print(f"Polling file status (attempt {poll_count}/{max_polls}) for resource {name}...", file=sys.stderr)
        status, _, body = _http("GET", url, headers, timeout=30)
        if status != 200:
            raise UploadRefused(f"Failed to poll file metadata: HTTP {status}")
            
        file_meta = json.loads(body)
        if "file" in file_meta:
            file_info = file_meta["file"]
        else:
            file_info = file_meta
            
        state = file_info.get("state")
        if not state:
            raise UploadRefused("File metadata response is missing 'state'")
            
        print(f"File state: {state}", file=sys.stderr)
        
        if state == "ACTIVE":
            expiration_str = file_info.get("expirationTime")
            if not expiration_str:
                raise UploadRefused("File metadata response is missing 'expirationTime'")
            if is_expired(expiration_str):
                raise UploadRefused(f"File is expired (expirationTime: {expiration_str})")
            return file_info
            
        if state == "FAILED":
            raise UploadRefused("File processing failed on Files API side")
            
        if state != "PROCESSING":
            raise UploadRefused(f"Unexpected file state: {state}")
            
    raise UploadRefused(f"File polling timed out: state remained PROCESSING after {max_polls} polls")


def _generate_content_blind(
    uri: str, 
    key_name: str, 
    key_value: str
) -> dict:
    """Perform blind audiovisual grounding with Gemini."""
    _guard_environment()
    
    prompt_parts = [
        "Analyze this video and provide:",
        *QUESTIONS,
        "Do not provide any ground truth or feedback on accuracy."
    ]
    prompt = "\n".join(prompt_parts)
    
    request_data = {
        "contents": [{
            "parts": [
                {"text": prompt},
                {
                    "file_data": {
                        "mime_type": "video/mp4",
                        "file_uri": uri
                    }
                }
            ]
        }],
        "generationConfig": {
            "temperature": 0.1,
            "topK": 16,
            "topP": 0.8,
            "maxOutputTokens": 512,
        }
    }
    
    headers = {
        "x-goog-api-key": key_value,
        "Content-Type": "application/json",
    }
    
    for attempt in range(3):
        try:
            status, _, response_body = _http(
                "POST", f"{API}/v1beta/models/{MODEL}:generateContent",
                headers, json.dumps(request_data).encode(), timeout=60
            )
            break
        except ProviderHTTPError as error:
            if error.status not in (500, 502, 503, 504) or attempt == 2:
                raise
            time.sleep(15 * (attempt + 1))
    
    if status != 200:
        raise UploadRefused(f"generateContent failed: HTTP {status}")
    
    return json.loads(response_body)


def _delete_file(name: str, key_value: str) -> bool:
    """Delete file from Files API. Returns True on success, False on error."""
    _guard_environment()
    try:
        status, _, _ = _http(
            "DELETE",
            f"{API}/v1beta/{name}",
            {"x-goog-api-key": key_value},
            timeout=30
        )
        return status in (200, 204)
    except Exception as e:
        err_msg = str(e)
        if key_value in err_msg:
            err_msg = err_msg.replace(key_value, "[REDACTED]")
        print(f"File deletion failed: {err_msg}", file=sys.stderr)
        return False


def main() -> int:
    """Main probe function."""
    try:
        _guard_environment()
    except UploadRefused as e:
        print(f"Upload refused: {e}", file=sys.stderr)
        return 1
        
    key_name = "OLD_ACCOUNT"
    key_value = os.getenv("AGMM_GEMINI_FREE_REVIEW_KEY")
    if not key_value:
        print("Error: AGMM_GEMINI_FREE_REVIEW_KEY environment variable not set", file=sys.stderr)
        return 1
        
    file_name = None
    expiration_str = "unknown"
    inference_error = None
    result = None
    
    try:
        print("Downloading and validating pilot video...", file=sys.stderr)
        video_data = _download_and_validate_pilot()
        print(f"Successfully downloaded {len(video_data)} bytes", file=sys.stderr)
        
        print("Uploading to Gemini Files API...", file=sys.stderr)
        provenance = _upload_to_gemini_files(video_data, key_name, key_value)
        file_name = provenance.get("name")
        expiration_str = provenance.get("expires_at_str", "unknown")
        print(f"Upload complete, resource: {file_name}", file=sys.stderr)
        
        if not file_name or not provenance.get("uri"):
            raise UploadRefused("Files API response missing resource name or URI")
        file_meta = _poll_file_active(file_name, key_value)
        expiration_str = file_meta.get("expirationTime", expiration_str)
        
        print("Performing blind audiovisual grounding...", file=sys.stderr)
        generation_result = _generate_content_blind(
            provenance["uri"],
            key_name,
            key_value
        )
        
        candidates = generation_result.get("candidates", [])
        candidates_text = ""
        if candidates and isinstance(candidates, list):
            first_cand = candidates[0]
            content = first_cand.get("content", {})
            parts = content.get("parts", [])
            if parts and isinstance(parts, list):
                candidates_text = parts[0].get("text", "")
                
        if not candidates_text.strip() or not generation_result.get("modelVersion"):
            raise UploadRefused("Inference returned no observations or observed modelVersion")
        result: ProbeResult = {
            "actualmodelVersion": generation_result["modelVersion"],
            "usage": generation_result.get("usageMetadata", {}),
            "sourcehash": provenance["sha256"],
            "input_provenance": {
                "sha256": provenance["sha256"],
                "size": provenance["size"],
                "uri": provenance["uri"],
                "key_name": key_name
            },
            "NOT_RELEASE_APPROVAL": True,
            "release_approval": "NOT_GRANTED",
            "candidates_text": candidates_text,
            "file_provenance": {
                "name": file_name,
                "uri": provenance["uri"],
                "state": file_meta.get("state"),
                "expiration": expiration_str
            },
            "limitations": "blind audiovisual grounding lacks absolute local groundtruth comparison"
        }
        
    except Exception as e:
        inference_error = e
        clean_msg = str(e)
        if key_value in clean_msg:
            clean_msg = clean_msg.replace(key_value, "[REDACTED]")
        print(f"Error during execution: {clean_msg}", file=sys.stderr)
        
    finally:
        deletion_success = True
        if file_name:
            print(f"Cleaning up File API resource {file_name}...", file=sys.stderr)
            deletion_success = _delete_file(file_name, key_value)
            if not deletion_success:
                print(f"File deletion failed for resource: {file_name}. Original expiration time was {expiration_str}.", file=sys.stderr)
                
        if inference_error:
            print(json.dumps({"release_approval": "NOT_GRANTED", "NOT_RELEASE_APPROVAL": True,
                              "error_type": type(inference_error).__name__, "error": clean_msg,
                              "cleanup": {"file_name": file_name, "deleted": deletion_success,
                                          "expiration": expiration_str}}))
            return 1
            
        if result:
            result["cleanup"] = {"deleted": deletion_success, "expiration": expiration_str}
            print(json.dumps(result, separators=(',', ':')))
            return 0
            
        return 1


if __name__ == "__main__":
    sys.exit(main())
