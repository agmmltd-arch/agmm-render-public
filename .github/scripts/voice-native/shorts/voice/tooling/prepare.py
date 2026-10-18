#!/usr/bin/env python3
"""Extract the Spoken script from a scripts-v2/S??.md card, merge its authored paragraphs
down to 4-5 (per PRODUCTION-RULES.md: never crossing a section, one-line dramatic beats
standalone -- the final CTA line is always kept standalone; content paragraphs are merged
smallest-adjacent-first, capped so no merged paragraph runs too long for the TTS to hold its
breath, same principle as the pilot's F01 fix), and extract a proper-noun list for isolated
pronunciation checks. Writes voice/<ID>/paragraphs.txt, voice/<ID>/names.txt,
voice/<ID>/source.json.
Usage: prepare.py <scripts_dir> <voice_dir> <ID> [max_words_per_paragraph]
"""
import json, math, os, re, sys
from pathlib import Path

STOP = {'the','so','here','this','that','when','then','now','if','after','a','an','it','its',
        "it's","here's","and","but","ask","write","follow","think","in","for","once","over",
        "more","at","across","on","only","one","because","despite","what","who","why","how",
        "we","you","your","did","do","does","not","no","is","are","was","were","has","have",
        "had","of","to","from","with","by","or","so,","since","plus","under","out","yes","today",
        "tomorrow","last","next","most","some","there","these","those","been","being","just"}
GENERIC = {'ai','uk','it','us','nhs','ceo','md','cto','cfo','gdp','gbp','usd','eu','api','llm',
           'york','months','year','years','now','ok','tv','pr','hr','id'}

def extract_spoken(md_text):
    m = re.search(r'## Spoken script\n\n(.*?)\n\n## ', md_text, re.S)
    body = m.group(1).strip()
    paras = [p.strip().replace('\n', ' ') for p in body.split('\n\n') if p.strip()]
    return paras

def merge_paragraphs(paras, max_words=75):
    if len(paras) <= 1:
        return paras[:]
    cta = paras[-1]
    content = paras[:-1]
    # keep CTA standalone always (it's the one-line dramatic/CTA beat per PRODUCTION-RULES.md)
    while len(content) > 4:
        best_i, best_cost = None, None
        for i in range(len(content) - 1):
            wc = len(content[i].split()) + len(content[i + 1].split())
            if best_cost is None or wc < best_cost:
                best_cost, best_i = wc, i
        if best_cost is not None and best_cost > max_words and len(content) <= 5:
            # already close enough and merging would over-stuff a paragraph; stop here
            break
        content[best_i] = content[best_i] + ' ' + content[best_i + 1]
        del content[best_i + 1]
    return content + [cta]

DICT_PATH = Path('/usr/share/dict/words')
_DICT = set(w.strip().lower() for w in DICT_PATH.read_text(errors='ignore').splitlines()) if DICT_PATH.exists() else set()

def _strip_possessive(w):
    return re.sub(r"[’']s$", '', w).rstrip("’'.,!?")

def extract_names(spoken_text, company_field):
    candidates = re.findall(r"[A-Z][a-zA-Z'\-]*(?:\s+[A-Z][a-zA-Z'\-]*)*", spoken_text)
    names = []
    seen = set()
    for c in candidates:
        words = [_strip_possessive(w) for w in c.split()]
        words = [w for w in words if w]
        while words and (words[0].lower() in STOP or words[0].lower() in GENERIC):
            words = words[1:]
        while words and (words[-1].lower() in STOP or words[-1].lower() in GENERIC):
            words = words[:-1]
        if not words:
            continue
        if len(words) == 1:
            w = words[0]
            if w.lower() in GENERIC:
                continue
            if len(w) <= 2 and not (w.isupper() and len(w) == 2):  # keep short acronyms like "EY"
                continue
            if w.lower() in _DICT:  # a real English word -> not a proper noun worth checking
                continue
        phrase = ' '.join(words)
        key = phrase.lower()
        if key in seen:
            continue
        seen.add(key)
        names.append(phrase)
    # always consider the header company's first clause if it plausibly appears verbatim
    primary = re.split(r'[(,]', company_field)[0].strip()
    if primary and primary.lower() not in seen and primary in spoken_text:
        names.insert(0, primary)
        seen.add(primary.lower())
    return names


def voicelead_prerequisite_issues(voice_dir, sid):
    """Read text/metadata only. A blocked take is never repaired or passed here."""
    voice_dir = Path(voice_dir)
    piece = voice_dir / sid
    script = voice_dir.parent / 'scripts-v2' / f'{sid}.md'
    issues = []

    def text(path):
        try:
            return path.read_text(encoding='utf-8')
        except (OSError, UnicodeError):
            issues.append(f'missing/unreadable prerequisite: {path.name}')
            return ''

    def obj(path):
        raw = text(path)
        if not raw:
            return {}
        try:
            value = json.loads(raw)
            if isinstance(value, dict):
                return value
        except ValueError:
            pass
        issues.append(f'invalid prerequisite JSON: {path.name}')
        return {}

    def norm(value):
        return ' '.join(value.split()) if isinstance(value, str) else ''

    res = obj(piece / 'RESULT.json')
    final = res.get('final') or {}
    if not isinstance(final, dict):
        issues.append('invalid RESULT final metadata')
        final = {}
    status = res.get('status')
    local = str(status or '').startswith('FINISHED_LOCAL') or res.get('listening_review') == 'UNJUDGED'
    expected = 'FINISHED_LOCAL_CHECKS_PASS' if local else 'FINISHED'
    if status != expected:
        errors = [str(final.get('error') or '')]
        attempts = res.get('attempts') or []
        errors += [str(x.get('error') or '') for x in attempts if isinstance(x, dict)] if isinstance(attempts, list) else []
        budget = any('billing_api_budget_exhausted' in x or ('Mistral HTTP 402' in x and 'API budget exhausted' in x) for x in errors)
        issues.append('RESULT status %s%s' % (status, ' (Mistral budget exhausted; not a rate-limit retry)' if budget else ''))
    elif not local:
        for key in ('naturalness', 'emphasis'):
            score = final.get(key)
            if not isinstance(score, (int, float)) or not math.isfinite(score) or score < 6.5:
                issues.append(f'listening {key} under 6.5 or missing')
        votes = final.get('robotic_votes') or []
        if not isinstance(votes, list):
            issues.append('invalid robotic cadence vote metadata')
        elif sum(bool(x) for x in votes) >= 2:
            issues.append('robotic cadence: at least two votes')
    if res and res.get('id') != sid:
        issues.append('RESULT id does not match short')

    md = text(script)
    try:
        spoken = extract_spoken(md) if md else []
    except (AttributeError, ValueError):
        spoken = []
    canonical = norm(' '.join(spoken))
    if not canonical:
        issues.append('current authored Spoken script is missing/invalid')
    paras = [p.strip() for p in text(piece / 'paragraphs.txt').strip().split('\n\n') if p.strip()]
    source = obj(piece / 'source.json')
    # Keep the producer's absolute source path as provenance when a frozen bundle moves to a hosted runner.
    # The ID/basename plus exact authored-text checks below bind its content without rewriting that provenance.
    if source.get('id') != sid or not source.get('script_file') or Path(str(source.get('script_file', ''))).name != script.name:
        issues.append('source.json id/script_file is missing or stale')
    for key in ('full_spoken_text', 'original_paragraphs', 'merged_paragraphs'):
        value = source.get(key)
        if key != 'full_spoken_text':
            value = ' '.join(value) if isinstance(value, list) and all(isinstance(x, str) for x in value) else ''
        if not canonical or norm(value) != canonical:
            issues.append(f'source.json {key} is missing or stale')
    # Reuse native spoken expansion/folding, with no numeric tolerance.
    # A curated rendering may also have existing reviewed CLEAN transcript edits.
    # This checks text equivalence only; the native take-SHA/quality rules still run.
    import difflib
    from voice_pace import _expanded
    from asr_triage import fold
    def units(value):
        return _expanded(fold(value).split()) if isinstance(value, str) else []
    equivalent = bool(paras) and units(' '.join(paras)) == units(canonical)
    if paras and canonical and not equivalent:
        try:
            triage = json.loads((voice_dir / 'ASR-TRIAGE.json').read_text())
        except (OSError, ValueError):
            triage = {}
        rules = triage.get(sid, {}) if isinstance(triage, dict) else {}
        rules = rules if isinstance(rules, dict) else {}
        expected, actual = units(canonical), units(' '.join(paras))
        reviewed = set()
        for rule in rules.values():
            if not isinstance(rule, dict) or rule.get('verdict') != 'CLEAN':
                continue
            reviewer = rule.get('by') or rule.get('clean_by')
            script_units = units(rule.get('script'))
            if (not reviewer or reviewer == 'voice_lead_check' or not (rule.get('why') or rule.get('clean_by')) or not script_units
                    or norm(rule.get('script')) not in canonical):
                continue
            offsets = [i for i in range(len(expected) - len(script_units) + 1)
                       if expected[i:i + len(script_units)] == script_units]
            if len(offsets) != 1:
                continue
            for key in ('mistral', 'whisper'):
                if not isinstance(rule.get(key), str) or not rule[key].strip():
                    continue
                heard = units(rule[key])
                for tag, a, b, c, d in difflib.SequenceMatcher(None, script_units, heard, autojunk=False).get_opcodes():
                    if tag != 'equal':
                        reviewed.add((offsets[0] + a, offsets[0] + b, tuple(heard[c:d])))
        equivalent = all((a, b, tuple(actual[c:d])) in reviewed for tag, a, b, c, d
                         in difflib.SequenceMatcher(None, expected, actual, autojunk=False).get_opcodes()
                         if tag != 'equal')
    if not paras or (canonical and not equivalent):
        issues.append('paragraphs.txt does not match current authored spoken words')
    names = [x.strip() for x in text(piece / 'names.txt').splitlines() if x.strip()]
    # names_extracted is the producer's heuristic seed. The reviewed names.txt may
    # correct it (S87: Guardian replaces the false-positive Unions); preserve that
    # native curation. Freshness below binds names changes to a new real check.
    if not names:
        issues.append('names.txt is empty/missing; name checks must not be skipped')

    receipt = obj(piece / f'{sid}.receipt.json')
    if paras and norm(receipt.get('full_script_text')) != norm(' '.join(paras)):
        issues.append('assembled receipt script does not match paragraphs.txt')
    words = obj(piece / f'{sid}.words.json').get('words')
    if not isinstance(words, list) or not words:
        issues.append('assembled word timings missing/empty')
    wanted = {f'P{i:02d}' for i in range(1, len(paras) + 1)}
    found = {p.name.split('.')[0] for p in piece.glob('P[0-9][0-9].receipt.json')}
    if found != wanted:
        issues.append('paragraph receipt set does not match paragraphs.txt')
    for i, para in enumerate(paras, 1):
        stem = f'P{i:02d}'
        if stem in found and norm(obj(piece / f'{stem}.receipt.json').get('text')) != norm(para):
            issues.append(f'{stem} receipt text does not match paragraphs.txt')
        for suffix in ('.wav', '.words.json'):
            if not (piece / f'{stem}{suffix}').is_file():
                issues.append(f'missing prerequisite: {stem}{suffix}')
    if not (piece / f'{sid}.wav').is_file():
        issues.append(f'missing prerequisite: {sid}.wav')
    return issues


def voicelead_input_mtime(voice_dir, sid):
    """Freshness uses file metadata; programme audio bytes are never read here."""
    voice_dir = Path(voice_dir)
    piece = voice_dir / sid
    # Current spoken words are validated above. Editing reference notes in the
    # authored Markdown cannot stale an unchanged, already checked voice take.
    paths = [piece / name for name in ('RESULT.json', 'paragraphs.txt', 'names.txt', 'source.json', f'{sid}.wav', f'{sid}.words.json', f'{sid}.receipt.json')]
    paths += list(piece.glob('P[0-9][0-9].*'))
    return max((p.stat().st_mtime for p in paths if p.is_file()), default=0.0)


def voicelead_runtime_issue():
    if not (sys.platform.startswith('linux') and os.environ.get('GITHUB_ACTIONS') == 'true'
            and os.environ.get('GITHUB_REPOSITORY') == 'agmmltd-arch/agmm-render-public'
            and os.environ.get('RUNNER_OS') == 'Linux'):
        return 'hosted voicelead required on public agmm-render-public Ubuntu Actions; no local media processing'
    return ''


def main():
    scripts_dir = Path(sys.argv[1])
    voice_dir = Path(sys.argv[2])
    sid = sys.argv[3]
    max_words = int(sys.argv[4]) if len(sys.argv) > 4 else 75

    md_text = (scripts_dir / f'{sid}.md').read_text()
    m_company = re.search(r'\|\s*Company\s*\|\s*(.*?)\s*\|', md_text)
    company = m_company.group(1).strip() if m_company else ''
    m_title = re.search(r'^# S\d+: (.*)$', md_text, re.M)
    title = m_title.group(1).strip() if m_title else company

    paras = extract_spoken(md_text)
    merged = merge_paragraphs(paras, max_words)

    piece_dir = voice_dir / sid
    piece_dir.mkdir(parents=True, exist_ok=True)
    (piece_dir / 'paragraphs.txt').write_text('\n\n'.join(merged) + '\n')

    full_text = ' '.join(paras)
    names = extract_names(full_text, company)
    (piece_dir / 'names.txt').write_text('\n'.join(names) + '\n')

    (piece_dir / 'source.json').write_text(json.dumps({
        'id': sid, 'title': title, 'company': company,
        'script_file': str((scripts_dir / f'{sid}.md').resolve()),
        'original_paragraphs': paras, 'original_paragraph_count': len(paras),
        'merged_paragraphs': merged, 'merged_paragraph_count': len(merged),
        'merged_word_counts': [len(p.split()) for p in merged],
        'total_words': sum(len(p.split()) for p in paras),
        'full_spoken_text': full_text,
        'names_extracted': names,
    }, indent=2) + '\n')
    print(sid, '-', title)
    print(' paragraphs:', len(paras), '->', len(merged), [len(p.split()) for p in merged])
    print(' names:', names)

if __name__ == '__main__':
    main()
