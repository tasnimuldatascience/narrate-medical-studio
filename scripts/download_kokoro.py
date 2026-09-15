"""Explicit setup-only download. Never invoked by the application at runtime."""
import hashlib
import json
import urllib.request
from pathlib import Path

folder=Path(__file__).resolve().parents[1]/'models'
folder.mkdir(exist_ok=True)
base='https://github.com/thewh1teagle/kokoro-onnx/releases/download/model-files-v1.1/'
manifest={}
expected={
    'kokoro-v1.0.onnx':'beb0d1848dee9a49da392cc3df26958d46cfa35d321edf434f52949153f0df3a',
    'voices-v1.0.bin':'bca610b8308e8d99f32e6fe4197e7ec01679264efed0cac9140fe9c29f1fbf7d',
}
for name in ('kokoro-v1.0.onnx','voices-v1.0.bin'):
    target=folder/name
    if not target.is_file():
        temporary=target.with_suffix(target.suffix+'.download')
        print('Downloading',name,flush=True)
        with urllib.request.urlopen(base+name,timeout=120) as source,temporary.open('wb') as out:
            while block:=source.read(1024*1024):
                out.write(block)
        if hashlib.sha256(temporary.read_bytes()).hexdigest()!=expected[name]:
            raise ValueError(f'{name} did not match the pinned voice asset hash. The download was not installed.')
        temporary.replace(target)
    digest=hashlib.sha256(target.read_bytes()).hexdigest()
    if digest!=expected[name]:
        raise ValueError(f'{name} differs from the pinned asset. Check the local model file before continuing.')
    manifest[name]={'source':base+name,'sha256':digest,'bytes':target.stat().st_size}
    print(name,target.stat().st_size,'bytes',digest,flush=True)
(folder/'kokoro-manifest.json').write_text(json.dumps(manifest,indent=2),encoding='utf-8')
