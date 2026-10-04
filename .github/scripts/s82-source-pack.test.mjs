import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import { findVisibleLogo, canonicalURL, sanitizeLogoDiscovery, taggedURL, validateLogoCandidate, validatePlan } from './s82-source-pack.mjs';

const here = new URL('.', import.meta.url);
const plan = JSON.parse(fs.readFileSync(new URL('./SOURCE-PLAN.json', here), 'utf8'));

test('frozen source plan has all 18 distinct native captures and 3 exact publishers', () => {
  assert.equal(validatePlan(plan), true);
  assert.deepEqual(plan.sources.map(x => x.publisher), [
    'Santander', 'The Irish News / Press Association', 'Leicestershire Live / Press Association',
  ]);
  const files = plan.sources.flatMap(source => source.files.map(row => row.file));
  assert.equal(files.length, 18);
  assert.equal(new Set(files).size, 18);
  assert.deepEqual([...files].sort(), [...plan.collection_policy.exact_capture_files].sort());
});

test('two previously uncovered spoken claims now map to exact Leicestershire Live paragraphs', () => {
  const source = plan.sources.find(x => x.key === 'gap-claims');
  assert.match(source.claim_paragraphs['gap-most-banks'], /Most banks have yet to put a figure/);
  assert.match(source.claim_paragraphs['gap-q1-value'], /35 million euros \(£30\.3 million\)/);
  assert.deepEqual(plan.script_claim_coverage[1].evidence, ['gap-claims.gap-most-banks']);
  assert.deepEqual(plan.script_claim_coverage[2].evidence, ['gap-claims.gap-q1-value']);
});

test('the opening cost-and-date sentence stays explicitly an inference, not a cleared direct quote', () => {
  assert.equal(plan.script_claim_coverage[0].status, 'COMPOSITE_INFERENCE_REVIEW_REQUIRED');
  assert.match(plan.script_claim_coverage[0].note, /does not directly establish/i);
  assert.match(plan.editorial_guards.join(' '), /never show.*£860bn typo/i);
});

test('tagged source loads preserve pinned path and add the mandatory QA campaign', () => {
  const raw = plan.sources[2].url;
  const tagged = new URL(taggedURL(raw));
  assert.equal(tagged.searchParams.get('utm_source'), 'qa');
  assert.equal(tagged.searchParams.get('utm_campaign'), 'qa_release_audit');
  assert.equal(canonicalURL(tagged.href), canonicalURL(raw));
});

test('plan rejects any output name outside its exact source-capture allowlist', () => {
  const bad = structuredClone(plan);
  bad.sources[2].files[0].file = 'unreviewed-extra.png';
  assert.throws(() => validatePlan(bad), /exact output allowlist/);
});

test('plan rejects a missing spoken claim crop instead of counting headline metadata as coverage', () => {
  const bad = structuredClone(plan);
  delete bad.sources[2].claim_paragraphs['gap-most-banks'];
  assert.throws(() => validatePlan(bad), /no exact paragraph binding|lacks exact source-text binding/);
});

test('plan rejects a source host not explicitly allowlisted', () => {
  const bad = structuredClone(plan);
  bad.sources[2].allowed_hosts = ['leicestermercury.co.uk'];
  assert.throws(() => validatePlan(bad), /unpinned or off-list origin/);
});

test('no capture passage includes the excluded GBP 860bn source typo', () => {
  const text = JSON.stringify(plan.sources.map(s => s.claim_paragraphs));
  assert.doesNotMatch(text, /£860 billion/i);
});

test('logo failure diagnostics are capped, metadata-only and strip query/fragment values', () => {
  const rows = Array.from({ length: 30 }, (_, i) => ({
    kind: i === 0 ? 'header' : 'descendant', headerIndex: 0, tag: i === 0 ? 'header' : 'img',
    rect: { x: 1.234, y: 2, width: 192, height: 36 }, display: 'block', visibility: 'visible', opacity: '1',
    label: i === 0 ? '' : 'Santander Bank',
    url: i === 0 ? '' : 'https://www.santander.com/content/logo.svg?secret=must-not-escape#private',
    innerHTML: '<img src="private">',
  }));
  const diagnostic = sanitizeLogoDiscovery({ headerCount: 1, candidateCount: 0, diagnosticRows: rows }, plan.sources[0].url);
  assert.equal(diagnostic.header_count, 1);
  assert.equal(diagnostic.candidate_count, 0);
  assert.equal(diagnostic.diagnostic_rows.length, 20);
  assert.equal(diagnostic.diagnostic_rows[1].url_host, 'www.santander.com');
  assert.equal(diagnostic.diagnostic_rows[1].url_path, '/content/logo.svg');
  assert.equal(diagnostic.diagnostic_rows[1].rect.x, 1.23);
  assert.doesNotMatch(JSON.stringify(diagnostic), /secret|private|innerHTML|must-not-escape/);
});

test('logo diagnostics safely report off-host sources and reject them for capture', () => {
  const candidate = { tag: 'img', label: 'Santander Bank', url: 'https://evil.example/logo.svg?token=hidden' };
  const diagnostic = sanitizeLogoDiscovery({ headerCount: 1, candidateCount: 1,
    diagnosticRows: [{ kind: 'descendant', headerIndex: 0, tag: 'img', label: candidate.label, url: candidate.url }] },
    plan.sources[0].url);
  assert.equal(diagnostic.diagnostic_rows[0].url_host, 'evil.example');
  assert.equal(diagnostic.diagnostic_rows[0].url_path, '/logo.svg');
  assert.doesNotMatch(JSON.stringify(diagnostic), /token=hidden/);
  assert.throws(() => validateLogoCandidate(candidate, plan.sources[0], plan.sources[0].url), /same-source HTTPS image/);
  assert.throws(() => validateLogoCandidate({ ...candidate, url: 'http://www.santander.com/logo.svg' }, plan.sources[0], plan.sources[0].url), /same-source HTTPS image/);
  assert.throws(() => validateLogoCandidate({ ...candidate, tag: 'svg', url: 'https://www.santander.com/logo.svg' }, plan.sources[0], plan.sources[0].url), /same-source HTTPS image/);
  assert.equal(validateLogoCandidate({ ...candidate, url: '/content/logo.svg', tag: 'img' }, plan.sources[0], plan.sources[0].url).hostname, 'www.santander.com');
});

test('diagnostic receipt rejects string counts and malformed row containers', () => {
  const diagnostic = sanitizeLogoDiscovery({ headerCount: '1', candidateCount: '0', diagnosticRows: 'not-an-array' }, plan.sources[0].url);
  assert.deepEqual(diagnostic, { header_count: 0, candidate_count: 0, diagnostic_rows: [] });
});


test('diagnostic mode returns before the logo-only image pass and any screenshot call', () => {
  const source = fs.readFileSync(new URL('./s82-source-pack.mjs', here), 'utf8');
  const discovery = source.indexOf("stage = 'source-identity-discovery'");
  const diagnosticReturn = source.indexOf('if (diagnosticOnly) {', discovery);
  const logoPass = source.indexOf("stage = 'tagged-source-logo-pass'", diagnosticReturn);
  const screenshot = source.indexOf('await locator.screenshot', logoPass);
  assert.ok(discovery >= 0 && diagnosticReturn > discovery);
  assert.ok(logoPass > diagnosticReturn && screenshot > logoPass);
  assert.match(source, /if \(type === 'image'\) return permittedLogoURLs\.has\(url\.href\) \? route\.continue\(\) : route\.abort\(\)/);
  assert.ok(source.indexOf('permittedLogoURLs.add(logoURL.href)') > diagnosticReturn);
});


test('actual logo discovery admits visible positioned child in zero-height header but refuses hidden or zero-size marks', async () => {
  const originalDocument = globalThis.document, originalComputed = globalThis.getComputedStyle;
  const originalImage = globalThis.HTMLImageElement;
  class MockImage {
    tagName = 'IMG';
    width = 192; height = 36; display = 'block';
    getBoundingClientRect() { return {x:32,y:52,width:this.width,height:this.height}; }
    getAttribute(key) { return {alt:'Santander Bank',src:'/content/dam/santander-com/images/logo/santander-logo-negative.svg'}[key] || null; }
  }
  const image = new MockImage();
  const header = {tagName:'HEADER',display:'block',visibility:'visible',opacity:'1',
    getBoundingClientRect:()=>({x:0,y:0,width:1440,height:0}),querySelectorAll:()=>[image]};
  globalThis.HTMLImageElement = MockImage;
  globalThis.document = {querySelectorAll:()=>[header]};
  globalThis.getComputedStyle = el => ({display:el.display || 'block',visibility:el.visibility || 'visible',opacity:el.opacity || '1'});
  const page = {evaluate:async(fn,args)=>fn(args)};
  try {
    assert.equal((await findVisibleLogo(page,plan.sources[0])).candidateCount,1);
    header.display = 'none'; assert.equal((await findVisibleLogo(page,plan.sources[0])).candidateCount,0);
    header.display = 'block'; image.width = 0; assert.equal((await findVisibleLogo(page,plan.sources[0])).candidateCount,0);
    image.width = 192; image.display = 'none'; assert.equal((await findVisibleLogo(page,plan.sources[0])).candidateCount,0);
    image.display = 'block'; image.getAttribute = key => key === 'alt' ? 'Unrelated publisher' : null;
    assert.equal((await findVisibleLogo(page,plan.sources[0])).candidateCount,0);
  } finally {
    globalThis.document = originalDocument; globalThis.getComputedStyle = originalComputed;
    globalThis.HTMLImageElement = originalImage;
  }
});
