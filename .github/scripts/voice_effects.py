"""Hosted-only transport plumbing; no voice or review judgments live here.

The native owners remain byte-identical. A workflow run is the durable intent:
reruns and duplicate dispatches are reconciliation-only. Per-POST receipts and
successful responses survive in the generated-only checkpoint. Unknown effects
and 402 stop the entire process tree before native retry loops can repeat them.
"""
import builtins
import fcntl
import hashlib
import io
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

PUBLIC = "agmmltd-arch/agmm-render-public"
ORIGINAL_ENV = "/Users/samwall/alfred/.env"
_installed = False


def need(value, why):
    if not value:
        raise RuntimeError(why)


def host():
    need(sys.platform == "linux" and os.environ.get("GITHUB_ACTIONS") == "true"
         and os.environ.get("GITHUB_REPOSITORY") == PUBLIC
         and os.environ.get("RUNNER_OS") == "Linux", "hosted public Ubuntu only")


def atomic(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(path.name + ".tmp-" + str(os.getpid()))
    with temp.open("x") as stream:
        json.dump(value, stream, sort_keys=True)
        stream.flush()
        os.fsync(stream.fileno())
    os.replace(temp, path)


def install():
    global _installed
    if _installed:
        return
    host()
    root = Path(os.environ["AGMM_VOICE_EFFECTS"])
    need(root.is_absolute() and root.is_dir(), "effect directory missing")
    _installed = True
    original_open = builtins.open
    original_urlopen = urllib.request.urlopen
    original_run = subprocess.run
    original_unlink = Path.unlink
    stop_path = root / "STOP.json"

    def stopped():
        if stop_path.exists():
            raise SystemExit(75)
        for path in root.glob("[0-9][0-9][0-9][0-9].json"):
            try:
                status = json.loads(path.read_text())["status"]
            except Exception:
                raise SystemExit(75)
            if status in (
                    "EFFECT_UNKNOWN", "CAPACITY_402", "ACCEPTED_PROVIDER_STAGE_FAILED_RECONCILE"):
                raise SystemExit(75)

    def stop(status, operation=None):
        try:
            atomic(stop_path, {"status": status, "operation": operation,
                               "run_id": os.environ["GITHUB_RUN_ID"], "at": time.time()})
        finally:
            # Even a full disk cannot turn a hard stop into an Exception that
            # native ASR's except/parent retry loops can catch and repeat.
            raise SystemExit(75)

    def keys_open(file, mode="r", *args, **kwargs):
        # No credential file is created, copied or exported. Only the two
        # source-declared getters receive process-local runner secret bindings.
        if isinstance(file, (str, os.PathLike)) and str(file) in (
                ORIGINAL_ENV, str(Path.home() / "alfred/.env")):
            need(mode == "r", "native credential file write refused")
            values = {"MISTRAL_KEY": os.environ.get("AGMM_VOICE_MISTRAL_KEY", ""),
                      "GEMINI_KEY_B": os.environ.get("AGMM_VOICE_GEMINI_FREE_KEY", "")}
            return io.StringIO("\n".join(k + "=" + v for k, v in values.items()))
        return original_open(file, mode, *args, **kwargs)

    def guarded_urlopen(request, *args, **kwargs):
        stopped()
        need(isinstance(request, urllib.request.Request), "unbound voice network request")
        url = urllib.parse.urlsplit(request.full_url)
        mistral = url.hostname == "api.mistral.ai" and url.path in (
            "/v1/audio/speech", "/v1/audio/transcriptions")
        gemini = url.hostname == "generativelanguage.googleapis.com" and url.path.startswith(
            "/v1beta/models/") and url.path.endswith(":generateContent")
        need(url.scheme == "https" and not url.query and (mistral or gemini)
             and request.get_method() == "POST", "provider boundary refused")
        # Bind without storing request bodies, headers, reference audio or keys.
        request_hash = hashlib.sha256(request.data or b"").hexdigest()
        with original_open(root / "sequence.lock", "a+") as lock:
            fcntl.flock(lock, fcntl.LOCK_EX)
            stopped()
            sequence_path = root / "sequence.json"
            n = json.loads(sequence_path.read_text())["n"] + 1 if sequence_path.exists() else 1
            atomic(sequence_path, {"n": n})
            operation = "%04d" % n
            path = root / (operation + ".json")
            receipt = {"operation": operation, "run_id": os.environ["GITHUB_RUN_ID"],
                       "run_attempt": os.environ["GITHUB_RUN_ATTEMPT"],
                       "provider": "mistral" if mistral else "gemini-free",
                       "path": url.path, "request_sha256": request_hash,
                       "status": "EFFECT_UNKNOWN", "at": time.time()}
            atomic(path, receipt)  # fsync before handing bytes to the provider
        try:
            response = original_urlopen(request, *args, **kwargs)
            body = response.read()
            status = response.status
        except urllib.error.HTTPError as error:
            receipt["http_status"] = error.code
            # 429/4xx are explicit rejections. Only the owner's existing bounded
            # 429 backoff may continue. 5xx/transport failures are uncertain.
            receipt["status"] = ("CAPACITY_402" if error.code == 402 else
                                 "REJECTED" if 400 <= error.code < 500 else "EFFECT_UNKNOWN")
            atomic(path, receipt)
            if error.code == 402:
                stop("CAPACITY_402", operation)
            if receipt["status"] == "EFFECT_UNKNOWN":
                stop("EFFECT_UNKNOWN", operation)
            raise
        except Exception:
            stop("EFFECT_UNKNOWN", operation)
        if status != 200:
            stop("EFFECT_UNKNOWN", operation)
        try:
            # Contains intended generated speech or model response, never input.
            body_path = root / (operation + ".response")
            with original_open(body_path, "xb") as stream:
                stream.write(body)
                stream.flush()
                os.fsync(stream.fileno())
            receipt.update(status="ACCEPTED", http_status=status, response_bytes=len(body),
                           response_sha256=hashlib.sha256(body).hexdigest())
            atomic(path, receipt)
        except Exception:
            stop("EFFECT_UNKNOWN", operation)
        result = io.BytesIO(body)
        result.status = status
        result.headers = response.headers
        return result

    def guarded_run(*args, **kwargs):
        stopped()
        before = len(list(root.glob("*.response")))
        result = original_run(*args, **kwargs)
        stopped()  # propagate a child's hard stop past run_short's retry loop
        if result.returncode and len(list(root.glob("*.response"))) > before:
            stop("ACCEPTED_PROVIDER_STAGE_FAILED_RECONCILE")
        return result

    def preserve_unlink(path, *args, **kwargs):
        # Native run_short.clear_paragraph_takes replaces generated takes when
        # retrying below-bar work. Keep those bytes and receipts on the runner.
        piece = Path(os.environ["AGMM_VOICE_PIECE"])
        if path.parent == piece and path.name.startswith("P") and path.suffix in (
                ".wav", ".json") and path.exists():
            destination = piece / "superseded-hosted" / (str(time.time_ns()) + "-" + path.name)
            destination.parent.mkdir(exist_ok=True)
            shutil.move(str(path), destination)
            return
        return original_unlink(path, *args, **kwargs)

    builtins.open = keys_open
    io.open = keys_open  # Path.read_text/open use io.open, including env_key()
    urllib.request.urlopen = guarded_urlopen
    subprocess.run = guarded_run
    Path.unlink = preserve_unlink

