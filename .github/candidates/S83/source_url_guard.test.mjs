import test from "node:test";
import assert from "node:assert/strict";
import {
  MAX_RECEIPT_STRING_LENGTH,
  assertSafeMarkUrl,
  assertTaggedSourceNavigation,
  hasAccessibleBrandIdentity,
  matchesExpectedSourceTitle,
  receiptText,
  safeReceiptError,
  sanitizeReceiptUrl,
  tagSourceUrl
} from "./source_url_guard.mjs";

test("adds the exact audit tags and preserves source path plus other query bindings", () => {
  const source = "https://www.walsallhealthcare.nhs.uk/news/avt/?edition=2026&ref=brief";
  const tagged = tagSourceUrl(source);
  const actual = new URL(tagged);
  assert.equal(actual.searchParams.getAll("utm_source").length, 1);
  assert.equal(actual.searchParams.get("utm_source"), "qa");
  assert.equal(actual.searchParams.getAll("utm_campaign").length, 1);
  assert.equal(actual.searchParams.get("utm_campaign"), "qa_release_audit");
  assert.equal(actual.pathname, "/news/avt/");
  assert.deepEqual(actual.searchParams.getAll("edition"), ["2026"]);
  assert.deepEqual(actual.searchParams.getAll("ref"), ["brief"]);
  assertTaggedSourceNavigation(tagged, source, ["www.walsallhealthcare.nhs.uk"]);
});

test("rejects an untagged page navigation", () => {
  const source = "https://www.walsallhealthcare.nhs.uk/news/avt/";
  assert.throws(() => assertTaggedSourceNavigation(source, source,
    ["www.walsallhealthcare.nhs.uk"]), /utm_source=qa/);
});

test("rejects an incorrect or duplicate audit tag binding", () => {
  const source = "https://www.walsallhealthcare.nhs.uk/news/avt/";
  assert.throws(() => assertTaggedSourceNavigation(
    "https://www.walsallhealthcare.nhs.uk/news/avt/?utm_source=real&utm_campaign=qa_release_audit",
    source, ["www.walsallhealthcare.nhs.uk"]), /utm_source=qa/);
  assert.throws(() => assertTaggedSourceNavigation(
    "https://www.walsallhealthcare.nhs.uk/news/avt/?utm_source=qa&utm_source=qa&utm_campaign=qa_release_audit",
    source, ["www.walsallhealthcare.nhs.uk"]), /exactly utm_source=qa/);
});

test("rejects off-source redirects and path/query changes", () => {
  const source = "https://www.royalwolverhampton.nhs.uk/?section=about";
  const hosts = ["www.royalwolverhampton.nhs.uk", "royalwolverhampton.nhs.uk"];
  assert.throws(() => assertTaggedSourceNavigation(
    "https://attacker.example/?section=about&utm_source=qa&utm_campaign=qa_release_audit",
    source, hosts), /allowlist/);
  assert.throws(() => assertTaggedSourceNavigation(
    "https://www.royalwolverhampton.nhs.uk/other/?section=about&utm_source=qa&utm_campaign=qa_release_audit",
    source, hosts), /identity/);
  assert.throws(() => assertTaggedSourceNavigation(
    "https://www.royalwolverhampton.nhs.uk/?section=press&utm_source=qa&utm_campaign=qa_release_audit",
    source, hosts), /identity/);
});

test("allows only the explicit RWT hostname alias when path/query and tags stay exact", () => {
  const source = "https://www.royalwolverhampton.nhs.uk/?section=about";
  assertTaggedSourceNavigation(
    "https://royalwolverhampton.nhs.uk/?section=about&utm_source=qa&utm_campaign=qa_release_audit",
    source, ["www.royalwolverhampton.nhs.uk", "royalwolverhampton.nhs.uk"]);
});

test("requires accessible brand identity and never treats an image URL as proof", () => {
  const pattern = "walsall healthcare";
  assert.equal(hasAccessibleBrandIdentity({ src: "https://walsallhealthcare.nhs.uk/walsall-logo.png" }, pattern), false);
  assert.equal(hasAccessibleBrandIdentity({ alt: "Walsall Healthcare NHS Trust" }, pattern), true);
  assert.equal(hasAccessibleBrandIdentity({ title: "Walsall Healthcare NHS Trust logo" }, pattern), true);
  assert.equal(hasAccessibleBrandIdentity({ owner_link_aria_label: "Walsall Healthcare home" }, pattern), true);
  assert.equal(hasAccessibleBrandIdentity({ alt: "Hospital logo", src: "https://walsallhealthcare.nhs.uk/logo.png" }, pattern), false);
});

test("matches the live BBC primary article title and rejects the old publisher-name predicate", () => {
  const liveTitle = "How an AI app is improving NHS wait times in the West Midlands";
  assert.equal(matchesExpectedSourceTitle(liveTitle,
    /How an AI app is improving NHS wait times in the West Midlands/i), true);
  assert.equal(matchesExpectedSourceTitle(liveTitle, /BBC News/i), false);
  assert.equal(matchesExpectedSourceTitle("BBC News - unrelated article",
    /How an AI app is improving NHS wait times in the West Midlands/i), false);
  assert.equal(matchesExpectedSourceTitle("",
    /How an AI app is improving NHS wait times in the West Midlands/i), false);
});

test("rejects credential-bearing navigation and mark URLs", () => {
  const source = "https://www.walsallhealthcare.nhs.uk/news/avt/";
  const credentialUrl = "https://user:secret@www.walsallhealthcare.nhs.uk/news/avt/?utm_source=qa&utm_campaign=qa_release_audit";
  assert.throws(() => assertTaggedSourceNavigation(credentialUrl, source,
    ["www.walsallhealthcare.nhs.uk"]), /credentials/);
  assert.throws(() => assertSafeMarkUrl("https://user:secret@cdn.walsallhealthcare.nhs.uk/logo.png"), /credentials/);
  const safeError = safeReceiptError(new Error("blocked https://user:secret@www.walsallhealthcare.nhs.uk/news/avt/?token=private#fragment"));
  assert.doesNotMatch(safeError, /user|secret|token|private|fragment/);
  assert.match(safeError, /URL omitted/);
});

test("rejects nondefault HTTPS ports for navigation and mark URLs", () => {
  const source = "https://www.walsallhealthcare.nhs.uk/news/avt/";
  const portUrl = "https://www.walsallhealthcare.nhs.uk:8443/news/avt/?utm_source=qa&utm_campaign=qa_release_audit";
  assert.throws(() => assertTaggedSourceNavigation(portUrl, source,
    ["www.walsallhealthcare.nhs.uk"]), /default HTTPS port/);
  assert.throws(() => assertSafeMarkUrl("https://cdn.walsallhealthcare.nhs.uk:8443/logo.png"), /default HTTPS port/);
});

test("strips transient query and fragment from receipts while runtime identity still rejects them", () => {
  const source = "https://www.walsallhealthcare.nhs.uk/news/avt/";
  const transient = "https://www.walsallhealthcare.nhs.uk/news/avt/?utm_source=qa&utm_campaign=qa_release_audit&session_secret=private#fragment";
  assert.equal(sanitizeReceiptUrl(transient), "https://www.walsallhealthcare.nhs.uk/news/avt/?utm_source=qa&utm_campaign=qa_release_audit");
  assert.equal(receiptText("title https://www.walsallhealthcare.nhs.uk/news/avt/?private=token#frag"),
    "title https://www.walsallhealthcare.nhs.uk/news/avt/");
  assert.throws(() => assertTaggedSourceNavigation(transient, source,
    ["www.walsallhealthcare.nhs.uk"]), /identity/);
});

test("caps oversized receipt strings and error messages", () => {
  const longValue = "sensitive-value ".repeat(100);
  const cappedText = receiptText(longValue);
  const cappedError = safeReceiptError(new Error(longValue));
  assert.equal(cappedText.length, MAX_RECEIPT_STRING_LENGTH);
  assert.equal(cappedText.endsWith("…"), true);
  assert.equal(cappedError.length, MAX_RECEIPT_STRING_LENGTH);
  assert.equal(cappedError.endsWith("…"), true);
});
