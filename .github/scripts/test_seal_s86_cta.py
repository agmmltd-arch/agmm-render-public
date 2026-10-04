import hashlib, io, json, tarfile, tempfile, unittest
from unittest.mock import patch
import seal_s86_cta as core
from pathlib import Path
from seal_s86_cta import (
    INSERT, REPLACEMENT, PARENT_PARTS_SHA, PARENT_SOURCE_SHA, PARENT_MIX_SHA,
    PARENT_RELEASE_ID, PARENT_NODE_ID, PARENT_TAG, PARENT_ASSETS,
    SealError, seal, require_hosted, validate_repository_and_head,
    validate_parent_release, release_absence_result,
)
ENV={"GITHUB_ACTIONS":"true","RUNNER_OS":"Linux","GITHUB_REPOSITORY":"agmmltd-arch/agmm-render-public","GITHUB_REF":"refs/heads/main","GITHUB_EVENT_NAME":"workflow_dispatch","GITHUB_SHA":"a"*40}

def h(b): return hashlib.sha256(b).hexdigest()

class SealTests(unittest.TestCase):
    def archive(self, root, spec=None, sums_override=None, extra=None):
        spec=spec or b'{"kind": "cta",\n"button": "FOLLOW",\n}'
        files={"pkg/s86-d/spec.js":spec,"pkg/s86-d/keep.txt":b"keep"}
        sums="".join(f"{h(v)}  ./{Path(k).name}\n" for k,v in files.items()).encode()
        files["pkg/s86-d/SHA256SUMS.txt"]=sums if sums_override is None else sums_override
        if extra: files.update(extra)
        p=root/"parent.tar.gz"
        with tarfile.open(p,"w:gz") as tf:
            for n,b in files.items():
                ti=tarfile.TarInfo(n); ti.size=len(b); tf.addfile(ti,io.BytesIO(b))
        return p
    def inputs(self, root, source, parts_extra=None):
        parts={"parts":core.EXPECTED_PARTS,"sha256":h(source.read_bytes()),"bytes":source.stat().st_size}
        if parts_extra: parts.update(parts_extra)
        pp=root/"parts.json"; pp.write_text(json.dumps(parts))
        mix=root/"mix.wav"; mix.write_bytes(b"synthetic audio bytes")
        return pp,mix
    def run_seal(self,src,pp,mix,root,**kw):
        pin_source=h(src.read_bytes()); pin_parts=h(pp.read_bytes()); pin_mix=h(b"synthetic audio bytes")
        with patch.multiple(core,PARENT_SOURCE_SHA=pin_source,PARENT_PARTS_SHA=pin_parts,PARENT_MIX_SHA=pin_mix):
            args={"parent_tag":PARENT_TAG,"parent_release_id":PARENT_RELEASE_ID,"parent_source_sha":pin_source,"parent_parts_sha":pin_parts,"parent_mix_sha":pin_mix,"env":ENV,"system":"Linux"}; args.update(kw)
            return core.seal(src,pp,mix,root/"parts-out.json",root/"corrected.tar.gz",root/"receipt.json",**args)
    def test_exact_patch_rebind_and_inventory(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td); src=self.archive(root); pp,mix=self.inputs(root,src)
            result=self.run_seal(src,pp,mix,root)
            with tarfile.open(src,"r:gz") as a,tarfile.open(root/"corrected.tar.gz","r:gz") as b:
                old={m.name:a.extractfile(m).read() for m in a.getmembers() if m.isfile()}
                new={m.name:b.extractfile(m).read() for m in b.getmembers() if m.isfile()}
            self.assertEqual(new["pkg/s86-d/spec.js"],old["pkg/s86-d/spec.js"].replace(INSERT,REPLACEMENT))
            self.assertEqual(new["pkg/s86-d/keep.txt"],old["pkg/s86-d/keep.txt"])
            self.assertEqual({k for k in old if old[k]!=new[k]},{"pkg/s86-d/spec.js","pkg/s86-d/SHA256SUMS.txt"})
            outparts=json.loads((root/"parts-out.json").read_text())
            self.assertEqual(outparts["parts"],json.loads(pp.read_text())["parts"])
            self.assertEqual(outparts["sha256"],h((root/"corrected.tar.gz").read_bytes()))
            self.assertEqual(result["parent"]["tag"],PARENT_TAG)
            self.assertEqual(result["parent"]["release_id"],PARENT_RELEASE_ID)
            self.assertEqual(result["corrected"]["parts_sha256"],h((root/"parts-out.json").read_bytes()))
            self.assertEqual(result["only_changed_members"], ["pkg/s86-d/spec.js","pkg/s86-d/SHA256SUMS.txt"])
    def test_native_root_directory_and_unprefixed_parts(self):
        for prefix in ("", "./"):
            with self.subTest(prefix=prefix), tempfile.TemporaryDirectory() as td:
                root=Path(td); src=self.archive(root)
                with tarfile.open(src,"r:gz") as tf:
                    rows=[(m,tf.extractfile(m).read()) for m in tf.getmembers()]
                with tarfile.open(src,"w:gz") as tf:
                    directory=tarfile.TarInfo("."); directory.type=tarfile.DIRTYPE;tf.addfile(directory)
                    for m,data in rows:
                        m.name=prefix+m.name.removeprefix("pkg/");tf.addfile(m,io.BytesIO(data))
                pp,mix=self.inputs(root,src); result=self.run_seal(src,pp,mix,root)
                with tarfile.open(root/"corrected.tar.gz","r:gz") as tf:
                    self.assertEqual(tf.getmembers()[0].name,".")
                    self.assertTrue(tf.getmembers()[0].isdir())
                    self.assertIn(REPLACEMENT,tf.extractfile(prefix+"s86-d/spec.js").read())
    def test_root_file_or_normalized_duplicate_is_rejected(self):
        for names in ((".",), ("x", "./x")):
            with tempfile.TemporaryDirectory() as td:
                path=Path(td)/"bad.tar.gz"
                with tarfile.open(path,"w:gz") as tf:
                    for name in names:
                        m=tarfile.TarInfo(name);m.size=1;tf.addfile(m,io.BytesIO(b"x"))
                with tarfile.open(path,"r:gz") as tf, self.assertRaises(SealError):core._inventory(tf)
    def test_cli_host_guard_precedes_path_access(self):
        with self.assertRaisesRegex(SealError,"Ubuntu only"):
            seal(Path("/missing/source"),Path("/missing/parts"),Path("/missing/mix"),Path("/tmp/p"),Path("/tmp/o"),Path("/tmp/r"),env={},system="Darwin")
        with self.assertRaises(SealError): require_hosted({**ENV,"GITHUB_REF":"refs/heads/other"},"Linux")
    def test_exact_public_main_guard(self):
        repo={"full_name":"agmmltd-arch/agmm-render-public","private":False,"visibility":"public"}
        validate_repository_and_head(repo,{"object":{"sha":ENV["GITHUB_SHA"]}},ENV["GITHUB_SHA"])
        with self.assertRaises(SealError): validate_repository_and_head({**repo,"private":True},{"object":{"sha":ENV["GITHUB_SHA"]}},ENV["GITHUB_SHA"])
        with self.assertRaises(SealError): validate_repository_and_head(repo,{"object":{"sha":"b"*40}},ENV["GITHUB_SHA"])
    def test_real_release_rest_numeric_and_node_id_shape(self):
        row={"id":PARENT_RELEASE_ID,"node_id":PARENT_NODE_ID,"tag_name":PARENT_TAG,"assets":[{"id":i,"name":n,"size":s,"digest":d} for n,(i,s,d) in PARENT_ASSETS.items()]}
        validate_parent_release(row)
        with self.assertRaisesRegex(SealError,"numeric ID/node ID"):
            validate_parent_release({**row,"id":PARENT_NODE_ID})
        with self.assertRaises(SealError): validate_parent_release({**row,"node_id":"wrong"})
    def test_tag_absence_requires_exact_404_not_forbidden_or_network(self):
        release_absence_result(404,{"message":"Not Found"},"new-tag")
        for status in (0,200,401,403,500):
            with self.subTest(status=status),self.assertRaises(SealError): release_absence_result(status,{"message":"Forbidden"},"new-tag")
        with self.assertRaises(SealError): release_absence_result(404,{"message":"different"},"new-tag")
    def test_parts_source_binding_or_parts_digest_drift_refused(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td); src=self.archive(root); pp,mix=self.inputs(root,src,parts_extra={"parts":[{"out":"DRIFT"}]})
            # Correctly shaped metadata must still have the parent asset digest.
            with self.assertRaisesRegex(SealError,"parts timeline"):
                self.run_seal(src,pp,mix,root)
    def test_tampered_checksum_refused(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td); src=self.archive(root,sums_override=(b"0"*64+b"  ./spec.js\n"+h(b"keep").encode()+b"  ./keep.txt\n"))
            pp,mix=self.inputs(root,src)
            with self.assertRaisesRegex(SealError,"checksum mismatch"):
                self.run_seal(src,pp,mix,root)
    def test_path_traversal_symlink_and_duplicate_refused(self):
        for kind in ("traversal","symlink","duplicate"):
            with self.subTest(kind=kind),tempfile.TemporaryDirectory() as td:
                root=Path(td); src=self.archive(root)
                temp=root/"bad.tar.gz"
                with tarfile.open(src,"r:gz") as source_tf, tarfile.open(temp,"w:gz") as bad_tf:
                    for member in source_tf.getmembers(): bad_tf.addfile(member,source_tf.extractfile(member) if member.isfile() else None)
                    if kind=="traversal":
                        b=b"x"; ti=tarfile.TarInfo("pkg/s86-d/../escape"); ti.size=1; bad_tf.addfile(ti,io.BytesIO(b))
                    elif kind=="symlink":
                        ti=tarfile.TarInfo("pkg/s86-d/link"); ti.type=tarfile.SYMTYPE; ti.linkname="spec.js"; bad_tf.addfile(ti)
                    else:
                        b=b"duplicate"; ti=tarfile.TarInfo("pkg/s86-d/keep.txt"); ti.size=len(b); bad_tf.addfile(ti,io.BytesIO(b))
                src=temp
                pp,mix=self.inputs(root,src)
                with self.assertRaises(SealError): self.run_seal(src,pp,mix,root)
    def test_provenance_or_mix_digest_drift_refused(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td); src=self.archive(root); pp,mix=self.inputs(root,src); mix.write_bytes(b"changed")
            with self.assertRaisesRegex(SealError,"mix hash drift"):
                self.run_seal(src,pp,mix,root)
            mix.write_bytes(b"synthetic audio bytes")
            with self.assertRaisesRegex(SealError,"provenance pins"):
                self.run_seal(src,pp,mix,root,parent_release_id=999)
if __name__=="__main__": unittest.main()
