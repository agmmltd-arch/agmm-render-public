#!/usr/bin/env python3
"""Publish one 30-ways film as a native LinkedIn video post.

Differences from ``adapters/linkedin_video_publish.py`` (the carousel lane's
slideshow route, left untouched): the caption comes from the week-1 bundle and
carries no 300-500 word document-carousel contract, and there is no sealed
licensed-audio manifest because the film's narration is its own audio.

Identity is proved live on every run through the ``/in/me/`` redirect to the
canonical authorised profile URL plus the Samuel Wall name and the AGMM marker.
The headline is recorded as observed evidence, never used as a credential: on
2026-08-25 a correct session failed a slot because the publisher required an
obsolete exact headline.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "adapters"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from playwright.sync_api import TimeoutError as PlaywrightTimeoutError  # noqa: E402
from playwright.sync_api import sync_playwright  # noqa: E402

import video_package as vp  # noqa: E402
import video_receipts as vr  # noqa: E402
from linkedin_identity import PROFILE_NAME, PROFILE_URL, verify_identity  # noqa: E402
from browser_profiles import publisher_browser_mode  # noqa: E402

SESSION = Path(
    "/Users/samwall/alfred/auto-poster/session-backup/linkedin-storage-state.json"
)


def log(message: str) -> None:
    print(f"[{time.strftime('%H:%M:%S')}] [li-video] {message}", flush=True)


def caption_for(package: Path) -> str:
    meta = json.loads((package / "package.json").read_text(encoding="utf-8"))
    if "linkedin" not in meta.get("captions", {}):
        raise RuntimeError(
            f"HELD_AWAITING_BUNDLE: no LinkedIn caption in {meta.get('bundle_path')}"
        )
    text = (package / meta["captions"]["linkedin"]["file"]).read_text(encoding="utf-8").strip()
    if vp.looks_like_serialised_data(text):
        raise RuntimeError(f"HELD_BAD_CAPTION: caption file holds serialised data, not prose: {text[:80]!r}")
    if len(text) > vp.CAPTION_LIMITS["linkedin"]:
        raise RuntimeError(f"LinkedIn caption is {len(text)} chars (limit 3000)")
    return text


def readback_matches(expected: str, observed: str) -> bool:
    """Wording and URLs must match exactly; only whitespace and zero-width
    editor markers may vary. LinkedIn renders one blank line as several nested
    block breaks in inner_text."""
    def canonical(value: str) -> str:
        return re.sub(r"\s+", " ", value.replace("​", "")).strip()

    return canonical(expected) == canonical(observed)


def preflight(package: Path) -> dict:
    checks: list[dict] = []
    meta_path = package / "package.json"
    checks.append({"code": "package_json", "ok": meta_path.is_file(), "detail": str(meta_path)})
    if not meta_path.is_file():
        return {"ok": False, "platform": "linkedin", "checks": checks}
    meta = json.loads(meta_path.read_text(encoding="utf-8"))
    video = package / "video.mp4"
    actual = vp.sha256(video) if video.is_file() else ""
    checks.append({"code": "sealed_video_hash", "ok": actual == meta["video"]["sha256"],
                   "detail": f"expected={meta['video']['sha256']} actual={actual}"})
    checks.append({"code": "vertical_1080x1920",
                   "ok": (meta["video"]["width"], meta["video"]["height"]) == vp.REQUIRED_DIMENSIONS,
                   "detail": f"{meta['video']['width']}x{meta['video']['height']}"})
    checks.append({"code": "audible_audio", "ok": bool(meta["video"]["has_audio"]),
                   "detail": str(meta["video"]["audio_codec"])})
    try:
        caption = caption_for(package)
        checks.append({"code": "bundle_caption", "ok": True,
                       "detail": f"{len(caption)} chars"})
    except RuntimeError as exc:
        checks.append({"code": "bundle_caption", "ok": False, "detail": str(exc)})
    checks.append({"code": "dedicated_session_file", "ok": SESSION.is_file(),
                   "detail": str(SESSION)})
    existing = vr.read_verified(package, "linkedin")
    checks.append({"code": "not_already_published", "ok": existing is None,
                   "detail": (existing or {}).get("post_url", "no receipt")})
    return {"ok": all(c["ok"] for c in checks), "platform": "linkedin",
            "format": "native_video_post", "checks": checks}


def find_existing_activity(page, caption: str) -> str:
    """Read-only reconciliation before any composer opens.

    A composer, a video preview or a rehearsed Post control is not a public
    post. The authenticated recent-activity feed is.
    """
    needle = re.sub(r"\s+", " ", caption).strip()[:52]
    page.goto(f"{PROFILE_URL}recent-activity/all/",
              wait_until="domcontentloaded", timeout=60_000)
    page.wait_for_timeout(4_000)
    try:
        return page.evaluate(
            """
            (needle) => {
                const norm = v => (v || '').replace(/\\s+/g, ' ').trim();
                for (const node of document.querySelectorAll('div[data-urn], div[data-id]')) {
                    if (!norm(node.innerText).includes(needle)) continue;
                    const urn = node.getAttribute('data-urn') || node.getAttribute('data-id') || '';
                    const m = urn.match(/urn:li:activity:(\\d+)/);
                    if (m) return 'https://www.linkedin.com/feed/update/' + m[0] + '/';
                }
                return '';
            }
            """,
            needle,
        ) or ""
    except Exception:
        return ""


def verify_public_url(browser, url: str, caption: str) -> dict:
    context = browser.new_context(storage_state=str(SESSION), locale="en-GB",
                                  viewport={"width": 1280, "height": 900})
    try:
        page = context.new_page()
        page.goto(url, wait_until="domcontentloaded", timeout=60_000)
        page.wait_for_timeout(3_500)
        body = page.locator("body").inner_text(timeout=20_000)
        name_ok = PROFILE_NAME in body
        caption_ok = re.sub(r"\s+", " ", caption).strip()[:40] in re.sub(r"\s+", " ", body)
        if not (name_ok and caption_ok):
            raise RuntimeError(
                "LinkedIn activity URL did not expose the approved identity and "
                f"caption (name={name_ok} caption={caption_ok})"
            )
        return {"identity_on_page": name_ok, "caption_on_page": caption_ok,
                "method": "authenticated_activity_url_readback"}
    finally:
        context.close()


def publish(package: Path, headed: bool | None = None,
            browser_mode: str | None = None) -> tuple[int, str]:
    mode = publisher_browser_mode("linkedin", browser_mode if browser_mode is not None else
                                  (None if headed is None else "headed" if headed else "headless"))
    status = preflight(package)
    if not status["ok"]:
        return 2, "preflight failed: " + ",".join(c["code"] for c in status["checks"] if not c["ok"])
    caption = caption_for(package)
    video = package / "video.mp4"
    video_hash = vp.sha256(video)
    claim = vr.ExternalActionClaim(package, "linkedin")

    with vr.slot_lock(package, "linkedin"):
        claim.assert_clear()
        with sync_playwright() as pw:
            browser = pw.chromium.launch(
                channel="chrome", headless=(mode == "headless"),
                args=["--disable-blink-features=AutomationControlled"])
            context = browser.new_context(
                storage_state=str(SESSION), viewport={"width": 1440, "height": 1000},
                locale="en-GB", timezone_id="Europe/London")
            page = context.new_page()
            try:
                identity = verify_identity(page)
                log(f"  identity -> {identity['name']} / {identity['headline'][:60]!r}")

                existing = find_existing_activity(page, caption)
                if existing:
                    return 9, (f"read-only reconciliation found this caption already "
                               f"public at {existing}; refusing to publish a duplicate")
                page.goto("https://www.linkedin.com/feed/",
                          wait_until="domcontentloaded", timeout=60_000)
                page.wait_for_timeout(2_000)
                vr.screenshot(page, package, "linkedin-01-feed")

                try:
                    page.get_by_role("button", name=re.compile("Start a post", re.I)).first.click(timeout=20_000)
                except PlaywrightTimeoutError:
                    # A click may open the composer before its navigation wait times out.
                    opened = page.get_by_role("dialog").filter(has_text=PROFILE_NAME)
                    opened.wait_for(state="visible", timeout=20_000)
                    media_ready = opened.locator('button[aria-label="Media"]')
                    if (opened.count() != 1 or media_ready.count() != 1
                            or not media_ready.is_visible() or not media_ready.is_enabled()):
                        raise
                    log("  Start a post timed out after opening the authorised composer; Media is ready")
                page.wait_for_timeout(2_500)
                vr.screenshot(page, package, "linkedin-02-composer-open")

                with page.expect_file_chooser(timeout=25_000) as chooser:
                    # 2026-09-07: the composer toolbar is icons only — emoji,
                    # "Media" (images and video, one file chooser), "Expand
                    # content types", "+". The old "Video" text control is gone;
                    # matching it by text hit the feed's "Video" shortcut and a
                    # player's "Play Video" button and timed out twice.
                    media = page.locator('div[role="dialog"] button[aria-label="Media"], button[aria-label="Media"]')
                    if media.count():
                        media.first.click(timeout=8_000)
                    else:
                        try:
                            page.get_by_role("button", name="Video", exact=True).click(timeout=8_000)
                        except PlaywrightTimeoutError:
                            page.locator('div[role="dialog"] button:has-text("Video")').first.click(timeout=8_000)
                chooser.value.set_files(str(video))
                vr.screenshot(page, package, "linkedin-03-video-chosen")

                # The editor footer owns Next; a background feed carousel also exposes Next.
                next_button = page.get_by_role("contentinfo").get_by_role("button", name="Next", exact=True)
                next_button.wait_for(state="visible", timeout=90_000)
                for _ in range(90):
                    if next_button.is_enabled():
                        break
                    page.wait_for_timeout(1_000)
                if not next_button.is_enabled():
                    vr.screenshot(page, package, "linkedin-04-next-never-enabled")
                    return 5, "LinkedIn video editor never enabled Next"
                next_button.click()
                page.wait_for_timeout(2_000)

                composer = page.get_by_role("dialog").last
                textbox = composer.locator('div[contenteditable="true"][role="textbox"]').first
                textbox.fill(caption)
                page.wait_for_timeout(1_000)
                observed = textbox.inner_text()
                vr.screenshot(page, package, "linkedin-05-caption-set")
                if not readback_matches(caption, observed):
                    return 6, "caption readback did not match the bundle copy exactly"

                post = composer.get_by_role("button", name="Post", exact=True)
                if not post.is_enabled():
                    vr.screenshot(page, package, "linkedin-06-post-disabled")
                    return 7, "Post button is disabled after the video upload"

                claim.commit()
                post.click()
                alert = page.get_by_role("alert").filter(has_text="Post successful").last
                # 25 Sep: a 456 MB pilot was 38% uploaded when 120 s ran out ("Keep the page open to finish
                # uploading"), and closing the page killed the upload. Wait for the whole upload.
                alert.wait_for(state="visible", timeout=1_500_000)
                url = alert.get_by_role("link", name="View post", exact=True).get_attribute("href")
                vr.screenshot(page, package, "linkedin-07-post-successful")
                if not url:
                    return 8, "success alert exposed no public URL; reconcile by hand"

                verification = verify_public_url(browser, url, caption)
                match = re.search(r"urn:li:activity:(\d+)", url)
                if not match:
                    return 8, f"invalid LinkedIn public activity URL: {url}"
                receipt = vr.build_receipt(
                    package=package, platform="linkedin", fmt="native_video_post",
                    post_url=url, platform_post_id=match.group(1), caption=caption,
                    video_sha256=video_hash, video_file="video.mp4",
                    identity=identity, verification=verification,
                )
                vr.save_receipt(package, "linkedin", receipt)
                claim.mark_verified(url)
                return 0, url
            except PlaywrightTimeoutError as exc:
                try:
                    vr.screenshot(page, package, "linkedin-99-timeout")
                except Exception:
                    pass
                return 10, f"LinkedIn video publisher timed out: {str(exc)[:300]}"
            finally:
                # Close the upload page before its context. An explicit
                # browser.close() after a completed LinkedIn document upload hung
                # that RPC and masked the real outcome on 2026-08-24.
                try:
                    if not page.is_closed():
                        page.close(run_before_unload=False)
                except Exception:
                    pass
                context.close()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--package", required=True, type=Path)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--publish", action="store_true")
    parser.add_argument("--browser-mode", choices=("headless", "headed"), default=None)
    args = parser.parse_args()
    package = args.package.resolve()
    status = preflight(package)
    if args.dry_run or not args.publish:
        print(json.dumps(status, indent=2))
        return 0 if status["ok"] else 2
    code, detail = publish(package, browser_mode=args.browser_mode)
    print(json.dumps({"platform": "linkedin", "returncode": code, "detail": detail}, indent=2))
    return code


if __name__ == "__main__":
    raise SystemExit(main())
