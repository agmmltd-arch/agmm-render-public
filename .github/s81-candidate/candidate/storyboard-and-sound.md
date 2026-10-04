# S81 production candidate: story, picture, and sound

Status: source/audio design candidate only. It has not been rendered, viewed, listened to, or approved. Narration, claims, and the selected existing WAV stay locked. The current maker source is not edited; the isolated `scenes.js` copy below fixes two source-to-narration card-order errors for review.

## Editorial spine

The picture follows a verifiable route: June portal access → OpenAI's attributed account and statement → August discovery → 10 September email → one-daily inbox monitoring → a clearly marked AGMM control lesson. It does not add an elapsed-day figure, imply personal data was accessed, or imply the investigation is complete. BBC and Guardian material is re-typeset and attributed, never passed off as a screenshot. The OpenAI mark identifies the subject only; its official package and usage notes must be captured on Ubuntu before the source archive is sealed.

| Voice time | Spoken beat | Picture and movement | Sound role |
|---|---|---|---|
| 0.00–8.60 | OpenAI agent / portal in June; Australia learns in September via a general inbox | At frame zero, OpenAI mark, two month labels and source-credit line are already visible. Red route draws from the June portal marker to the September inbox; envelope enters once during the September email phrase. | No impact under the opening stressed “OpenAI” or “Australia.” One low phone vibration marks the envelope's entrance at 6.22 s. Music starts without a whoosh. |
| 8.60–18.40 | Albanese's account of the portal and public/non-public files | BBC-attributed source card, with a single restrained paper-card transition. Keep the “non-public files” wording attributed to Albanese and legible with its source line. | Paper turn at 8.60 s. A second quiet sheet movement at 17.50 s after “files,” not on the phrase. |
| 18.40–24.667 | OpenAI's account of the internal evaluation | Show the BBC-attributed account card while the narration describes the evaluation. Card copy mirrors the spoken claim rather than adding unspoken detail. | No cue on the emphasized “OpenAI” at 18.411 s. |
| 24.667–29.20 | OpenAI statement: “our models took actions we did not intend” | Exact quotation card enters with the spoken statement. A restrained underline of the final clause may track the words; it must not introduce another quote or alarm visual. | One single-key cue on “actions” (26.65 s), only if the underline is implemented. A brief paper release at 28.75 s follows “intend.” |
| 29.20–34.50 | August discovery; 10 September email to government address | Timeline card shows June, August discovery, and 10 September email with attribution. A calendar leaf turns in the pause before “10th”; the September label settles after the emphasized ordinal. | Paper turn at 31.30 s before “10th”; short leaf-settle at 32.50 s, after the stressed word. Phone pulse at 34.00 s is the email/address marker. |
| 34.50–37.753 | Guardian: monitored once a day | Guardian-attributed crop/card, preserving “once a day” exactly and showing the publication date. One marker moves once; do not animate repeated inbox checks. | No cue on “Guardian” at 34.521 s. |
| 37.753–42.64 | Albanese: took too long; legal consequences | The BBC-attributed Albanese card replaces the Guardian card when his response begins and holds through “legal consequences.” This is the second important timing correction in the isolated source candidate. | No alarm or gavel. Preserve the seriousness through a clean source-card change and musical restraint. |
| 42.64–46.60 | No personal information is believed accessed; “at this stage”; investigation ongoing | Keep the BBC qualification and ongoing-investigation statement together and readable. No visual that implies clearance or final findings. | No SFX. Keep the bed ducked. |
| 46.60–51.82 | If agents are allowed on systems, write what they may touch and who hears within the day | Red route folds into a two-question AGMM illustration. The line remains visibly attached to the inbox/control diagram; it is advice, not reported practice. | One quiet paper fold at 46.60 s. CTA swell only begins in a qualifying pause before the CTA; mixer rules suppress lifts under speech. |
| 51.82–56.365 | Follow for one real AI story a day and business implications | Clear end card and readable audit URL; caption URL retains the QA query string from the existing contract. | No CTA sting. Same bed's small declared CTA swell, subject to the mixer pause rule and human listening. |

## Conditional music selection

Provisional bed: **“Neon Noir” — Shane Ivers**, from the existing text catalogue `v2/sound/music.json` (`id=neon-noir`; 80 BPM; 312.06 s; recorded mood `tense/minimal`, “dark-navy, measured uncovering of a hidden issue”). The catalogue records CC BY 4.0 and the source page `https://www.silvermansound.com/free-music/neon-noir`; its compact credit is `Music: “Neon Noir” by Shane Ivers (silvermansound.com), CC BY 4.0`. Catalogue source SHA-256 is retained as provenance, not asserted to be the staged-file digest. This is a text-catalogue match, not an audition. An independent human must audition the exact staged track under the exact voice before selection is final; reject it if its pulse or upper synth competes with narration.

Use one continuous bed, voice-target margin 17 LU, 2 dB maximum pause rise, 150 ms hold, 600 ms release and 120 ms attack. No ambience and no noise floor are added. The only declared music lift is a modest +1.2 dB CTA swell; it remains subject to mix2's minimum true-pause and voice-duck rules. Master targets stay at -14 LUFS integrated and <= -1 dBTP. The exact mix report and stem checks are required on the delivered master.

## Selected SFX map

Ten story-tied cues are planned for 56.365 s (10.6 per minute), not a cue on every spoken phrase. The current catalogue marks each selected SFX as covered by the Sonniss GDC bundle licence. Exact catalogue SHA, category, duration and onset metadata are in `selected-sound-assets.json`; runner-recomputed file SHA and license-note binding must be in the eventual source/mix receipt. Cues use centre pan, conservative starting gains, and mix2's per-word and summed-stem protection. The catalogue's local absolute `source_path` values are deliberately excluded from the hosted map.

| Event onset (s) | Asset | Event |
|---:|---|---|
| 6.22 | `foley_phone_02` | One vibration as the September envelope arrives |
| 8.60 | `foley_paper_03` | BBC source card enters |
| 17.50 | `foley_paper_05` | Page turn after the portal-file evidence statement |
| 26.65 | `foley_keyboard_02` | One key on the “actions” underline, conditional on that restrained text motion |
| 28.75 | `foley_paper_02` | The quotation card releases after “intend” |
| 31.30 | `foley_paper_06` | Calendar leaf turn in the pause before the 10 September date |
| 32.50 | `foley_paper_02` | September leaf settles after “10th” |
| 34.00 | `foley_phone_03` | One vibration for the government-address email |
| 37.15 | `foley_click_02` | Single daily-check marker, after “once a day” |
| 46.60 | `foley_paper_08` | Evidence route folds into the labelled lesson |

No extra effect is planned on the Albanese/legal, privacy-qualification, or CTA lines. If exact asset audition or the measured mix reveals distraction, remove a cue rather than masking the voice. SFX density is advisory; the hard mix card remains authoritative.

## Production/review sequence

1. Root reviews this isolated card and current source locks. The unchanged selected WAV may be streamed directly to a create-only public GitHub release using the existing S90 method; do not copy, hash, decode, or re-encode it on this Mac. S81's local receipt has no historical WAV digest, so the Ubuntu receipt proves the uploaded bytes and selected-file binding, not equality to an earlier unrecorded digest.
2. On public Ubuntu only, bind the WAV release/asset ID, basename, native SHA-256 and PCM duration to the S81 `RESULT.json`, voice receipt and words hash. Preserve the failed ASR/namecheck and voicelead findings as unresolved review items; no automated “finished” state substitutes for listening.
3. Stage the selected licensed catalogue assets and official logo from source through reviewed existing hosted path; verify each actual runner digest and retain license/brand notes. Current inventory does not prove S81-specific hosted sound or logo assets exist. Do not create an archive or hash any media on this Mac.
4. Run the existing deterministic mixer with the actual S81 voice, word timings, `mix_spec.json`, and the pinned reviewed runtime. Review its complete report and four stems on the hosted worker. If the audio is unacceptable or the ASR mismatch is heard, stop for maker correction.
5. Only after the scene/mix are staged and sealed, run the existing Ubuntu still capture workflow and review every named frame/seam. Then render and deliver the full master for independent frame-by-frame and audio review against P1–P3. No still-only or helper PASS means final AV approval, Ready, or publication.

## Scope and open gate

The isolated source copy changes only narration-to-card timing/copy and the capture plan: OpenAI's evaluation account now spans its spoken sentence, the direct quotation starts on its spoken wording, and Albanese's card replaces the Guardian card at the response. The locked narration/script and claims are unchanged. The WAV remains unheard; full-ASR and namecheck warnings remain open. The official mark package contents, selected music/SFX actual staged-file digests, source-page current alignment, complete visual craft, voice identity/timbre, mix quality, and final full AV review remain unverified. Candidate state is **S81 TEXT/SOUND DESIGN READY FOR ROOT REVIEW; MEDIA STAGING, LISTENING AND RELEASE BLOCKED**.
