# S81 second picture correction — root review packet

Status: isolated source draft, not rendered or approved. Root reviewed all 19 native images from hosted source run `37238009845` at head `d699d3837647a142afffb595c96b8249d3a0fb68` and returned `SOURCE_SET_FAIL`. The exact receipt is `ROOT-SECOND-ACTUAL-19-FRAME-REVIEW.json`.

## Four observed defects and source responses

| Frames | Root-observed defect | Source-only correction |
|---|---|---|
| 09 | Guardian quote showed literal `<strong>` tags because shared `el()` uses `textContent`. | Build the quote as a text node plus a real `<strong>` element. |
| 02, 03 | `NON-PUBLIC` broke inside the word. | Use the whole-word line break `NON-` / `PUBLIC` / `FILES`. |
| 07, 08 | `NOTIFICATION` broke inside the word. | Use the shorter whole-word heading `EMAIL NOTICE`. |
| 15 | Left lesson control entered beyond the frame edge. | Bound entry to `min(24px, 64px safe inset - 20px clearance)`. |

Frame 09's entire bottom source credit was visibly present and not clipped in root's review. It is unchanged.

## Preserved source contract

- Keep the visible moving frame-zero hook and official OpenAI mark. Native opening provenance remains the verified scene SHA `045a9f74d976055573057a9833eebd6d6a8a54030b9fb5ca7f787bef2273645b` from main `41bf913ffeadc9f54d8e5b90d0be42c59af0a430` and source commit `c8e11bb0ce89e692aafe428df2b46ec917ed27b0`.
- Keep the 56.365-second duration, 158 locked words, exact 19 capture names/times, narration, factual claims, privacy qualifier, audit URL, captions, and source credits.
- Keep the hosted source capture silent. No programme media was read, copied, decoded, hashed, archived, rendered, or listened to on Mac.

## Checks and remaining gates

Source syntax and deterministic guards pass: 14 source/active-frame tests (synthetic PNGs only), 7 targeted source correction tests, and 5 payload story/sound tests. Payload and silent-spec validation are recorded in `TEST-OUTPUT.txt`. These are static checks; they do not verify new rendered images.

A fresh corrected hosted still capture has **not** been run. Root must admit the exact packet and decide on one changed 19-still capture. Continuous motion/audio review, independent pilot comparison, AV approval, and release remain open. No publication or dispatch is authorized by this packet.
