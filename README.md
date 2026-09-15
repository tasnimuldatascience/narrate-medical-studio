# Narrate Medical Studio

A local application for turning medical PowerPoint presentations into reviewed narration, captioned video, and interactive learning packages. Built with React, TypeScript, Vite, FastAPI, SQLite, Ollama, Kokoro, optional Piper, and FFmpeg.

**Status: working development release, not a validated clinical product.** The workflow accepts different presentations and specialties. The supplied injection decks are test inputs, not hard-coded templates. No presentation content is submitted to a cloud API by this application.

## What works

- Import `.pptx` and `.pptm`, inspect slide text, notes, editable tables, image counts, and reference URLs.
- Render high-resolution slide previews using installed Microsoft PowerPoint on Windows, with macros disabled and a sanitized rendering copy.
- Transcribe rendered image-only slides with local RapidOCR. Inspect the proposed text, recognition confidence, and number/unit warnings under **Source > Image text**, correct it against the slide, and explicitly mark the transcription checked.
- Review original visuals beside the script. Local Ollama first drafts an explanation, then performs a separate editorial pass comparing the draft with the supplied source. Authors can also edit text directly. This two-pass workflow remains under evaluation; it does not confer clinical approval.
- Flag numerical content, limited sources, unreadable characters, tables, image interpretation, and model-reported uncertainty.
- Use a cinematic production workspace with source/script review, scene navigation, accessible dialogs, and explicit readiness feedback.
- Add source-grounded multiple-choice knowledge checks with feedback.
- Author up to six labeled source regions per slide. Set their order, center, width, and height against the actual slide preview; regions are clipped at image edges.
- Choose **Whiteboard** to reveal authored source regions progressively and finish on the original slide, or **Studio** to retain the full slide with timed callouts. Slides without cues show their full source visual. These are animations of existing source material, not generated medical anatomy.
- Audition four local Kokoro narrators using a fixed nonmedical sample in Setup or the export dialog. Kokoro synthesizes complete thoughts/paragraph blocks rather than each subtitle fragment; Piper and Windows voice remain alternatives.
- Record a named review of each slide revision. Any script, question, cue label, cue position, region size, cue order, or source-transcription change resets approval. The backend blocks export of unapproved slides and blocks approval when populated image text has not been checked.
- Export any approved slide range as 1080p H.264/AAC MP4, SRT captions, transcript, review manifest, and a self-contained interactive lesson ZIP.
- Interactive lessons include chapters, transcript search and seeking, playback speeds, knowledge checks, and progress feedback. Extract the ZIP and open `index.html`; no server is required.
- Store projects, reviews, jobs, model output, and exports in local SQLite/files. Interrupted jobs can be retried.

## Run on this Windows machine

From PowerShell in the repository:

```powershell
.\Start.ps1
```

Open `http://127.0.0.1:8765`. Keep the terminal open while the studio is running. Stop it with Ctrl+C. The server binds only to loopback, not to your LAN.

The development environment and local English voice assets have been installed on the current workstation. Use Setup & preferences to check availability on the machine where you run the app. Dependencies and model files are excluded from Git.

## Set up another Windows machine

Prerequisites:

- Python 3.11–3.13, Node.js 22.12+ (tested with Node 24), and npm.
- Installed Microsoft PowerPoint for Windows slide rendering.
- FFmpeg **and ffprobe** on PATH, with libx264 and libass support.
- Ollama with an installed local writing model for optional AI drafting. `qwen3.5:9b` is installed and tuned on the development workstation as a higher-capacity option. The lighter `qwen3:4b` has shown qualifier-preservation errors during evaluation. Neither model has passed a general medical narration quality assessment; use a model that fits your machine and review every result.

Run `Setup.ps1` for explicit dependency and model installation. It recommends Kokoro by default and offers Piper, both engines, or skipping voice downloads. It also offers offline OCR preparation: the pinned RapidOCR wheel already contains its ONNX models, and the setup script copies verified assets into the project and extracts the local character dictionary. Installing dependencies and voice/writing models needs internet access; OCR asset preparation needs no additional model download after its wheel is installed. Afterwards, ordinary authoring and export operate locally. To prepare a disconnected machine, transfer the installed runtime environment, dependencies, and model assets using your organization's software distribution process. A portable offline installer is not yet provided.

```powershell
# Equivalent manual setup
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
npm.cmd --prefix frontend ci
npm.cmd --prefix frontend run build
# Recommended: Kokoro model and voice bank (setup-only network download)
.\.venv\Scripts\python.exe scripts\download_kokoro.py
# Prepare OCR from the models bundled in the installed RapidOCR wheel:
.\.venv\Scripts\python.exe scripts\download_ocr.py
# Optional compact alternative:
.\.venv\Scripts\python.exe -m piper.download_voices en_US-lessac-medium --download-dir models
# Install the model explicitly during setup, if needed:
ollama pull qwen3.5:9b
.\Start.ps1
```

The UI's Setup page reports renderer, video, voice, OCR, and local model availability. Missing runtime components produce an error rather than switching to a cloud service. OCR verifies its local model and character assets and disables runtime downloads.

## Authoring workflow

1. Import your presentation and render its previews.
2. Set the specialty and learner audience under Setup.
3. Inspect each visual and its extracted source. For image-only content, open **Source > Image text**, run local OCR, and correct the transcription against the rendered slide. Check numbers, decimals, units, labels, and reading order; recognition confidence does not measure medical accuracy. Mark the image text checked only after comparison. Running OCR again retains existing authored image text; review the new OCR result before replacing your corrections.
4. Draft or edit a concise spoken explanation. Local drafting uses two calls: an initial draft and an editorial/source-comparison pass. Review their flags and compare the resulting narration with notes, extracted text, and checked image text. Resolve disagreements explicitly; a smoother rewrite does not resolve a source conflict. The current `medical-source-v5-editor` prompt is under evaluation and has no general quality-pass claim.
5. Optionally add a question, three choices, the correct answer, and a source-grounded explanation.
6. In **Visual story**, explicitly place source regions by clicking the preview or entering percentages. Add reviewed labels, adjust the region width/height, and order the reveals. No clinical region is chosen automatically. Labels support up to 120 characters; each region dimension is 2–100% of the source image (initial size 24%).
7. Save and verify claims, quantities, terminology, questions, labels, and selected source regions. Approve that revision by name. Editing these items or changing the source transcription/check state resets narration approval; review or regenerate the explanation against the changed source.
8. Choose an approved slide range, Whiteboard or Studio visual direction, narrator, pace, and caption preference. Use **Preview voice** to audition the fixed sample before exporting. Its sample contains no project narration.
9. Inspect the final video, source-region reveals, voice pronunciation, caption timing, and interactive package before distributing it.

Kokoro voices: `af_heart` (Warm American, female), `af_bella` (Conversational American, female), `am_michael` (Clear American, male), and `bf_emma` (British narrator, female). The default is `af_heart` when Kokoro is available.

Ollama writes the script; Kokoro turns the reviewed script into speech. This application does not use Voicebox or Qwen TTS. Improving the writing and improving the voice are separate review steps.

Drafting automatically reads a rendered image-only slide with local OCR if it has no saved transcription. If OCR is unavailable, it asks for setup or manually entered image text. The detected source and draft are saved together only after both writing passes succeed. Automatically detected text remains unchecked; compare it with the slide before approval.

The learner's reading transcript uses complete speech passages with larger type, search highlights, and a **Show current passage** control. Short captions remain separate for video viewing. Existing exports are immutable; export again to include an updated script or learner interface.

Subtitle boundaries are estimated from synthesized speech-block durations. They are **not forced-aligned word timings**. Caption and visual-reveal synchronization require playback review, especially for long sentences and medical terminology.

Supplied medical examples intentionally have **no automatic clinical approval**. The nonclinical three-slide demonstration in `data/validation` is a software test fixture.

## Development and checks

```powershell
.\.venv\Scripts\python.exe -m pytest -q
npm.cmd --prefix frontend run build
# Uses installed rendering, speech and FFmpeg components. Generates synthetic test content.
# Inspect the script for its selected engine/style; fixture coverage is recorded in docs/VALIDATION.md.
.\.venv\Scripts\python.exe scripts\verify_pipeline.py
# Private source audit (replace PROJECT_ID with an imported project ID):
.\.venv\Scripts\python.exe scripts\audit_slide_sources.py --project-id PROJECT_ID --output data\validation\source-audit.json
# Private draft comparison; never grants approval:
.\.venv\Scripts\python.exe scripts\evaluate_narration.py --project-id PROJECT_ID --model qwen3.5:9b --slides 4,6,13 --skip-baseline
```

The API schema is available at `/openapi.json`. CDN-based API documentation pages are disabled to keep the runtime independent of internet access. For frontend development, run the backend and `npm.cmd --prefix frontend run dev`; Vite proxies `/api` to port 8765.

Tests cover review invalidation, stale revision conflicts, job locks, upload validation, XML entity rejection, macro/external relationship removal, caption handling, local model guards, and package escaping. The integration script runs extraction, rendering, real neural speech, video assembly, and interactive packaging. See `docs/VALIDATION.md` for the current validation record.

## Local storage and architecture

```text
React interface (localhost)
        |
FastAPI + SQLite review records
        |
Safe OOXML extraction -> PowerPoint slide images -> optional local OCR + checked transcription
        |
Local Ollama draft -> local editorial/source-comparison pass -> practitioner edit and approval
        |
Local Kokoro/Piper voice -> estimated captions + authored source-region scenes -> FFmpeg
        |
MP4 + interactive HTML package + review manifest
```

`data/` contains private presentation content and exports. Back it up with the app stopped. `models/` holds installed voice models, the Kokoro voice bank, and verified OCR assets under `models/ocr/`. Neither folder is version-controlled. Set `NARRATE_DATA` to change storage and `NARRATE_VOICE` to choose an installed Piper `.onnx` file with its matching JSON config. `NARRATE_KOKORO_MODEL` and `NARRATE_KOKORO_VOICES` override the local Kokoro model and voice-bank paths; `NARRATE_OCR_MODELS` sets the directory containing the complete verified OCR asset set. The Kokoro download script records downloaded asset sources, sizes, and calculated hashes in `models/kokoro-manifest.json`; runtime synthesis never initiates this download.

On non-Windows systems, the rendering adapter supports an explicit LibreOffice executable through `NARRATE_SOFFICE`; cross-platform packaging and verification remain pending.

## Boundaries and next work

- Clinical validity requires expert review. Model prompts and number checks cannot prove that a narration is scientifically accurate or that all original facts were preserved.
- Static slide extraction preserves composition, not PowerPoint animations, interactive controls, or embedded video playback. Authored region reveals add new motion to the extracted source; they do not reconstruct the original animations or generate medically validated anatomical motion. Active embedded objects are removed from the rendering copy.
- OCR transcribes visible text; it does not understand anatomy, verify references, or resolve conflicts between slides and notes. Reading order, punctuation, quantities, and units may be wrong even at high recognition confidence. Visual reasoning, automatic reference verification, a medical pronunciation dictionary, multilingual quality evaluation, SCORM/xAPI, collaborative identity, and a signed desktop installer are not implemented.
- The two-pass narration editor is still being evaluated on the supplied medical slides. Readability diagnostics and a larger local model do not establish source fidelity or clinical validity. Qualifier changes and omitted source details remain explicit review targets.
- The English voices are general neural voices. Medication and anatomical pronunciation require listening review. Paragraph-block synthesis improves continuity but does not guarantee natural delivery or pronunciation accuracy. Subtitle timing remains estimated.
- Reviewers are locally entered names, not authenticated signatures. Local data is not encrypted by this application. This is a single-user workstation tool, not a multi-user hospital deployment.
- The application makes no remote inference requests and disables HTTP proxy inheritance for its local AI calls. PowerPoint, Ollama, and other independently installed programs are not OS-network-sandboxed by this application. Use an OS firewall/disconnected environment for a strict air gap.
- A running Ollama request may take up to its timeout to acknowledge cancellation. OCR checks cancellation before and after native inference, so an in-progress inference call must return first. Long imports and very large decks need additional performance profiling.

See `docs/ROADMAP.md` for a production-readiness plan with acceptance criteria.

The complete processing flow and review boundaries are documented in [docs/PIPELINE.md](docs/PIPELINE.md).

## Dependency licensing

Dependencies, Kokoro model/voice assets, and alternative voices have their own terms. Piper is GPL-3.0; PyMuPDF is AGPL/commercial dual-licensed; FFmpeg licensing depends on its build (libx264 commonly implies GPL). PowerPoint requires the user's license. Review these before redistributing a packaged commercial product. This repository does not assign a public open-source license to the application code.

Official implementation references: [React](https://react.dev/versions), [Vite](https://vite.dev/guide/), [Ollama API](https://docs.ollama.com/api/generate), [Piper](https://github.com/OHF-Voice/piper1-gpl).
