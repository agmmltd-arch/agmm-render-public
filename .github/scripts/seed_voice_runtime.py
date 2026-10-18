#!/usr/bin/env python3
"""Ubuntu dependency and exact existing-model cache closure; never generates."""
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
from voice_effects import host
from voice_hosted import source_closure

MODELS = {
    "Systran/faster-whisper-small.en": "d1d751a5f8271d482d14ca55d9e2deeebbae577f",
    "Systran/faster-whisper-base.en": "3d3d5dee26484f91867d81cb899cfcf72b96be6c",
}
FILES = ["config.json", "model.bin", "tokenizer.json", "vocabulary.txt"]


def main():
    host()
    source_closure()
    from huggingface_hub import snapshot_download
    import faster_whisper
    import numpy
    need = lambda x: x or (_ for _ in ()).throw(RuntimeError("runtime closure failed"))
    records = []
    for repo, revision in MODELS.items():
        path = Path(snapshot_download(repo_id=repo, revision=revision, allow_patterns=FILES))
        need(path.name == revision and all((path / name).is_file() for name in FILES))
        alias = path.parent.parent / "refs/main"
        alias.parent.mkdir(exist_ok=True)
        alias.write_text(revision)
        need(Path(snapshot_download(repo_id=repo, local_files_only=True)).name == revision)
        records.append({"repository": repo, "revision": revision,
                        "files": [{"name": name, "bytes": (path / name).stat().st_size} for name in FILES]})
    os.environ["HF_HUB_OFFLINE"] = "1"
    # Bare imports resolve the complete source graph without model inference,
    # waveform decoding or provider calls. All main entry points stay inactive.
    here = Path(__file__).resolve().parent
    native = here / "voice-native"
    short = native / "shorts/voice/tooling"
    film = native / "films/voice/tooling"
    sys.path[:0] = [str(short), str(film), str(native / "sound/v2"), str(native / "kit"),
                    str(native / "kit/tools"), str(native / "kit/platforms"), str(native / "films/tools"), str(native / "crew")]
    imported = []
    ast_only = []
    for path in sorted(native.rglob("*.py")):
        if path.name == "key_green.py":
            # This original CLI reads image argv at import time. Qualify syntax
            # and PIL dependency, never execute it as a misleading bare import.
            import ast
            from PIL import Image
            ast.parse(path.read_text())
            ast_only.append(str(path.relative_to(native)))
            continue
        if path.name == "voice_pitch.py":
            subprocess.run(["/Users/samwall/alfred/venvs/pitch/bin/python", "-c",
                            "import runpy,sys; runpy.run_path(sys.argv[1],run_name='closure_import')", str(path)], check=True)
            imported.append(str(path.relative_to(native)))
            continue
        spec = importlib.util.spec_from_file_location("closure_" + path.stem, path)
        module = importlib.util.module_from_spec(spec)
        sys.modules[spec.name] = module
        spec.loader.exec_module(module)
        imported.append(str(path.relative_to(native)))
    out = Path(sys.argv[1])
    out.mkdir(parents=True, exist_ok=True)
    pitch = subprocess.run(["/Users/samwall/alfred/venvs/pitch/bin/python", "-c",
                            "import json,numpy,parselmouth; print(json.dumps({'numpy':numpy.__version__,'praat':parselmouth.__version__}))"],
                           check=True, capture_output=True, text=True)
    receipt = {"status": "HOSTED_DEPENDENCY_IMPORT_CLOSURE_ONLY", "python": sys.version,
               "numpy": numpy.__version__, "pitch_environment": json.loads(pitch.stdout),
               "models": records, "imports": imported, "cli_ast_only": ast_only,
               "pip_freeze": subprocess.run([sys.executable, "-m", "pip", "freeze"], check=True,
                                              text=True, capture_output=True).stdout.splitlines(),
               "ffmpeg": subprocess.run(["ffmpeg", "-version"], check=True, text=True,
                                          capture_output=True).stdout.splitlines()[0],
               "voice_generated": False, "provider_calls": 0, "approval": False}
    (out / "RUNTIME-CLOSURE.json").write_text(json.dumps(receipt, indent=2) + "\n")


if __name__ == "__main__":
    main()
