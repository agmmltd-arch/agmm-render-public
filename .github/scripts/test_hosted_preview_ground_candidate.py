import importlib, json, sys, types, unittest
from pathlib import Path
from unittest.mock import patch

with patch.dict(sys.modules, {'extract_story':types.ModuleType('extract_story')}):
    p=importlib.import_module('hosted_preview_ground_candidate')

class PreviewGroundTest(unittest.TestCase):
    def test_wrong_script_binding_stops_before_provider_and_output(self):
        prompt={'id':'S290','schema':'agmm-story-preview-prompt-v1','timing':'estimated',
                'release_approved':False,'source_manifest_sha256':'a'*64,
                'revision_script_sha256':'b'*64,'prompt_sha256':'c'*64,'prompt':'text'}
        saved={'id':'S290','prompt_sha256':'c'*64,'meta':{'request_id':'w'+'1'*12,'run_id':123,'model_key':'q30a3b-iq3xxs'}}
        with patch.object(Path,'read_bytes',return_value=b'x'), \
             patch.object(p,'crypt',side_effect=[json.dumps(prompt).encode(),json.dumps(saved).encode()]), \
             patch.object(p.prep,'validate',return_value={'revision_script_sha256':'d'*64}), \
             patch.object(p.original,'api') as api:
            with self.assertRaisesRegex(ValueError,'identity'):
                p.ground(Path('/tmp/input'),Path('/tmp/prompt'),Path('/tmp/response'),Path('/tmp/out'),'a'*64,'key')
            api.assert_not_called()

if __name__=='__main__':unittest.main()
