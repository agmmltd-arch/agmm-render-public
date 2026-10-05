#!/usr/bin/env python3
"""Run HyperFrames check on Ubuntu and always persist bounded, sanitized diagnostics."""
from __future__ import annotations
import argparse, json, os, re, subprocess
from pathlib import Path

MAX_TEXT = 16_000
MAX_JSON = 100_000
CONTROL = re.compile(r"[^\x09\x0a\x0d\x20-\x7e]")

def sanitize(data: bytes, roots: tuple[str, ...]) -> str:
    text = data.decode("utf-8", "replace")
    for root in roots:
        if root:
            text = text.replace(root, "<runner-path>")
    text = re.sub(r"/(?:home|private)/runner/[^\s\'\"]+", "<runner-path>", text)
    text = CONTROL.sub("�", text)
    if len(text) > MAX_TEXT:
        text = text[:MAX_TEXT] + "\n[truncated at 16000 characters]\n"
    return text

def sanitize_json(value, roots: tuple[str, ...]):
    if isinstance(value, str):
        return sanitize(value.encode("utf-8", "replace"), roots)
    if isinstance(value, list):
        return [sanitize_json(item, roots) for item in value]
    if isinstance(value, dict):
        return {sanitize(str(key).encode("utf-8", "replace"), roots): sanitize_json(item, roots)
                for key, item in value.items()}
    return value

def run(command: list[str], *, cwd: Path, env: dict[str, str], json_path: Path, text_path: Path, require_json: bool = True) -> int:
    try:
        proc = subprocess.run(command, cwd=cwd, env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                              timeout=360, check=False)
        returncode, raw_out, raw_err = proc.returncode, proc.stdout or b"", proc.stderr or b""
        timed_out = False
    except subprocess.TimeoutExpired as exc:
        returncode, raw_out, raw_err = 124, exc.stdout or b"", exc.stderr or b""
        timed_out = True
    except OSError as exc:
        returncode, raw_out, raw_err = 127, b"", str(exc).encode("utf-8", "replace")
        timed_out = False
    roots = (env.get("GITHUB_WORKSPACE", ""), env.get("RUNNER_TEMP", ""), str(cwd))
    stdout = sanitize(raw_out if isinstance(raw_out,bytes) else str(raw_out).encode(), roots)
    stderr = sanitize(raw_err if isinstance(raw_err,bytes) else str(raw_err).encode(), roots)
    try:
        raw_payload = raw_out if isinstance(raw_out, bytes) else str(raw_out).encode("utf-8", "replace")
        if len(raw_payload) > MAX_JSON:
            raise json.JSONDecodeError("check JSON exceeds byte cap", "", 0)
        parsed = sanitize_json(json.loads(raw_payload.decode("utf-8")), roots)
        encoded = json.dumps(parsed, indent=2, sort_keys=True) + "\n"
        if len(encoded.encode("utf-8")) <= MAX_JSON:
            json_path.write_text(encoded, encoding="utf-8")
            result_file = json_path.name
        else:
            result_file = None
    except (json.JSONDecodeError, UnicodeDecodeError):
        result_file = None
    if require_json and returncode == 0 and result_file is None:
        returncode = 1
    diagnostic = {
        "schema": "agmm-s83-hyperframes-check-diagnostic-v1",
        "exit_code": returncode,
        "timed_out": timed_out,
        "status": "PASS" if returncode == 0 else "FAILED",
        "json_report_written": result_file is not None,
        "json_report_file": result_file,
        "stdout": stdout,
        "stderr": stderr,
        "approval": "NOT_GRANTED",
    }
    text_path.write_text(json.dumps(diagnostic, indent=2) + "\n", encoding="utf-8")
    return returncode

def main() -> int:
    p=argparse.ArgumentParser()
    p.add_argument("--candidate", required=True, type=Path)
    p.add_argument("--snapshot", action="store_true")
    p.add_argument("--at")
    p.add_argument("--no-end", action="store_true")
    p.add_argument("--describe")
    p.add_argument("--no-browser-gpu", action="store_true")
    p.add_argument("--timeout")
    p.add_argument("--output")
    p.add_argument("--json-output", required=True, type=Path)
    p.add_argument("--diagnostic-output", required=True, type=Path)
    a=p.parse_args()
    if os.environ.get("GITHUB_ACTIONS") != "true" or os.environ.get("RUNNER_OS") != "Linux" or os.environ.get("RUNNER_ENVIRONMENT") != "github-hosted":
        raise SystemExit("refusing HyperFrames browser check outside GitHub-hosted Linux")
    command=["npx", "--yes", "hyperframes@0.8.71", "snapshot" if a.snapshot else "check", str(a.candidate)]
    if a.snapshot:
        if not all((a.at, a.describe, a.timeout, a.output)):
            raise SystemExit("snapshot requires --at, --describe, --timeout and --output")
        command += ["--at",a.at]
        if a.no_end: command.append("--no-end")
        command += ["--describe",a.describe]
        if a.no_browser_gpu: command.append("--no-browser-gpu")
        command += ["--timeout",a.timeout,"--output",a.output]
    else:
        command.append("--json")
    return run(command, cwd=Path.cwd(), env=os.environ.copy(), json_path=a.json_output, text_path=a.diagnostic_output, require_json=not a.snapshot)
if __name__ == "__main__":
    raise SystemExit(main())
