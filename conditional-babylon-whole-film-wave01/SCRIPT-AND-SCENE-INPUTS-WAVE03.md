# F08 Babylon — conditional script and storyboard, Wave 03

**Status:** revised conditional candidate for root editorial, fact and code review. Title/slate approval remains open. This does not authorise voice generation, rendering, publication or a library change.

## Proposed title

**What Did Babylon's 81% AI Score Actually Test?**

Working title for this package only. The canonical F08 library row remains `Babylon Health: the AI that passed the GP exam` until its owner approves a change.

## Editorial plan

The hook asks what the 81% measured and immediately shows the selection boundary. The story follows three separate evidence tracks: Babylon's selected diagnostic-question sample and historical pass-mark comparator; a different company-reported vignette comparison; and the separate prospective study in the 2018 paper. A short NHS section establishes GP at Hand's service context and dated patient-mix evidence. A final chronology gives only bounded corporate events. The conclusion returns to the four questions a business should ask of an AI benchmark.

The edit removes the 2022 revenue/loss paragraph and repeated causation caveats. It retains one plain boundary at each transition where evidence types could otherwise be confused. It does not connect the score causally to financing, valuation, company events or patient outcomes.

## Candidate narration

### Scene 01 — The number

What does 81 per cent actually mean? In June 2018, Babylon announced that its AI had scored 81 per cent on a set of diagnostic questions. That sounds like a pass. But the first thing to ask is smaller and more useful: what was in the set?

### Scene 02 — The selected sample

Babylon's own release says the Royal College of General Practitioners did not publish past exam papers. So the company assembled what it called a representative sample from public RCGP material and independent exam-preparation sources. Babylon said its AI scored 81 per cent on that sample, on its first attempt.

The boundary matters. This was a selected question sample, not a sitting of the complete MRCGP examination. Keep the unselected field visible around it: the score describes what entered the sample, not every question that could have been asked.

### Scene 03 — The comparator

Babylon set 81 per cent beside a 72 per cent average pass mark drawn from RCGP data covering 2012 to 2017. One number is the company's result on its sample. The other is a historical pass-mark average. The announcement does not describe a matched test where candidates and software answered the same full paper under the same conditions.

So the useful comparison is not a race between two bars. It is a check on the denominator: what questions counted, how was the sample assembled, and what can that older pass-mark figure tell us?

### Scene 04 — A separate study

The announcement also reports a different comparison: 100 clinical vignettes, with Babylon's AI at 80 per cent and seven doctors between 64 and 94 per cent. Those vignettes are a separate task from the sample behind 81 per cent.

A paper submitted on the same day describes a prospective comparison of an AI triage-and-diagnosis system with doctors on identical cases, with a judge blind to which answer came from whom. It also discusses benchmark vignettes. The paper does not report an independent repeat of the 81 per cent sample-question result. Keep those three things on separate tracks: sample questions, company-reported vignettes, and the prospective study.

### Scene 05 — GP at Hand

Babylon launched GP at Hand through the Lillie Road NHS practice in 2017, combining digital access with GP consultations. NHS England later described its patient profile using age- and sex-adjusted QOF prevalence: slightly below Hammersmith and Fulham averages, except asthma, which was broadly as expected. The paper also says people with long-term conditions needing regular face-to-face care were encouraged to seek advice before registering while the model was assessed.

That describes a service population and a selection policy. It does not turn an exam-question score into a measure of care for every patient.

### Scene 06 — A dated service count

In a September 2023 board paper, NHS North East London described GP at Hand as serving more than 100,000 London residents. Put the date beside the count. It is a later service snapshot, not another measurement of the 2018 AI test.

### Scene 07 — Company chronology

The company timeline has its own dates. In 2019 Babylon announced a 550-million-dollar fundraise, saying more than 450 million was committed and the remainder expected. In 2021, Babylon and Alkuri announced a proposed merger with an initial pro forma equity value of about 4.2 billion dollars. The merger later completed, and BBLN trading began on the New York Stock Exchange on 22 October.

In 2023, a proposed transfer of core operating subsidiaries to MindMaze did not proceed. Babylon then reported its exit from the core US business and the acquisition of its UK business assets by eMed; it said GP at Hand would continue. The London Gazette separately records administration for named Babylon entities beginning on 1 September.

These dates make a chronology. They do not explain one another, and they do not measure the 2018 score.

### Scene 08 — The test to take away

So what did 81 per cent prove? It records what Babylon said its AI achieved on a representative sample of diagnostic questions. The public description does not make that a pass of the full GP examination.

When an AI benchmark informs a business decision, ask four things: what task was tested, how was the sample chosen, what did the comparator measure, and has the result been independently repeated on the job you care about?

If you are assessing a constraint in your own AI workflow, start with the AI Constraint Audit at agmm.co.uk/ai-constraint-audit.

## Storyboard direction

| Scene | Visual action | On-screen copy | Source credit / boundary |
|---|---|---|---|
| 01 | At frame zero, a field of small question strips moves toward a narrow transparent aperture. One strip crosses; the camera locks to the boundary before `81%` lands inside it. | `81%` / `Babylon-reported` / `June 2018` | Babylon release, 27 June 2018. No exam paper or RCGP logo. |
| 02 | A bespoke selection instrument reveals the source families feeding the bounded sample; the outer field remains visible and dim. | `Selected diagnostic-question sample` / `Public RCGP material + independent preparation sources` | Attribute the method to Babylon. Do not invent question count or selection protocol. |
| 03 | The bounded sample track ends at 81. A separate dated pass-mark strip runs below it and stops at 72; no shared axis or race animation. | `81%: company-reported sample result` / `72%: average pass mark, 2012–2017` | Babylon release. Label the comparison as unlike measures, not a matched trial. |
| 04 | The 100-case vignette branch splits away from the sample instrument. A second, separately sourced study track enters with identical-case markers and a blind-judge shutter. | `100 vignettes: separate company-reported comparison` / `Paper: separate prospective study` | Babylon release; Razzaki et al., arXiv:1806.10698. No independent-replication claim. |
| 05 | The graphics shift to a service-map plan: a single Lillie Road identifier, then a carefully labelled QOF comparator strip and selection-policy gate. | `GP at Hand · 2017` / `QOF prevalence: slightly below comparator; asthma broadly expected` | NHS England source. No generic healthy/unhealthy patient icons or claims. |
| 06 | A calendar plate marked `SEP 2023` slides into a separate frame before `100,000+` appears. | `London residents served` | NHS North East London ICB. Count remains dated to this statement. |
| 07 | Three disconnected chronology rails: 2019 financing; 2021 proposed value then trading; 2023 proposal, UK asset sale and named-entity administration. Gaps stay open; no arrows connect back to 2018. | Dated source labels only; no chart of share price. | Babylon/SEC filings and London Gazette. Exact entity names stay in source note/credit. |
| 08 | Three evidence tracks fold into four question tabs. The CTA card enters only after the four questions have been spoken. | `Task? Sample? Comparator? Independent repeat?` / `AI Constraint Audit` | Editorial synthesis and live-checked route from prior package. No outcome promise. |

## Clock and build boundary

The generated board uses **155 words per minute** as an editorial estimate, with no added scene holds. Scene duration follows its narration word count, rounded to 0.1 seconds. This is a planning clock, not a performance measurement. The conditional composition must visibly say `ESTIMATED CLOCK · NO VOICE`.

The production builder must refuse to bind a final clock until it receives the approved script hash, actual voice SHA-256 and monotonic measured word timings. Root review of this script, storyboard, asset plan and source code remains required before any hosted render.
