import hashlib, io, json, os, subprocess, tempfile, unittest, zipfile
from datetime import datetime,timezone,timedelta
from pathlib import Path
from unittest.mock import patch
import export_s86_corrected_master as ex
from export_s86_corrected_master import ExportError
ENV={"GITHUB_ACTIONS":"true","RUNNER_OS":"Linux","GITHUB_REPOSITORY":ex.REPO,"GITHUB_REF":"refs/heads/main","GITHUB_EVENT_NAME":"workflow_dispatch","GITHUB_SHA":"a"*40}
def h(b): return hashlib.sha256(b).hexdigest()
def j(b): return json.dumps(b,indent=2).encode()+b"\n"
class ExportTests(unittest.TestCase):
 def setup_case(self,root,large=False):
  source=(b"s"*9_817_800) if large else b"corrected source archive"; mix=(b"m"*17_452_902) if large else b"synthetic mix"; master=(b"v"*4_000_000) if large else b"synthetic master bytes"
  parts={"parts":ex.EXPECTED_PARTS,"sha256":h(source),"bytes":len(source)}; parts_raw=j(parts)
  source_receipt={"kind":"s86_cta_source_seal","parent":{"tag":"S86-source-quote-37171207319","release_id":402788582,"node_id":"RE_kwDOU05Rms4YAhDm","source_sha256":ex.PARENT_SOURCE_SHA,"parts_sha256":ex.PARENT_PARTS_SHA,"mix_sha256":ex.PARENT_MIX_SHA},"corrected":{"source_sha256":h(source),"source_bytes":len(source),"parts_sha256":h(parts_raw),"parts_bytes":len(parts_raw),"mix_sha256":h(mix),"mix_bytes":len(mix)},"cta_pressed_label":"FOLLOW","editorial_status":"NOT_REVIEWED","approval":"NOT_GRANTED"}
  tag="S86-cta-follow-12345"; source_release={"id":999,"tag_name":tag,"draft":False,"prerelease":False,"assets":[{"name":"source.tar.gz","size":len(source),"digest":"sha256:"+h(source)},{"name":"parts.json","size":len(parts_raw),"digest":"sha256:"+h(parts_raw)},{"name":"mix.wav","size":len(mix),"digest":"sha256:"+h(mix)},{"name":"source-receipt.json","size":len(j(source_receipt)),"digest":"sha256:"+h(j(source_receipt))}]}
  parent={"id":402788582,"node_id":"RE_kwDOU05Rms4YAhDm","tag_name":"S86-source-quote-37171207319","assets":[{"id":608971395,"name":"source.tar.gz","size":9817800,"digest":"sha256:"+ex.PARENT_SOURCE_SHA},{"id":608971394,"name":"parts.json","size":699,"digest":"sha256:"+ex.PARENT_PARTS_SHA},{"id":608971392,"name":"mix.wav","size":17452902,"digest":"sha256:"+ex.PARENT_MIX_SHA},{"id":608971391,"name":"source-receipt.json","size":56219,"digest":"sha256:"+ex.PARENT_RECEIPT_SHA}]}
  inp={"kind":"agmm_short_exact_input_receipt","source_sha256":h(source),"source_bytes":len(source),"parts_sha256":h(parts_raw),"parts_bytes":len(parts_raw),"mix_sha256":h(mix),"duration":60.6,"frames":1818,"part_count":4,"render_4k":True}
  master_row={"file":"FINAL.mp4","sha256":h(master),"bytes":len(master),"resolution":"1080","frames":1818,"full_decode":"PASS","probe":{"format":{"duration":"60.600000"},"streams":[{"codec_type":"video","width":1080,"height":1920},{"codec_type":"audio","sample_rate":"48000","channels":2}]}}
  master4=b"synthetic 4k bytes"; row4={"file":"FINAL-4K.mp4","sha256":h(master4),"bytes":len(master4),"resolution":"4k","full_decode":"PASS"}
  tech={"technical_status":"PASS","editorial_status":"NOT_REVIEWED","masters":[master_row,row4]}; sums=(h(master)+"  FINAL.mp4\n"+h(master4)+"  FINAL-4K.mp4\n"+h(j(tech))+"  TECHNICAL-EVIDENCE.json\n"+h(b"synthetic omitted contact sheet")+"  review/CONTACT-SHEET.jpg\n").encode()
  input_zip=root/"input.zip"; master_zip=root/"master.zip"
  with zipfile.ZipFile(input_zip,"w") as z:
   for n,b in {"INPUT-RECEIPT.json":j(inp),"MATRIX.json":b"{}","NORMALISED-PARTS.json":b"{}","source.tar.gz":source,"parts.json":parts_raw,"mix.wav":mix}.items(): z.writestr(n,b)
  with zipfile.ZipFile(master_zip,"w") as z:
   for n,b in {"FINAL.mp4":master,"FINAL-4K.mp4":master4,"TECHNICAL-EVIDENCE.json":j(tech),"SHA256SUMS.txt":sums}.items(): z.writestr(n,b)
  now=datetime.now(timezone.utc); exp=(now+timedelta(hours=2)).isoformat()
  im={"id":123,"name":"S86-test-EXACT-INPUT","size_in_bytes":input_zip.stat().st_size,"digest":"sha256:"+h(input_zip.read_bytes()),"expired":False,"expires_at":exp,"workflow_run":{"id":77,"head_sha":"b"*40}}
  mm={"id":124,"name":"S86-test-FINAL-MASTERS","size_in_bytes":master_zip.stat().st_size,"digest":"sha256:"+h(master_zip.read_bytes()),"expired":False,"expires_at":exp,"workflow_run":{"id":77,"head_sha":"b"*40}}
  run={"id":77,"event":"workflow_dispatch","status":"completed","conclusion":"success","head_branch":"main","path":".github/workflows/agmm-short-package.yml","head_sha":"b"*40}
  repo={"full_name":ex.REPO,"private":False,"visibility":"public"}; ref={"object":{"sha":ENV["GITHUB_SHA"]}}
  return locals()
 def run_prepare(self,c,**changes):
  args={"run_id":77,"input_id":123,"master_id":124,"repository":c["repo"],"main_ref":c["ref"],"run":c["run"],"input_metadata":c["im"],"master_metadata":c["mm"],"input_zip":c["input_zip"],"master_zip":c["master_zip"],"source_receipt":c["source_receipt"],"parent_release":c["parent"],"source_release":c["source_release"],"out":c["root"]/"out","env":ENV,"system":"Linux"}; args.update(changes)
  return ex.prepare(**args)
 def test_exact_preparation_copy_and_open_status(self):
  with tempfile.TemporaryDirectory() as td:
   c=self.setup_case(Path(td)); result=self.run_prepare(c); output=Path(td)/"out"
   self.assertEqual((output/"S86-FOLLOW-CORRECTED-1080.mp4").read_bytes(),b"synthetic master bytes")
   receipt=json.loads((output/"REVIEW-PLAYBACK-RECEIPT.json").read_text())
   self.assertEqual(receipt["master_sha256"],h(b"synthetic master bytes")); self.assertEqual(receipt["editorial_status"],"NOT_REVIEWED"); self.assertFalse(receipt["full_playback_verified"])
   self.assertEqual(set(result["asset_names"]),ex.INITIAL_FILES)
 def test_pinned_runtime_checksum_inventory_and_technical_hash(self):
  for kind in ("missing_review", "wrong_technical", "unexpected_row"):
   with self.subTest(kind=kind),tempfile.TemporaryDirectory() as td:
    c=self.setup_case(Path(td)); zpath=c["master_zip"]
    with zipfile.ZipFile(zpath) as z: rows={n:z.read(n) for n in z.namelist()}
    lines=rows["SHA256SUMS.txt"].decode().splitlines()
    if kind=="missing_review": lines=[x for x in lines if not x.endswith("review/CONTACT-SHEET.jpg")]
    elif kind=="wrong_technical": lines=[("0"*64+"  TECHNICAL-EVIDENCE.json") if x.endswith("TECHNICAL-EVIDENCE.json") else x for x in lines]
    else: lines.append("0"*64+"  unexpected.txt")
    rows["SHA256SUMS.txt"]=("\n".join(lines)+"\n").encode()
    with zipfile.ZipFile(zpath,"w") as z:
     for n,b in rows.items():z.writestr(n,b)
    c["mm"]["digest"]="sha256:"+h(zpath.read_bytes());c["mm"]["size_in_bytes"]=zpath.stat().st_size
    with self.assertRaisesRegex(ExportError,"checksum"):self.run_prepare(c)
 def test_host_guard_precedes_file_access(self):
  with self.assertRaisesRegex(ExportError,"Ubuntu"):
   ex.prepare(1,2,3,Path("/missing"),Path("/missing"),Path("/missing"),Path("/missing"),Path("/missing"),Path("/missing"),Path("/missing"),{}, {}, {}, Path("/missing"),env={},system="Darwin")
 def test_current_public_main_gate(self):
  repo={"full_name":ex.REPO,"private":False,"visibility":"public"}; sha="a"*40
  ex.validate_repo_main(repo,{"object":{"sha":sha}},sha)
  with self.assertRaises(ExportError): ex.validate_repo_main({**repo,"private":True},{"object":{"sha":sha}},sha)
  with self.assertRaises(ExportError): ex.validate_repo_main(repo,{"object":{"sha":"c"*40}},sha)
 def test_run_metadata_native_schema_and_path(self):
  run={"id":77,"event":"workflow_dispatch","status":"completed","conclusion":"success","head_branch":"main","path":".github/workflows/agmm-short-package.yml","head_sha":"b"*40}
  ex.validate_run(run,77)
  for bad in ({**run,"id":"77"},{**run,"path":"other.yml"},{**run,"conclusion":"failure"}):
   with self.assertRaises(ExportError): ex.validate_run(bad,77)
 def test_native_sized_source_and_mix_and_large_master_are_streamed(self):
  with tempfile.TemporaryDirectory() as td:
   c=self.setup_case(Path(td),large=True); result=self.run_prepare(c)
   target=Path(td)/"out"/"S86-FOLLOW-CORRECTED-1080.mp4"
   self.assertEqual(target.stat().st_size,4_000_000)
   self.assertEqual(ex.file_sha(target),(h(b"v"*4_000_000),4_000_000))
   self.assertEqual(result["master_bytes"],4_000_000)
 def test_hosted_workflow_validates_zip_before_use_and_publishes_before_public_probe(self):
  workflow=Path(__file__).with_name("s86-corrected-master-export.yml").read_text()
  self.assertNotIn("extractall",workflow)
  self.assertLess(workflow.index("validate-release \"$RUNNER_TEMP/s86-export/release.json\""),workflow.index("name: Publish review-only prerelease, then verify public range"))
  self.assertLess(workflow.index("-F draft=false"),workflow.index("verify-range"))
  self.assertNotIn("-f draft=false",workflow)
  self.assertLess(workflow.index("verify-range"),workflow.index("finalize "))
  self.assertLess(workflow.index("finalize "),workflow.index("gh release upload"))
  self.assertEqual(workflow.count("validate-release \"$RUNNER_TEMP/s86-export/release-final.json\""),1)
 def test_native_draft_resolution_and_recovery_branch_precede_typed_publish(self):
  workflow=Path(__file__).with_name("s86-corrected-master-export.yml").read_text()
  self.assertIn("existing_release_id: {description:",workflow)
  self.assertIn("existing_release_run_id: {description:",workflow)
  self.assertIn("select-draft-release",workflow)
  self.assertIn("check-release-absence",workflow)
  self.assertIn('gh api "repos/agmmltd-arch/agmm-render-public/releases/$rid"',workflow)
  self.assertIn("--target-commitish",workflow)
  publish=workflow.index("-F draft=false")
  resolve=workflow.index("name: Create or reuse exact draft and verify native assets")
  self.assertLess(resolve,publish)
  before_publish=workflow[:publish]
  self.assertNotIn('gh api "repos/agmmltd-arch/agmm-render-public/releases/tags/$tag"',before_publish)
  self.assertIn('gh release create "$tag"',before_publish)
  self.assertIn('if [[ -n "$EXISTING_RELEASE_ID" ]]; then',before_publish)
 def test_unique_release_list_selector_requires_exact_tag_target_id_and_draft_state(self):
  tag="S86-cta-follow-review-77"; target="b"*40
  row={"id":403166948,"tag_name":tag,"target_commitish":target,"draft":True,"prerelease":True}
  self.assertEqual(ex.select_unique_draft_release([[row,{"id":2,"tag_name":"other"}]],tag,target,403166948),403166948)
  ex.require_release_tag_absent([[{"id":2,"tag_name":"other"}]],tag)
  for pages,expected_tag,expected_target,expected_id in (
   ([[row,row]],tag,target,403166948),([[row]],"wrong",target,403166948),([[row]],tag,"c"*40,403166948),
   ([[{**row,"id":"403166948"}]],tag,target,403166948),([[{**row,"draft":False}]],tag,target,403166948),
   ([[{**row,"prerelease":False}]],tag,target,403166948),([[row]],tag,target,403166949),
  ):
   with self.subTest(pages=pages,expected_tag=expected_tag,expected_target=expected_target,expected_id=expected_id),self.assertRaises(ExportError):
    ex.select_unique_draft_release(pages,expected_tag,expected_target,expected_id)
  with self.assertRaisesRegex(ExportError,"already exists"):
   ex.require_release_tag_absent([[row]],tag)
 def test_recovery_draft_must_match_all_six_native_asset_hashes_sizes_and_target(self):
  with tempfile.TemporaryDirectory() as td:
   c=self.setup_case(Path(td)); self.run_prepare(c); output=Path(td)/"out"
   tag="S86-cta-follow-review-77"; target="2c0d8b383df93d22601ca49a373b4c184c0e5409"
   inventory={"tag":tag,"assets":ex.asset_inventory(output)}
   rows=[{"name":name,"state":"uploaded","size":asset["size"],"digest":asset["digest"]} for name,asset in inventory["assets"].items()]
   draft={"id":403166948,"tag_name":tag,"target_commitish":target,"draft":True,"prerelease":True,"assets":rows}
   ex.validate_release_assets(draft,403166948,inventory,target_commitish=target)
   for changed,release_id,expected_target in (
    ({**draft,"assets":rows[:-1]},403166948,target),
    ({**draft,"assets":[*rows[:-1],{**rows[-1],"digest":"sha256:"+"0"*64}]},403166948,target),
    ({**draft,"target_commitish":"f"*40},403166948,target),
   (draft,403166949,target),
   ):
    with self.subTest(changed=changed,release_id=release_id,expected_target=expected_target),self.assertRaises(ExportError):
     ex.validate_release_assets(changed,release_id,inventory,target_commitish=expected_target)
 def test_validate_release_cli_json_inventory_roundtrip_and_malformed_refusal(self):
  tag="S86-cta-follow-review-77"; target="a"*40
  release={"id":403166948,"tag_name":tag,"target_commitish":target,"draft":True,"prerelease":True,"assets":[{"name":"only.txt","state":"uploaded","size":4,"digest":"sha256:deadbeef"}]}
  with tempfile.TemporaryDirectory() as td:
   p=Path(td); (p/"release.json").write_text(json.dumps(release))
   inventory={"tag":tag,"assets":{"only.txt":{"size":4,"digest":"sha256:deadbeef"}}}
   inv=p/"inventory.json"; inv.write_text(json.dumps(inventory))
   args=["export_s86_corrected_master.py","validate-release",str(p/"release.json"),str(inv),"--release-id","403166948","--target-commitish",target]
   with patch.dict(os.environ,ENV,clear=True),patch.object(ex.platform,"system",return_value="Linux"),patch("sys.argv",args),patch("sys.stdout",io.StringIO()):
    ex.main()
   for bad in (
    {"tag":tag,"assets":{"only.txt":{"size":5,"digest":"sha256:deadbeef"}}},
    {"tag":tag,"assets":{"only.txt":{"size":4,"digest":"sha256:"+"0"*64}}},
    {"tag":tag,"assets":{"only.txt":{"size":"4","digest":"sha256:deadbeef"}}},
   ):
    inv.write_text(json.dumps(bad))
    with patch.dict(os.environ,ENV,clear=True),patch.object(ex.platform,"system",return_value="Linux"),patch("sys.argv",args),patch("sys.stdout",io.StringIO()),self.assertRaises(ExportError):
     ex.main()
 def test_prepare_owns_output_directory_creation_and_refuses_existing_directory(self):
  workflow=Path(__file__).with_name("s86-corrected-master-export.yml").read_text()
  step=workflow.split("name: Download exact render artifacts on Ubuntu and prepare unchanged master",1)[1].split("name: Build exact expected release inventory",1)[0]
  self.assertNotIn('mkdir -p "$RUNNER_TEMP/s86-export/out"',step)
  self.assertIn('--out "$RUNNER_TEMP/s86-export/out"',step)
  with tempfile.TemporaryDirectory() as td:
   c=self.setup_case(Path(td)); output=Path(td)/"runner"/"s86-export"/"out"
   output.parent.mkdir(parents=True)
   self.assertFalse(output.exists())
   self.run_prepare(c,out=output)
   self.assertTrue(output.is_dir())
  with tempfile.TemporaryDirectory() as td:
   c=self.setup_case(Path(td)); runner_temp=Path(td)/"runner"; output=runner_temp/"s86-export"/"out"
   (runner_temp/"s86-export").mkdir(parents=True)
   # Execute the exact removed workflow command to prove it recreates the hosted failure.
   subprocess.run(["bash","-eu","-c",'mkdir -p "$RUNNER_TEMP/s86-export/out"'],env={**os.environ,"RUNNER_TEMP":str(runner_temp)},check=True)
   with self.assertRaises(FileExistsError): self.run_prepare(c,out=output)
 def test_tag_absence_only_exact_404(self):
  ex.validate_absence(404,{"message":"Not Found"})
  for status in (0,200,401,403,500):
   with self.subTest(status=status),self.assertRaises(ExportError): ex.validate_absence(status,{"message":"Forbidden"})
 def test_input_or_master_artifact_id_shape_rejected(self):
  with tempfile.TemporaryDirectory() as td:
   c=self.setup_case(Path(td)); c["im"]["id"]="123"
   with self.assertRaises(ExportError): self.run_prepare(c)
 def test_parts_timeline_drift_rejected(self):
  with tempfile.TemporaryDirectory() as td:
   c=self.setup_case(Path(td)); c["source_receipt"]["corrected"]["parts_sha256"]="f"*64
   with self.assertRaises(ExportError): self.run_prepare(c)
 def test_archive_bad_paths_types_and_duplicate_names_rejected(self):
  with tempfile.TemporaryDirectory() as td:
   for names in (("../evil",),("dup","dup")):
    p=Path(td)/f"{len(list(Path(td).iterdir()))}.zip"
    with zipfile.ZipFile(p,"w") as z:
     for name in names: z.writestr(name,b"x")
    with self.assertRaises(ExportError): ex._zip_members(p,"master")
 def test_full_workflow_output_requires_native_4k_enabled_artifact_shape(self):
  with tempfile.TemporaryDirectory() as td:
   c=self.setup_case(Path(td));
   with zipfile.ZipFile(c["master_zip"],"w") as z:
    z.writestr("FINAL.mp4",b"synthetic master bytes"); z.writestr("TECHNICAL-EVIDENCE.json",j({"technical_status":"PASS","editorial_status":"NOT_REVIEWED","masters":[]})); z.writestr("SHA256SUMS.txt",b"0"*64+b"  FINAL.mp4\n")
   c["mm"]["size_in_bytes"]=c["master_zip"].stat().st_size; c["mm"]["digest"]="sha256:"+h(c["master_zip"].read_bytes())
   with self.assertRaises(ExportError): self.run_prepare(c)
 def test_workflow_four_asset_source_publish_exact_set(self):
  with tempfile.TemporaryDirectory() as td:
   c=self.setup_case(Path(td)); self.run_prepare(c)
   assets=c["source_release"]["assets"]
   names={a["name"] for a in assets}
   self.assertEqual(names,{"source.tar.gz","source-receipt.json","parts.json","mix.wav"})
   parts={"parts":ex.EXPECTED_PARTS,"sha256":h(b"corrected source archive"),"bytes":len(b"corrected source archive")}
   for bad in (assets[:-1],assets+[dict(assets[0])]):
    changed={**c["source_release"],"assets":bad}
    with self.assertRaises(ExportError): ex.validate_source_provenance(c["parent"],changed,c["source_receipt"],parts,h(b"synthetic mix"))
 def test_provenance_mismatch_refused(self):
  with tempfile.TemporaryDirectory() as td:
   c=self.setup_case(Path(td)); c["source_release"]["id"]="999"
   with self.assertRaises(ExportError): self.run_prepare(c)
 def test_checksum_and_technical_receipt_mismatch_refused(self):
  with tempfile.TemporaryDirectory() as td:
   c=self.setup_case(Path(td))
   with zipfile.ZipFile(c["master_zip"],"w") as z:
    z.writestr("FINAL.mp4",b"wrong master"); z.writestr("TECHNICAL-EVIDENCE.json",j({"technical_status":"PASS","editorial_status":"NOT_REVIEWED","masters":[]})); z.writestr("SHA256SUMS.txt",b"0"*64+b"  FINAL.mp4\n")
   c["mm"]["size_in_bytes"]=c["master_zip"].stat().st_size;c["mm"]["digest"]="sha256:"+h(c["master_zip"].read_bytes())
   with self.assertRaises(ExportError): self.run_prepare(c)
 def test_range_status_exact(self):
  class Response:
   status=206
   headers={"Content-Range":"bytes 0-0/22"}
   def geturl(self): return "https://release-assets.githubusercontent.com/asset"
   def read(self,n): return b"x"
   def __enter__(self): return self
   def __exit__(self,*a): pass
  class Opener:
   def open(self,*a,**kw): return Response()
  url=f"https://github.com/{ex.REPO}/releases/download/S86-cta-follow-review-77/S86-FOLLOW-CORRECTED-1080.mp4"
  self.assertEqual(ex.range_probe(url,22,"S86-cta-follow-review-77",Opener())["bytes_read"],1)
  class Bad(Opener):
   def open(self,*a,**kw):
    Response.status=403
    return Response()
  with self.assertRaises(ExportError): ex.range_probe(url,22,"S86-cta-follow-review-77",Bad())
 def test_release_id_and_asset_binding(self):
  release={"id":5,"tag_name":"tag","target_commitish":"a"*40,"draft":True,"prerelease":True,"assets":[{"name":"x","state":"uploaded","size":1,"digest":"sha256:a"}]}
  expected={"tag":"tag","assets":{"x":(1,"sha256:a")}}
  ex.validate_release_assets(release,5,expected,target_commitish="a"*40)
  with self.assertRaises(ExportError): ex.validate_release_assets({"id":"5","tag_name":"tag","draft":True,"prerelease":True,"assets":[]},5,{"tag":"tag","assets":{}})
  with self.assertRaisesRegex(ExportError,"target commit"): ex.validate_release_assets(release,5,expected,target_commitish="b"*40)
if __name__=="__main__": unittest.main()
