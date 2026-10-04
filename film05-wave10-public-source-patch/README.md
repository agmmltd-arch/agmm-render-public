# Film05 Wave10 source patch (text only)

Overlay `index.html` onto the exact Wave08 project extracted from the private input repository on the Ubuntu runner. This patch intentionally excludes all image, audio and video binaries. It contains ten text-only files: authored HTML/CSS/GSAP source, continuity notes, preimage gate, source manifest, asset ledger and text-only checks. The private Wave08 project remains the source of its existing synthetic still assets. The two Pexels MP4s are acquired only on the Ubuntu runner from the exact URLs and verified against the exact hosted screen-run hashes in `SOURCE-MANIFEST.json`.

Expected private input: `agmmltd-arch/agmm-video-render`, commit `1899af7ed53fd2f6e432966150b9db1b56ef74b0`, archive `video-program/longform/film05-wave08-first-act/source.tar.gz`, SHA-256 `8bdbf047f74a6ce0de4d860df5174ca765ebc49da44f300e38910a500323461f`.

This patch is not a release-ready source package. Root integration must include a reviewed public-main commit SHA in the workflow_dispatch input, must guard repository visibility and main ref, and must check out only the exact private source commit using the repository's existing read-only key.
