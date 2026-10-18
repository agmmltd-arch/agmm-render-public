"""Exact original produce.storyboard_guard function, extracted without change.

The full native produce.py contains private operator identifiers and imports
unrelated gate/render owners. This isolated original guard is the only function
this hosted package adapter consumes. Native produce.py is never modified.
"""
import json,os,sys
KIT=os.path.dirname(os.path.abspath(__file__))

def storyboard_guard(ID):
    """25 Sep 02:25: no render without an art-director-approved storyboard (tools/storyboard.py).
    25 Sep 08:20 (the inspector found it): the guard ran only on the codespace path, so a local or actions render
    walked round it; it now runs in stage_dispatch for every mode. The skip switch needs a reviewer too, and an
    approval covers the spec it saw: a spec or scenes change after approval needs a new one (C08 was changed two
    minutes after approval on 25 Sep and only the art director's own eye caught it)."""
    sys.path.insert(0, os.path.join(KIT, "tools"))
    import storyboard as sb
    rp = os.path.join(KIT, "registry", "storyboards", ID + ".json")
    rec = json.load(open(rp)) if os.path.exists(rp) else {}
    state = rec.get("state")
    if os.environ.get("AGMM_SKIP_STORYBOARD") == "1":
        if os.environ.get("AGMM_REVIEWER") != "1":
            sys.exit("STORYBOARD GUARD: AGMM_SKIP_STORYBOARD needs AGMM_REVIEWER=1 as well; writers cannot skip the art director.")
        print("STORYBOARD GUARD skipped by a reviewer for %s" % ID, file=sys.stderr)
        return
    if state != "approved":
        sys.exit("STORYBOARD GUARD: %s has no approved storyboard (state %r). Run `python3 tools/storyboard.py submit %s` and wait for approval." % (ID, state, ID))
    want = rec.get("approved_hash")
    if want:
        now = sb.spec_hash(ID)
        if now != want and getattr(sb, "spec_hash_legacy", lambda i: None)(ID) == want:
            now = want   # approved under the pre-28 Sep hash (archives counted); unchanged since
        if now != want:
            sys.exit("STORYBOARD GUARD: %s changed since its storyboard was approved (spec/scenes hash %s, approved %s). Resubmit: `python3 tools/storyboard.py submit %s`." % (ID, now[:12], want[:12], ID))
    else:
        print("STORYBOARD GUARD: %s approval predates hash tracking (approved before 25 Sep 08:20); allowed, resubmit on any change" % ID, file=sys.stderr)
