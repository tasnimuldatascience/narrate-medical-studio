import hashlib
import json
import os
from pathlib import Path
import subprocess
import socket
import sys
import threading
from types import SimpleNamespace
import wave

import numpy as np
import pytest

from backend import qwen_voice as qwen
from backend.media import Cancelled


@pytest.fixture
def assets(tmp_path,monkeypatch):
    model=tmp_path/'model'
    model.mkdir()
    (model/'config.json').write_bytes(b'{}')
    manifest={'repository':qwen.REPOSITORY,'revision':qwen.REVISION,
        'files':{'config.json':{'size':2,'sha256':hashlib.sha256(b'{}').hexdigest()}}}
    (model/'narrate-manifest.json').write_text(json.dumps(manifest))
    runtime=tmp_path/'runtime'
    runtime.mkdir()
    python=runtime/'python.exe'
    python.write_bytes(b'placeholder')
    (runtime/'narrate-runtime.json').write_text(json.dumps(qwen.RUNTIME_VERSIONS))
    monkeypatch.setattr(qwen,'MODEL_DIR',model)
    monkeypatch.setattr(qwen,'RUNTIME_DIR',runtime)
    monkeypatch.setattr(qwen,'PYTHON',python)
    monkeypatch.setattr(qwen,'REQUIRED',{'config.json'})
    monkeypatch.setattr(qwen,'_verified',{})
    return model


def test_assets_require_complete_local_pinned_snapshot(assets):
    assert qwen.available()
    qwen.validate_assets(full=True)
    (assets/'config.json').write_bytes(b'[]')
    with pytest.raises(ValueError,match='checksum'):
        qwen.validate_assets(full=True)
    (assets/'config.json').unlink()
    assert not qwen.available()


def test_asset_manifest_cannot_escape_model_folder(assets):
    path=assets/'narrate-manifest.json'
    manifest=json.loads(path.read_text())
    manifest['files']['../private']={'size':1,'sha256':'unused'}
    path.write_text(json.dumps(manifest))
    with pytest.raises(ValueError,match='manifest'):
        qwen.validate_assets()


def test_wrong_model_release_is_rejected(assets):
    path=assets/'narrate-manifest.json'
    manifest=json.loads(path.read_text())
    manifest['repository']='Someone/Voice-Cloner'
    path.write_text(json.dumps(manifest))
    assert not qwen.available()


def test_network_model_folder_is_rejected_without_reading_it(monkeypatch):
    monkeypatch.setattr(qwen,'MODEL_DIR',Path('//server/share/model'))
    with pytest.raises(ValueError,match='local disk'):
        qwen.validate_assets()


@pytest.mark.parametrize('marker',[
    {},{'qwen_tts':'0.1.1'},
    {**qwen.RUNTIME_VERSIONS,'torch':'2.9.1+cpu'},
    {**qwen.RUNTIME_VERSIONS,'torchaudio':'2.8.0+cu128'},
    {**qwen.RUNTIME_VERSIONS,'qwen_tts':'0.1.0'},
    {**qwen.RUNTIME_VERSIONS,'status':'installing'},
    [],None,
])
def test_readiness_requires_all_pinned_runtime_versions(assets,monkeypatch,marker):
    (qwen.RUNTIME_DIR/'narrate-runtime.json').write_text(json.dumps(marker))
    monkeypatch.setattr(qwen,'validate_assets',lambda **kwargs:pytest.fail('Incomplete runtime reached model readiness'))
    assert qwen.available() is False


def test_readiness_requires_well_formed_local_marker(assets):
    marker=qwen.RUNTIME_DIR/'narrate-runtime.json'
    marker.write_text('{broken')
    assert qwen.available() is False
    marker.unlink()
    assert qwen.available() is False


def test_failed_runtime_repair_clears_previous_readiness(assets,monkeypatch):
    from scripts import setup_qwen_voice
    assert qwen.available()
    def fail(*args,**kwargs):
        raise subprocess.CalledProcessError(1,args[0])
    monkeypatch.setattr(setup_qwen_voice.subprocess,'run',fail)
    with pytest.raises(subprocess.CalledProcessError):
        setup_qwen_voice.install_runtime()
    assert qwen.available() is False
    assert json.loads((qwen.RUNTIME_DIR/'narrate-runtime.json').read_text())=={'status':'installing'}


@pytest.mark.parametrize('text,voice,rate,style',[
    ('','Ryan',1,'warm'),('A'*12001,'Ryan',1,'warm'),
    ('Hello','arbitrary reference voice',1,'warm'),('Hello','Ryan',float('nan'),'warm'),
    ('Hello','Ryan',1.5,'warm'),('Hello','Ryan',1,'arbitrary instruction'),
])
def test_request_validation(text,voice,rate,style):
    with pytest.raises(ValueError):
        qwen.validate_request(text,voice,rate,style)


def test_offline_environment_overrides_online_parent_settings(monkeypatch):
    monkeypatch.setenv('HF_HUB_OFFLINE','0')
    env=qwen.offline_environment()
    assert env['HF_HUB_OFFLINE']==env['TRANSFORMERS_OFFLINE']=='1'
    assert env['HF_HUB_DISABLE_TELEMETRY']==env['DO_NOT_TRACK']=='1'
    assert env['GRADIO_ANALYTICS_ENABLED']=='False'


def test_process_adapter_returns_measured_audio_and_releases_job(assets,tmp_path,monkeypatch):
    calls=[]
    class Process:
        returncode=0
        def __init__(self,args,**kwargs):
            calls.append((args,kwargs))
            request=json.loads(Path(args[-1]).read_text())
            output=Path(request['output'])
            with wave.open(str(output),'wb') as audio:
                audio.setparams((1,2,24000,0,'NONE','not compressed'))
                audio.writeframes(b'\0\0'*24000)
            output.with_suffix('.json').write_text(json.dumps({
                'duration':1,'cues':[{'start':0,'end':1,'text':request['text']}]}))
        def poll(self):return 0
    monkeypatch.setattr(qwen.subprocess,'Popen',Process)
    output=tmp_path/'result.wav'
    cues,duration=qwen.synthesize('Hello.',output,'Aiden',1,threading.Event(),style='clear')
    assert duration==1 and cues[0]['text']=='Hello.'
    assert output.is_file() and output.with_suffix('.qwen.json').is_file()
    assert calls[0][0][0]==str(qwen.PYTHON)
    assert calls[0][1]['env']['HF_HUB_OFFLINE']=='1'
    assert not list(tmp_path.glob('.qwen-*'))
    assert not qwen._lock.locked()


def test_cancellation_terminates_worker_without_publishing_audio(assets,tmp_path,monkeypatch):
    cancel=threading.Event()
    stopped=[]
    class Process:
        running=True
        def __init__(self,*args,**kwargs):cancel.set()
        def poll(self):return None if self.running else 1
        def terminate(self):self.running=False;stopped.append(True)
        def wait(self,timeout=None):return 1
    monkeypatch.setattr(qwen.subprocess,'Popen',Process)
    output=tmp_path/'cancelled.wav'
    with pytest.raises(Cancelled):
        qwen.synthesize('Hello.',output,'Ryan',1,cancel)
    assert stopped==[True]
    assert not output.exists()
    assert not list(tmp_path.glob('.qwen-*'))
    assert not qwen._lock.locked()


def test_worker_uses_only_local_weights_and_measures_complete_thoughts(assets,tmp_path,monkeypatch):
    for name in ('HF_HUB_OFFLINE','TRANSFORMERS_OFFLINE','HF_DATASETS_OFFLINE',
                 'HF_HUB_DISABLE_TELEMETRY','DO_NOT_TRACK','GRADIO_ANALYTICS_ENABLED',
                 'TOKENIZERS_PARALLELISM','PYTHONUTF8'):
        monkeypatch.setenv(name,os.environ.get(name,''))
    calls=[]
    class Model:
        @staticmethod
        def from_pretrained(path,**kwargs):
            assert path==str(assets)
            assert kwargs['local_files_only'] is True
            assert kwargs['trust_remote_code'] is False
            return Model()
        def generate_custom_voice(self,**kwargs):
            calls.append(kwargs)
            return [np.full(24000,.05,dtype=np.float32)],24000
    torch=SimpleNamespace(cuda=SimpleNamespace(is_available=lambda:True,
        mem_get_info=lambda:(8*1024**3,8*1024**3),max_memory_allocated=lambda:1024**3),
        bfloat16='bf16',set_num_threads=lambda count:None,manual_seed=lambda seed:None)
    monkeypatch.setitem(sys.modules,'torch',torch)
    monkeypatch.setitem(sys.modules,'qwen_tts',SimpleNamespace(Qwen3TTSModel=Model))
    monkeypatch.setitem(sys.modules,'onnxruntime',SimpleNamespace(disable_telemetry_events=lambda:None))
    # Restore global worker-only socket changes when this in-process test ends.
    for owner,name in [(socket.socket,'connect'),(socket.socket,'connect_ex'),
                       (socket,'create_connection'),(socket,'getaddrinfo')]:
        monkeypatch.setattr(owner,name,getattr(owner,name))
    output=tmp_path/'speech.wav'
    request=tmp_path/'request.json'
    request.write_text(json.dumps({'text':'First thought.\n\nSecond thought.','voice':'Aiden',
        'rate':.8,'style':'engaging','output':str(output)}))
    qwen.worker(request)
    assert [call['text'] for call in calls]==['First thought.','Second thought.']
    assert all(call['speaker']=='Aiden' and 'slower' in call['instruct'] for call in calls)
    report=json.loads(output.with_suffix('.json').read_text())
    assert report['duration']==2.18
    assert report['text_sha256']==hashlib.sha256(b'First thought.\n\nSecond thought.').hexdigest()
    assert report['cues'][1]['start']==1.18
    assert report['peak_gpu_memory_mib']==1024
