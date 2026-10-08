"""Exercise the exact runtime Next assignment against the native duplicate-control case."""
import argparse
import ast
import json
import os
from pathlib import Path
from playwright.sync_api import sync_playwright


def selector(runtime, page):
    tree = ast.parse(Path(runtime).read_text())
    nodes = [n for n in ast.walk(tree) if isinstance(n, ast.Assign)
             and any(isinstance(t, ast.Name) and t.id == 'next_button' for t in n.targets)]
    assert len(nodes) == 1, 'Runtime assignment must be unique'
    return eval(compile(ast.Expression(nodes[0].value), str(runtime), 'eval'), {'page': page})


def html(footer=True, disabled=False, duplicate=False, extra_feed=False):
    # Native trace: editor contentinfo Next plus carousel-inline-right-button Next.
    buttons = ('<button id="editor-next" type="button" ' + ('disabled' if disabled else '') + '>Next</button>') if footer else ''
    if duplicate:
        buttons += '<button type="button">Next</button>'
    return ('<main><div role="dialog" aria-label="Editor"><footer role="contentinfo">' + buttons +
            '</footer></div><button type="button" aria-label="Next" data-testid="carousel-inline-right-button">→</button>' +
            ('<button aria-label="Next">→</button>' if extra_feed else '') + '</main>')


def main():
    assert os.environ.get('GITHUB_ACTIONS') == 'true', 'Browser qualification runs on public Ubuntu Actions'
    parser = argparse.ArgumentParser()
    parser.add_argument('--before', required=True)
    parser.add_argument('--candidate', required=True)
    parser.add_argument('--output', required=True)
    args = parser.parse_args()
    report = {'scope': 'exact Next assignment, native duplicate-control topology; no account/media/public action',
              'before': {}, 'candidate': []}
    with sync_playwright() as pw:
        browser = pw.chromium.launch()
        page = browser.new_page()
        page.set_content(html())
        old = selector(args.before, page)
        assert old.count() == 2
        try:
            old.wait_for(state='visible', timeout=1000)
        except Exception as exc:
            assert 'strict mode violation' in str(exc), 'Different failure cannot qualify this repair'
            report['before'] = {'verdict': 'FAIL', 'matched': 2, 'native_failure_reproduced': 'strict mode violation'}
        else:
            raise AssertionError('Original selector did not fail on native duplicate case')
        cases = [('native_duplicate', html(), 1, True), ('additional_feed_next', html(extra_feed=True), 1, True),
                 ('missing_editor_next', html(footer=False), 0, None),
                 ('disabled_editor_next', html(disabled=True), 1, False),
                 ('ambiguous_editor_footer', html(duplicate=True), 2, None)]
        for name, source, count, enabled in cases:
            page.set_content(source)
            selected = selector(args.candidate, page)
            assert selected.count() == count, name
            if count == 1:
                assert selected.get_attribute('id') == 'editor-next', name
                assert selected.is_enabled() is enabled, name
                if enabled:
                    selected.click(trial=True, timeout=1000)
            elif count == 2:
                try:
                    selected.wait_for(state='visible', timeout=1000)
                except Exception as exc:
                    assert 'strict mode violation' in str(exc), name
                else:
                    raise AssertionError('Candidate must retain ambiguity refusal')
            report['candidate'].append({'case': name, 'verdict': 'PASS', 'matched': count, 'enabled': enabled})
        browser.close()
    report['passed'] = len(report['candidate']) == 5 and all(x['verdict'] == 'PASS' for x in report['candidate'])
    Path(args.output).write_text(json.dumps(report, indent=2) + '\n')
    print(json.dumps(report))


if __name__ == '__main__':
    main()
