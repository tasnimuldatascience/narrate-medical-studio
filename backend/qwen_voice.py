"""Optional expressive Qwen3-TTS in a separate, short-lived local process.

No cloning, reference audio, remote model IDs, or arbitrary voice instructions
are accepted. Importing this adapter does not import torch or occupy GPU memory.
"""
import argparse
import hashlib
import json
import math
import os
from pathlib import Path
import shutil
import subprocess
import sys
import threading
import time
import uuid
import wave

ROOT=Path(__file__).resolve().parents[1]
RUNTIME_DIR=ROOT/'models'/'qwen-tts-runtime'
PYTHON=RUNTIME_DIR/('Scripts/python.exe' if os.name=='nt' else 'bin/python')
MODEL_DIR=Path(os.environ.get('NARRATE_QWEN_TTS_MODEL',ROOT/'models'/'qwen3-tts-1.7b-customvoice'))
if not str(MODEL_DIR).startswith(('\\\\','//')):
    MODEL_DIR=MODEL_DIR.resolve()
REPOSITORY='Qwen/Qwen3-TTS-12Hz-1.7B-CustomVoice'
REVISION='f00cf133b78d3c2c35857faba3b1be9b98c4f971'
VOICES={'Ryan':'Expressive English male','Aiden':'Warm American English male'}
RUNTIME_VERSIONS={'qwen_tts':'0.1.1','torch':'2.9.1+cu128','torchaudio':'2.9.1+cu128'}
STYLES={
    'warm':'Speak warmly and conversationally, like a thoughtful teacher explaining to a colleague. Use natural emphasis and gentle pauses between ideas. Avoid a flat reading cadence. Keep clear articulation.',
    'clear':'Speak with calm confidence and clear articulation. Use moderate natural emphasis on key terms and short pauses at thought boundaries. Keep the delivery professional and unhurried.',
    'engaging':'Speak with lively but measured teaching energy. Vary your intonation naturally, emphasize the important words, and pause briefly between ideas. Remain clear and professional.',
}
REQUIRED={'config.json','generation_config.json','tokenizer_config.json','preprocessor_config.json',
          'vocab.json','merges.txt','model.safetensors',
          'speech_tokenizer/config.json','speech_tokenizer/model.safetensors',
          'speech_tokenizer/preprocessor_config.json'}
_verified={}
_lock=threading.Lock()


def file_hash(path):
    with Path(path).open('rb') as stream:
        return hashlib.file_digest(stream,'sha256').hexdigest()


def validate_assets(full=False):
    if str(MODEL_DIR).startswith(('\\\\','//')):
        raise ValueError('Qwen model files must be on a local disk, not a network share.')
    manifest=json.loads((MODEL_DIR/'narrate-manifest.json').read_text(encoding='utf-8'))
    if manifest.get('repository')!=REPOSITORY or manifest.get('revision')!=REVISION:
        raise ValueError('Qwen voice assets do not match the explicitly installed release.')
    files=manifest.get('files',{})
    if not REQUIRED.issubset(files):
        raise ValueError('Qwen voice assets are incomplete. Run explicit voice setup.')
    for name,record in files.items():
        relative=Path(name)
        if relative.is_absolute() or '..' in relative.parts:
            raise ValueError('Invalid Qwen voice asset manifest.')
        path=(MODEL_DIR/relative).resolve()
        if not path.is_relative_to(MODEL_DIR):
            raise ValueError('Qwen voice assets must remain in their local model folder.')
        stat=path.stat()
        if stat.st_size!=record['size']:
            raise ValueError('Qwen voice asset size mismatch. Run explicit voice setup.')
        stamp=(str(path),stat.st_size,stat.st_mtime_ns,stat.st_ctime_ns)
        if full and _verified.get(stamp)!=record['sha256']:
            if file_hash(path)!=record['sha256']:
                raise ValueError('Qwen voice asset checksum mismatch. Run explicit voice setup.')
            _verified[stamp]=record['sha256']
    return manifest


def available():
    try:
        ready=json.loads((RUNTIME_DIR/'narrate-runtime.json').read_text(encoding='utf-8'))
        if not isinstance(ready,dict) or ready.get('status','ready')!='ready':
            return False
        if not all(ready.get(name)==version for name,version in RUNTIME_VERSIONS.items()):
            return False
        return PYTHON.is_file() and bool(validate_assets())
    except (OSError,ValueError,KeyError,TypeError):
        return False


def offline_environment():
    env=os.environ.copy()
    env.update(HF_HUB_OFFLINE='1',TRANSFORMERS_OFFLINE='1',HF_DATASETS_OFFLINE='1',
               HF_HUB_DISABLE_TELEMETRY='1',DO_NOT_TRACK='1',GRADIO_ANALYTICS_ENABLED='False',
               TOKENIZERS_PARALLELISM='false',PYTHONUTF8='1')
    return env


def validate_request(text,voice,rate,style):
    if not isinstance(text,str) or not text.strip() or len(text)>12000:
        raise ValueError('Provide between 1 and 12000 characters of reviewed narration.')
    if voice not in VOICES or style not in STYLES:
        raise ValueError('Choose a supported Qwen narrator and delivery style.')
    if not isinstance(rate,(int,float)) or not math.isfinite(rate) or not .7<=rate<=1.4:
        raise ValueError('Choose a speaking pace from 0.7 to 1.4.')


def synthesize(text,output,voice,rate,cancel,style='warm'):
    from .media import check
    validate_request(text,voice,rate,style)
    check(cancel)
    if not available():
        raise ValueError('Qwen expressive voice is not installed. Run its explicit setup script.')
    validate_assets(full=True)
    if '://' in str(output) or str(output).startswith(('\\\\','//')):
        raise ValueError('Qwen voice output must be on a local disk.')
    output=Path(output).resolve()
    if output.suffix.lower()!='.wav':
        raise ValueError('Qwen voice output must be a local WAV file.')
    output.parent.mkdir(parents=True,exist_ok=True)
    while not _lock.acquire(timeout=.1):
        check(cancel)
    job=output.parent/f'.qwen-{uuid.uuid4().hex}'
    process=None
    try:
        check(cancel)
        job.mkdir()
        request={'text':text,'voice':voice,'rate':rate,'style':style,'output':str(job/'speech.wav')}
        (job/'request.json').write_text(json.dumps(request),encoding='utf-8')
        with (job/'worker.log').open('wb') as log:
            process=subprocess.Popen([str(PYTHON),'-m','backend.qwen_voice','--worker',str(job/'request.json')],
                cwd=ROOT,env=offline_environment(),stdout=log,stderr=subprocess.STDOUT,
                creationflags=subprocess.CREATE_NO_WINDOW if os.name=='nt' else 0)
            started=time.monotonic()
            while process.poll() is None:
                check(cancel)
                if time.monotonic()-started>1800:
                    raise ValueError('Qwen voice exceeded its 30-minute generation limit.')
                try:
                    process.wait(timeout=.2)
                except subprocess.TimeoutExpired:
                    pass
        if process.returncode:
            detail=(job/'worker.log').read_text(encoding='utf-8',errors='replace')[-2000:]
            raise ValueError('Qwen voice generation failed: '+detail)
        check(cancel)
        report=json.loads((job/'speech.json').read_text(encoding='utf-8'))
        with wave.open(str(job/'speech.wav'),'rb') as audio:
            duration=audio.getnframes()/audio.getframerate()
        if duration<=0 or abs(duration-report['duration'])>.01:
            raise ValueError('Qwen voice returned inconsistent audio timing.')
        (job/'speech.wav').replace(output)
        (job/'speech.json').replace(output.with_suffix('.qwen.json'))
        return report['cues'],duration
    finally:
        if process is not None and process.poll() is None:
            process.terminate()
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill();process.wait()
        try:
            if job.is_dir():
                shutil.rmtree(job)
        finally:
            _lock.release()


def worker(request_path):
    # Set offline switches before importing Hugging Face or the voice package.
    os.environ.update(offline_environment())
    import socket
    def no_network(*args,**kwargs):
        raise RuntimeError('Network access is disabled in the Qwen voice worker.')
    socket.socket.connect=no_network
    socket.socket.connect_ex=no_network
    socket.create_connection=no_network
    socket.getaddrinfo=no_network
    import numpy as np
    import torch
    import onnxruntime
    onnxruntime.disable_telemetry_events()
    from qwen_tts import Qwen3TTSModel
    from .speech_text import natural_blocks
    request=json.loads(Path(request_path).read_text(encoding='utf-8'))
    validate_request(request['text'],request['voice'],request['rate'],request['style'])
    validate_assets(full=True)
    if not torch.cuda.is_available():
        raise ValueError('This optional Qwen voice adapter requires a CUDA-capable NVIDIA GPU.')
    free,total=torch.cuda.mem_get_info()
    if free<5.5*1024**3:
        raise ValueError('Free GPU memory is insufficient. Unload the local writing model and retry Qwen voice.')
    torch.set_num_threads(4)
    torch.manual_seed(17)
    started=time.monotonic()
    model=Qwen3TTSModel.from_pretrained(str(MODEL_DIR),device_map='cuda:0',dtype=torch.bfloat16,
        attn_implementation='sdpa',local_files_only=True,trust_remote_code=False)
    frames=[];cues=[];cursor=0.;sample_rate=None
    instruction=STYLES[request['style']]
    if request['rate']<.95:
        instruction+=' Speak at a slower, deliberate pace.'
    elif request['rate']>1.05:
        instruction+=' Speak at a brisk but clearly understandable pace.'
    blocks=natural_blocks(request['text'])
    for index,block in enumerate(blocks):
        print(f'Generating thought {index+1}/{len(blocks)}',flush=True)
        audio,sr=model.generate_custom_voice(text=block,language='English',speaker=request['voice'],
            instruct=instruction,non_streaming_mode=True,max_new_tokens=1024)
        samples=np.asarray(audio[0],dtype=np.float32)
        if samples.ndim!=1 or not len(samples) or not np.isfinite(samples).all():
            raise ValueError('Qwen voice returned invalid audio.')
        if sample_rate is not None and sr!=sample_rate:
            raise ValueError('Qwen voice changed sample rate between passages.')
        sample_rate=sr
        duration=len(samples)/sr
        cues.append({'start':cursor,'end':cursor+duration,'text':block})
        frames.append(samples);cursor+=duration
        if index<len(blocks)-1:
            silence=np.zeros(round(sr*.18),dtype=np.float32)
            frames.append(silence);cursor+=len(silence)/sr
    combined=np.concatenate(frames)
    peak=float(np.max(np.abs(combined)))
    if peak>.97:
        combined*=.97/peak
    output=Path(request['output'])
    with wave.open(str(output),'wb') as wav:
        wav.setnchannels(1);wav.setsampwidth(2);wav.setframerate(sample_rate)
        wav.writeframes((np.clip(combined,-1,1)*32767).astype('<i2').tobytes())
    report={'engine':'Qwen3-TTS 1.7B CustomVoice','revision':REVISION,'voice':request['voice'],
            'text_sha256':hashlib.sha256(request['text'].encode('utf-8')).hexdigest(),
            'style':request['style'],'requested_rate':request['rate'],
            'pace_control':'instruction-based; not an exact time stretch',
            'duration':len(combined)/sample_rate,'sample_rate':sample_rate,'cues':cues,
            'elapsed_seconds':round(time.monotonic()-started,3),
            'peak_gpu_memory_mib':round(torch.cuda.max_memory_allocated()/1024**2,1)}
    output.with_suffix('.json').write_text(json.dumps(report,indent=2),encoding='utf-8')


if __name__=='__main__':
    parser=argparse.ArgumentParser()
    parser.add_argument('--worker',required=True,type=Path)
    worker(parser.parse_args().worker)
