"""Exercise preparation and original grounding using only synthetic local text."""
import hashlib,io,json,os,sys,tempfile,unittest,zipfile
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

HERE=Path(__file__).resolve().parent
LOCAL=Path('/Users/samwall/alfred/builds/video-program-2026-09-23/v2/kit/tools')
if not (HERE/'voice-native/kit/tools/extract_story.py').exists() and LOCAL.exists():sys.path.insert(0,str(LOCAL))
import hosted_preview_prepare_candidate as prep
import hosted_preview_ground_candidate as ground

class EndToEndTest(unittest.TestCase):
 def test_original_extractor_grounding_uses_estimated_inputs(self):
  with tempfile.TemporaryDirectory() as tmp:
   root=Path(tmp)/'source';runtime=Path(tmp)/'runtime';root.mkdir();runtime.mkdir()
   script=prep.story.FIX_SCRIPT+'\n## Sources used\n- [SRC1] https://example.org/a (trade; fetched 2026-10-20, HTTP 200) Acme Bank chatbot | The Example Times\n'
   files={'shorts/scripts-v2/S999.md':script.encode(), 'shorts/scripts-v2/_sources/S999_1.txt':b'Acme Bank said its chatbot handled 4.2 million customer chats in 2025, up from 2 million in 2023.\nThe top request by far was the reset my card button, the bank said. It was simply the easiest thing to ask for, a spokesman added.\n', 'story-data/STORY-DATA.md':b'## 6. JSON Schema\n```json\n{"type":"object"}\n```\n'}
   for name,data in files.items():
    f=root/name;f.parent.mkdir(parents=True,exist_ok=True);f.write_bytes(data)
   digest=lambda b:hashlib.sha256(b).hexdigest()
   manifest={'schema':'agmm-story-preview-input-v1','id':'S999','timing':'estimated','no_media':True,'release_approved':False,
      'revision_script_sha256':digest(files['shorts/scripts-v2/S999.md']),'files':{k:digest(v) for k,v in files.items()}}
   raw=json.dumps(manifest).encode();(root/'MANIFEST.json').write_bytes(raw);binding=digest(raw);prompt_path=Path(tmp)/'prompt.enc'
   env={'GITHUB_ACTIONS':'true','STORY_PREVIEW_MANIFEST_SHA':binding,'AGMM_WRITER_PASS':'synthetic'}
   story=prep.story
   with patch.object(prep,'ROOT',runtime),patch.object(prep.sys,'platform','linux'),patch.dict(os.environ,env), \
        patch.object(story,'V2',str(runtime)),patch.object(story,'SCRIPTS',str(runtime/'shorts/scripts-v2')), \
        patch.object(story,'VOICE',str(runtime/'shorts/voice')),patch.object(story,'ASSETS',str(runtime/'kit/assets')), \
        patch.object(prep,'crypt',side_effect=lambda b,k:b),patch.object(prep.sys,'argv',['script',str(root),'S999',str(prompt_path)]):
    prep.main();packet=json.loads(prompt_path.read_bytes());ctx=story.build_context('S999');answer=json.dumps(story._good_reply(ctx))
    meta={'request_id':'w'+'1'*12,'run_id':123,'model_key':'q30a3b-iq3xxs'}
    saved={'id':'S999','prompt_sha256':packet['prompt_sha256'],'response':answer,'meta':meta}
    response=Path(tmp)/'response.enc';response.write_text(json.dumps(saved))
    provider={'meta':{'request_id':meta['request_id'],'model':'q30a3b-iq3xxs'},'response':{'choices':[{'message':{'content':answer}}]}}
    z=io.BytesIO()
    with zipfile.ZipFile(z,'w') as f:f.writestr('response.enc',json.dumps(provider))
    payload=z.getvalue();run={'id':123,'path':ground.original.WRITER,'event':'workflow_dispatch','run_attempt':1,'status':'completed','conclusion':'success','display_title':'llmw '+meta['request_id'],'head_sha':'d'*40}
    artifact={'name':'llm-'+meta['request_id'],'expired':False,'workflow_run':{'id':123},'digest':'sha256:'+digest(payload),'id':456}
    output=Path(tmp)/'grounded.enc'
    with patch.object(ground.original,'api',side_effect=[run,{'sha':ground.original.BLOB},{'artifacts':[artifact]}]), \
         patch.object(ground.subprocess,'check_output',return_value=payload),patch.object(ground,'crypt',side_effect=lambda b,k,decrypt=False:b):
     ground.ground(root,prompt_path,response,output,binding,'synthetic')
    result=json.loads(output.read_bytes());self.assertEqual(result['timing'],'estimated');self.assertFalse(result['release_approved']);self.assertFalse(result['independent_av_review'])
    self.assertEqual(result['grounding_failures'],[]);self.assertIn('no-words',result['story']['gaps']);self.assertIn('thin',result['story']['gaps'])
if __name__=='__main__':unittest.main()
