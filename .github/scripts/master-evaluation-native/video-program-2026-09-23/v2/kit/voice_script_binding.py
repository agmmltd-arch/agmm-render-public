"""Bind generated voice source text to the current canonical short script."""
from __future__ import annotations
import importlib.util
import json
import os
import re
from functools import lru_cache
from pathlib import Path, PurePosixPath


@lru_cache(maxsize=2)
def _extractor(v2_root: Path):
    prepare = v2_root / "shorts" / "voice" / "tooling" / "prepare.py"
    spec = importlib.util.spec_from_file_location("_agmm_voice_prepare_binding", prepare)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load canonical voice parser: {prepare}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.extract_spoken


def check_voice_script_binding(sid: str, voice_dir: Path, v2_root: Path):
    """Return (MATCH | UNBOUND_LEGACY | REFUSE, reason); read text only."""
    voice_dir, v2_root = Path(voice_dir), Path(v2_root).resolve()
    source_path = voice_dir / "source.json"
    if not source_path.exists():
        return "UNBOUND_LEGACY", "source.json absent; preserve prior readiness rules"
    try:
        metadata = json.loads(source_path.read_text(encoding="utf-8"))
    except Exception as exc:
        return "REFUSE", f"source.json unreadable or invalid: {type(exc).__name__}"
    if not isinstance(metadata, dict):
        return "REFUSE", "source.json must be an object"

    has_file = "script_file" in metadata
    has_text = "full_spoken_text" in metadata
    if not has_file and not has_text:
        return "UNBOUND_LEGACY", "legacy source.json has neither binding field"
    if has_file != has_text:
        return "REFUSE", "partial script binding; both script_file and full_spoken_text are required"
    if metadata.get("id") != sid:
        return "REFUSE", f"source.json id does not match requested {sid}"
    saved_path = metadata.get("script_file")
    saved_text = metadata.get("full_spoken_text")
    if not isinstance(saved_path, str) or not isinstance(saved_text, str):
        return "REFUSE", "script_file and full_spoken_text must be strings"

    # Treat host-absolute paths as identity metadata only. Never open them.
    lexical = PurePosixPath(saved_path.replace("\\", "/"))
    if ".." in lexical.parts or lexical.name != f"{sid}.md":
        return "REFUSE", "script_file has traversal or wrong filename"
    if tuple(lexical.parts[-4:]) != ("v2", "shorts", "scripts-v2", f"{sid}.md"):
        return "REFUSE", "script_file is not under v2/shorts/scripts-v2 for this ID"

    scripts_dir = (v2_root / "shorts" / "scripts-v2").resolve()
    current_script = (scripts_dir / f"{sid}.md").resolve()
    try:
        current_script.relative_to(scripts_dir)
    except ValueError:
        return "REFUSE", "canonical script resolves outside scripts-v2"
    if not current_script.is_file():
        return "REFUSE", "canonical in-tree script is missing"
    try:
        paragraphs = _extractor(v2_root)(current_script.read_text(encoding="utf-8"))
    except Exception as exc:
        return "REFUSE", f"canonical spoken section cannot be extracted: {type(exc).__name__}"
    current_text = " ".join(paragraphs)
    if re.sub(r"\s+", " ", saved_text).strip() != re.sub(r"\s+", " ", current_text).strip():
        return "REFUSE", "voice source text differs from current canonical spoken script"
    return "MATCH", "current canonical spoken script matches voice source.json"
