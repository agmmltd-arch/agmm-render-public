"""Text-only S83 static runtime contract and mutation regressions.

No browser, screenshot, programme media, network, or audio is opened here.
"""
from __future__ import annotations
import hashlib
import html.parser
import json
import os
import re
import subprocess
import shutil
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent
GSAP_PATH = "assets/gsap.min.js"
GSAP_SHA256 = "c174bfce53a729418d57a8ad8625e7247c793a22fef8e2851e3cfa3de9cd8280"
GSAP_GIT_BLOB = "fde57af06cc445f47ca2a6fc1232ec04666346d4"
EXPECTED_CLIPS = [
    ("s1", "0", "7.815", "0"),
    ("s2", "7.815", "10.804", "1"),
    ("s3", "18.619", "9.838", "2"),
    ("evidence-turn", "28.457", "16.444", "3"),
    ("s6", "44.901", "6.034", "5"),
    ("s7", "50.935", "5.598333", "6"),
]

class ContractParser(html.parser.HTMLParser):
    def __init__(self):
        super().__init__(); self.root_attrs = None; self.clips = []; self.scripts = []
        self.in_root = False; self.in_script = False; self.script_attrs = None; self.script_text = []
    def handle_starttag(self, tag, attrs):
        a=dict(attrs)
        if tag == "main" and a.get("id") == "root": self.root_attrs=a; self.in_root=True
        if tag == "section" and "clip" in a.get("class", "").split(): self.clips.append(a)
        if tag == "script": self.script_attrs=a; self.scripts.append(a); self.in_script=True; self.script_text=[]
    def handle_endtag(self, tag):
        if tag == "main": self.in_root=False
        if tag == "script": self.in_script=False
    def handle_data(self, data):
        if self.in_script: self.script_text.append(data)

def validate(tree: Path) -> None:
    html=(tree/"index.html").read_text()
    vendor=tree/GSAP_PATH
    if vendor.is_symlink() or not vendor.is_file(): raise ValueError("pinned GSAP runtime missing")
    data=vendor.read_bytes()
    if hashlib.sha256(data).hexdigest()!=GSAP_SHA256: raise ValueError("pinned GSAP runtime altered")
    if b"GSAP 3.14.2" not in data[:512] or b"https://gsap.com/standard-license" not in data[:1024]:
        raise ValueError("GSAP version/license header missing")
    doc=json.loads((tree/"CANDIDATE-MANIFEST.json").read_text())
    provenance=doc.get("vendored_runtime_assets", {}).get(GSAP_PATH)
    if provenance != {"package":"gsap","version":"3.14.2","source_sha256":GSAP_SHA256,
                      "source_git_blob_sha1":GSAP_GIT_BLOB,
                      "license":"GSAP Standard 'no charge' license; notice retained in source",
                      "license_url":"https://gsap.com/community/standard-license/"}:
        raise ValueError("GSAP provenance missing or changed")
    p=ContractParser(); p.feed(html)
    if not p.root_attrs: raise ValueError("HyperFrames root missing")
    attrs=p.root_attrs
    if (attrs.get("data-composition-id"),attrs.get("data-root"),attrs.get("data-width"),attrs.get("data-height"),attrs.get("data-duration")) != ("s83","true","1080","1920","56.533333"):
        raise ValueError("HyperFrames composition root contract changed")
    clips=[]
    for a in p.clips:
        classes=a.get("class","").split()
        name=next((c for c in classes if c in {x[0] for x in EXPECTED_CLIPS}),None)
        if name: clips.append((name,a.get("data-start"),a.get("data-duration"),a.get("data-track-index")))
    if clips != EXPECTED_CLIPS: raise ValueError("authored scene clip timing/track contract changed")
    gsap_tag=[s for s in p.scripts if s.get("src")==GSAP_PATH]
    if len(gsap_tag)!=1: raise ValueError("composition must load exactly one pinned GSAP script")
    # Use source positions to prove the global bundle/registry guards run before GSAP timeline use.
    if html.index(f'<script src="{GSAP_PATH}"></script>') > html.index('id="word-data"'):
        raise ValueError("GSAP must load before the composition inline script")
    registry_init="window.__timelines = window.__timelines || {};"
    if registry_init not in html: raise ValueError("HyperFrames timeline registry initialization missing")
    guard="if (typeof window.__timelines !== 'object' || Array.isArray(window.__timelines)) throw new Error('HyperFrames timeline registry is invalid');"
    if guard not in html: raise ValueError("HyperFrames timeline registry type guard missing")
    required=("window.gsap.timeline", registry_init, guard, "gsap.timeline({ paused: true })", "window.__timelines.s83 = tl;")
    positions=[html.find(token) for token in required]
    if any(pos<0 for pos in positions): raise ValueError("GSAP/HyperFrames runtime guard or timeline registration missing")
    if not positions[0] < positions[1] < positions[2] < positions[3]:
        raise ValueError("runtime guards must precede timeline creation and registration")
    if html.count("data-composition-id=\"s83\"") != 1: raise ValueError("composition identity is ambiguous")

def validate_workflow_staging_paths(tree: Path, workflow_text: str) -> None:
    if 'cd "$CANDIDATE"' not in workflow_text:
        raise ValueError("workflow does not establish candidate working directory")
    if 'static_tree="$RUNNER_TEMP/s83-static-tree"' not in workflow_text:
        raise ValueError("workflow static tree staging block missing")
    block=workflow_text.split('static_tree="$RUNNER_TEMP/s83-static-tree"',1)[1].split('npx --yes hyperframes@0.8.71 lint',1)[0]
    sources=re.findall(r'install -m 0644 ([^ \n]+)',block)
    if sources != ["index.html","assets/gsap.min.js"]:
        raise ValueError("static staging source paths drifted from candidate working directory")
    for rel in sources:
        source=tree/rel
        if source.is_symlink() or not source.is_file(): raise ValueError("static staging source missing from cwd: "+rel)

def execute_static_staging(workspace: Path, candidate_rel: str, runner_temp: Path, workflow_text: str) -> subprocess.CompletedProcess:
    block=workflow_text.split('static_tree="$RUNNER_TEMP/s83-static-tree"',1)[1].split('npx --yes hyperframes@0.8.71 lint',1)[0]
    shell='set -euo pipefail\ncd "$CANDIDATE"\nstatic_tree="$RUNNER_TEMP/s83-static-tree"'+block
    env=os.environ.copy(); env.update(CANDIDATE=candidate_rel,RUNNER_TEMP=str(runner_temp))
    return subprocess.run(["bash","-euo","pipefail","-c",shell],cwd=workspace,env=env,capture_output=True,text=True)

class RuntimeContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls): cls.original=(ROOT/"index.html").read_text(); cls.manifest=(ROOT/"CANDIDATE-MANIFEST.json").read_text(); cls.vendor=(ROOT/GSAP_PATH).read_bytes()
    def test_current_candidate_contract(self): validate(ROOT)
    def test_workflow_static_staging_resolves_from_candidate_cwd(self):
        workflow=(ROOT/"s83-source-capture.workflow.yml").read_text(); validate_workflow_staging_paths(ROOT,workflow)
        with tempfile.TemporaryDirectory() as td:
            workspace=Path(td); candidate=workspace/".github/candidates/S83"; (candidate/"assets").mkdir(parents=True)
            (candidate/"index.html").write_bytes((ROOT/"index.html").read_bytes()); (candidate/GSAP_PATH).write_bytes((ROOT/GSAP_PATH).read_bytes())
            runner=workspace/"runner-temp"; result=execute_static_staging(workspace,".github/candidates/S83",runner,workflow)
            self.assertEqual(result.returncode,0,result.stderr)
            self.assertEqual((runner/"s83-static-tree/index.html").read_bytes(),(candidate/"index.html").read_bytes())
            self.assertEqual((runner/f"s83-static-tree/{GSAP_PATH}").read_bytes(),(candidate/GSAP_PATH).read_bytes())
            self.assertTrue((runner/"s83-static-tree/assets/wht-mark.png").is_file())
    def test_workflow_double_candidate_prefix_is_rejected(self):
        workflow=(ROOT/"s83-source-capture.workflow.yml").read_text().replace('install -m 0644 index.html','install -m 0644 $CANDIDATE/index.html')
        with self.assertRaisesRegex(ValueError,"source paths drifted"): validate_workflow_staging_paths(ROOT,workflow)
        with tempfile.TemporaryDirectory() as td:
            workspace=Path(td); candidate=workspace/".github/candidates/S83"; (candidate/"assets").mkdir(parents=True)
            (candidate/"index.html").write_bytes((ROOT/"index.html").read_bytes()); (candidate/GSAP_PATH).write_bytes((ROOT/GSAP_PATH).read_bytes())
            result=execute_static_staging(workspace,".github/candidates/S83",workspace/"runner-temp",workflow)
            self.assertNotEqual(result.returncode,0)
    def with_tree(self, mutate):
        with tempfile.TemporaryDirectory() as td:
            d=Path(td); (d/"assets").mkdir(); (d/"index.html").write_text(self.original); (d/"CANDIDATE-MANIFEST.json").write_text(self.manifest); (d/GSAP_PATH).write_bytes(self.vendor); mutate(d)
            return d
    def test_missing_gsap_script_rejected(self):
        with tempfile.TemporaryDirectory() as td:
            d=Path(td); (d/"assets").mkdir(); (d/"index.html").write_text(self.original.replace('  <script src="assets/gsap.min.js"></script>\n','')); (d/"CANDIDATE-MANIFEST.json").write_text(self.manifest); (d/GSAP_PATH).write_bytes(self.vendor)
            with self.assertRaisesRegex(ValueError,"exactly one pinned GSAP"): validate(d)
    def test_missing_gsap_vendor_rejected(self):
        with tempfile.TemporaryDirectory() as td:
            d=Path(td); (d/"assets").mkdir(); (d/"index.html").write_text(self.original); (d/"CANDIDATE-MANIFEST.json").write_text(self.manifest)
            with self.assertRaisesRegex(ValueError,"runtime missing"): validate(d)
    def test_missing_timeline_registry_initialization_rejected(self):
        broken=self.original.replace("window.__timelines = window.__timelines || {};\n","")
        with tempfile.TemporaryDirectory() as td:
            d=Path(td); (d/"assets").mkdir(); (d/"index.html").write_text(broken); (d/"CANDIDATE-MANIFEST.json").write_text(self.manifest); (d/GSAP_PATH).write_bytes(self.vendor)
            with self.assertRaisesRegex(ValueError,"registry initialization missing"): validate(d)
    def test_changed_vendor_rejected(self):
        with tempfile.TemporaryDirectory() as td:
            d=Path(td); (d/"assets").mkdir(); (d/"index.html").write_text(self.original); (d/"CANDIDATE-MANIFEST.json").write_text(self.manifest); (d/GSAP_PATH).write_bytes(self.vendor+b" ")
            with self.assertRaisesRegex(ValueError,"altered"): validate(d)
    def test_changed_scene_timing_rejected(self):
        with tempfile.TemporaryDirectory() as td:
            d=Path(td); (d/"assets").mkdir(); (d/"index.html").write_text(self.original.replace('data-start="0" data-duration="7.815"','data-start="0" data-duration="7.816"',1)); (d/"CANDIDATE-MANIFEST.json").write_text(self.manifest); (d/GSAP_PATH).write_bytes(self.vendor)
            with self.assertRaisesRegex(ValueError,"timing/track"): validate(d)
    def test_manifest_provenance_drift_rejected(self):
        doc=json.loads(self.manifest); doc["vendored_runtime_assets"]={GSAP_PATH:{"package":"gsap","version":"3.14.1"}}
        with tempfile.TemporaryDirectory() as td:
            d=Path(td); (d/"assets").mkdir(); (d/"index.html").write_text(self.original); (d/"CANDIDATE-MANIFEST.json").write_text(json.dumps(doc)); (d/GSAP_PATH).write_bytes(self.vendor)
            with self.assertRaisesRegex(ValueError,"provenance"): validate(d)

if __name__ == "__main__": unittest.main(verbosity=2)
