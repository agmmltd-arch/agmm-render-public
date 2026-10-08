"""Run the real date-extraction JS in hosted Chrome against offline source/negative cases.

No screenshots, programme media, APIs, approval or posting. CHROME_PATH is mandatory.
--before additionally proves the archived native tool fails the Channel 4 source case.
"""
import argparse
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import subprocess


def load(path):
    spec = importlib.util.spec_from_file_location('crop_dates_' + path.stem, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def html(body, head=''):
    return '<!doctype html><html><head><title>Date test</title>' + head + '</head><body>' + body + '</body></html>'


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--candidate', type=Path, required=True)
    parser.add_argument('--before', type=Path)
    parser.add_argument('--fixture', type=Path, required=True)
    parser.add_argument('--runner', type=Path, required=True)
    parser.add_argument('--out', type=Path, required=True)
    args = parser.parse_args()
    assert os.environ.get('GITHUB_ACTIONS') == 'true', 'DOM checks run on hosted Ubuntu'
    assert os.environ.get('CHROME_PATH'), 'Native hosted Chrome path required'
    args.out.mkdir(parents=True, exist_ok=True)
    published = '<span class="c-article-date">20 October 2025</span>'
    header = '<header><h1>Source headline</h1></header>'
    cases = {
        'channel4_cached_source_topology': {'html': args.fixture.read_text(), 'expected': '2025-10-20'},
        'main_body_explicit_publication': {'html': html('<main>' + header + '<section>' + published + '</section></main>'), 'expected': '2025-10-20'},
        'metadata_precedence': {'html': html('<article>' + header + published + '</article>', '<meta property="article:published_time" content="2024-03-04T09:30:00Z">'), 'expected': '2024-03-04'},
        'json_ld_precedence': {'html': html('<article>' + header + published + '</article>', '<script type="application/ld+json">{"datePublished":"2023-05-06"}</script>'), 'expected': '2023-05-06'},
        'generic_headline_date_preserved': {'html': html('<article><header><h1>Headline</h1><span class="publish-date">4 March 2026</span></header></article>'), 'expected': '2026-03-04'},
        'updated_only_refused': {'html': html('<article>' + header + '<span class="c-article-date">Updated 20 October 2025</span></article>'), 'expected': None},
        'hidden_publication_refused': {'html': html('<article>' + header + '<span class="c-article-date" style="display:none">20 October 2025</span></article>'), 'expected': None},
        'invisible_publication_refused': {'html': html('<article>' + header + '<span class="c-article-date" style="visibility:hidden">20 October 2025</span></article>'), 'expected': None},
        'related_sidebar_refused': {'html': html('<article>' + header + '<aside>' + published + '</aside></article>'), 'expected': None},
        'footer_refused': {'html': html('<article>' + header + '<footer>' + published + '</footer></article>'), 'expected': None},
        'outside_article_refused': {'html': html('<main><article>' + header + '</article><section>' + published + '</section></main>'), 'expected': None},
        'body_event_date_not_publication': {'html': html('<article>' + header + '<p>The event happened on 20 October 2025.</p></article>'), 'expected': None},
        'undated_refused': {'html': html('<article>' + header + '<p>No publication date supplied.</p></article>'), 'expected': None},
    }
    modules = {'candidate': load(args.candidate)}
    if args.before:
        modules['before'] = load(args.before)
    payload = {'expressions': {name: mod.JS_META for name, mod in modules.items()}, 'cases': cases}
    input_path = args.out / 'input.json'
    raw_path = args.out / 'native-dom.json'
    input_path.write_text(json.dumps(payload, indent=2) + '\n')
    subprocess.run(['node', str(args.runner), str(input_path), str(raw_path)], check=True, timeout=120)
    native = json.loads(raw_path.read_text())
    results = {}
    for version, module in modules.items():
        results[version] = []
        for name, case in cases.items():
            meta = native[version][name]
            dates = [(source, module.parse_date(value)) for source, value in meta['dates']]
            dates = [(source, parsed) for source, parsed in dates if parsed]
            actual = dates[0][1][1] if dates else None
            results[version].append({'case': name, 'expected': case['expected'], 'actual': actual,
                                     'date_source': dates[0][0] if dates else None,
                                     'passed': actual == case['expected']})
    failed = {version: [row for row in rows if not row['passed']] for version, rows in results.items()}
    proof = {'scope': 'Exact runtime JS_META plus parse_date, offline native Ubuntu Chrome DOM; date extraction only',
             'inputs': {str(path): hashlib.sha256(path.read_bytes()).hexdigest() for path in
                        [args.candidate, args.fixture, args.runner] + ([args.before] if args.before else [])},
             'results': results, 'failures': failed,
             'candidate_passed': not failed['candidate'], 'programme_media_io': False,
             'source_crop_pixels_or_master_quality_approved': False}
    if args.before:
        proof['known_bad_before_proved'] = any(row['case'] == 'channel4_cached_source_topology' for row in failed['before'])
    (args.out / 'qualification.json').write_text(json.dumps(proof, indent=2) + '\n')
    print(json.dumps(proof, indent=2))
    assert proof['candidate_passed'], 'Candidate DOM qualification failed'
    if args.before:
        assert proof['known_bad_before_proved'], 'Archived tool did not fail the real source topology'


if __name__ == '__main__':
    main()
