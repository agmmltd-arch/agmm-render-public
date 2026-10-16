#!/usr/bin/env python3
"""Existing render-input DOM lint. All archive, image and browser IO is Ubuntu-only.

The rules are imported intact from the published native source closure. This helper
only verifies the render request, prepares the native plan and seals its results.
"""
from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import math
import os
import re
import sys
from pathlib import Path
from urllib.parse import unquote, urlsplit

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import render_short_package as package
import snap_short_package as snap

NATIVE = HERE / "domlint-native"
sys.path.insert(0, str(NATIVE / "kit" / "tools"))
import dom_lint as lint
sys.path.insert(0, str(NATIVE / "qa"))
import machine_pass

REPOSITORY = "agmmltd-arch/agmm-render-public"
HASH = re.compile(r"^[0-9a-f]{64}$")
SID = re.compile(r"^[SCP][0-9]{2,3}$")


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":")).encode()


def digest(value):
    return hashlib.sha256(canonical(value)).hexdigest()


def require(ok, message):
    if not ok:
        raise package.ContractError(message)


def validate_request(payload):
    require(isinstance(payload, dict) and payload.get("schema") == 1, "unsupported existing-request schema")
    require(re.fullmatch(r"[0-9a-f]{40}", payload.get("runtime_commit", "")), "runtime commit must be immutable")
    require(payload.get("every") == 0.1, "existing-input lint requires the native 0.1 s grid")
    require(HASH.fullmatch(payload.get("request_sha256", "")), "native REQUEST byte hash is absent")
    req = payload.get("render_request") or {}
    sid = req.get("id", "")
    require(SID.fullmatch(sid), "invalid short ID")
    require(req.get("schema") == 1 and req.get("kind") == "agmm_short_cloud_dispatch_request", "not a native render REQUEST")
    require(req.get("workflow", {}).get("repository") == REPOSITORY, "render REQUEST repository mismatch")
    require(req.get("workflow", {}).get("workflow") == "agmm-short-package.yml", "unsupported render REQUEST workflow")
    appr = req.get("approval") or {}
    require(appr.get("state") == "approved" and HASH.fullmatch(appr.get("approved_hash", "")), "native approval is absent")
    require(appr.get("current_hash") == appr["approved_hash"], "render REQUEST source was not current approved source")
    inputs, wi = req.get("inputs") or {}, req.get("workflow_inputs") or {}
    binding = {}
    for key in ("source", "parts", "mix"):
        item = inputs.get(key) or {}
        require(HASH.fullmatch(item.get("sha256", "")), "invalid %s hash" % key)
        require(type(item.get("bytes")) is int and item["bytes"] > 0, "invalid %s byte count" % key)
        name = key + "_sha256"
        require(wi.get(name) == item["sha256"], "%s workflow binding mismatch" % key)
        binding[name] = item["sha256"]
    require(req.get("package_id") == digest(binding), "render package_id mismatch")
    request_binding = dict(binding, approved_hash=appr["approved_hash"], render_4k=wi.get("render_4k"), workers=wi.get("workers"))
    require(type(wi.get("render_4k")) is bool and wi.get("workers") == "2", "unsupported native render options")
    require(req.get("request_id") == digest(request_binding), "native request_id mismatch")
    require(wi.get("release") == "short-%s-%s" % (sid.lower(), req["package_id"]), "render release binding mismatch")
    p = lint.platforms.profile(payload.get("target"))
    require(payload.get("target") == p["key"], "target must be an explicit canonical platform key")
    require(isinstance(payload.get("beat_starts"), list) and payload["beat_starts"], "native beat starts are required")
    require(all(type(t) in (int, float) and math.isfinite(t) and t >= 0 for t in payload["beat_starts"]), "invalid beat starts")
    require(payload["beat_starts"] == sorted(set(payload["beat_starts"])), "beat starts must be unique and ordered")
    require(isinstance(payload.get("allow_lint"), list) and all(isinstance(t, str) for t in payload["allow_lint"]), "invalid native lint exceptions")
    return req, p


def runtime_pins():
    pins = json.loads((NATIVE / "PINS.json").read_text())
    for name, expected in pins.items():
        require(package.sha256(HERE / name) == expected, "native runtime source changed: " + name)
    return pins


def require_host(payload):
    require(sys.platform == "linux" and os.environ.get("GITHUB_ACTIONS") == "true", "archive/image/browser path is hosted Ubuntu Actions only")
    require(os.environ.get("GITHUB_REPOSITORY") == REPOSITORY, "hosted repository mismatch")
    require(os.environ.get("GITHUB_SHA") == payload["runtime_commit"], "workflow runtime commit changed after preflight")
    require(os.environ.get("RUNNER_OS") == "Linux", "Ubuntu runner is required")


def validate_assets(data, req):
    require(isinstance(data, dict) and not data.get("draft"), "release metadata is invalid")
    assets = data.get("assets") or []
    require(sorted(a.get("name", "") for a in assets) == ["mix.wav", "parts.json", "source.tar.gz"], "expected the exact three-asset native render release")
    for key, name in (("source", "source.tar.gz"), ("parts", "parts.json"), ("mix", "mix.wav")):
        asset = next(a for a in assets if a["name"] == name)
        want = req["inputs"][key]
        require(asset.get("size") == want["bytes"], "release %s byte count mismatch" % name)
        if asset.get("digest"):
            require(asset["digest"] == "sha256:" + want["sha256"], "release %s digest mismatch" % name)


def dump(path, value):
    path.write_text(json.dumps(value, indent=1) + "\n")


def prepare(payload, source, parts_path, output, assets):
    req, prof = validate_request(payload)
    require_host(payload)
    pins = runtime_pins()
    validate_assets(assets, req)
    package.verify_hash(source, req["inputs"]["source"]["sha256"], "source.tar.gz")
    package.verify_hash(parts_path, req["inputs"]["parts"]["sha256"], "parts.json")
    require(source.stat().st_size == req["inputs"]["source"]["bytes"], "source bytes changed")
    raw_parts = json.loads(parts_path.read_text())
    require(raw_parts.get("sha256") == req["inputs"]["source"]["sha256"] and raw_parts.get("bytes") == source.stat().st_size, "parts.json source binding mismatch")
    project = output / "project"
    members = package.safe_extract(source, project)
    info = package.validate_parts(raw_parts, project)
    parts = info["parts"]
    require(len(parts) == req["package"]["parts"] and info["frames"] == req["package"]["frames"], "native part/frame contract mismatch")
    require(len(members) == req["package"]["archive_members"], "native archive member count mismatch")
    # Resolve each part's own frozen spec; never trust a client-supplied plan.
    for part in parts:
        source_spec = (project / part["look"] / "spec.js").read_text()
        match = re.search(r"=\s*(\{.*\})\s*;?\s*$", source_spec, re.S)
        require(match is not None, "part has no frozen native spec.js")
        spec = json.loads(match.group(1))
        require([float(b["from"]) for b in spec["beats"]] == payload["beat_starts"], "hosted beat starts do not match current resolved metadata")
    kinds = lint.sample_times(parts, payload["beat_starts"], 0.1)
    require(len(kinds) <= 780, "native 0.1 s grid exceeds one dispatch; do not coarsen a release check")
    plan, lookup = lint.make_plan(parts, kinds)
    plan = snap.parse_plan(json.dumps(plan))
    fp, files = machine_pass.dir_fingerprint(str(project))
    prof_json = {"visible": {k: prof["visible"][k] for k in ("x0", "y0", "x1", "y1")}, "overlays": [{k: o[k] for k in ("x0", "y0", "x1", "y1")} for o in prof["overlays"]]}
    output.mkdir(parents=True, exist_ok=True)
    dump(output / "PLAN.json", plan)
    dump(output / "profile.json", prof_json)
    dump(output / "META.json", {"payload": payload, "parts": parts, "pins": pins, "pkg_fingerprint": fp, "pkg_files": files,
                                 "plan_sha256": digest(plan), "expected_samples": sum(len(j["times"]) for j in plan),
                                 "expected_cuts": sum(kind == "cut" for _, kind in lookup.values())})


def validate_raw(raw, plan, project):
    require(set(raw.get("parts", {})) == {j["part"] for j in plan}, "runner omitted a native part")
    images = set()
    for job in plan:
        data = raw["parts"][job["part"]]
        require(data.get("look") == job["look"] and not data.get("errors"), "runner look mismatch or page errors")
        require([s.get("t") for s in data.get("samples", [])] == job["times"], "runner sample coverage mismatch")
        for sample in data["samples"]:
            require(all(isinstance(sample.get(k), list) for k in ("texts", "imgs", "paints")), "raw DOM omitted images/texts/paints")
            for im in sample["imgs"]:
                require(im.get("nw", 0) > 0 and im.get("nh", 0) > 0, "image did not load")
                src = urlsplit(im["src"])
                require(not src.scheme and not src.netloc, "non-local image cannot receive the native pixel check")
                path = (project / job["look"] / unquote(src.path)).resolve()
                require(project.resolve() in path.parents and path.is_file(), "source image is absent from the hosted package")
                images.add(path)
    # Native image_text_height returns None on a photo, but missing PIL or a corrupt
    # image must not silently become an exemption. Decode checks happen only here.
    from PIL import Image
    import numpy
    svg = []
    for path in sorted(images):
        if path.suffix.lower() == ".svg":
            svg.append(path.relative_to(project.resolve()).as_posix())
        else:
            with Image.open(path) as im:
                im.load()
        lint.image_text_height(str(path))
    return len(images), svg, numpy.__version__, Image.__version__


def analyze(prepared, result):
    meta = json.loads((prepared / "META.json").read_text())
    payload = meta["payload"]
    req, prof = validate_request(payload)
    require_host(payload)
    require(runtime_pins() == meta["pins"], "runtime source changed during lint")
    project = prepared / "project"
    require(machine_pass.dir_fingerprint(str(project)) == (meta["pkg_fingerprint"], meta["pkg_files"]), "hosted package changed during lint")
    raw = json.loads((result / "raw.json").read_text())
    plan = json.loads((prepared / "PLAN.json").read_text())
    images, svg, numpy_version, pillow_version = validate_raw(raw, plan, project)
    _, kinds = lint.make_plan(meta["parts"], lint.sample_times(meta["parts"], payload["beat_starts"], 0.1))
    report = lint.analyze(raw, req["id"], prof, 0.1, kinds, meta["parts"], str(result), payload["allow_lint"], str(project) + os.sep, False)
    report.update(id=req["id"], platform=prof["key"], step=0.1)
    require(report["stats"]["samples"] == meta["expected_samples"] and report["stats"]["cut_frames"] == meta["expected_cuts"], "native report coverage mismatch")
    dump(result / "result.json", report)
    receipt = {"schema": 1, "kind": "agmm_hosted_native_domlint", "id": req["id"], "target": prof["key"], "step": 0.1,
               "repository": REPOSITORY, "run_id": os.environ["GITHUB_RUN_ID"], "run_attempt": os.environ["GITHUB_RUN_ATTEMPT"],
               "runtime_commit": os.environ["GITHUB_SHA"], "request_id": req["request_id"], "request_sha256": payload["request_sha256"],
               "release": req["workflow_inputs"]["release"], "source_sha256": req["inputs"]["source"]["sha256"],
               "parts_sha256": req["inputs"]["parts"]["sha256"], "approved_hash": req["approval"]["approved_hash"],
               "pkg_fingerprint": meta["pkg_fingerprint"], "pkg_files": meta["pkg_files"], "plan_sha256": meta["plan_sha256"],
               "native_sources": meta["pins"], "samples": meta["expected_samples"], "cut_frames": meta["expected_cuts"],
               "image_checks": "native image_text_height + card_items + image legibility; no omission", "image_files_checked": images, "image_files_decoded": images - len(svg), "native_svg_blind_spots": svg,
               "numpy": numpy_version, "pillow": pillow_version, "result_sha256": package.sha256(result / "result.json"),
               "raw_sha256": package.sha256(result / "raw.json"), "FAIL": report["stats"]["FAIL"], "WARN": report["stats"]["WARN"]}
    dump(result / "RECEIPT.json", receipt)
    print("native hosted DOM lint %s -> %s: %d samples/%d cuts; %d FAIL/%d WARN; %d image files checked" %
          (req["id"], prof["key"], receipt["samples"], receipt["cut_frames"], receipt["FAIL"], receipt["WARN"], images))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("command", choices=("prepare", "analyze"))
    ap.add_argument("--payload", default="existing-request.json")
    ap.add_argument("--input", default="exact-input")
    ap.add_argument("--prepared", default="prepared")
    ap.add_argument("--result", default="result")
    a = ap.parse_args()
    try:
        if a.command == "prepare":
            prepare(json.loads(Path(a.payload).read_text()), Path(a.input) / "source.tar.gz", Path(a.input) / "parts.json", Path(a.prepared), json.loads((Path(a.input) / "release.json").read_text()))
        else:
            analyze(Path(a.prepared), Path(a.result))
    except (package.ContractError, ValueError, KeyError, OSError) as error:
        raise SystemExit("CONTRACT ERROR: %s" % error)


if __name__ == "__main__":
    main()
