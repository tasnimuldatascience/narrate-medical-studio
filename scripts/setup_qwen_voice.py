"""Explicit optional Qwen3-TTS setup; runtime never downloads models.

Official source: https://github.com/QwenLM/Qwen3-TTS
Use --install-runtime and/or --download-model. Several GB of downloads and an
NVIDIA CUDA GPU are required. The main application environment is unchanged.
"""
import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import urllib.parse
import urllib.request
import venv

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from backend import qwen_voice


def fetch(url):
    return urllib.request.urlopen(urllib.request.Request(url,headers={'User-Agent':'Narrate-Explicit-Model-Setup/1.0'}),timeout=180)


def download_model():
    repo=qwen_voice.REPOSITORY
    revision=qwen_voice.REVISION
    with fetch(f'https://huggingface.co/api/models/{repo}/revision/{revision}?blobs=true') as response:
        info=json.load(response)
    if info['sha'] != revision:
        raise ValueError('Model revision did not match the pinned Qwen release.')
    target=qwen_voice.MODEL_DIR
    target.mkdir(parents=True,exist_ok=True)
    files={}
    for entry in info['siblings']:
        name=entry['rfilename']
        relative=Path(name)
        if relative.is_absolute() or '..' in relative.parts:
            raise ValueError('Unsafe model asset path.')
        if relative.suffix not in ('.json','.safetensors','.txt'):
            continue
        path=target/relative
        path.parent.mkdir(parents=True,exist_ok=True)
        expected=entry.get('lfs',{}).get('sha256')
        size=entry.get('size') or entry.get('lfs',{}).get('size')
        if not (path.is_file() and path.stat().st_size==size and
                (not expected or qwen_voice.file_hash(path)==expected)):
            url=f'https://huggingface.co/{repo}/resolve/{revision}/{urllib.parse.quote(name)}'
            temporary=path.with_suffix(path.suffix+'.part')
            print(f'Downloading official Qwen asset: {name} ({size} bytes)',flush=True)
            with fetch(url) as response,temporary.open('wb') as output:
                while chunk:=response.read(8*1024*1024):
                    output.write(chunk)
            if size and temporary.stat().st_size!=size:
                raise ValueError(f'Incomplete download: {name}')
            if expected and qwen_voice.file_hash(temporary)!=expected:
                raise ValueError(f'Model checksum mismatch: {name}')
            temporary.replace(path)
        digest=qwen_voice.file_hash(path)
        if not expected:
            data=path.read_bytes()
            git_digest=hashlib.sha1(f'blob {len(data)}\0'.encode()+data).hexdigest()
            if entry.get('blobId') and git_digest!=entry['blobId']:
                raise ValueError(f'Model configuration checksum mismatch: {name}')
        files[name]={'size':path.stat().st_size,'sha256':digest}
    manifest={'repository':repo,'revision':revision,'files':files,
              'source':'Official Qwen model repository; explicit setup download only.'}
    (target/'narrate-manifest.json').write_text(json.dumps(manifest,indent=2),encoding='utf-8')
    qwen_voice.validate_assets(full=True)
    print('Qwen model assets verified locally.',flush=True)


def install_runtime():
    if not qwen_voice.PYTHON.is_file():
        venv.EnvBuilder(with_pip=True).create(qwen_voice.RUNTIME_DIR)
    # A failed repair/install must not retain a previously successful marker.
    marker=qwen_voice.RUNTIME_DIR/'narrate-runtime.json'
    marker.write_text('{"status":"installing"}',encoding='utf-8')
    python=str(qwen_voice.PYTHON)
    subprocess.run([python,'-m','pip','install','torch==2.9.1','torchaudio==2.9.1',
                    '--index-url','https://download.pytorch.org/whl/cu128'],check=True)
    subprocess.run([python,'-m','pip','install','-r',str(ROOT/'requirements-qwen-tts.txt'),
                    '--index-url','https://pypi.org/simple'],check=True)
    subprocess.run([python,'-m','pip','check'],check=True)
    versions=subprocess.check_output([python,'-c',
        "import importlib.metadata as m,json; print(json.dumps({'qwen_tts':m.version('qwen-tts'),'torch':m.version('torch'),'torchaudio':m.version('torchaudio')}))"],text=True)
    installed=json.loads(versions)
    if installed!=qwen_voice.RUNTIME_VERSIONS:
        raise ValueError('The isolated Qwen runtime does not match its pinned CUDA package versions.')
    installed['status']='ready'
    temporary=marker.with_suffix('.json.part')
    temporary.write_text(json.dumps(installed),encoding='utf-8')
    temporary.replace(marker)


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--install-runtime',action='store_true')
    parser.add_argument('--download-model',action='store_true')
    args=parser.parse_args()
    if not (args.install_runtime or args.download_model):
        parser.error('Select --install-runtime and/or --download-model to authorize setup downloads.')
    if args.install_runtime:
        install_runtime()
    if args.download_model:
        download_model()


if __name__=='__main__':
    main()
