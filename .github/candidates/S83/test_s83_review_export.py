import hashlib, json, os, pathlib, tempfile, unittest
from unittest.mock import patch
from prepare_s83_review_export import prepare, Refusal
from publish_s83_review_release import expected_files, validate_release

class ReviewExportTests(unittest.TestCase):
 def build_fixture(self, root, count=18):
  root.mkdir(parents=True,exist_ok=True); packet=root/'source'; packet.mkdir()
  (root/'FINAL.mp4').write_bytes(b'\x00\x00\x00\x18ftypisomS83TEST')
  assets=[{'id':i,'name':f'asset-{i:02d}','size':20,'digest':'sha256:'+f'{i:064x}','git_blob_sha':'0'*40} for i in range(count)]
  items=[{'status':'PASS','name':x['name'],'asset_id':x['id'],'sha256':x['digest'][7:],'bytes':x['size'],'git_blob_sha':x['git_blob_sha']} for x in assets]
  protected=root/'protected.json';protected.write_text(json.dumps({'schema':'agmm-s83-protected-input-verification-v1','status':'PASS_18_EXACT_INPUTS' if count==18 else 'FAIL','private_repository':'agmmltd-arch/agmm-video-render','private_commit':'04b48f467025d86ffcdb54d933717682b0e84903','asset_count':count,'items':items}))
  manifest=root/'CANDIDATE-MANIFEST.json';manifest.write_text(json.dumps({'schema':'agmm-s83-candidate-manifest-v1','story_id':'S83','candidate_files':{}}))
  (root/'PROTECTED-INPUTS.json').write_text(json.dumps({'schema':'agmm-s83-protected-inputs-v1','repository':'agmmltd-arch/agmm-video-render','private_tree_binding':{'commit':'04b48f467025d86ffcdb54d933717682b0e84903'},'assets':assets}))
  (packet/'SOURCE-CAPTURE-RECEIPT.json').write_text(json.dumps({'story_id':'S83','status':'SOURCE_TEXT_AND_TRUST_LOGOS_CAPTURED_NEEDS_INDEPENDENT_EYES','rights':{'status':'NOT_ASSESSED'}}))
  (packet/'CAPTURE-STATUS.json').write_text(json.dumps({'story_id':'S83','status':'SOURCE_CHECK_AND_STILLS_CAPTURED_NEEDS_INDEPENDENT_EYES','source_step':'success','check_step':'success','stills_step':'success','review_scope':'ONE_DAY_GITHUB_ACTIONS_ARTIFACT','review_retention_days':1,'artifact_access_limit':'public repository artifact','rights_status':'NOT_ASSESSED','public_review_copy_permission':'NOT_ASSESSED','raw_assets_written_to_public_git':False,'release_approval':'NOT_GRANTED'}))
  (packet/'HYPERFRAMES-CHECK.json').write_text('{}')
  for i in range(37): (packet/f'still-frame-{i:02d}.png').write_bytes(b'\x89PNG\r\n\x1a\n'+b'test')
  frames=[]
  for i in range(37):
   name=f'still-frame-{i:02d}.png';q=packet/name
   frames.append({'name':name,'bytes':q.stat().st_size,'sha256':hashlib.sha256(q.read_bytes()).hexdigest()})
  canon=''.join(f"{x['sha256']}  {x['name']}\n" for x in frames).encode()
  (packet/'SOURCE-FRAMES-BINDING.json').write_text(json.dumps({'schema':'agmm-s83-source-frames-binding-v1','story_id':'S83','candidate_manifest_sha256':hashlib.sha256(manifest.read_bytes()).hexdigest(),'source_public_head_sha':'a'*40,'frame_count':37,'frames_sha256':hashlib.sha256(canon).hexdigest(),'frames':frames}))
  rows=[]
  for item in sorted(packet.iterdir()): rows.append(f'{hashlib.sha256(item.read_bytes()).hexdigest()}  {item.name}')
  (packet/'SHA256SUMS.txt').write_text('\n'.join(rows)+'\n')
  parts=root/'parts.json';parts.write_text(json.dumps({'parts':[{'look':'S83','file':'S83.mp4','out':'S83','off':0,'dur':56.533333}],'frames':1696},separators=(',',':')))
  mix=root/'master.wav';mix.write_bytes(b'synthetic-mix')
  mix_receipt=root/'MIX-QUALITY-RECEIPT.json';mix_receipt.write_text(json.dumps({'schema':'agmm-s83-mix-quality-receipt-v1','status':'TECHNICAL_MIX_RENDERED_NEEDS_EARS_AND_EDITORIAL_REVIEW','master':{'bytes':mix.stat().st_size,'sha256':hashlib.sha256(mix.read_bytes()).hexdigest()},'audio_review':'NOT_PERFORMED','approval':'NOT_GRANTED','protected_master_or_stems_in_artifact':False}))
  clock=root/'clock.json';clock.write_text(json.dumps({'schema':'agmm-s83-hosted-source-clock-receipt-v1','status':'TECHNICAL_SOURCE_BINDING_PASS_AUDIO_REVIEW_REQUIRED'}))
  evidence=root/'evidence.json'; evidence.write_text(json.dumps({'kind':'agmm_short_remote_technical_evidence','technical_status':'PASS','editorial_status':'NOT_REVIEWED','publication_status':'NOT_REQUESTED','masters':[{'file':'FINAL.mp4','resolution':'1080','frames':1696,'full_decode':'PASS','sha256':hashlib.sha256((root/'FINAL.mp4').read_bytes()).hexdigest(),'bytes':(root/'FINAL.mp4').stat().st_size,'probe':{'streams':[{'codec_type':'video','width':1080,'height':1920,'r_frame_rate':'30/1'},{'codec_type':'audio','codec_name':'aac','sample_rate':'48000','channels':2}]},'audio':{'integrated_lufs':-14.0,'true_peak_dbfs':-1.5}}]}))
  return root/'FINAL.mp4',evidence,protected,manifest,packet,parts,mix,mix_receipt,clock
 def test_successful_synthetic_master_binds_exact18_private_assets_and_status(self):
  with tempfile.TemporaryDirectory() as td:
   f,e,p,m,packet,parts,mix,mix_receipt,clock=self.build_fixture(pathlib.Path(td))
   with patch('prepare_s83_review_export.platform.system',return_value='Linux'),patch.dict(os.environ,{'GITHUB_ACTIONS':'true','RUNNER_ENVIRONMENT':'github-hosted'}):
    out=pathlib.Path(td)/'payload';r=prepare(f,e,p,m,packet,parts,mix,mix_receipt,clock,'a'*40,'123','1','S83-development-review-123-a1',out)
   self.assertEqual(r['private_input_binding']['count'],18);self.assertEqual(r['release_approval'],'NOT_GRANTED')
   self.assertEqual(r['source_mix']['quality_receipt_sha256'],hashlib.sha256(mix_receipt.read_bytes()).hexdigest())
   self.assertEqual(r['reviewed_source_frames']['count'],37);self.assertEqual(r['reviewed_source_frames']['source_public_head_sha'],'a'*40)
   self.assertEqual({x.name for x in out.iterdir()},{'FINAL.mp4','PUBLIC-TECHNICAL-EVIDENCE.json','PREVIEW-SHA256SUMS.txt','S83-DEVELOPMENT-PREVIEW.json'})
 def test_17_private_inputs_refused_before_export(self):
  with tempfile.TemporaryDirectory() as td:
   f,e,p,m,packet,parts,mix,mix_receipt,clock=self.build_fixture(pathlib.Path(td),17)
   with patch('prepare_s83_review_export.platform.system',return_value='Linux'),patch.dict(os.environ,{'GITHUB_ACTIONS':'true','RUNNER_ENVIRONMENT':'github-hosted'}):
    with self.assertRaisesRegex(Refusal,'private receipt does not bind'):
     prepare(f,e,p,m,packet,parts,mix,mix_receipt,clock,'a'*40,'123','1','S83-development-review-123-a1',pathlib.Path(td)/'out')
 def test_mix_quality_receipt_must_bind_exact_master_and_open_review(self):
  with tempfile.TemporaryDirectory() as td:
   f,e,p,m,packet,parts,mix,mix_receipt,clock=self.build_fixture(pathlib.Path(td))
   obj=json.loads(mix_receipt.read_text());obj['master']['sha256']='0'*64;mix_receipt.write_text(json.dumps(obj))
   with patch('prepare_s83_review_export.platform.system',return_value='Linux'),patch.dict(os.environ,{'GITHUB_ACTIONS':'true','RUNNER_ENVIRONMENT':'github-hosted'}):
    with self.assertRaisesRegex(Refusal,'mix-quality receipt does not bind'):
     prepare(f,e,p,m,packet,parts,mix,mix_receipt,clock,'a'*40,'123','1','S83-development-review-123-a1',pathlib.Path(td)/'out')
 def test_mix_quality_receipt_must_match_full_media_byte_size(self):
  with tempfile.TemporaryDirectory() as td:
   f,e,p,m,packet,parts,mix,mix_receipt,clock=self.build_fixture(pathlib.Path(td))
   obj=json.loads(mix_receipt.read_text());obj['master']['bytes']=3;mix_receipt.write_text(json.dumps(obj))
   with patch('prepare_s83_review_export.platform.system',return_value='Linux'),patch.dict(os.environ,{'GITHUB_ACTIONS':'true','RUNNER_ENVIRONMENT':'github-hosted'}):
    with self.assertRaisesRegex(Refusal,'mix-quality receipt does not bind'):
     prepare(f,e,p,m,packet,parts,mix,mix_receipt,clock,'a'*40,'123','1','S83-development-review-123-a1',pathlib.Path(td)/'out')
 def test_reviewed_source_frame_binding_must_match_candidate_and_head(self):
  with tempfile.TemporaryDirectory() as td:
   f,e,p,m,packet,parts,mix,mix_receipt,clock=self.build_fixture(pathlib.Path(td))
   bind=json.loads((packet/'SOURCE-FRAMES-BINDING.json').read_text());bind['source_public_head_sha']='b'*40;(packet/'SOURCE-FRAMES-BINDING.json').write_text(json.dumps(bind))
   rows=[]
   for item in sorted(packet.iterdir()):
    if item.name!='SHA256SUMS.txt': rows.append(f'{hashlib.sha256(item.read_bytes()).hexdigest()}  {item.name}')
   (packet/'SHA256SUMS.txt').write_text('\n'.join(rows)+'\n')
   with patch('prepare_s83_review_export.platform.system',return_value='Linux'),patch.dict(os.environ,{'GITHUB_ACTIONS':'true','RUNNER_ENVIRONMENT':'github-hosted'}):
    with self.assertRaisesRegex(Refusal,'37 source frames were not reviewed'):
     prepare(f,e,p,m,packet,parts,mix,mix_receipt,clock,'a'*40,'123','1','S83-development-review-123-a1',pathlib.Path(td)/'out')
 def test_release_inventory_rejects_mismatch_and_extra_asset(self):
  with tempfile.TemporaryDirectory() as td:
   f,e,p,m,packet,parts,mix,mix_receipt,clock=self.build_fixture(pathlib.Path(td))
   with patch('prepare_s83_review_export.platform.system',return_value='Linux'),patch.dict(os.environ,{'GITHUB_ACTIONS':'true','RUNNER_ENVIRONMENT':'github-hosted'}):
    out=pathlib.Path(td)/'payload';prepare(f,e,p,m,packet,parts,mix,mix_receipt,clock,'a'*40,'123','1','S83-development-review-123-a1',out)
   expected=expected_files(out,'S83-development-review-123-a1','a'*40)
   assets=[{'name':n,'size':x['size'],'digest':'sha256:'+x['sha256'],'browser_download_url':f'https://github.com/agmmltd-arch/agmm-render-public/releases/download/S83-development-review-123-a1/{n}'} for n,x in expected.items()]
   release={'tag_name':'S83-development-review-123-a1','draft':True,'prerelease':True,'assets':assets}
   self.assertEqual(set(validate_release(release,expected,'S83-development-review-123-a1',draft=True)),set(expected))
   with self.assertRaisesRegex(ValueError,'unexpected asset'):
    validate_release({**release,'assets':assets+[dict(assets[0],name='voice.wav')]},expected,'S83-development-review-123-a1',draft=True)
   with self.assertRaisesRegex(ValueError,'release inventory is missing'):
    validate_release({**release,'assets':assets[:-1]},expected,'S83-development-review-123-a1',draft=True)
   with self.assertRaisesRegex(ValueError,'size/SHA'):
    validate_release({**release,'assets':[dict(assets[0],digest='sha256:'+'0'*64),*assets[1:]]},expected,'S83-development-review-123-a1',draft=True)

if __name__=='__main__': unittest.main(verbosity=2)
