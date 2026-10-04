import json
import hashlib
import os
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch
import zipfile
import csv

import f06_preview_export as f

ROOT = Path(__file__).parent
FIX = ROOT.parent / 'fixtures'

def load(name):
    return json.loads((FIX / name).read_text())

class ExportTests(unittest.TestCase):
    def setUp(self):
        self.repo = load('repository.json')
        self.run = load('run.json')
        self.jobs = load('jobs.json')
        self.artifacts = load('artifacts.json')
        self.now = f.parse_time('2026-10-04T16:00:00Z')

    def test_exact_native_source_binding(self):
        x = f.validate_source(self.repo, self.run, self.jobs, self.artifacts, self.now)
        self.assertEqual(x['artifact']['id'], f.ARTIFACT_ID)

    def test_wrong_repo_head_event_job_artifact_are_refused(self):
        for field, value in [('full_name','attacker/fork'), ('private',True)]:
            doc = dict(self.repo); doc[field] = value
            with self.subTest(field=field), self.assertRaises(f.Refusal):
                f.validate_source(doc, self.run, self.jobs, self.artifacts, self.now)
        for field, value in [('head_sha','0'*40), ('event','push'), ('conclusion','failure')]:
            doc = dict(self.run); doc[field] = value
            with self.subTest(field=field), self.assertRaises(f.Refusal):
                f.validate_source(self.repo, doc, self.jobs, self.artifacts, self.now)
        jobs = json.loads(json.dumps(self.jobs)); jobs['jobs'][0]['id'] += 1
        with self.assertRaises(f.Refusal): f.validate_source(self.repo,self.run,jobs,self.artifacts,self.now)
        arts = json.loads(json.dumps(self.artifacts)); arts['artifacts'][0]['digest'] = 'sha256:'+'0'*64
        with self.assertRaises(f.Refusal): f.validate_source(self.repo,self.run,self.jobs,arts,self.now)

    def test_expiry_and_sparse_inventory_refused(self):
        with self.assertRaises(f.Refusal): f.validate_source(self.repo,self.run,self.jobs,self.artifacts,f.parse_time('2026-10-06T00:00:00Z'))
        a=json.loads(json.dumps(self.artifacts)); a['total_count']=2
        with self.assertRaises(f.Refusal): f.validate_source(self.repo,self.run,self.jobs,a,self.now)

    def test_native_404_only(self):
        exact=subprocess.CompletedProcess([],1,'{"message":"Not Found","status":"404"}\n','gh: Not Found (HTTP 404)\n')
        self.assertTrue(f.confirmed_not_found(exact))
        for bad in [
            subprocess.CompletedProcess([],1,'{"message":"Not Found","status":"403"}','gh: Not Found (HTTP 404)'),
            subprocess.CompletedProcess([],1,'{"message":"Not Found","status":"404"}','gh: HTTP 403'),
            subprocess.CompletedProcess([],1,'','network timeout'),
            subprocess.CompletedProcess([],0,'{}',''),
        ]:
            with self.subTest(bad=bad.stderr): self.assertFalse(f.confirmed_not_found(bad))

    def test_zip_member_contract_exact_and_unique(self):
        self.assertEqual(len(f.EXPECTED_ZIP_MEMBERS),117)
        self.assertIn(f.VIDEO_MEMBER,f.EXPECTED_ZIP_MEMBERS)
        self.assertEqual(len(f.EXPECTED_PUBLIC_NAMES),114)
        self.assertEqual(len(f.native_frame_numbers()),101)
        self.assertEqual(f.native_frame_numbers()[0:3],[0,1,2])

    def test_safe_release_asset_verification_refuses_mismatch(self):
        row={'name':'v.mp4','size':5,'sha256':'a'*64,'path':'/tmp/v.mp4'}
        asset={'name':'v.mp4','size':5,'digest':'sha256:'+'a'*64,'browser_download_url':f'https://github.com/{f.REPO}/releases/download/{f.PUBLIC_TAG}/v.mp4'}
        self.assertEqual(f.validate_release_assets({'v.mp4':row},[asset],f.PUBLIC_TAG),{'v.mp4':asset})
        bad=dict(asset,size=6)
        with self.assertRaises(f.Refusal): f.validate_release_assets({'v.mp4':row},[bad],f.PUBLIC_TAG)
        with self.assertRaises(f.Refusal): f.validate_release_assets({'v.mp4':row},[asset,asset],f.PUBLIC_TAG)

    def test_zip_wrong_size_refused_before_digest_or_extract(self):
        source=f.validate_source(self.repo,self.run,self.jobs,self.artifacts,self.now)
        with tempfile.TemporaryDirectory() as d, patch.dict(os.environ,{'GITHUB_ACTIONS':'true'}), patch.object(f.platform,'system',return_value='Linux'):
            z=Path(d)/'bad.zip'; z.write_bytes(b'not the native artifact')
            with self.assertRaises(f.Refusal): f.extract_artifact_zip(z,source,Path(d)/'out')
            self.assertFalse((Path(d)/'out').exists())

    def test_source_receipt_private_fields_are_pinned_then_sanitized(self):
        good={'private_media_commit':f.PRIVATE_MEDIA_HEAD,'new_image_git_blob_sha':f.PRIVATE_IMAGE_GIT_BLOB,
              'base_source_archive_sha256':f.BASE_ARCHIVE_SHA256,'host_rebuilt_source_lock_sha256':'1'*64,
              'compute':'GitHub-hosted Ubuntu 24.04','release_approval':'NOT_GRANTED',
              'fully_decoded_video_frames':288,'contact_sheets':6,'native_review_frames':101}
        with tempfile.TemporaryDirectory() as d:
            p=Path(d)/'receipt.json'; p.write_text(json.dumps(good)); f.validate_source_receipt_file(p)
            good['private_media_commit']='0'*40; p.write_text(json.dumps(good))
            with self.assertRaises(f.Refusal): f.validate_source_receipt_file(p)
        safe=f.safe_technical_summary({}, {'video_sha256':'2'*64,'video_bytes':1,'duration_seconds':9.6,'ffprobe':{}})
        text=json.dumps(safe)
        self.assertNotIn(f.PRIVATE_MEDIA_HEAD,text); self.assertNotIn(f.PRIVATE_IMAGE_GIT_BLOB,text); self.assertNotIn(f.BASE_ARCHIVE_SHA256,text)
        self.assertEqual(safe['picture_review_status'],'NOT_REVIEWED')


    def _synthetic_extracted_tree(self, root):
        evidence = root / f.EVIDENCE_ROOT
        evidence.mkdir(parents=True)
        (root / f.VIDEO_MEMBER).parent.mkdir(parents=True)
        (root / f.VIDEO_MEMBER).write_bytes(b"\x00\x00\x00\x18ftypisom" + b"synthetic-test-only")
        (evidence / "check.json").write_text("{}\n")
        (evidence / "ffprobe.json").write_text(json.dumps({"streams":[{"codec_type":"video","width":1920,"height":1080,"r_frame_rate":"30/1","nb_frames":"288"}],"format":{"duration":"9.6"}}))
        lines=["# synthetic framemd5 fixture"]+[f"0,          {i},          {i},        1, 6220800, " + "a"*32 for i in range(288)]
        (evidence / "video-frames.framemd5").write_text("\n".join(lines)+"\n")
        (evidence / "black-freeze-scan.txt").write_text("synthetic test receipt\n")
        (evidence / "render.log").write_text("synthetic hosted test log\n")
        (evidence / f.FRAME_COUNT_NAME).write_text("288 fully decoded frames; 6 chronological sheets; 101 native cut/event frames; silent picture proof only; release approval not granted.\n")
        for name, rows in [(f.FRAME_INDEX_NAME,f.frame_index_rows()),(f.BOUNDARY_MAP_NAME,f.boundary_rows())]:
            with (evidence/name).open("w",newline="") as stream: csv.writer(stream,lineterminator="\n").writerows(rows)
        source_receipt={"private_media_commit":f.PRIVATE_MEDIA_HEAD,"new_image_git_blob_sha":f.PRIVATE_IMAGE_GIT_BLOB,"base_source_archive_sha256":f.BASE_ARCHIVE_SHA256,"host_rebuilt_source_lock_sha256":"1"*64,"compute":"GitHub-hosted Ubuntu 24.04","release_approval":"NOT_GRANTED","fully_decoded_video_frames":288,"contact_sheets":6,"native_review_frames":101}
        (evidence/"SOURCE-RECEIPT.json").write_text(json.dumps(source_receipt))
        # Minimal synthetic JPEG SOF marker with only the dimensions used by the validator.
        jpeg=b"\xff\xd8\xff\xc0\x00\x11\x08\x05\xa0\x07\x80"+b"\x00"*12+b"\xff\xd9"
        for name in f.CONTACT_NAMES: (evidence/name).write_bytes(jpeg)
        png=b"\x89PNG\r\n\x1a\n"+b"\x00\x00\x00\rIHDR"+(1920).to_bytes(4,"big")+(1080).to_bytes(4,"big")
        for name in f.NATIVE_NAMES: (evidence/name).write_bytes(png)

    def _prepared_payload(self, root):
        source=f.validate_source(self.repo,self.run,self.jobs,self.artifacts,self.now)
        extracted=root/"extract"; self._synthetic_extracted_tree(extracted)
        payload=root/"payload"
        with patch.dict(os.environ,{'GITHUB_ACTIONS':'true'}), patch.object(f.platform,'system',return_value='Linux'):
            f.prepare_export(extracted,source,payload)
            receipt, expected=f.validate_prepared_export(payload)
        return source,payload,receipt,expected

    def test_synthetic_prepare_validate_and_mock_native_publication(self):
        with tempfile.TemporaryDirectory() as d:
            source,payload,receipt,expected=self._prepared_payload(Path(d))
            self.assertEqual(len(list(payload.iterdir())),114)
            self.assertEqual(len(receipt['public_preview_assets']),112)
            self.assertNotIn(f.PRIVATE_MEDIA_HEAD,(payload/f.RECEIPT_NAME).read_text())
            assets=[{'name':name,'size':row['size'],'digest':'sha256:'+row['sha256'],'browser_download_url':f"https://github.com/{f.REPO}/releases/download/{f.PUBLIC_TAG}/{name}"} for name,row in expected.items()]
            release={'tag_name':f.PUBLIC_TAG,'draft':False,'prerelease':True,'assets':assets}
            missing=subprocess.CompletedProcess([],1,json.dumps({'status':'404','message':'Not Found'}),'gh: Not Found (HTTP 404)\n')
            ok=subprocess.CompletedProcess([],0,'{}','')
            release_result=subprocess.CompletedProcess([],0,json.dumps(release),'')
            commit_result=subprocess.CompletedProcess([],0,json.dumps({'sha':f.RUN_HEAD}),'')
            replies=[missing,ok,release_result,commit_result,release_result]
            with patch.dict(os.environ,{'GITHUB_ACTIONS':'true'}), patch.object(f.platform,'system',return_value='Linux'), patch.object(f,'run_gh',side_effect=replies) as gh:
                out=f.publish_export(payload)
            self.assertEqual(out['editorial_approval'],'NOT_GRANTED')
            self.assertEqual(out['full_av_review'],'OPEN')
            self.assertEqual(len(gh.call_args_list),5)
            self.assertIn('--prerelease',gh.call_args_list[1].args[0])
            self.assertTrue(all('create' not in call.args[0] for call in gh.call_args_list[2:]))

    def test_synthetic_prepare_validate_rejects_tampering_and_extra_media(self):
        with tempfile.TemporaryDirectory() as d:
            _,payload,_,_=self._prepared_payload(Path(d))
            (payload/f"native-001.png").write_bytes(b"changed")
            with self.assertRaises(f.Refusal): f.validate_prepared_export(payload)
        with tempfile.TemporaryDirectory() as d:
            _,payload,_,_=self._prepared_payload(Path(d))
            (payload/"unexpected.mp4").write_bytes(b"extra")
            with self.assertRaises(f.Refusal): f.validate_prepared_export(payload)

    def test_publish_never_creates_on_non404_native_lookup(self):
        with tempfile.TemporaryDirectory() as d:
            _,payload,_,_=self._prepared_payload(Path(d))
            forbidden=subprocess.CompletedProcess([],1,'{"message":"Forbidden","status":"403"}','gh: HTTP 403')
            with patch.dict(os.environ,{'GITHUB_ACTIONS':'true'}), patch.object(f.platform,'system',return_value='Linux'), patch.object(f,'run_gh',return_value=forbidden) as gh:
                with self.assertRaises(f.Refusal): f.publish_export(payload)
            self.assertEqual(len(gh.call_args_list),1)

if __name__ == '__main__': unittest.main()
