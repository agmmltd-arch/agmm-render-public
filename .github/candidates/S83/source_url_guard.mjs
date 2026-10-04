const AUDIT_PARAMS = new Map([
  ["utm_source", "qa"],
  ["utm_campaign", "qa_release_audit"]
]);
export const MAX_RECEIPT_STRING_LENGTH = 512;

function safeHttpsUrl(value, label) {
  const url = new URL(value);
  if (url.protocol !== "https:") throw new Error(`${label} must use HTTPS`);
  if (url.username || url.password) throw new Error(`${label} must not contain URL credentials`);
  if (url.port) throw new Error(`${label} must use the default HTTPS port`);
  return url;
}

export function assertSafeMarkUrl(markUrl) {
  safeHttpsUrl(markUrl, "mark image URL");
  return true;
}

export function sanitizeReceiptUrl(value) {
  const url = safeHttpsUrl(value, "receipt URL");
  const auditValues = [];
  for (const [name, expected] of AUDIT_PARAMS) {
    const bindings = url.searchParams.getAll(name);
    if (bindings.length && (bindings.length !== 1 || bindings[0] !== expected)) {
      throw new Error("receipt URL contains a noncanonical audit binding");
    }
    if (bindings.length) auditValues.push([name, expected]);
  }
  const hasAnyAuditValue = [...AUDIT_PARAMS.keys()].some(name => url.searchParams.has(name));
  if (hasAnyAuditValue && auditValues.length !== AUDIT_PARAMS.size) {
    throw new Error("receipt URL contains an incomplete audit binding");
  }
  url.search = "";
  url.hash = "";
  for (const [name, value] of auditValues) url.searchParams.append(name, value);
  return capString(url.href);
}

export function receiptUrlOrRedacted(value) {
  try {
    return sanitizeReceiptUrl(value);
  } catch {
    return "[URL omitted: unsafe or invalid]";
  }
}

export function receiptText(value) {
  if (value === null || value === undefined) return null;
  const normalized = String(value).replace(/[\u0000-\u001f\u007f]/g, " ").replace(/\s+/g, " ").trim();
  const sanitized = normalized.replace(/https?:\/\/[^\s"'<>]+/gi, rawUrl => {
    let candidate = rawUrl;
    while (/[),.;!?]$/.test(candidate)) candidate = candidate.slice(0, -1);
    const punctuation = rawUrl.slice(candidate.length);
    return receiptUrlOrRedacted(candidate) + punctuation;
  });
  return capString(sanitized);
}

function capString(value) {
  if (value.length <= MAX_RECEIPT_STRING_LENGTH) return value;
  return value.slice(0, MAX_RECEIPT_STRING_LENGTH - 1) + "…";
}

export function safeReceiptError(error) {
  const message = error instanceof Error ? `${error.name}: ${error.message}` : String(error);
  const sanitized = message.replace(/https?:\/\/[^\s"'<>]+/gi, rawUrl => {
    let candidate = rawUrl;
    while (/[),.;!?]$/.test(candidate)) candidate = candidate.slice(0, -1);
    return receiptUrlOrRedacted(candidate);
  });
  return receiptText(sanitized);
}

export function tagSourceUrl(sourceUrl) {
  const tagged = safeHttpsUrl(sourceUrl, "source URL");
  for (const [name, value] of AUDIT_PARAMS) tagged.searchParams.set(name, value);
  return tagged.href;
}

function sourceIdentity(url) {
  const value = new URL(url);
  const retainedQuery = [...value.searchParams.entries()]
    .filter(([name]) => !AUDIT_PARAMS.has(name));
  return {
    protocol: value.protocol,
    pathname: value.pathname,
    query: JSON.stringify(retainedQuery),
    hash: value.hash
  };
}

export function assertTaggedSourceNavigation(navigationUrl, canonicalSourceUrl, allowedHosts) {
  const actual = safeHttpsUrl(navigationUrl, "navigation URL");
  const source = safeHttpsUrl(canonicalSourceUrl, "canonical source URL");
  if (source.protocol !== "https:" || !allowedHosts.includes(source.hostname)) {
    throw new Error("canonical source is not an HTTPS URL on its exact allowlist");
  }
  if (actual.protocol !== "https:" || !allowedHosts.includes(actual.hostname)) {
    throw new Error("navigation host/protocol is outside the source-specific allowlist");
  }
  for (const [name, value] of AUDIT_PARAMS) {
    const bindings = actual.searchParams.getAll(name);
    if (bindings.length !== 1 || bindings[0] !== value) {
      throw new Error(`navigation must carry exactly ${name}=${value}`);
    }
  }
  const identity = sourceIdentity(actual);
  const expected = sourceIdentity(source);
  if (identity.protocol !== expected.protocol || identity.pathname !== expected.pathname ||
      identity.query !== expected.query || identity.hash !== expected.hash) {
    throw new Error("redirect changed canonical source path or non-audit query identity");
  }
  return actual.href;
}

export function hasAccessibleBrandIdentity(imageMetadata, identityPattern) {
  const identity = new RegExp(identityPattern, "i");
  return [
    imageMetadata.alt,
    imageMetadata.title,
    imageMetadata.aria_label,
    imageMetadata.owner_link_aria_label,
    imageMetadata.owner_link_title
  ].filter(Boolean).some(value => identity.test(value));
}
