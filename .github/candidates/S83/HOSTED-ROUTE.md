# Guarded S83 source and review route

**Observed public parent:** `agmmltd-arch/agmm-render-public` `main` at `5499b45d278c6a0908a81558352ceec49afd7973`, observed 2026-10-04. Root must recheck and rebind immediately before publication.

## Source capture and bounded review artifact

1. Root reviews the candidate and workflow diff, then runs the publisher in read-only mode. Publication requires the exact public repository, parent SHA, four helper preimages, candidate hashes and absent targets. The publisher installs one identical workflow blob both in the candidate directory and at `.github/workflows/s83-source-capture.yml`; publication itself does not dispatch Actions.
2. The workflow is manual-only on `main`. It checks the exact direct parent with `fetch-depth: 2`, verifies public repository identity and candidate/helper receipts, then runs URL, logo-identity and artifact-guard tests before visiting a source. A preflight failure blocks receipt generation and artifact upload.
3. Every main-frame source navigation and redirect must carry exactly `utm_source=qa` and `utm_campaign=qa_release_audit`. Only those two keys are removed for runtime canonical identity comparison; protocol, source-specific host allowlist, path, hash and all other query bindings must remain exact. Credential-bearing URLs and nondefault HTTPS ports are refused at navigation and mark-image binding. The three HTTPS sources are the named Walsall Trust article, RWT homepage and BBC report.
4. Trust logo capture requires one visible `header img` whose accessible alt/title/aria label or linked brand label identifies the Trust. `src` and `currentSrc` are recorded but never count as identity evidence. Public receipt URLs retain only protocol, host, path and exact QA parameters when present; other query values and fragments are stripped. Receipt text/errors are capped at 512 characters. If source text or brand identity fails, the failure receipt does not qualify for logo copying or still capture.
5. After verified source capture, only the two logo PNGs enter the temporary composition. HyperFrames 0.8.71 runs `check` and samples the frozen 37 timestamps into runner temp. The receipt builder and artifact guard enforce exact failure/full packets and SHA256 bindings. A valid packet uploads through pinned `actions/upload-artifact` with one-day retention. No Git branch or raw Git asset is created.

## Material access limit

`agmmltd-arch/agmm-render-public` is public. GitHub's [artifact REST documentation](https://docs.github.com/en/rest/actions/artifacts) says public resources can be accessed without authentication. The one-day artifact is temporary but not an authenticated/private boundary; its images may be publicly retrievable during that day. Raw logo rights and public-review-copy permission remain `NOT_ASSESSED`. See `RIGHTS-EVIDENCE.md`; it records guidance, not permission. Root must account for the access window before dispatch.

## Review limits

The artifact supports source/visual review only. It does not grant logo rights, editorial, audio, render or release approval, or platform acceptance. No local programme media is processed. The 42 px meaningful-text floor and 46 px captions remain; this correction changes capture safeguards only.


## Protected S83 media and public runner boundary

`PROTECTED-INPUTS.json` binds the 18 original release assets to the root-staged private Git tree at `04b48f467025d86ffcdb54d933717682b0e84903`, including exact native Git blob IDs. The combined manual workflow first verifies the published public candidate and five public runtime blob IDs, then checks out only the allowlisted private tree through the existing `AGMM_SFX_READ_DEPLOY_KEY` in one `actions/checkout` step. It verifies commit, paths, regular-file status, native blob IDs, byte sizes, and release SHA256 values on a GitHub-hosted Ubuntu runner before installing the mixer or processing media.

The hosted run binds S83 PCM format, duration and word-clock data; runs the pinned sound runtime; and captures the existing 37-still source review packet. It uploads only four sanitized text receipts plus the bounded source stills and marks. The master, stems, protected input checkout and temporary input copies are deleted before upload. The receipts state that audio review was not performed, rights are `NOT_ASSESSED`, and approval is not granted. Root publication and a new hosted run remain outstanding. Independent visual review remains outstanding. The full mix is currently deleted before durable export. Sam has separately authorized public, durable in-review content previews; root has identified the existing native preview exporter as the permitted public release route. Integration into the S83 run remains OPEN. Upload only the single mixed master and sanitized receipts through that tagged preview release route, with `NOT_REVIEWED` labels and all approval gates open; keep raw voice and stems private. The one-day Actions artifact remains audio-free. Do not regenerate a successfully exported mix just to recreate its review copy.

Any public Actions artifact is retrievable according to the public repository's artifact permissions during its one-day retention. The packet retains the existing access-limit disclosure and does not claim a private boundary. Raw Trust marks and public-review-copy permission remain `NOT_ASSESSED`; see `RIGHTS-EVIDENCE.md`.


## Separate OPEN task: durable in-review mix preview

Sam explicitly authorized public durable content previews, including in-review/held previews. The authorization receipt is `/Users/samwall/alfred/builds/video-autonomy-2026-10-02/S90-durable-review-export-luna/ROOT-PUBLIC-PREVIEW-AUTHORIZATION.json`; it does not authorize editorial approval, Ready, arming, social posting, or release approval. Root identified the already-authorized native preview exporter as the S83 full-mix route. The existing public repository route needs no new key.

The current S83 workflow still deletes its master before durable export. Root owns integrating the exact in-run master with the existing exporter and verifying one tagged preview release asset against the source SHA256/size. Include `NOT_REVIEWED` labeling, audio/AV review `OPEN`, Ready `NOT_GRANTED`, and release approval `NOT_GRANTED`. Publish only the mixed master and sanitized receipts via the preview release; raw voice and stems stay private. The Actions artifact remains limited to source captures/stills and text receipts. See `MIX-REVIEW-ROUTE.md`.
