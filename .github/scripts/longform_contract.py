#!/usr/bin/env python3
"""The long-form YouTube contract: pure checks, no browser, no network.

Shared by the publisher (``youtube_longform_video.py``), the arming tool
(``v2/autoposter/tools/arm_film.py``) and the tests, so a rule changed here
changes everywhere at once. Every function returns problems as plain strings;
an empty list means the input passed. Each rule is pinned by a test that first
proves it can fail (tests/test_youtube_longform.py).

What a long-form post must carry (Sam, 25 Sep 2026: one film a day, each with
an excellent custom thumbnail):
  * a regular 16:9 upload, never a Short (landscape, longer than 3 minutes);
  * a title of at most 100 characters with no dash tells;
  * a description that tells the story, carries YouTube chapters (first at
    0:00, at least three, ascending, each at least 10 s), carries the audit
    link for THIS film in its first 3 lines, above YouTube's "show more" (Sam,
    29 Sep 2026; F01 and earlier ended with it, which still passes), and has no
    em or en dash, no "link in bio" and no claim that the audit is free (it is
    a paid engagement);
  * a custom thumbnail: a 1280x720 JPEG under 2 MB whose bytes are sealed;
  * "not made for kids" and an honest altered/synthetic content answer.
"""
from __future__ import annotations

import hashlib
import re
from pathlib import Path

AUDIT_LINK = ("https://agmm.co.uk/ai-constraint-audit/?utm_source=youtube"
              "&utm_campaign=v2-films&utm_content={fid}")
TITLE_LIMIT = 100
DESCRIPTION_LIMIT = 5000
THUMB_SIZE = (1280, 720)
THUMB_MAX_BYTES = 2 * 1024 * 1024
MIN_LONGFORM_SECONDS = 181.0          # a vertical upload up to 3 min is a Short; a film must never be one
MAX_LONGFORM_SECONDS = 12 * 3600.0
MIN_CHAPTERS = 3
MIN_CHAPTER_SECONDS = 10
CTA_TOP_LINES = 3                     # what YouTube shows above "show more"
CHAPTER_RE = re.compile(r"^\s*((?:\d{1,2}:)?\d{1,2}:\d{2})\s+(\S.*?)\s*$")
FID_RE = re.compile(r"^F\d{2}$")

# Upload traffic in a rehearsal. The wizard POSTs the video bytes to
# upload.youtube.com/upload/studio and the thumbnail to
# upload.youtube.com/upload/studiothumbnail (both observed 25 Sep 2026 17:05);
# the metadata save needs a video id that only a started upload creates.
# Everything below is aborted before it leaves the Mac, so a rehearsal can walk
# the whole wizard without YouTube ever holding a byte of the film.
_REHEARSAL_BLOCK = re.compile(
    r"(upload\.youtube\.com|/upload/|createvideo|metadata_update|thumbnail|video_manager|"
    r"/youtubei/v1/(?:creator/)?(?:update|set|delete|publish)\w*)", re.I)


def audit_link(fid: str) -> str:
    return AUDIT_LINK.format(fid=fid)


def audit_link_on_top(description: str, fid: str) -> bool:
    """The audit link sits in the first CTA_TOP_LINES lines and only link lines come before it: what YouTube shows
    above "show more" (a one-line story paragraph wraps to many screen lines, so prose above it does not count)."""
    lines = [ln.strip() for ln in description.splitlines() if ln.strip()]
    link = audit_link(fid)
    idx = next((i for i, ln in enumerate(lines[:CTA_TOP_LINES]) if link in ln), None)
    return idx is not None and all("http" in ln for ln in lines[:idx])


def seconds(stamp: str) -> int:
    parts = [int(p) for p in stamp.split(":")]
    total = 0
    for part in parts:
        total = total * 60 + part
    return total


def parse_chapters(description: str) -> list[dict]:
    """Every line that starts with a timestamp, in order."""
    out = []
    for line in description.splitlines():
        m = CHAPTER_RE.match(line)
        if m:
            out.append({"stamp": m.group(1), "seconds": seconds(m.group(1)), "title": m.group(2)})
    return out


def check_chapters(description: str, duration_s: float | None) -> list[str]:
    chapters = parse_chapters(description)
    problems = []
    if len(chapters) < MIN_CHAPTERS:
        problems.append(f"chapters: {len(chapters)} timestamps, YouTube needs at least {MIN_CHAPTERS}")
        return problems
    if chapters[0]["seconds"] != 0:
        problems.append(f"chapters: the first timestamp is {chapters[0]['stamp']}, YouTube needs 0:00")
    for prev, cur in zip(chapters, chapters[1:]):
        gap = cur["seconds"] - prev["seconds"]
        if gap <= 0:
            problems.append(f"chapters: {cur['stamp']} does not come after {prev['stamp']}")
        elif gap < MIN_CHAPTER_SECONDS:
            problems.append(f"chapters: {prev['stamp']} to {cur['stamp']} is {gap}s, under {MIN_CHAPTER_SECONDS}s")
    if duration_s is not None:
        last = chapters[-1]
        if last["seconds"] > duration_s - MIN_CHAPTER_SECONDS:
            problems.append(f"chapters: {last['stamp']} leaves under {MIN_CHAPTER_SECONDS}s of a "
                            f"{duration_s:.1f}s film")
    return problems


def forbidden_copy(text: str) -> list[str]:
    """The copy guards arm_ready.py applies to every short, applied to a film."""
    low = text.lower()
    hits = []
    if "—" in text:
        hits.append("em dash")
    if "–" in text:
        hits.append("en dash")
    if re.search(r"\bin (?:our |my |the )?bio\b", low):
        hits.append("'link in bio' wording (the craft standard forbids it)")
    if re.search(r"\bfree (?:ai )?(?:constraint )?audit\b", low) or re.search(r"\baudit (?:is|for) free\b", low):
        hits.append("calls the audit free (it is a paid engagement)")
    return hits


def check_title(title: str) -> list[str]:
    problems = []
    if not title.strip():
        problems.append("title: empty")
    if len(title) > TITLE_LIMIT:
        problems.append(f"title: {len(title)} characters (limit {TITLE_LIMIT})")
    if "<" in title or ">" in title:
        problems.append("title: YouTube rejects < and >")
    problems += [f"title: {h}" for h in forbidden_copy(title)]
    return problems


def check_description(description: str, fid: str, duration_s: float | None) -> list[str]:
    problems = []
    if not FID_RE.match(fid or ""):
        problems.append(f"film id {fid!r} is not F<nn>")
    text = description.strip()
    if len(text) > DESCRIPTION_LIMIT:
        problems.append(f"description: {len(text)} characters (limit {DESCRIPTION_LIMIT})")
    if "<" in text or ">" in text:
        problems.append("description: YouTube rejects < and >")
    problems += [f"description: {h}" for h in forbidden_copy(text)]
    link = audit_link(fid)
    lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
    top = audit_link_on_top(text, fid)
    if not lines or not (top or lines[-1].endswith(link)):
        problems.append(f"description: must carry the audit link {link} in the first {CTA_TOP_LINES} lines "
                        f"(above 'show more'), or must end with it")
    other_audit = [u for u in re.findall(r"https?://agmm\.co\.uk/ai-constraint-audit\S*", text) if u != link]
    if other_audit:
        problems.append(f"description: an audit link with other tracking: {other_audit[0]}")
    problems += check_chapters(text, duration_s)
    story = [ln for ln in lines if not CHAPTER_RE.match(ln) and "http" not in ln]
    if sum(len(ln) for ln in story) < 280:
        problems.append("description: under 280 characters of prose; it must tell the story, not only list chapters")
    return problems


def jpeg_size(path: Path) -> tuple[int, int] | None:
    """(width, height) from the JPEG's own SOF marker. None when it is not a JPEG."""
    data = path.read_bytes()
    if data[:2] != b"\xff\xd8":
        return None
    i = 2
    while i + 9 < len(data):
        if data[i] != 0xFF:
            i += 1
            continue
        marker = data[i + 1]
        if marker in (0xD8, 0x01) or 0xD0 <= marker <= 0xD7:
            i += 2
            continue
        length = int.from_bytes(data[i + 2:i + 4], "big")
        if marker in (0xC0, 0xC1, 0xC2, 0xC3, 0xC5, 0xC6, 0xC7, 0xC9, 0xCA, 0xCB, 0xCD, 0xCE, 0xCF):
            height = int.from_bytes(data[i + 5:i + 7], "big")
            width = int.from_bytes(data[i + 7:i + 9], "big")
            return width, height
        i += 2 + length
    return None


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def check_thumbnail(path: Path, expected_sha256: str | None = None) -> list[str]:
    if not path.is_file():
        return [f"thumbnail: missing {path}"]
    problems = []
    size = path.stat().st_size
    if size >= THUMB_MAX_BYTES:
        problems.append(f"thumbnail: {size} bytes, YouTube's limit is under 2 MB")
    dims = jpeg_size(path)
    if dims is None:
        problems.append("thumbnail: not a JPEG")
    elif dims != THUMB_SIZE:
        problems.append(f"thumbnail: {dims[0]}x{dims[1]}, must be exactly 1280x720")
    if expected_sha256 is not None:
        actual = sha256_file(path)
        if actual != expected_sha256:
            problems.append(f"thumbnail: sha256 {actual[:16]} is not the sealed {expected_sha256[:16]}")
    return problems


def check_video_shape(width: int, height: int, duration_s: float, has_audio: bool) -> list[str]:
    problems = []
    if not (width and height) or width * 9 != height * 16:
        problems.append(f"video: {width}x{height} is not 16:9")
    elif width < 1920:
        problems.append(f"video: {width}x{height} is under 1920x1080")
    if duration_s < MIN_LONGFORM_SECONDS:
        problems.append(f"video: {duration_s:.1f}s; a long-form film must run over 3 minutes (never a Short)")
    if duration_s > MAX_LONGFORM_SECONDS:
        problems.append(f"video: {duration_s:.1f}s is over YouTube's 12 hour limit")
    if not has_audio:
        problems.append("video: no audio stream")
    return problems


def check_altered_content(declared) -> list[str]:
    """The disclosure must be an explicit, reasoned answer, never a default."""
    if not isinstance(declared, dict) or not isinstance(declared.get("value"), bool):
        return ["altered_content: must be declared as {\"value\": true|false, \"reason\": ...}"]
    if len(str(declared.get("reason") or "").strip()) < 20:
        return ["altered_content: the declaration needs a reason (what is or is not synthetic)"]
    return []


def is_rehearsal_blocked(url: str, method: str) -> bool:
    """True for any request a rehearsal must never let leave the Mac."""
    if "upload.youtube.com" in url:
        return True
    return method.upper() != "GET" and bool(_REHEARSAL_BLOCK.search(url))


def video_id_from(url: str) -> str:
    m = re.search(r"(?:youtu\.be/|/shorts/|[?&]v=|/video/)([\w-]{11})", url or "")
    return m.group(1) if m else ""


def thumb_distance(a: Path, b: Path) -> float:
    """Mean absolute difference (0-255) between two images at 64x36 greyscale.

    YouTube re-encodes a custom thumbnail, so bytes never match; the picture
    does. A frame YouTube auto-picked from the film scores far higher than our
    re-encoded upload (measured in tests with a different picture).
    """
    from PIL import Image

    def small(p: Path):
        with Image.open(p) as im:
            w, h = im.size
            if h * 16 > w * 9 + w // 20:
                # hqdefault/sddefault are 4:3 with the 16:9 picture letterboxed in the middle
                keep = w * 9 // 16
                top = (h - keep) // 2
                im = im.crop((0, top, w, top + keep))
            return list(im.convert("L").resize((64, 36), Image.BILINEAR).getdata())

    x, y = small(a), small(b)
    return sum(abs(i - j) for i, j in zip(x, y)) / len(x)


THUMB_MATCH_MAX = 12.0
