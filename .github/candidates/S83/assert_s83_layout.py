#!/usr/bin/env python3
"""Fail closed when the hosted S83 HyperFrames report has text-layout errors."""
from __future__ import annotations

import json
import sys
from pathlib import Path


def validate(report: dict) -> None:
    layout = report.get("layout")
    if not isinstance(layout, dict):
        raise ValueError("HyperFrames report has no layout section")
    errors = layout.get("errorCount")
    findings = layout.get("findings")
    if not isinstance(errors, int) or not isinstance(findings, list):
        raise ValueError("HyperFrames layout report is incomplete")
    error_findings = [item for item in findings
                      if isinstance(item, dict) and item.get("severity") == "error"]
    if errors != 0 or error_findings or layout.get("ok") is not True:
        pairs = [f"{item.get('selector')} overlaps {item.get('containerSelector')}"
                 for item in error_findings]
        raise ValueError(f"S83 layout must have zero errors; errorCount={errors}; {pairs}")

    runtime = report.get("runtime")
    if not isinstance(runtime, dict) or not isinstance(runtime.get("findings"), list):
        raise ValueError("HyperFrames report has no runtime findings list")
    missing_targets = [item.get("message", "") for item in runtime["findings"]
                       if isinstance(item, dict)
                       and item.get("code") == "console_warning"
                       and "GSAP target" in item.get("message", "")
                       and "not found" in item.get("message", "")]
    if missing_targets:
        raise ValueError(f"S83 GSAP targets must resolve in the composition: {missing_targets}")


def main() -> int:
    if len(sys.argv) != 2:
        raise SystemExit("usage: assert_s83_layout.py HYPERFRAMES-CHECK.json")
    report = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
    validate(report)
    print("S83 layout regression gate: PASS (zero layout errors; all GSAP targets resolved)")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (OSError, json.JSONDecodeError, ValueError) as exc:
        print(f"S83 layout regression gate: FAIL: {exc}", file=sys.stderr)
        raise SystemExit(1)
