# AGMM render (public)

Public on purpose: GitHub Actions minutes are free for public repositories. This repo holds ONLY render workflows and the
sealed film packages they render (film source that will be published on YouTube anyway). No keys, no secrets, no archives,
no business data: never commit anything else here. Private archives stay in agmmltd-arch/agmm-video-render.

Workflows:
- agmm-render-template.yml: the proven HyperFrames render job (composition matrix, artifacts), the template for
- agmm-film-4k.yml (to build): one matrix job per film segment at landscape-4k, same package/SEG edit/verify as
  v2/films/tools/render_codespace_film.py, artifacts SEGnn.mp4 per segment.
- patch-hosted-master.yml: reusable hosted-master repair. It takes the complete segment manifest and a JSON patch list
  in the form `[{"i":"01","run_id":123456789,"tag":"exact-artifact-prefix"}]`. The workflow accepts only numeric
  run IDs, safe exact tags and unique in-range segment IDs. A completed failed base run is accepted because the selected
  segment set is proved artifact by artifact; every replacement run must have succeeded. The workflow verifies the exact
  repository, run commit, GitHub artifact archive digest and member set, chooses one artifact for each manifest segment,
  and extracts the sealed `audio/mix.flac` (or `./audio/mix.flac`) from an exact release asset digest. It applies the
  established -0.5 dB mix adjustment, fully decodes the 4K and 1080 outputs, runs the full-duration static/audio audit
  and native Vision OCR, and emits SHA256-bound provenance and gate receipts. Editorial review and release approval
  remain outstanding.
- agmm-short-package.yml: reusable exact-release short render. It hash-verifies fixed `source.tar.gz`, `parts.json`
  and `mix.wav` release assets; renders all declared parts at 1080 and optional native portrait 4K; assembles and fully
  decodes/probes/frame-counts the masters; checks 48 kHz stereo loudness/true peak; and emits compact seam and quarter
  stills. Assembly caps picture to the declared full-timeline frame count before validating it against the duration's
  allowed counts; it does not use FFmpeg `-shortest`, which can discard reordered H.264 packets before exact-length AAC.
  It is technical evidence only, with no approval, arming, scheduling or publication step.
- agmm-short-assemble-retry.yml: assembly-only recovery from a completed failed `agmm-short-package.yml` run whose
  preflight and every render job succeeded. It checks out current `main`, binds the declared release and three hashes to
  the retained exact-input receipt, verifies the source run/head/workflow/jobs and the complete unexpired artifact set,
  then downloads those artifacts by exact source run ID. It reuses no local media and leaves editorial status
  `NOT_REVIEWED` and publication status `NOT_REQUESTED`.

The short workflow uses public `ubuntu-24.04` runners for every media operation. Master artifacts expire after one
day and compact evidence after three days. The caller only needs the three exact hashes and does not need to download,
render or decode video on its own computer.

Example invocation after uploading the reviewed, sealed assets to one release:

```sh
gh workflow run agmm-short-package.yml -R agmmltd-arch/agmm-render-public --ref main \
  -f release=SHORT-RELEASE-TAG \
  -f source_sha256=SOURCE_TAR_SHA256 \
  -f parts_sha256=PARTS_JSON_SHA256 \
  -f mix_sha256=MIX_WAV_SHA256 \
  -f tag=SHORT-ID-ROUND -f render_4k=true -f workers=2
```

If that run fails only during assembly after all part artifacts were retained, retry assembly without re-rendering:

```sh
gh workflow run agmm-short-assemble-retry.yml -R agmmltd-arch/agmm-render-public --ref main \
  -f source_run_id=SOURCE_RUN_ID -f source_head_sha=SOURCE_RUN_HEAD_SHA \
  -f release=SHORT-RELEASE-TAG -f tag=SHORT-ID-ROUND \
  -f source_sha256=SOURCE_TAR_SHA256 -f parts_sha256=PARTS_JSON_SHA256 \
  -f mix_sha256=MIX_WAV_SHA256 -f render_4k=true
```
