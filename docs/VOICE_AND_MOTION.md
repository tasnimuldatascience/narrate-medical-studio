# Voice and motion

## Voice engines

| Engine | Best use | Runtime | Current limitation |
|---|---|---|---|
| Qwen3-TTS 1.7B CustomVoice | Expressive long-form teaching voice | Separate local CUDA environment | Slow; requires an NVIDIA GPU and pronunciation review |
| Kokoro ONNX | Faster high-quality local narration | CPU/ONNX Runtime | Less controllable expressiveness |
| Piper | Compact offline fallback | CPU | More synthetic delivery |
| Windows speech | Built-in fallback | Windows | Voice availability varies by workstation |

Voicebox is not integrated.

## Qwen3-TTS setup

```powershell
.\.venv\Scripts\python.exe scripts\setup_qwen_voice.py --install-runtime --download-model
```

The script creates `models/qwen-tts-runtime`, installs pinned Qwen/CUDA dependencies, and downloads the pinned official `Qwen/Qwen3-TTS-12Hz-1.7B-CustomVoice` assets. Model files are excluded from Git.

At runtime the adapter:

- validates the local manifest, required files, sizes, and hashes;
- loads only the local model path;
- enables Hugging Face offline flags and disables supported telemetry;
- blocks Python socket and DNS access in the worker;
- checks available CUDA memory before loading;
- exposes only the fixed Aiden and Ryan voices and reviewed delivery presets; and
- exits after the requested job so GPU memory is released.

No voice cloning, reference audio, arbitrary voice instructions, or remote model ID is accepted.

## Delivery and batching

The delivery presets are `warm`, `clear`, and `engaging`. Pace is an instruction to the model rather than an exact time stretch.

Narration is split into natural thought blocks. Adjacent blocks are passed to Qwen in batches of at most two. Outputs retain original order and individual lengths; the adapter reconstructs the slide WAV with a 0.18-second gap and stores a cue for every block.

On the development RTX 5070 Laptop GPU, a two-block benchmark reduced generation wall time from 47.85 to 31.71 seconds, a 34% reduction. Peak allocated memory increased from about 4.38 to 4.77 GiB. This was a speed and integrity check, not a listening-quality comparison.

Each completed WAV has a `.qwen.json` report containing the text hash, WAV hash, model revision, synthesis-recipe hash, settings, cues, duration, elapsed time, and peak allocated GPU memory. A cache entry is accepted only when those identities and the actual WAV structure still match.

## Measured full lecture

The supplied 60-slide draft used Qwen Aiden with the engaging preset:

| Measurement | Result |
|---|---:|
| Speech duration | 45.03 min |
| Final video duration | 47 min 11.625 sec |
| Narration generation | 96.22 min |
| Peak allocated GPU memory | 5093.4 MiB |
| Completed slide WAVs | 60 |

The complete video and package passed structural QA. These measurements do not certify naturalness, terminology pronunciation, or comprehension.

## Captions and reading transcript

Short subtitle cues and the learner reading transcript serve different purposes:

- captions are short phrases timed inside measured speech blocks;
- the reading transcript contains complete spoken passages and supports search and seeking.

The timing is estimated from generated block durations. There is no word-level forced alignment. Practitioners should check visible timing and spoken medical terms in the final artifact.

## Motion modes

### Guided focus

The camera moves into reviewed regions, holds during the linked explanation, and returns to full-slide context. Magnification is capped and constrained so the region remains visible.

### Whiteboard

Reviewed source regions appear in authored order and the scene ends with the full original slide.

### Studio

The full slide remains visible while timed labels and chapter framing direct attention.

### PowerPoint effects

On Windows, installed PowerPoint can render supported existing animations and transitions from a sanitized temporary copy. Click-driven effects advance automatically; automatic groups remain grouped. The existing effect timeline is fitted to the narration and the scale is recorded.

Shape-triggered interactions, indefinite effects, and embedded media are not supported. Entry transitions are rendered per slide and may not reproduce pixels from the preceding slide exactly. If narration is shorter than the supported effect timeline, rendering fails instead of silently dropping effects.

The supplied 60-slide decks contain no native animation timelines or transitions. Their motion therefore comes from reviewed Guided focus, Whiteboard, or Studio cues.

## Medical boundary

All motion is derived from supplied slide pixels and practitioner-authored regions. The system does not synthesize anatomical structures or infer how a procedure should move. A practitioner must review region selection, reveal order, full-source visibility, labels, captions, voice, and pronunciation before distribution.
