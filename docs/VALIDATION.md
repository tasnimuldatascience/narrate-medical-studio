# Validation record

## Environment

Windows workstation, Python 3.13, Node 24, React/TypeScript/Vite, installed Microsoft PowerPoint, FFmpeg, Kokoro English narrator assets, optional Piper English Lessac medium, local Ollama qwen3:4b.

## Current revision — 2026-09-15

- Frontend formatting and TypeScript/optimized production build passed after adding Whiteboard/Studio selection, source-region dimensions, cue ordering, and label limits.
- Implemented controls: Kokoro voice auditions use a fixed nonmedical sample; no project narration is submitted for audition. Export review remains separate.
- Source-region authoring uses normalized image coordinates, 2–100% width/height, 24% initial dimensions, up to six regions, and labels up to 120 characters. Overlay rectangles are clipped to the actual contained source image.
- Whiteboard progressively reveals authored regions; Studio uses the full slide with callouts. Subtitle boundaries are estimated from speech durations, not forced-aligned words.
- **115 automated tests passed** on Windows. Coverage includes real FFmpeg frame timing, source-region clipping and preservation, cancellation, complete long-label rendering, title extraction, subtitle layout, duplicate-caption prevention, fixed-script auditions, cache integrity, and approval invalidation when regions change. Two dependency deprecation warnings remain in the test client.
- The three-slide diagram fixture completed real PowerPoint rendering, Kokoro speech, and both Whiteboard and Studio video exports. Each output has H.264 1920×1080 video, AAC audio, and a selectable subtitle stream. Audio and video durations both equal **38.875 seconds**.
- Visual inspection found and corrected low caption contrast on the white canvas. Long authored labels now fit in full. Additional native captions default off when the video already contains permanent captions.
- Browser inspection confirmed the redesigned studio, local runtime readiness, and a real fixed-script voice preview. The browser decoded the 16.349-second WAV with readyState 4 and no media error; attempting playback subsequently crashed the embedded browser. End-user audio-device playback in a standalone browser remains to be confirmed.
- Direct `file://` launch of the lesson could not be tested because the browser tool blocks local-file URLs. No workaround was used. Earlier localhost interactive checks and current caption/package tests are recorded separately from this unverified launch mode.
- Live API validation passed through synthetic upload, rendering, region/script edits, named approval, Kokoro export, and downloads. ZIP CRCs, unique safe paths, the identical packaged MP4, settings, reviewed cues, chapter titles, quality metadata, and the final knowledge check were verified. A retained software demo is available in the studio; no clinical approvals were added.
- Browser inspection confirmed the retained demo's source-region coordinates, labels, region-size controls, review status, and generated export links.

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
