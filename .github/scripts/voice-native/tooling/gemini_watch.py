#!/usr/bin/env python3
"""Have Gemini watch AND hear a video (local mp4 <=18MB or a YouTube URL) and answer a prompt.
Usage: gemini_watch.py <video.mp4|youtube-url> <prompt-file-or-text> [--model M] [--out file] [--json]
Keys are read from ~/alfred/.env and never printed. Vertex (Google credit) when GEMINI_VERTEX_PROJECT is set."""
import base64, json, os, sys, time, urllib.request, urllib.error

def env():
    e = {}
    for line in open(os.path.expanduser("~/alfred/.env"), encoding="utf-8", errors="ignore"):
        line = line.strip().replace("\r", "")
        if "=" in line and not line.startswith("#"):
            k, v = line.split("=", 1)
            e[k.strip()] = v.strip().strip('"').strip("'")
    return e

def main():
    a = sys.argv[1:]
    model = "gemini-2.5-pro"; out = None; want_json = False
    if "--model" in a: i = a.index("--model"); model = a[i+1]; del a[i:i+2]
    if "--out" in a: i = a.index("--out"); out = a[i+1]; del a[i:i+2]
    if "--json" in a: a.remove("--json"); want_json = True
    src, prompt = a[0], a[1]
    if os.environ.get("FLEET_NO_LOCAL_MEDIA") == "1" and not src.startswith("https://"):
        sys.exit("FLEET_NO_LOCAL_MEDIA=1: only remote HTTPS video inputs are allowed")
    if os.path.exists(prompt): prompt = open(prompt).read()
    e = env()
    # Root, 24 Sep 21:15: the Vertex project's free-trial credit is used up and Vertex now bills Adam's card
    # (console: "You are now incurring charges ... as of September 24, 2026"). Sam: "im not paying anything".
    # Default = AI Studio with GEMINI_KEY_B (only key that answers; 2.5 Pro is no longer offered there, so flash).
    # Set GEMINI_WATCH_VERTEX=1 only if someone explicitly accepts paid Vertex.
    use_vertex = os.environ.get("GEMINI_WATCH_VERTEX") == "1"
    free_only = os.environ.get("FLEET_FREE_ONLY", "1") == "1"
    if free_only and use_vertex:
        sys.exit("FLEET_FREE_ONLY=1: paid Vertex is refused")
    proj = e.get("GEMINI_VERTEX_PROJECT") if use_vertex else None
    base = ("https://aiplatform.googleapis.com/v1/projects/%s/locations/global/publishers/google/models" % proj) if proj \
        else "https://generativelanguage.googleapis.com/v1beta/models"
    # GEMINI_WATCH_KEY (critics subagent, 28 Sep 23:00): the NAME of the ~/alfred/.env key to use on AI Studio free,
    # e.g. GEMINI_API_KEY_OLD_ACCOUNT, a second free project with its own daily quota (gate check 9 uses it when
    # KEY_B is out). Never GEMINI_API_KEY: that is the prepay project. Unset = GEMINI_KEY_B, as before.
    wkey = os.environ.get("GEMINI_WATCH_KEY", "").strip()
    if free_only and wkey not in ("", "GEMINI_KEY_B", "GEMINI_API_KEY_OLD_ACCOUNT"):
        sys.exit("FLEET_FREE_ONLY=1: unapproved key name is refused")
    if wkey and not proj:
        if wkey == "GEMINI_API_KEY" or not e.get(wkey):
            sys.exit("GEMINI_WATCH_KEY=%s refused: missing from ~/alfred/.env or the prepay project key" % wkey)
    api_key = e["GEMINI_API_KEY"] if proj else e[wkey or "GEMINI_KEY_B"]
    if not proj and model == "gemini-2.5-pro":
        model = "gemini-2.5-flash"
    if src.startswith("http"):
        media = {"fileData": {"fileUri": src, "mimeType": "video/*"}}
    else:
        size = os.path.getsize(src)
        if size > 18_000_000: sys.exit("file >18MB: downscale first, SHORT side 720 (vertical: ffmpeg -vf scale=720:-2 -b:v 1800k -x264-params threads=2; never scale=-2:480, which makes a vertical short 270x480)")
        media = {"inlineData": {"mimeType": "video/mp4", "data": base64.b64encode(open(src, "rb").read()).decode()}}
    gen = {"temperature": 0.2, "maxOutputTokens": 16000}
    if want_json: gen["responseMimeType"] = "application/json"
    body = {"contents": [{"role": "user", "parts": [media, {"text": prompt}]}], "generationConfig": gen}
    # Quota fallback (root, 24 Sep): gemini-2.5-pro hit a persistent 429 on the Vertex project while
    # flash stayed available. After retries on pro, fall back to flash and record it in the receipt.
    models = [model] + (["gemini-2.5-flash"] if model == "gemini-2.5-pro" else [])
    if not proj:
        # Free tier quotas are PER MODEL PER DAY (quotaId GenerateRequestsPerDayPerProjectPerModel-FreeTier), so rotate
        # through the free video+audio models; a model that 429s on its daily quota is skipped until the Pacific-day reset.
        FREE = ["gemini-3.8-flash", "gemini-3.7-flash", "gemini-3.6-flash", "gemini-3.5-flash", "gemini-3-flash-preview",
                "gemini-2.5-flash", "gemini-omni-1.1-flash", "gemini-3.5-flash-lite", "gemini-2.5-flash-lite"]
        if free_only and model not in FREE:
            sys.exit("FLEET_FREE_ONLY=1: unapproved model is refused")
        models = [model] + [m for m in FREE if m != model] if model not in ("gemini-2.5-flash",) else FREE
        # per key: a model that is out on KEY_B is not out on the second project
        dayf = os.path.expanduser("~/.cache/gemini_free_exhausted%s.json" % (("." + wkey) if wkey else ""))
        pday = time.strftime("%Y-%m-%d", time.gmtime(time.time() - 7 * 3600))   # Pacific day, when free quotas reset
        try:
            dead = json.load(open(dayf))
        except Exception:
            dead = {}
        dead = {k: v for k, v in dead.items() if v == pday}
        models = [m for m in models if m not in dead] or models
    flag = os.path.expanduser("~/.cache/gemini_pro_quota_exhausted")
    if model == "gemini-2.5-pro" and os.path.exists(flag) and time.time() - os.path.getmtime(flag) < 1800:
        models = ["gemini-2.5-flash"]  # pro 429ed in the last 30 min; skip the slow retries
    d = None; fell_back = False
    for mi, m in enumerate(models):
        req = urllib.request.Request("%s/%s:generateContent" % (base, m), data=json.dumps(body).encode(),
            headers={"Content-Type": "application/json", "x-goog-api-key": api_key})
        for attempt in range(4):
            try:
                with urllib.request.urlopen(req, timeout=600) as r:
                    d = json.loads(r.read()); break
            except urllib.error.HTTPError as ex:
                msg = ex.read().decode()[:400]
                if ex.code == 429 and not proj and "PerDay" in msg:   # checked before the sleep-retry: a daily cap never clears in 60 s
                    dead[m] = pday; os.makedirs(os.path.dirname(dayf), exist_ok=True); json.dump(dead, open(dayf, "w"))
                    print("[gemini_watch] %s free daily quota used up, trying the next model" % m, file=sys.stderr)
                    break
                # root 29 Sep: a 503 "high demand" on one model used to cost 20+40+60 s before moving on, so gates timed out
                # before reaching flash-lite, which still had quota. With a next model to try, move on after one short retry.
                if ex.code == 503 and not proj and mi + 1 < len(models) and attempt >= 1:
                    print("[gemini_watch] %s busy (503), trying the next model" % m, file=sys.stderr)
                    break
                if ex.code in (429, 500, 503) and attempt < 3: time.sleep((5 if ex.code == 503 and mi + 1 < len(models) else 20) * (attempt + 1)); continue
                if ex.code in (404, 503) and not proj and mi + 1 < len(models):
                    print("[gemini_watch] %s unavailable (%s), trying the next model" % (m, ex.code), file=sys.stderr)
                    break
                if ex.code == 429 and mi + 1 < len(models):
                    print("[gemini_watch] %s quota exhausted, falling back to %s" % (m, models[mi + 1]), file=sys.stderr)
                    os.makedirs(os.path.dirname(flag), exist_ok=True); open(flag, "w").write(str(time.time()))
                    break
                sys.exit("HTTP %s: %s" % (ex.code, msg))
        if d is not None:
            model = m; fell_back = (m != models[0]) or (models == ["gemini-2.5-flash"] and m != model); break
    if d is None:
        sys.exit("every free Gemini model is out of quota or unavailable today: %s" % models)
    text = "".join(p.get("text", "") for p in d["candidates"][0]["content"]["parts"])
    u = d.get("usageMetadata", {})
    receipt = {"model": d.get("modelVersion", model), "fell_back_to_flash": fell_back, "backend": "vertex" if proj else "ai-studio-free", "key": None if proj else (wkey or "GEMINI_KEY_B"), "src": src, "prompt_tokens": u.get("promptTokenCount"), "out_tokens": u.get("candidatesTokenCount")}
    if out:
        open(out, "w").write(text); open(out + ".receipt.json", "w").write(json.dumps(receipt, indent=1))
    print(text); print("\n[receipt] " + json.dumps(receipt), file=sys.stderr)

if __name__ == "__main__":
    main()
