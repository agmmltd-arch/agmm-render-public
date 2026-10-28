import importlib
import json
import os
import sys
import tempfile
import types
import unittest
from pathlib import Path
from unittest.mock import patch


class NativeBuildSealTests(unittest.TestCase):
    def test_only_exact_original_native_receipt_can_seal(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);inputs={}
            for key in ('source','parts','mix'):
                p=root/(key+'.txt');p.write_text('synthetic '+key);inputs[key]={'path':str(p),'sha256':'a'*64}
            exact={'inputs':inputs}; request={'id':'S999','intent':'synthetic'}
            dispatch=types.SimpleNamespace(exact_request=lambda *a,**k:exact,
                _config=lambda *a:{'enabled':True},_secret_scan=lambda p:None)
            def need(ok,why):
                if not ok:raise ValueError(why)
            native=types.SimpleNamespace(host=lambda:None,source_closure=lambda:None,need=need,
                digest=lambda x:'request-binding',validate_owner=lambda x:dispatch,BASE=root)
            out=root/'out';out.mkdir();receipt={'request_sha256':'request-binding',
                'status':'NATIVE_PACKAGE_BUILT_NOT_SEALED','exact_request':exact}
            (out/'PACKAGE-RECEIPT.json').write_text(json.dumps(receipt))
            with patch.dict(sys.modules,{'build_native_short':native}), \
                 patch.dict(os.environ,{'GITHUB_RUN_ATTEMPT':'1','RUNNER_TEMP':str(root)}):
                sys.modules.pop('native_build_seal_candidate',None)
                module=importlib.import_module('native_build_seal_candidate')
                with patch.object(module,'seal',side_effect=lambda *a:None) as seal:
                    module.seal_native(request,out,root/'dummy.enc')
                    self.assertEqual(seal.call_count,1)
                saved=json.loads((out/'PACKAGE-RECEIPT.json').read_text())
                self.assertEqual(saved['status'],'NATIVE_PACKAGE_ENCRYPTED_NOT_UPLOADED')
                self.assertFalse(saved['release_approved'])
                with self.assertRaises(ValueError):module.seal_native(request,out,root/'dummy2.enc')
            sys.modules.pop('native_build_seal_candidate',None)


if __name__=='__main__':unittest.main()
