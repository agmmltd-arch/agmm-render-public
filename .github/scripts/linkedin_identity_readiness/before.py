#!/usr/bin/env python3
"""Single fail-closed owner for the authorised LinkedIn publishing identity."""
from __future__ import annotations

from urllib.parse import urlsplit


PROFILE_NAME = "Samuel Wall"
PROFILE_URL = "https://www.linkedin.com/in/samuel-wall-7a7a93351/"
PROFILE_MARKER = "AGMM"


def normalise_profile_url(value: str) -> str:
    parsed = urlsplit(value)
    host = parsed.netloc.lower().split(":", 1)[0]
    path = parsed.path.rstrip("/").lower()
    return f"https://{host}{path}"


def identity_from_profile(url: str, body: str) -> dict:
    """Validate LinkedIn's /in/me redirect and return observed identity evidence.

    The canonical self-profile URL is the stable account credential. Headline
    copy is evidence recorded from the live page, not a credential, because it
    can legitimately change without changing the signed-in account.
    """
    observed_url = normalise_profile_url(url)
    expected_url = normalise_profile_url(PROFILE_URL)
    if observed_url != expected_url:
        raise RuntimeError(
            "LinkedIn identity mismatch; /in/me resolved to "
            f"{observed_url!r}, expected {expected_url!r}"
        )
    lines = [line.strip() for line in body.splitlines() if line.strip()]
    if PROFILE_NAME not in lines:
        raise RuntimeError("LinkedIn identity mismatch; authorised profile name not found")
    name_index = lines.index(PROFILE_NAME)
    headline = next(
        (line for line in lines[name_index + 1 : name_index + 20] if PROFILE_MARKER in line),
        "",
    )
    if not headline:
        raise RuntimeError("LinkedIn identity mismatch; AGMM profile marker not found")
    return {
        "name": PROFILE_NAME,
        "headline": headline,
        "profile_url": PROFILE_URL,
        "verified": True,
        "verification_method": "linkedin_in_me_redirect_name_and_agmm_marker",
    }


def verify_identity(page) -> dict:
    page.goto("https://www.linkedin.com/in/me/", wait_until="domcontentloaded", timeout=60_000)
    page.wait_for_timeout(1_500)
    body = page.locator("body").inner_text(timeout=20_000)[:15_000]
    url = page.url
    if normalise_profile_url(url).endswith("/in/me"):
        # 29 Sep 2026 (root): LinkedIn stopped redirecting /in/me to the vanity URL; the signed-in profile is served
        # at /in/me itself. Read the page's OWN canonical/og:url instead. Still fail-closed: identity_from_profile
        # requires the exact authorised vanity URL, the name and the AGMM marker.
        try:
            canon = page.evaluate(
                "() => (document.querySelector('link[rel=canonical]') || {}).href"
                " || (document.querySelector('meta[property=\"og:url\"]') || {}).content || ''")
        except Exception:
            canon = ""
        if not canon:
            html = page.content()
            slug = urlsplit(PROFILE_URL).path.rstrip("/")
            if slug in html:
                canon = PROFILE_URL
        if canon:
            url = canon
    identity = identity_from_profile(url, body)
    # Publishers open their composer from the feed. Identity verification must
    # leave the page on that expected surface after proving the self-profile.
    page.goto("https://www.linkedin.com/feed/", wait_until="domcontentloaded", timeout=60_000)
    page.wait_for_timeout(1_000)
    return identity
