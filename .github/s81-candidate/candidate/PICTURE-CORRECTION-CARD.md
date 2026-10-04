# S81 second picture correction

Status: isolated source draft for root review. The exact actual still set from run `37233356865` failed picture review. The opening frame passed its narrow visual check; the full set did not. No render, motion/audio approval, or release approval is claimed.

Opening provenance was reconciled directly against `.github/s81-candidate/candidate/scenes.js` at both native main `41bf913ffeadc9f54d8e5b90d0be42c59af0a430` and source run commit `c8e11bb0ce89e692aafe428df2b46ec917ed27b0`; both expose the same approved scene SHA-256 `045a9f74d976055573057a9833eebd6d6a8a54030b9fb5ca7f787bef2273645b`. The candidate retains its explicit visible parent, visible title, and portal/title/mark motion at time zero.

## Root findings and source changes

| Actual still | Root finding | Candidate source response |
|---|---|---|
| 02 at 10.10s, 03 at 16.22s | Header/disclaimer overlap; isolated black captions cross the file prop. | Reserve a separate source-note row below the 42px kicker; keep long source credits in the bottom source band; put captions in an opaque paper card with ink text. Keep words grouped as four-word phrases and visible as complete phrases. |
| 04 at 18.41s, 09 at 34.52s, 15 at 46.61s | The next story subject is absent at the exact scene-start capture. | Scene parents enter at full opacity at their exact `from` time, with position movement carrying the entrance. The evaluation monitor, inbox/alert, and lesson objects remain present at those timestamps. Capture timestamps stay unchanged. |
| 07 at 30.66s, 08 at 32.33s | Red calendar rule crosses the `PORTAL ACTIVITY` heading; `AUG` is clipped. | Give the three cards equal flexible width, wrap headings at 42px, and place the red rule below the heading. |
| 11–14 and 18–19 | Privacy qualification and audit URL remain intact. | Preserve their exact copy and scene timing. Do not move the word clock or weaken the qualification. |

## Locked boundaries

- Preserve the 56.365-second duration, the exact locked word clock, and all 19 source capture names and times in `capture-plan-source.json`.
- Keep the exact opening, narration, factual claims, quotations, attribution, OpenAI identification mark and URL. Do not create an endorsement, portal screenshot, legal conclusion, or personal-data access claim.
- Keep this source capture silent: no voice or music is attached, and no protected voice, music, SFX, screenshot, or programme media is included.
- Keep approval `NOT_GRANTED`, editorial status `NOT_REVIEWED`, AV review `NOT_PERFORMED`, and publication `NOT_REQUESTED`.

## Source-only checks

The local regression checks bind the active guard and picture tests to `candidate/scenes.js`. They assert the header row, 42px authored type floor, phrase-card contrast and visibility, scene-entry visibility, lower caption-safe band, calendar rule position, unchanged 19 captures, and unchanged locked privacy/CTA timing. Synthetic PNG tests exercise only the existing active-frame receipt guard; they are not pictures from this candidate.

Static PASS means the candidate source and deterministic checks are internally consistent. It does not establish that the new layout renders well. Root must review a fresh actual 19-still hosted capture before any full render, audio work, readiness claim, or release decision.
