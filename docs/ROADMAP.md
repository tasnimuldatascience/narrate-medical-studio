# Production readiness

The working release proves the workstation workflow. A professional medical education product needs further evidence before being described as production-ready.

## Implemented in the development release

- Cinematic React studio with source review, scene navigation, local voice auditions, and explicit output-style selection.
- Kokoro thought/paragraph-block synthesis with four narrator choices; optional Piper/Windows alternatives.
- Up to six manually authored source regions per slide, editable sequence and 120-character labels. Label, position, size, and sequence edits reset review.
- Whiteboard progressively reveals authored source regions and ends with the original slide. Studio retains the full source with timed callouts. No-cue slides retain their full visual.
- Caption timing estimated from generated block duration. This is not forced alignment.

These capabilities animate reviewed source material. They do not establish reference-video equivalence, generated anatomical motion, clinical validity, or production certification. Updated end-to-end fixture results are pending in `VALIDATION.md`.

## Clinical content and narration

- Build a permission-cleared evaluation corpus spanning specialties, notes-heavy slides, tables, units, multilingual text, images, and conflicting information. Measure omitted claims, added claims, quantity preservation, abbreviation handling, and reviewer correction rate.
- Add OCR and local visual models with source-region citations. Treat OCR as uncertain extracted text, never authoritative medical transcription. Acceptance: every generated factual claim can be traced to a visible source, and unclear source regions are flagged.
- Add a versioned pronunciation dictionary with audio previews, reviewer-approved phonetics, and per-project overrides. Benchmark common drugs, anatomy, and acronyms with educators.
- Evaluate the implemented paragraph-block delivery across medical terminology and long passages. Add tested forced alignment if precise word/phrase synchronization is required; evaluate intelligibility, pacing, caption accuracy, and retained meaning separately.

## Authoring and learner experience

- Add bulk source-preserving draft queues, slide grouping, reusable lesson templates, learning objectives, chapter editing, and undoable changes.
- Extend the existing authored source-region reveals and knowledge checks with manually authored clinical cases, accessible image descriptions, and richer explanation sequences. Validate both authoring and learner interaction without a mouse.
- Add a fast rendered export preview and expand the implemented Whiteboard/Studio styles. Evaluate source-region visibility, progressive reveal timing, and caption readability on laptops and classroom displays. Do not equate automated callouts with medically accurate generated animation.
- Evaluate SCORM/xAPI and LMS packaging with actual target learning systems. Do not infer that a generic HTML ZIP is an LMS-standard package.
- Validate with practitioners on real work: time to first approved lesson, completion of key tasks without help, review errors, accessibility barriers, and learner comprehension.

## Reliability and deployment

- Package a signed Windows desktop installer with pinned runtime assets, dependency license compliance, hashes, update/rollback, and a complete offline installation path.
- Validate macOS/Linux rendering and voice quality separately before claiming support.
- Add process isolation for untrusted converters, tighter resource limits, per-process network restrictions, encrypted storage options, authenticated reviewers, and tamper-evident audit records for organizations that need them.
- Add resumable per-slide jobs and bounded disk cleanup. Verify cancellation, restart, corrupt input, storage exhaustion, large-file memory behavior, and simultaneous windows.
- Establish CI with unit/integration coverage, dependency auditing, cross-platform packaging, UI accessibility tests, and repeatable visual checks. PowerPoint integration needs a licensed Windows test runner.

## Release gates

1. All required runtime checks and automated tests pass with pinned dependencies.
2. Every declared file type and target platform passes a documented compatibility suite.
3. Independent educators review a representative set of clinical lessons and report acceptable error/omission rates.
4. No unreviewed revision can reach published audio or a learner assessment.
5. Offline behavior is verified under network denial, including external renderers and local model runtimes.
6. Critical authoring and learner tasks pass keyboard and screen-reader testing, with measured WCAG contrast.
7. A fresh-machine install and recovery from interrupted jobs are demonstrated.

These are validation milestones, not claims that this release already meets them.
