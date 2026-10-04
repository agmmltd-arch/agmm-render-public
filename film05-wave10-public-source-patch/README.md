# Film05 Wave10 source patch (text only)

Overlay `index.html` onto the exact Wave08 project extracted from the private input repository on the Ubuntu runner. This patch intentionally excludes all image, audio and video binaries. It contains ten text-only files: authored HTML/CSS/GSAP source, continuity notes, preimage gate, source manifest, asset ledger and text-only checks. The private Wave08 project remains the source of its existing synthetic still assets. The two Pexels MP4s are acquired only on the Ubuntu runner from the exact URLs and verified against the exact hosted screen-run hashes in `SOURCE-MANIFEST.json`.

Expected private input: `agmmltd-arch/agmm-video-render`, commit `1899af7ed53fd2f6e432966150b9db1b56ef74b0`, archive `video-program/longform/film05-wave08-first-act/source.tar.gz`, SHA-256 `8bdbf047f74a6ce0de4d860df5174ca765ebc49da44f300e38910a500323461f`.

This patch is not a release-ready source package. Root integration must include a reviewed public-main commit SHA in the workflow_dispatch input, must guard repository visibility and main ref, and must check out only the exact private source commit using the repository's existing read-only key.


## Corrective lineage

Hosted diagnostic run `37212155745` at public head `ecdd898910b725c326472f3b5adc6ca98f51a138` ran HyperFrames `0.8.62 check --json`. The overall check failed with 17 layout errors (`text_occluded`): the full-frame `#operations-disclosure` layer covered the operations heading and card text, including the customer proposal. `SOURCE-MANIFEST.json` records the observed selectors and sampled times.

This corrective copy resets the disclosure clip's inherited full-frame inset and confines its opaque background to a compact top-right label box in the reserved band above the operations board. It preserves the persistent illustrative-fiction disclosure and the intended task/proposal distinction. No occlusion finding is suppressed. The source-only checks below verify this geometry rule and disclosure/story content; only a fresh hosted HyperFrames check can establish layout findings, and hosted stills remain necessary to assess the actual picture. No check pass, render, AV approval, or release status is claimed here.


A follow-up native diagnostic, run `37213342359` at public head `60c50bc740c82166a2370798f41cb792d0921f3d`, confirmed the disclosure fix removed the earlier full-frame occlusion errors but found two `content_overlap` errors: the board callout covered the task-strip and customer-proposal labels. The updated source places that callout in a separate flex-flow row after the card grid. The exact findings are recorded in `SOURCE-MANIFEST.json`; this is another source correction only, pending hosted native recheck.
