# S83 hosted workflow dependency manifest

Workflow: `.github/workflows/s83-source-capture.yml` (manual `workflow_dispatch`; no S83 dispatch has occurred).

## Published candidate files used at runtime

All are included under `.github/candidates/S83/`, listed in `CANDIDATE-MANIFEST.json` and verified by both hash receipts:

- `index.html`, `source_capture.mjs`, `source_url_guard.mjs`
- `hosted_receipt.py`, `guard_review_artifact.py`
- `source_url_guard.test.mjs`, `test_guard_review_artifact.py`
- `CANDIDATE-MANIFEST.json`, `CANDIDATE-MANIFEST.sha256`, `CANDIDATE-TEXT-HASHES.txt`

The same `s83-source-capture.workflow.yml` blob is present in the candidate hash list and installed at `.github/workflows/s83-source-capture.yml` by the guarded publisher.

## Existing public repository dependencies

The workflow verifies these exact `main` blobs before source access:

| Path | Blob SHA |
|---|---|
| `.github/workflows/agmm-short-capture.yml` | `3cb41404efec5fed821510b8d8717b8188221891` |
| `.github/scripts/capture_short_package.py` | `65f9b89f126c6113a91061a2f1f361954c96a0ae` |
| `.github/scripts/render_short_package.py` | `754099346a84c5bd305f5684ef24399a53bd9697` |
| `.github/workflows/agmm-short-package.yml` | `2e8c6e21409e0bdaaf80356d8b02b71bd4c5491b` |

## Pinned runner tools and actions

- Ubuntu 24.04 GitHub-hosted runner; Node 22; checkout fetch-depth 2 with exact `HEAD == GITHUB_SHA` and `GITHUB_SHA^ == S83_PARENT` guards.
- `actions/checkout@11bd71901bbe5b1630ceea73d27597364c9af683`.
- `actions/setup-node@49933ea5288caeca8642d1e84afbd3f7d6820020`.
- `actions/upload-artifact@ea165f8d65b6e75b540449e92b4886f43607fa02`, one-day retention, `if-no-files-found: error`.
- Playwright 1.55.1 with Chromium installed by the workflow.
- HyperFrames 0.8.71 for the hosted source composition check and 37 stills.
- Node built-in test runner for URL/identity negatives; Python standard-library unittest for packet guard negatives.

A dedicated step derives `S83_CAPTURE_DIR`, `S83_STILLS_DIR`, `S83_CHECK_JSON`, and `S83_REVIEW_DIR` from shell `$RUNNER_TEMP`, then writes them to `$GITHUB_ENV`. The workflow's receipt and output guard are gated on successful `steps.verify`; it emits no failure artifact after a repository, ref, helper or hash preflight failure.

Every main-frame request and final page URL must carry exactly `utm_source=qa` and `utm_campaign=qa_release_audit`. Only those two query keys are excluded from canonical identity comparison. Redirect protocol, host allowlist, path and all other query bindings remain guarded. Navigation and mark-image URLs reject credentials and nondefault HTTPS ports. Public receipt URLs retain only HTTPS host/path plus the exact QA parameters when present; other query values and fragments are stripped. Receipt text and errors are capped at 512 characters. Logo identity requires accessible `alt`, `title`, or `aria-label` evidence inside the official page header; image `src`/`currentSrc` is never used as brand proof.

The workflow uploads only the exact guarded receipt/mark/still packet to a one-day Actions artifact; it writes no public Git review branch. Since the repository is public, this is time-bounded but not asserted private or authenticated. See `RIGHTS-EVIDENCE.md` and the internal root review packet. `MIX-SPEC.json` is not invoked here; media staging, mixing, audition and ears review remain separate hosted gates.


## Source-clock and mix package additions

`SOURCE-BINDING.json` and `SOURCE-CLOCK.json` freeze the current text receipts and expose known tokenization/timing discrepancies. `validate_s83_source_clock.py` computes a current WAV SHA256 and PCM duration only when run on the authorized Ubuntu runner; it does not repair timings or certify listening. Synthetic fixtures are covered by `test_validate_s83_source_clock.py`.

`MIX-RUNTIME-DEPENDENCIES.json` pins the five exact public runtime Git blobs at observed public main `91f5f0e649d7381fcf7f0fbd7599c48d25085943`; root rechecks them at publication. `PROTECTED-INPUTS.json` binds all 18 immutable release assets by asset ID, name, size, release SHA256, private Git path and exact native Git blob at private commit `04b48f467025d86ffcdb54d933717682b0e84903`. The hosted workflow uses the existing read-only SSH deploy key in one checkout step and verifies every private blob, size and release digest on Ubuntu before media processing. Hosted SHA256 verification remains pending the public Actions run.
