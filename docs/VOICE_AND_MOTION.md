# Voice and motion

## Expressive offline voice

Optional **Qwen3-TTS 1.7B CustomVoice** adds Aiden and Ryan with warm, clear and engaging instruction presets. This is a different model from the Qwen writing model in Ollama. No Voicebox integration or voice cloning is used. Kokoro remains a faster CPU-friendly alternative; compare the actual recordings before choosing a narrator.

Explicit setup from the repository:

```powershell
.\.venv\Scripts\python.exe scripts\setup_qwen_voice.py --install-runtime --download-model
```

Setup creates a separate runtime in `models/qwen-tts-runtime`, installs pinned CUDA PyTorch/Qwen dependencies, and downloads a pinned official model revision with verified checksums (about 4.52 GB of model assets). Ordinary generation loads only local paths, sets Hugging Face offline flags and blocks Python socket connection/DNS calls in the worker. This is not an operating-system network sandbox for every external dependency.

The optional adapter requires an NVIDIA CUDA GPU and checks free memory before loading. Its process exits after the requested narration, releasing GPU memory. Model generation is slower than Kokoro; consult the measured sample results in `VALIDATION.md`. Delivery pace is instruction-based, not an exact speed multiplier. Narration text is preserved; no guessed pronunciation substitutions or invented medical explanations are inserted.

Each generated WAV has measured speech-block cues and a local `.qwen.json` report with text hash, model revision, elapsed time, and peak allocated GPU memory. Subtitles estimate timing within these measured blocks. PCM inspection measures sample rate, RMS/peak level, near-clipping and long silence; it cannot certify naturalness or medical pronunciation.

## Evidence review stays separate from voice

Source fidelity uses exact stored passage IDs, two independent complete alignment passes, and a challenge to proposed discrepancies. Potential findings, unresolved comparisons, refuted proposals and lexical hints remain visible for practitioner decisions. Reports are bound to source/script hashes, evaluator code and model identity, with a byte-based context budget that rejects insufficient room. Case-sensitive units are preserved by the exact-text guard.

This evaluator does not rewrite the script, approve medical content, or certify the spoken recording. Voice synthesis continues to receive the saved narration unchanged; measured PCM/video results in [VALIDATION.md](VALIDATION.md) remain separate evidence. The local eight-case `scripts/calibrate_evidence_review.py` experiment is development calibration, not a clinical or held-out benchmark; no result is claimed here while that run is in progress.

## Visual direction

- **Guided focus:** smooth camera movement into authored regions, a hold for explanation, then a return to context. Magnification is capped at 3× and limited to keep the selected region in view. It magnifies existing pixels; small raster text may remain low resolution.
- **Whiteboard:** source regions are revealed in authored order, ending on the full source.
- **Studio:** full-slide framing with timed source callouts.
- **PowerPoint effects:** Windows PowerPoint renders supported existing animations/transitions from a sanitized temporary copy. Page-click effects advance automatically; automatic effect groups remain together. The complete native timeline is uniformly fitted to narration and its timing scale is recorded. Shape-triggered interactions, embedded media and indefinite effects require source authoring changes. Narration shorter than the supported animation timeline fails explicitly.

Region cues can use automatic spacing or an authored narration paragraph in Guided focus/Whiteboard. Paragraph timing follows measured speech-block boundaries and remains distinct from word-level forced alignment. Both supplied 60-slide decks contain zero native animation timelines and zero transitions; native mode alone therefore leaves their slides static.

Original decks are never edited. No mode infers an anatomical procedure or creates new clinical imagery from the slides. Source regions and labels are part of the revision requiring practitioner review.

Native export renders one slide per narration segment. Entry transitions start from that isolated slide's background; transitions that rely on the previous slide's pixels are not reproduced exactly. Per-slide effect schedules, timing scale and transition policy are included in output quality metadata.
