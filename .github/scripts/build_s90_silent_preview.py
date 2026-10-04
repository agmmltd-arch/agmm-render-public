#!/usr/bin/env python3
"""Build a bounded, silent S90 development composition on hosted Linux only.

This intentionally does not call build_short.py, generate audio, render video,
or change canonical kit/card state. It stages only pinned generic runtime files
and the eleven source-pack PNGs, then emits inputs for the existing capture-only
workflow/helper.
"""
from __future__ import annotations

import argparse
import gzip
import hashlib
import json
import os
import platform
import re
import struct
import tarfile
import urllib.request
from urllib.parse import urlparse
from pathlib import Path, PurePosixPath


INPUTS_NAME = "preview-inputs"
LOOK = "s90-preview-a"
DURATION = 58.133
FRAMES = 1744
PARENT_RELEASE = 400657643
PARENT_TAG = "S86-r2-source-202610010547"
PARENT_ASSET = 602456631
PARENT_ASSET_BYTES = 9830053
PARENT_ASSET_SHA256 = "c8fa6aea8bc904de1183ef648188de4d7ec2ab0d432be623f6b165fd7ac4408b"
RUNTIME_PROOF_SHA256 = "de28d9725c166286e377cc972b73a344ad763cfd5dd7652800dcfccef17c374f"
SOURCE_MANIFEST_SHA256 = "1056bc10aa7a6b9d70a46d96d14139abe8e60ef3b7d8b82940c23061505c1e0b"
SOURCE_REVIEW_SHA256 = "b0102274086343806a9f4aed0d0d5fae2dedcbeb52c5fc65e18b634990ba0953"
WORDS_SHA256 = "a6d08fbb84c55f406457751213df0094561e55de1e1824faf66cd760845f3925"
SCENES_SHA256 = "5e623b801272b1e5439cf4191ec6038a2a1787c3df455500b4f1fa39221a2290"
DELTA_SHA256 = "a6358970948829a231850f1d77f122de1210863c6f1865251e530c557db96857"
PINNED_KIT3_SHA256 = "e0505dd3deca92e3a54c4473f7a37124e706d0a6647297eb87f149aef2e80762"
PINNED_KIT3_CSS_SHA256 = "2182674e7c361aa73d5e92e8fe05ef3c1f0ae2fa20ce2c2eb26b20521d7d0bb6"
PINNED_DS_CSS_SHA256 = "181eb68d13ee571ae8a9129abbd14dda51d939aefebaf20f0173ac16c35d7135"
SOURCE_BASE = "https://raw.githubusercontent.com/agmmltd-arch/agmm-render-public/review-S90-source-pack-37163208994/public-review/S90/37163208994/"
PNG_SIG = b"\x89PNG\r\n\x1a\n"
HASH_RE = re.compile(r"^[0-9a-f]{64}$")


class Refusal(RuntimeError):
    pass


def canonical_json(value: object) -> bytes:
    return (json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False) + "\n").encode()


def sha_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for block in iter(lambda: f.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def pinned_text(path: Path, expected: str, label: str) -> bytes:
    data = path.read_bytes()
    actual = sha_bytes(data)
    if actual != expected:
        raise Refusal(f"{label} pin mismatch: expected {expected}, got {actual}")
    return data


def require_hosted_linux() -> None:
    if platform.system() != "Linux" or os.environ.get("GITHUB_ACTIONS") != "true" or os.environ.get("S90_HOSTED_PREVIEW") != "1":
        raise Refusal("refusing source/archive/media staging outside the explicitly enabled hosted Linux workflow")


def safe_member(name: str) -> PurePosixPath:
    if name in (".", "./"):
        return PurePosixPath(".")
    while name.startswith("./"):
        name = name[2:]
    path = PurePosixPath(name)
    if not name or path.is_absolute() or ".." in path.parts or "\\" in name or "\x00" in name:
        raise Refusal(f"unsafe runtime archive path: {name!r}")
    return path


def validate_parent_release(metadata_path: Path) -> None:
    data = json.loads(metadata_path.read_text())
    validate_parent_release_text(data)


def validate_parent_release_text(data: object) -> None:
    if not isinstance(data, dict):
        raise Refusal("runtime parent metadata is not an object")
    if data.get("id") != PARENT_RELEASE or data.get("tag_name") != PARENT_TAG or data.get("draft") is not False or data.get("prerelease") is not False:
        raise Refusal("runtime parent release identity/status does not match the pinned public release")
    matches = [a for a in data.get("assets", []) if a.get("id") == PARENT_ASSET]
    if len(matches) != 1:
        raise Refusal("pinned runtime parent asset is missing or ambiguous")
    asset = matches[0]
    if asset.get("name") != "source.tar.gz" or asset.get("state") != "uploaded" or asset.get("size") != PARENT_ASSET_BYTES:
        raise Refusal("pinned runtime parent asset metadata mismatch")
    digest = asset.get("digest")
    if digest not in (None, "sha256:" + PARENT_ASSET_SHA256):
        raise Refusal("pinned runtime parent metadata digest mismatch")


def validate_repository_text(data: object) -> None:
    if not isinstance(data, dict) or data.get("full_name") != "agmmltd-arch/agmm-render-public" or data.get("private") is not False or data.get("visibility") != "public":
        raise Refusal("repository is not the exact public AGMM render repository")


def load_inputs(candidate: Path) -> tuple[dict, dict, dict, dict]:
    inputs = candidate / INPUTS_NAME
    proof = json.loads(pinned_text(inputs / "ROOT-RUNTIME-PARENT-PROOF.json", RUNTIME_PROOF_SHA256, "runtime proof"))
    manifest = json.loads(pinned_text(inputs / "ROOT-SUCCESS-manifest.json", SOURCE_MANIFEST_SHA256, "source manifest"))
    review = json.loads(pinned_text(inputs / "ROOT-SOURCE-ASSET-REVIEW.json", SOURCE_REVIEW_SHA256, "source review"))
    words = json.loads(pinned_text(inputs / "S90.words.json", WORDS_SHA256, "voice word timing"))
    pinned_text(candidate / "scenes.js", SCENES_SHA256, "scene implementation")
    pinned_text(candidate / "spec-delta.json", DELTA_SHA256, "storyboard delta")
    if proof.get("parent_release_id") != PARENT_RELEASE or proof.get("parent_asset", {}).get("id") != PARENT_ASSET:
        raise Refusal("runtime proof release/asset identity mismatch")
    if proof.get("parent_asset", {}).get("digest") != "sha256:" + PARENT_ASSET_SHA256 or proof.get("parent_asset", {}).get("size") != PARENT_ASSET_BYTES:
        raise Refusal("runtime proof archive digest/size mismatch")
    if len(proof.get("generic_runtime_members", {})) != 50:
        raise Refusal("runtime parent proof must contain exactly 50 reviewed generic members")
    if review.get("run") != 37163208994 or review.get("verdict") != "ACCEPTED_FOR_STORYBOARD_DEVELOPMENT_ONLY":
        raise Refusal("source asset review is not the pinned storyboard-development-only review")
    if manifest.get("story_id") != "S90" or manifest.get("policy", {}).get("rights_status") != "NOT_ASSESSED":
        raise Refusal("source manifest identity or rights status changed")
    if manifest.get("source", {}).get("publisher") != "Channel 4" or manifest.get("source", {}).get("http_status") != 200:
        raise Refusal("source manifest publisher/status mismatch")
    if not isinstance(words.get("words"), list) or not words["words"]:
        raise Refusal("locked voice timing is missing")
    return proof, manifest, review, words


def validate_archive_and_extract(archive_path: Path, members: dict[str, str], destination: Path) -> dict[str, str]:
    if archive_path.stat().st_size != PARENT_ASSET_BYTES or sha_file(archive_path) != PARENT_ASSET_SHA256:
        raise Refusal("downloaded runtime parent archive bytes/hash do not match the pinned release")
    if destination.exists() and any(destination.iterdir()):
        raise Refusal("refusing to overlay a nonempty staged project")
    destination.mkdir(parents=True, exist_ok=True)
    wanted = set(members)
    found: dict[str, str] = {}
    seen: set[str] = set()
    with tarfile.open(archive_path, "r:gz") as tar:
        entries = tar.getmembers()
        if len(entries) > 10000 or not entries:
            raise Refusal("runtime archive member count is outside bound")
        total_declared = 0
        for info in entries:
            rel = safe_member(info.name)
            key = rel.as_posix().rstrip("/")
            if key in seen:
                raise Refusal(f"duplicate normalized runtime archive member: {key}")
            seen.add(key)
            if not (info.isdir() or info.isfile()) or info.issym() or info.islnk() or info.isdev() or info.isfifo():
                raise Refusal(f"forbidden runtime archive member type: {key}")
            if rel == PurePosixPath("."):
                if not info.isdir():
                    raise Refusal("runtime archive root marker must be a directory")
                continue
            total_declared += info.size
            if total_declared > 750_000_000:
                raise Refusal("runtime parent archive expands beyond the 750 MB safety limit")
            # Validate every path/type, but extract only the exact reviewed allowlist.
            if key not in wanted or info.isdir():
                continue
            source = tar.extractfile(info)
            if source is None:
                raise Refusal(f"allowlisted runtime member cannot be read: {key}")
            relative = key.removeprefix("s86-a/")
            target_rel = safe_member(relative)
            target = destination.joinpath(*target_rel.parts)
            target.parent.mkdir(parents=True, exist_ok=True)
            h = hashlib.sha256()
            with target.open("xb") as out:
                for block in iter(lambda: source.read(1024 * 1024), b""):
                    h.update(block)
                    out.write(block)
            digest = h.hexdigest()
            if digest != members[key]:
                raise Refusal(f"allowlisted runtime member hash mismatch: {key}")
            found[key] = digest
    if set(found) != wanted:
        missing = sorted(wanted - set(found))
        raise Refusal(f"runtime parent allowlist is incomplete; missing={missing[:5]}")
    if any("/img/" in "/" + p.lower() or PurePosixPath(p).suffix.lower() in {".png", ".jpg", ".jpeg", ".webp", ".mp3", ".wav", ".mp4", ".mov", ".webm"} for p in found):
        raise Refusal("runtime parent allowlist unexpectedly includes image/audio/video media")
    return found


def png_dimensions(data: bytes, label: str) -> tuple[int, int]:
    if len(data) < 24 or data[:8] != PNG_SIG or data[12:16] != b"IHDR":
        raise Refusal(f"source asset is not a PNG with an IHDR: {label}")
    width, height = struct.unpack(">II", data[16:24])
    if not (1 <= width <= 20000 and 1 <= height <= 20000):
        raise Refusal(f"source PNG dimensions outside safe bounds: {label}")
    return width, height


def fetch_assets(project: Path, manifest: dict) -> tuple[list[dict], list[dict]]:
    assets = manifest.get("assets")
    if not isinstance(assets, list) or len(assets) != 11:
        raise Refusal("source manifest must contain exactly 11 pinned development assets")
    root = project / LOOK / "img" / "s90-source-pack"
    root.mkdir(parents=True)
    rows = []
    dims = []
    seen_names: set[str] = set()
    for item in assets:
        name = item.get("file")
        digest = item.get("sha256")
        size = item.get("bytes")
        if not isinstance(name, str) or not re.fullmatch(r"[a-z0-9-]+\.png", name) or not isinstance(digest, str) or not HASH_RE.fullmatch(digest) or not isinstance(size, int) or not (1 <= size <= 2_000_000):
            raise Refusal("source manifest contains malformed filename/hash/size or an oversized image")
        if name in seen_names:
            raise Refusal(f"source manifest repeats asset filename: {name}")
        seen_names.add(name)
        if item.get("usable_for_render") is not False or item.get("human_rights_review") != "REQUIRED":
            raise Refusal("source assets have changed from storyboard-only/unreviewed rights status")
        request = urllib.request.Request(SOURCE_BASE + name, headers={"User-Agent": "S90-hosted-development-preview"})
        with urllib.request.urlopen(request, timeout=30) as response:
            if response.status != 200 or urlparse(response.geturl()).hostname != "raw.githubusercontent.com":
                raise Refusal(f"source asset response/status host is not the frozen raw GitHub source: {name}")
            data = response.read(size + 1)
        if len(data) != size or sha_bytes(data) != digest:
            raise Refusal(f"source asset byte count or SHA256 mismatch: {name}")
        width, height = png_dimensions(data, name)
        (root / name).write_bytes(data)
        rows.append({"path": f"{LOOK}/img/s90-source-pack/{name}", "sha256": digest, "bytes": size})
        dims.append({"file": name, "width": width, "height": height, "bytes": size, "sha256": digest})
    rows.sort(key=lambda row: row["path"])
    return rows, dims


def write_json(path: Path, value: object) -> bytes:
    data = canonical_json(value)
    path.write_bytes(data)
    return data


def derive_inactive_optional_css(look: Path, spec: dict, scene_source: str) -> list[dict]:
    """Remove only two absent URLs proven inactive for this exact silent softui candidate.

    Parent CSS is first verified byte-for-byte by the 50-member archive allowlist. This
    creates candidate-derived copies; the sealed source retains before/after hashes.
    The native static checker remains strict for every other CSS reference.
    """
    if spec.get("look") != "softui":
        raise Refusal("optional CSS derivation is approved only for the pinned softui preview")
    beats = spec.get("beats")
    if not isinstance(beats, list) or not beats or any(b.get("field") != "none" for b in beats):
        raise Refusal("optional CSS derivation requires every native beat field to be none")
    if re.search(r"\b(?:AG\.grain\s*\(|\.k3-f-cork\b|\.ag-grain\b|field\s*:\s*['\"]cork['\"])", scene_source):
        raise Refusal("S90 scenes activate a texture/field whose CSS asset would be removed")
    kit3 = (look / "kit3.js").read_bytes()
    if sha_bytes(kit3) != PINNED_KIT3_SHA256:
        raise Refusal("pinned kit3 runtime changed before optional CSS derivation")
    kit3_text = kit3.decode("utf-8")
    if not re.search(r"softui\s*:\s*\{[^}]*field:\s*['\"]soft['\"][^}]*grain:\s*0", kit3_text):
        raise Refusal("pinned softui runtime no longer proves soft field and zero grain")

    rules = (
        ("ds/kit.css", PINNED_DS_CSS_SHA256,
         'background-image: url("img/grain.png");', "background-image: none;",
         "softui look has grain=0; no scene requests AG.grain"),
        ("kit3.css", PINNED_KIT3_CSS_SHA256,
         ".k3-f-cork { background: #6b4a2b url(ds2/img/eb-cork-tile.jpg);",
         ".k3-f-cork { background: #6b4a2b;",
         "softui field is soft and every native beat has field=none"),
    )
    derivations = []
    for rel, expected_parent, old, new, reason in rules:
        path = look / rel
        before = path.read_bytes()
        if sha_bytes(before) != expected_parent:
            raise Refusal(f"pinned runtime CSS changed before derivation: {rel}")
        text = before.decode("utf-8")
        if text.count(old) != 1:
            raise Refusal(f"expected exactly one pinned optional CSS declaration in {rel}")
        after = text.replace(old, new, 1).encode("utf-8")
        path.write_bytes(after)
        derivations.append({"path": rel, "parent_sha256": sha_bytes(before), "derived_sha256": sha_bytes(after),
                            "single_declaration_replacement": {"before": old, "after": new}, "inactivity_basis": reason})
    return derivations


def build_spec(words_obj: dict, delta: dict) -> dict:
    words = []
    for row in words_obj["words"]:
        word = str(row.get("word") or row.get("text") or "").strip()
        if word:
            words.append({"word": word, "start": round(float(row["start"]), 3), "end": round(float(row["end"]), 3), "emph": bool(row.get("emph") or row.get("emphasis"))})
    beats = []
    for row in delta.get("beats", []):
        beats.append({"id": row["id"], "comp": "s90-custom", "from": row["from"], "to": row["to"], "field": "none", "tx": "none", "drift": False, "hold": 0.001, "props": {"scene": row["scene"]}})
    if len(beats) != 16:
        raise Refusal("candidate must have exactly sixteen bespoke scenes")
    return {
        "id": "S90-SILENT-DEVELOPMENT",
        "kit": "AGMM",
        "kit_defaults": "2026-09-28",
        "look": "softui",
        "dur": DURATION,
        "words": words,
        "beats": beats,
        # Preserve kit captions on purpose; caption overlap is unresolved and is for root review.
        "captions": [{"from": 0, "to": DURATION, "top": 1290, "height": 300}],
        "images": {},
        "music": None,
        "voice": None,
        "development_only": True,
    }


def capture_plan(beats: list[dict], parts_sha: str, source_sha: str, media_sha: str) -> dict:
    captures = []
    for beat in beats:
        start, end = float(beat["from"]), float(beat["to"])
        for suffix, when in (("incoming", start + 0.12), ("late", end - 0.08)):
            global_t = round(min(max(when, start + 0.02), end - 0.02), 6)
            captures.append({"name": f"{beat['id']}-{suffix}", "kind": "beat", "global": global_t, "local": global_t, "look": LOOK})
    return {"version": 1, "short_id": "S90-silent-development", "source_sha256": source_sha, "parts_sha256": parts_sha, "media_identity_sha256": media_sha, "include_part_seams": True, "captures": captures}


def stage(args: argparse.Namespace) -> None:
    require_hosted_linux()
    validate_parent_release(args.parent_release_metadata)
    candidate = args.candidate.resolve()
    proof, manifest, review, words_obj = load_inputs(candidate)
    output = args.output.resolve()
    if output.exists():
        raise Refusal("refusing to overwrite an existing development package/output")
    project = output / "project"
    project.mkdir(parents=True)
    look = project / LOOK
    look.mkdir()
    member_hashes = validate_archive_and_extract(args.parent_archive, proof["generic_runtime_members"], look)
    # These exact entry files are the existing kit runtime; no S86 story code/audio/images are copied.
    (look / "scenes.js").write_bytes((candidate / "scenes.js").read_bytes())
    spec = build_spec(words_obj, json.loads((candidate / "spec-delta.json").read_text()))
    write_json(look / "spec.json", spec)
    (look / "spec.js").write_text("window.AGK_SPEC=" + json.dumps(spec, ensure_ascii=False, separators=(",", ":")) + ";\n")
    css_derivations = derive_inactive_optional_css(look, spec, (candidate / "scenes.js").read_text())
    (look / "index.html").write_text(make_html())
    (look / "static_check.py").write_text(static_check_source())
    media_rows, dimensions = fetch_assets(project, manifest)
    # Use only the exact allowlisted runtime members. The package source includes the native images for visual review.
    sums = []
    for path in sorted(p for p in look.rglob("*") if p.is_file()):
        rel = path.relative_to(look).as_posix()
        sums.append(f"{sha_file(path)}  {rel}")
    (look / "SHA256SUMS.txt").write_text("\n".join(sums) + "\n")
    # Seal a small exact source archive. Deterministic metadata avoids needless hash churn.
    source_path = output / "source.tar.gz"
    with source_path.open("wb") as raw:
        with gzip.GzipFile(fileobj=raw, mode="wb", filename="", mtime=0) as gz:
            with tarfile.open(fileobj=gz, mode="w") as tar:
                for path in sorted(p for p in project.rglob("*") if p.is_file()):
                    rel = path.relative_to(project).as_posix()
                    info = tar.gettarinfo(str(path), arcname=rel)
                    info.uid = info.gid = 0
                    info.uname = info.gname = ""
                    info.mtime = 0
                    with path.open("rb") as stream:
                        tar.addfile(info, stream)
    source_sha = sha_file(source_path)
    source_bytes = source_path.stat().st_size
    parts = {"sha256": source_sha, "bytes": source_bytes, "frames": FRAMES, "parts": [{"look": LOOK, "file": "index.html", "out": LOOK, "off": 0, "dur": DURATION}]}
    parts_bytes = write_json(output / "parts.json", parts)
    parts_sha = sha_bytes(parts_bytes)
    media_bytes = canonical_json(media_rows)
    media_sha = sha_bytes(media_bytes)
    write_json(output / "MEDIA-IDENTITIES.json", {"sha256": media_sha, "files": media_rows})
    delta = json.loads((candidate / "spec-delta.json").read_text())
    plan = capture_plan(delta["beats"], parts_sha, source_sha, media_sha)
    plan_bytes = write_json(output / "capture-plan.json", plan)
    write_json(output / "STAGING-RECEIPT.json", {
        "kind": "s90_silent_development_staging_receipt",
        "technical_status": "STAGED_ON_HOSTED_LINUX_FOR_CAPTURE_ONLY",
        "source_sha256": source_sha, "source_bytes": source_bytes,
        "parts_sha256": parts_sha, "capture_plan_sha256": sha_bytes(plan_bytes), "media_identity_sha256": media_sha,
        "runtime_parent_release": PARENT_TAG, "runtime_parent_release_id": PARENT_RELEASE,
        "runtime_parent_asset_id": PARENT_ASSET, "runtime_parent_sha256": PARENT_ASSET_SHA256,
        "runtime_parent_members_used": len(member_hashes),
        "runtime_css_derivations": css_derivations,
        "source_assets": dimensions,
        "composition": "SILENT SOURCE COMPOSITION DEVELOPMENT PREVIEW; narration and music intentionally absent",
        "caption_layer": "PRESERVED; overlap remains open for visual review",
        "storyboard": "NOT_APPROVED", "rights": "NOT_ASSESSED", "editorial_review": "NOT_PERFORMED",
        "audio_visual_review": "NOT_PERFORMED", "production_or_release_approval": "NOT_GRANTED",
        "preview_duration_seconds": DURATION, "preview_frame_count": FRAMES,
        "plan_capture_count": len(plan["captures"]),
    })


def make_html() -> str:
    return '''<!doctype html><html><head><meta charset="utf-8"><meta name="viewport" content="width=1080,initial-scale=1"><link rel="stylesheet" href="ds/kit.css"><link rel="stylesheet" href="ds2/kit2.css"><link rel="stylesheet" href="kit3.css"><style>html,body{margin:0;width:1080px;height:1920px;overflow:hidden;background:#081827}#root{position:relative;width:1080px;height:1920px;overflow:hidden}</style></head><body><div id="root" data-composition-id="s90-silent-development" data-look="softui" data-start="0" data-width="1080" data-height="1920" data-duration="58.133"></div><script>window.AGK_PART={off:0,dur:58.133};window.__timelines={};</script><script src="ds/vendor/gsap.min.js"></script><script src="ds/kit.js"></script><script src="ds2/kit2.js"></script><script src="kit3.js"></script><script src="spec.js"></script><script src="scenes.js"></script><script>window.AGK.run(window.AGK_SPEC);</script></body></html>'''


def static_check_source() -> str:
    return r'''from pathlib import Path
import json,re
root=Path(__file__).resolve().parent
html=(root/"index.html").read_text()
for name in re.findall(r"(?:src|href)=\"([^\"]+)\"",html):
 if name.startswith(("http:","https:","//")): raise SystemExit("remote runtime reference refused: "+name)
 if not (root/name).is_file(): raise SystemExit("missing runtime reference: "+name)
for css in root.rglob("*.css"):
 for name in re.findall(r"url\(\s*['\"]?([^)'\"]+)",css.read_text()):
  if name.startswith("data:"): continue
  if name.startswith(("http:","https:","//")): raise SystemExit("remote CSS reference refused: "+name)
  if not (css.parent/name).is_file(): raise SystemExit("missing CSS reference: "+str(css.relative_to(root))+" -> "+name)
if "AGK.run(window.AGK_SPEC)" not in html: raise SystemExit("native AGK entry call missing")
for attr,value in (("data-composition-id","s90-silent-development"),("data-start","0"),("data-width","1080"),("data-height","1920"),("data-duration","58.133")):
 if re.search(attr+r'="'+re.escape(value)+r'"',html) is None: raise SystemExit("native root composition attribute missing: "+attr)
spec=json.loads((root/"spec.json").read_text())
if spec.get("voice") is not None or spec.get("music") is not None: raise SystemExit("silent development preview must contain no voice or music")
if not spec.get("captions"): raise SystemExit("native caption layer must remain present")
print("S90 silent hosted composition static references PASS; editorial/visual quality NOT REVIEWED")
'''


def main() -> None:
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="command", required=True)
    verify = sub.add_parser("verify-release")
    verify.add_argument("--metadata", type=Path, required=True)
    verify.set_defaults(func=lambda a: (require_hosted_linux(), validate_parent_release(a.metadata)))
    repository = sub.add_parser("verify-repository")
    repository.add_argument("--metadata", type=Path, required=True)
    repository.set_defaults(func=lambda a: (require_hosted_linux(), validate_repository_text(json.loads(a.metadata.read_text()))))
    build = sub.add_parser("stage")
    build.add_argument("--parent-release-metadata", type=Path, required=True)
    build.add_argument("--parent-archive", type=Path, required=True)
    build.add_argument("--candidate", type=Path, required=True)
    build.add_argument("--output", type=Path, required=True)
    build.set_defaults(func=stage)
    args = parser.parse_args()
    try:
        args.func(args)
    except Refusal as exc:
        raise SystemExit(f"S90 hosted-preview refusal: {exc}")


if __name__ == "__main__":
    main()
