"""reviewer_evidence.py (root, 30 Sep 11:50): a non-root reviewer (Hound) must SHOW its review, or the decision is refused.
Test that found it: Hound approved S02 S11 S12 S40 in 2 minutes with an identical note ('No major defects found') and no
logged review. Rule: the note cites >= 3 distinct timestamps/frames (e.g. '4.2 s', '@12s', 'frame 07'), and
~/.fleet/buzz/ladder/shadow.jsonl has a line for this ID from the last 2 hours with >= 1 checked item."""
import json, os, re, time

LADDER = os.path.expanduser("~/.fleet/buzz/ladder/shadow.jsonl")


def check(who, sid, note):
    if (who or "").lower() in ("root", "sam", "art-director", "reviewer-root"):
        return None
    refs = set(re.findall(r"(?:@\s?)?(\d{1,3}(?:\.\d+)?)\s?s\b|frame[- ]?(\d+)", note or ""))
    if len(refs) < 3:
        return "REFUSED (%s): cite >= 3 specific timestamps/frames you looked at (found %d). Look first, then decide." % (who, len(refs))
    try:
        rows = [json.loads(l) for l in open(LADDER) if l.strip()]
    except OSError:
        rows = []
    now = time.time()
    def recent(r):
        try:
            return now - time.mktime(time.strptime(str(r.get("at", ""))[:19], "%Y-%m-%dT%H:%M:%S")) < 7200
        except Exception:
            return False
    if not any(r.get("id") == sid and recent(r) and (r.get("flags") is not None or r.get("checked")) for r in rows):
        return "REFUSED (%s): no review of %s logged in %s in the last 2 h. Log your frame-by-frame review there first." % (who, sid, LADDER)
    return None
