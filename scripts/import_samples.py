"""Import supplied examples locally, preserving human review as pending."""
import sys
import time
from pathlib import Path
import httpx
root=Path(__file__).resolve().parents[1]
with httpx.Client(base_url='http://127.0.0.1:8765',trust_env=False,timeout=120) as client:
    existing={p['filename']:p for p in client.get('/api/projects').json()}
    for path in sorted((root/'AI to convert ppt to audiovisual presentation').glob('*.ppt*')):
        if path.name in existing:
            project=existing[path.name]
        else:
            with path.open('rb') as f:
                r=client.post('/api/projects',files={'file':(path.name,f)})
                r.raise_for_status();project=r.json()
        project_id=project['id']
        print('Imported',path.name,project_id,flush=True)
        r=client.post(f'/api/projects/{project_id}/render')
        r.raise_for_status()
        for _ in range(180):
            time.sleep(2)
            p=client.get(f'/api/projects/{project_id}').json()
            if p['job']['status'] not in ('queued','running'):
                print(p['job'],flush=True)
                if p['job']['status']!='completed':
                    sys.exit(1)
                break
        else:
            raise TimeoutError('Rendering did not complete in six minutes.')
