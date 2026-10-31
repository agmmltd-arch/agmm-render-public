import hashlib
import json
import subprocess
import tempfile
import unittest
from pathlib import Path

from youtube_private_inputs import NAMES, stage


class PrivateInputTests(unittest.TestCase):
    def test_exact_tree_stages_and_changed_bytes_refuse(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d)/'repo'; root.mkdir(); out=Path(d)/'out'; out.mkdir()
            def git(*args): return subprocess.run(['git',*args],cwd=root,capture_output=True,text=True,check=True).stdout.strip()
            git('init','-q'); git('config','user.email','test@example.invalid'); git('config','user.name','Test')
            prefix='youtube-hosted-inputs/'+'a'*32; folder=root/prefix; folder.mkdir(parents=True)
            files={}
            for name in NAMES:
                data=json.dumps({'synthetic':name}).encode(); (folder/name).write_bytes(data)
                files[name]={'sha256':hashlib.sha256(data).hexdigest(), 'git_blob':git('hash-object',str(folder/name))}
            (folder/'MANIFEST.json').write_text(json.dumps({'schema':'agmm-youtube-private-inputs-v1','files':files}))
            git('add','.'); git('commit','-qm','synthetic fixture')
            commit=git('rev-parse','HEAD'); blob=git('rev-parse',commit+':'+prefix+'/MANIFEST.json')
            stage(root,commit,prefix,blob,out)
            self.assertEqual(set(x.name for x in out.iterdir()),set(NAMES))
            out2=Path(d)/'out2'; out2.mkdir(); (folder/NAMES[0]).write_text('{}')
            with self.assertRaisesRegex(ValueError,'hash mismatch'): stage(root,commit,prefix,blob,out2)
            self.assertEqual(list(out2.iterdir()),[])


if __name__=='__main__': unittest.main()
