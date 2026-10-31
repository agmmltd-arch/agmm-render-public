#!/usr/bin/env python3
"""Ground an authenticated preview response against exact estimated inputs on Ubuntu."""
import io, json, os, re, subprocess, sys, zipfile
from pathlib import Path
import hosted_preview_prepare_candidate as prep
import hosted_ground_generic as original
from writer_crypto import crypt


def ground(root, prompt_path, response_path, output, manifest_sha, password):
    need = prep.need
    prompt = json.loads(crypt(prompt_path.read_bytes(), password, True))
    saved = json.loads(crypt(response_path.read_bytes(), password, True))
    sid = prompt.get('id')
    data = prep.validate(root, sid, manifest_sha)
    meta = saved.get('meta') or {}
    rid, run_id = meta.get('request_id'), meta.get('run_id')
    need(prompt.get('schema') == 'agmm-story-preview-prompt-v1' and prompt.get('timing') == 'estimated'
         and prompt.get('release_approved') is False and saved.get('id') == sid
         and prompt.get('source_manifest_sha256') == manifest_sha
         and prompt.get('revision_script_sha256') == data['revision_script_sha256']
         and prompt.get('prompt_sha256') == saved.get('prompt_sha256')
         and prep.sha(prompt.get('prompt', '').encode()) == prompt.get('prompt_sha256')
         and meta.get('model_key') == 'q30a3b-iq3xxs' and re.fullmatch(r'w[0-9a-f]{12}', rid or '')
         and str(run_id or '').isdigit(), 'preview response identity differs')
    run = original.api('repos/%s/actions/runs/%s' % (original.REPO, run_id))
    need(run.get('path') == original.WRITER and run.get('event') == 'workflow_dispatch'
         and run.get('run_attempt') == 1 and run.get('status') == 'completed'
         and run.get('conclusion') == 'success' and run.get('display_title') == 'llmw ' + rid,
         'preview writer run differs')
    wf = original.api('repos/%s/contents/%s?ref=%s' % (original.REPO, original.WRITER, run['head_sha']))
    need(wf.get('sha') == original.BLOB, 'preview writer workflow differs')
    rows = original.api('repos/%s/actions/runs/%s/artifacts?per_page=100' % (original.REPO, run_id))['artifacts']
    items = [a for a in rows if a.get('name') == 'llm-' + rid and not a.get('expired')]
    need(len(items) == 1 and items[0].get('workflow_run', {}).get('id') == run['id']
         and re.fullmatch(r'sha256:[a-f0-9]{64}', items[0].get('digest') or ''), 'preview writer artifact differs')
    raw = subprocess.check_output(['gh', 'api', 'repos/%s/actions/artifacts/%s/zip' % (original.REPO, items[0]['id'])])
    need(len(raw) < 10000000 and 'sha256:' + prep.sha(raw) == items[0]['digest'], 'preview artifact bytes differ')
    with zipfile.ZipFile(io.BytesIO(raw)) as archive:
        need(archive.namelist() == ['response.enc'] and archive.getinfo('response.enc').file_size < 9000000,
             'preview artifact inventory differs')
        provider = json.loads(crypt(archive.read('response.enc'), password, True))
    need(provider['meta'].get('request_id') == rid and provider['meta'].get('model') == 'q30a3b-iq3xxs',
         'preview provider identity differs')
    answer = ((provider['response'].get('choices') or [{}])[0].get('message') or {}).get('content') or ''
    answer = re.sub(r'(?is)<think>.*?</think>', '', answer.strip()).strip()
    need(answer == saved.get('response'), 'preview saved response differs')
    for rel in data['files']:
        if rel.startswith('shorts/'):
            target = prep.ROOT / rel
            target.parent.mkdir(parents=True, exist_ok=True)
            need(not target.is_symlink(), 'preview runtime input is a symlink')
            raw_input = (root / rel).read_bytes()
            if target.exists():
                need(target.is_file() and target.read_bytes() == raw_input, 'preview runtime input differs')
            else:
                target.write_bytes(raw_input)
    old_timing = prep.ROOT / 'shorts/voice' / sid / (sid + '.words.json')
    need(not old_timing.exists() and not old_timing.is_symlink(), 'old voice timing present')
    original.story.STORY_DATA_MD = str(root / 'story-data/STORY-DATA.md')
    need(original.story.load_schema() is not None, 'story schema missing')
    ctx = original.story.build_context(sid)
    need(ctx['mode'] == 'estimated' and ctx['ranges'] is not None
         and prep.sha(original.story.build_prompt(ctx)['full'].encode()) == prompt['prompt_sha256'],
         'estimated preview context differs')
    value, failures, _ = original.story.extract(sid, ctx=ctx, replies=[{'text': answer,
        'lane': 'ghw-q30a3b-iq3xxs', 'family': 'free-hosted'}], retries=0, save_receipts=False)
    need(value is not None, 'original grounding produced no preview')
    errors = original.story.schema_errors(value) if value.get('status') != 'rejected' else []
    result = {'schema':'agmm-hosted-story-preview-v1', 'id':sid,
              'revision_script_sha256':data['revision_script_sha256'], 'source_manifest_sha256':manifest_sha,
              'prompt_sha256':prompt['prompt_sha256'], 'writer_run_id':run_id,
              'timing':'estimated', 'story':value, 'grounding_failures':failures, 'schema_errors':errors,
              'release_approved':False, 'independent_av_review':False}
    need(not output.exists() and not output.is_symlink(), 'preview output already exists')
    output.write_bytes(crypt(json.dumps(result, ensure_ascii=False).encode(), password))
    print('Original preview grounding completed; no release or audiovisual approval.')


def main():
    prep.need(sys.platform.startswith('linux') and os.getenv('GITHUB_ACTIONS') == 'true', 'Ubuntu Actions required')
    root, prompt, response, output = map(Path, sys.argv[1:5])
    ground(root, prompt, response, output, os.environ['STORY_PREVIEW_MANIFEST_SHA'], os.environ['AGMM_WRITER_PASS'])


if __name__ == '__main__':
    main()
