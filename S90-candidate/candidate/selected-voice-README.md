# S90 selected-voice hosted input adapter (isolated proposal)

This adapts the existing selected WAV into the current full-AV builder's input shape. It does not create a voice, alter `RESULT.json` selection, authorize a render, or grant audio/visual approval.

The native GitHub release asset is pinned to public repository `agmmltd-arch/agmm-render-public`, release `402989473` / tag `S90-selected-voice-hosted-20261004`, asset `609728994` / `S90.wav`, 2,798,068 bytes, server digest `sha256:5f8ce5a135e0b81ba0623d801bb8047cd6a729f8abc1840d4f266ad5bf05cdd1`. The corresponding local source selection is the unchanged `RESULT.json` final attempt 1 / `pass1`, with source path `/Users/samwall/alfred/builds/video-program-2026-09-23/v2/shorts/voice/S90/S90.wav` and selected take directory `.../S90/take-pass1`. Text hashes of `RESULT.json` and `S90.receipt.json` are pinned in the adapter; script and word-timing hashes remain the existing builder's locked values.

On the public Ubuntu workflow only, use this step before the existing candidate builder:

```sh
S90_HOSTED_REVIEW_BUILD=1 python3 hosted-selected-voice-adapter/prepare_selected_voice.py \
  --words-source /path/to/locked/S90.words.json \
  --output "$RUNNER_TEMP/s90-input"
```

The adapter requires `GITHUB_ACTIONS=true`, confirms repository visibility and exact release/asset IDs through `gh api`, downloads only the exact release/tag/name, verifies actual bytes against both GitHub's native digest and pinned byte count, and inspects the WAV header/frame duration on Ubuntu. It writes:

- `$RUNNER_TEMP/s90-input/voice/S90.wav`
- `$RUNNER_TEMP/s90-input/selected-voice-receipt.json`
- `$RUNNER_TEMP/s90-input/mix/mix_spec.json`
- `$RUNNER_TEMP/s90-input/mix/S90.words.json`

The mix-spec candidate keeps all 19 existing cue IDs and the 58.3-second/1749-frame proposal, replaces the unresolved voice path with the stable sibling path, and binds the actual release/asset IDs and digest. Its exact template SHA-256 is `1d84bcc021147ea2e05634935982fe22e8224bed70c1d151ed536d1c6b0fe729`; the adapter copies it byte-for-byte so storyboard approval can bind a stable mix-spec hash. It remains `UNAPPROVED_NOT_RENDERABLE`; `approval.render_authorized` and `approval.release_authorized` remain false. Stage the already-reviewed mixer bundle under `$RUNNER_TEMP/s90-input/mixer/v2` and its `library.json` at `$RUNNER_TEMP/s90-input/mixer/library.json` before the existing builder. The builder's mix validator now checks the pinned library text hash when the candidate supplies it.

The existing `build_s90_hosted_review_candidate.py` independently rechecks the WAV's size, SHA-256, PCM properties, frame count and actual duration after the adapter. The adapter output SHA is then passed to its required `--expected-voice-sha256`; its `--voice`, `--voice-receipt`, and `--mix-spec` arguments use the paths above. The output of that existing builder is still only `HOSTED_FULL_AV_REVIEW_CANDIDATE_NOT_APPROVED`.

## Remaining review input

The existing builder deliberately refuses until the canonical S90 spec tree and independent storyboard approval exist. That approval must bind the locked script SHA `a8006145cc4610be0abfd70f6e8355e6f6f64780064afe7a7834b49f33360055`, word SHA `a6d08fbb84c55f406457751213df0094561e55de1e1824faf66cd760845f3925`, exact current scene SHA `5e623b801272b1e5439cf4191ec6038a2a1787c3df455500b4f1fa39221a2290`, exact spec-delta SHA, current canonical spec hash, this final mix-spec hash, and the exact duration/frame grid. The reviewer must judge the complete current 32-frame source composition, including B16's actual text/CTA geometry and the preserved non-confirmed callback/payment-held claim. Any final CTA hold beyond the final beat end must be explicit in the approval. A rendered candidate still needs independent frame/motion/caption review and full audio listening; asset identity or successful mixing is not craft approval.

## Checks

`test_prepare_selected_voice.py` checks the current text-only source pins, public release/asset metadata guards, duplicate-name refusal, unchanged 19 cue IDs and unapproved mix state. `test_s90_hosted_review_builder.py` covers the existing builder's refusal/hash contracts and text-level mixer integration. Neither test downloads or reads the hosted WAV.
