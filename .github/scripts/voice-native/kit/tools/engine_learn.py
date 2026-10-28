#!/usr/bin/env python3
"""engine_learn.py: the free engine learns from what posted shorts measured (26 Oct 2026, ENGINE-LEARN). Deterministic: no LLM, no network, no writes outside the files named below.

  python3 engine_learn.py                 daily: join measured results to creative choices, write kit/registry/engine-weights.json
  python3 engine_learn.py --weekly        also write the lesson candidates (Mondays only unless --weekly is passed) into kit/CREATIVE-SCHOOL-candidates.md
                                          and kit/registry/strategy-v3-proposed.json (PROPOSED threshold changes; strategy-v3.json is never edited here)
  python3 engine_learn.py --dry-run       compute and print, write nothing
  python3 engine_learn.py --selftest      synthetic data: a better arm gains weight, the exploration floor and min-n gate hold, a null produces no lesson

THE JOIN. One unit = one FILM (a short posted on several platforms counts once). Per post (shorts, age >= 1 day, >= 30 views) the metric is divided by that
platform's own median over all posted shorts (so 1.0 = a typical short on that platform; YouTube, TikTok and Facebook publish a 3 s hold curve, Instagram and
LinkedIn do not), then averaged over the film's platforms. Metrics: rel_hold3 (the objective that drives the weights), rel_watch (avg watch / duration),
rel_shares and rel_comments (per 1k views). Choice dimensions: format, world_family, ground (light|mid|dark), swatch, hook_type, beat2_artefact, you_by_3s,
brand_recognition, length_bucket, ending_type, loop_close. Declared arms (concept.json craft.experiment) win; older makers' shorts fall back to the tracker's
derived labels (experiments.film_table, reused, not copied). format / swatch exist only for engine-built shorts; world_family and ground exist for every concept.json.

THE WEIGHTS (Thompson sampling). Per dimension, per arm: normal posterior of the mean rel_hold3, prior = the grand mean with 3 pseudo-films, variance = the
dimension's pooled film variance. 4,000 posterior draws give P(arm is best). An arm moves off the uniform share only when n >= MIN_N_WEIGHT films; a dimension is
ACTIVE only when >= 2 arms qualify (until then format_engine keeps its rule defaults). Qualifying arms split their uniform mass as EXPLORATION/|E| + (1-EXPLORATION)*P(best),
so every qualifying arm keeps at least EXPLORATION/|E| of its mass (EXPLORATION = 0.25 >= the required 0.20) and the chooser in format_engine re-applies a 0.20 floor
over the options that are valid for the story at hand. Evidence (n, mean, 90% interval, effect against the films on other arms) is written next to every weight.

THE LESSONS (weekly). An arm is a candidate lesson only when it has n >= 10 films, the other films are n >= 10 too, and the 90% bootstrap interval of its effect on
rel_hold3 (arm minus the rest) excludes zero. Root reads kit/CREATIVE-SCHOOL-candidates.md; the numbers are code, nothing here asks a model.
"""
import argparse, datetime, hashlib, json, math, os, random, statistics, sys, tempfile, time

HERE = os.path.dirname(os.path.abspath(__file__))
KIT = os.path.dirname(HERE)
V2 = os.path.dirname(KIT)
AN = os.path.join(V2, "autoposter", "analytics")
REG = os.path.join(KIT, "registry")
WEIGHTS = os.path.join(REG, "engine-weights.json")
PROPOSED = os.path.join(REG, "strategy-v3-proposed.json")
STRATEGY = os.path.join(REG, "strategy-v3.json")
CANDIDATES = os.path.join(KIT, "CREATIVE-SCHOOL-candidates.md")
MARK0, MARK1 = "<!-- engine-learn:start -->", "<!-- engine-learn:end -->"

MIN_N_WEIGHT = 8        # films with a measured rel_hold3 before an arm's weight leaves uniform
MIN_N_LESSON = 10       # strategy v3 "Experiments": n >= 10 per arm
EXPLORATION = 0.25      # share of every qualifying arm's mass that stays uniform (>= the 0.20 the brief requires)
CHOOSE_FLOOR = 0.20     # format_engine re-applies this over the valid options at pick time
DRAWS = 4000
PRIOR_K = 3.0
BOOT = 2000
CI = 90
MIN_VIEWS, MIN_AGE_D = 30, 1.0
REL_CAP = 5.0
DIMS = ("format", "world_family", "ground", "swatch", "hook_type", "beat2_artefact", "you_by_3s", "brand_recognition", "length_bucket", "ending_type", "loop_close")
ENGINE_APPLIED = ("format", "world_family", "ground", "swatch")       # dimensions format_engine samples; the rest are evidence for writers and the weekly lessons
# a dimension's numeric strategy-v3 threshold, when it has one: arm -> proposed value
THRESHOLD_FOR = {"length_bucket": ("length_warn_over_s", {"<35": 35, "35-50": 50})}
METRICS = ("rel_hold3", "rel_watch", "rel_shares", "rel_comments")


def jload(p, d=None):
    try:
        with open(p, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return d


def atomic_write(path, text):
    d = os.path.dirname(path)
    fd, tmp = tempfile.mkstemp(prefix=os.path.basename(path) + ".", suffix=".tmp", dir=d)
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        f.write(text)
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp, path)


def seed_of(*parts):
    return int(hashlib.sha256("|".join(str(p) for p in parts).encode()).hexdigest()[:12], 16)


# ================================================================================================ the chooser (used by format_engine; stdlib only)
def load_weights(path=None):
    w = jload(path or WEIGHTS, None)
    return w if isinstance(w, dict) and isinstance(w.get("dimensions"), dict) else None


def weights_ref(w):
    """what a concept.json records so a result stays attributable to the weights that shaped it"""
    if not w:
        return None
    return {"file": "kit/registry/engine-weights.json", "generated_at": w.get("generated_at"), "sha1": w.get("sha1")}


def choose(weights, dim, options, default, seed):
    """Pick one of `options` (the choices that are VALID for this story; the caller owns validity). -> (choice, record).
    No weights / dimension not active / a single option -> `default`, recorded as such. Active -> sample from the file's probabilities restricted to the
    valid options, re-floored so every valid option keeps at least CHOOSE_FLOOR/len(options) (exploration never dies)."""
    options = list(options)
    rec = {"dim": dim, "options": options, "default": default}
    dd = ((weights or {}).get("dimensions") or {}).get(dim) or {}
    if len(options) <= 1:
        rec.update(source="forced" if options else "none", chosen=options[0] if options else default)
        return rec["chosen"], rec
    if not dd.get("active"):
        rec.update(source="default (dimension not active: fewer than 2 arms with n >= %d)" % MIN_N_WEIGHT, chosen=default)
        return default, rec
    probs = dd.get("probs") or {}
    base = 1.0 / len(options)
    raw = [max(0.0, float(probs.get(o, base))) for o in options]
    tot = sum(raw) or 1.0
    p = [CHOOSE_FLOOR / len(options) + (1 - CHOOSE_FLOOR) * r / tot for r in raw]
    u = random.Random(seed_of("choose", dim, seed, weights.get("generated_at"))).random() * sum(p)
    acc, pick = 0.0, options[-1]
    for o, pi in zip(options, p):
        acc += pi
        if u < acc:
            pick = o
            break
    rec.update(source="weights", chosen=pick, probs={o: round(pi / sum(p), 4) for o, pi in zip(options, p)})
    return pick, rec


# ================================================================================================ statistics
def mean_sd(v):
    n = len(v)
    m = sum(v) / n if n else None
    sd = statistics.pstdev(v) * math.sqrt(n / (n - 1.0)) if n > 1 else None
    return m, sd


def boot_diff(a, b, key):
    """mean(a) - mean(b), bootstrap 90% percentile interval, seeded from the key so reruns agree"""
    rng = random.Random(seed_of("boot", key))
    ds = []
    for _ in range(BOOT):
        ra = sum(a[rng.randrange(len(a))] for _ in a) / len(a)
        rb = sum(b[rng.randrange(len(b))] for _ in b) / len(b)
        ds.append(ra - rb)
    ds.sort()
    lo, hi = ds[int(BOOT * (100 - CI) / 200.0)], ds[int(BOOT * (1 - (100 - CI) / 200.0)) - 1]
    return sum(a) / len(a) - sum(b) / len(b), lo, hi


def boot_mean_ci(v, key):
    rng = random.Random(seed_of("bootm", key))
    ms = sorted(sum(v[rng.randrange(len(v))] for _ in v) / len(v) for _ in range(BOOT))
    return ms[int(BOOT * (100 - CI) / 200.0)], ms[int(BOOT * (1 - (100 - CI) / 200.0)) - 1]


def arm_stats(vals_by_arm_metric, films_by_arm, dim, all_vals_hold):
    """vals_by_arm_metric: {arm: {metric: {film: value}}} -> evidence dict per arm"""
    ev = {}
    for arm, md in vals_by_arm_metric.items():
        e = {"films": len(films_by_arm[arm])}
        for met in METRICS:
            v = list(md.get(met, {}).values())
            if not v:
                e[met] = {"n": 0}
                continue
            m, sd = mean_sd(v)
            s = {"n": len(v), "mean": round(m, 4)}
            if len(v) >= 3:
                lo, hi = boot_mean_ci(v, "%s|%s|%s" % (dim, arm, met))
                s["ci90"] = [round(lo, 4), round(hi, 4)]
            # effect against the films labelled with a DIFFERENT arm of this same dimension (never against films that lack the label)
            rest = [x for a2, md2 in vals_by_arm_metric.items() if a2 != arm for x in md2.get(met, {}).values()]
            if len(v) >= 3 and len(rest) >= 3:
                d, lo, hi = boot_diff(v, rest, "%s|%s|%s|eff" % (dim, arm, met))
                s["effect_vs_rest"] = {"diff": round(d, 4), "ci90": [round(lo, 4), round(hi, 4)], "n_rest": len(rest), "excludes_zero": bool(lo > 0 or hi < 0)}
            e[met] = s
        ev[arm] = e
    return ev


def thompson(eligible, rng_seed, mu0, sigma2):
    """eligible: {arm: (n, mean)} -> {arm: P(best)} by DRAWS posterior draws; normal-normal with PRIOR_K pseudo-films at the grand mean mu0"""
    rng = random.Random(rng_seed)
    post = {a: ((PRIOR_K * mu0 + n * m) / (PRIOR_K + n), math.sqrt(sigma2 / (PRIOR_K + n))) for a, (n, m) in eligible.items()}
    wins = {a: 0 for a in eligible}
    for _ in range(DRAWS):
        best = max(post, key=lambda a: rng.gauss(*post[a]))
        wins[best] += 1
    return {a: wins[a] / float(DRAWS) for a in wins}, {a: {"post_mean": round(m, 4), "post_sd": round(s, 4)} for a, (m, s) in post.items()}


def dimension_weights(dim, vals_hold, films_by_arm, ev, engine_options, grand, sigma2):
    arms = sorted(films_by_arm)
    for o in engine_options or []:
        if o not in arms:
            arms.append(o)
    K = len(arms)
    n_of = {a: ev.get(a, {}).get("rel_hold3", {}).get("n", 0) for a in arms}
    elig = {a: (n_of[a], ev[a]["rel_hold3"]["mean"]) for a in arms if n_of[a] >= MIN_N_WEIGHT}
    out = {"arms": arms, "min_n": MIN_N_WEIGHT, "exploration": EXPLORATION, "objective": "rel_hold3 (3 s hold / the platform's median, mean over the film's platforms)",
           "engine_options": engine_options or [], "applied_by_format_engine": dim in ENGINE_APPLIED, "active": len(elig) >= 2}
    probs = {a: 1.0 / K for a in arms}
    if out["active"]:
        pbest, post = thompson(elig, seed_of("ts", dim), grand, sigma2)
        E = len(elig)
        for a in elig:
            probs[a] = (EXPLORATION / E + (1 - EXPLORATION) * pbest[a]) * E / K
        out["thompson"] = {a: {"p_best": round(pbest[a], 4), **post[a]} for a in elig}
    s = sum(probs.values())
    out["probs"] = {a: round(probs[a] / s, 4) for a in arms}
    out["evidence"] = {a: ev.get(a, {"films": 0}) for a in arms}
    return out


# ================================================================================================ the join
def load_analytics():
    sys.path.insert(0, AN)
    os.chdir(AN)
    import va_common as C            # noqa: E402
    import model as M                # noqa: E402
    import experiments as E          # noqa: E402
    return C, M, E


def film_metrics(rows):
    """rows: model.wide() posts -> {film: {metric: value}} (mean of the platform-relative values over the film's platforms)"""
    src = {"rel_hold3": "hold3", "rel_watch": "watch_pct", "rel_shares": "shares_per_1k", "rel_comments": "comments_per_1k"}
    eligible = [r for r in rows if r.get("fmt") != "longform" and (r.get("views") or 0) >= MIN_VIEWS and (r.get("age_days") or 0) >= MIN_AGE_D]
    ref = {}
    for plat in {r["platform"] for r in eligible}:
        for met, col in src.items():
            v = [r[col] for r in eligible if r["platform"] == plat and r.get(col) is not None]
            if len(v) < 5:
                continue
            m = statistics.median(v)
            if m <= 0:
                pos = [x for x in v if x > 0]
                m = sum(pos) / len(pos) if pos else 0
            if m > 0:
                ref[(plat, met)] = m
    per = {}
    for r in eligible:
        for met, col in src.items():
            m = ref.get((r["platform"], met))
            if m and r.get(col) is not None:
                per.setdefault(r["film"], {}).setdefault(met, []).append(min(REL_CAP, r[col] / m))
    fm = {f: {met: sum(v) / len(v) for met, v in d.items()} for f, d in per.items()}
    return fm, {"platform_medians": {"%s:%s" % k: round(v, 4) for k, v in sorted(ref.items())}, "posts_used": len(eligible)}


def film_choices(films, E):
    """film -> {dimension: arm}. Declared arms win over derived (experiments.film_table); format/swatch only where the engine built the short"""
    hooks = (jload(os.path.join(REG, "hook-labels.json"), {}) or {}).get("labels", {})
    ft = E.film_table(films, hooks)
    fe = jload(os.path.join(REG, "format-engine.json"), {}) or {}
    out = {}
    for f in films:
        arms = {k: v for k, v in ft.get(f, {}).get("arms", {}).items()}
        c = jload(os.path.join(KIT, "specs", f, "concept.json"), {}) or {}
        sp = jload(os.path.join(KIT, "specs", f, "spec.json"), {}) or {}
        comp = sp.get("composed") or {}
        engine = comp.get("engine") == "format_engine" or f in fe
        wf = (c.get("world") or {}).get("world_family")
        if wf:
            arms["world_family"] = wf
        lum = (c.get("ground") or {}).get("luminance")
        if lum:
            arms["ground"] = lum
        if engine:
            arms["format"] = (fe.get(f) or {}).get("format") or comp.get("format")
            arms["swatch"] = (fe.get(f) or {}).get("swatch") or comp.get("swatch")
        craft = c.get("craft") if isinstance(c.get("craft"), dict) else {}
        if "loop_close" in craft:
            arms["loop_close"] = "yes" if craft["loop_close"] else "no"
        out[f] = {k: v for k, v in arms.items() if v not in (None, "") and k in DIMS}
        out[f]["_maker"] = "engine" if engine else "maker"
    return out


def learn(db=None, C=None, M=None, E=None):
    if C is None:
        C, M, E = load_analytics()
    db = db or C.connect()
    rows = M.wide(db)
    fm, meta = film_metrics(rows)
    films = sorted({r["film"] for r in rows if r.get("fmt") != "longform"})
    ch = film_choices(films, E)
    return analyse(fm, ch, meta, rows)


def analyse(fm, ch, meta=None, rows=None):
    """pure function of {film: metrics}, {film: choices}: -> the weights document (also what the selftest drives)"""
    grand_hold = [m["rel_hold3"] for m in fm.values() if "rel_hold3" in m]
    grand = (sum(grand_hold) / len(grand_hold)) if grand_hold else 1.0
    all_vals = {met: {f: m[met] for f, m in fm.items() if met in m} for met in METRICS}
    dims = {}
    for dim in DIMS:
        films_by_arm = {}
        for f, c in ch.items():
            if dim in c and f in fm:
                films_by_arm.setdefault(str(c[dim]), []).append(f)
        engine_opts = ENGINE_OPTIONS.get(dim)
        if not films_by_arm and not engine_opts:
            dims[dim] = {"active": False, "arms": [], "probs": {}, "evidence": {}, "note": "no posted short carries this choice yet"}
            continue
        vals = {a: {met: {f: fm[f][met] for f in fl if met in fm[f]} for met in METRICS} for a, fl in films_by_arm.items()}
        ev = arm_stats(vals, films_by_arm, dim, all_vals)
        within = []
        for a, md in vals.items():
            v = list(md["rel_hold3"].values())
            if len(v) > 1:
                m_, sd = mean_sd(v)
                within += [(x - m_) ** 2 for x in v]
        sigma2 = max(0.01, (sum(within) / max(1, len(within))) if within else statistics.pvariance(grand_hold) if len(grand_hold) > 1 else 0.05)
        d = dimension_weights(dim, vals, films_by_arm, ev, engine_opts, grand, sigma2)
        d["films_with_choice"] = sum(len(v) for v in films_by_arm.values())
        d["sigma2"] = round(sigma2, 5)
        dims[dim] = d
    doc = {"schema": 1, "generated_at": time.strftime("%Y-%m-%dT%H:%M:%S"), "by": "kit/tools/engine_learn.py",
           "note": "Sampling weights for kit/tools/format_engine.py. Thompson sampling on rel_hold3; an arm leaves uniform at n >= %d films; >= %d%% exploration; dimensions with fewer than 2 qualifying arms are inactive and the engine keeps its rule defaults. Weights only choose among options the story's own gates leave valid. Lessons need n >= %d and a %d%% interval that excludes zero."
                   % (MIN_N_WEIGHT, int(EXPLORATION * 100), MIN_N_LESSON, CI),
           "films_scored": len(fm), "films_with_hold3": len(grand_hold), "grand_mean_rel_hold3": round(grand, 4),
           "makers": {k: sum(1 for f in fm if ch.get(f, {}).get("_maker") == k) for k in ("maker", "engine")},
           "join": meta or {}, "dimensions": dims}
    return doc


def _engine_options():
    """what format_engine can actually choose between (from its own tables; no import of the engine, so this stays light and cannot fail on an engine edit)"""
    opts = {"format": ["dossier", "clean", "newsroom"], "ground": ["light", "dark"], "world_family": ["desk-paper", "ui-screen", "interior-set", "map-plan"]}
    try:
        sys.path.insert(0, HERE)
        sys.path.insert(0, KIT)
        import fe_formats as FF
        opts["format"] = sorted(FF.FORMATS)
        opts["swatch"] = sorted(FF.SWATCHES)
    except Exception:
        pass
    return opts


ENGINE_OPTIONS = _engine_options()


# ================================================================================================ weekly lessons
def london_today():
    try:
        from zoneinfo import ZoneInfo
        return datetime.datetime.now(ZoneInfo("Europe/London")).date()
    except Exception:
        return datetime.date.today()


def lessons_from(doc, min_n=MIN_N_LESSON):
    out = []
    for dim, d in doc["dimensions"].items():
        for arm, e in (d.get("evidence") or {}).items():
            h = e.get("rel_hold3") or {}
            ef = h.get("effect_vs_rest")
            if h.get("n", 0) >= min_n and ef and ef["n_rest"] >= min_n and ef["excludes_zero"]:
                others = {m: (e.get(m) or {}).get("mean") for m in ("rel_watch", "rel_shares", "rel_comments")}
                out.append({"dim": dim, "arm": arm, "n": h["n"], "mean": h["mean"], "diff": ef["diff"], "ci90": ef["ci90"], "n_rest": ef["n_rest"], "others": others})
    return sorted(out, key=lambda x: -abs(x["diff"]))


def proposals_from(doc, lessons):
    cur = jload(STRATEGY, {}) or {}
    props = []
    for les in lessons:
        thr = THRESHOLD_FOR.get(les["dim"])
        if not thr or les["arm"] not in thr[1] or les["diff"] <= 0:
            continue
        key, mp = thr
        if key in cur and cur[key] != mp[les["arm"]]:
            props.append({"key": key, "current": cur[key], "proposed": mp[les["arm"]], "because": "%s=%s: rel_hold3 %+.2f vs the other films (90%% interval %+.2f to %+.2f), n=%d vs %d" % (les["dim"], les["arm"], les["diff"], les["ci90"][0], les["ci90"][1], les["n"], les["n_rest"]),
                          "status": "PROPOSED: root/Sam approve; strategy-v3.json is not edited by the learner"})
    return props


def block_text(doc, lessons, props, week):
    L = [MARK0, "", "## Engine-learn, week of %s" % week, "",
         "Written %s by `kit/tools/engine_learn.py` from %d scored films (%d with a 3 s hold curve). Numbers only, no model. A candidate needs n >= %d films, the rest n >= %d, and a %d%% bootstrap interval of (arm minus the films on the dimension's other arms) on relative 3 s hold that excludes zero. Relative = divided by that platform's own median, so 1.00 is a typical short."
         % (doc["generated_at"], doc["films_scored"], doc["films_with_hold3"], MIN_N_LESSON, MIN_N_LESSON, CI), ""]
    if lessons:
        for les in lessons:
            o = ", ".join("%s %s" % (k.replace("rel_", ""), ("%.2f" % v) if v is not None else "-") for k, v in les["others"].items())
            L.append("- %s `%s=%s`: relative 3 s hold %.2f over %d films, %+.2f against the %d films on other arms (90%% interval %+.2f to %+.2f). Other metrics (relative): %s." %
                     (doc["generated_at"][:10], les["dim"], les["arm"], les["mean"], les["n"], les["diff"], les["n_rest"], les["ci90"][0], les["ci90"][1], o))
    else:
        L.append("- No arm clears the bar yet (n >= %d films with the interval excluding zero)." % MIN_N_LESSON)
    L += ["", "Threshold proposals (strategy-v3.json untouched, see registry/strategy-v3-proposed.json): " + (
        "; ".join("%s %s -> %s (%s)" % (p["key"], p["current"], p["proposed"], p["because"]) for p in props) if props else "none."), "", MARK1]
    return "\n".join(L)


def write_weekly(doc, force=False):
    today = london_today()
    if today.weekday() != 0 and not force:
        return "skipped (not Monday)"
    week = (today - datetime.timedelta(days=today.weekday())).isoformat()
    lessons = lessons_from(doc)
    props = proposals_from(doc, lessons)
    atomic_write(PROPOSED, json.dumps({"schema": 1, "generated_at": doc["generated_at"], "week": week, "proposals": props,
                                       "rule": "PROPOSED only. strategy-v3.json is edited by root/Sam, never by engine_learn.py."}, indent=1) + "\n")
    try:
        old = open(CANDIDATES, encoding="utf-8").read()
    except OSError:
        old = "# CREATIVE SCHOOL: lesson candidates (from the tracker, for root)\n\n"
    prev = ""
    if MARK0 in old and MARK1 in old:
        a, b = old.index(MARK0), old.index(MARK1) + len(MARK1)
        prev, old = old[a:b], old[:a].rstrip("\n") + "\n\n" + old[b:].lstrip("\n")
    # keep the previous weeks of this block, replace this week's
    kept = [s for s in prev.split("\n## Engine-learn, week of ")[1:] if not s.startswith(week)]
    kept = [("## Engine-learn, week of " + s).split("\n" + MARK1)[0].rstrip("\n") for s in kept][:7]
    new = block_text(doc, lessons, props, week)
    if kept:
        new = new[:-len(MARK1)].rstrip("\n") + "\n\n" + "\n\n".join(kept) + "\n\n" + MARK1
    head, sep, rest = old.partition("\n## Week of ")
    text = head.rstrip("\n") + "\n\n" + new + "\n" + ((sep + rest) if sep else "")
    atomic_write(CANDIDATES, text if text.endswith("\n") else text + "\n")
    return "wrote %d candidate(s), %d proposal(s) for week %s" % (len(lessons), len(props), week)


# ================================================================================================ selftest
def _synthetic(rng, n_films=60, lift=0.30):
    fm, ch = {}, {}
    for i in range(n_films):
        f = "T%03d" % i
        g = "light" if i % 2 == 0 else "dark"
        x = 1.0 + (lift if g == "light" else 0.0) + rng.gauss(0, 0.15)
        fm[f] = {"rel_hold3": x, "rel_watch": 1.0 + rng.gauss(0, .1), "rel_shares": 1.0, "rel_comments": 1.0}
        ch[f] = {"ground": g, "hook_type": rng.choice(["a", "b", "c"]), "_maker": "maker"}
    return fm, ch


def selftest():
    bad = 0

    def say(ok, msg):
        nonlocal bad
        print(("PASS " if ok else "FAIL ") + msg)
        bad += 0 if ok else 1
    rng = random.Random(7)
    fm, ch = _synthetic(rng)
    doc = analyse(fm, ch)
    g = doc["dimensions"]["ground"]
    say(g["active"] and g["probs"]["light"] > g["probs"]["dark"] > 0, "a clearly better arm (light, +0.30) gains weight and the other keeps some: %s" % g["probs"])
    say(g["probs"]["dark"] >= EXPLORATION / 2 * 0.99, "exploration floor: the losing arm keeps >= %.3f of the mass (%.3f)" % (EXPLORATION / 2, g["probs"]["dark"]))
    say(abs(sum(g["probs"].values()) - 1) < 0.01, "probabilities sum to 1")
    ls = lessons_from(doc)
    say(any(x["dim"] == "ground" and x["arm"] == "light" for x in ls), "the real +0.30 effect becomes a lesson candidate")
    # null: the same outcomes with the labels shuffled must give no lesson and weights near uniform
    labels = [c["ground"] for c in ch.values()]
    rng.shuffle(labels)
    ch0 = {f: dict(c, ground=labels[i]) for i, (f, c) in enumerate(ch.items())}
    d0 = analyse(fm, ch0)
    say(not any(x["dim"] == "ground" for x in lessons_from(d0)), "shuffled labels: no ground lesson (a check that can fail)")
    # min-n gate: 5 films per arm never moves a weight
    fm5 = {f: v for f, v in list(fm.items())[:10]}
    ch5 = {f: ch[f] for f in fm5}
    d5 = analyse(fm5, ch5)["dimensions"]["ground"]
    say(not d5["active"] and len(set(d5["probs"].values())) == 1, "n < %d per arm: dimension inactive, weights uniform %s" % (MIN_N_WEIGHT, d5["probs"]))
    # chooser: inactive -> default; active -> the favoured option wins most of the time; forced -> forced; invalid option never drawn
    pick, rec = choose(doc, "ground", ["light", "dark"], "dark", "S1")
    wins = sum(choose(doc, "ground", ["light", "dark"], "dark", "S%d" % i)[0] == "light" for i in range(400))
    say(wins > 200 and wins < 400, "chooser follows the weights but still explores: light %d/400" % wins)
    say(choose(doc, "ground", ["dark"], "dark", "S1")[0] == "dark", "a single valid option is never overridden")
    say(choose(None, "ground", ["light", "dark"], "dark", "S1")[0] == "dark", "no weights file: the engine's default")
    say(all(choose(doc, "ground", ["dark", "mid"], "dark", "S%d" % i)[0] in ("dark", "mid") for i in range(50)), "options outside the valid set are never drawn")
    print("engine_learn selftest: %s" % ("ALL PASS" if not bad else "%d FAILED" % bad))
    return 1 if bad else 0


# ================================================================================================ main
def summary(doc):
    L = ["engine-weights: %d films scored (%d with 3 s hold), grand mean rel_hold3 %.3f, makers %s" % (doc["films_scored"], doc["films_with_hold3"], doc["grand_mean_rel_hold3"], doc["makers"])]
    for dim, d in doc["dimensions"].items():
        if not d.get("arms"):
            L.append("  %-18s no data" % dim)
            continue
        cells = []
        for a in d["arms"]:
            h = (d["evidence"].get(a) or {}).get("rel_hold3") or {}
            cells.append("%s n=%s %s p=%.2f" % (a, h.get("n", 0), ("%.2f" % h["mean"]) if "mean" in h else "-", d["probs"][a]))
        L.append("  %-18s %s | %s" % (dim, "ACTIVE" if d["active"] else "inactive", "; ".join(cells)))
    return "\n".join(L)


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--weekly", action="store_true", help="write the lesson candidates now (otherwise only on Mondays, London)")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--selftest", action="store_true")
    a = ap.parse_args()
    if a.selftest:
        return selftest()
    t0 = time.time()
    doc = learn()
    body = json.dumps(doc, indent=1, ensure_ascii=False, sort_keys=False)
    doc["sha1"] = hashlib.sha1(body.encode()).hexdigest()[:12]
    print(summary(doc))
    if a.dry_run:
        return 0
    atomic_write(WEIGHTS, json.dumps(doc, indent=1, ensure_ascii=False) + "\n")
    print("wrote %s (sha1 %s)" % (WEIGHTS, doc["sha1"]))
    print("weekly: " + write_weekly(doc, force=a.weekly))
    print("engine_learn done in %.1f s" % (time.time() - t0))
    return 0


if __name__ == "__main__":
    sys.exit(main())
