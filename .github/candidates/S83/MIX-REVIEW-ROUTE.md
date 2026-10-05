# S83 durable developmental AV review route

## Authorization and boundary

Sam authorized durable public in-review previews, including held previews. The recorded authorization is `/Users/samwall/alfred/builds/video-autonomy-2026-10-02/S90-durable-review-export-luna/ROOT-PUBLIC-PREVIEW-AUTHORIZATION.json`. It covers preview storage only: it does not grant AV/craft approval, Ready, arming, social posting or release approval. Raw source audio and individual stems remain private.

## Candidate implementation

The isolated S83 candidate now contains a same-run Ubuntu route in `s83-source-capture.workflow.yml`. HyperFrames source check and 37 still captures run before private checkout or mixing. The bounded check wrapper retains sanitized JSON plus stderr/exit diagnostics when the browser fails; the one-day packet records them before any protected checkout. `produce_development_preview` defaults to `false`, so the first source capture ends with stills and receipts only. It emits a normalized exact-37-PNG digest bound to the candidate-manifest SHA256 and public source-head SHA, independent of run metadata. A later private-mix/render route requires all three values in an independent review receipt and compares them to the newly captured frame packet before protected checkout. Missing, extra, or changed PNGs or a changed candidate/head fail before private-media work.

Only after the source-review binding succeeds does the workflow check out and verify the exact 18 protected inputs, bind the source clock, mix on Ubuntu, render one 1080 picture, and mux it with the single mixed master using the public `render_short_package.py` helper pinned to blob `754099346a84c5bd305f5684ef24399a53bd9697`. The export helper binds source capture, reviewed-frame digest, source clock, parts and mix hashes, the exact `MIX-QUALITY-RECEIPT.json`, the 18-input verification receipt, candidate manifest, final MP4 and technical receipt. It creates a draft prerelease, verifies exact asset names, SHA256, size and source-head tag, then publishes it. Only the mixed `FINAL.mp4` and three sanitized text files can enter the release; voice, SFX, stems and standalone WAV remain private.

## Status

`IMPLEMENTED IN ISOLATED CANDIDATE; NOT PUBLISHED OR DISPATCHED`. The current native public main observed for rebinding is `cd9aa32a6c219f356ec54da61858c294f5e76a9c`; all nine public/helper runtime blobs in the candidate's parent receipt matched that tree. Root owns final review, guarded publication and any Actions dispatch.

No S83 render, mix result, or new source capture is established by this local work. The latest native run `37233648257` passed source-text/logo capture but failed at the browser check; GitHub cleanup destroyed its diagnostics, so the exact exception is unrecoverable. The candidate's next run will retain bounded diagnostics before any protected checkout or mix.

Technical checks and a durable preview do not establish subjective quality. Full continuous AV, source/craft, rights, and independent-review gates remain open; status must remain `NOT_REVIEWED`, `OPEN`, and `NOT_GRANTED` until the proper reviewer acts.
