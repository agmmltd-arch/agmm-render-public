#!/usr/bin/env python3
"""Caption lint: the same rules the scripts obey, applied to social copy.

Rules (a hit on any FAIL rule fails the caption):
  * em dash, en dash, or " - " used as a dash                       (gate.py check 1)
  * stamp words: fictional, illustrative, placeholder ...           (gate.py STAMP_PHRASES)
  * AI-tell vocabulary, bloated verbs, dead openings/transitions     (gate.py AI_TELL_PHRASES)
  * "it's not X, it's Y" negative parallelism                        (gate.py NEG_PARALLELISM_RE)
  * an-anti-ai-writing extras: banned metaphor verbs, engagement bait, hype
  * serialised data (a dict/JSON/path pasted as a caption)          (video_package.looks_like_serialised_data)
  * platform length limits                                           (video_package.CAPTION_LIMITS)
  * every numeral in the caption must appear in the short's own script file (facts only as in the script)

The vocabulary is read from gate.py at run time (AST, no import side effects), so the caption lint and the
video gate can never drift apart. Matching is on word boundaries: gate.py matches substrings, which makes
"Marks and Spencer" hit "marks a" and "Foster" hit "foster". That false positive is reported in AUDIT.md;
captions here say "M&S" anyway.
"""
from __future__ import annotations

import ast
import re
from pathlib import Path

HERE = Path(__file__).resolve().parent
GATE = HERE.parents[1] / "qa" / "gate.py"

CAPTION_LIMITS = {"instagram": 2200, "facebook": 63206, "linkedin": 3000, "tiktok": 2200, "youtube": 5000}
YOUTUBE_TITLE_LIMIT = 100


def _gate_lists() -> dict:
    tree = ast.parse(GATE.read_text(encoding="utf-8"))
    wanted = {"STAMP_PHRASES", "AI_TELL_PHRASES"}
    found = {}
    for node in tree.body:
        if isinstance(node, ast.Assign) and len(node.targets) == 1 and isinstance(node.targets[0], ast.Name):
            name = node.targets[0].id
            if name in wanted:
                value = node.value
                # AI_TELL_PHRASES = sorted(set([...]))
                while isinstance(value, ast.Call):
                    value = value.args[0]
                found[name] = list(ast.literal_eval(value))
    missing = wanted - set(found)
    if missing:
        raise RuntimeError(f"could not read {missing} from {GATE}; refusing to lint with a partial list")
    return found


_LISTS = _gate_lists()
STAMP_PHRASES = _LISTS["STAMP_PHRASES"]
AI_TELL_PHRASES = _LISTS["AI_TELL_PHRASES"]
SKILL_EXTRAS = [
    # an-anti-ai-writing: banned metaphor verbs, bait, hype, dead openings not in gate.py
    "baked in", "bolted on", "bolted onto", "woven", "distilled", "unpacked", "crystallized", "crystallised",
    "amplified", "sculpted", "let that sink in", "read that again", "this changes everything",
    "future-proof", "10x", "in a world where", "in this post", "north star", "flywheel", "game changer",
]
NEG_PARALLELISM_RE = re.compile(r"\bit'?s not (?:just )?.{0,80}?,?\s*(?:it'?s|but)\b", re.I)
DASH_SPACE_RE = re.compile(r"(?<!-) - (?!-)")
NUM_RE = re.compile(r"(?<![A-Za-z#])\d[\d,]*(?:\.\d+)?")
URL_RE = re.compile(r"https?://\S+")
HASHTAG_RE = re.compile(r"#\w+")


def _phrase_re(phrase: str) -> re.Pattern:
    return re.compile(r"(?<![\w'])" + re.escape(phrase) + r"(?![\w])", re.I)


_PATTERNS = [("stamp", p, _phrase_re(p)) for p in STAMP_PHRASES] + \
            [("ai-tell", p, _phrase_re(p)) for p in AI_TELL_PHRASES] + \
            [("ai-tell", p, _phrase_re(p)) for p in SKILL_EXTRAS]


def looks_like_serialised_data(text: str) -> bool:
    t = text.lstrip()
    return t[:1] in "{[" or t.startswith("/Users/") or "'sha256':" in t or '"sha256":' in t


def lint_text(text: str) -> list[dict]:
    hits = []
    if "—" in text:
        hits.append({"type": "dash", "hit": "em dash"})
    if "–" in text:
        hits.append({"type": "dash", "hit": "en dash"})
    if DASH_SPACE_RE.search(text):
        hits.append({"type": "dash", "hit": "' - ' used as a dash"})
    prose = URL_RE.sub(" ", text)
    for kind, phrase, rx in _PATTERNS:
        if rx.search(prose):
            hits.append({"type": kind, "hit": phrase})
    if NEG_PARALLELISM_RE.search(prose):
        hits.append({"type": "ai-tell", "hit": "negative parallelism (it's not X, it's Y)"})
    if looks_like_serialised_data(text):
        hits.append({"type": "serialised", "hit": text[:60]})
    return hits


def strip_credits(text: str, credit_text) -> str:
    """Remove the credit text: one string (the filled credit) or a list of credit lines (credits.credit_lines)."""
    for c in ([credit_text] if isinstance(credit_text, str) else list(credit_text or [])):
        if c:
            text = text.replace(c, " ")
    return text


def numbers_outside_script(text: str, allowed: set[str], credit_text="") -> list[str]:
    """Numerals in the caption that do not appear anywhere in the script file.

    URLs, hashtags and the licensed-music credit line are excluded: they are not claims.
    """
    prose = URL_RE.sub(" ", strip_credits(text, credit_text))
    prose = HASHTAG_RE.sub(" ", prose)
    bad = []
    for raw in NUM_RE.findall(prose):
        n = raw.replace(",", "").rstrip(".")
        if n not in allowed:
            bad.append(raw)
    return bad


def lint_caption(platform: str, text: str, allowed_numbers: set[str], credit_text="",
                 title: str | None = None) -> dict:
    problems = []
    # The licensed-music credit is attribution (music.json `credit` or `credit_compact`), not our prose; Shane Ivers'
    # legacy credits contain " - " by the licensor's own wording. credit_text may be a list of credit lines. Lint the rest.
    prose_only = strip_credits(text, credit_text)
    for h in lint_text(prose_only):
        problems.append(f"{h['type']}: {h['hit']}")
    if len(text) > CAPTION_LIMITS[platform]:
        problems.append(f"length {len(text)} > {platform} limit {CAPTION_LIMITS[platform]}")
    for n in numbers_outside_script(text, allowed_numbers, credit_text):
        problems.append(f"number not in script: {n}")
    tags = HASHTAG_RE.findall(URL_RE.sub(" ", text))
    if not 3 <= len(tags) <= 5:
        problems.append(f"{len(tags)} hashtags (want 3 to 5)")
    if title is not None:
        for h in lint_text(title):
            problems.append(f"title {h['type']}: {h['hit']}")
        if len(title) > YOUTUBE_TITLE_LIMIT:
            problems.append(f"title length {len(title)} > {YOUTUBE_TITLE_LIMIT}")
        for n in numbers_outside_script(title, allowed_numbers):
            problems.append(f"title number not in script: {n}")
    return {"ok": not problems, "problems": problems, "characters": len(text), "hashtags": tags}


if __name__ == "__main__":
    import json
    import sys
    sample = sys.stdin.read()
    print(json.dumps(lint_text(sample), indent=1))
