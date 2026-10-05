#!/usr/bin/env python3
"""Build an S81 source-only HyperFrames package on hosted Ubuntu.

The package reuses the authenticated S86 generic AGMM runtime. It contains no
voice, music, screenshot, or source-programme media. The only media member is
an unchanged official OpenAI SVG selected by an explicit ZIP member path.
"""
from __future__ import annotations

import argparse
import gzip
import hashlib
import importlib.util
import json
import math
import os
import platform
import re
import shutil
import struct
import tarfile
import zipfile
from pathlib import Path, PurePosixPath
from xml.etree import ElementTree

PROOF_SHA256 = "de28d9725c166286e377cc972b73a344ad763cfd5dd7652800dcfccef17c374f"
PAYLOAD_MANIFEST_SHA256 = "bbef6305c2396270d29fce2daa35a78e6e92a39f30555e3daa4bb8dab36e08cb"
PARENT_RELEASE_ID = 400657643
PARENT_TAG = "S86-r2-source-202610010547"
PARENT_ASSET_ID = 602456631
PARENT_BYTES = 9830053
PARENT_SHA256 = "c8fa6aea8bc904de1183ef648188de4d7ec2ab0d432be623f6b165fd7ac4408b"
PINNED_KIT3_SHA256 = "e0505dd3deca92e3a54c4473f7a37124e706d0a6647297eb87f149aef2e80762"
PINNED_KIT3_CSS_SHA256 = "2182674e7c361aa73d5e92e8fe05ef3c1f0ae2fa20ce2c2eb26b20521d7d0bb6"
PINNED_DS_CSS_SHA256 = "181eb68d13ee571ae8a9129abbd14dda51d939aefebaf20f0173ac16c35d7135"
LOOK = "s81-evidence-route"
DURATION = 56.365
PNG_OR_MEDIA_SUFFIXES = {".wav", ".mp3", ".mp4", ".mov", ".webm", ".png", ".jpg", ".jpeg", ".webp"}
HASH_RE = re.compile(r"^[0-9a-f]{64}$")

_VERIFY_SPEC = importlib.util.spec_from_file_location(
    "s81_payload_public_text_policy", Path(__file__).with_name("verify_s81_payload.py")
)
if _VERIFY_SPEC is None or _VERIFY_SPEC.loader is None:
    raise RuntimeError("shared S81 public-text verifier is unavailable")
_VERIFY = importlib.util.module_from_spec(_VERIFY_SPEC)
_VERIFY_SPEC.loader.exec_module(_VERIFY)


class Refusal(RuntimeError):
    pass


def require_hosted_linux() -> None:
    # Keep this as the first operation in stage(): do not inspect files first.
    if (platform.system() != "Linux" or os.environ.get("GITHUB_ACTIONS") != "true"
            or os.environ.get("S81_HOSTED_SOURCE_CAPTURE") != "1"):
        raise Refusal("refusing source/archive/media access outside explicitly enabled GitHub Linux Actions")


def sha_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for block in iter(lambda: f.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def canonical_json(value: object) -> bytes:
    return (json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False) + "\n").encode()


def safe_member(name: str) -> PurePosixPath:
    if name in (".", "./"):
        return PurePosixPath(".")
    while name.startswith("./"):
        name = name[2:]
    path = PurePosixPath(name)
    if not name or path.is_absolute() or ".." in path.parts or "\\" in name or "\x00" in name:
        raise Refusal(f"unsafe archive member: {name!r}")
    return path


def verify_payload(payload: Path, expected_manifest_sha: str = PAYLOAD_MANIFEST_SHA256) -> tuple[dict, dict]:
    manifest_path = payload / "S81-CANDIDATE-MANIFEST.json"
    if sha_file(manifest_path) != expected_manifest_sha:
        raise Refusal("S81 text payload manifest digest differs from the frozen candidate")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if manifest.get("kind") != "s81_hosted_capture_text_payload_manifest":
        raise Refusal("S81 payload manifest kind mismatch")
    rows = manifest.get("required_files")
    if not isinstance(rows, list) or not rows:
        raise Refusal("S81 payload manifest has no required file rows")
    expected: set[str] = set()
    for row in rows:
        rel = row.get("path")
        if not isinstance(rel, str) or rel in expected:
            raise Refusal("S81 payload has an invalid or duplicate path")
        clean = safe_member(rel)
        if clean.as_posix() != rel or PurePosixPath(rel).suffix.lower() in PNG_OR_MEDIA_SUFFIXES:
            raise Refusal(f"S81 candidate payload contains an unapproved media/path entry: {rel}")
        file = payload / rel
        if not file.is_file() or file.is_symlink():
            raise Refusal(f"S81 candidate text file is missing or is a symlink: {rel}")
        data = file.read_bytes()
        try:
            data.decode("utf-8")
        except UnicodeDecodeError:
            raise Refusal(f"S81 candidate payload is not UTF-8 text: {rel}") from None
        if len(data) != row.get("bytes") or sha_bytes(data) != row.get("sha256"):
            raise Refusal(f"S81 candidate text file digest/size mismatch: {rel}")
        expected.add(rel)
    if any(p.is_symlink() for p in payload.rglob("*")):
        raise Refusal("S81 candidate text payload contains a symlink")
    actual = {p.relative_to(payload).as_posix() for p in payload.rglob("*") if p.is_file()}
    if actual != expected | {"S81-CANDIDATE-MANIFEST.json"}:
        raise Refusal("S81 candidate payload has missing or unlisted files")
    try:
        _VERIFY.validate_public_text_rows({rel: (payload / rel).read_bytes() for rel in sorted(actual)})
    except ValueError as exc:
        raise Refusal(str(exc)) from None
    required = {
        "candidate/scenes.js", "candidate/spec.json", "candidate/sources.js",
        "candidate/spec-delta.json", "candidate/capture-plan-source.json",
        "voice-text/S81.words.json", "voice-text/S81.receipt.json",
    }
    if not required <= expected:
        raise Refusal("S81 source builder requires the exact scene/spec/source/word-clock/receipt inputs")
    spec = json.loads((payload / "candidate/spec.json").read_text())
    delta = json.loads((payload / "candidate/spec-delta.json").read_text())
    if (spec.get("id") != "S81" or spec.get("world") != "s81-evidence-route"
            or spec.get("voice", {}).get("duration_s") != DURATION
            or delta.get("kind") != "s81_candidate_spec_delta"
            or delta.get("approval") != "NOT_GRANTED"):
        raise Refusal("S81 locked story identity, duration, or no-approval status changed")
    return manifest, spec


def validate_parent_proof(proof_path: Path, release_metadata_path: Path, repository_metadata_path: Path) -> dict:
    proof_bytes = proof_path.read_bytes()
    if sha_bytes(proof_bytes) != PROOF_SHA256:
        raise Refusal("runtime parent proof digest mismatch")
    proof = json.loads(proof_bytes)
    if (proof.get("parent_release_id") != PARENT_RELEASE_ID
            or proof.get("parent_asset", {}).get("id") != PARENT_ASSET_ID
            or proof.get("parent_asset", {}).get("size") != PARENT_BYTES
            or proof.get("parent_asset", {}).get("digest") != "sha256:" + PARENT_SHA256
            or len(proof.get("generic_runtime_members", {})) != 50):
        raise Refusal("runtime parent proof does not bind the reviewed generic-only release")
    release = json.loads(release_metadata_path.read_text())
    assets = [a for a in release.get("assets", []) if a.get("id") == PARENT_ASSET_ID]
    if (release.get("id") != PARENT_RELEASE_ID or release.get("tag_name") != PARENT_TAG
            or release.get("draft") is not False or release.get("prerelease") is not False
            or len(assets) != 1 or assets[0].get("name") != "source.tar.gz"
            or assets[0].get("size") != PARENT_BYTES
            or assets[0].get("digest") not in (None, "sha256:" + PARENT_SHA256)):
        raise Refusal("live runtime release metadata differs from the pinned proof")
    repository = json.loads(repository_metadata_path.read_text())
    if (repository.get("full_name") != "agmmltd-arch/agmm-render-public"
            or repository.get("private") is not False or repository.get("visibility") != "public"):
        raise Refusal("workflow repository is not the exact public renderer repository")
    return proof


def extract_runtime(archive: Path, members: dict[str, str], destination: Path) -> dict[str, str]:
    if archive.stat().st_size != PARENT_BYTES or sha_file(archive) != PARENT_SHA256:
        raise Refusal("runtime parent archive does not match the pinned release bytes")
    destination.mkdir(parents=True, exist_ok=True)
    if any(destination.iterdir()):
        raise Refusal("refusing to overlay a nonempty runtime destination")
    found: dict[str, str] = {}
    seen: set[str] = set()
    total = 0
    with tarfile.open(archive, "r:gz") as tar:
        entries = tar.getmembers()
        if not entries or len(entries) > 10000:
            raise Refusal("runtime archive member count outside bounds")
        for info in entries:
            rel = safe_member(info.name)
            key = rel.as_posix().rstrip("/")
            if key in seen:
                raise Refusal(f"duplicate normalized runtime path: {key}")
            seen.add(key)
            if not (info.isdir() or info.isfile()) or info.issym() or info.islnk() or info.isdev() or info.isfifo():
                raise Refusal(f"forbidden runtime archive member type: {key}")
            if rel == PurePosixPath("."):
                if not info.isdir():
                    raise Refusal("runtime archive root marker must be a directory")
                continue
            total += info.size
            if total > 750_000_000:
                raise Refusal("runtime archive exceeds the reviewed expansion bound")
            if key not in members or info.isdir():
                continue
            stream = tar.extractfile(info)
            if stream is None:
                raise Refusal(f"runtime member unreadable: {key}")
            rel_out = safe_member(key.removeprefix("s86-a/"))
            target = destination.joinpath(*rel_out.parts)
            target.parent.mkdir(parents=True, exist_ok=True)
            data = stream.read()
            if sha_bytes(data) != members[key]:
                raise Refusal(f"runtime member hash mismatch: {key}")
            target.write_bytes(data)
            found[key] = members[key]
    if found != members:
        raise Refusal("runtime archive did not contain the exact 50-member generic allowlist")
    if any(PurePosixPath(k).suffix.lower() in PNG_OR_MEDIA_SUFFIXES or "/img/" in "/" + k.lower() for k in found):
        raise Refusal("runtime proof unexpectedly includes programme media")
    return found


def extract_exact_logo(brand_zip: Path, member_name: str, destination: Path) -> dict:
    if not member_name or safe_member(member_name).as_posix() != member_name or not member_name.lower().endswith(".svg"):
        raise Refusal("an explicitly named, exact clean .svg member path from the official OpenAI package is required")
    with zipfile.ZipFile(brand_zip) as zf:
        matches = [i for i in zf.infolist() if i.filename == member_name]
        if len(matches) != 1 or matches[0].is_dir() or (matches[0].external_attr >> 16) & 0o170000 == 0o120000:
            raise Refusal("the explicitly named OpenAI logo member is missing, duplicated, or a symlink")
        info = matches[0]
        if info.file_size < 1 or info.file_size > 1_000_000:
            raise Refusal("selected official logo SVG is outside the 1 MB bound")
        data = zf.read(info)
    try:
        root = ElementTree.fromstring(data)
    except ElementTree.ParseError:
        raise Refusal("selected official OpenAI logo is not valid XML/SVG") from None
    if root.tag.rsplit("}", 1)[-1].lower() != "svg":
        raise Refusal("selected official OpenAI brand member is not an SVG root")
    lower = data.decode("utf-8", errors="strict").lower()
    if ("<script" in lower or "foreignobject" in lower or re.search(r"(?:href|src)\s*=\s*['\"]\s*(?:https?:|//|data:)", lower)):
        raise Refusal("selected logo SVG contains executable or external references")
    for element in root.iter():
        for attr, value in element.attrib.items():
            key = attr.rsplit("}", 1)[-1].lower()
            if key.startswith("on") or (key in {"href", "src"} and not value.startswith("#")):
                raise Refusal("selected logo SVG contains an event handler or non-fragment asset reference")
    if re.search(r"url\(\s*['\"]?(?!#)[^)]+", lower):
        raise Refusal("selected logo SVG contains an external style URL")
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_bytes(data)
    return {"path": "media/openai-mark.svg", "sha256": sha_bytes(data), "bytes": len(data),
            "source_url": "https://openai.com/brand/", "package_url": "https://cdn.openai.com/brand/OpenAI-Logos-2025.zip",
            "package_sha256": sha_file(brand_zip), "member": member_name,
            "use": "unchanged company identification; no endorsement implied", "rights_review": "OPEN",
            "guidance_summary": "OpenAI marks are OpenAI property; use only for directly related identification, keep the mark unaltered, do not imply endorsement, and confirm permission/terms before release"}


def make_spec(payload: Path) -> dict:
    words_doc = json.loads((payload / "voice-text/S81.words.json").read_text())
    rows = words_doc.get("words")
    if not isinstance(rows, list) or not rows:
        raise Refusal("locked S81 voice word-clock is missing")
    words = []
    previous = 0.0
    for row in rows:
        word = str(row.get("word") or row.get("text") or "").strip()
        start, end = float(row["start"]), float(row["end"])
        # The authenticated source clock contains one 10 ms inter-word overlap;
        # preserve it while rejecting reordering or materially overlapping rows.
        if not word or not math.isfinite(start) or not math.isfinite(end) or start < previous - 0.05 or end <= start or end > DURATION + 1e-3:
            raise Refusal("locked S81 word-clock is malformed or outside its duration")
        words.append({"word": word, "start": start, "end": end,
                      "emph": bool(row.get("emph") or row.get("emphasis"))})
        previous = end
    return {
        "schema": "agmm-kit3-short-candidate-v1", "id": "S81", "look": "softui",
        "dur": DURATION, "fps": 30, "width": 1080, "height": 1920,
        "captions": [{"from": 0, "to": DURATION, "top": 1280, "height": 360, "maxWords": 4}],
        "words": words, "narration_binding": {"attached_audio": False, "reason": "source-still capture only; exact selected voice remains a separate protected hosted input"},
        "voice": None, "music": None, "images": {},
        "beats": [{"id": "s81-evidence-route", "from": 0.0, "to": DURATION,
                   "comp": "custom", "props": {"scene": "s81-evidence-route"},
                   "field": "none", "tx": "cut", "drift": False, "hold": 0.001}],
        "approval": "NOT_GRANTED", "editorial_status": "NOT_REVIEWED",
        "audio_visual_review": "NOT_PERFORMED", "publication_status": "NOT_REQUESTED",
    }


def make_index() -> str:
    return '''<!doctype html><html><head><meta charset="utf-8"><meta name="viewport" content="width=1080,initial-scale=1"><link rel="stylesheet" href="ds/kit.css"><link rel="stylesheet" href="ds2/kit2.css"><link rel="stylesheet" href="kit3.css"><style>html,body{margin:0;width:1080px;height:1920px;overflow:hidden;background:#f1eee7}#root{position:relative;width:1080px;height:1920px;overflow:hidden}</style></head><body><div id="root" data-composition-id="s81-evidence-route" data-look="softui" data-start="0" data-width="1080" data-height="1920" data-duration="56.365"></div><script>window.AGK_PART={off:0,dur:56.365};window.__timelines={};</script><script src="ds/vendor/gsap.min.js"></script><script src="ds/kit.js"></script><script src="ds2/kit2.js"></script><script src="kit3.js"></script><script src="sources.js"></script><script src="spec.js"></script><script src="scenes.js"></script><script>window.AGK.run(window.AGK_SPEC);</script></body></html>'''


def static_check(look: Path) -> None:
    html = (look / "index.html").read_text()
    for ref in re.findall(r"(?:src|href)=\"([^\"]+)\"", html):
        if ref.startswith(("http:", "https:", "//")) or not (look / ref).is_file():
            raise Refusal(f"external or missing runtime reference in S81 index: {ref}")
    for css in look.rglob("*.css"):
        for raw in re.findall(r"url\(\s*([^)]+)\)", css.read_text()):
            ref = raw.strip(" '\\\"")
            if ref.startswith("data:"):
                continue
            if ref.startswith(("http:", "https:", "//")) or not (css.parent / ref).is_file():
                raise Refusal(f"external or missing CSS asset in S81 runtime: {css.relative_to(look)} -> {ref}")
    if "AGK.run(window.AGK_SPEC)" not in html or "window.S81_SRC" not in (look / "sources.js").read_text():
        raise Refusal("S81 AGK entry or source identity binding is missing")
    scenes = (look / "scenes.js").read_text()
    if 'A.scenes["s81-evidence-route"]' not in scenes or 'media/openai-mark.svg' not in scenes:
        raise Refusal("exact S81 scene or official-mark path is missing")
    guard_path = Path(__file__).with_name("verify_s81_active_frames.py")
    guard_spec = importlib.util.spec_from_file_location("s81_picture_static_guard", guard_path)
    if guard_spec is None or guard_spec.loader is None:
        raise Refusal("S81 picture static guard is unavailable")
    guard = importlib.util.module_from_spec(guard_spec)
    guard_spec.loader.exec_module(guard)
    try:
        guard.validate_hook_source_text(scenes)
        guard.validate_picture_source_text(scenes)
    except ValueError as exc:
        raise Refusal(f"S81 picture source failed static design gate: {exc}") from None
    spec = json.loads((look / "spec.json").read_text())
    if spec.get("id") != "S81" or spec.get("dur") != DURATION or spec.get("voice") is not None or spec.get("music") is not None:
        raise Refusal("S81 source-capture spec must preserve duration and remain silent")
    if spec.get("captions") != [{"from": 0, "to": DURATION, "top": 1280, "height": 360, "maxWords": 4}]:
        raise Refusal("S81 captions must remain in the fixed phrase-safe band with four-word grouping")
    beats = spec.get("beats")
    if (not isinstance(beats, list) or len(beats) != 1
            or beats[0].get("comp") != "custom"
            or beats[0].get("props", {}).get("scene") != "s81-evidence-route"):
        raise Refusal("S81 scene registration must use the pinned kit3 custom component schema")


def static_check_source() -> str:
    return '''from pathlib import Path
import json,re
root=Path(__file__).resolve().parent
html=(root/"index.html").read_text()
for ref in re.findall(r'(?:src|href)="([^"]+)"',html):
    if ref.startswith(("http:","https:","//")) or not (root/ref).is_file(): raise SystemExit("external or missing runtime reference: "+ref)
for css in root.rglob("*.css"):
    for raw in re.findall(r"url\(\s*([^)]+)\)",css.read_text()):
        ref=raw.strip(" '\\\"")
        if ref.startswith("data:"): continue
        if ref.startswith(("http:","https:","//")) or not (css.parent/ref).is_file(): raise SystemExit("external or missing CSS asset: "+str(css.relative_to(root))+" -> "+ref)
spec=json.loads((root/"spec.json").read_text())
if spec.get("id")!="S81" or spec.get("dur")!=56.365 or spec.get("voice") is not None or spec.get("music") is not None: raise SystemExit("S81 source capture must remain silent and duration-bound")
if not (root/"media/openai-mark.svg").is_file(): raise SystemExit("official OpenAI mark missing")
if "AGK.run(window.AGK_SPEC)" not in html: raise SystemExit("AGK entrypoint missing")
print("S81 source composition references PASS; source stills only; no AV approval")
'''


def derive_inactive_optional_css(look: Path, spec: dict, scene_source: str) -> list[dict]:
    """Apply only the two existing S90-verified no-op texture removals to S81 softui."""
    if spec.get("look") != "softui" or not isinstance(spec.get("beats"), list) or not spec["beats"]:
        raise Refusal("optional runtime CSS derivation requires S81 softui composition beats")
    if any(row.get("field") != "none" for row in spec["beats"]):
        raise Refusal("optional CSS derivation requires every S81 native beat field to be none")
    if re.search(r"\b(?:AG\.grain\s*\(|\.k3-f-cork\b|\.ag-grain\b|field\s*:\s*['\"]cork['\"])", scene_source):
        raise Refusal("S81 scene activates a texture whose runtime CSS declaration would be removed")
    kit3 = (look / "kit3.js").read_bytes()
    if sha_bytes(kit3) != PINNED_KIT3_SHA256:
        raise Refusal("pinned kit3 runtime changed before S81 optional CSS derivation")
    if not re.search(r"softui\s*:\s*\{[^}]*field:\s*['\"]soft['\"][^}]*grain:\s*0", kit3.decode("utf-8")):
        raise Refusal("pinned softui runtime no longer proves soft field and zero grain")
    rules = (
        ("ds/kit.css", PINNED_DS_CSS_SHA256, 'background-image: url("img/grain.png");',
         "background-image: none;", "S81 uses no AG.grain and softui is zero-grain"),
        ("kit3.css", PINNED_KIT3_CSS_SHA256,
         ".k3-f-cork { background: #6b4a2b url(ds2/img/eb-cork-tile.jpg);",
         ".k3-f-cork { background: #6b4a2b;", "S81 has no cork field or cork scene class"),
    )
    rows = []
    for rel, expected, before, after, basis in rules:
        path = look / rel
        content = path.read_bytes()
        if sha_bytes(content) != expected:
            raise Refusal(f"pinned runtime CSS changed before S81 derivation: {rel}")
        text = content.decode("utf-8")
        if text.count(before) != 1:
            raise Refusal(f"expected one exact S90-verified optional declaration in {rel}")
        path.write_text(text.replace(before, after, 1), encoding="utf-8")
        rows.append({"path": rel, "parent_sha256": sha_bytes(content),
                     "derived_sha256": sha_file(path), "removed_declaration": before,
                     "replacement": after, "inactivity_basis": basis})
    return rows


def resolve_logo_discovery(brand_zip: Path, discovery_path: Path) -> dict:
    import importlib.util
    discovery_path_module = Path(__file__).with_name("discover_openai_logo.py")
    spec = importlib.util.spec_from_file_location("s81_logo_discovery", discovery_path_module)
    if spec is None or spec.loader is None:
        raise Refusal("official logo discovery helper is unavailable")
    discovery_module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(discovery_module)
    try:
        supplied = json.loads(discovery_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        raise Refusal("hosted official-logo discovery receipt is missing or invalid") from None
    requested_member = supplied.get("selected_member") if isinstance(supplied, dict) else None
    try:
        actual = discovery_module.discover_archive(brand_zip, selected_member=requested_member
            if isinstance(supplied, dict) and supplied.get("status") == "EXPLICIT_APPROVED_SQUARE_SVG_SELECTED" else None)
    except discovery_module.Refusal as exc:
        raise Refusal(str(exc)) from None
    if supplied != actual:
        raise Refusal("official-logo discovery receipt does not bind to the downloaded ZIP metadata")
    if actual.get("status") not in {"UNIQUE_SQUARE_SVG_DISCOVERED", "EXPLICIT_APPROVED_SQUARE_SVG_SELECTED"} or not actual.get("selected_member"):
        raise Refusal("official logo package did not yield exactly one structurally suitable square SVG; human review required")
    return actual

def stage(args: argparse.Namespace) -> dict:
    require_hosted_linux()
    payload = args.payload.resolve()
    manifest, candidate_spec = verify_payload(payload)
    proof = validate_parent_proof(args.runtime_proof, args.release_metadata, args.repository_metadata)
    if args.output.exists():
        raise Refusal("refusing to overwrite existing S81 package output")
    project = args.output / "project"
    look = project / LOOK
    look.mkdir(parents=True)
    used = extract_runtime(args.runtime_archive, proof["generic_runtime_members"], look)
    scene = payload / "candidate/scenes.js"
    sources = payload / "candidate/sources.js"
    (look / "scenes.js").write_bytes(scene.read_bytes())
    (look / "sources.js").write_bytes(sources.read_bytes())
    spec = make_spec(payload)
    (look / "spec.json").write_bytes(canonical_json(spec))
    (look / "spec.js").write_text("window.AGK_SPEC=" + json.dumps(spec, ensure_ascii=False, separators=(",", ":")) + ";\n")
    actual_discovery = resolve_logo_discovery(args.brand_zip, args.logo_discovery)
    logo = extract_exact_logo(args.brand_zip, actual_discovery["selected_member"], look / "media/openai-mark.svg")
    if logo["package_sha256"] != actual_discovery["package_sha256"]:
        raise Refusal("logo extraction package digest differs from the discovery receipt")
    logo["discovery_receipt_sha256"] = sha_file(args.logo_discovery)
    logo["discovery_status"] = actual_discovery["status"]
    logo["human_visual_review"] = "OPEN"
    logo["rights_review"] = "OPEN; see OpenAI brand guidelines; no permission or endorsement claimed"
    css_derivations = derive_inactive_optional_css(look, spec, scene.read_text())
    (look / "index.html").write_text(make_index())
    (look / "static_check.py").write_text(static_check_source())
    # Build a strict local-reference and source identity check; snapshots are not a render or AV review.
    static_check(look)
    sums = []
    for path in sorted(p for p in look.rglob("*") if p.is_file()):
        sums.append(f"{sha_file(path)}  {path.relative_to(look).as_posix()}")
    (look / "SHA256SUMS.txt").write_text("\n".join(sums) + "\n")
    candidate_dir = project / "S81-CANDIDATE"
    shutil.copytree(payload, candidate_dir)
    source_path = args.output / "source.tar.gz"
    with source_path.open("wb") as raw:
        with gzip.GzipFile(fileobj=raw, mode="wb", filename="", mtime=0) as gz:
            with tarfile.open(fileobj=gz, mode="w") as tar:
                for path in sorted(p for p in project.rglob("*") if p.is_file()):
                    rel = path.relative_to(project).as_posix()
                    info = tar.gettarinfo(str(path), arcname=rel)
                    info.uid = info.gid = 0; info.uname = info.gname = ""; info.mtime = 0
                    with path.open("rb") as stream:
                        tar.addfile(info, stream)
    source_sha, source_bytes = sha_file(source_path), source_path.stat().st_size
    frames = round(DURATION * 30)
    parts = {"sha256": source_sha, "bytes": source_bytes, "frames": frames,
             "parts": [{"look": LOOK, "file": "index.html", "out": LOOK, "off": 0.0, "dur": DURATION}]}
    parts_bytes = canonical_json(parts)
    (args.output / "parts.json").write_bytes(parts_bytes)
    # The exact capture helper computes identities from the package's SHA256SUMS; no voice is present.
    import sys
    sys.path.insert(0, str(args.capture_helper.parent))
    import capture_short_package as capture
    normalized = capture.short.validate_parts(parts, project)
    media = capture.media_identities(project, normalized["parts"])
    media_sha = capture.media_identity_sha256(media)
    (args.output / "MEDIA-IDENTITIES.json").write_bytes(canonical_json({"kind": "agmm_short_media_identities", "sha256": media_sha, "files": media}))
    plan_source = json.loads((payload / "candidate/capture-plan-source.json").read_text())
    import sys
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    from compile_s81_capture_plan import compile_plan
    plan = compile_plan(plan_source, parts, source_sha, sha_bytes(parts_bytes), media_sha)
    (args.output / "capture-plan.json").write_bytes(canonical_json(plan))
    return {"kind": "s81_hosted_source_package_receipt", "status": "SOURCE_PACKAGE_STAGED_ON_HOSTED_LINUX_FOR_SOURCE_CAPTURE_ONLY",
            "source_sha256": source_sha, "source_bytes": source_bytes, "parts_sha256": sha_bytes(parts_bytes),
            "parts": 1, "duration_s": DURATION, "frames_at_30fps": frames, "capture_count": len(plan["captures"]),
            "runtime_parent_release_id": PARENT_RELEASE_ID, "runtime_parent_asset_id": PARENT_ASSET_ID,
            "runtime_parent_sha256": PARENT_SHA256, "runtime_generic_members": len(used),
            "candidate_manifest_sha256": sha_file(payload / "S81-CANDIDATE-MANIFEST.json"),
            "scene_sha256": sha_file(scene), "spec_source_sha256": sha_file(payload / "candidate/spec.json"),
            "word_clock_sha256": sha_file(payload / "voice-text/S81.words.json"),
            "runtime_css_derivations": css_derivations,
            "voice_asset": "NOT_INCLUDED; no S81 native hosted voice asset identity was supplied",
            "logo": logo, "editorial_status": "NOT_REVIEWED", "audio_visual_review": "NOT_PERFORMED",
            "approval": "NOT_GRANTED", "publication_status": "NOT_REQUESTED",
            "mac_media_operations": False, "hosted_media_staging": True}


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--payload", type=Path, required=True)
    p.add_argument("--runtime-proof", type=Path, required=True)
    p.add_argument("--release-metadata", type=Path, required=True)
    p.add_argument("--repository-metadata", type=Path, required=True)
    p.add_argument("--runtime-archive", type=Path, required=True)
    p.add_argument("--brand-zip", type=Path, required=True)
    p.add_argument("--logo-discovery", type=Path, required=True)
    p.add_argument("--capture-helper", type=Path, required=True)
    p.add_argument("--output", type=Path, required=True)
    args = p.parse_args()
    try:
        print(json.dumps(stage(args), sort_keys=True))
    except (Refusal, OSError, ValueError, KeyError, zipfile.BadZipFile, tarfile.TarError) as exc:
        raise SystemExit(f"S81 hosted source package refusal: {exc}")


if __name__ == "__main__":
    main()
