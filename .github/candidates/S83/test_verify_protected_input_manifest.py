import copy
import importlib.util
import json
import unittest
from pathlib import Path

ROOT=Path(__file__).parent
spec=importlib.util.spec_from_file_location("s83_protected",ROOT/"verify_protected_input_manifest.py")
module=importlib.util.module_from_spec(spec); spec.loader.exec_module(module)

class ProtectedInputManifestTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls): cls.doc=json.loads((ROOT/"PROTECTED-INPUTS.json").read_text())
    def test_exact_18_assets_and_runtime_paths(self):
        assets=module.validate(self.doc)
        self.assertEqual(len(assets),18)
        self.assertEqual(sum(a["name"]=="S83.wav" for a in assets),1)
    def test_rejects_missing_asset(self):
        d=copy.deepcopy(self.doc); d["assets"].pop()
        with self.assertRaisesRegex(ValueError,"exact 18-file"): module.validate(d)
    def test_rejects_changed_digest(self):
        d=copy.deepcopy(self.doc); next(a for a in d["assets"] if a["name"]=="foley_click_01.wav")["digest"]="sha256:"+"0"*64
        with self.assertRaisesRegex(ValueError,"runtime binding mismatch|digest"): module.validate(d)
    def test_rejects_wrong_release(self):
        d=copy.deepcopy(self.doc); d["release_id"]+=1
        with self.assertRaisesRegex(ValueError,"release identity"): module.validate(d)
    def test_rejects_path_traversal(self):
        d=copy.deepcopy(self.doc); next(a for a in d["assets"] if a["name"]=="foley_click_01.wav")["private_tree_path"]="../foley_click_01.wav"
        with self.assertRaisesRegex(ValueError,"runtime binding mismatch|unsafe runtime"): module.validate(d)

if __name__=="__main__": unittest.main()
