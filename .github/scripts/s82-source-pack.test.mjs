import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import { canonicalURL, taggedURL, validatePlan } from './s82-source-pack.mjs';

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
