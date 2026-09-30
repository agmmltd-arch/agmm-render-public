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
- agmm-short-capture.yml: capture-only hosted review evidence for a sealed short package. It verifies exact
  `source.tar.gz`, `parts.json` and `capture-plan.json` release assets; safely extracts the archive; verifies every
  per-look checksum; binds the canonical image/audio/video media identity digest; checks every named global/local
  timestamp; automatically adds `-0.04/+0.02/+0.06s` frames around every part seam; and runs the exact
  `hyperframes@0.8.71 snapshot --at ... --no-end` route. It uploads one compact artifact containing native portrait
  PNGs and receipts. It does not render or decode a full video, and its editorial status is always `NOT_REVIEWED`.

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

## Exact hosted capture route

The release named in `release` must contain exactly these capture inputs under these names:

- `source.tar.gz`
- `parts.json`
- `capture-plan.json`

`capture-plan.json` names the editorial beat and transition frames in global and part-local time. The helper refuses a
wrong global/local mapping and adds every part seam itself. The media digest is derived from all image, audio and video
rows authenticated by the sealed package's per-look `SHA256SUMS.txt` files, so changing any declared media file changes
the required dispatch identity.

The prepared S40 and S56 dispatch contracts are:

| Short | Capture plan | source SHA256 | parts SHA256 | media identity SHA256 | capture-plan SHA256 | Frames |
|---|---|---|---|---|---|---:|
| S40 | `.github/capture-plans/S40.json` | `b37866945acd809f5d537b6634665f3c379581f9316442f64211482757a4cb5b` | `3337a58f83becdbdcf4c6118e2b9e6d61acddad06778a5e59fdd8c5df83689c0` | `036c26697d4fdff7553b44c0be27cbc4d0df74d270663a41d4bfb073919493e9` | `8fd94902df5f51f3b92430a1d47228de8d57c7185c6ab918327e73931a875b0e` | 15 |
| S56 | `.github/capture-plans/S56.json` | `c4544eb9b267625c0c01d7948e2d4d0cb8e5ff0c6cb5f1fd31bceffc48c47424` | `b28bb4571d50cdd4decfdf9431e809fb0fd610f32d2443573d34fac225c1a417` | `195cab94ef9b76cdc3c3fbb6e84e13d8c4fe610b32e8a1e4372eb30ad6ac98da` | `d672ec0fb41910c67d5436c0aed5c54d34798282dff5653f072180cc71673b61` | 17 |

S40 captures the repaired `pattern` transition at global `37.48/37.54/37.58s`, then the required review frames at
`38.05/39.05/40.05s` (part C local `9.85/10.85/11.85s`). S56 captures both sides of the Alphabet beat, its standard
midpoint at `8.44s`, and the required Alphabet review frame at global/local `8.658s`. Both plans add all A/B/C/D part
seams automatically.

After the workflow commit is on the selected ref and an exact three-asset release exists, dispatch S40 with:

```sh
gh workflow run agmm-short-capture.yml -R agmmltd-arch/agmm-render-public --ref main \
  -f release=S40-r6-capture-source -f tag=S40-r6-capture \
  -f source_sha256=b37866945acd809f5d537b6634665f3c379581f9316442f64211482757a4cb5b \
  -f parts_sha256=3337a58f83becdbdcf4c6118e2b9e6d61acddad06778a5e59fdd8c5df83689c0 \
  -f capture_plan_sha256=8fd94902df5f51f3b92430a1d47228de8d57c7185c6ab918327e73931a875b0e \
  -f media_identity_sha256=036c26697d4fdff7553b44c0be27cbc4d0df74d270663a41d4bfb073919493e9
```

Dispatch S56 with:

```sh
gh workflow run agmm-short-capture.yml -R agmmltd-arch/agmm-render-public --ref main \
  -f release=S56-brand-capture-source -f tag=S56-brand-capture \
  -f source_sha256=c4544eb9b267625c0c01d7948e2d4d0cb8e5ff0c6cb5f1fd31bceffc48c47424 \
  -f parts_sha256=b28bb4571d50cdd4decfdf9431e809fb0fd610f32d2443573d34fac225c1a417 \
  -f capture_plan_sha256=d672ec0fb41910c67d5436c0aed5c54d34798282dff5653f072180cc71673b61 \
  -f media_identity_sha256=195cab94ef9b76cdc3c3fbb6e84e13d8c4fe610b32e8a1e4372eb30ad6ac98da
```

Those release names are the intended exact inputs; this repository change does not create either release or dispatch a
workflow. A successful capture pack is technical evidence only. A reviewer must still inspect the native PNGs and make
the separate editorial decision.
