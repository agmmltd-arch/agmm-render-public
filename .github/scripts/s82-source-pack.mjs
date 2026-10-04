import crypto from 'node:crypto';
import fs from 'node:fs/promises';
import os from 'node:os';
import path from 'node:path';
import { execFileSync } from 'node:child_process';

export const REPOSITORY = 'agmmltd-arch/agmm-render-public';
export const PLAN_PATH = '.github/scripts/s82-source-pack-plan.json';
export const PLAN_SHA256 = '0fe325104557169140b7b7ca1643acbbcbac92c2c57a8f6075845b24055ca661';
export const PARENT_SHA = 'ab8011d077cd219319a04670c7e89f367d45934f';
export const MAX_FILE_BYTES = 2_000_000;
export const MAX_TOTAL_BYTES = 16_000_000;
export const MAX_LOGO_DIAGNOSTIC_ROWS = 20;
export const QA = { utm_source: 'qa', utm_campaign: 'qa_release_audit' };

export const normalizeText = value => String(value ?? '')
  .replace(/[\u00a0\u2009\u202f]/g, ' ').replace(/[‘’]/g, "'")
  .replace(/[“”]/g, '"').replace(/[–—]/g, '-').replace(/\s+/g, ' ')
  .trim().toLocaleLowerCase('en-GB');

export function taggedURL(raw) {
  const url = new URL(raw);
  url.searchParams.set('utm_source', QA.utm_source);
  url.searchParams.set('utm_campaign', QA.utm_campaign);
  return url.href;
}

export function canonicalURL(raw) {
  const url = new URL(raw);
  url.hash = '';
  url.searchParams.delete('utm_source');
  url.searchParams.delete('utm_campaign');
  return url.href;
}

export function validatePlan(plan) {
  if (plan?.schema !== 'agmm-s82-source-plan-v3' || plan.story_id !== 'S82') {
    throw new Error('unexpected S82 source plan schema/story id');
  }
  if (PLAN_SHA256 === 'TO_BE_PINNED') throw new Error('S82 plan pin has not been frozen');
  if (plan.collection_policy.photos !== false || plan.collection_policy.clips !== false
      || plan.collection_policy.audio_or_video_download !== false
      || plan.collection_policy.follow_links !== false
      || plan.collection_policy.full_page_screenshots !== false) {
    throw new Error('source-only capture policy was weakened');
  }
  if (plan.sources.length !== 3 || plan.script_claim_coverage.length !== 6) {
    throw new Error('all three source pages and six script claim groups are required');
  }
  const expected = new Set(plan.collection_policy.exact_capture_files);
  const actual = new Set();
  for (const source of plan.sources) {
    const url = new URL(source.url);
    if (url.protocol !== 'https:' || !source.allowed_hosts?.includes(url.hostname)) {
      throw new Error(`source ${source.key} has an unpinned or off-list origin`);
    }
    if (!source.title || !source.header_logo_accessible_name_pattern
        || !(source.byline_date_selector || (source.byline_selector && source.date_selector))) {
      throw new Error(`source ${source.key} lacks title/header/byline-date bindings`);
    }
    for (const file of source.files) {
      if (actual.has(file.file)) throw new Error(`duplicate source asset name: ${file.file}`);
      actual.add(file.file);
    }
    for (const [id, text] of Object.entries(source.claim_paragraphs ?? {})) {
      if (!text || !source.required_visible_text_by_capture?.[id]?.length) {
        throw new Error(`claim crop ${source.key}.${id} lacks exact source-text binding`);
      }
      if (!source.files.some(file => file.capture_id === id)) {
        throw new Error(`claim crop ${source.key}.${id} is not in the capture manifest`);
      }
    }
    for (const id of Object.keys(source.required_visible_text_by_capture ?? {})) {
      if (!(id in (source.claim_paragraphs ?? {}))) {
        throw new Error(`required claim ${source.key}.${id} has no exact paragraph binding`);
      }
    }
  }
  if (actual.size !== expected.size || [...actual].some(name => !expected.has(name))) {
    throw new Error('capture file map differs from the frozen exact output allowlist');
  }
  for (const claim of plan.script_claim_coverage) {
    if (!claim.spoken_claim || !claim.status || !Array.isArray(claim.evidence)) {
      throw new Error('spoken-claim mapping lacks a status or evidence list');
    }
    for (const ref of claim.evidence) {
      const [sourceKey, captureId, ...extra] = String(ref).split('.');
      const source = plan.sources.find(row => row.key === sourceKey);
      if (!source || !captureId || extra.length || !source.files.some(row => row.capture_id === captureId)) {
        throw new Error(`spoken-claim evidence reference is not a frozen crop: ${ref}`);
      }
    }
  }
  return true;
}

function hostedGuard() {
  let head = '', parent = '';
  try {
    head = execFileSync('git', ['rev-parse', 'HEAD'], { encoding: 'utf8' }).trim();
    parent = execFileSync('git', ['rev-parse', 'HEAD^'], { encoding: 'utf8' }).trim();
  } catch { throw new Error('refusing source-page IO: cannot verify workflow commit ancestry'); }
  if (os.platform() !== 'linux' || process.env.GITHUB_ACTIONS !== 'true'
      || process.env.GITHUB_REPOSITORY !== REPOSITORY
      || process.env.GITHUB_REF !== 'refs/heads/main'
      || process.env.GITHUB_SHA !== head || parent !== PARENT_SHA) {
    throw new Error('refusing source-page IO: exact public Ubuntu workflow commit and guarded parent required');
  }
}

function visible(el) {
  const r = el.getBoundingClientRect(); const s = getComputedStyle(el);
  return r.width > 0 && r.height > 0 && s.display !== 'none' && s.visibility !== 'hidden'
    && Number(s.opacity || 1) > 0;
}

function diagnosticText(value, cap = 160) {
  return String(value ?? '').replace(/[\u0000-\u001f\u007f]/g, ' ').replace(/\s+/g, ' ').trim().slice(0, cap);
}

function diagnosticRect(value) {
  if (!value || typeof value !== 'object') return null;
  const out = {};
  for (const key of ['x', 'y', 'width', 'height']) {
    const number = Number(value[key]);
    out[key] = Number.isFinite(number) ? Math.round(number * 100) / 100 : null;
  }
  return out;
}

export function sanitizeLogoDiscovery(value, baseURL) {
  const rows = Array.isArray(value?.diagnosticRows) ? value.diagnosticRows.slice(0, MAX_LOGO_DIAGNOSTIC_ROWS) : [];
  return {
    header_count: Number.isSafeInteger(value?.headerCount) && value.headerCount >= 0 ? value.headerCount : 0,
    candidate_count: Number.isSafeInteger(value?.candidateCount) && value.candidateCount >= 0 ? value.candidateCount : 0,
    diagnostic_rows: rows.map(row => {
      const safe = {
        kind: row?.kind === 'header' ? 'header' : 'descendant',
        header_index: Number.isSafeInteger(row?.headerIndex) && row.headerIndex >= 0 ? row.headerIndex : null,
        tag: diagnosticText(row?.tag, 24).toLowerCase(),
        rect: diagnosticRect(row?.rect),
        display: diagnosticText(row?.display, 24),
        visibility: diagnosticText(row?.visibility, 24),
        opacity: diagnosticText(row?.opacity, 24),
      };
      if (row?.kind !== 'header') {
        safe.accessible_label = diagnosticText(row?.label, 160);
        try {
          const url = new URL(String(row?.url || ''), baseURL);
          safe.url_protocol = url.protocol;
          safe.url_host = diagnosticText(url.host, 160);
          safe.url_path = diagnosticText(url.pathname, 240);
        } catch {
          safe.url_protocol = 'invalid'; safe.url_host = ''; safe.url_path = '';
        }
      }
      return safe;
    }),
  };
}

export function validateLogoCandidate(candidate, source, baseURL) {
  const url = new URL(String(candidate?.url || ''), baseURL);
  if (candidate?.tag !== 'img' || url.protocol !== 'https:' || !source?.allowed_hosts?.includes(url.hostname)) {
    throw new Error('native publisher mark is not a same-source HTTPS image');
  }
  return url;
}

async function findVisibleLogo(page, source) {
  return page.evaluate(({ selector, patternText }) => {
    const re = new RegExp(patternText, 'i');
    const shown = el => {
      const r = el.getBoundingClientRect(), s = getComputedStyle(el);
      return r.width > 0 && r.height > 0 && s.display !== 'none' && s.visibility !== 'hidden'
        && Number(s.opacity || 1) > 0;
    };
    const rect = el => { const r = el.getBoundingClientRect(); return { x:r.x, y:r.y, width:r.width, height:r.height }; };
    const headers = [...document.querySelectorAll(selector)];
    const candidates = [];
    let candidateCount = 0;
    const diagnosticRows = [];
    for (const [headerIndex, header] of headers.entries()) {
      const headerStyle = getComputedStyle(header);
      if (diagnosticRows.length < 20) diagnosticRows.push({ kind:'header', headerIndex,
        tag:header.tagName.toLowerCase(), rect:rect(header), display:headerStyle.display,
        visibility:headerStyle.visibility, opacity:headerStyle.opacity });
      for (const el of header.querySelectorAll('img,svg,[role="img"]')) {
        if (diagnosticRows.length >= 20) break;
        const style=getComputedStyle(el);
        const label=[el.getAttribute('alt'),el.getAttribute('aria-label'),el.getAttribute('title')]
          .filter(Boolean).join(' ').trim();
        const rawURL=el instanceof HTMLImageElement ? (el.getAttribute('src') || el.currentSrc || el.src) : '';
        diagnosticRows.push({ kind:'descendant', headerIndex, tag:el.tagName.toLowerCase(), rect:rect(el),
          display:style.display, visibility:style.visibility, opacity:style.opacity, label, url:rawURL });
      }
      if (!shown(header)) continue;
      for (const el of header.querySelectorAll('img,svg,[role="img"]')) {
        const style = getComputedStyle(el);
        if (style.display === 'none' || style.visibility === 'hidden' || Number(style.opacity || 1) <= 0) continue;
        const label = [el.getAttribute('alt'), el.getAttribute('aria-label'), el.getAttribute('title')]
          .filter(Boolean).join(' ').trim();
        if (!label || !re.test(label)) continue;
        candidateCount += 1;
        if (candidates.length < 20) candidates.push({ headerIndex, label, tag: el.tagName.toLowerCase(),
          url: el instanceof HTMLImageElement ? (el.getAttribute('src') || el.currentSrc || el.src) : '' });
      }
    }
    return { headerCount: headers.length, candidateCount, candidates, diagnosticRows };
  }, { selector: source.header_selector || 'header', patternText: source.header_logo_accessible_name_pattern });
}

async function captureSource(plan, source, outDir) {
  const { chromium } = await import('playwright');
  const browser = await chromium.launch({ headless: true, args: ['--no-sandbox'] });
  const allowedHosts = new Set(source.allowed_hosts);
  const qaURL = taggedURL(source.url);
  let page;
  let response = null;
  let stage = 'browser-context';
  const identity = { key: source.key, source_url: source.url, tagged_url: qaURL,
    publisher: source.publisher, title_expected: source.title, date_expected: source.date,
    byline_expected: source.exact_byline, http_status: null, final_url: null,
    title_verified: false, byline_date_verified: false, logo_verified: false,
    photos_or_clips_requested: false, source_review: 'NOT_REVIEWED' };
  const outputRows = [];
  try {
    const context = await browser.newContext({ viewport: { width: 1440, height: 1100 },
      deviceScaleFactor: 2, acceptDownloads: false, serviceWorkers: 'block', reducedMotion: 'reduce' });
    page = await context.newPage();
    const permittedLogoURLs = new Set();
    await page.route('**/*', async route => {
      const req = route.request(), url = new URL(req.url()), type = req.resourceType();
      if (['audio', 'video', 'media', 'websocket', 'eventsource', 'fetch', 'xhr'].includes(type)) return route.abort();
      if (!allowedHosts.has(url.hostname) || url.protocol !== 'https:') return route.abort();
      if (type === 'image') return permittedLogoURLs.has(url.href) ? route.continue() : route.abort();
      if (type === 'document' && canonicalURL(url.href) !== canonicalURL(qaURL)) return route.abort();
      return route.continue();
    });

    stage = 'tagged-source-fetch';
    const first = await page.goto(qaURL, { waitUntil: 'domcontentloaded', timeout: 90000 });
    if (!first || first.status() < 200 || first.status() >= 300) throw new Error('tagged source request was not HTTP 2xx');
    response = first.status(); identity.http_status = response; identity.final_url = page.url();
    if (canonicalURL(page.url()) !== canonicalURL(source.url)) throw new Error('source redirected away from exact pinned path');

    stage = 'source-identity-discovery';
    const logo = await findVisibleLogo(page, source);
    const diagnosticOnly = process.env.S82_DIAGNOSTIC_ONLY === 'true';
    if (logo.candidateCount !== 1) {
      identity.logo_discovery = sanitizeLogoDiscovery(logo, source.url);
      throw new Error(`expected one accessible logo in visible publisher header; found ${logo.candidateCount}`);
    }
    const candidate = logo.candidates[0];
    if (diagnosticOnly) {
      identity.logo_discovery = sanitizeLogoDiscovery(logo, source.url);
      identity.diagnostic_only = true;
      return { identity, assets: [] };
    }
    let logoURL;
    try { logoURL = validateLogoCandidate(candidate, source, qaURL); }
    catch (error) {
      identity.logo_discovery = sanitizeLogoDiscovery(logo, source.url);
      throw error;
    }
    permittedLogoURLs.add(logoURL.href);

    stage = 'tagged-source-logo-pass';
    const second = await page.goto(qaURL, { waitUntil: 'domcontentloaded', timeout: 90000 });
    if (!second || second.status() !== response || canonicalURL(page.url()) !== canonicalURL(source.url)) {
      throw new Error('source identity changed between blocked-image and logo-only passes');
    }
    const logoLoaded = await page.evaluate(({ selector, candidate, expectedURL }) => {
      const headers = [...document.querySelectorAll(selector)];
      const header = headers[candidate.headerIndex];
      if (!header) return false;
      const shown = el => { const r=el.getBoundingClientRect(),s=getComputedStyle(el); return r.width>0&&r.height>0&&s.display!=='none'&&s.visibility!=='hidden'&&Number(s.opacity||1)>0; };
      const matches = [...header.querySelectorAll('img')].filter(el => {
        const label=[el.getAttribute('alt'),el.getAttribute('aria-label'),el.getAttribute('title')].filter(Boolean).join(' ').trim();
        return label === candidate.label && (el.currentSrc || el.src) === expectedURL && el.complete && el.naturalWidth > 0 && shown(el);
      });
      return matches.length === 1;
    }, { selector: source.header_selector || 'header', candidate, expectedURL: logoURL.href });
    if (!logoLoaded) throw new Error('native logo did not load visibly from its exact allowlisted HTTPS URL');
    identity.logo_verified = true;
    identity.header_logo = { accessible_label: candidate.label, tag: candidate.tag, host: logoURL.hostname };

    stage = 'title-date-binding';
    const titleState = await page.locator(source.title_selector || 'h1').evaluateAll((els, expected) => {
      const norm=s=>String(s||'').replace(/[\u00a0\u2009\u202f]/g,' ').replace(/[‘’]/g,"'").replace(/[“”]/g,'"').replace(/[–—]/g,'-').replace(/\s+/g,' ').trim().toLowerCase();
      const shown=el=>{const r=el.getBoundingClientRect(),s=getComputedStyle(el);return r.width>0&&r.height>0&&s.display!=='none'&&s.visibility!=='hidden'&&Number(s.opacity||1)>0;};
      return els.map((el,index)=>({el,index})).filter(({el})=>shown(el)&&norm(el.innerText)===norm(expected)).map(({el,index})=>({index,text:el.innerText}));
    }, source.exact_title || source.title);
    if (titleState.length !== 1) throw new Error(`expected one exact visible article title; found ${titleState.length}`);
    const normalize = value => String(value ?? '').replace(/[\u00a0\u2009\u202f]/g,' ').replace(/[‘’]/g,"'")
      .replace(/[“”]/g,'"').replace(/[–—]/g,'-').replace(/\s+/g,' ').trim().toLocaleLowerCase('en-GB');
    const bindVisibleText = async (selector, required, label) => {
      const rows = await page.locator(selector).evaluateAll((els, text) => {
        const norm=s=>String(s||'').replace(/[\u00a0\u2009\u202f]/g,' ').replace(/[‘’]/g,"'").replace(/[“”]/g,'"').replace(/[–—]/g,'-').replace(/\s+/g,' ').trim().toLowerCase();
        const shown=el=>{const r=el.getBoundingClientRect(),s=getComputedStyle(el);return r.width>0&&r.height>0&&s.display!=='none'&&s.visibility!=='hidden'&&Number(s.opacity||1)>0;};
        return els.map((el,index)=>({el,index})).filter(({el})=>shown(el)&&norm(el.innerText).includes(norm(text)))
          .map(({el,index})=>({index,text:el.innerText}));
      }, required);
      if (rows.length !== 1) throw new Error(`expected one visible ${label} binding; found ${rows.length}`);
      return rows[0];
    };
    const bylineState = source.byline_date_selector
      ? await bindVisibleText(source.byline_date_selector,
          `${source.exact_metadata_text || source.exact_byline} ${source.exact_date_text || source.required_date_fragment || source.date}`,
          'byline/date block')
      : await bindVisibleText(source.byline_selector, source.exact_byline, 'byline');
    const dateState = source.byline_date_selector ? bylineState
      : await bindVisibleText(source.date_selector, source.required_date_fragment || source.exact_date_text || source.date, 'date');
    identity.title_verified = true; identity.byline_date_verified = true;

    const titleLocator = page.locator(source.title_selector || 'h1').nth(titleState[0].index);

    stage = 'claim-text-binding';
    const paras = await page.locator(source.paragraph_selector || 'article p, main p').evaluateAll(els => {
      const shown=el=>{const r=el.getBoundingClientRect(),s=getComputedStyle(el);return r.width>0&&r.height>0&&s.display!=='none'&&s.visibility!=='hidden';};
      return els.map((el,index)=>({el,index})).filter(({el})=>shown(el))
      .map(({el,index})=>({index,text:el.innerText||''})).filter(x=>x.text.trim());
    });
    const claimMatches = {};
    for (const [id, expectedText] of Object.entries(source.claim_paragraphs || {})) {
      const matches = paras.filter(p => normalize(p.text) === normalize(expectedText));
      if (matches.length !== 1) throw new Error(`${id}: expected one exact live paragraph, found ${matches.length}`);
      const required = source.required_visible_text_by_capture[id] || [];
      if (required.some(phrase => !normalize(matches[0].text).includes(normalize(phrase)))) throw new Error(`${id}: required phrase missing from exact paragraph`);
      claimMatches[id] = matches[0];
    }

    stage = 'native-crop-capture';
    const staged = path.join(outDir, source.key);
    await fs.mkdir(staged, { recursive: false });
    const headerLocator = page.locator(source.header_selector || 'header').nth(candidate.headerIndex);
    const bylineLocator = page.locator(source.byline_date_selector || source.byline_selector).nth(bylineState.index);
    const dateLocator = source.byline_date_selector ? bylineLocator
      : page.locator(source.date_selector).nth(dateState.index);
    const files = source.files;
    for (const row of files) {
      let locator;
      if (row.type === 'visible-native-publisher-header-mark') locator = headerLocator;
      else if (row.type === 'source-title') locator = titleLocator;
      else if (row.type === 'source-byline') locator = bylineLocator;
      else if (row.type === 'source-date' || row.type === 'source-byline-date') locator = dateLocator;
      else if (row.type === 'exact-source-claim') locator = page.locator(source.paragraph_selector || 'article p, main p').nth(claimMatches[row.capture_id].index);
      if (!locator) throw new Error(`no native DOM binding for capture ${row.capture_id}`);
      const target = path.join(staged, row.file);
      await locator.screenshot({ path: target, type: 'png', animations: 'disabled', timeout: 30000 });
      const bytes = await fs.readFile(target);
      if (bytes.length < 100 || bytes.length > MAX_FILE_BYTES || bytes.subarray(0,8).toString('hex') !== '89504e470d0a1a0a') {
        throw new Error(`capture is not a bounded native PNG: ${row.file}`);
      }
      outputRows.push({ file: row.file, capture_id: row.capture_id, type: row.type,
        publisher: source.publisher, source_url: source.url, source_title: source.title, source_date: source.date,
        sha256: crypto.createHash('sha256').update(bytes).digest('hex'), bytes: bytes.length,
        human_source_review: 'REQUIRED', editorial_status: 'NOT_REVIEWED', render_approval: 'NOT_GRANTED' });
    }
    return { identity, assets: outputRows };
  } catch (error) {
    identity.capture_stage = stage;
    identity.error = String(error?.message || error).slice(0, 500);
    throw Object.assign(error instanceof Error ? error : new Error(String(error)), { sourceIdentity: identity, stage });
  } finally {
    await browser.close();
  }
}

export async function runCapture(plan, outDir) {
  validatePlan(plan);
  hostedGuard();
  const diagnosticOnly = process.env.S82_DIAGNOSTIC_ONLY === 'true';
  const planBytes = await fs.readFile(PLAN_PATH);
  const planHash = crypto.createHash('sha256').update(planBytes).digest('hex');
  if (planHash !== PLAN_SHA256) throw new Error('frozen source plan hash changed');
  await fs.mkdir(outDir, { recursive: false });
  const receipt = { schema: 'agmm-s82-source-pack-receipt-v1', story_id: 'S82', status: 'CAPTURE_IN_PROGRESS',
    plan_sha256: planHash, plan_parent_sha: PARENT_SHA, assets_published: false,
    editorial_status: 'NOT_REVIEWED', render_approval: 'NOT_GRANTED', release_approval: 'NOT_GRANTED',
    diagnostic_only: diagnosticOnly, assets: [] };
  const identity = { schema: 'agmm-s82-source-identities-v1', story_id: 'S82', plan_sha256: planHash, sources: [] };
  try {
    const sourceRows = diagnosticOnly ? plan.sources.slice(0, 1) : plan.sources;
    for (const source of sourceRows) {
      try {
        const result = await captureSource(plan, source, outDir);
        identity.sources.push(result.identity); receipt.assets.push(...result.assets);
      } catch (error) {
        if (error.sourceIdentity) identity.sources.push(error.sourceIdentity);
        throw error;
      }
    }
    if (diagnosticOnly) {
      receipt.status = 'SOURCE_IDENTITY_DIAGNOSTIC_ONLY';
      receipt.asset_count = 0;
      receipt.total_bytes = 0;
    } else {
    const expected = [...plan.collection_policy.exact_capture_files].sort();
    const actual = receipt.assets.map(row => row.file).sort();
    if (JSON.stringify(actual) !== JSON.stringify(expected)) throw new Error('captured file set does not match frozen output allowlist');
    const total = receipt.assets.reduce((sum, row) => sum + row.bytes, 0);
    if (total > MAX_TOTAL_BYTES) throw new Error('source crop bundle exceeds byte cap');
    receipt.status = 'SOURCE_CROPS_CAPTURED_NEEDS_ROOT_EYES';
    receipt.asset_count = receipt.assets.length; receipt.total_bytes = total;
    receipt.claim_coverage = plan.script_claim_coverage;
    }
  } catch (error) {
    receipt.status = 'SOURCE_CAPTURE_FAILED'; receipt.failure_stage = error.stage || 'workflow';
    receipt.failure = String(error?.message || error).slice(0, 500);
    receipt.assets = [];
    for (const name of await fs.readdir(outDir)) {
      const target = path.join(outDir, name);
      const st = await fs.stat(target);
      if (st.isDirectory()) await fs.rm(target, { recursive: true, force: true }); else await fs.rm(target, { force: true });
    }
  }
  identity.status = receipt.status; identity.sources_count = identity.sources.length;
  if (receipt.status === 'SOURCE_CROPS_CAPTURED_NEEDS_ROOT_EYES') {
    const manifest = { schema: 'agmm-s82-source-pack-manifest-v1', story_id: 'S82',
      plan_sha256: planHash, source_identities: identity.sources.map(row => ({ key: row.key,
        source_url: row.source_url, publisher: row.publisher, title_expected: row.title_expected,
        date_expected: row.date_expected, http_status: row.http_status, final_url: row.final_url })),
      assets: receipt.assets, asset_count: receipt.asset_count, total_bytes: receipt.total_bytes,
      claim_coverage: plan.script_claim_coverage, source_review: 'NOT_REVIEWED',
      independent_source_approval: 'NOT_GRANTED', render_approval: 'NOT_GRANTED', release_approval: 'NOT_GRANTED' };
    await fs.writeFile(path.join(outDir, 'manifest.json'), JSON.stringify(manifest, null, 2) + '\n');
  }
  await fs.writeFile(path.join(outDir, 'SOURCE-IDENTITY.json'), JSON.stringify(identity, null, 2) + '\n');
  await fs.writeFile(path.join(outDir, 'CAPTURE-RECEIPT.json'), JSON.stringify(receipt, null, 2) + '\n');
  if (receipt.status !== 'SOURCE_CROPS_CAPTURED_NEEDS_ROOT_EYES' && receipt.status !== 'SOURCE_IDENTITY_DIAGNOSTIC_ONLY') {
    throw new Error(receipt.failure || 'capture failed');
  }
  return receipt;
}

if (import.meta.url === `file://${process.argv[1]}`) {
  try {
    const plan = JSON.parse(await fs.readFile(PLAN_PATH, 'utf8'));
    const receipt = await runCapture(plan, process.env.S82_CAPTURE_DIR);
    console.log(JSON.stringify({ status: receipt.status, asset_count: receipt.asset_count, total_bytes: receipt.total_bytes }));
  } catch (error) {
    console.error(`S82 source capture failed: ${String(error?.message || error).slice(0, 500)}`);
    process.exitCode = 1;
  }
}
