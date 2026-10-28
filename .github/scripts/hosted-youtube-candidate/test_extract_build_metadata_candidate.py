import unittest
import io
import json
import tarfile
from copy import deepcopy
from extract_build_metadata_candidate import public_metadata, receipt_from_tar

class ReceiptTest(unittest.TestCase):
    def setUp(self):
        self.bind = {'run_id':'123456','runtime_commit':'a'*40,'expected_id':'S269',
                     'request_sha256':'b'*64,'approved_hash':'c'*64}
        self.receipt={'status':'NATIVE_PACKAGE_ENCRYPTED_NOT_UPLOADED','run_id':'123456',
            'runtime_commit':'a'*40,'id':'S269','request_sha256':'b'*64,'approved_hash':'c'*64,
            'release_approved':False,'content_posted':False,'render_dispatched':False,
            'exact_request':{'id':'S269','approval':{'approved_hash':'c'*64},'editorial_status':'NOT_REVIEWED',
                'inputs':{k:{'sha256':v*64,'path':'private'} for k,v in [('source','d'),('parts','e'),('mix','f')]}}}
    def test_minimal_output_and_exact_binding(self):
        out=public_metadata(self.receipt,**self.bind)
        self.assertEqual(out['source_sha256'],'d'*64)
        self.assertNotIn('private',str(out))
        self.assertFalse(out['release_approval'])
    def test_changed_receipt_never_returns_metadata(self):
        for key,value in [('id','S270'),('request_sha256','0'*64),('release_approved',True),('render_dispatched',True)]:
            with self.subTest(key=key):
                r=deepcopy(self.receipt);r[key]=value
                with self.assertRaises(ValueError): public_metadata(r,**self.bind)
        r=deepcopy(self.receipt);r['exact_request']['inputs']['mix']['sha256']='missing'
        with self.assertRaises(ValueError): public_metadata(r,**self.bind)
    def test_archive_rejects_duplicate_or_unsafe_receipts(self):
        def archive(names):
            stream=io.BytesIO()
            with tarfile.open(fileobj=stream,mode='w:') as tar:
                raw=json.dumps(self.receipt).encode()
                for name in names:
                    info=tarfile.TarInfo(name);info.size=len(raw);tar.addfile(info,io.BytesIO(raw))
            return stream.getvalue()
        name='native-build-json/PACKAGE-RECEIPT.json'
        self.assertEqual(receipt_from_tar(archive([name]))['id'],'S269')
        for names in ([name,name],[name,'../escape']):
            with self.subTest(names=names), self.assertRaises(ValueError):receipt_from_tar(archive(names))

if __name__=='__main__':unittest.main()
