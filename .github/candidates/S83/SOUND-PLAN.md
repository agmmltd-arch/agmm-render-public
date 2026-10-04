# S83 sound plan

## Intent

Keep the piece dry and legible, like a carefully handled evidence file. BGM was considered and no bed selected. The six short voice paragraphs carry the argument; paper, pencil and restrained interface cues mark changes in evidence state. No room tone, clinic ambience, keyboard typing or simulated consultation audio is used. This avoids suggesting that a real patient encounter or Walsall system was recorded.

## Cue edit

The executable cue list is in `MIX-SPEC.json`: 17 cues across 56.523 s (18.05 cues/minute), all marked non-designed hits at −18 dB except the opening metric impact at −20 dB. The library metadata names Sonniss GDC bundle licensing for the selected IDs; catalog metadata is not file presence or file-level rights evidence. The selected source audio is staged in the private Git tree; it has not been auditioned. This proposal binds each cue to its actual source-layout object and animation event start; see `MIX-CUE-PAN-MAP.json`.

| Time | Cue | Picture event | Gain |
|---:|---|---|---:|
| 0.000 | `foley_click_02` | Walsall identity card settles | −18 dB |
| 0.280 | `impact_soft_09` | Metric value begins its left-origin expansion | −20 dB |
| 7.815 | `foley_click_04` | Illustrative phone card enters | −18 dB |
| 8.200 | `foley_paper_03` | Trust statement card enters | −18 dB |
| 13.674 | `foley_paper_02` | Review pencil begins | −18 dB |
| 14.582 | `foley_paper_05` | Edit pencil pass | −18 dB |
| 15.894 | `foley_stamp_01` | Approval endpoint | −18 dB |
| 18.619 | `paper_page_06` | Clinician evidence card | −18 dB |
| 23.600 | `foley_paper_08` | Route line draws | −18 dB |
| 23.750 | `foley_click_01` | Walsall mark lands | −18 dB |
| 23.990 | `foley_click_06` | Royal Wolverhampton mark lands | −18 dB |
| 28.457 | `paper_page_07` | BBC clarification card | −18 dB |
| 34.533 | `paper_page_08` | Evidence sheet turns | −18 dB |
| 40.150 | `foley_stamp_03` | Not-published status lands in the right evidence column | −18 dB |
| 44.901 | `foley_paper_09` | Worksheet lands | −18 dB |
| 50.935 | `paper_page_10` | CTA sheet enters | −18 dB |
| 53.400 | `foley_click_05` | Drawn underline finishes | −18 dB |

## Hosted mix checks required

1. The prepared public Ubuntu workflow checks out the exact root-pinned private Git tree and verifies all 18 Git blob IDs, bytes, and release SHA256 values before any media processing. It also verifies the pinned public sound library and candidate word JSON. Its text receipt is technical evidence only.
2. Run the approved `mix2.py` against `MIX-SPEC.json`; preserve its complete command, version/source hash and JSON result.
3. Audition every cue against the narration. Keep `protect_words` enabled; ensure any cue within 150 ms of a stressed word is at least 10 dB below that word. Remove or move any masking cue and revise the spec before mixing.
4. Confirm actual integrated loudness −14 LUFS and true peak no higher than −1 dBTP from the final mix receipt; these are targets, not current results.
5. Bind the resulting mix to the 56.523 s voice receipt and 56.533333 s visual hold. Ears review and sync review stay open.

No audio was opened, copied, processed, hashed, rendered or heard on this Mac. The hosted route is prepared but has not been published or run. SFX audition, voice review, mix review, AV sync review, rights assessment, and release approval remain open.


## Position-bound cue pan proposal

The mixer reads `pan` in each cue, clamps it to `audio_rules.json` `pan_max` (0.7), and applies constant-power stereo panning. The proposal derives signed `pan` from the transformed element-box centre at cue onset, except drawing cues which use their moving/drawing start point: `clamp(0.7 * (2 * x / 1080 - 1), -0.7, 0.7)`. Off-canvas entry positions clamp to the mixer's bounds. Values are source-CSS/tween derivations, not observed final audio; review the corresponding hosted stills, listen, and inspect word-masking clamps before acceptance.

| Time | Cue | Bound visible event | Pan |
|---:|---|---|---:|
| 0.000 | `foley_click_02` | Walsall identity card enters from the left | -0.70 |
| 0.280 | `impact_soft_09` | Metric value begins at transformed centre x=366.44 during left-origin scale | −0.22 |
| 7.815 | `foley_click_04` | Illustrative phone silhouette enters from the left | -0.64 |
| 8.200 | `foley_paper_03` | Trust statement card enters from the right | +0.68 |
| 13.674 | `foley_paper_02` | REVIEWED step appears at left; pencil appears on it | -0.42 |
| 14.582 | `foley_paper_05` | EDITED IF NEEDED step appears; pencil starts its pass from the left | -0.42 |
| 15.894 | `foley_stamp_01` | APPROVED step appears at right | +0.44 |
| 18.619 | `paper_page_06` | Clinician evidence card enters from the left | -0.54 |
| 23.600 | `foley_paper_08` | Route line drawing begins at its left endpoint (point anchor) | -0.43 |
| 23.750 | `foley_click_01` | Walsall mark lands in the left Trust card | -0.32 |
| 23.990 | `foley_click_06` | Royal Wolverhampton mark lands in the right Trust card | +0.32 |
| 28.457 | `paper_page_07` | BBC clarification sheet enters at centre | +0.00 |
| 34.533 | `paper_page_08` | Evidence sheet turns around centre | +0.00 |
| 40.150 | `foley_stamp_03` | Not-published state appears in right evidence column, centre x=772 | +0.30 |
| 44.901 | `foley_paper_09` | Worksheet enters from the left | -0.26 |
| 50.935 | `paper_page_10` | Follow card rises at centre | +0.01 |
| 53.400 | `foley_click_05` | Underline stroke begins at its left edge (point anchor) | -0.44 |
