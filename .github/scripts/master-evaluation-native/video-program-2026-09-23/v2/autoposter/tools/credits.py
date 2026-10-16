#!/usr/bin/env python3
"""Compact attribution lines for captions and film descriptions, and the check that the credit names the bed.

Sam, 29 Sep 2026: the descriptions were too cluttered; do not credit the music at such length. Every bed is CC BY 4.0
(Kevin MacLeod / incompetech, Shane Ivers / Silverman Sound), so a credit is still legally required, but CC BY 4.0 asks
only for a reasonable one: title, author, source and licence. No ISRC page, no licence URL, no "excerpted and mixed".

    one track     Music: "Cold Funk" by Kevin MacLeod (incompetech.com), CC BY 4.0
    one artist,   Music by Kevin MacLeod (incompetech.com), CC BY 4.0: Oppressive Gloom, Interloper, Dreamlike
    many tracks
    a photo       Photo: <title>, <author>, Wikimedia Commons, CC BY-SA 4.0

The long licensor strings stay in sound/music.json `credit` (history, and what the 25-29 Sep posts carry);
`credit_compact` is what new captions get. music_credit_problems() accepts either form, so captions staged before this
change still validate, and it FAILS when a credited track is not a bed in the mix or a bed in the mix is not credited.
"""
from __future__ import annotations

import re
from urllib.parse import urlparse

LICENCE_RE = re.compile(r"\bCC BY(?:-SA)? \d\.\d\b")
# Music: "Title" by Artist (source) ...   (the compact single form and the legacy incompetech form)
_QUOTED = re.compile(r'^\s*Music:\s*"(?P<title>[^"]+)"\s+by\s+(?P<artist>[^()]+?)\s*\((?P<src>[^)]+)\)')
# Music by Artist (source), CC BY 4.0: Title, Title, Title   (the compact multi-track form)
_MULTI = re.compile(r"^\s*Music by\s+(?P<artist>[^()]+?)\s*\((?P<src>[^)]+)\),\s*(?P<lic>CC BY[^:]*):\s*(?P<titles>.+?)\s*$")
# Music: Title by Artist - https://...   (the legacy Silverman Sound form)
_LEGACY_DASH = re.compile(r"^\s*Music:\s*(?P<title>[^\"]+?)\s+by\s+(?P<artist>.+?)\s+-\s+(?P<src>\S+)")
_PHOTO = re.compile(r"^\s*(?:Photo|Photograph|Thumbnail (?:\w+ )?photograph)\b[^:]*:", re.I)


def source_host(item: dict) -> str:
    for key in ("source_official_page", "source_url"):
        host = urlparse(str(item.get(key) or "")).hostname or ""
        if host:
            return host[4:] if host.startswith("www.") else host
    return ""


def licence_of(item: dict) -> str:
    return str(item.get("license") or item.get("licence") or "").strip()


def derive_compact(item: dict) -> str:
    """The one-track line, built from the library's own fields."""
    return f'Music: "{item["title"]}" by {item["artist"]} ({source_host(item)}), {licence_of(item)}'


def compact_line(item: dict) -> str:
    return str(item.get("credit_compact") or derive_compact(item))


def compact_music_credit(beds: list[str], catalogue: dict) -> str:
    """One line per artist: the single form for one track, the multi form for several by the same artist."""
    groups: dict[tuple, list[dict]] = {}
    for b in dict.fromkeys(beds or []):
        if b in catalogue:
            it = catalogue[b]
            groups.setdefault((it["artist"], source_host(it), licence_of(it)), []).append(it)
    lines = []
    for (artist, host, lic), items in groups.items():
        if len(items) == 1:
            lines.append(compact_line(items[0]))
        else:
            lines.append(f"Music by {artist} ({host}), {lic}: " + ", ".join(i["title"] for i in items))
    return "\n".join(lines)


def photo_credit(title: str, author: str, licence: str = "CC BY-SA 4.0", source: str = "Wikimedia Commons") -> str:
    return f"Photo: {title}, {author}, {source}, {licence}"


def _norm(s: str) -> str:
    return re.sub(r"\s+", " ", str(s)).strip().casefold()


def credited_tracks(text: str) -> list[dict]:
    """Every track a caption credits, from any accepted credit form: [{title, artist, source, licence, line}]."""
    out = []
    for line in text.splitlines():
        m = _MULTI.match(line)
        if m:
            lic = LICENCE_RE.search(m.group("lic"))
            for t in m.group("titles").split(","):
                if t.strip():
                    out.append({"title": t.strip().rstrip("."), "artist": m.group("artist").strip(),
                                "source": m.group("src").strip(), "licence": lic.group(0) if lic else "", "line": line})
            continue
        m = _QUOTED.match(line) or _LEGACY_DASH.match(line)
        if m:
            lic = LICENCE_RE.search(line)
            out.append({"title": m.group("title").strip(), "artist": m.group("artist").strip(),
                        "source": m.group("src").strip(), "licence": lic.group(0) if lic else "", "line": line})
    return out


def credit_lines(text: str) -> list[str]:
    """The attribution lines (music or photo) in a caption: excluded from the prose lint and the number check,
    because titles, handles and licence versions are not our claims."""
    return [ln for ln in text.splitlines() if ln.strip() and (_QUOTED.match(ln) or _MULTI.match(ln)
                                                              or _LEGACY_DASH.match(ln) or _PHOTO.match(ln))]


def music_credit_problems(text: str, beds: list[str], catalogue: dict) -> list[str]:
    """Empty when the caption credits exactly the beds in the mix: every CC BY bed named with its author, its source and
    its licence, and no track credited that is not a bed. Compact and legacy forms both count."""
    problems = []
    credited = credited_tracks(text)
    got = {(_norm(c["title"]), _norm(c["artist"])): c for c in credited}
    want = {}
    for b in dict.fromkeys(beds or []):
        if b not in catalogue:
            continue
        it = catalogue[b]
        key = (_norm(it["title"]), _norm(it["artist"]))
        want[key] = b
        if "CC BY" not in licence_of(it):
            continue
        c = got.get(key)
        if c is None:
            problems.append(f"bed {b} (\"{it['title']}\" by {it['artist']}) is in the mix but not credited")
            continue
        lic = licence_of(it)
        if lic and c["licence"] != lic:
            problems.append(f"credit for \"{it['title']}\" does not name the licence {lic}")
        host = source_host(it)
        if host and host.casefold() not in c["line"].casefold():
            problems.append(f"credit for \"{it['title']}\" does not name the source {host}")
    for key, c in got.items():
        if key not in want:
            problems.append(f"credits \"{c['title']}\" by {c['artist']}, which is not a bed in the mix "
                            f"(beds: {', '.join(want.values()) or 'none recorded'})")
    return problems


def render_caption(caption: str, beds: list[str], catalogue: dict, placeholder: str = "{music_credit}") -> str:
    """Fill the {music_credit} placeholder with the compact credit for the beds the build recorded."""
    credit = compact_music_credit(beds, catalogue)
    return caption.replace(placeholder, credit) if credit else caption


if __name__ == "__main__":
    import json
    import sys
    from pathlib import Path
    cat = {i["id"]: i for i in json.loads((Path(__file__).resolve().parents[2] / "sound" / "music.json")
                                          .read_text(encoding="utf-8"))["items"]}
    print(compact_music_credit(sys.argv[1:] or ["cold-funk"], cat))
