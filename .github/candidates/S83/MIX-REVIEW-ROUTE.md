# OPEN conditional task: durable in-review mix preview

## Authorization and route

Sam has explicitly authorized public, durable in-review content previews, including held previews. The recorded authorization is `/Users/samwall/alfred/builds/video-autonomy-2026-10-02/S90-durable-review-export-luna/ROOT-PUBLIC-PREVIEW-AUTHORIZATION.json`; it covers preview storage and sharing only, not AV/craft approval, Ready, arming, social posting, or publication approval. Root has identified the native durable preview exporter as the approved route for an S83 mixed programme review master. No new key is required for the public repository route.

The route is a unique, tagged public GitHub preview prerelease with a sanitized checksum/technical receipt. Mark the master and prerelease notes `NOT_REVIEWED` / in-review; state that audio and AV review remain OPEN, Ready is NOT_GRANTED, and release approval is NOT_GRANTED. Public preview storage does not confer any review or publication approval. Keep raw S83 voice and every individual stem private; export only the single mixed master and safe text receipts.

## Current implementation state

The S83 candidate renders `master.wav` on public Ubuntu but currently deletes it before any durable preview release is created. Root publisher/preview-export integration is an OPEN separate conditional task. Root owns this integration with the existing native exporter and current publication workflow; do not duplicate root publisher work. Bind the exact in-run master SHA256, byte length, source input/spec/runtime identities, preview tag/release, and exported asset identity in one sanitized receipt. Verify the released asset metadata/hash against the source master before making the reviewer handoff. Do not rerender after a successful transfer simply to recover a review copy.

The existing one-day Actions artifact remains limited to bounded source captures/stills and four sanitized text receipts. It must not include the master, raw inputs, or stems.

## Status

`OPEN — DURABLE PREVIEW EXPORT NOT YET INTEGRATED INTO S83 HOSTED RUN`. Public preview storage is authorized within the scope above; the remaining work is to bind the exact S83 render to the existing preview exporter and verify the uploaded asset.
