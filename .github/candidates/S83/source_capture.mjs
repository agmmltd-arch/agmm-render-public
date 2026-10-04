import fs from "node:fs/promises";
import path from "node:path";
import { createHash } from "node:crypto";
import { chromium } from "playwright";
import {
  assertSafeMarkUrl,
  assertTaggedSourceNavigation,
  hasAccessibleBrandIdentity,
  receiptText,
  receiptUrlOrRedacted,
  safeReceiptError,
  sanitizeReceiptUrl,
  tagSourceUrl
} from "./source_url_guard.mjs";

const out = process.env.S83_CAPTURE_DIR;
if (!out) throw new Error("S83_CAPTURE_DIR is required");
await fs.mkdir(path.join(out, "assets"), { recursive: true });
let browser;
const receipt = {
  schema: "agmm-s83-hosted-source-capture-v1",
  story_id: "S83",
  status: "SOURCE_CAPTURE_FAILED",
  host: "public agmm-render-public Ubuntu Actions runner",
  navigation_policy: {
    required_query: { utm_source: "qa", utm_campaign: "qa_release_audit" },
    enforcement: "Every main-frame navigation must contain each exact value once; strip only these two keys when comparing redirect identity to its canonical source URL.",
    off_source_or_untagged_navigation: "BLOCKED"
  },
  items: [],
  logo_discovery: [],
  rights: {
    status: "NOT_ASSESSED",
    restriction: "Trust logo PNGs are limited to this source-review artifact. Permission for this public review copy and any downstream use is not verified. Do not include them in a public master/site/post or imply endorsement until rights are assessed and approved."
  },
  render_approval: "NOT_GRANTED",
  release_approval: "NOT_GRANTED"
};

const normalize = value => value.replace(/[’‘]/g, "'").replace(/\s+/g, " ").toLowerCase();

async function openSource(url, expectedHosts, titleTest) {
  const requestedHost = new URL(url).hostname;
  if (!expectedHosts.includes(requestedHost)) throw new Error("requested source host is not exactly allowlisted: " + requestedHost);
  const page = await browser.newPage({ viewport: { width: 1600, height: 1200 }, deviceScaleFactor: 1 });
  const requestedUrl = tagSourceUrl(url);
  const navigationUrls = [];
  const blockedNavigations = [];
  await page.route("**/*", async route => {
    const request = route.request();
    if (!request.isNavigationRequest() || request.frame() !== page.mainFrame()) {
      await route.continue();
      return;
    }
    try {
      navigationUrls.push(assertTaggedSourceNavigation(request.url(), url, expectedHosts));
      await route.continue();
    } catch (error) {
      blockedNavigations.push({ url: receiptUrlOrRedacted(request.url()), reason: safeReceiptError(error) });
      await route.abort("blockedbyclient");
    }
  });
  let response;
  try {
    response = await page.goto(requestedUrl, { waitUntil: "domcontentloaded", timeout: 45000 });
  } catch (error) {
    if (blockedNavigations.length) {
      throw new Error("source navigation guard blocked an unsafe navigation: " + JSON.stringify(blockedNavigations));
    }
    throw error;
  }
  if (blockedNavigations.length) throw new Error("source navigation guard blocked an unsafe navigation: " + JSON.stringify(blockedNavigations));
  const finalUrl = page.url();
  if (!response || response.status() !== 200) throw new Error("source HTTP status was not 200: " + url);
  const finalHost = new URL(finalUrl).hostname;
  assertTaggedSourceNavigation(finalUrl, url, expectedHosts);
  if (!expectedHosts.includes(finalHost)) throw new Error("source redirected outside the exact allowlisted hosts: " + finalUrl);
  const title = await page.title();
  if (!titleTest.test(title)) throw new Error("source title did not match: " + title);
  return { page, title: receiptText(title), finalUrl, canonicalUrl: url, requestedUrl, requestedHost, finalHost, status: response.status(), allowedHosts: expectedHosts, navigationUrls };
}

async function captureOfficialTrustLogo(source, filename, publisher, identityPattern) {
  const images = await source.page.locator("header img").evaluateAll(nodes => nodes.map((img, index) => {
    const box = img.getBoundingClientRect();
    const style = getComputedStyle(img);
    const ownerLink = img.closest("a");
    return {
      index,
      selector: `page.locator("header img").nth(${index})`,
      alt: img.getAttribute("alt"),
      title: img.getAttribute("title"),
      aria_label: img.getAttribute("aria-label"),
      owner_link_aria_label: ownerLink?.getAttribute("aria-label") || null,
      owner_link_title: ownerLink?.getAttribute("title") || null,
      src: img.getAttribute("src"),
      current_src: img.currentSrc,
      natural_width: img.naturalWidth,
      natural_height: img.naturalHeight,
      visible: box.width > 0 && box.height > 0 && style.display !== "none" && style.visibility !== "hidden"
    };
  }));
  const candidates = images.filter(img => img.visible && hasAccessibleBrandIdentity(img, identityPattern));
  const publicImages = images.slice(0, 50).map(img => ({
    index: img.index,
    selector: receiptText(img.selector),
    alt: receiptText(img.alt),
    title: receiptText(img.title),
    aria_label: receiptText(img.aria_label),
    owner_link_aria_label: receiptText(img.owner_link_aria_label),
    owner_link_title: receiptText(img.owner_link_title),
    src: receiptUrlOrRedacted(img.src),
    current_src: receiptUrlOrRedacted(img.current_src),
    natural_width: img.natural_width,
    natural_height: img.natural_height,
    visible: img.visible
  }));
  receipt.logo_discovery.push({
    publisher,
    requested_url: sanitizeReceiptUrl(source.requestedUrl),
    final_url: sanitizeReceiptUrl(source.finalUrl),
    header_image_count: images.length,
    header_images_truncated: images.length > publicImages.length,
    header_images: publicImages,
    identity_match_count: candidates.length
  });
  if (candidates.length !== 1) throw new Error(`${publisher} official header logo img must be a unique visible match from accessible alt/title/aria-label evidence; found ${candidates.length}`);

  const logo = candidates[0];
  if (!logo.src) throw new Error(`${publisher} official header logo img has no source URL`);
  assertSafeMarkUrl(new URL(logo.src, source.finalUrl).href);
  assertSafeMarkUrl(logo.current_src);
  const locator = source.page.locator("header img").nth(logo.index);
  const target = path.join(out, "assets", filename);
  await locator.screenshot({ path: target, animations: "disabled", timeout: 20000 });
  const bytes = await fs.readFile(target);
  if (bytes.length < 1000) throw new Error(filename + " capture is unexpectedly small");
  receipt.items.push({
    file: "assets/" + filename,
    publisher,
    evidence: {
      requested_url: sanitizeReceiptUrl(source.requestedUrl),
      canonical_source_url: sanitizeReceiptUrl(source.canonicalUrl),
      final_url: sanitizeReceiptUrl(source.finalUrl),
      navigation_urls: source.navigationUrls.map(sanitizeReceiptUrl),
      requested_host: source.requestedHost,
      final_host: source.finalHost,
      allowed_hosts: source.allowedHosts,
      page_title: receiptText(source.title),
      selector: receiptText(logo.selector),
      src: receiptUrlOrRedacted(logo.src),
      current_src: receiptUrlOrRedacted(logo.current_src),
      alt: receiptText(logo.alt),
      title: receiptText(logo.title),
      aria_label: receiptText(logo.aria_label),
      owner_link_aria_label: receiptText(logo.owner_link_aria_label),
      owner_link_title: receiptText(logo.owner_link_title),
      identity_basis: "accessible alt/title/aria-label on the header image or its linked logo; src/currentSrc are recorded but never used as brand proof",
      natural_width: logo.natural_width,
      natural_height: logo.natural_height,
      identity_match_count: candidates.length
    },
    bytes: bytes.length,
    sha256: createHash("sha256").update(bytes).digest("hex")
  });
}

try {
  browser = await chromium.launch({ headless: true });

  const wht = await openSource(
    "https://www.walsallhealthcare.nhs.uk/news/2026/08/25/new-digital-ambient-voice-technology-avt/",
    ["www.walsallhealthcare.nhs.uk"],
    /New digital Ambient Voice Technology/i
  );
  const whtBody = await wht.page.locator("body").innerText();
  const whtNormalized = normalize(whtBody);
  const whtChecks = [
    "25 august 2026",
    "on average reduced clinicians' documentation time to less than four minutes per patient",
    "reviewed, edited where necessary and approved",
    "successful 8-month pilot",
    "the royal wolverhampton and walsall healthcare"
  ];
  for (const text of whtChecks) if (!whtNormalized.includes(normalize(text))) throw new Error("Walsall issuer source missing exact dated evidence: " + text);
  await captureOfficialTrustLogo(wht, "wht-mark.png", "Walsall Healthcare NHS Trust", "walsall");
  receipt.items.push({
    type: "verified-source-text",
    publisher: "Walsall Healthcare NHS Trust",
    requested_url: sanitizeReceiptUrl(wht.requestedUrl),
    canonical_source_url: sanitizeReceiptUrl(wht.canonicalUrl),
    url: sanitizeReceiptUrl(wht.finalUrl),
    navigation_urls: wht.navigationUrls.map(sanitizeReceiptUrl),
    requested_host: wht.requestedHost,
    final_host: wht.finalHost,
    allowed_hosts: wht.allowedHosts,
    title: wht.title,
    status: wht.status,
    publication_date: "25 August 2026",
    verified_excerpts: [
      "less than four minutes per patient",
      "reviewed, edited where necessary and approved"
    ]
  });
  await wht.page.close();

  const rwt = await openSource(
    "https://www.royalwolverhampton.nhs.uk/",
    ["www.royalwolverhampton.nhs.uk", "royalwolverhampton.nhs.uk"],
    /Royal Wolverhampton/i
  );
  await captureOfficialTrustLogo(rwt, "rwt-mark.png", "The Royal Wolverhampton NHS Trust", "royal[ -]?wolverhampton|\\brwt\\b");
  receipt.items.push({
    type: "official-page-identity",
    publisher: "The Royal Wolverhampton NHS Trust",
    requested_url: sanitizeReceiptUrl(rwt.requestedUrl),
    canonical_source_url: sanitizeReceiptUrl(rwt.canonicalUrl),
    url: sanitizeReceiptUrl(rwt.finalUrl),
    navigation_urls: rwt.navigationUrls.map(sanitizeReceiptUrl),
    requested_host: rwt.requestedHost,
    final_host: rwt.finalHost,
    allowed_hosts: rwt.allowedHosts,
    title: rwt.title,
    status: rwt.status
  });
  await rwt.page.close();

  const bbc = await openSource(
    "https://www.bbc.com/news/articles/cjrgrxgexjro",
    ["www.bbc.com"],
    /BBC News/i
  );
  const bbcBody = await bbc.page.locator("body").innerText();
  const bbcNormalized = normalize(bbcBody);
  const bbcDate = "15 july 2026";
  const sixMinuteExcerpt = "saving him six minutes per consultation";
  const clarificationDate = "clarification 24 july";
  const clarificationExcerpt = "evidence for this has not yet been published";
  for (const text of [bbcDate, "dr mohammed jamil aslam", "is " + sixMinuteExcerpt, clarificationDate, clarificationExcerpt]) {
    if (!bbcNormalized.includes(normalize(text))) throw new Error("BBC canonical article missing the exact date, six-minute report, or clarification: " + text);
  }
  receipt.items.push({
    type: "verified-source-text",
    publisher: "BBC News",
    requested_url: sanitizeReceiptUrl(bbc.requestedUrl),
    canonical_source_url: sanitizeReceiptUrl(bbc.canonicalUrl),
    url: sanitizeReceiptUrl(bbc.finalUrl),
    navigation_urls: bbc.navigationUrls.map(sanitizeReceiptUrl),
    requested_host: bbc.requestedHost,
    final_host: bbc.finalHost,
    allowed_hosts: bbc.allowedHosts,
    title: bbc.title,
    status: bbc.status,
    publication_date: "15 July 2026",
    clarification_date: "24 July 2026",
    verified_excerpts: [sixMinuteExcerpt, clarificationExcerpt],
    media_captured: false
  });
  await bbc.page.close();

  const expected = ["assets/rwt-mark.png", "assets/wht-mark.png"];
  const actual = receipt.items.filter(item => item.file).map(item => item.file).sort();
  if (JSON.stringify(actual) !== JSON.stringify(expected)) throw new Error("hosted Trust logo allowlist does not match the frozen asset set");
  receipt.status = "SOURCE_TEXT_AND_TRUST_LOGOS_CAPTURED_NEEDS_INDEPENDENT_EYES";
} catch (error) {
    receipt.failure = safeReceiptError(error);
} finally {
  await fs.writeFile(path.join(out, "SOURCE-CAPTURE-RECEIPT.json"), JSON.stringify(receipt, null, 2) + "\n");
  if (browser) await browser.close();
}
if (receipt.status !== "SOURCE_TEXT_AND_TRUST_LOGOS_CAPTURED_NEEDS_INDEPENDENT_EYES") process.exitCode = 1;
