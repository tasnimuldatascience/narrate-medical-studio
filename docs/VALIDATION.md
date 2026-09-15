# Validation record

## Expressive voice, editorial roles and animation milestone — 2026-09-15

Automated verification: **314 tests passed** in the Windows development environment, with two dependency deprecation warnings. TypeScript checking, optimized frontend build, formatting and whitespace checks passed. Focused follow-up tests also cover shared paragraph-boundary parsing. Runtime model assets and Office playback are verified separately from mocked/unit contracts.

### Actual supplied PowerPoint sample

The saved, unapproved notes-deck slide 6 revision 3 was synthesized with **Qwen3-TTS 1.7B CustomVoice / Aiden / engaging / rate guidance 1.0**, without rewriting its text. Speech-block text matched the normalized saved script. This verifies input/cue bookkeeping, not an ASR comparison of the spoken recording.

- Narration: **64.44 seconds**, mono 16-bit PCM, 24 kHz.
- Model load + generation: **197.473 seconds**; complete cold adapter run: **241.677 seconds**.
- Peak PyTorch allocated memory: **4462.3 MiB**; observed NVIDIA total process use about **4854 MiB**. The 8 GB GPU was released after the worker exited.
- New guided-focus video: **67.666667 seconds**, matching H.264 1920×1080 and AAC audio durations, selectable subtitle stream. Region changes follow measured paragraph starts, with authored regions and a permanent unapproved banner.
- PCM result: peak **−2.32 dBFS**, RMS **−19.80 dBFS**, near-clipping fraction **0**, longest silence **1.7 seconds**; no technical audio warnings.
- Private artifacts: `data/validation/qwen-slide-6-aiden-engaging.wav` and `data/validation/draft-preview-slide-6-a6612c59/presentation.mp4`. Source, script, voice, timing and quality metadata accompany them. These files are excluded from Git.

The previous comparison used Kokoro af_bella at 0.97 and produced a 72.5-second preview. The new engine changes delivery; listening preference, pronunciation accuracy and learner comprehension have not been independently scored. No clinical approval or released medical lesson was created.

### Native PowerPoint and guided-focus verification

Both supplied sanitized decks have 60 slides and **zero native timing or transition elements**. A separate synthetic PowerPoint 16 fixture with fade, fly-in and a 0.5-second entry transition demonstrated actual native animation. Its complete 7.8213-second timeline was fitted to 7.25 seconds / 174 frames / 24 fps. Early and late frames differed as expected; the safe source hash remained unchanged. Cancellation returned in about 2.14 seconds, no owned Office process remained, and a too-short one-second request was rejected explicitly.

The complete three-slide synthetic pipeline passed in **Guided focus** and **PowerPoint effects** modes: each produced **38.875 seconds** of H.264/AAC video, captions, transcript, chapters, quality metadata and a portable interactive ZIP. Native timing scale, effect schedule and isolated-entry transition limitations are recorded. Native effects require separate Windows/Office integration checks; unit tests alone cannot validate COM playback.

### Live editorial findings

Ollama rejected a large `maxLength` constraint while initializing its JSON grammar. The transport schema now omits that parser-incompatible constraint; original Pydantic bounds still validate returned data. This fix applies to writer and critic calls.

The first successful saved-script critic call produced **false positives**, claiming omitted equipment ranges and a hemostat instruction that were already present. A full workflow trial also returned an altered source quotation and was rejected before modifying the saved script. Exact quotation validation is necessary but does not establish correctness of a finding. These trials are retained privately; they are evidence against claiming calibrated or clinically reliable self-evaluation.

Revision selection now retains the original candidate if a proposed rewrite introduces new numeric, unit, qualifier or absolute-wording mismatches. Unreviewed OCR and unresolved source conflicts cannot be repaired by rewriting, so those findings alone do not trigger an automatic revision. Findings remain reviewer suggestions, with deterministic and model origins distinguished.

A single bounded critic repair attempt was then tested live. Both initial and repair responses altered an evidence quotation, so the full automatic draft workflow failed closed again. Private raw attempts are retained for diagnosis. The separate saved-script assessment did complete through the live API at revision 4, after three authored paragraph-linked cues were saved; narration wording and its editorial origin remained unchanged. This establishes the API path, not critic reliability.

## Environment

Windows workstation, Python 3.13, Node 24, React/TypeScript/Vite, installed Microsoft PowerPoint, FFmpeg, Kokoro English narrator assets, optional Piper English Lessac medium, local Ollama qwen3:4b and qwen3.5:9b.

## Current revision — 2026-09-15

- Frontend formatting and TypeScript/optimized production build passed after adding Whiteboard/Studio selection, source-region dimensions, cue ordering, and label limits.
- Implemented controls: Kokoro voice auditions use a fixed nonmedical sample; no project narration is submitted for audition. Export review remains separate.
- Source-region authoring uses normalized image coordinates, 2–100% width/height, 24% initial dimensions, up to six regions, and labels up to 120 characters. Overlay rectangles are clipped to the actual contained source image.
- Whiteboard progressively reveals authored regions; Studio uses the full slide with callouts. Subtitle boundaries are estimated from speech durations, not forced-aligned words.
- **184 automated tests passed** in the final Windows regression run, with two dependency deprecation warnings. Coverage includes cancellation between writing passes, incomplete model responses, atomic OCR/draft updates, equivalent spoken ranges, source review invalidation, complete reading passages versus short captions, real FFmpeg frame timing, source-region preservation, and export review gates.
- The three-slide diagram fixture completed real PowerPoint rendering, Kokoro speech, and both Whiteboard and Studio video exports. Each output has H.264 1920×1080 video, AAC audio, and a selectable subtitle stream. Audio and video durations both equal **38.875 seconds**.
- Visual inspection found and corrected low caption contrast on the white canvas. Long authored labels now fit in full. Additional native captions default off when the video already contains permanent captions.
- Browser inspection confirmed the redesigned studio, local runtime readiness, and a real fixed-script voice preview. The browser decoded the 16.349-second WAV with readyState 4 and no media error; attempting playback subsequently crashed the embedded browser. End-user audio-device playback in a standalone browser remains to be confirmed.
- Direct `file://` launch of the lesson could not be tested because the browser tool blocks local-file URLs. No workaround was used. Earlier localhost interactive checks and current caption/package tests are recorded separately from this unverified launch mode.
- Live API validation passed through synthetic upload, rendering, region/script edits, named approval, Kokoro export, and downloads. ZIP CRCs, unique safe paths, the identical packaged MP4, settings, reviewed cues, chapter titles, quality metadata, and the final knowledge check were verified. A retained software demo is available in the studio; no clinical approvals were added.
- Browser inspection confirmed the retained demo's source-region coordinates, labels, region-size controls, review status, and generated export links.

## Additional source and narration checks — 2026-09-15

- Offline OCR processed all **60 slides** of the supplied notes deck in **61.7 seconds**, extracting **752 lines**. **47 lines across 36 slides** scored below 0.9 confidence. There were **165 numeric lines across 31 slides**, including **two low-confidence numeric lines**. Confidence scores identify material to inspect; they do not establish transcription accuracy or medical correctness. This evaluation did **not mutate the project database** or add review decisions.
- Real drafting comparisons used supplied slides **4, 6, and 13** with **qwen3:4b** and **qwen3.5:9b**. Inspection found omissions and changed qualifiers. The 9B model retained many size values, but the comparison was **not a clinical fidelity pass**. A larger model does not remove the need to compare every claim, condition, and quantity with the source.
- A reasoning-enabled trial reached the output cap without a usable final draft. Thinking mode was disabled for narration calls after that failure; a syntactically successful response alone is insufficient evidence of a usable explanation.
- The learner reading pane now uses complete speech-block paragraphs, separate from short subtitle cues. Typography, active highlighting, literal search highlighting, and navigation to the current passage were updated. Inline JavaScript and static offline-resource checks passed, and the focused lesson suite passed **eight tests**. This focused result is not the total application test count.
- Browser inspection confirmed the supplied deck's slide 6 OCR action, disabled controls while processing, detected source text and quantities, and unchecked transcription status. The revised multi-paragraph script and explicit Codex editorial provenance are visible in the editor; clinical approval remains disabled. This is a focused authoring check, not a full browser acceptance or accessibility audit. The exported learner's local-file launch remains unverified as described above.
- A refreshed synthetic export through the real API has matching audio/video duration of **38.875 seconds**, with **H.264 video and AAC audio**. This is a software fixture result, not an approved medical lesson or evidence that narration preserves every clinical detail.
- Codex editorial corrections were saved locally for slides 4, 6, and 13 after comparing the source images and notes. They are labelled separately from local-model results. Slide 6's listed numeric values/units were retained; slide 4's unresolved glove/drape scope differences and slide 13's undefined abbreviation/timing item were explicitly flagged. These drafts do not establish clinical approval or a general local-writer quality pass. The private before/after report stays in ignored `data/validation/revised-slide-narration.md`.

## Requested source-PPT draft preview — 2026-09-15

- Created a private preview from the actual supplied deck's slide 6 and its saved Codex editorial draft. Kokoro `af_bella` at 0.97 pace produced a **72.5-second** 1920×1080 H.264/AAC video with captions. FFprobe confirmed matching video/audio duration.
- Author-selected source text regions change at measured paragraph boundaries. The full source remains visible. This is source highlighting, not generated procedural or anatomical animation.
- Inspected intermediate frames for source readability, captions, region placement, and the permanent **UNAPPROVED / FOR REVIEW ONLY** banner. Corrected a header overlap. Automated checks verify the banner cannot change its input image and stays present when applied repeatedly.
- Project approvals were not changed; the video is a separate private review artifact in ignored `data/validation/`. The reviewed clinical exporter remains gated. This test does not establish clinical accuracy, medical pronunciation quality, or learner comprehension.

## Earlier baseline checks

The following results were recorded before the current Kokoro and authored-region/Whiteboard revision:

- Frontend TypeScript checking and optimized production build passed.
- Twenty backend workflow tests passed during independent review. The suite covers approval invalidation and stale writes, job serialization/cancellation bookkeeping, invalid uploads, traversal, XML DTD rejection, active content removal, export authorization, and local model alias checks.
- A synthetic three-slide deck completed real PowerPoint rendering, Piper speech synthesis, captions, FFmpeg video assembly, and interactive ZIP export.
- ffprobe confirmed H.264 video at 1920×1080, AAC audio, and a selectable subtitle track. The revised media pipeline joins PCM before encoding AAC to avoid accumulating per-slide padding.
- Both supplied medical decks imported and rendered all 60 slides. The brief's reference to 73 slides does not match either file's actual slide count.
- Browser inspection confirmed the library, real slide previews, extracted source material, draft controls, and disabled approval controls until review prerequisites are met.
- Real local qwen3:4b drafting completed on a sparse title slide and flagged insufficient source detail rather than inventing a clinical explanation.
- Interactive browser checks confirmed chapter seeking, transcript filtering, selection of an answer, source-grounded feedback, and progress changing from 0 to 1 reviewed chapter.
- The earlier synthetic output had matching audio/video duration of 10.125 seconds, with H.264 1080p, AAC, and subtitles verified by ffprobe.

## Findings fixed

- Python/pytest temporary directories and frontend subprocesses required approved execution outside the Windows sandbox.
- One test used the Windows default encoding to read UTF-8 lesson HTML. It now specifies UTF-8.
- Removing hyperlink relationships without their referencing nodes made the original PPTM rendering copy unreadable. Sanitization now removes dangling hyperlink actions too.
- Independent review identified SQLite connection closure, cancellation bookkeeping races, export validation timing, and cloud-model aliases; these were corrected.
- Test discovery is limited to `tests/`, preventing private data folders and generated temporary files from being collected as test suites.
- Export requires both FFmpeg and ffprobe; a missing verification tool cannot silently produce a successful unverified export.
- Automatic heading selection ignores large decorative punctuation and numeric-only labels instead of choosing them over meaningful chapter titles.

## Not established

This record is not clinical validation, a security certification, a full accessibility audit, a fresh-machine installer test, or production certification. It does not establish forced-aligned subtitles, medically validated generated anatomy, or equivalence to a reference educational animation. The medical decks have no automated practitioner approval and have not been exported as approved clinical lessons. Visual spot checks do not establish pixel-perfect fidelity across all 120 rendered slides. Cross-platform operation and disconnected-system behavior of external programs need separate tests.

Run `pytest`, the frontend build, and `scripts/verify_pipeline.py` to reproduce the software checks. Generated validation outputs stay in ignored `data/validation/`.
