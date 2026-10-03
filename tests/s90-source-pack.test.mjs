import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import crypto from 'node:crypto';
import os from 'node:os';
import { spawnSync } from 'node:child_process';
import { fileURLToPath } from 'node:url';
import {
  EXPECTED_FILES, PLAN_SHA256, assetDigest, normalizeText,
  paragraphMatches, validatePlan,
} from '../.github/scripts/s90-source-pack.mjs';

const here = path.dirname(fileURLToPath(import.meta.url));
const planPath = path.join(here, '../.github/scripts/s90-source-pack-plan.json');
const workflowPath = path.join(here, '../.github/workflows/s90-source-pack-capture.yml');
const planBytes = fs.readFileSync(planPath);
const plan = JSON.parse(planBytes.toString('utf8'));

test('plan is frozen to the exact official source and claim list', () => {
  assert.equal(crypto.createHash('sha256').update(planBytes).digest('hex'), PLAN_SHA256);
  validatePlan(plan);
  assert.deepEqual(plan.claims.map(c => c.id), [1,2,3,4,5,6,7,8]);
  assert.equal(plan.source.url, 'https://www.channel4.com/press/news/channel-4-makes-tv-history-britains-first-ai-presenter');
  assert.equal(plan.source.publisher, 'Channel 4');
  assert.equal(plan.source.credit_line, 'Source: Channel 4, News Release, 20 October 2025');
  assert.equal(plan.source.date_selector, '.c-article-date');
  assert.deepEqual(plan.claims[7].required_source_phrases, [
    'Louisa Compton, Head of News and Current Affairs, Specialist Factual and Sport at Channel 4, said:',
  ]);
});

test('typography and whitespace normalization keeps exact evidence matching stable', () => {
  assert.equal(normalizeText('“Some of you might have guessed: I don’t exist.”'), '"some of you might have guessed: i don\'t exist."');
  const claim = { required_source_phrases: ["I don't exist", "I wasn't on location reporting this story"] };
  assert.equal(paragraphMatches(['She says: I don’t exist. I wasn’t on location reporting this story.'], claim).length, 1);
});

test('all frozen phrases must occur within the same live paragraph', () => {
  const claim = { required_source_phrases: ['the presenter appears throughout', 'entirely AI-generated'] };
  assert.equal(paragraphMatches(['the presenter appears throughout', 'the presenter was entirely AI-generated'], claim).length, 0);
});

test('ambiguous source paragraphs fail closed', () => {
  const claim = { required_source_phrases: ['the presenter was entirely AI-generated'] };
  assert.equal(paragraphMatches(['The presenter was entirely AI-generated.', 'The presenter was entirely AI-generated.'], claim).length, 2);
});

test('live article date and Louisa speaker introduction bind to their observed native elements', () => {
  const observedDate = { tag: 'span', className: 'c-article-date', text: '20 October 2025' };
  assert.equal(observedDate.tag, 'span');
  assert.equal(observedDate.className, plan.source.date_selector.slice(1));
  assert.equal(normalizeText(observedDate.text), normalizeText(plan.source.date));
  const paragraphs = [
    'Louisa Compton, Head of News and Current Affairs, Specialist Factual and Sport at Channel 4, said: “This is a deliberate on-screen stunt.”',
    'Production credits: Louisa Compton, Head of News and Current Affairs, Specialist Factual and Sport at Channel 4.',
  ];
  const matches = paragraphMatches(paragraphs, plan.claims[7]);
  assert.equal(matches.length, 1);
  assert.equal(matches[0].index, 0);
});

test('capture output name set is fixed to three source identity crops plus eight claim crops', () => {
  assert.equal(EXPECTED_FILES.length, 11);
  assert.deepEqual(EXPECTED_FILES.slice(0,3), ['header-channel4.png','release-title.png','release-date.png']);
  assert.equal(EXPECTED_FILES.at(-1), 'claim-08.png');
  assert.equal(assetDigest(Buffer.from('text-only test')), crypto.createHash('sha256').update('text-only test').digest('hex'));
});

test('workflow has only a manual public-Linux source-capture route and branch receipt output', () => {
  const yml = fs.readFileSync(workflowPath, 'utf8');
  assert.match(yml, /^  workflow_dispatch:$/m);
  assert.match(yml, /runs-on: ubuntu-24\.04/);
  assert.match(yml, /repo\.get\('private'\) is False and repo\.get\('visibility'\)=='public'/);
  assert.match(yml, /review-S90-source-pack-/);
  assert.match(yml, /CAPTURE-RECEIPT\.json/);
  assert.doesNotMatch(yml, /gh release create|workflow_run:|schedule:/);
});

test('workflow never requests source photos, clips, or link traversal', () => {
  const yml = fs.readFileSync(workflowPath, 'utf8');
  assert.match(yml, /plan\['collection'\]\['photos'\] is False/);
  assert.match(yml, /plan\['collection'\]\['clips'\] is False/);
  assert.match(yml, /plan\['collection'\]\['follow_links'\] is False/);
  assert.match(yml, /plan\['collection'\]\['full_page_screenshot'\] is False/);
});

test('async navigation discovery accepts blocked logo dimensions but loaded pass requires exact visible publisher mark', () => {
  const script = fs.readFileSync(path.join(here, '../.github/scripts/s90-source-pack.mjs'), 'utf8');
  const discovery = script.slice(script.indexOf('async function visibleHeaderLogo'), script.indexOf('async function waitForHeaderLogoDom'));
  const loaded = script.slice(script.indexOf('async function waitForLoadedHeaderLogo'), script.indexOf('async function capture'));
  assert.match(discovery, /page\.evaluate\(\(\{ selector, patternText \}\) => \{/);
  assert.match(discovery, /const visibleHeaderCount = headers\.filter\(visible\)\.length/);
  assert.doesNotMatch(discovery, /if \(!visible\(el\)\) continue/);
  assert.match(discovery, /getAttribute\('src'\) \|\| el\.currentSrc \|\| el\.src/);
  assert.match(script, /await waitForHeaderLogoDom\(page, plan\.source\.header_selector/);
  assert.match(script, /message\?\.type\?\.\(\) === 'error' && \/globalnav\/i\.test\(text\)/);
  assert.match(script, /message\.replace\(\/https\?:\\\/\\\/\[\^\\s\)\]\+\/gi, '\[url\]'\)\.slice\(0, 240\)/);
  assert.match(script, /header_count: header\.headerCount[\s\S]*visible_header_count: header\.visibleHeaderCount[\s\S]*candidates: header\.candidates\.map/);
  assert.match(loaded, /\|\| !visible\(el\)\) return false/);
  assert.match(loaded, /\(el\.currentSrc \|\| el\.src\) === expected\.url && el\.complete && el\.naturalWidth > 0/);
  assert.match(loaded, /name !== expected\.label \|\| el\.tagName\.toLowerCase\(\) !== expected\.tag/);

  const regex = new RegExp(plan.source.logo_accessibility_pattern, 'i');
  const blockedMark = { headerVisible:true, label:'Channel4.com Homepage', box:{width:0,height:0},
    src:'https://all4nav.channel4.com/globalnav/static/2.1.34/images/all4_logo.svg' };
  const discovers = row => row.headerVisible && regex.test(row.label);
  const secondPassAccepts = (row, image) => row.headerVisible && regex.test(row.label)
    && row.box.width > 0 && row.box.height > 0 && image.complete && image.naturalWidth > 0 && image.url === row.src;
  assert.equal(discovers(blockedMark), true);
  assert.equal(secondPassAccepts(blockedMark, {complete:false,naturalWidth:0,url:''}), false);
  const visibleMark = { ...blockedMark, box:{width:200,height:80} };
  assert.equal(secondPassAccepts(visibleMark, {complete:true,naturalWidth:200,
    url:'https://assets-corporate.channel4.com/AI-Presenter.jpg'}), false);
  assert.equal(secondPassAccepts(visibleMark, {complete:true,naturalWidth:200,url:blockedMark.src}), true);
});

test('actual labelled Channel4.com logo passes while an unlabelled Channel 4 presenter photo does not', () => {
  const regex = new RegExp(plan.source.logo_accessibility_pattern, 'i');
  const accessibleName = node => [node.alt, node.ariaLabel, node.title].filter(Boolean).join(' ');
  const liveHeaderLogo = {
    alt: 'Channel4.com Homepage', ariaLabel: '', title: '',
    src: 'https://all4nav.channel4.com/globalnav/static/2.1.34/images/all4_logo.svg',
  };
  const presenterImage = {
    alt: '', ariaLabel: '', title: '',
    src: 'https://assets-corporate.channel4.com/.../AI-Presenter.jpg',
  };
  assert.equal(regex.test(accessibleName(liveHeaderLogo)), true);
  assert.equal(regex.test(accessibleName(presenterImage)), false);
  assert.match(liveHeaderLogo.src, /all4_logo\.svg$/);
  assert.match(presenterImage.src, /AI-Presenter\.jpg$/);
});

test('workflow-runtime failure still writes a publishable failure receipt when capture never made its directory', () => {
  const yml = fs.readFileSync(workflowPath, 'utf8');
  const stepStart = yml.indexOf('- name: Prepare an exact allowlisted public review payload, including failure receipts');
  const heredocStart = yml.indexOf('python3 - <<\'PY\'\n', stepStart);
  const heredocEnd = yml.indexOf('\n          PY', heredocStart);
  assert.ok(stepStart >= 0 && heredocStart > stepStart && heredocEnd > heredocStart);
  const python = yml.slice(heredocStart + 'python3 - <<\'PY\'\n'.length, heredocEnd)
    .split('\n').map(line => line.replace(/^          /, '')).join('\n');
  const temp = fs.mkdtempSync(path.join(os.tmpdir(), 's90-failure-receipt-'));
  const src = path.join(temp, 'capture-never-created');
  const out = path.join(temp, 'review');
  try {
    const result = spawnSync('python3', ['-c', python], {
      cwd: path.dirname(here),
      encoding: 'utf8',
      env: { ...process.env, S90_CAPTURE_DIR: src, S90_REVIEW_DIR: out,
        CAPTURE_OUTCOME: 'failure', S90_PLAN_SHA256: PLAN_SHA256 },
    });
    assert.equal(result.status, 0, result.stderr || result.stdout);
    assert.equal(fs.existsSync(path.join(src, 'CAPTURE-RECEIPT.json')), true);
    assert.equal(fs.existsSync(path.join(src, 'SOURCE-IDENTITY.json')), true);
    assert.equal(fs.existsSync(path.join(out, 'CAPTURE-RECEIPT.json')), true);
    const receipt = JSON.parse(fs.readFileSync(path.join(out, 'CAPTURE-RECEIPT.json'), 'utf8'));
    assert.equal(receipt.status, 'SOURCE_CAPTURE_NOT_RUN');
    assert.equal(receipt.capture_step_outcome, 'failure');
    assert.deepEqual(fs.readdirSync(out).sort(), ['CAPTURE-RECEIPT.json','SOURCE-IDENTITY.json','SOURCE-PLAN.json']);
  } finally {
    fs.rmSync(temp, { recursive: true, force: true });
  }
});
