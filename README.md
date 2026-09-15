# Narrate Medical Studio

A local application for turning medical PowerPoint presentations into reviewed narration, captioned video, and interactive learning packages. Built with React, TypeScript, Vite, FastAPI, SQLite, Ollama, Kokoro, optional Piper, and FFmpeg.

**Status: working development release, not a validated clinical product.** The workflow accepts different presentations and specialties. The supplied injection decks are test inputs, not hard-coded templates. No presentation content is submitted to a cloud API by this application.

## What works

- Import `.pptx` and `.pptm`, inspect slide text, notes, editable tables, image counts, and reference URLs.
- Render high-resolution slide previews using installed Microsoft PowerPoint on Windows, with macros disabled and a sanitized rendering copy.
- Review original visuals beside the script. Draft narration with an installed local Ollama model or edit the supplied text and notes directly.
- Flag numerical content, limited sources, unreadable characters, tables, image interpretation, and model-reported uncertainty.
- Use a cinematic production workspace with source/script review, scene navigation, accessible dialogs, and explicit readiness feedback.
- Add source-grounded multiple-choice knowledge checks with feedback.
- Author up to six labeled source regions per slide. Set their order, center, width, and height against the actual slide preview; regions are clipped at image edges.
- Choose **Whiteboard** to reveal authored source regions progressively and finish on the original slide, or **Studio** to retain the full slide with timed callouts. Slides without cues show their full source visual. These are animations of existing source material, not generated medical anatomy.
- Audition four local Kokoro narrators using a fixed nonmedical sample in Setup or the export dialog. Kokoro synthesizes complete thoughts/paragraph blocks rather than each subtitle fragment; Piper and Windows voice remain alternatives.
- Record a named review of each slide revision. Any script, question, cue label, cue position, region size, or cue order edit resets approval. The backend blocks export of unapproved slides.
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
- Ollama with an installed local model, such as `qwen3:4b`, for optional AI drafting.

Run `Setup.ps1` for explicit dependency and model installation. It recommends Kokoro by default and offers Piper, both engines, or skipping voice downloads. Setup needs internet access. Afterwards, ordinary authoring and export operate locally. To prepare a disconnected machine, transfer the installed runtime environment, dependencies, and model assets using your organization's software distribution process. A portable offline installer is not yet provided.

```powershell
# Equivalent manual setup
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
npm.cmd --prefix frontend ci
npm.cmd --prefix frontend run build
# Recommended: Kokoro model and voice bank (setup-only network download)
.\.venv\Scripts\python.exe scripts\download_kokoro.py
# Optional compact alternative:
.\.venv\Scripts\python.exe -m piper.download_voices en_US-lessac-medium --download-dir models
# Install the model explicitly during setup, if needed:
ollama pull qwen3:4b
.\Start.ps1
```

The UI's Setup page reports renderer, video, voice, and local model availability. Missing runtime components produce an error rather than switching to a cloud service.

## Authoring workflow

1. Import your presentation and render its previews.
2. Set the specialty and learner audience under Setup.
3. Inspect each visual and its extracted source. Draft or edit a concise explanation. On image-only slides, supply a reviewed explanation; extraction does not transcribe image text.
4. Optionally add a question, three choices, the correct answer, and a source-grounded explanation.
5. In **Visual story**, explicitly place source regions by clicking the preview or entering percentages. Add reviewed labels, adjust the region width/height, and order the reveals. No clinical region is chosen automatically. Labels support up to 120 characters; each region dimension is 2–100% of the source image (initial size 24%).
6. Save and verify claims, quantities, terminology, questions, labels, and selected source regions. Approve that revision by name. Editing these items resets approval.
7. Choose an approved slide range, Whiteboard or Studio visual direction, narrator, pace, and caption preference. Use **Preview voice** to audition the fixed sample before exporting. Its sample contains no project narration.
8. Inspect the final video, source-region reveals, voice pronunciation, caption timing, and interactive package before distributing it.

Kokoro voices: `af_heart` (Warm American, female), `af_bella` (Conversational American, female), `am_michael` (Clear American, male), and `bf_emma` (British narrator, female). The default is `af_heart` when Kokoro is available.

Subtitle boundaries are estimated from synthesized speech-block durations. They are **not forced-aligned word timings**. Caption and visual-reveal synchronization require playback review, especially for long sentences and medical terminology.

Supplied medical examples intentionally have **no automatic clinical approval**. The nonclinical three-slide demonstration in `data/validation` is a software test fixture.

## Development and checks

```powershell
.\.venv\Scripts\python.exe -m pytest -q
npm.cmd --prefix frontend run build
# Uses installed rendering, speech and FFmpeg components. Generates synthetic test content.
# Inspect the script for its selected engine/style; fixture coverage is recorded in docs/VALIDATION.md.
.\.venv\Scripts\python.exe scripts\verify_pipeline.py
```

The API schema is available at `/openapi.json`. CDN-based API documentation pages are disabled to keep the runtime independent of internet access. For frontend development, run the backend and `npm.cmd --prefix frontend run dev`; Vite proxies `/api` to port 8765.

Tests cover review invalidation, stale revision conflicts, job locks, upload validation, XML entity rejection, macro/external relationship removal, caption handling, local model guards, and package escaping. The integration script runs extraction, rendering, real neural speech, video assembly, and interactive packaging. See `docs/VALIDATION.md` for the current validation record.

## Local storage and architecture

```text
React interface (localhost)
        |
FastAPI + SQLite review records
        |
Safe OOXML extraction -> PowerPoint slide images
        |
Local Ollama draft -> practitioner edit and approval
        |
Local Kokoro/Piper voice -> estimated captions + authored source-region scenes -> FFmpeg
        |
MP4 + interactive HTML package + review manifest
```

`data/` contains private presentation content and exports. Back it up with the app stopped. `models/` holds installed voice models and the Kokoro voice bank. Neither folder is version-controlled. Set `NARRATE_DATA` to change storage and `NARRATE_VOICE` to choose an installed Piper `.onnx` file with its matching JSON config. `NARRATE_KOKORO_MODEL` and `NARRATE_KOKORO_VOICES` override the local Kokoro model and voice-bank paths. The download script records downloaded asset sources, sizes, and calculated hashes in `models/kokoro-manifest.json`; runtime synthesis never initiates this download.

On non-Windows systems, the rendering adapter supports an explicit LibreOffice executable through `NARRATE_SOFFICE`; cross-platform packaging and verification remain pending.

## Boundaries and next work

- Clinical validity requires expert review. Model prompts and number checks cannot prove that a narration is scientifically accurate or that all original facts were preserved.
- Static slide extraction preserves composition, not PowerPoint animations, interactive controls, or embedded video playback. Authored region reveals add new motion to the extracted source; they do not reconstruct the original animations or generate medically validated anatomical motion. Active embedded objects are removed from the rendering copy.
- OCR, visual reasoning, automatic reference verification, a medical pronunciation dictionary, multilingual quality evaluation, SCORM/xAPI, collaborative identity, and a signed desktop installer are not implemented.
- The English voices are general neural voices. Medication and anatomical pronunciation require listening review. Paragraph-block synthesis improves continuity but does not guarantee natural delivery or pronunciation accuracy. Subtitle timing remains estimated.
- Reviewers are locally entered names, not authenticated signatures. Local data is not encrypted by this application. This is a single-user workstation tool, not a multi-user hospital deployment.
- The application makes no remote inference requests and disables HTTP proxy inheritance for its local AI calls. PowerPoint, Ollama, and other independently installed programs are not OS-network-sandboxed by this application. Use an OS firewall/disconnected environment for a strict air gap.
- A running Ollama request may take up to its timeout to acknowledge cancellation. Long imports and very large decks need additional performance profiling.

See `docs/ROADMAP.md` for a production-readiness plan with acceptance criteria.

The complete processing flow and review boundaries are documented in [docs/PIPELINE.md](docs/PIPELINE.md).

## Dependency licensing

Dependencies, Kokoro model/voice assets, and alternative voices have their own terms. Piper is GPL-3.0; PyMuPDF is AGPL/commercial dual-licensed; FFmpeg licensing depends on its build (libx264 commonly implies GPL). PowerPoint requires the user's license. Review these before redistributing a packaged commercial product. This repository does not assign a public open-source license to the application code.

Official implementation references: [React](https://react.dev/versions), [Vite](https://vite.dev/guide/), [Ollama API](https://docs.ollama.com/api/generate), [Piper](https://github.com/OHF-Voice/piper1-gpl).
