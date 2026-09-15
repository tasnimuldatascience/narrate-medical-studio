import hashlib
import json
from pathlib import Path
import sys
import uuid
import wave

import numpy as np
import pytest
from fastapi.testclient import TestClient
from PIL import Image

from backend import app as studio, media, store
from scripts import render_draft_preview as renderer


@pytest.fixture
def preview(tmp_path,monkeypatch):
    monkeypatch.setattr(store,'DATA',tmp_path)
    project_id=uuid.uuid4().hex
    folder=tmp_path/project_id/'slides'
    folder.mkdir(parents=True)
    Image.new('RGB',(40,30),'white').save(folder/'slide-1.png')
    slide={'number':1,'title':'Source explanation','narration':'First thought.\n\nSecond thought.',
        'revision':3,'image':True,'approved':False,'reviewer':'','approved_at':None,
        'visual_cues':[{'label':f'Region {i}','x':.5,'y':.5,'width':.2,'height':.2} for i in range(3)]}
    store.create({'id':project_id,'name':'Private preview fixture','source_sha256':'source-checksum',
        'slides':[slide],'job':{'status':'idle'},'history':[],'exports':[],
        'created_at':store.now(),'updated_at':store.now()})
    pending=[]
    monkeypatch.setattr(studio.pool,'submit',lambda operation:pending.append(operation))
    with TestClient(studio.app) as client:
        yield client,project_id,pending


def successful_renderer(command,cancel,**kwargs):
    def option(name):return command[command.index(name)+1]
    folder=Path(option('--output-dir'))
    (folder/'presentation.mp4').write_bytes(b'private-test-video')
    manifest={'kind':'unapproved-draft-preview','clinical_approval':False,
        'revision':int(option('--expected-revision')),'source_fingerprint':option('--expected-fingerprint'),
        'duration':2.5,'quality':{'verified':True}}
    slide=store.get(option('--project-id'))['slides'][int(option('--slide'))-1]
    manifest.update(project_id=option('--project-id'),slide=int(option('--slide')),
        text_sha256=hashlib.sha256(slide['narration'].encode()).hexdigest(),
        engine=option('--engine'),voice=option('--voice'),delivery=option('--delivery'),
        rate=float(option('--rate')),visual_style=option('--visual-style'))
    (folder/'manifest.json').write_text(json.dumps(manifest))
    return ''


@pytest.mark.parametrize('bad_field,bad_value',[('voice','Aiden'),('text_sha256','wrong'),('clinical_approval',True)])
def test_invalid_worker_manifest_never_publishes(preview,monkeypatch,bad_field,bad_value):
    client,project_id,pending=preview
    def invalid(command,cancel,**kwargs):
        successful_renderer(command,cancel,**kwargs)
        path=Path(command[command.index('--output-dir')+1])/'manifest.json'
        manifest=json.loads(path.read_text());manifest[bad_field]=bad_value
        path.write_text(json.dumps(manifest))
    monkeypatch.setattr(media,'run',invalid)
    client.post(f'/api/projects/{project_id}/slides/1/preview',json={});pending.pop()()
    project=store.get(project_id)
    assert project['job']['status']=='failed'
    assert not project.get('draft_previews')


def test_authored_paragraph_save_and_preview_preserve_script_origin(preview,monkeypatch):
    client,project_id,pending=preview
    with store.edit(project_id) as project:
        project['slides'][0].update(approved=True,draft_origin='Local editorial draft')
    slide=store.get(project_id)['slides'][0]
    cue={**slide['visual_cues'][0],'paragraph':1}
    payload={'revision':3,'narration':slide['narration'],'visual_cues':[cue]}
    response=client.put(f'/api/projects/{project_id}/slides/1',json=payload)
    assert response.status_code==200
    saved=response.json()['slides'][0]
    assert saved['revision']==4 and not saved['approved']
    assert saved['draft_origin']=='Local editorial draft'
    payload.update(revision=4,visual_cues=[{**cue,'paragraph':2}])
    assert client.put(f'/api/projects/{project_id}/slides/1',json=payload).status_code==400
    payload['visual_cues'][0]['paragraph']=-1
    assert client.put(f'/api/projects/{project_id}/slides/1',json=payload).status_code==422
    monkeypatch.setattr(media,'run',successful_renderer)
    client.post(f'/api/projects/{project_id}/slides/1/preview',json={});pending.pop()()
    metadata=store.get(project_id)['slides'][0]['draft_preview']
    direction=json.loads((store.directory(project_id)/'draft-previews'/metadata['id']/'direction.json').read_text())
    assert direction['regions'][0]['paragraph']==1


def test_private_preview_of_unapproved_slide_preserves_script_and_review(preview,monkeypatch):
    client,project_id,pending=preview
    before=store.get(project_id)['slides'][0]
    commands=[]
    def run(command,cancel,**kwargs):
        commands.append(command)
        return successful_renderer(command,cancel,**kwargs)
    monkeypatch.setattr(media,'run',run)
    response=client.post(f'/api/projects/{project_id}/slides/1/preview',json={})
    assert response.status_code==200,response.text
    assert response.json()['job']['status']=='queued'
    pending.pop()()
    project=store.get(project_id)
    assert project['job']['status']=='completed',project['job']
    after=project['slides'][0]
    assert {key:value for key,value in after.items() if key!='draft_preview'}==before
    metadata=after['draft_preview']
    assert metadata['revision']==3 and metadata['clinical_approval'] is False
    assert metadata['visual_style']=='focus' and metadata['engine']=='kokoro'
    assert project['exports']==[]
    assert project['draft_previews']==[metadata]
    downloaded=client.get(metadata['url'])
    assert downloaded.status_code==200 and downloaded.headers['content-type']=='video/mp4'
    assert downloaded.content==b'private-test-video'
    command=commands[0]
    direction=json.loads(Path(command[command.index('--direction')+1]).read_text())
    assert [region['paragraph'] for region in direction['regions']]==[0,0,1]
    assert 'not semantic alignment' in direction['timing_note']


@pytest.mark.parametrize('body',[{'engine':'piper'},{'engine':'windows'},
    {'engine':'qwen','voice':'af_heart'},{'engine':'kokoro','voice':'Aiden'},{'visual_style':'arbitrary'}])
def test_preview_settings_validation_never_queues(preview,body):
    client,project_id,pending=preview
    assert client.post(f'/api/projects/{project_id}/slides/1/preview',json=body).status_code==422
    assert pending==[]


@pytest.mark.parametrize('change',[{'narration':' '},{'image':False}])
def test_preview_needs_saved_script_and_rendered_source(preview,change):
    client,project_id,pending=preview
    with store.edit(project_id) as project:project['slides'][0].update(change)
    assert client.post(f'/api/projects/{project_id}/slides/1/preview',json={}).status_code==400
    assert pending==[]


def test_queued_preview_rejects_changed_source_before_synthesis(preview,monkeypatch):
    client,project_id,pending=preview
    assert client.post(f'/api/projects/{project_id}/slides/1/preview',json={}).status_code==200
    with store.edit(project_id) as project:project['slides'][0]['narration']='Changed outside the app.'
    monkeypatch.setattr(media,'run',lambda *args,**kwargs:pytest.fail('Stale source reached renderer'))
    pending.pop()()
    project=store.get(project_id)
    assert project['job']['status']=='failed'
    assert not project.get('draft_previews')


def test_preview_rechecks_source_before_publishing(preview,monkeypatch):
    client,project_id,pending=preview
    def changed(command,cancel,**kwargs):
        successful_renderer(command,cancel,**kwargs)
        with store.edit(project_id) as project:project['slides'][0]['revision']+=1
    monkeypatch.setattr(media,'run',changed)
    client.post(f'/api/projects/{project_id}/slides/1/preview',json={})
    pending.pop()()
    project=store.get(project_id)
    assert project['job']['status']=='failed'
    assert not project.get('draft_previews')


def test_failed_rerun_preserves_previous_preview_and_hides_partial_files(preview,monkeypatch):
    client,project_id,pending=preview
    monkeypatch.setattr(media,'run',successful_renderer)
    client.post(f'/api/projects/{project_id}/slides/1/preview',json={});pending.pop()()
    prior=store.get(project_id)['slides'][0]['draft_preview']
    failed=[]
    def failure(command,cancel,**kwargs):
        folder=Path(command[command.index('--output-dir')+1])
        (folder/'presentation.mp4').write_bytes(b'partial')
        failed.append(folder.name)
        raise RuntimeError('Encoder stopped')
    monkeypatch.setattr(media,'run',failure)
    client.post(f'/api/projects/{project_id}/slides/1/preview',json={});pending.pop()()
    assert store.get(project_id)['slides'][0]['draft_preview']==prior
    assert client.get(prior['url']).status_code==200
    assert client.get(f'/api/projects/{project_id}/draft-previews/{failed[0]}/presentation.mp4').status_code==404
    assert client.get(prior['url'].replace('presentation.mp4','direction.json')).status_code==404
    assert client.get(f'/api/projects/{project_id}/draft-previews/not-a-uuid/presentation.mp4').status_code==404


def test_cancelled_preview_requests_child_cleanup_and_publishes_nothing(preview,monkeypatch):
    client,project_id,pending=preview
    def interrupted(command,cancel,**kwargs):
        studio.cancellations[project_id].set()
        assert cancel.is_set() is False  # Give nested workers a cleanup window.
        assert Path(command[command.index('--cancel-file')+1]).is_file()
        raise RuntimeError('CLI acknowledged cancellation')
    monkeypatch.setattr(media,'run',interrupted)
    client.post(f'/api/projects/{project_id}/slides/1/preview',json={});pending.pop()()
    project=store.get(project_id)
    assert project['job']['status']=='cancelled'
    assert not project.get('draft_previews')


def test_cli_renders_every_region_with_banner_and_one_qwen_session(preview,tmp_path,monkeypatch):
    _,project_id,_=preview
    folder=tmp_path/'rendered-preview'
    direction=tmp_path/'direction.json'
    regions=[{'label':f'Region {i}','paragraph':0 if i<2 else 1,'x':.5,'y':.5,'width':.2,'height':.2} for i in range(3)]
    direction.write_text(json.dumps({'regions':regions}))
    project=store.get(project_id)
    visual=store.DATA/project_id/'slides'/'slide-1.png'
    fingerprint=renderer.source_fingerprint(project,project['slides'][0],visual)
    monkeypatch.setattr(sys,'argv',['render_draft_preview.py','--project-id',project_id,'--slide','1',
        '--engine','qwen','--voice','Aiden','--direction',str(direction),'--output-dir',str(folder),
        '--expected-revision','3','--expected-fingerprint',fingerprint])
    monkeypatch.setattr(renderer.shutil,'which',lambda command:command)
    calls=[]
    def synthesize(text,path,engine,rate,cancel,voice,delivery):
        calls.append(text)
        with wave.open(str(path),'wb') as wav:
            wav.setparams((1,2,24000,0,'NONE','not compressed'))
            wav.writeframes((np.sin(np.arange(48000)*.05)*3000).astype('<i2').tobytes())
        cues=[{'start':0,'end':1,'text':'First thought.'},{'start':1,'end':2,'text':'Second thought.'}]
        path.with_suffix('.qwen.json').write_text(json.dumps({'voice':voice,'style':delivery,'requested_rate':rate,'cues':cues}))
        return cues,2
    monkeypatch.setattr(media,'synthesize',synthesize)
    monkeypatch.setattr(media,'run',lambda command,cancel,**kwargs:(kwargs['cwd']/'presentation.mp4').write_bytes(b'encoded'))
    monkeypatch.setattr(media,'audit_video',lambda *args:{'verified':True})
    active=[]
    def focus(full,regions,rectangles,completed,index,fraction):
        active.append(index)
        return full.copy()
    monkeypatch.setattr(renderer.focus_motion,'paint',focus)
    banners=[]
    def save_frame(image,path,*args,**kwargs):
        banners.append(image.getpixel((0,0)))
        Path(path).write_bytes(b'frame')
    monkeypatch.setattr(Image.Image,'save',save_frame)
    renderer.main()
    assert calls==[project['slides'][0]['narration']]
    assert set(active)=={0,1,2}
    assert banners and all(pixel==(128,48,45) for pixel in banners)
    manifest=json.loads((folder/'manifest.json').read_text())
    assert manifest['clinical_approval'] is False
    assert manifest['source_fingerprint']==fingerprint
    assert manifest['text_sha256']==hashlib.sha256(calls[0].encode()).hexdigest()
    assert store.get(project_id)['slides'][0]==project['slides'][0]
