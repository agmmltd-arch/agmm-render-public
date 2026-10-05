# Guarded S83 source capture and developmental review route

**Current public main observed from native GitHub API:** `agmmltd-arch/agmm-render-public` `main` at `cd9aa32a6c219f356ec54da61858c294f5e76a9c`, commit date `2026-10-04T21:59:21Z`. All nine runtime/helper Git blob pins in `PARENT-IDENTITY.json` matched this exact tree. Root must recheck and bind the immediate parent again at publication.

## Source-only phase precedes protected inputs

The manual workflow validates the exact root-published public head and candidate manifest, verifies pinned source/runtime code and source tests, then captures the current source text and identified Trust marks. HyperFrames 0.8.71 browser check and the 37 frozen snapshots execute before private checkout, word-clock verification, or mix. The check wrapper writes parseable check JSON and a separate bounded/sanitized stdout/stderr/exit diagnostic even when HyperFrames fails. Snapshot attempts retain the same capped diagnostic receipt. The one-day packet is sealed after the source step and uploaded; if the source step was never reached, the packet/upload steps stay skipped.

The one-day Actions artifact contains only review captures and sanitized receipts. A success-only publisher creates a unique run-scoped public source-review branch containing exactly 37 canonical PNG stills and text receipts. Standalone source marks, source audio, WAVs, stems, video, and archives are excluded. Review access is public; the receipts keep rights `NOT_ASSESSED` and approvals open.

`produce_development_preview` defaults to `false`: the first workflow run is source-only and finishes with the 37 stills/receipts without checking out protected audio or mixing/rendering. It seals a normalized digest over the exact sorted PNG names and bytes, independent of run metadata, plus the candidate-manifest SHA256 and public source commit. A later preview run requires all three values from the independent review receipt (`reviewed_source_frames_sha256`, `reviewed_source_manifest_sha256`, `reviewed_source_public_head_sha`); the runner recomputes and compares them before the protected checkout. Any missing/extra/changed frame, candidate or commit mismatch stops before private media work. Root must review all 37 frames and record the three bound values before enabling the preview input. The durable orphan branch starts with `git read-tree --empty` so only the explicit review packet enters its tree; a synthetic Git regression verifies the staged and committed inventories.

Source navigation keeps the exact QA tags `utm_source=qa` and `utm_campaign=qa_release_audit`; credential-bearing URLs and nondefault HTTPS ports are refused. Source host/path/hash and mark identity checks remain unchanged.

## Ubuntu production phase

Only after the exact reviewed-source-frame binding succeeds, the workflow checks out the allowlisted private Git tree at `04b48f467025d86ffcdb54d933717682b0e84903` using the existing read-only deploy key in a single checkout step. It verifies commit, paths, regular-file status, native Git blob IDs, sizes and release SHA256 for all 18 inputs before processing. It then checks the source PCM clock, renders/mixes on GitHub-hosted `ubuntu-24.04`, renders the single 1080 picture with pinned HyperFrames 0.8.71, and muxes through the exact published renderer blob `754099346a84c5bd305f5684ef24399a53bd9697`. `MIX-QUALITY-RECEIPT.json` must match the exact WAV SHA256 and full byte count; the export binds that receipt hash while keeping audio review open.

A run-tagged draft prerelease is created only after the sealed master and sanitized receipts bind exact source, runtime, mix and private-input verification hashes. The route verifies the exact draft asset inventory, each GitHub SHA256 digest, byte size, URL, and tag-to-head binding before making the preview public. It releases one mixed MP4 plus three text files. Raw voice, each individual stem, and the WAV master remain private and are removed from runner storage after verification.

## Status and limits

The route is implemented only in the isolated candidate. It has not been published, dispatched, or executed; no S83 media output is created or approved by these local checks. The latest native source capture passed, but its HyperFrames check failure is unrecoverable from the deleted prior-run diagnostics. The new candidate saves exact bounded diagnostics before any protected media is checked out or mixed.

A public Actions artifact is retrievable according to the public repository's artifact permissions during its one-day retention; it is not an authenticated/private boundary. Public source-review and preview material remains unreviewed. Full continuous visual/audio review, factual/craft, rights assessment, Ready, and release approval remain open. The route uses no local programme-media processing.
