import json, os, pathlib, subprocess, sys, tempfile, unittest
from capture_hyperframes_diagnostic import MAX_TEXT, run

class DiagnosticTests(unittest.TestCase):
    def run_case(self, script, rc=0):
        with tempfile.TemporaryDirectory() as td:
            root=pathlib.Path(td); jout=root/'check.json'; tout=root/'diag.json'
            env=os.environ.copy(); env.update(GITHUB_WORKSPACE=str(root),RUNNER_TEMP=str(root/'temp'))
            p=run([sys.executable,'-c',script],cwd=root,env=env,json_path=jout,text_path=tout)
            return p, jout.exists(), json.loads(tout.read_text()), jout.read_text() if jout.exists() else None
    def test_success_json_saved(self):
        rc,exists,diag,report=self.run_case("print('{\\\"ok\\\":true}')")
        self.assertEqual(rc,0); self.assertTrue(exists); self.assertTrue(json.loads(report)['ok'])
        self.assertEqual(diag['status'],'PASS')

    def test_nested_check_json_paths_are_sanitized_before_artifact(self):
        with tempfile.TemporaryDirectory() as td:
            root=pathlib.Path(td); jout=root/'check.json'; tout=root/'diag.json'
            env=os.environ.copy(); env.update(GITHUB_WORKSPACE=str(root/'work'),RUNNER_TEMP=str(root/'temp'))
            payload=json.dumps({'checks':[{'path':str(root/'work/.github/candidates/S83/index.html'),'ok':True}]})
            rc=run([sys.executable,'-c',f"print({payload!r})"],cwd=root,env=env,json_path=jout,text_path=tout)
            self.assertEqual(rc,0); emitted=json.loads(jout.read_text())
            self.assertEqual(emitted['checks'][0]['path'],'<runner-path>/.github/candidates/S83/index.html')
    def test_failure_json_and_stderr_saved(self):
        rc,exists,diag,report=self.run_case("import sys;print('{\\\"errors\\\":[\\\"browser failed\\\"]}');print('stack',file=sys.stderr);sys.exit(1)")
        self.assertEqual(rc,1); self.assertTrue(exists); self.assertEqual(json.loads(report)['errors'],['browser failed'])
        self.assertIn('stack',diag['stderr']); self.assertEqual(diag['status'],'FAILED')
    def test_timeout_still_writes_partial_diagnostics(self):
        from unittest.mock import patch
        from subprocess import TimeoutExpired
        with tempfile.TemporaryDirectory() as td:
            root=pathlib.Path(td);out=root/'check.json';diag=root/'diag.json';env=os.environ.copy()
            with patch('capture_hyperframes_diagnostic.subprocess.run',side_effect=TimeoutExpired(['npx'],360,output=b'partial browser output',stderr=b'timed out')):
                rc=run(['npx'],cwd=root,env=env,json_path=out,text_path=diag)
            obj=json.loads(diag.read_text());self.assertEqual(rc,124);self.assertTrue(obj['timed_out']);self.assertIn('partial browser output',obj['stdout']);self.assertIn('timed out',obj['stderr'])

    def test_non_json_failure_bounded_sanitized_and_preserved(self):
        rc,exists,diag,_=self.run_case("import sys;print('/private/runner/work/s83 '+('x'*60000));sys.exit(1)")
        self.assertEqual(rc,1); self.assertFalse(exists); self.assertLessEqual(len(diag['stdout']),MAX_TEXT+64)
        self.assertNotIn('/private/runner/work/s83',diag['stdout']); self.assertIn('<runner-path>',diag['stdout'])

    def test_successful_check_without_json_is_failed_but_snapshot_text_is_allowed(self):
        with tempfile.TemporaryDirectory() as td:
            root=pathlib.Path(td); env=os.environ.copy(); jout=root/'check.json'; tout=root/'diag.json'
            rc=run([sys.executable,'-c',"print('not json')"],cwd=root,env=env,json_path=jout,text_path=tout)
            self.assertEqual(rc,1); self.assertEqual(json.loads(tout.read_text())['status'],'FAILED')
            rc=run([sys.executable,'-c',"print('snapshot complete')"],cwd=root,env=env,json_path=jout,text_path=tout,require_json=False)
            self.assertEqual(rc,0); self.assertEqual(json.loads(tout.read_text())['status'],'PASS')

if __name__=='__main__': unittest.main(verbosity=2)
