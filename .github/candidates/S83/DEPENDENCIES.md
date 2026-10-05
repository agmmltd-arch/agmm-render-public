# S83 hosted workflow dependency manifest

Workflow: `.github/workflows/s83-source-capture.yml` (manual `workflow_dispatch`; no S83 dispatch has occurred).

## Published candidate files used at runtime

All are included under `.github/candidates/S83/`, listed in `CANDIDATE-MANIFEST.json` and verified by both hash receipts:

- `index.html`, `source_capture.mjs`, `source_url_guard.mjs`
- `hosted_receipt.py`, `guard_review_artifact.py`, `capture_hyperframes_diagnostic.py`
- `prepare_s83_review_export.py`, `publish_s83_review_release.py`
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

- Ubuntu 24.04 GitHub-hosted runner; Node 22.23.1 (asserted exactly); checkout fetch-depth 2 with exact `HEAD == GITHUB_SHA` and `GITHUB_SHA^ == S83_PARENT` guards.
- `actions/checkout@11bd71901bbe5b1630ceea73d27597364c9af683`.
- `actions/setup-node@49933ea5288caeca8642d1e84afbd3f7d6820020`.
- `actions/upload-artifact@ea165f8d65b6e75b540449e92b4886f43607fa02`, one-day retention, `if-no-files-found: error`.
- Playwright 1.55.1 with Chromium installed by the workflow.
- HyperFrames 0.8.71: an early `lint --json` static contract check runs before protected inputs are checked or processed; the later hosted `check` and 37 still captures run only after source/mix gates. `check` includes browser/layout work and is never represented by local lint.
- GSAP 3.14.2 is vendored at `assets/gsap.min.js` from the existing installed `gsap` package; SHA256 `c174bfce53a729418d57a8ad8625e7247c793a22fef8e2851e3cfa3de9cd8280`, Git blob `fde57af06cc445f47ca2a6fc1232ec04666346d4`. The original license header is retained. The inline composition checks `window.gsap.timeline`, initializes `window.__timelines` to an object when absent (matching HyperFrames 0.8.71 runtime lazy initialization), and type-checks it before creating/registering the paused `s83` timeline. The exact package/source/license binding is in `CANDIDATE-MANIFEST.json`.
- Node built-in test runner for URL/identity negatives; Python standard-library unittest for packet guard negatives.

A setup step writes the S83 temporary paths to `$GITHUB_ENV` from the real runner context. Candidate/head/runtime checks and static tests run first. Source text/logo capture, HyperFrames 0.8.71 browser check and 37 snapshots then run before any protected checkout or mix. The bounded check wrapper preserves JSON plus sanitized diagnostics even on failure; the source packet uploads under `if: always()`, then an explicit guard prevents private media work unless every source step succeeds.

Every main-frame request and final page URL must carry exactly `utm_source=qa` and `utm_campaign=qa_release_audit`. Only those two query keys are excluded from canonical identity comparison. Redirect protocol, host allowlist, path and all other query bindings remain guarded. Navigation and mark-image URLs reject credentials and nondefault HTTPS ports. Public receipt URLs retain only HTTPS host/path plus the exact QA parameters when present; other query values and fragments are stripped. Receipt text and errors are capped at 512 characters. Logo identity requires accessible `alt`, `title`, or `aria-label` evidence inside the official page header; image `src`/`currentSrc` is never used as brand proof.

The workflow uploads an exact one-day source/check packet and, only on a complete 37-still success, creates a unique public run-scoped review branch containing PNG captures and sanitized text receipts, including a frame-only digest bound to the exact candidate manifest and public commit. It excludes standalone marks, media, audio and archives. The public branch/artifact remain review-only; rights and approval are not inferred. `produce_development_preview` defaults false; protected checkout/mix/render requires the explicit three-field independent review receipt and exact new 37-frame match. The mixed export helper also requires `MIX-QUALITY-RECEIPT.json` to match the private WAV SHA256 and full byte count. It releases a single mixed MP4 plus three sanitized text assets only after exact draft-release inventory verification. Raw voice, stems and WAV master remain private. See `HOSTED-ROUTE.md` and `MIX-REVIEW-ROUTE.md`.

## Source-clock and mix package additions

`SOURCE-BINDING.json` and `SOURCE-CLOCK.json` freeze the current text receipts and expose known tokenization/timing discrepancies. `validate_s83_source_clock.py` computes a current WAV SHA256 and PCM duration only when run on the authorized Ubuntu runner; it does not repair timings or certify listening. Synthetic fixtures are covered by `test_validate_s83_source_clock.py`.

`MIX-RUNTIME-DEPENDENCIES.json` pins the five exact public runtime Git blobs at observed public main `cd9aa32a6c219f356ec54da61858c294f5e76a9c`; all nine helper/runtime paths were rechecked against this exact tree; root rebinds immediately before publication. `PROTECTED-INPUTS.json` binds all 18 immutable release assets by asset ID, name, size, release SHA256, private Git path and exact native Git blob at private commit `04b48f467025d86ffcdb54d933717682b0e84903`. The hosted workflow uses the existing read-only SSH deploy key in one checkout step and verifies every private blob, size and release digest on Ubuntu before media processing. Hosted SHA256 verification remains pending the next source-gated Ubuntu run.
