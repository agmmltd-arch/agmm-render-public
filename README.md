# AGMM render (public)

Public on purpose: GitHub Actions minutes are free for public repositories. This repo holds ONLY render workflows and the
sealed film packages they render (film source that will be published on YouTube anyway). No keys, no secrets, no archives,
no business data: never commit anything else here. Private archives stay in agmmltd-arch/agmm-video-render.

Workflows:
- agmm-render-template.yml: the proven HyperFrames render job (composition matrix, artifacts), the template for
- agmm-film-4k.yml (to build): one matrix job per film segment at landscape-4k, same package/SEG edit/verify as
  v2/films/tools/render_codespace_film.py, artifacts SEGnn.mp4 per segment.
