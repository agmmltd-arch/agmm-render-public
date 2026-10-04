"""One-shot preflight for the exact retained F07 matrix run (text metadata only)."""
from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import re
import subprocess
from pathlib import Path
from typing import Any, Callable

REPOSITORY = "agmmltd-arch/agmm-render-public"
PARENT_RUN_ID = 37183236257
PARENT_HEAD_SHA = "11b7c8d03c33a180620a653164a99efd037e409b"
RENDER_COUNT = 73


class ReuseRefused(RuntimeError):
    pass


def _command(runner: Callable[..., Any], argv: list[str]) -> dict[str, Any]:
    result = runner(argv, capture_output=True, text=True, timeout=20, check=True)
    try:
        value = json.loads(result.stdout)
    except (TypeError, json.JSONDecodeError) as exc:
        raise ReuseRefused("GitHub returned invalid reuse metadata") from exc
    if not isinstance(value, dict):
        raise ReuseRefused("GitHub reuse metadata has the wrong shape")
    return value


def _verify_release_asset(runner: Callable[..., Any], *, release_tag: str,
                          release_id: int, asset: dict[str, Any]) -> None:
    release = _command(
        runner,
        ["gh", "api", f"repos/{REPOSITORY}/releases/tags/{release_tag}"],
    )
    if release.get("id") != release_id or release.get("tag_name") != release_tag:
        raise ReuseRefused("source or overlay release identity differs from the reviewed lock")
    assets = release.get("assets")
    if not isinstance(assets, list):
        raise ReuseRefused("source or overlay release asset list is unavailable")
    matches = [item for item in assets if isinstance(item, dict) and
               item.get("id") == asset.get("id")]
    if len(matches) != 1:
        raise ReuseRefused("locked source or overlay asset is not a unique member of its release")
    found = matches[0]
    if (found.get("name") != asset.get("name") or
        found.get("size") != asset.get("size_bytes") or
        found.get("digest") != "sha256:" + str(asset.get("sha256"))):
        raise ReuseRefused("source or overlay asset metadata differs from the reviewed lock")


def verify_reuse(run_id: str, repository: str, *, lock_path: Path,
                 package_sha256: str, overlay_sha256: str, source_release: str,
                 overlay_release: str, tag: str, fid: str, segments_json: str,
                 apply_source_overlay: str, runner: Callable[..., Any] = subprocess.run,
                 now: dt.datetime | None = None) -> dict[str, Any]:
    if repository != REPOSITORY or run_id != str(PARENT_RUN_ID):
        raise ReuseRefused("only the reviewed F07 parent run may be reused")
    try:
        lock = json.loads(Path(lock_path).read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ReuseRefused("retained artifact lock is unavailable or invalid") from exc
    if (lock.get("schema") != "f07-retained-segment-artifact-lock-v1" or
        lock.get("repository") != REPOSITORY or lock.get("parent_run_id") != PARENT_RUN_ID or
        lock.get("parent_head_sha") != PARENT_HEAD_SHA):
        raise ReuseRefused("retained artifact lock identity mismatch")
    if (package_sha256 != lock.get("source_sha256") or
        overlay_sha256 != lock.get("overlay_sha256") or
        source_release != lock.get("source_release") or overlay_release != lock.get("overlay_release") or
        tag != lock.get("tag") or fid != lock.get("fid") or apply_source_overlay != "false" or
        hashlib.sha256(segments_json.encode("utf-8")).hexdigest() != lock.get("segments_json_sha256")):
        raise ReuseRefused("dispatch inputs do not match the retained source, overlay, FID, tag, and segment plan")

    _verify_release_asset(runner, release_tag=source_release,
                          release_id=lock.get("source_release_id"),
                          asset=lock.get("source_asset", {}))
    _verify_release_asset(runner, release_tag=overlay_release,
                          release_id=lock.get("overlay_release_id"),
                          asset=lock.get("overlay_asset", {}))

    run = _command(runner, ["gh", "run", "view", run_id, "--repo", REPOSITORY,
                            "--json", "name,workflowName,headSha,status,conclusion,event,jobs"])
    if (run.get("name") != lock.get("parent_run_name") or
        run.get("workflowName") != lock.get("parent_workflow_name") or
        run.get("headSha") != PARENT_HEAD_SHA or run.get("status") != "completed" or
        run.get("conclusion") != "failure" or run.get("event") != "workflow_dispatch"):
        raise ReuseRefused("parent run identity or terminal state differs from the reviewed receipt")
    jobs = run.get("jobs")
    if not isinstance(jobs, list):
        raise ReuseRefused("parent job list is unavailable")
    renders: dict[str, str | None] = {}
    for job in jobs:
        if not isinstance(job, dict):
            raise ReuseRefused("parent job entry has the wrong shape")
        match = re.fullmatch(r"render \((\d{2}),.*\)", job.get("name", ""))
        if match:
            key = match.group(1)
            if key in renders:
                raise ReuseRefused("duplicate parent render job")
            renders[key] = job.get("conclusion")
    expected_ids = {f"{i:02d}" for i in range(1, RENDER_COUNT + 1)}
    if set(renders) != expected_ids or any(state != "success" for state in renders.values()):
        raise ReuseRefused("parent does not contain exactly 73 successful render jobs")
    assemble = [j for j in jobs if j.get("name") == "assemble"]
    if len(assemble) != 1 or assemble[0].get("conclusion") != "failure":
        raise ReuseRefused("parent failure is not isolated to the expected assembly job")
    if any(j.get("conclusion") == "failure" and j.get("name") != "assemble" for j in jobs):
        raise ReuseRefused("parent has an unrelated failed job")

    artifacts_doc = _command(runner, ["gh", "api", f"repos/{REPOSITORY}/actions/runs/{run_id}/artifacts?per_page=100"])
    actual_list = artifacts_doc.get("artifacts")
    expected_list = lock.get("segments")
    if not isinstance(actual_list, list) or not isinstance(expected_list, list) or len(expected_list) != RENDER_COUNT:
        raise ReuseRefused("artifact metadata list is invalid")
    actual = {str(a.get("id")): a for a in actual_list if isinstance(a, dict)}
    if len(actual_list) != RENDER_COUNT or len(actual) != RENDER_COUNT:
        raise ReuseRefused("parent artifact set is not exactly 73 unique artifacts")
    if len({str(a.get("id")) for a in expected_list if isinstance(a, dict)}) != RENDER_COUNT:
        raise ReuseRefused("lock does not contain 73 unique artifact IDs")
    current_time = now or dt.datetime.now(dt.timezone.utc)
    expected_names = {f"F07-full-63243-9bb0efdd-20261004-SEG{i:02d}" for i in range(1, RENDER_COUNT + 1)}
    if {a.get("name") for a in expected_list} != expected_names:
        raise ReuseRefused("lock artifact names do not match the exact 73-part plan")
    for item in expected_list:
        if not isinstance(item, dict):
            raise ReuseRefused("lock contains an invalid artifact row")
        row = actual.get(str(item.get("id")))
        if row is None:
            raise ReuseRefused("locked artifact ID is missing")
        try:
            expiry = dt.datetime.fromisoformat(str(item["expires_at"]).replace("Z", "+00:00"))
        except (KeyError, ValueError) as exc:
            raise ReuseRefused("locked artifact expiry is invalid") from exc
        if (row.get("name") != item.get("name") or row.get("size_in_bytes") != item.get("size_bytes") or
            row.get("digest") != "sha256:" + str(item.get("sha256")) or row.get("expired") is not False or
            row.get("expires_at") != item.get("expires_at") or expiry <= current_time):
            raise ReuseRefused("locked artifact metadata differs or has expired")
    return {"run_id": PARENT_RUN_ID, "render_jobs": len(renders), "artifact_count": len(actual),
            "earliest_expiry": min(x["expires_at"] for x in expected_list),
            "source_sha256": lock["source_sha256"], "status": "PASS"}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--repo", required=True)
    parser.add_argument("--package-sha256", required=True)
    parser.add_argument("--overlay-sha256", required=True)
    parser.add_argument("--source-release", required=True)
    parser.add_argument("--overlay-release", required=True)
    parser.add_argument("--tag", required=True)
    parser.add_argument("--fid", required=True)
    parser.add_argument("--segments-json", required=True)
    parser.add_argument("--apply-source-overlay", required=True)
    parser.add_argument("--lock", type=Path, default=Path("retained-segment-artifact-lock.json"))
    args = parser.parse_args()
    result = verify_reuse(args.run_id, args.repo, lock_path=args.lock,
                          package_sha256=args.package_sha256, overlay_sha256=args.overlay_sha256,
                          source_release=args.source_release, overlay_release=args.overlay_release,
                          tag=args.tag, fid=args.fid, segments_json=args.segments_json,
                          apply_source_overlay=args.apply_source_overlay)
    print("F07_RETAINED_73_ARTIFACT_LOCK_PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
