import importlib.util
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest
import yaml

HERE = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location('s82_guard', HERE / 's82-source-pack-guard.py')
guard = importlib.util.module_from_spec(spec)
spec.loader.exec_module(guard)


class SourcePackGuardTests(unittest.TestCase):
    def setUp(self):
        self.plan = {
            'schema': 'agmm-s82-source-plan-v3', 'story_id': 'S82', 'sources': [{}, {}, {}],
            'collection_policy': {'exact_capture_files': [str(i) for i in range(18)],
                'photos': False, 'clips': False, 'audio_or_video_download': False,
                'follow_links': False, 'full_page_screenshots': False,
                'automated_page_load_query': '?utm_source=qa&utm_campaign=qa_release_audit'},
        }
        # Test fixture pins are overridden only in memory; production pins remain immutable constants.
        self.plan_bytes = __import__('json').dumps(self.plan, sort_keys=True).encode()
        self.helper_bytes = b'fixture helper'
        self.env = {'GITHUB_ACTIONS':'true','RUNNER_OS':'Linux',
            'GITHUB_REPOSITORY':guard.REPOSITORY,'GITHUB_REF':'refs/heads/main',
            'GITHUB_SHA':'c' * 40, 'S82_PLAN_SHA256':'fixture', 'S82_HELPER_SHA256':'fixture'}
        self.repo = {'full_name':guard.REPOSITORY,'private':False,'visibility':'public'}
        self.head = 'c' * 40
        self.parent = guard.PARENT_SHA
        self.blobs = dict(guard.INHERITED_BLOBS)
        self.paths = ['.github/workflows/s82-source-pack-capture.yml']
        self._plan_pin = guard.PLAN_SHA256
        self._helper_pin = guard.HELPER_SHA256
        guard.PLAN_SHA256 = guard.sha256(self.plan_bytes)
        guard.HELPER_SHA256 = guard.sha256(self.helper_bytes)
        self.env['S82_PLAN_SHA256'] = guard.PLAN_SHA256
        self.env['S82_HELPER_SHA256'] = guard.HELPER_SHA256

    def tearDown(self):
        guard.PLAN_SHA256 = self._plan_pin
        guard.HELPER_SHA256 = self._helper_pin

    def validate(self):
        guard.validate_preflight(env=self.env, repo=self.repo, head=self.head, parent=self.parent,
            plan_bytes=self.plan_bytes, helper_bytes=self.helper_bytes,
            inherited_blobs=self.blobs, tracked_paths=self.paths)

    def test_exact_public_linux_parent_and_text_runtime_pass(self):
        self.validate()

    def test_private_target_refuses_before_capture(self):
        self.repo['private'] = True
        with self.assertRaisesRegex(ValueError, 'public repository'):
            self.validate()

    def test_moved_main_head_refuses(self):
        self.head = 'f' * 40
        with self.assertRaisesRegex(ValueError, 'preimage moved'):
            self.validate()

    def test_previous_observed_parent_refuses_after_refresh(self):
        self.parent = '1cbf444fe3278327aa098bee93deadd8abbc97a7'
        with self.assertRaisesRegex(ValueError, 'preimage moved'):
            self.validate()

    def test_unexpected_inherited_runtime_blob_refuses(self):
        key = next(iter(self.blobs))
        self.blobs[key] = '0' * 40
        with self.assertRaisesRegex(ValueError, 'inherited helper preimage mismatch'):
            self.validate()

    def test_absent_s82_runtime_input_refuses(self):
        self.helper_bytes = b''
        with self.assertRaisesRegex(ValueError, 'helper pin mismatch'):
            self.validate()

    def test_public_voice_or_media_input_refuses(self):
        self.paths.append('v2/shorts/voice/S82/S82.wav')
        with self.assertRaisesRegex(ValueError, 'media inputs'):
            self.validate()

    def test_source_policy_weakening_refuses(self):
        self.plan['collection_policy']['photos'] = True
        self.plan_bytes = __import__('json').dumps(self.plan, sort_keys=True).encode()
        guard.PLAN_SHA256 = guard.sha256(self.plan_bytes)
        self.env['S82_PLAN_SHA256'] = guard.PLAN_SHA256
        with self.assertRaisesRegex(ValueError, 'capture policy changed'):
            self.validate()

    def test_workflow_exports_capture_path_in_step_and_fetches_parent_for_guard(self):
        workflow_path = HERE / 's82-source-pack-capture.yml'
        workflow_text = workflow_path.read_text()
        workflow = yaml.safe_load(workflow_text)
        steps = workflow['jobs']['capture']['steps']
        checkout = next(step for step in steps if step.get('uses', '').startswith('actions/checkout@'))
        self.assertEqual(checkout['with'].get('fetch-depth'), 2)
        self.assertNotIn('S82_CAPTURE_DIR', workflow['jobs']['capture'].get('env', {}))
        init = next(step for step in steps if step.get('name') == 'Initialize the capture path for later steps')
        self.assertIn('S82_CAPTURE_DIR=%s/s82-source-capture', init['run'])
        self.assertIn('$RUNNER_TEMP', init['run'])
        self.assertIn('$GITHUB_ENV', init['run'])

    def test_actual_workflow_payload_step_flattens_exact_nested_capture_paths(self):
        workflow = yaml.safe_load((HERE / 's82-source-pack-capture.yml').read_text())
        step = next(step for step in workflow['jobs']['capture']['steps']
                    if step.get('name') == 'Prepare an exact allowlisted public review payload, including failure receipts')
        run = step['run']
        plan = json.loads((HERE / 'SOURCE-PLAN.json').read_text())
        expected = sorted(plan['collection_policy']['exact_capture_files'])
        plan_hash = guard.PLAN_SHA256
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp); workspace = root / 'workspace'; runner = root / 'runner'
            (workspace / '.github/scripts').mkdir(parents=True)
            (workspace / '.github/scripts/s82-source-pack-plan.json').write_text(json.dumps(plan))
            source = runner / 's82-source-capture'; source.mkdir(parents=True)
            receipt = {'status':'SOURCE_CROPS_CAPTURED_NEEDS_ROOT_EYES','asset_count':18,
                       'plan_sha256':plan_hash,'assets':[{'file':name} for name in expected]}
            (source / 'CAPTURE-RECEIPT.json').write_text(json.dumps(receipt))
            (source / 'SOURCE-IDENTITY.json').write_text(json.dumps({'status':receipt['status']}))
            (source / 'manifest.json').write_text(json.dumps({'plan_sha256':plan_hash,'asset_count':18}))
            for source_row in plan['sources']:
                folder = source / source_row['key']; folder.mkdir()
                for row in source_row['files']:
                    (folder / row['file']).write_bytes(b'SYNTHETIC-NATIVE-CROP-PLACEHOLDER\n' * 5)
            env = dict(os.environ)
            env.update({'RUNNER_TEMP':str(runner),'S82_CAPTURE_DIR':str(source),
                        'S82_PLAN_SHA256':plan_hash,'CAPTURE_OUTCOME':'success'})
            result = subprocess.run(['bash','-euo','pipefail','-c',run],cwd=workspace,env=env,
                                    text=True,capture_output=True)
            self.assertEqual(result.returncode,0,result.stderr or result.stdout)
            payload=runner/'s82-source-review'
            self.assertEqual({p.name for p in payload.iterdir()},
                set(expected)|{'SOURCE-PLAN.json','CAPTURE-RECEIPT.json','SOURCE-IDENTITY.json','manifest.json','SHA256SUMS.txt'})
            self.assertFalse(any(p.is_dir() for p in payload.iterdir()))

    def test_orphan_publish_fixture_empties_index_before_exact_run_payload(self):
        workflow=yaml.safe_load((HERE/'s82-source-pack-capture.yml').read_text())
        publish=next(step for step in workflow['jobs']['capture']['steps']
                     if step.get('name')=='Publish only this run\'s source crops and TEXT receipts to a review branch')['run']
        self.assertIn('git switch --orphan "$BRANCH"',publish)
        self.assertIn('git read-tree --empty',publish)
        self.assertNotIn('git rm -rf --cached .',publish)
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp); repo=root/'repo'; repo.mkdir()
            env=dict(os.environ,GIT_AUTHOR_NAME='Fixture',GIT_AUTHOR_EMAIL='fixture@example.invalid',
                     GIT_COMMITTER_NAME='Fixture',GIT_COMMITTER_EMAIL='fixture@example.invalid')
            def git(*args,check=True):
                return subprocess.run(['git',*args],cwd=repo,env=env,text=True,capture_output=True,check=check)
            git('init','-b','main'); (repo/'tracked.txt').write_text('baseline')
            git('add','tracked.txt'); git('commit','-m','baseline')
            git('switch','--orphan','review-fixture'); git('read-tree','--empty')
            old_cleanup=git('rm','-rf','--cached','.',check=False)
            self.assertNotEqual(old_cleanup.returncode,0)
            target='public-review/S82/fixture-run'; (repo/target).mkdir(parents=True)
            (repo/target/'CAPTURE-RECEIPT.json').write_text('{"status":"FAILED"}\n')
            git('add','--all',target); git('commit','-m','exact failure receipt')
            names=git('ls-tree','-r','--name-only','HEAD').stdout.splitlines()
            self.assertEqual(names,[target+'/CAPTURE-RECEIPT.json'])
            self.assertNotEqual(git('rev-parse','HEAD^',check=False).returncode,0)


if __name__ == '__main__':
    unittest.main()
