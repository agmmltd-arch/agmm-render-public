"""Exercise the original extractor's estimated prompt using synthetic text only."""
import hashlib, json, os, sys, tempfile, unittest
from pathlib import Path
from unittest.mock import patch

HERE=Path(__file__).resolve().parent
LOCAL=Path('/Users/samwall/alfred/builds/video-program-2026-09-23/v2/kit/tools')
if not (HERE/'voice-native/kit/tools/extract_story.py').exists() and LOCAL.exists():
    sys.path.insert(0,str(LOCAL))
import hosted_preview_prepare_candidate as prep

class OriginalContextTest(unittest.TestCase):
    def test_estimated_prompt_uses_original_extractor(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)/'source';runtime=Path(tmp)/'runtime';root.mkdir();runtime.mkdir()
            texts={'shorts/scripts-v2/S999.md':prep.story.FIX_SCRIPT.encode(),
                   'shorts/scripts-v2/_sources/S999_1.txt':b'Acme Bank said its chatbot handled 4.2 million customer chats in 2025, up from 2 million in 2023.\nThe top request by far was the reset my card button, the bank said.\n',
                   'story-data/STORY-DATA.md':b'synthetic schema text'}
            for name,data in texts.items():
                path=root/name;path.parent.mkdir(parents=True,exist_ok=True);path.write_bytes(data)
            manifest={'schema':'agmm-story-preview-input-v1','id':'S999','timing':'estimated','no_media':True,'release_approved':False,
                'revision_script_sha256':hashlib.sha256(texts['shorts/scripts-v2/S999.md']).hexdigest(),
                'files':{k:hashlib.sha256(v).hexdigest() for k,v in texts.items()}}
            raw=json.dumps(manifest).encode();(root/'MANIFEST.json').write_bytes(raw);out=Path(tmp)/'prompt.enc'
            env={'GITHUB_ACTIONS':'true','STORY_PREVIEW_MANIFEST_SHA':hashlib.sha256(raw).hexdigest(),'AGMM_WRITER_PASS':'synthetic'}
            with patch.object(prep,'ROOT',runtime), patch.object(prep.sys,'platform','linux'), \
                 patch.dict(os.environ,env),patch.object(prep.sys,'argv',['script',str(root),'S999',str(out)]), \
                 patch.object(prep.story,'V2',str(runtime)),patch.object(prep.story,'SCRIPTS',str(runtime/'shorts/scripts-v2')), \
                 patch.object(prep.story,'VOICE',str(runtime/'shorts/voice')), \
                 patch.object(prep,'crypt',side_effect=lambda b,k:b):
                prep.main()
            packet=json.loads(out.read_bytes());self.assertEqual(packet['timing'],'estimated');self.assertFalse(packet['release_approved'])
            self.assertGreater(len(packet['prompt']),1000);self.assertEqual(packet['revision_script_sha256'],manifest['revision_script_sha256'])

if __name__=='__main__':unittest.main()
