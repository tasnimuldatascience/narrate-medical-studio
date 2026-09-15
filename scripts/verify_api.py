"""Validate the live local API using one retained, entirely synthetic lesson.

The resume record is written immediately after upload, so rerunning the script
continues the same demonstration project instead of creating another project.
No clinical presentations are approved or modified by this script.
"""
import hashlib
import argparse
import io
import json
import sys
import time
import zipfile
from pathlib import Path, PurePosixPath

import httpx
from PIL import Image

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from scripts.verify_pipeline import fixture
from backend import store


BASE='http://127.0.0.1:8765'
NAME='Learning loop - software demo.pptx'
REVIEWER='Synthetic software validation'
SETTINGS={'start':1,'end':3,'engine':'kokoro','voice':'af_heart','rate':.96,
          'burn_captions':True,'visual_style':'whiteboard'}
QUIZ={
    'question':'After recalling the idea in your own words, what comes next?',
    'options':['Compare it with the source','Only reread the title','Skip the explanation'],
    'correct':0,
    'explanation':'The illustrated loop asks you to check your explanation against the source, adjust it, and try again.'}


def request(client,method,path,**kwargs):
    response=client.request(method,path,**kwargs)
    response.raise_for_status()
    return response


def wait_job(client,root,kind,timeout):
    deadline=time.monotonic()+timeout
    previous=None
    while time.monotonic()<deadline:
        project=request(client,'GET',root).json()
        job=project.get('job',{})
        state=(job.get('status'),job.get('message'))
        if state!=previous:
            print(kind,*state,flush=True)
            previous=state
        if job.get('status')=='completed':
            assert job.get('kind')==kind,job
            return project
        if job.get('status') in {'failed','cancelled'}:
            raise RuntimeError(f'{kind} did not complete: {job}')
        time.sleep(1)
    raise TimeoutError(f'{kind} exceeded {timeout}s. The retained project may still be processing; rerun to resume.')


def save_record(path,record):
    temporary=path.with_suffix('.tmp')
    temporary.write_text(json.dumps(record,indent=2),encoding='utf-8')
    temporary.replace(path)


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--refresh-export',action='store_true',
                        help='Create a fresh export of the same retained synthetic project.')
    args=parser.parse_args()
    folder=store.ROOT/'data'/'validation'
    folder.mkdir(parents=True,exist_ok=True)
    result_path=folder/'api-result.json'
    source_path=folder/'api-source.pptx'
    prs,cue_sets=fixture()
    narration=[slide.notes_slide.notes_text_frame.text for slide in prs.slides]
    record=json.loads(result_path.read_text(encoding='utf-8')) if result_path.is_file() else {}
    with httpx.Client(base_url=BASE,trust_env=False,timeout=30) as client:
        health=request(client,'GET','/api/health').json()
        if record.get('project_id'):
            root='/api/projects/'+record['project_id']
            project=request(client,'GET',root).json()
            assert project['filename']==NAME,'Refusing to modify a project not created by this synthetic verifier.'
            assert len(project['slides'])==3
            print('Resuming retained synthetic project',project['id'],flush=True)
        else:
            prs.save(source_path)
            with source_path.open('rb') as source:
                project=request(client,'POST','/api/projects',files={
                    'file':(NAME,source,'application/vnd.openxmlformats-officedocument.presentationml.presentation')}).json()
            root='/api/projects/'+project['id']
            record={'project_id':project['id'],'project_url':BASE+root,
                    'source':str(source_path),'status':'uploaded'}
            save_record(result_path,record)
            print('Created synthetic project',project['id'],flush=True)

        active=project.get('job',{})
        if active.get('status') in {'queued','running'}:
            project=wait_job(client,root,active['kind'],180 if active['kind']=='export' else 120)
        if not all(slide.get('image') for slide in project['slides']):
            request(client,'POST',root+'/render')
            project=wait_job(client,root,'render',120)
        for i,slide in enumerate(project['slides']):
            png=request(client,'GET',f'{root}/slides/{i+1}/image').content
            with Image.open(io.BytesIO(png)) as image:
                assert image.width>=1000 and image.height>0
                image.verify()
            payload={'revision':slide['revision'],'narration':narration[i],
                     'knowledge':QUIZ if i==2 else None,'visual_cues':cue_sets[i]}
            project=request(client,'PUT',f'{root}/slides/{i+1}',json=payload).json()
            reviewed=project['slides'][i]
            assert reviewed['narration']==narration[i]
            assert reviewed['visual_cues']==cue_sets[i]
            project=request(client,'POST',f'{root}/slides/{i+1}/approve',json={
                'revision':reviewed['revision'],'reviewer':REVIEWER,'acknowledged':True}).json()
        record['status']='reviewed synthetic fixture'
        save_record(result_path,record)

        # Reuse only a verified export from this exact retained project/settings.
        matching=[export for export in project['exports'] if export.get('settings')==SETTINGS]
        if matching and not args.refresh_export:
            export_id=matching[-1]['id']
        else:
            request(client,'POST',root+'/export',json=SETTINGS)
            project=wait_job(client,root,'export',180)
            export_id=project['exports'][-1]['id']
        record.update(export_id=export_id,status='verifying downloads')
        save_record(result_path,record)
        export_url=f'{root}/exports/{export_id}'
        mp4=request(client,'GET',export_url+'/presentation.mp4').content
        assert len(mp4)>1000 and mp4[4:8]==b'ftyp','Invalid MP4 download'
        manifest=request(client,'GET',export_url+'/manifest.json').json()
        quality=request(client,'GET',export_url+'/quality.json').json()
        assert manifest['id']==export_id
        assert manifest['settings']==SETTINGS
        assert quality['verified'] is True
        assert manifest['quality']==quality
        assert 'estimat' in quality['caption_timing'].lower()
        assert manifest['duration']>20
        for i,slide in enumerate(manifest['slides']):
            assert slide['reviewer']==REVIEWER and slide['approved_at']
            assert slide['narration']==narration[i]
            assert slide['visual_cues']==cue_sets[i]
        assert manifest['slides'][2]['knowledge']==QUIZ
        bundle=request(client,'GET',export_url+'/interactive-lesson.zip').content
        with zipfile.ZipFile(io.BytesIO(bundle)) as archive:
            names=archive.namelist()
            assert len(names)==len(set(names)),'Duplicate ZIP names'
            for name in names:
                path=PurePosixPath(name)
                assert not path.is_absolute() and '..' not in path.parts and ':' not in name and '\\' not in name
            assert archive.testzip() is None
            assert {'index.html','presentation.mp4','manifest.json','quality.json','chapters.json'}<=set(names)
            assert json.loads(archive.read('manifest.json'))==manifest
            assert hashlib.sha256(archive.read('presentation.mp4')).digest()==hashlib.sha256(mp4).digest()
            chapters=json.loads(archive.read('chapters.json'))
            assert len(chapters)==3 and chapters[2]['knowledge']==QUIZ
            assert [chapter['title'] for chapter in chapters]==[slide['title'] for slide in project['slides']]
        export_folder=Path(health['data_path'])/project['id']/export_id
        record.update(status='passed',duration=manifest['duration'],mp4_bytes=len(mp4),
            zip_bytes=len(bundle),quality=quality,
            paths={name:str(export_folder/name) for name in
                   ['presentation.mp4','interactive-lesson.zip','manifest.json','quality.json','chapters.json']},
            downloads={name:BASE+export_url+'/'+name for name in
                       ['presentation.mp4','interactive-lesson.zip','manifest.json']})
        save_record(result_path,record)
        print(json.dumps(record,indent=2),flush=True)


if __name__=='__main__':
    main()
