#!/usr/bin/env python3
"""Publish one 30-ways film to Instagram and Facebook as native video.

This reuses the Business Suite composer walk that was independently verified on
the public Facebook and Instagram records on 2026-08-24, importing its proven
helpers from ``adapters/meta_publish.py`` rather than copying them. The
carousel lane's ordered six-panel motion route is untouched.

Two composer passes, not one
----------------------------
The week-1 bundle carries a different caption for Instagram and for Facebook.
A single cross-posted composer pass can only carry one, so each destination is
published on its own pass with its own caption and its own receipt. Instagram
converts a vertical sub-90s video to a Reel itself; the receipt records the
canonical ``/reel/`` or ``/p/`` URL Meta's own insights page reports, never an
assumed one.

Like the carousel motion route this remains a **governed policy-exception
lane**: the receipt is labelled honestly and is not a learner-ledger row.
"""
from __future__ import annotations

import argparse
import re
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
import meta_session_gate as msg  # noqa: E402
import video_platform_review  # noqa: E402
from browser_profiles import META_PROFILE, profile_is_locked, profile_lock, publisher_browser_mode  # noqa: E402

_spec = importlib.util.spec_from_file_location(
    "meta_publish_module", ROOT / "adapters" / "meta_publish.py"
)
mp = importlib.util.module_from_spec(_spec)
assert _spec.loader is not None
_spec.loader.exec_module(mp)

COMPOSER = "https://business.facebook.com/latest/composer/"
# Instagram refuses 9:16 in the post composer ("Adjust aspect ratio", 4:5-16:9,
# Publish greyed; proven 2026-09-07 08:11 and 11:28). Reels go through the
# Reel composer: Create (destination, video, text) -> Edit -> Share -> Share.
REELS_COMPOSER = f"https://business.facebook.com/latest/reels_composer/?asset_id={{page_id}}"
DESTINATIONS = ("instagram", "facebook")


def log(message: str) -> None:
    print(f"[{time.strftime('%H:%M:%S')}] [meta-video] {message}", flush=True)


def caption_for(package: Path, platform: str) -> str:
    meta = json.loads((package / "package.json").read_text(encoding="utf-8"))
    if platform not in meta.get("captions", {}):
        raise RuntimeError(
            f"HELD_AWAITING_BUNDLE: no {platform} caption in {meta.get('bundle_path')}"
        )
    text = (package / meta["captions"][platform]["file"]).read_text(encoding="utf-8").strip()
    if vp.looks_like_serialised_data(text):
        raise RuntimeError(f"HELD_BAD_CAPTION: caption file holds serialised data, not prose: {text[:80]!r}")
    if len(text) > vp.CAPTION_LIMITS[platform]:
        raise RuntimeError(
            f"{platform} caption is {len(text)} chars (limit {vp.CAPTION_LIMITS[platform]})"
        )
    return text


def preflight(package: Path, platform: str) -> dict:
    checks: list[dict] = []
    session_blocker = msg.session_blocker()
    checks.append({"code": "meta_session_gate", "ok": session_blocker is None,
                   "detail": session_blocker or "no recorded session hold"})
    meta_path = package / "package.json"
    checks.append({"code": "package_json", "ok": meta_path.is_file(), "detail": str(meta_path)})
    if not meta_path.is_file():
        return {"ok": False, "platform": platform, "checks": checks}
    meta = json.loads(meta_path.read_text(encoding="utf-8"))
    review_hold = video_platform_review.blocker(package, platform)
    checks.append({"code": "independent_platform_review", "ok": review_hold is None,
                   "detail": review_hold or "no exact-master platform hold"})
    if review_hold:
        return {"ok": False, "platform": platform, "checks": checks}
    video = package / "video.mp4"
    actual = vp.sha256(video) if video.is_file() else ""
    checks.append({"code": "sealed_video_hash", "ok": actual == meta["video"]["sha256"],
                   "detail": f"expected={meta['video']['sha256']} actual={actual}"})
    checks.append({"code": "vertical_1080x1920",
                   "ok": (meta["video"]["width"], meta["video"]["height"]) == vp.REQUIRED_DIMENSIONS,
                   "detail": f"{meta['video']['width']}x{meta['video']['height']}"})
    checks.append({"code": "audible_audio", "ok": bool(meta["video"]["has_audio"]),
                   "detail": str(meta["video"]["audio_codec"])})
    if platform == "instagram":
        checks.append({"code": "reel_duration_under_90s",
                       "ok": meta["video"]["duration_seconds"] <= 90.0,
                       "detail": f"{meta['video']['duration_seconds']}s"})
    try:
        caption = caption_for(package, platform)
        checks.append({"code": "bundle_caption", "ok": True, "detail": f"{len(caption)} chars"})
    except RuntimeError as exc:
        checks.append({"code": "bundle_caption", "ok": False, "detail": str(exc)})
    checks.append({"code": "meta_chrome_profile", "ok": META_PROFILE.is_dir(),
                   "detail": str(META_PROFILE)})
    # Bar 2 of the run standard: never race a runner. The Meta Chrome profile is
    # shared with analytics collection and TikTok recovery, and concurrent access
    # to one user-data-dir is what destroyed the Google session in August. A busy
    # profile is RETRYABLE, not terminal: no adapter opens, and the 5-minute
    # recovery sweep picks the slot up again once the holder exits.
    contended = profile_is_locked(META_PROFILE)
    holder = ""
    if contended:
        lock_file = ROOT / "runtime" / f"chrome-profile-{META_PROFILE.name}.lock"
        try:
            holder = lock_file.read_text(encoding="utf-8").strip()
        except OSError:
            holder = "unreadable lock file"
    checks.append({
        "code": "meta_profile_not_contended", "ok": not contended,
        "detail": (f"RETRYABLE: shared Meta Chrome profile is held by {holder!r}; "
                   "no adapter opened, the next recovery sweep retries"
                   if contended else "shared Meta Chrome profile is free"),
    })
    existing = vr.read_verified(package, platform)
    checks.append({"code": "not_already_published", "ok": existing is None,
                   "detail": (existing or {}).get("post_url", "no receipt")})
    return {"ok": all(c["ok"] for c in checks), "platform": platform,
            "format": "native_reel" if platform == "instagram" else "native_video_post",
            "checks": checks}


def reconcile_only(package: Path, platform: str) -> str:
    """Read-only proof of whether this exact caption is already public.

    Bar 4 of the run standard: reconciliation before any republish, always.
    """
    caption = caption_for(package, platform)
    with profile_lock(META_PROFILE), sync_playwright() as pw:
        ctx = pw.chromium.launch_persistent_context(
            str(META_PROFILE), headless=True, channel="chrome",
            args=["--disable-blink-features=AutomationControlled"],
            viewport={"width": 1440, "height": 1600})  # 5 Oct: terms banner + thumbnail strip push footer Next below 1200 too
        page = ctx.new_page()
        try:
            urls = mp.find_meta_post_urls(page, caption)
            url = str(urls.get(platform) or "")
            if not url and platform == "facebook":
                url = _fb_public_from_published_row(page, caption)
            return url
        finally:
            ctx.close()


def _ig_reel_codes(page) -> list[str]:
    """Reel codes currently on the public agmm_ltd reels grid (logged-out view)."""
    try:
        page.goto("https://www.instagram.com/agmm_ltd/reels/", wait_until="domcontentloaded", timeout=60_000)
        time.sleep(6)
        hrefs = page.eval_on_selector_all("a[href*='/reel/']", "els => els.map(e => e.href)")
        return [h.rstrip("/").rsplit("/", 1)[-1] for h in dict.fromkeys(hrefs)]
    except Exception as exc:
        log(f"    reels grid read failed: {str(exc)[:120]}")
        return []


def _ig_reel_caption_matches(page, code: str, caption: str) -> bool:
    try:
        page.goto(f"https://www.instagram.com/reel/{code}/", wait_until="domcontentloaded", timeout=60_000)
        time.sleep(5)
        body = page.evaluate("() => document.body.innerText")
        needle = mp.caption_fingerprint(caption)
        norm = " ".join(body.split())
        return needle in norm
    except Exception as exc:
        log(f"    reel caption read failed: {str(exc)[:120]}")
        return False


def _reel_set_destination(page, want: str) -> str:
    """Open the 'Post to' picker and leave exactly `want` selected. Returns the picker text."""
    picker = page.get_by_role("combobox").first
    picker.click()
    time.sleep(2)
    for name in ("AGMM", "agmm_ltd"):
        opt = page.get_by_role("option", name=re.compile(rf"^{re.escape(name)}$")).first
        if not opt.count():
            continue
        selected = (opt.get_attribute("aria-selected") or opt.get_attribute("aria-checked") or "").lower() == "true"
        if selected is None:
            selected = False
        should = (name == want)
        if selected != should:
            opt.click()
            time.sleep(1)
    page.keyboard.press("Escape")
    time.sleep(1.5)
    text = " ".join((picker.inner_text() or "").split()).replace("​", "").strip()
    if text != want:
        # the option states may not expose aria-selected; toggle by reading the picker text
        picker.click(); time.sleep(2)
        for name in ("AGMM", "agmm_ltd"):
            opt = page.get_by_role("option", name=re.compile(rf"^{re.escape(name)}$")).first
            if opt.count() and ((name in text) != (name == want)):
                opt.click(); time.sleep(1)
        page.keyboard.press("Escape"); time.sleep(1.5)
        text = " ".join((picker.inner_text() or "").split()).replace("​", "").strip()
    return text


def _click_footer_button(page, label: str, timeout_s: int = 60) -> bool:
    """Click the lowest visible [role=button] whose text (ZWSP stripped) equals `label`.
    The reel composer renders two 'Next' controls; the footer one is the lowest."""
    deadline = time.time() + timeout_s
    while time.time() < deadline:
        clicked = page.evaluate(
            """(label) => {
                const norm = s => (s || '').replace(/[\u200b\u200c\u200d\ufeff]/g, '').replace(/\s+/g, ' ').trim();
                let best = null;
                for (const el of document.querySelectorAll('[role="button"], button')) {
                    if (norm(el.innerText) !== label) continue;
                    const r = el.getBoundingClientRect();
                    if (r.width === 0 || r.height === 0) continue;
                    if ((el.getAttribute('aria-disabled') || '') === 'true') continue;
                    // must be inside the viewport: the composer also renders a
                    // small 'Next' below the caption box that can sit off-screen
                    // and win on y while a mouse click there does nothing.
                    // 5 Oct 17:48: Meta's terms banner shifts the 100vh layout down ~60 px, so the pinned footer Next is
                    // ALWAYS clipped ~15 px at any window height. Accept a control whose top 8+ px are visible and click
                    // inside the visible part.
                    if (r.top > window.innerHeight - 8 || r.top < 0) continue;
                    if (!best || r.y > best.y) best = {y: r.y, el};
                }
                if (!best) {
                    // 5 Oct 17:43: the footer Next sat just below the window, so nothing qualified and the step never
                    // advanced. Scroll the page (never the element itself) so the lowest match comes into view, then retry.
                    let low = null;
                    for (const el of document.querySelectorAll('[role="button"], button')) {
                        if (norm(el.innerText) !== label) continue;
                        const r = el.getBoundingClientRect();
                        if (r.width === 0 || r.height === 0) continue;
                        if (!low || r.bottom > low) low = r.bottom;
                    }
                    if (low && low > window.innerHeight) window.scrollBy(0, low - window.innerHeight + 40);
                    return null;
                }
                const r = best.el.getBoundingClientRect();
                return {x: r.x + r.width / 2, y: Math.min(r.y + r.height / 2, (r.top + window.innerHeight) / 2)};
            }""",
            label,
        )
        if clicked:
            # A real mouse click: React ignores element.click() on these divs
            # (2026-09-07 12:20, the composer never left the Create step).
            page.mouse.click(clicked["x"], clicked["y"])
            return True
        time.sleep(2)
    return False


def _fb_public_from_published_row(page, caption: str) -> str:
    """Facebook REELS: the insights page shows no 'View Post on Facebook' link, so
    resolve the published row's FB_PAGE_POST id and follow facebook.com/<id>,
    which redirects to the canonical /reel/<video id>/ page. Verified 2026-09-07:
    122192930960801231 -> https://www.facebook.com/reel/1753722392533662."""
    needle = mp.caption_fingerprint(caption)
    try:
        page.goto(f"https://business.facebook.com/latest/posts/published_posts?asset_id={mp.AGMM_PAGE_ID}", wait_until="domcontentloaded", timeout=60_000)
        time.sleep(8)
        post_id = page.evaluate(
            """(needle) => {
                const norm = s => (s || '').replace(/\s+/g, ' ').trim();
                for (const row of document.querySelectorAll('tr[role="row"]')) {
                    const text = norm(row.innerText);
                    if (!text.includes(needle) || /Failed to publish/.test(text)) continue;
                    for (const el of row.querySelectorAll('[data-surface]')) {
                        const m = (el.getAttribute('data-surface') || '').match(/post:FB_PAGE_POST:(\d+)/);
                        if (m) return m[1];
                    }
                }
                return '';
            }""", needle) or ""
        if not post_id:
            return ""
        page.goto(f"https://www.facebook.com/{post_id}", wait_until="domcontentloaded", timeout=60_000)
        time.sleep(7)
        body = " ".join(page.evaluate("() => document.body.innerText").split())
        url = page.url.split("?")[0]
        if needle in body and re.search(r"facebook\.com/(reel|AGMM/videos|AGMM/posts)/", url):
            return url
        return ""
    except Exception as exc:
        log(f"    facebook row fallback failed: {str(exc)[:120]}")
        return ""


def _publish_instagram_reel(page, package: Path, caption: str, video: Path, claim) -> tuple[int, str, dict]:
    """The Reel composer route. Returns (code, detail_or_url, verification)."""
    before = _ig_reel_codes(page)
    log(f"  reels on the public grid before: {len(before)}")
    page.goto(REELS_COMPOSER.format(page_id=mp.AGMM_PAGE_ID), wait_until="domcontentloaded", timeout=60_000)
    time.sleep(8)
    mp.dismiss_popups(page)
    vr.screenshot(page, package, "meta-instagram-01-reel-composer")
    if not mp.confirm_identity(page):
        if msg.hold_if_login(page):
            return 11, "Meta login required; scheduled browser attempts held", {}
        return 3, "reel composer is not scoped to the AGMM asset", {}
    dest = _reel_set_destination(page, "agmm_ltd")
    log(f"  reel destination -> {dest!r}")
    vr.screenshot(page, package, "meta-instagram-02-destinations")
    if dest != "agmm_ltd":
        return 4, f"could not scope the reel to agmm_ltd only (picker reads {dest!r})", {}
    with page.expect_file_chooser(timeout=20_000) as chooser:
        page.get_by_role("button", name=re.compile(r"^Add video$")).first.click()
    chooser.value.set_files(str(video))
    uploaded = False
    # 5 Oct 17:31: a 185 MB master did not reach 100% in a fixed 2 minutes while other uploads shared the line. Allow ~1.5 s
    # per MB (min 2, max 8 minutes); nothing irreversible has been clicked yet, so waiting longer is safe.
    polls = max(24, min(96, int(video.stat().st_size / 1e6 * 1.5 / 5) + 1))
    for _ in range(polls):
        time.sleep(5)
        body = page.evaluate("() => document.body.innerText")
        if "video.mp4" in body and "100%" in body:
            uploaded = True
            break
    vr.screenshot(page, package, "meta-instagram-03-video-uploaded")
    if not uploaded:
        return 5, "reel composer never reported the upload at 100%", {}
    box = page.get_by_role("textbox").first
    box.click(); box.fill(caption); time.sleep(1.5)
    readback = " ".join((box.inner_text() or "").split())
    if mp.caption_fingerprint(caption) not in readback:
        vr.screenshot(page, package, "meta-instagram-04-caption-failed")
        return 6, "reel caption did not read back", {}
    vr.screenshot(page, package, "meta-instagram-04-caption-set")
    if not _click_footer_button(page, "Next", timeout_s=30):
        vr.screenshot(page, package, "meta-instagram-04c-next-missing")
        return 7, "reel composer: footer Next never became clickable after upload", {}
    time.sleep(8)   # Create -> Edit, or straight to Share (Instagram-only reels skip Edit)
    if "Share now" not in page.evaluate("() => document.body.innerText"):
        if not _click_footer_button(page, "Next", timeout_s=30):
            vr.screenshot(page, package, "meta-instagram-04c-next2-missing")
            return 7, "reel composer: second Next (Edit -> Share) never became clickable", {}
        time.sleep(8)   # Edit -> Share
    vr.screenshot(page, package, "meta-instagram-04b-share-step")
    body = page.evaluate("() => document.body.innerText")
    if "Share now" not in body:
        return 7, "share step did not appear (no 'Share now')", {}
    claim.commit()
    if not _click_footer_button(page, "Share", timeout_s=20):
        return 8, "claim committed but the footer Share control was not found; reconcile by hand", {}
    log("  clicked 'Share' on the reel composer")
    time.sleep(30)
    vr.screenshot(page, package, "meta-instagram-05-post-publish")
    url = ""
    for attempt in range(1, 9):
        # 1) Meta's own published record + insights link
        url = mp.find_meta_post_urls(page, caption).get("instagram") or ""
        if url:
            break
        # 2) the public reels grid: a new code whose page carries the caption
        after = _ig_reel_codes(page)
        new = [c for c in after if c not in before]
        for code in new:
            if _ig_reel_caption_matches(page, code, caption):
                url = f"https://www.instagram.com/reel/{code}/"
                break
        if url:
            break
        log(f"  public record probe {attempt}/8 found nothing yet")
        time.sleep(20)
    return (0 if url else 8), (url or "clicked Share but no platform-native public record was found; state is AMBIGUOUS and must be reconciled by hand, never retried"), {"reels_before": len(before), "public_record_probes": attempt}


def publish(package: Path, platform: str, headed: bool | None = None,
            browser_mode: str | None = None) -> tuple[int, str]:
    mode = publisher_browser_mode("meta", browser_mode if browser_mode is not None else
                                  (None if headed is None else "headed" if headed else "headless"))
    status = preflight(package, platform)
    if not status["ok"]:
        return 2, "preflight failed: " + ",".join(c["code"] for c in status["checks"] if not c["ok"])
    caption = caption_for(package, platform)
    video = package / "video.mp4"
    video_hash = vp.sha256(video)
    claim = vr.ExternalActionClaim(package, platform)

    with vr.slot_lock(package, platform):
        claim.assert_clear()
        with profile_lock(META_PROFILE), sync_playwright() as pw:
            ctx = pw.chromium.launch_persistent_context(
                str(META_PROFILE), headless=(mode == "headless"), channel="chrome",
                args=["--disable-blink-features=AutomationControlled"],
                viewport={"width": 1440, "height": 1600})  # 5 Oct: terms banner + thumbnail strip push footer Next below 1200 too
            page = ctx.new_page()
            try:
                existing = mp.find_meta_post_urls(page, caption).get(platform) or ""
                if existing:
                    return 9, (f"read-only reconciliation found this caption already "
                               f"public at {existing}; refusing to publish a duplicate")

                if platform == "instagram":
                    code, detail, verification = _publish_instagram_reel(page, package, caption, video, claim)
                    if code != 0:
                        return code, detail
                    url = detail
                    post_id = url.rstrip("/").rsplit("/", 1)[-1]
                    receipt = vr.build_receipt(
                        package=package, platform=platform, fmt="native_reel",
                        post_url=url, platform_post_id=post_id, caption=caption,
                        video_sha256=video_hash, video_file="video.mp4",
                        identity={"asset": "agmm_ltd", "page_id": mp.AGMM_PAGE_ID,
                                  "verified_by": "business_suite_agmm_asset_marker"},
                        verification={"method": "reels_composer_then_public_reel_page_caption_match", **verification},
                        extra={"evidence_class": "verified_policy_exception",
                               "evidence_note": "Business Suite Reel composer route (Instagram-only destination)."},
                    )
                    vr.save_receipt(package, platform, receipt)
                    claim.mark_verified(url)
                    return 0, url

                page.goto(COMPOSER, wait_until="domcontentloaded", timeout=60_000)
                time.sleep(8)
                mp.dismiss_popups(page)
                vr.screenshot(page, package, f"meta-{platform}-01-composer")
                if not mp.confirm_identity(page):
                    if msg.hold_if_login(page):
                        return 11, "Meta login required; scheduled browser attempts held"
                    return 3, "composer is not scoped to the AGMM asset"

                destinations = mp.set_post_destinations(page, platform)
                log(f"  destinations -> {destinations}")
                vr.screenshot(page, package, f"meta-{platform}-02-destinations")
                if not destinations.get(
                    "AGMM" if platform == "facebook" else "agmm_ltd", False
                ):
                    return 4, f"could not select the {platform} destination: {destinations}"

                uploaded = mp.upload_slides(page, [video])
                if uploaded != 1:
                    vr.screenshot(page, package, f"meta-{platform}-03-upload-failed")
                    return 5, f"composer accepted {uploaded} of 1 video files"
                time.sleep(12)
                vr.screenshot(page, package, f"meta-{platform}-03-video-uploaded")

                if not mp.set_caption(page, caption):
                    vr.screenshot(page, package, f"meta-{platform}-04-caption-failed")
                    return 6, "caption did not read back from the composer"
                vr.screenshot(page, package, f"meta-{platform}-04-caption-set")

                claim.commit()
                # The same React footer used by Reels ignores synthetic
                # element.click(). Wait for an enabled, visible footer and
                # send a real mouse event; a claim still precedes the action.
                # 25 Sep: a 456 MB pilot needs several minutes in the post composer; Publish stays greyed until the
                # upload finishes. 120 s gave up at ~30% twice (P1 17:24, 17:49), so wait for the whole upload.
                # 25 Sep (P3 twice): with the green "Publish your video as a reel" notice showing, the click did not
                # register and the composer stayed open. Dismiss the notice first, then re-click only while the
                # composer is visibly still there (a registered click always leaves for the Planner).
                try:
                    page.evaluate("""() => { for (const el of document.querySelectorAll('[aria-label="Close"], [aria-label="Dismiss"]')) {
                        const box = el.closest('div'); if (box && /Publish your video as a reel/.test((box.parentElement||box).innerText||'')) { el.click(); return true; } } return false; }""")
                    time.sleep(2)
                except Exception:
                    pass
                published = _click_footer_button(page, "Publish", timeout_s=1500)
                if not published:
                    return 7, "no enabled footer Publish control; reconcile the standing claim"
                log("  clicked footer Publish with real mouse event")
                for again in range(2):
                    time.sleep(15)
                    still = page.evaluate("() => /Create post/.test(document.body.innerText) && /Post details/.test(document.body.innerText)")
                    if not still:
                        break
                    log(f"  composer still open 15 s after Publish; clicking again ({again + 1}/2)")
                    vr.screenshot(page, package, f"meta-{platform}-05a-still-open-{again + 1}")
                    _click_footer_button(page, "Publish", timeout_s=30)
                time.sleep(20)
                vr.screenshot(page, package, f"meta-{platform}-05-post-publish")

                url = ""
                for attempt in range(1, 7):
                    url = mp.find_meta_post_urls(page, caption).get(platform) or ""
                    if not url and platform == "facebook":
                        url = _fb_public_from_published_row(page, caption)
                    if url:
                        break
                    log(f"  public record probe {attempt}/6 found nothing yet")
                    time.sleep(20)
                if not url:
                    return 8, ("clicked Publish but no platform-native public record "
                               "was found; state is AMBIGUOUS and must be reconciled "
                               "by hand, never retried")

                post_id = url.rstrip("/").rsplit("/", 1)[-1]
                receipt = vr.build_receipt(
                    package=package, platform=platform,
                    fmt="native_reel" if platform == "instagram" else "native_video_post",
                    post_url=url, platform_post_id=post_id, caption=caption,
                    video_sha256=video_hash, video_file="video.mp4",
                    identity={"asset": "AGMM" if platform == "facebook" else "agmm_ltd",
                              "page_id": mp.AGMM_PAGE_ID,
                              "verified_by": "business_suite_agmm_asset_marker"},
                    verification={
                        "method": "business_suite_published_row_plus_object_insights_view_post_link",
                        "destinations_selected": destinations,
                        "public_record_probes": attempt,
                    },
                    extra={
                        "evidence_class": "verified_policy_exception",
                        "evidence_note": (
                            "Desktop Business Suite route, same governed exception as "
                            "the carousel motion lane. Not a learner-ledger row."
                        ),
                    },
                )
                vr.save_receipt(package, platform, receipt)
                claim.mark_verified(url)
                return 0, url
            finally:
                try:
                    if not page.is_closed():
                        page.close(run_before_unload=False)
                except Exception:
                    pass
                ctx.close()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--package", required=True, type=Path)
    parser.add_argument("--destination", choices=DESTINATIONS, required=True)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--reconcile-only", action="store_true")
    parser.add_argument("--publish", action="store_true")
    parser.add_argument("--browser-mode", choices=("headless", "headed"), default=None)
    args = parser.parse_args()
    package = args.package.resolve()
    if args.reconcile_only:
        url = reconcile_only(package, args.destination)
        print(json.dumps({"platform": args.destination,
                          "public_record": url or None,
                          "detail": url or "no exact public record yet"}, indent=2))
        return 0
    status = preflight(package, args.destination)
    if args.dry_run or not args.publish:
        print(json.dumps(status, indent=2))
        return 0 if status["ok"] else 2
    code, detail = publish(package, args.destination, browser_mode=args.browser_mode)
    print(json.dumps({"platform": args.destination, "returncode": code, "detail": detail}, indent=2))
    return code


if __name__ == "__main__":
    raise SystemExit(main())
