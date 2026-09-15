"""Measured PCM checks, deliberately separate from human listening judgments."""
import math
import wave
from pathlib import Path

import numpy as np


def inspect_audio(path):
    with wave.open(str(Path(path)), 'rb') as wav:
        if wav.getsampwidth()!=2 or wav.getcomptype()!='NONE':
            raise ValueError('Audio inspection requires uncompressed 16-bit PCM.')
        rate, channels, count=wav.getframerate(),wav.getnchannels(),wav.getnframes()
        samples=np.frombuffer(wav.readframes(count),dtype='<i2').astype(np.float64)/32768
    if not samples.size or not np.isfinite(samples).all():
        raise ValueError('Voice output is empty or contains invalid samples.')
    peak=float(np.max(np.abs(samples)))
    rms=float(np.sqrt(np.mean(samples*samples)))
    # Window energy across channels avoids false silence from phase cancellation.
    frame_energy=np.mean(samples.reshape(-1,channels)**2,axis=1)
    window=max(1,round(rate*.02))
    silence=[]
    for start in range(0,count,window):
        silence.append(float(np.mean(frame_energy[start:start+window]))<10**(-50/10))
    longest=run=0
    for quiet in silence:
        run=run+1 if quiet else 0
        longest=max(longest,run)
    clipping=float(np.mean(np.abs(samples)>=32760/32768))
    warnings=[]
    if peak<.001: warnings.append('Voice output is effectively silent.')
    if clipping>.001: warnings.append('More than 0.1% of samples approach digital clipping; listen for distortion.')
    if longest*.02>3: warnings.append('A silence longer than three seconds needs listening review.')
    return {'version':'pcm-audio-check-v1','duration_seconds':count/rate,
        'sample_rate':rate,'channels':channels,'peak_dbfs':round(20*math.log10(max(peak,1e-12)),2),
        'rms_dbfs':round(20*math.log10(max(rms,1e-12)),2),
        'near_clipping_fraction':round(clipping,6),'longest_silence_seconds':round(min(count/rate,longest*.02),3),
        'warnings':warnings,'listening_review_required':True,
        'not_assessed':['naturalness','medical pronunciation','spoken source fidelity','listener comprehension']}
