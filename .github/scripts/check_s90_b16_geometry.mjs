#!/usr/bin/env node
// Hosted-Linux-only browser geometry guard for the S90 B16 safety qualifier.
// It measures the rendered DOM; it does not capture, decode, or inspect image files.

import { createHash } from 'node:crypto';
import { readFile } from 'node:fs/promises';
import path from 'node:path';
import { pathToFileURL } from 'node:url';

export const TIMES = Object.freeze([52.767, 58.027]);
export const MIN_CLEARANCE_PX = 4;
export const ORIGINAL_SCENES_SHA256 = 'a77a514b9de9c4e45941758615ebb7512c3630b95c9d5483742e8963a403eba9';
export const CANDIDATE_SCENES_SHA256 = '2e92ff94e6764379e941a2f924e21974c69dc7b8064013a6c3d0f9a8534269f7';

const EXPECTED_TEXT = Object.freeze({
  cta: 'FOLLOW FOR ONE REAL AI STORY A DAY, AND WHAT IT MEANS FOR YOUR BUSINESS',
  pending: 'CHANGE REMAINS PENDING UNTIL CONFIRMED',
  link: 'agmm.co.uk/ai-constraint-audit',
});

function bad(message) { throw new Error(`S90 B16 geometry refusal: ${message}`); }
function finiteRect(rect, label) {
  if (!rect || !['x', 'y', 'width', 'height'].every(k => Number.isFinite(rect[k])) || rect.width <= 0 || rect.height <= 0) {
    bad(`${label} rectangle missing or non-finite`);
  }
  return { left: rect.x, top: rect.y, right: rect.x + rect.width, bottom: rect.y + rect.height, width: rect.width, height: rect.height };
}
function overlaps(a, b) {
  return a.left < b.right && a.right > b.left && a.top < b.bottom && a.bottom > b.top;
}
function clears(a, b, gap = MIN_CLEARANCE_PX) {
  return a.right + gap <= b.left || b.right + gap <= a.left ||
    a.bottom + gap <= b.top || b.bottom + gap <= a.top;
}
function inside(inner, outer, inset = 0) {
  return inner.left >= outer.left + inset && inner.top >= outer.top + inset &&
    inner.right <= outer.right - inset && inner.bottom <= outer.bottom - inset;
}
function normalized(text) { return String(text ?? '').replace(/\s+/g, ' ').trim(); }
function listRects(value, label) {
  if (!Array.isArray(value) || value.length === 0) bad(`${label} has no measured Range.getClientRects() fragments`);
  return value.map((rect, i) => finiteRect(rect, `${label}[${i}]`));
}

export function observationFailures(row) {
  const failures = [];
  if (!row || row.schema !== 's90-b16-dom-geometry-v1') bad('unknown or missing response schema');
  if (!TIMES.includes(row.time)) failures.push('unexpected-time');
  if (row.activeBeat !== 'B16') failures.push('B16-not-active');
  if (row.pageErrors !== 0) failures.push('browser-page-error');
  if (row.fonts?.ready !== true || row.fonts?.archivo42 !== true || row.fonts?.archivo78 !== true) failures.push('required-font-not-loaded');
  if (row.viewport?.width !== 1080 || row.viewport?.height !== 1920) failures.push('wrong-viewport');
  for (const name of ['cta', 'pending', 'link', 'caption']) {
    if (row.selectorCounts?.[name] !== 1) failures.push(`selector-count-${name}`);
  }
  if (normalized(row.text?.cta) !== EXPECTED_TEXT.cta) failures.push('cta-text-mismatch');
  if (normalized(row.text?.pending) !== EXPECTED_TEXT.pending) failures.push('pending-text-mismatch');
  if (normalized(row.text?.link) !== EXPECTED_TEXT.link) failures.push('link-text-mismatch');

  const ctaText = listRects(row.textRects?.cta, 'CTA text');
  const pendingText = listRects(row.textRects?.pending, 'pending qualifier text');
  const linkText = listRects(row.textRects?.link, 'link text');
  const link = finiteRect(row.linkBorderBox, 'link border-box');
  const caption = finiteRect(row.captionBand, 'native caption band');
  const composition = finiteRect(row.compositionBox, 'composition root');
  const viewport = { left: 0, top: 0, right: 1080, bottom: 1920 };

  if (composition.left !== 0 || composition.top !== 0 || composition.width !== 1080 || composition.height !== 1920) failures.push('wrong-composition-box');
  if (![...ctaText, ...pendingText, ...linkText, link, caption].every(rect => inside(rect, viewport))) failures.push('geometry-outside-viewport');
  if (!linkText.every(rect => inside(rect, link, 4))) failures.push('link-text-outside-border-box');
  if (pendingText.some(rect => overlaps(rect, link) || !clears(rect, link))) failures.push('pending-link-overlap');
  if (pendingText.some(rect => overlaps(rect, caption) || !clears(rect, caption))) failures.push('pending-caption-overlap');
  if (ctaText.some(rect => overlaps(rect, caption) || !clears(rect, caption))) failures.push('cta-caption-overlap');
  if (overlaps(link, caption) || !clears(link, caption)) failures.push('link-caption-overlap');

  return [...new Set(failures)];
}

export function validatePair(pair) {
  if (!pair || pair.schema !== 's90-b16-dom-geometry-pair-v1') bad('pair response schema missing');
  for (const key of ['original', 'candidate']) {
    if (!Array.isArray(pair[key]) || pair[key].length !== TIMES.length) bad(`${key} must contain both exact time observations`);
    if (pair[key].some((row, index) => row.time !== TIMES[index])) bad(`${key} observations are missing, duplicated, or out of order`);
  }

  const originalIssues = pair.original.map(observationFailures);
  for (let i = 0; i < originalIssues.length; i++) {
    if (!originalIssues[i].includes('pending-link-overlap')) bad(`original at ${TIMES[i]}s did not reproduce the known qualifier/link collision`);
    if (originalIssues[i].some(issue => issue !== 'pending-link-overlap')) bad(`original at ${TIMES[i]}s has unrelated geometry/selector failures: ${originalIssues[i].join(', ')}`);
  }
  const candidateIssues = pair.candidate.map(observationFailures);
  for (let i = 0; i < candidateIssues.length; i++) {
    if (candidateIssues[i].length) bad(`candidate at ${TIMES[i]}s fails measured geometry: ${candidateIssues[i].join(', ')}`);
  }
  return {
    status: 'DOM_GEOMETRY_PASS',
    times: TIMES,
    baseline: 'both hosted DOM observations reproduce only the known pending-qualifier/link-borderbox overlap',
    candidate: 'both hosted DOM observations clear every text fragment, link border-box, and measured native caption band by at least 4px',
    disclaimer: 'geometry evidence only; no visual/editorial/voice/AV/still/release approval',
  };
}

async function measurePageScript(requestedTime) {
    const norm = value => String(value || '').replace(/\s+/g, ' ').trim();
    const rectJSON = rect => ({ x: rect.x, y: rect.y, width: rect.width, height: rect.height });
    const rangeRects = element => {
      const result = [];
      const walker = document.createTreeWalker(element, NodeFilter.SHOW_TEXT);
      while (walker.nextNode()) {
        if (!walker.currentNode.nodeValue.trim()) continue;
        const range = document.createRange();
        range.selectNodeContents(walker.currentNode);
        for (const rect of range.getClientRects()) result.push(rectJSON(rect));
      }
      return result;
    };
    const one = (selector, name) => {
      const rows = document.querySelectorAll(selector);
      if (rows.length !== 1) throw new Error(`${name} selector count ${rows.length}, expected exactly one`);
      const element = rows[0];
      const style = getComputedStyle(element);
      if (style.display === 'none' || style.visibility === 'hidden' || Number(style.opacity) === 0) throw new Error(`${name} is not painted at ${requestedTime}s`);
      return element;
    };
    if (!window.AGK_SPEC || window.AGK_SPEC.id !== 'S90-SILENT-DEVELOPMENT') throw new Error('native S90 spec missing');
    const beats = window.AGK_SPEC.beats.filter(beat => beat.id === 'B16' && beat.from <= requestedTime && requestedTime < beat.to);
    if (beats.length !== 1) throw new Error(`B16 is not uniquely active at ${requestedTime}s`);
    const timeline = window.__timelines?.[window.AGK_SPEC.id];
    if (!timeline || typeof timeline.time !== 'function') throw new Error('native AGK timeline unavailable');
    timeline.pause();
    window.__storyTL?.pause();
    timeline.time(requestedTime, false);
    await new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve)));

    // AGK creates all 16 scene layers up front. Scope repeated scene classes to the
    // native AG.scene id for the active B16 layer before requiring one text target.
    const b16Root = '#root #S90-SILENT-DEVELOPMENT-B16';
    one(b16Root, 'B16 scene root');
    const cta = one(`${b16Root} .s90-cta`, 'CTA');
    const pending = one(`${b16Root} .s90-pending`, 'pending qualifier');
    const link = one(`${b16Root} .s90-link`, 'audit URL');
    const caption = one('#root .ag2-cap', 'native caption band');
    const usedFaces = Array.from(document.fonts).filter(face => face.family.replace(/["']/g, '') === 'AG Archivo');
    const fontStatus = {
      ready: document.fonts.status === 'loaded',
      archivo42: document.fonts.check('900 42px "AG Archivo"', 'CONFIRMED') && usedFaces.some(face => face.status === 'loaded'),
      archivo78: document.fonts.check('900 78px "AG Archivo"', 'FOLLOW') && usedFaces.some(face => face.status === 'loaded'),
      faces: usedFaces.map(face => ({ family: face.family, weight: face.weight, status: face.status })),
    };
    const visibleText = element => element.innerText;
    const root = one('#root', 'composition root');
    return {
      schema: 's90-b16-dom-geometry-v1',
      time: requestedTime,
      activeBeat: beats[0].id,
      pageErrors: 0,
      viewport: { width: innerWidth, height: innerHeight },
      fonts: fontStatus,
      selectorCounts: { cta: 1, pending: 1, link: 1, caption: 1 },
      text: { cta: norm(visibleText(cta)), pending: norm(visibleText(pending)), link: norm(visibleText(link)) },
      textRects: { cta: rangeRects(cta), pending: rangeRects(pending), link: rangeRects(link) },
      linkBorderBox: rectJSON(link.getBoundingClientRect()),
      captionBand: rectJSON(caption.getBoundingClientRect()),
      compositionBox: rectJSON(root.getBoundingClientRect()),
    };
}

async function observePage(browser, rootPath) {
  const page = await browser.newPage({ viewport: { width: 1080, height: 1920 }, deviceScaleFactor: 1 });
  const pageErrors = [];
  page.on('pageerror', error => pageErrors.push(String(error?.name || 'pageerror')));
  const url = pathToFileURL(path.resolve(rootPath, 'index.html')).href;
  await page.goto(url, { waitUntil: 'load', timeout: 30000 });
  await page.evaluate(async () => {
    await Promise.all([
      document.fonts.load('900 42px "AG Archivo"', 'CONFIRMED'),
      document.fonts.load('900 78px "AG Archivo"', 'FOLLOW'),
    ]);
    await document.fonts.ready;
  });
  return { page, pageErrors, measure: async time => {
    const row = await page.evaluate(measurePageScript, time);
    row.pageErrors = pageErrors.length;
    return row;
  }};
}

async function main() {
  if (process.platform !== 'linux' || process.env.GITHUB_ACTIONS !== 'true' || process.env.S90_HOSTED_PREVIEW !== '1') {
    bad('browser composition is allowed only in the explicitly enabled hosted Linux workflow');
  }
  const args = Object.fromEntries(process.argv.slice(2).map(arg => {
    const split = arg.replace(/^--/, '').split('=', 2);
    return [split[0], split[1]];
  }));
  if (!args['original-root'] || !args['candidate-root']) bad('both --original-root and --candidate-root are required');
  const [originalBytes, candidateBytes] = await Promise.all([
    readFile(path.join(args['original-root'], 'scenes.js')),
    readFile(path.join(args['candidate-root'], 'scenes.js')),
  ]);
  const hash = data => createHash('sha256').update(data).digest('hex');
  if (hash(originalBytes) !== ORIGINAL_SCENES_SHA256) bad('original scene source is not the authenticated a77a514b baseline');
  if (hash(candidateBytes) !== CANDIDATE_SCENES_SHA256) bad('candidate scene source does not match the exact reviewed S90 development bytes');
  const playwrightEntry = process.env.S90_PLAYWRIGHT_ENTRY;
  if (!playwrightEntry) bad('S90_PLAYWRIGHT_ENTRY is required; run only in the hosted Linux workflow');
  const { chromium } = await import(pathToFileURL(path.resolve(playwrightEntry)).href);
  const browser = await chromium.launch({ channel: 'chrome', headless: true, args: ['--allow-file-access-from-files'] });
  try {
    const original = await observePage(browser, args['original-root']);
    const candidate = await observePage(browser, args['candidate-root']);
    const pair = { schema: 's90-b16-dom-geometry-pair-v1', original: [], candidate: [] };
    for (const time of TIMES) {
      pair.original.push(await original.measure(time));
      pair.candidate.push(await candidate.measure(time));
    }
    const evidence = { browserVersion: browser.version(), sourceHashes: { original: hash(originalBytes), candidate: hash(candidateBytes) }, observations: pair };
    // Preserve the real measured rectangles in the workflow log even when the
    // pair fails its expected-baseline or candidate-clearance assertion.
    console.log(JSON.stringify({ status: 'DOM_MEASUREMENTS_CAPTURED_BEFORE_VALIDATION', ...evidence }, null, 2));
    const result = validatePair(pair);
    console.log(JSON.stringify({ ...result, ...evidence }, null, 2));
  } finally {
    await browser.close();
  }
}

if (import.meta.url === pathToFileURL(process.argv[1] || '').href) {
  main().catch(error => { console.error(error.message); process.exitCode = 1; });
}
