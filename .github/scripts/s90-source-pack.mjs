import crypto from 'node:crypto';
import fs from 'node:fs/promises';
import os from 'node:os';
import path from 'node:path';

export const REPOSITORY = 'agmmltd-arch/agmm-render-public';
export const SOURCE_PLAN_PATH = '.github/scripts/s90-source-pack-plan.json';
export const PLAN_SHA256 = 'da81ea62eeb36ddfab4b63b748894b567e2268c105d00e82d83638fed4c939d5';
export const EXPECTED_FILES = [
  'header-channel4.png', 'release-title.png', 'release-date.png',
  ...Array.from({ length: 8 }, (_, i) => `claim-${String(i + 1).padStart(2, '0')}.png`),
];
export const MAX_ASSET_BYTES = 6_000_000;
export const MAX_TOTAL_ASSET_BYTES = 24_000_000;

export function normalizeText(value) {
  return String(value ?? '')
    .replace(/[\u00a0\u2009\u202f]/g, ' ')
    .replace(/[‘’]/g, "'")
    .replace(/[“”]/g, '"')
    .replace(/[–—]/g, '-')
    .replace(/\s+/g, ' ')
    .trim()
    .toLocaleLowerCase('en-GB');
}

export function normalizeURL(value) {
  const url = new URL(value);
  url.hash = '';
  return url.href;
}

export function validatePlan(plan, expectedHash = PLAN_SHA256) {
  if (plan?.schema !== 'agmm-source-pack-plan-v1' || plan?.story_id !== 'S90') {
    throw new Error('unexpected S90 source-pack plan schema or story id');
  }
  if (expectedHash === 'TO_BE_PINNED_AFTER_PLAN_REVIEW') {
    throw new Error('source-plan SHA-256 has not been pinned');
  }
  if (plan.source.url !== 'https://www.channel4.com/press/news/channel-4-makes-tv-history-britains-first-ai-presenter') {
    throw new Error('source URL differs from the pinned official Channel 4 release');
  }
  if (plan.source.publisher !== 'Channel 4' || plan.source.document_type !== 'News Release'
      || plan.source.date !== '20 October 2025' || plan.claims.length !== 8
      || plan.collection.photos !== false || plan.collection.clips !== false
      || plan.collection.follow_links !== false || plan.collection.full_page_screenshot !== false) {
    throw new Error('source identity, claim count, or source-only policy changed');
  }
  const ids = plan.claims.map(claim => claim.id);
  if (ids.join(',') !== '1,2,3,4,5,6,7,8') throw new Error('claim ids must be exactly 1 through 8');
  for (const claim of plan.claims) {
    if (!claim.spoken_claim || !Array.isArray(claim.required_source_phrases)
        || claim.required_source_phrases.length === 0) {
      throw new Error(`claim ${claim.id} lacks source-bound text`);
    }
  }
}

export function paragraphMatches(paragraphs, claim) {
  const needles = claim.required_source_phrases.map(normalizeText);
  return paragraphs
    .map((text, index) => ({ text, index, normalized: normalizeText(text) }))
    .filter(row => row.text.trim() && needles.every(needle => row.normalized.includes(needle)));
}

export function assetDigest(bytes) {
  return crypto.createHash('sha256').update(bytes).digest('hex');
}

function hostedGuard() {
  if (os.platform() !== 'linux' || process.env.GITHUB_ACTIONS !== 'true'
      || process.env.GITHUB_REPOSITORY !== REPOSITORY) {
    throw new Error('refusing source capture before IO: verified public GitHub Actions Linux runner required');
  }
}

async function visibleHeaderLogo(page, selector, pattern) {
  return page.evaluate(({ selector, patternText }) => {
    const pattern = new RegExp(patternText, 'i');
    const visible = el => {
      const rect = el.getBoundingClientRect();
      const style = getComputedStyle(el);
      return rect.width > 0 && rect.height > 0 && style.display !== 'none'
        && style.visibility !== 'hidden' && Number(style.opacity || 1) > 0;
    };
    const headers = [...document.querySelectorAll(selector)];
    const visibleHeaderCount = headers.filter(visible).length;
    const candidates = [];
    for (const header of headers) {
      if (!visible(header)) continue;
      for (const el of header.querySelectorAll('img,svg,[role="img"]')) {
        const attrs = [el.getAttribute('alt'), el.getAttribute('aria-label'), el.getAttribute('title')]
          .filter(Boolean).join(' ');
        if (!pattern.test(attrs)) continue;
        // Images are blocked during discovery, so a genuine logo can have a zero-size box.
        // Discover it by accessible name inside the visible publisher header, then verify
        // dimensions and successful load against this exact URL on the second pass.
        const src = el instanceof HTMLImageElement ? (el.getAttribute('src') || el.currentSrc || el.src) : '';
        const rect = el.getBoundingClientRect();
        candidates.push({ headerIndex: headers.indexOf(header), src, tag: el.tagName.toLowerCase(),
          label: attrs, discovery_box: { width: rect.width, height: rect.height } });
      }
    }
    return { headerCount: headers.length, visibleHeaderCount, candidates };
  }, { selector, patternText: pattern });
}

async function waitForHeaderLogoDom(page, selector, patternText, timeout = 20000) {
  await page.waitForFunction(({ selector, patternText }) => {
    const pattern = new RegExp(patternText, 'i');
    const visible = el => {
      const rect = el.getBoundingClientRect(); const style = getComputedStyle(el);
      return rect.width > 0 && rect.height > 0 && style.display !== 'none'
        && style.visibility !== 'hidden' && Number(style.opacity || 1) > 0;
    };
    return [...document.querySelectorAll(selector)].some(header => visible(header)
      && [...header.querySelectorAll('img,svg,[role="img"]')].some(el => {
        const name = [el.getAttribute('alt'), el.getAttribute('aria-label'), el.getAttribute('title')]
          .filter(Boolean).join(' ');
        return pattern.test(name);
      }));
  }, { selector, patternText }, { timeout });
}

async function waitForLoadedHeaderLogo(page, selector, patternText, expected) {
  try {
    await page.waitForFunction(({ selector, patternText, expected }) => {
      const pattern = new RegExp(patternText, 'i');
      const visible = el => {
        const rect = el.getBoundingClientRect(); const style = getComputedStyle(el);
        return rect.width > 0 && rect.height > 0 && style.display !== 'none'
          && style.visibility !== 'hidden' && Number(style.opacity || 1) > 0;
      };
      return [...document.querySelectorAll(selector)].some(header => visible(header)
        && [...header.querySelectorAll('img,svg,[role="img"]')].some(el => {
          const name = [el.getAttribute('alt'), el.getAttribute('aria-label'), el.getAttribute('title')]
            .filter(Boolean).join(' ');
          if (!pattern.test(name) || name !== expected.label || el.tagName.toLowerCase() !== expected.tag
              || !visible(el)) return false;
          if (el instanceof HTMLImageElement) {
            return (el.currentSrc || el.src) === expected.url && el.complete && el.naturalWidth > 0;
          }
          return el instanceof SVGElement && el.ownerSVGElement === null
            && el.querySelectorAll('path,rect,circle,polygon,text,line,polyline').length > 0;
        }));
    }, { selector, patternText, expected }, { timeout: 20000 });
    return true;
  } catch (error) {
    if (error?.name === 'TimeoutError') return false;
    throw error;
  }
}

async function capture(plan, outputDir) {
  hostedGuard();
  const pageUrl = plan.source.url;
  const baseHost = new URL(pageUrl).hostname;
  const hostAllowed = hostname => hostname === baseHost || hostname.endsWith(plan.collection.allowed_host_suffix);
  const allowedLogoUrls = new Set();
  const { chromium } = await import('playwright');
  const browser = await chromium.launch({ headless: true, args: ['--no-sandbox'] });
  let page;
  let responseStatus = null;
  let failureStage = 'browser-start';
  const identity = {
    schema: 'agmm-source-page-identity-v1', story_id: 'S90',
    pinned_url: pageUrl, final_url: null, http_status: null,
    publisher: plan.source.publisher, document_type: plan.source.document_type,
    expected_title: plan.source.title, observed_title: null,
    expected_date: plan.source.date, observed_date: null,
    title_verified: false, date_verified: false, identified_header_logo_candidates: [],
    header_discovery: null, navigation_init_errors: [],
    no_photos_or_clips_requested: true, editorial_status: 'NOT_REVIEWED',
    release_approval: 'NOT_GRANTED',
  };
  try {
    const context = await browser.newContext({ viewport: { width: 1440, height: 1100 }, deviceScaleFactor: 2,
      serviceWorkers: 'block', reducedMotion: 'reduce' });
    page = await context.newPage();
    page.on('pageerror', error => {
      const message = String(error?.message || '');
      if (/globalnav/i.test(message) && identity.navigation_init_errors.length < 5) {
        identity.navigation_init_errors.push({
          name: String(error?.name || 'Error').slice(0, 48),
          message: message.replace(/https?:\/\/[^\s)]+/gi, '[url]').slice(0, 240),
        });
      }
    });
    page.on('console', message => {
      const text = String(message?.text?.() || '');
      if (message?.type?.() === 'error' && /globalnav/i.test(text)
          && identity.navigation_init_errors.length < 5) {
        identity.navigation_init_errors.push({
          name: 'ConsoleError',
          message: text.replace(/https?:\/\/[^\s)]+/gi, '[url]').slice(0, 240),
        });
      }
    });
    await page.route('**/*', async route => {
      const request = route.request();
      const url = new URL(request.url());
      const type = request.resourceType();
      if (['media', 'audio', 'video'].includes(type)) return route.abort();
      if (['xhr', 'fetch', 'websocket', 'eventsource'].includes(type)) return route.abort();
      if (type === 'image') {
        if (allowedLogoUrls.has(url.href) && hostAllowed(url.hostname)) return route.continue();
        return route.abort();
      }
      if (type === 'document' && normalizeURL(url.href) !== normalizeURL(pageUrl)) return route.abort();
      if (!hostAllowed(url.hostname)) return route.abort();
      return route.continue();
    });

    failureStage = 'initial-source-fetch';
    const firstResponse = await page.goto(pageUrl, { waitUntil: 'domcontentloaded', timeout: 90000 });
    if (!firstResponse) throw new Error('official source navigation returned no HTTP response');
    responseStatus = firstResponse.status();
    identity.http_status = responseStatus;
    identity.final_url = page.url();
    if (responseStatus < 200 || responseStatus >= 300) throw new Error(`official source returned HTTP ${responseStatus}`);
    if (normalizeURL(page.url()) !== normalizeURL(pageUrl)) throw new Error('official source redirected away from the exact pinned URL');
    await page.waitForLoadState('domcontentloaded');

    failureStage = 'header-mark-identification';
    let headerDomReady = true;
    try {
      // Channel 4 injects its global navigation asynchronously. Wait for the observed
      // accessible mark in the actual visible publisher header, not a fixed sleep.
      await waitForHeaderLogoDom(page, plan.source.header_selector,
        plan.source.logo_accessibility_pattern, 20000);
    } catch (error) {
      if (error?.name !== 'TimeoutError') throw error;
      headerDomReady = false;
    }
    const header = await visibleHeaderLogo(page, plan.source.header_selector, plan.source.logo_accessibility_pattern);
    identity.header_discovery = {
      selector: plan.source.header_selector,
      dom_ready_with_accessible_logo: headerDomReady,
      header_count: header.headerCount,
      visible_header_count: header.visibleHeaderCount,
      candidates: header.candidates.map(c => ({ tag: c.tag, accessible_label: c.label || null,
        source_host: c.src ? new URL(c.src, pageUrl).hostname : null, discovery_box: c.discovery_box })),
      navigation_init_errors: identity.navigation_init_errors,
    };
    if (!headerDomReady) {
      throw new Error(`Channel 4 global navigation did not expose its accessible logo within 20 seconds (headers=${header.headerCount}, visible_headers=${header.visibleHeaderCount}, candidates=${header.candidates.length}, navigation_errors=${identity.navigation_init_errors.length})`);
    }
    if (header.candidates.length !== 1 || (header.candidates[0].tag === 'img' && !header.candidates[0].src)) {
      throw new Error(`could not identify exactly one accessible real Channel 4 mark inside the visible native site header (headers=${header.headerCount}, visible_headers=${header.visibleHeaderCount}, candidates=${header.candidates.length})`);
    }
    const logoUrl = new URL(header.candidates[0].src || pageUrl);
    if (!hostAllowed(logoUrl.hostname) || logoUrl.protocol !== 'https:') {
      throw new Error('identified header mark is not served from the Channel 4 HTTPS publisher domain');
    }
    allowedLogoUrls.add(logoUrl.href);
    identity.identified_header_logo_candidates = [{ host: logoUrl.hostname, tag: header.candidates[0].tag,
      accessible_label: header.candidates[0].label || null,
      discovery_box: header.candidates[0].discovery_box,
      second_pass_visibility_required: true, second_pass_loaded: false }];

    failureStage = 'source-render';
    const secondResponse = await page.goto(pageUrl, { waitUntil: 'domcontentloaded', timeout: 90000 });
    if (!secondResponse || secondResponse.status() !== responseStatus || normalizeURL(page.url()) !== normalizeURL(pageUrl)) {
      throw new Error('pinned source identity changed between image-blocked inspection and header-logo capture');
    }
    const logoLoaded = await waitForLoadedHeaderLogo(page, plan.source.header_selector,
      plan.source.logo_accessibility_pattern, {
        tag: header.candidates[0].tag, label: header.candidates[0].label,
        url: header.candidates[0].tag === 'img' ? logoUrl.href : null,
      });
    if (!logoLoaded) throw new Error('Channel 4 header logo image did not load from the pinned publisher domain');
    identity.identified_header_logo_candidates[0].second_pass_loaded = true;

    failureStage = 'title-date-validation';
    const titleMatches = await page.locator(plan.source.title_selector).evaluateAll((els, expected) => {
      const norm = s => String(s || '').replace(/[\u00a0\u2009\u202f]/g, ' ').replace(/[‘’]/g, "'")
        .replace(/[“”]/g, '"').replace(/[–—]/g, '-').replace(/\s+/g, ' ').trim().toLowerCase();
      return els.map((el, index) => ({ el, index })).filter(({ el }) => {
        const r = el.getBoundingClientRect(); const s = getComputedStyle(el);
        return r.width > 0 && r.height > 0 && s.display !== 'none' && s.visibility !== 'hidden'
          && norm(el.innerText) === norm(expected);
      }).map(({ el, index }) => ({ text: el.innerText, index }));
    }, plan.source.title);
    if (titleMatches.length !== 1) throw new Error(`expected one visible exact release h1; found ${titleMatches.length}`);
    identity.observed_title = titleMatches[0].text; identity.title_verified = true;
    const titleIndex = titleMatches[0].index;
    const dates = await page.locator(plan.source.date_selector).evaluateAll((els, expected) => {
      const norm = s => String(s || '').replace(/[\u00a0\u2009\u202f]/g, ' ').replace(/\s+/g, ' ').trim().toLowerCase();
      return els.map((el, index) => ({ el, index })).filter(({ el }) => {
        const r = el.getBoundingClientRect(); const s = getComputedStyle(el);
        return r.width > 0 && r.height > 0 && s.display !== 'none' && s.visibility !== 'hidden'
          && norm(el.innerText || el.getAttribute('datetime')) === norm(expected);
      }).map(({ el, index }) => ({ text: el.innerText || el.getAttribute('datetime'), index }));
    }, plan.source.date);
    if (dates.length !== 1) throw new Error(`expected one visible exact release date element; found ${dates.length}`);
    identity.observed_date = dates[0].text; identity.date_verified = true;
    const dateIndex = dates[0].index;

    failureStage = 'claim-paragraph-validation';
    const paragraphs = await page.locator('article p, main p').evaluateAll(els => {
      const visible = el => {
        const r = el.getBoundingClientRect(); const s = getComputedStyle(el);
        return r.width > 0 && r.height > 0 && s.display !== 'none' && s.visibility !== 'hidden';
      };
      return els.map((el, index) => ({ text: el.innerText || '', tag: el.tagName.toLowerCase(), index,
        visible: visible(el) })).filter(row => row.visible && row.text.trim());
    });
    const bindings = [];
    for (const claim of plan.claims) {
      const matches = paragraphMatches(paragraphs.map(p => p.visible ? p.text : ''), claim);
      if (matches.length !== 1) throw new Error(`claim ${claim.id}: expected exactly one live source paragraph matching all frozen phrases; found ${matches.length}`);
      const paragraph = paragraphs[matches[0].index];
      bindings.push({ claim, paragraph, paragraph_index: paragraph.index });
    }

    failureStage = 'native-source-crop-capture';
    await fs.mkdir(outputDir, { recursive: false });
    const headerIndex = header.candidates[0].headerIndex;
    const headerLocator = page.locator(plan.source.header_selector).nth(headerIndex);
    // If the site's semantic attributes do not let Playwright resolve this same header, fail instead of cropping a guess.
    if (await headerLocator.count() !== 1) throw new Error('identified logo header could not be reselected unambiguously');
    const rows = [];
    async function saveElement(locator, filename, metadata) {
      await locator.screenshot({ path: path.join(outputDir, filename), type: 'png', animations: 'disabled', timeout: 30000 });
      const bytes = await fs.readFile(path.join(outputDir, filename));
      if (bytes.length < 100 || bytes.length > MAX_ASSET_BYTES || bytes.subarray(0, 8).toString('hex') !== '89504e470d0a1a0a') {
        throw new Error(`native DOM screenshot did not produce a valid PNG: ${filename}`);
      }
      const asset = { file: filename, type: metadata.type, source_url: pageUrl,
        publisher: plan.source.publisher, document_type: plan.source.document_type,
        document_title: plan.source.title, document_date: plan.source.date,
        credit_line_for_composition: plan.source.credit_line,
        placement_scope: 'source evidence pane only; remove before AGMM CTA',
        sha256: assetDigest(bytes), bytes: bytes.length,
        human_rights_review: 'REQUIRED', usable_for_render: false, ...metadata };
      rows.push(asset);
      return asset;
    }
    await saveElement(headerLocator, 'header-channel4.png', { type: 'native_publisher_header', claim_ids: [],
      logo_host: logoUrl.hostname, matched_source_text_sha256: null });
    await saveElement(page.locator(plan.source.title_selector).nth(titleIndex), 'release-title.png', { type: 'native_release_title', claim_ids: [],
      matched_source_text_sha256: assetDigest(Buffer.from(normalizeText(identity.observed_title))) });
    await saveElement(page.locator(plan.source.date_selector).nth(dateIndex), 'release-date.png', { type: 'native_release_date', claim_ids: [],
      matched_source_text_sha256: assetDigest(Buffer.from(normalizeText(identity.observed_date))) });
    for (const { claim, paragraph, paragraph_index } of bindings) {
      const locator = page.locator('article p, main p').nth(paragraph.index);
      const filename = `claim-${String(claim.id).padStart(2, '0')}.png`;
      const normalizedParagraph = normalizeText(paragraph.text);
      const missing = claim.required_source_phrases.filter(phrase => !normalizedParagraph.includes(normalizeText(phrase)));
      if (missing.length) throw new Error(`claim ${claim.id}: a frozen source phrase disappeared before screenshot`);
      await saveElement(locator, filename, { type: 'native_source_claim_paragraph', claim_ids: [claim.id],
        spoken_claim_text: claim.spoken_claim, required_source_phrases: claim.required_source_phrases,
        matched_source_paragraph_sha256: assetDigest(Buffer.from(normalizedParagraph)), paragraph_index,
        match_method: 'all exact frozen phrases present in one visible live-page paragraph after typography/whitespace normalization' });
    }
    const totalAssetBytes = rows.reduce((sum, row) => sum + row.bytes, 0);
    if (totalAssetBytes > MAX_TOTAL_ASSET_BYTES) throw new Error('captured source crops exceed the total output size bound');
    identity.capture_stage = 'SOURCE_CROPS_CAPTURED';
    identity.captured_at = new Date().toISOString();
    const manifest = {
      schema: 'agmm-source-pack-manifest-v1', story_id: 'S90', source_plan_sha256: PLAN_SHA256,
      source: { url: pageUrl, final_url: identity.final_url, http_status: responseStatus,
        publisher: plan.source.publisher, document_type: plan.source.document_type,
        title: identity.observed_title, date: identity.observed_date,
        credit_line: plan.source.credit_line, credit_display_rule: 'at least 42px at 1080px output width for full asset duration' },
      claim_bindings: bindings.map(({ claim, paragraph_index }) => ({
        id: claim.id, spoken_claim_text: claim.spoken_claim, asset_file: `claim-${String(claim.id).padStart(2, '0')}.png`,
        required_source_phrases: claim.required_source_phrases,
        source_paragraph_index: paragraph_index, source_paragraph_sha256: rows.find(row => row.claim_ids?.includes(claim.id)).matched_source_paragraph_sha256,
      })),
      non_source_advice: plan.non_source_advice,
      assets: rows,
      policy: { photos: false, clips: false, followed_links: false, full_page_capture: false,
        media_requests: 'blocked', external_hosts: 'blocked except same-publisher header mark if required',
        rights_status: 'NOT_ASSESSED', editorial_status: 'NEEDS_ROOT_EYES', release_approval: 'NOT_GRANTED',
        render_approval: 'NOT_GRANTED' },
    };
    await fs.writeFile(path.join(outputDir, 'SOURCE-IDENTITY.json'), JSON.stringify(identity, null, 2) + '\n');
    await fs.writeFile(path.join(outputDir, 'manifest.json'), JSON.stringify(manifest, null, 2) + '\n');
    await fs.writeFile(path.join(outputDir, 'CAPTURE-RECEIPT.json'), JSON.stringify({
      schema: 'agmm-source-pack-capture-receipt-v1', story_id: 'S90',
      status: 'SOURCE_CROPS_CAPTURED_NEEDS_ROOT_EYES', source_url: pageUrl,
      source_plan_sha256: PLAN_SHA256, asset_count: rows.length, files: rows.map(row => row.file),
      editorial_status: 'NEEDS_ROOT_EYES', rights_status: 'NOT_ASSESSED',
      render_approval: 'NOT_GRANTED', release_approval: 'NOT_GRANTED',
    }, null, 2) + '\n');
    return { identity, rows };
  } catch (error) {
    await fs.mkdir(outputDir, { recursive: true });
    identity.http_status = responseStatus ?? identity.http_status;
    identity.final_url = page?.url() || identity.final_url;
    identity.capture_stage = failureStage;
    identity.captured_at = new Date().toISOString();
    identity.failure = String(error?.message || error).slice(0, 600);
    identity.editorial_status = 'SOURCE_CAPTURE_FAILED';
    await fs.writeFile(path.join(outputDir, 'SOURCE-IDENTITY.json'), JSON.stringify(identity, null, 2) + '\n');
    await fs.writeFile(path.join(outputDir, 'CAPTURE-RECEIPT.json'), JSON.stringify({
      schema: 'agmm-source-pack-capture-receipt-v1', story_id: 'S90', status: 'SOURCE_CAPTURE_FAILED',
      source_url: pageUrl, source_plan_sha256: PLAN_SHA256, failure_stage: failureStage,
      failure: identity.failure, assets_published: false, editorial_status: 'SOURCE_CAPTURE_FAILED',
      render_approval: 'NOT_GRANTED', release_approval: 'NOT_GRANTED',
    }, null, 2) + '\n');
    throw error;
  } finally {
    await browser.close().catch(() => {});
  }
}

export async function runCapture({ planPath = SOURCE_PLAN_PATH, outputDir = process.env.S90_CAPTURE_DIR } = {}) {
  hostedGuard();
  const raw = await fs.readFile(planPath);
  if (assetDigest(raw) !== PLAN_SHA256) throw new Error('frozen S90 source plan SHA-256 mismatch');
  const plan = JSON.parse(raw.toString('utf8'));
  validatePlan(plan);
  if (!outputDir) throw new Error('S90_CAPTURE_DIR is required');
  return capture(plan, outputDir);
}

if (process.argv[1] && path.resolve(process.argv[1]) === path.resolve(new URL(import.meta.url).pathname)) {
  const outputDir = process.env.S90_CAPTURE_DIR;
  runCapture({ outputDir }).catch(error => {
    console.error(`S90 source capture refused: ${String(error?.message || error).slice(0, 600)}`);
    process.exitCode = 1;
  });
}
