#!/usr/bin/env python3
"""Probe or publish one reviewed F07 master through YouTube Studio in a cloud browser.

The browser receives a temporary Playwright storage-state secret.  It never
prints that state.  Publish mode requires a hash-bound independent approval,
uses YouTube's normal Studio upload surface, and succeeds only after Studio
reports PUBLIC and logged-out oEmbed returns the exact AGMM title.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import time
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

from PIL import Image, ImageChops, ImageStat
from playwright.sync_api import sync_playwright

CHANNEL_ID = "UChbp0G1KDjCnruAhxfmzEXg"
LONGFORM_TAB = f"https://studio.youtube.com/channel/{CHANNEL_ID}/videos/upload"
LONDON = ZoneInfo("Europe/London")
STUDIO_MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sept", "Oct", "Nov", "Dec"]


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for block in iter(lambda: f.read(8 * 1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def save_json(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, ensure_ascii=False) + "\n")


def norm(value: str) -> str:
    return re.sub(r"\s+", " ", value or "").strip()


def signed_in(page) -> tuple[bool, str]:
    body = (page.locator("body").inner_text(timeout=20_000) or "")[:12_000]
    bad = "sign in" in body.lower() or "accounts.google.com" in page.url
    marker = "agmm" in body.lower()
    return (not bad and marker), f"signed_out={bad} agmm_marker={marker} host={urllib.parse.urlparse(page.url).netloc}"


def fill_box(page, which: str, text: str) -> str:
    return page.evaluate(
        """([which, text]) => {
          const el = which === 'title'
            ? (document.querySelector('ytcp-mention-textbox#title-textarea div[contenteditable="true"]')
               || document.querySelector('#title-textarea #textbox')
               || document.querySelector('div[aria-label*="Title" i][contenteditable="true"]'))
            : (document.querySelector('ytcp-mention-textbox#description-textarea div[contenteditable="true"]')
               || document.querySelector('#description-textarea #textbox'));
          if (!el) return '';
          el.scrollIntoView({block:'center'}); el.focus();
          const s=window.getSelection(), r=document.createRange();
          r.selectNodeContents(el); s.removeAllRanges(); s.addRange(r);
          document.execCommand('delete', false, null);
          document.execCommand('insertText', false, text);
          el.dispatchEvent(new Event('input',{bubbles:true,cancelable:true}));
          el.dispatchEvent(new Event('change',{bubbles:true}));
          return (el.innerText||'').trim();
        }""",
        [which, text],
    )


def checked(page, name: str) -> bool:
    return bool(page.evaluate(
        """n => { const r=document.querySelector(`tp-yt-paper-radio-button[name="${n}"]`);
          return !!r && (r.getAttribute('aria-checked')==='true' || r.hasAttribute('checked')
                         || r.classList.contains('iron-selected')); }""", name))


def click_radio(page, name: str) -> bool:
    for _ in range(4):
        if checked(page, name):
            return True
        try:
            loc = page.locator(f'tp-yt-paper-radio-button[name="{name}"]').first
            loc.scroll_into_view_if_needed(timeout=4000)
            loc.click(timeout=5000, force=True)
        except Exception:
            pass
        time.sleep(2)
    return checked(page, name)


def wait_details(page, timeout_s: int = 120) -> bool:
    deadline = time.time() + timeout_s
    while time.time() < deadline:
        if page.locator("ytcp-mention-textbox#title-textarea, #title-textarea").count() and page.locator("input#file-loader").count():
            return True
        time.sleep(2)
    return False


def set_thumbnail(page, thumb: Path) -> None:
    loader = page.locator("input#file-loader").first
    if not loader.count() or loader.is_disabled():
        raise RuntimeError("custom thumbnail input is missing or disabled")
    loader.set_input_files(str(thumb), timeout=20_000)
    for _ in range(30):
        if page.locator("ytcp-video-thumbnail-editor img").count():
            return
        time.sleep(1)
    raise RuntimeError("Studio showed no thumbnail preview")


def open_show_more(page) -> None:
    if page.locator('tp-yt-paper-radio-button[name="VIDEO_HAS_ALTERED_CONTENT_YES"]').count():
        return
    page.locator("ytcp-button#toggle-button, #toggle-button").first.click(timeout=8000)
    time.sleep(2)


def on_visibility(page) -> bool:
    return page.locator('tp-yt-paper-radio-button[name="PUBLIC"]').count() > 0


def walk_visibility(page) -> None:
    for _ in range(7):
        if on_visibility(page):
            return
        moved = False
        for _ in range(20):
            b = page.locator("ytcp-button#next-button").first
            if b.count() and not b.is_disabled():
                b.click(timeout=6000)
                moved = True
                break
            time.sleep(3)
        if not moved:
            break
        time.sleep(3)
    if not on_visibility(page):
        raise RuntimeError("never reached Studio Visibility step")


def wait_publish_enabled(page, timeout_s: int = 3600) -> None:
    deadline = time.time() + timeout_s
    while time.time() < deadline:
        b = page.locator("ytcp-button#done-button").first
        if b.count() and not b.is_disabled():
            return
        time.sleep(5)
    raise RuntimeError("Publish never enabled before timeout")


def wait_upload_complete(page, timeout_s: int = 10800) -> None:
    deadline = time.time() + timeout_s
    while time.time() < deadline:
        text = (page.locator("body").inner_text(timeout=10_000) or "")[:20_000]
        if re.search(r"Upload interrupted|Processing abandoned", text, re.I):
            raise RuntimeError("Studio reports interrupted upload")
        if not re.search(r"Uploading\s+\d+%", text, re.I):
            return
        time.sleep(10)
    raise RuntimeError("Studio upload did not complete before timeout")


def public_url(page) -> str:
    body = page.locator("body").inner_text(timeout=10_000) or ""
    m = re.search(r"https://youtu\.be/([\w-]+)", body)
    if m:
        return "https://www.youtube.com/watch?v=" + m.group(1)
    for href in page.locator('a[href*="youtu.be/"], a[href*="watch?v="]').evaluate_all("els => els.map(e => e.href)"):
        m = re.search(r"(?:youtu\.be/|watch\?v=)([\w-]+)", href)
        if m:
            return "https://www.youtube.com/watch?v=" + m.group(1)
    return ""


def studio_state(page, video_id: str, title: str) -> str:
    page.goto(LONGFORM_TAB, wait_until="domcontentloaded", timeout=60_000)
    for _ in range(40):
        if page.locator("ytcp-video-row").count():
            break
        time.sleep(2)
    return page.evaluate(
        """([vid,title]) => { const read=row => { const t=row.innerText;
          if (/\\bPublic\\b/.test(t)) return 'PUBLIC'; if (/\\bPrivate\\b/.test(t)) return 'PRIVATE';
          if (/\\bDraft\\b/.test(t)) return 'DRAFT'; if (/\\bUnlisted\\b/.test(t)) return 'UNLISTED'; return 'UNKNOWN'; };
          const rows=[...document.querySelectorAll('ytcp-video-row')];
          for (const row of rows) { const a=row.querySelector('a[href*="/video/"]'); if (a&&a.href.includes(vid)) return read(row); }
          for (const row of rows) if (title&&row.innerText.includes(title)) return read(row);
          return 'ROW_NOT_FOUND'; }""", [video_id,title])


def schedule_label(when: datetime) -> str:
    return f"{when.day} {STUDIO_MONTHS[when.month - 1]} {when.year}"


def scheduler_state(page) -> dict:
    return page.evaluate(
        """() => { const s=document.querySelector('ytcp-visibility-scheduler');
          const d=document.querySelector('#datepicker-trigger');
          const t=document.querySelector('#time-of-day-container input');
          const b=document.querySelector('ytcp-button#done-button');
          return {visible:!!s&&s.offsetParent!==null,text:s?s.innerText:'',date:d?d.innerText.trim():'',
            time:t?t.value:'',done_label:b?(b.innerText||'').trim():'',
            premiere:(()=>{if(!s)return null;const c=s.querySelector('[role="checkbox"],ytcp-checkbox-lit,tp-yt-paper-checkbox');
              return c?(c.getAttribute('aria-checked')==='true'||c.hasAttribute('checked')):null;})(),
            browser_tz:Intl.DateTimeFormat().resolvedOptions().timeZone}; }""")


def set_schedule(page, when: datetime) -> dict:
    when = when.astimezone(LONDON)
    want_date, want_time = schedule_label(when), when.strftime("%H:%M")
    wall = page.evaluate("ms => {const d=new Date(ms);return [d.getFullYear(),d.getMonth()+1,d.getDate(),d.getHours(),d.getMinutes()]}", int(when.timestamp()*1000))
    if list(wall) != [when.year, when.month, when.day, when.hour, when.minute]:
        raise RuntimeError(f"browser timezone maps schedule to {wall}, not {want_date} {want_time}")
    state = scheduler_state(page)
    if not state["visible"]:
        page.locator("#second-container-expand-button").first.click(timeout=8000)
        time.sleep(2)
    for _ in range(3):
        state = scheduler_state(page)
        if norm(state["date"]) == want_date:
            break
        page.locator("#datepicker-trigger").first.click(timeout=8000)
        time.sleep(1)
        box = page.locator("ytcp-date-picker input").first
        box.fill(want_date); box.press("Enter"); time.sleep(2)
    for _ in range(3):
        state = scheduler_state(page)
        if state["time"] == want_time:
            break
        box = page.locator("#time-of-day-container input").first
        box.fill(want_time); box.press("Enter"); time.sleep(2)
    state = scheduler_state(page)
    problems = []
    if norm(state["date"]) != want_date: problems.append(f"date={state['date']!r}")
    if state["time"] != want_time: problems.append(f"time={state['time']!r}")
    if state.get("premiere"): problems.append("premiere selected")
    if state["done_label"] != "Schedule": problems.append(f"button={state['done_label']!r}")
    if problems:
        raise RuntimeError("schedule readback failed: " + "; ".join(problems))
    return {**state, "scheduled_for": when.isoformat(), "scheduled_epoch": int(when.timestamp())}


def studio_record(page, video_id: str, title: str) -> tuple[str, dict]:
    bodies: list[dict] = []
    def on_response(response):
        if "list_creator_videos" in response.url:
            try: bodies.append(response.json())
            except Exception: pass
    page.on("response", on_response)
    try:
        row = studio_state(page, video_id, title)
        time.sleep(3)
    finally:
        page.remove_listener("response", on_response)
    for body in bodies:
        for video in body.get("videos", []) if isinstance(body, dict) else []:
            if video.get("videoId") == video_id:
                fields = ("videoId","title","privacy","status","timeCreatedSeconds","timePublishedSeconds","scheduledPublishingDetails","visibility")
                return row, {k:video.get(k) for k in fields}
    return row, {}


def scheduled_evidence(row: str, record: dict, when: datetime) -> dict:
    stamps: list[int] = []
    def walk(value):
        if isinstance(value, dict):
            for item in value.values(): walk(item)
        elif isinstance(value, list):
            for item in value: walk(item)
        elif isinstance(value, (int,str)) and str(value).isdigit() and 1_600_000_000 < int(value) < 4_000_000_000:
            stamps.append(int(value))
    details = record.get("scheduledPublishingDetails") or {}
    walk(details)
    target = int(when.timestamp())
    private = str(record.get("privacy") or "").endswith("PRIVATE")
    ok = (private and target in stamps) or (row == "SCHEDULED" and (target in stamps or not details))
    return {"ok":ok,"row":row,"server_privacy":record.get("privacy"),"server_scheduled_details":details,
            "server_scheduled_epoch_matches_slot":target in stamps,"slot_epoch":target}


def oembed(video_id: str) -> dict:
    url = "https://www.youtube.com/oembed?" + urllib.parse.urlencode(
        {"url": f"https://www.youtube.com/watch?v={video_id}", "format": "json"})
    with urllib.request.urlopen(url, timeout=20) as r:
        return json.loads(r.read().decode())


def image_distance(a: Path, b: Path) -> float:
    with Image.open(a).convert("RGB") as ia, Image.open(b).convert("RGB") as ib:
        ia = ia.resize((320, 180))
        ib = ib.resize((320, 180))
        stat = ImageStat.Stat(ImageChops.difference(ia, ib))
        return sum(stat.mean) / 3


def verify_thumbnail(ctx, page, video_id: str, ours: Path, out: Path) -> float:
    page.goto(f"https://studio.youtube.com/video/{video_id}/edit", wait_until="domcontentloaded", timeout=60_000)
    for _ in range(40):
        srcs = page.locator("img").evaluate_all("(els,vid) => [...new Set(els.map(i=>i.src).filter(s=>s.includes('ytimg.com/vi/'+vid+'/')))]", video_id)
        if srcs:
            break
        time.sleep(2)
    best = None
    for src in srcs:
        try:
            raw = ctx.request.get(src, timeout=30_000).body()
            out.write_bytes(raw)
            d = image_distance(ours, out)
            best = d if best is None else min(best, d)
        except Exception:
            continue
    if best is None or best > 24.0:
        raise RuntimeError(f"Studio thumbnail mismatch or unavailable: distance={best}")
    return best


def publish(args, ctx, page, evidence: Path) -> dict:
    metadata = json.loads(args.metadata.read_text())
    approval = json.loads(args.approval.read_text())
    actual = sha256(args.video)
    if actual != args.expected_sha256 or approval.get("master_sha256") != actual:
        raise RuntimeError("master hash is not covered by the independent approval")
    if str(approval.get("source_run_id")) != str(args.source_run_id) or approval.get("overall") != "PASS":
        raise RuntimeError("approval is not a PASS for this exact cloud run")
    title = metadata["snippet"]["title"]
    description = metadata["snippet"]["description"]
    page.goto("https://www.youtube.com/upload", wait_until="domcontentloaded", timeout=60_000)
    time.sleep(7)
    ok, detail = signed_in(page)
    if not ok:
        raise RuntimeError("YouTube cloud session is not the AGMM Studio session: " + detail)
    page.screenshot(path=str(evidence / "01-upload-open.png"))
    file_input = page.locator('input[type="file"][accept*="video"], ytcp-uploads-file-picker input[type="file"]').first
    if not file_input.count():
        raise RuntimeError("Studio video file input did not render")
    file_input.set_input_files(str(args.video), timeout=30_000)
    if not wait_details(page):
        raise RuntimeError("Studio details step did not open")
    if norm(fill_box(page, "title", title)) != norm(title):
        raise RuntimeError("title readback mismatch")
    if norm(fill_box(page, "description", description)) != norm(description):
        raise RuntimeError("description readback mismatch")
    set_thumbnail(page, args.thumbnail)
    if not click_radio(page, "VIDEO_MADE_FOR_KIDS_NOT_MFK"):
        raise RuntimeError("not-made-for-kids readback failed")
    open_show_more(page)
    altered = "VIDEO_HAS_ALTERED_CONTENT_YES" if metadata["status"].get("containsSyntheticMedia") else "VIDEO_HAS_ALTERED_CONTENT_NO"
    if not click_radio(page, altered):
        raise RuntimeError("altered-content readback failed")
    page.screenshot(path=str(evidence / "02-details-sealed.png"))
    walk_visibility(page)
    schedule_at = datetime.fromisoformat(args.schedule_at).astimezone(LONDON) if args.schedule_at else None
    if schedule_at:
        if (schedule_at - datetime.now(LONDON)).total_seconds() < 15 * 60:
            raise RuntimeError("schedule is less than 15 minutes ahead")
        release_state = set_schedule(page, schedule_at)
    else:
        if not click_radio(page, "PUBLIC"):
            raise RuntimeError("PUBLIC selection readback failed")
        release_state = {"visibility":"PUBLIC"}
    wait_publish_enabled(page)
    page.screenshot(path=str(evidence / ("03-schedule-ready.png" if schedule_at else "03-public-ready.png")))
    page.locator("ytcp-button#done-button").first.click(timeout=10_000, force=True)
    wait_upload_complete(page)
    time.sleep(15)
    url = public_url(page)
    if not url:
        raise RuntimeError("Studio surfaced no video URL after Publish")
    video_id = urllib.parse.parse_qs(urllib.parse.urlparse(url).query).get("v", [""])[0]
    if schedule_at:
        row, record = studio_record(page, video_id, title)
        proof = scheduled_evidence(row, record, schedule_at)
        for _ in range(5):
            if proof["ok"]: break
            time.sleep(20)
            row, record = studio_record(page, video_id, title)
            proof = scheduled_evidence(row, record, schedule_at)
        if not proof["ok"]:
            raise RuntimeError(f"YouTube server did not prove the schedule: {proof}")
        thumb_out = evidence / "studio-thumbnail.jpg"
        distance = verify_thumbnail(ctx, page, video_id, args.thumbnail, thumb_out)
        return {
            "schema":"agmm-youtube-cloud-studio-scheduled-v1","overall":"SCHEDULED_VERIFIED",
            "video_id":video_id,"post_url":url,"title":title,"master_sha256":actual,
            "source_run_id":str(args.source_run_id),"thumbnail_sha256":sha256(args.thumbnail),
            "scheduled_for":schedule_at.isoformat(),"scheduled_evidence":proof,"studio_record":record,
            "studio_thumbnail_mean_abs_distance":round(distance,2),"wizard_schedule":release_state,
            "verified_at":datetime.now(timezone.utc).isoformat(),
        }
    state = studio_state(page, video_id, title)
    for _ in range(5):
        if state == "PUBLIC": break
        time.sleep(20); state = studio_state(page, video_id, title)
    if state != "PUBLIC": raise RuntimeError(f"Studio reports {state}, not PUBLIC")
    payload = {}
    for _ in range(8):
        try:
            payload = oembed(video_id)
            if payload.get("author_name", "").strip().lower() == "agmm" and payload.get("title", "").strip() == title:
                break
        except Exception:
            pass
        time.sleep(20)
    else:
        raise RuntimeError("logged-out oEmbed did not prove AGMM author and exact title")
    thumb_out = evidence / "studio-thumbnail.jpg"
    distance = verify_thumbnail(ctx, page, video_id, args.thumbnail, thumb_out)
    return {
        "schema": "agmm-youtube-cloud-studio-public-v1", "overall": "PUBLIC_VERIFIED",
        "video_id": video_id, "post_url": url, "title": title,
        "master_sha256": actual, "source_run_id": str(args.source_run_id),
        "thumbnail_sha256": sha256(args.thumbnail), "studio_state": state,
        "oembed": {k: payload.get(k) for k in ("author_name", "title", "thumbnail_url")},
        "studio_thumbnail_mean_abs_distance": round(distance, 2),
        "verified_at": datetime.now(timezone.utc).isoformat(),
    }


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--mode", choices=("probe", "publish"), required=True)
    p.add_argument("--storage-state", type=Path, required=True)
    p.add_argument("--out", type=Path, required=True)
    p.add_argument("--evidence", type=Path, required=True)
    p.add_argument("--video", type=Path)
    p.add_argument("--thumbnail", type=Path)
    p.add_argument("--metadata", type=Path)
    p.add_argument("--approval", type=Path)
    p.add_argument("--expected-sha256", default="")
    p.add_argument("--source-run-id", default="")
    p.add_argument("--schedule-at", default="")
    args = p.parse_args()
    args.evidence.mkdir(parents=True, exist_ok=True)
    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=True, channel="chrome", args=["--disable-blink-features=AutomationControlled"])
        ctx = browser.new_context(storage_state=str(args.storage_state), viewport={"width": 1440, "height": 940}, locale="en-GB", timezone_id="Europe/London")
        page = ctx.new_page()
        try:
            page.goto(LONGFORM_TAB, wait_until="domcontentloaded", timeout=60_000)
            time.sleep(10)
            ok, detail = signed_in(page)
            page.screenshot(path=str(args.evidence / "00-session-probe.png"))
            if not ok:
                raise RuntimeError("AGMM Studio session probe failed: " + detail)
            result = {"schema": "agmm-youtube-cloud-session-v1", "overall": "SESSION_PASS", "detail": detail,
                      "checked_at": datetime.now(timezone.utc).isoformat()}
            if args.mode == "publish":
                required = (args.video, args.thumbnail, args.metadata, args.approval)
                if not all(required):
                    raise RuntimeError("publish mode is missing required files")
                result = publish(args, ctx, page, args.evidence)
            save_json(args.out, result)
            print(json.dumps({"overall": result["overall"], "video_id": result.get("video_id"), "post_url": result.get("post_url")}))
            return 0
        finally:
            ctx.close()
            browser.close()


if __name__ == "__main__":
    raise SystemExit(main())
