#!/usr/bin/env python3
"""Fail-closed text-only preflight for the isolated S82 source-capture workflow."""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import subprocess

REPOSITORY = 'agmmltd-arch/agmm-render-public'
PARENT_SHA = 'ab8011d077cd219319a04670c7e89f367d45934f'
PLAN_PATH = Path('.github/scripts/s82-source-pack-plan.json')
HELPER_PATH = Path('.github/scripts/s82-source-pack.mjs')
PLAN_SHA256 = '0fe325104557169140b7b7ca1643acbbcbac92c2c57a8f6075845b24055ca661'
HELPER_SHA256 = 'd5e99cfe2825763b199e0dbe8dea0f90475ec540475ff596e1f2bc268623b576'
INHERITED_BLOBS = {
    '.github/scripts/capture_short_package.py': '65f9b89f126c6113a91061a2f1f361954c96a0ae',
    '.github/scripts/render_short_package.py': '754099346a84c5bd305f5684ef24399a53bd9697',
    '.github/scripts/s90-source-pack.mjs': '8ba7e1ea22b8a463f9538556b4836f884d73985e',
    '.github/workflows/s90-silent-preview.yml': 'ec8b5258881470a8b83ee3c6a40b3f8a83239e8a',
    '.github/workflows/s90-source-pack-capture.yml': '73e3194ddd9285fcb050954110a2af5c2ff0b39f',
}


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def has_public_s82_media(paths: list[str]) -> list[str]:
    media = {'.wav', '.mp3', '.m4a', '.flac', '.mp4', '.mov', '.mkv'}
    return [p for p in paths if 's82' in p.lower() and Path(p).suffix.lower() in media]


def validate_preflight(*, env: dict[str, str], repo: dict, head: str, parent: str,
                       plan_bytes: bytes, helper_bytes: bytes,
                       inherited_blobs: dict[str, str], tracked_paths: list[str]) -> None:
    if env.get('GITHUB_ACTIONS') != 'true' or env.get('RUNNER_OS') != 'Linux':
        raise ValueError('requires GitHub Actions Linux runner')
    if env.get('GITHUB_REPOSITORY') != REPOSITORY or repo.get('full_name') != REPOSITORY:
        raise ValueError('wrong GitHub repository')
    if env.get('S82_DIAGNOSTIC_ONLY', 'false') not in ('true', 'false'):
        raise ValueError('diagnostic-only workflow input must be a boolean')
    if repo.get('private') is not False or repo.get('visibility') != 'public':
        raise ValueError('source-crop target must be the public repository')
    if env.get('GITHUB_REF') != 'refs/heads/main' or env.get('GITHUB_SHA') != head or parent != PARENT_SHA:
        raise ValueError('main preimage moved; refresh and review the guarded parent')
    if PLAN_SHA256 == 'TO_BE_PINNED' or sha256(plan_bytes) != PLAN_SHA256:
        raise ValueError('frozen source-plan pin mismatch')
    if HELPER_SHA256 == 'TO_BE_PINNED' or sha256(helper_bytes) != HELPER_SHA256:
        raise ValueError('frozen source-helper pin mismatch')
    if env.get('S82_PLAN_SHA256') != PLAN_SHA256 or env.get('S82_HELPER_SHA256') != HELPER_SHA256:
        raise ValueError('workflow and preflight source pins differ')
    for path, expected in INHERITED_BLOBS.items():
        if inherited_blobs.get(path) != expected:
            raise ValueError(f'inherited helper preimage mismatch: {path}')
    forbidden = has_public_s82_media(tracked_paths)
    if forbidden:
        raise ValueError(f'public source-capture preimage unexpectedly contains S82 media inputs: {forbidden}')
    plan = json.loads(plan_bytes)
    if plan.get('schema') != 'agmm-s82-source-plan-v3' or plan.get('story_id') != 'S82':
        raise ValueError('source plan schema/story id mismatch')
    if len(plan.get('sources', [])) != 3 or len(plan.get('collection_policy', {}).get('exact_capture_files', [])) != 18:
        raise ValueError('source plan is incomplete')
    policy = plan['collection_policy']
    if any(policy.get(name) is not False for name in ('photos', 'clips', 'audio_or_video_download', 'follow_links', 'full_page_screenshots')):
        raise ValueError('source-only capture policy changed')
    if policy.get('automated_page_load_query') != '?utm_source=qa&utm_campaign=qa_release_audit':
        raise ValueError('required QA query tag changed')


def main() -> int:
    repo_path = Path(os.environ['RUNNER_TEMP']) / 's82-repository.json'
    repo = json.loads(repo_path.read_text())
    inherited = {
        path: subprocess.check_output(['git', 'rev-parse', f'HEAD:{path}'], text=True).strip()
        for path in INHERITED_BLOBS
    }
    tracked = subprocess.check_output(['git', 'ls-tree', '-r', '--name-only', 'HEAD'], text=True).splitlines()
    validate_preflight(
        env=dict(os.environ), repo=repo,
        head=subprocess.check_output(['git', 'rev-parse', 'HEAD'], text=True).strip(),
        parent=subprocess.check_output(['git', 'rev-parse', 'HEAD^'], text=True).strip(),
        plan_bytes=PLAN_PATH.read_bytes(), helper_bytes=HELPER_PATH.read_bytes(),
        inherited_blobs=inherited, tracked_paths=tracked,
    )
    print('S82 public source-capture preflight PASS; no media inputs present.')
    return 0


if __name__ == '__main__':
    try:
        raise SystemExit(main())
    except Exception as error:
        raise SystemExit(f'S82 source-capture preflight refused: {error}')
