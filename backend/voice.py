"""Expressive local narration. Caption boundaries never dictate short speech chunks."""
import os
import threading
import wave
from pathlib import Path
import numpy as np
from . import store
from .speech_text import natural_blocks

VOICES={'af_heart':'en-us','af_bella':'en-us','am_michael':'en-us','bf_emma':'en-gb'}
MODEL=Path(os.environ.get('NARRATE_KOKORO_MODEL',store.ROOT/'models'/'kokoro-v1.0.onnx'))
VOICE_BANK=Path(os.environ.get('NARRATE_KOKORO_VOICES',store.ROOT/'models'/'voices-v1.0.bin'))
_model=None
_lock=threading.Lock()

def available():
    return MODEL.is_file() and VOICE_BANK.is_file()

def synthesize(text,output,voice,rate,cancel):
    global _model
    from .media import check
    if voice not in VOICES:
        raise ValueError('Choose a supported narrator voice.')
    if not available():
        raise ValueError('Kokoro is not installed. Run the explicit voice setup download first.')
    blocks=natural_blocks(text)
    if not blocks:
        raise ValueError('Narration is empty.')
    with _lock:
        check(cancel)
        if _model is None:
            from kokoro_onnx import Kokoro
            _model=Kokoro(str(MODEL),str(VOICE_BANK))
        frames=[];cues=[];cursor=0.;sample_rate=24000
        # Each model call gets a complete thought rather than a subtitle fragment.
        for i,block in enumerate(blocks):
            check(cancel)
            samples,sample_rate=_model.create(block,voice=voice,speed=rate,lang=VOICES[voice],
                sentence_pause=.24,clause_pause=.08,trim=True)
            check(cancel)
            samples=np.asarray(samples,dtype=np.float32)
            if not len(samples) or not np.isfinite(samples).all():
                raise ValueError('The local voice returned invalid audio. Try another narrator.')
            duration=len(samples)/sample_rate
            cues.append({'start':cursor,'end':cursor+duration,'text':block})
            frames.append(samples)
            cursor+=duration
            if i<len(blocks)-1:
                # A brief thought break; no random tempo or pitch perturbations.
                pause=np.zeros(round(sample_rate*.18),dtype=np.float32)
                frames.append(pause);cursor+=len(pause)/sample_rate
        audio=np.concatenate(frames)
        peak=float(np.max(np.abs(audio)))
        if peak>.97:
            audio*=.97/peak
        pcm=(np.clip(audio,-1,1)*32767).astype('<i2')
        with wave.open(str(output),'wb') as wav:
            wav.setnchannels(1);wav.setsampwidth(2);wav.setframerate(sample_rate);wav.writeframes(pcm.tobytes())
        return cues,cursor
