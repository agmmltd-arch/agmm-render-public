import io
import json
import tarfile
import tempfile
import types
import unittest
from pathlib import Path
from unittest.mock import patch

import verify_build_producer as v


class ProducerTests(unittest.TestCase):
    def test_exact_owner_and_source_pins_are_required(self):
        sha=next(iter(v.ALLOWED_RUNTIME));run={'event':'workflow_dispatch','conclusion':'success',
            'run_attempt':1,'head_sha':sha,'path':'.github/workflows/native-build-encrypted-candidate.yml@refs/tags/x'}
        names=('Run unchanged native source and sound build with provider access denied','Seal exact native inputs to an encrypted package',
               'Return encrypted native build input','Return encrypted native build metadata')
        jobs={'jobs':[{'name':'build','conclusion':'success','steps':[{'name':n,'conclusion':'success'} for n in names]}]}
        hashes={'source':'a'*64,'parts':'b'*64,'mix':'c'*64}
        receipt={'status':'NATIVE_PACKAGE_ENCRYPTED_NOT_UPLOADED','run_id':'123456','runtime_commit':sha,
                 'release_approved':False,'content_posted':False,
                 'exact_request':{'inputs':{k:{'sha256':x} for k,x in hashes.items()}}}
        stream=io.BytesIO()
        with tarfile.open(fileobj=stream,mode='w:') as t:
            raw=json.dumps(receipt).encode();info=tarfile.TarInfo('native-build-json/PACKAGE-RECEIPT.json');info.size=len(raw);t.addfile(info,io.BytesIO(raw))
        with tempfile.TemporaryDirectory() as d:
            p=Path(d)/'metadata.enc';p.write_bytes(b'synthetic')
            with patch.object(v.platform,'system',return_value='Linux'), \
                 patch.dict(v.os.environ,{'GITHUB_ACTIONS':'true','VOICEFREE_PASS':'synthetic'}), \
                 patch.object(v,'api',side_effect=lambda p:jobs if '/jobs?' in p else run), \
                 patch.object(v.subprocess,'run',return_value=types.SimpleNamespace(stdout=stream.getvalue())):
                v.verify('123456',p,hashes)
                with self.assertRaisesRegex(ValueError,'binding mismatch'):
                    v.verify('123456',p,dict(hashes,source='d'*64))
                run['conclusion']='failure'
                with self.assertRaisesRegex(ValueError,'not qualified'):v.verify('123456',p,hashes)


if __name__=='__main__':unittest.main()
