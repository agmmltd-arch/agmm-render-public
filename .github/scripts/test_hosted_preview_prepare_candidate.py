import hashlib, importlib, json, sys, tempfile, types, unittest
from pathlib import Path
from unittest.mock import patch

with patch.dict(sys.modules, {'extract_story':types.ModuleType('extract_story')}):
    p=importlib.import_module('hosted_preview_prepare_candidate')

class PreviewPrepareTest(unittest.TestCase):
    def test_manifest_binding_and_no_voice(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d); files={'shorts/scripts-v2/S290.md':b'script',
                 'shorts/scripts-v2/_sources/S290_1.txt':b'source','story-data/STORY-DATA.md':b'schema'}
            for name,data in files.items():
                target=root/name;target.parent.mkdir(parents=True,exist_ok=True);target.write_bytes(data)
            manifest={'schema':'agmm-story-preview-input-v1','id':'S290','timing':'estimated','no_media':True,'release_approved':False,
                'revision_script_sha256':hashlib.sha256(files['shorts/scripts-v2/S290.md']).hexdigest(),
                'files':{n:hashlib.sha256(b).hexdigest() for n,b in files.items()}}
            raw=json.dumps(manifest).encode();(root/'MANIFEST.json').write_bytes(raw);binding=hashlib.sha256(raw).hexdigest()
            self.assertEqual(p.validate(root,'S290',binding),manifest)
            (root/'shorts/scripts-v2/S290.md').write_bytes(b'tampered')
            with self.assertRaisesRegex(ValueError,'source differs'):p.validate(root,'S290',binding)
            (root/'shorts/scripts-v2/S290.md').write_bytes(b'script')
            manifest['files']['shorts/voice/S290/S290.wav']='a'*64
            raw=json.dumps(manifest).encode();(root/'MANIFEST.json').write_bytes(raw)
            with self.assertRaisesRegex(ValueError,'inventory'):p.validate(root,'S290',hashlib.sha256(raw).hexdigest())

if __name__=='__main__':unittest.main()
