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
