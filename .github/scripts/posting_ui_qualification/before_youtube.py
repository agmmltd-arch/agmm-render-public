#!/usr/bin/env python3
"""Publish one 30-ways film as a YouTube Short.

The wizard walk is the proven one from ``adapters/youtube_publish.py`` and is
imported from it rather than re-implemented, so a fix there is not silently
lost here. What differs is only the package contract: a sealed video.mp4 and a
bundle caption instead of a carousel package's youtube-short.mp4 and sealed
licensed-audio manifest.

Nothing is a publication until Studio itself reports PUBLIC **and** the
logged-out oEmbed endpoint returns the AGMM author and the exact title. A
returned /shorts/ URL is not proof: Studio has surfaced one for a video that
stayed a DRAFT.
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "adapters"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from playwright.sync_api import sync_playwright  # noqa: E402

import video_package as vp  # noqa: E402
import video_receipts as vr  # noqa: E402
import video_platform_review  # noqa: E402
from browser_profiles import (  # noqa: E402
    YOUTUBE_PROFILE,
    profile_lock,
    publisher_browser_mode,
    publisher_headless_user_agent,
)

_spec = importlib.util.spec_from_file_location(
    "youtube_publish_module", ROOT / "adapters" / "youtube_publish.py"
)
yt = importlib.util.module_from_spec(_spec)
assert _spec.loader is not None
_spec.loader.exec_module(yt)

CHANNEL_ID = "UChbp0G1KDjCnruAhxfmzEXg"


def log(message: str) -> None:
    print(f"[{time.strftime('%H:%M:%S')}] [yt-video] {message}", flush=True)


def copy_for(package: Path) -> tuple[str, str]:
    """Title and description, both from the bundle. Never invented."""
    meta = json.loads((package / "package.json").read_text(encoding="utf-8"))
    if "youtube" not in meta.get("captions", {}):
        raise RuntimeError(
            "HELD_AWAITING_BUNDLE: no YouTube caption in "
            f"{meta.get('bundle_path')}"
        )
    body = (package / meta["captions"]["youtube"]["file"]).read_text(encoding="utf-8").strip()
    # The staged package carries the title (arm_slot copies it). Reading the
    # bundle under ~/Documents from launchd raises PermissionError (TCC), so it
    # is only a fallback for packages armed before 2026-09-07 12:20.
    title = str(((meta.get("titles") or {}).get("youtube", ""))).strip()
    if not title:
        try:
            bundle, _ = vp.read_bundle(meta["film"])
        except PermissionError:
            bundle = None
        title = str(((bundle or {}).get("titles") or {}).get("youtube", "")).strip()
    if not title:
        # A bundle that ships a caption but no explicit title is incomplete;
        # deriving one from the body is inventing copy, so refuse instead.
        raise RuntimeError(
            "HELD_AWAITING_BUNDLE: bundle carries a YouTube caption but no "
            "titles.youtube; refusing to invent a title"
        )
    if vp.looks_like_serialised_data(body) or vp.looks_like_serialised_data(title):
        raise RuntimeError("HELD_BAD_CAPTION: YouTube copy holds serialised data, not prose")
    if len(title) > vp.YOUTUBE_TITLE_LIMIT:
        raise RuntimeError(f"YouTube title is {len(title)} chars (limit {vp.YOUTUBE_TITLE_LIMIT})")
    if len(body) > vp.CAPTION_LIMITS["youtube"]:
        raise RuntimeError(f"YouTube description is {len(body)} chars (limit 5000)")
    return title, body


def preflight(package: Path) -> dict:
    checks: list[dict] = []
    meta_path = package / "package.json"
    checks.append({"code": "package_json", "ok": meta_path.is_file(), "detail": str(meta_path)})
    if not meta_path.is_file():
        return {"ok": False, "platform": "youtube", "checks": checks}
    meta = json.loads(meta_path.read_text(encoding="utf-8"))
    review_hold = video_platform_review.blocker(package, "youtube")
    checks.append({"code": "independent_platform_review", "ok": review_hold is None,
                   "detail": review_hold or "no exact-master YouTube hold"})
    if review_hold:
        return {"ok": False, "platform": "youtube", "checks": checks}
    video = package / "video.mp4"
    actual = vp.sha256(video) if video.is_file() else ""
    checks.append({"code": "sealed_video_hash",
                   "ok": actual == meta["video"]["sha256"],
                   "detail": f"expected={meta['video']['sha256']} actual={actual}"})
    checks.append({"code": "vertical_1080x1920",
                   "ok": (meta["video"]["width"], meta["video"]["height"]) == vp.REQUIRED_DIMENSIONS,
                   "detail": f"{meta['video']['width']}x{meta['video']['height']}"})
    checks.append({"code": "audible_audio", "ok": bool(meta["video"]["has_audio"]),
                   "detail": str(meta["video"]["audio_codec"])})
    checks.append({"code": "short_duration_under_180s",
                   "ok": meta["video"]["duration_seconds"] <= 180.0,
                   "detail": f"{meta['video']['duration_seconds']}s"})
    try:
        title, body = copy_for(package)
        checks.append({"code": "bundle_copy", "ok": True,
                       "detail": f"title={title[:60]!r} description_chars={len(body)}"})
    except RuntimeError as exc:
        checks.append({"code": "bundle_copy", "ok": False, "detail": str(exc)})
    checks.append({"code": "dedicated_youtube_profile", "ok": YOUTUBE_PROFILE.is_dir(),
                   "detail": str(YOUTUBE_PROFILE)})
    existing = vr.read_verified(package, "youtube")
    checks.append({"code": "not_already_published", "ok": existing is None,
                   "detail": (existing or {}).get("post_url", "no receipt")})
    return {"ok": all(c["ok"] for c in checks), "platform": "youtube",
            "format": "native_short", "checks": checks}


def publish(package: Path, browser_mode: str | None = None) -> tuple[int, str]:
    status = preflight(package)
    if not status["ok"]:
        return 2, "preflight failed: " + ",".join(c["code"] for c in status["checks"] if not c["ok"])
    title, description = copy_for(package)
    video = package / "video.mp4"
    video_hash = vp.sha256(video)
    claim = vr.ExternalActionClaim(package, "youtube")

    with vr.slot_lock(package, "youtube"):
        claim.assert_clear()
        mode = publisher_browser_mode("youtube", browser_mode)
        log(f"browser mode -> {mode}")
        launch: dict = {}
        if mode == "headless":
            launch["user_agent"] = publisher_headless_user_agent()
        with profile_lock(YOUTUBE_PROFILE), sync_playwright() as pw:
            ctx = pw.chromium.launch_persistent_context(
                str(YOUTUBE_PROFILE), headless=(mode == "headless"), channel="chrome",
                args=["--disable-blink-features=AutomationControlled"],
                viewport={"width": 1440, "height": 940}, **launch,
            )
            page = ctx.new_page()
            try:
                page.goto("https://www.youtube.com/upload",
                          wait_until="domcontentloaded", timeout=60_000)
                time.sleep(7)
                body = page.evaluate("() => (document.body.innerText||'').slice(0,400)")
                vr.screenshot(page, package, "youtube-01-upload-open")
                if "sign in" in body.lower():
                    return 3, "YouTube session is signed out"

                uploaded = False
                for selector in ('input[type="file"][accept*="video"]',
                                 'ytcp-uploads-file-picker input[type="file"]',
                                 'input[type="file"]'):
                    try:
                        page.locator(selector).first.set_input_files(str(video), timeout=6000)
                        log(f"  file set via {selector}")
                        uploaded = True
                        break
                    except Exception:
                        continue
                if not uploaded:
                    vr.screenshot(page, package, "youtube-02-no-file-input")
                    return 4, ("no file input found; probe the session before "
                               "believing this - one expired session presents as "
                               "three unrelated-looking errors")
                time.sleep(10)

                for _ in range(3):
                    got = yt.fill_box(page, "title", title)
                    if got and got.strip().lower() not in ("", "video", "final"):
                        break
                    time.sleep(2)
                yt.fill_box(page, "description", description[:4500])
                page.evaluate("window.scrollTo(0, 600)")
                time.sleep(1.5)
                log(f"  not-for-kids -> {yt.click_not_for_kids(page)}")
                page.evaluate("window.scrollTo(0, 0)")
                time.sleep(2)
                vr.screenshot(page, package, "youtube-03-metadata-preflight")

                reached = False
                for index in range(6):
                    if yt.on_visibility_step(page):
                        reached = True
                        break
                    advanced = False
                    for _ in range(8):
                        if yt.click_next(page):
                            advanced = True
                            break
                        time.sleep(3)
                    if not advanced:
                        break
                    time.sleep(3)
                if not reached and not yt.on_visibility_step(page):
                    vr.screenshot(page, package, "youtube-04-never-reached-visibility")
                    return 5, "never reached the Visibility step"

                visibility = yt.select_public(page)
                log(f"  visibility -> {visibility}")
                if visibility.startswith("FAILED"):
                    vr.screenshot(page, package, "youtube-05-visibility-failed")
                    return 6, "could not select Public; refusing to save a draft"
                time.sleep(2)

                claim.commit()
                log(f"  publish -> {yt.click_publish(page)}")
                # never navigate this tab while Studio is still uploading (P2, 25 Sep: "Upload interrupted")
                if yt.wait_upload_complete(page) != "COMPLETE":
                    vr.screenshot(page, package, "youtube-06-still-uploading")
                    return 7, "upload still running after 30 min; left the tab alone rather than kill it"
                time.sleep(14)
                url = yt.public_url(page)
                vr.screenshot(page, package, "youtube-06-post-publish")
                video_id = url.rsplit("/", 1)[-1].split("?")[0] if "/shorts/" in url else ""
                if not video_id:
                    return 7, f"no video id surfaced (url={url!r}); cannot verify"

                state = yt.verify_public(page, video_id, title)
                for _ in range(2):
                    if state == "PUBLIC":
                        break
                    log(f"  still {state}; re-publishing the open draft")
                    yt.publish_open_draft(page, video_id, title, description)
                    state = yt.verify_public(page, video_id, title)
                if state != "PUBLIC":
                    return 7, f"Studio reports {state}, not PUBLIC"
                if not yt.verify_logged_out_public(video_id, title):
                    return 8, "Studio says PUBLIC but the logged-out oEmbed proof failed"

                post_url = f"https://www.youtube.com/shorts/{video_id}"
                receipt = vr.build_receipt(
                    package=package, platform="youtube", fmt="native_short",
                    post_url=post_url, platform_post_id=video_id,
                    caption=description, video_sha256=video_hash, video_file="video.mp4",
                    identity={"channel_id": CHANNEL_ID, "channel": "AGMM",
                              "verified_by": "studio_channel_page_and_public_oembed_author"},
                    verification={
                        "studio_state": state,
                        "logged_out_oembed_author_and_title_match": True,
                        "method": "studio_video_row_plus_logged_out_oembed",
                    },
                    extra={"title": title},
                )
                vr.save_receipt(package, "youtube", receipt)
                claim.mark_verified(post_url)
                return 0, post_url
            finally:
                yt.close_context_without_upload_hang(page, ctx)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--package", required=True, type=Path)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--publish", action="store_true")
    parser.add_argument("--browser-mode", choices=("headless", "headed"))
    args = parser.parse_args()
    package = args.package.resolve()
    status = preflight(package)
    if args.dry_run or not args.publish:
        print(json.dumps(status, indent=2))
        return 0 if status["ok"] else 2
    code, detail = publish(package, args.browser_mode)
    print(json.dumps({"platform": "youtube", "returncode": code, "detail": detail}, indent=2))
    return code


if __name__ == "__main__":
    raise SystemExit(main())
