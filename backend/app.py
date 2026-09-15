import hashlib
import json
import os
import shutil
import threading
import uuid
import zipfile
from concurrent.futures import ThreadPoolExecutor
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Literal

import httpx
from fastapi import FastAPI, File, HTTPException, UploadFile, Request
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
from starlette.middleware.trustedhost import TrustedHostMiddleware

from . import store, extract, media, narration, voice

pool = ThreadPoolExecutor(max_workers=1)
cancellations = {}
jobs_lock = threading.RLock()
MAX_UPLOAD = 150 * 1024 * 1024

@asynccontextmanager
async def lifespan(app):
    for project in store.list_projects():
        if project.get('job',{}).get('status') in ('queued','running'):
            with store.edit(project['id']) as p:
                p['job'].update(status='failed',message='Processing was interrupted by a restart. Retry this step.')
    yield
    with jobs_lock:
        for token in cancellations.values():
            token.set()

app = FastAPI(title='Narrate Studio',version='0.1.0',lifespan=lifespan,docs_url=None,redoc_url=None)
app.add_middleware(TrustedHostMiddleware,allowed_hosts=['127.0.0.1','localhost','testserver'])

@app.middleware('http')
async def local_origin(request:Request, call_next):
    origin = request.headers.get('origin')
    if origin and origin not in {'http://127.0.0.1:8765','http://localhost:8765','http://127.0.0.1:5173','http://localhost:5173'}:
        return JSONResponse({'detail':'Only the local studio can access this API.'},status_code=403)
    response = await call_next(request)
    response.headers['X-Content-Type-Options']='nosniff'
    response.headers['Referrer-Policy']='no-referrer'
    response.headers['X-Frame-Options']='DENY'
    response.headers['Content-Security-Policy']="default-src 'self'; img-src 'self' data:; media-src 'self' blob:; style-src 'self' 'unsafe-inline'; script-src 'self'; connect-src 'self'; frame-ancestors 'none'"
    response.headers['Cache-Control']='no-store'
    return response

@app.exception_handler(KeyError)
async def missing(request, exc):
    return JSONResponse({'detail':'Project or slide not found.'},status_code=404)

def idle(project):
    if project.get('job',{}).get('status') in ('queued','running'):
        raise HTTPException(409,'Wait for the active job to finish or cancel it.')

def get_slide(project,number):
    return next((s for s in project['slides'] if s['number']==number),None) or (_ for _ in ()).throw(KeyError(number))

def progress(project_id,percent,message):
    with store.edit(project_id) as p:
        p['job'].update(progress=percent,message=message,status='running')

def submit(project_id,kind,operation,validate=None):
    token = threading.Event()
    with jobs_lock:
        with store.edit(project_id) as p:
            idle(p)
            if validate:
                validate(p)
            p['job']={'kind':kind,'status':'queued','progress':0,'message':'Waiting for the local worker'}
            store.event(p,'job_started',kind)
        cancellations[project_id]=token
    def work():
        try:
            media.check(token)
            progress(project_id,1,f'Starting {kind}')
            operation(token)
            media.check(token)
            with store.edit(project_id) as p:
                p['job'].update(status='completed',progress=100,message=f'{kind.capitalize()} complete')
                store.event(p,'job_completed',kind)
        except Exception as exc:
            with store.edit(project_id) as p:
                p['job'].update(status='cancelled' if isinstance(exc,media.Cancelled) else 'failed',message=str(exc)[-2000:])
                store.event(p,'job_failed',str(exc)[-2000:])
        finally:
            with jobs_lock:
                if cancellations.get(project_id) is token:
                    cancellations.pop(project_id,None)
    try:
        pool.submit(work)
    except Exception:
        with jobs_lock:
            cancellations.pop(project_id,None)
            with store.edit(project_id) as p:
                p['job'].update(status='failed',message='The local worker could not start. Restart the studio and retry.')
        raise
    return store.get(project_id)

@app.get('/api/health')
def health():
    models, ollama_error = [], None
    try:
        with httpx.Client(trust_env=False,timeout=2) as client:
            r = client.get(narration.OLLAMA+'/api/tags')
            r.raise_for_status()
            models=[m['name'] for m in r.json().get('models',[]) if 'cloud' not in m['name'].lower()]
    except Exception:
        ollama_error='Start Ollama to enable local AI drafting.'
    powerpoint=False
    if os.name=='nt':
        import winreg
        try:
            with winreg.OpenKey(winreg.HKEY_CLASSES_ROOT,'PowerPoint.Application'):
                powerpoint=True
        except OSError:
            pass
    return {'offline':True,'models':models,'ollama_error':ollama_error,'ffmpeg':bool(shutil.which('ffmpeg') and shutil.which('ffprobe')),
        'renderer':powerpoint or bool(os.environ.get('NARRATE_SOFFICE') or shutil.which('soffice')),
        'renderer_name':'Microsoft PowerPoint' if powerpoint else 'LibreOffice',
        'piper':media.voice_path().is_file(),'kokoro':voice.available(),'windows_voice':os.name=='nt','data_path':str(store.DATA),
        'version':'0.1.0'}

@app.get('/api/projects')
def projects():
    return [{k:v for k,v in p.items() if k not in ('slides','history')} | {'slide_count':len(p['slides']),
        'approved_count':sum(s['approved'] for s in p['slides'])} for p in store.list_projects()]

@app.get('/api/projects/{project_id}')
def project(project_id:str):
    return store.get(project_id)

@app.post('/api/projects',status_code=201)
async def upload(file:UploadFile=File(...)):
    filename=Path(file.filename or 'presentation').name
    if Path(filename).suffix.lower() not in ('.pptx','.pptm'):
        raise HTTPException(400,'Upload a .pptx or .pptm presentation.')
    project_id=uuid.uuid4().hex
    folder=store.DATA/project_id
    folder.mkdir(parents=True)
    source=folder/'source.pptx'
    size=0
    try:
        with source.open('wb') as out:
            while chunk:=await file.read(1024*1024):
                size+=len(chunk)
                if size>MAX_UPLOAD:
                    raise ValueError('The upload limit is 150 MB.')
                out.write(chunk)
        extract.sanitize(source,folder/'safe.pptx')
        slides,metadata=extract.extract(folder/'safe.pptx')
        if not slides:
            raise ValueError('This presentation contains no slides.')
        p={'id':project_id,'name':Path(filename).stem.replace('_',' '),'filename':filename,'created_at':store.now(),
            'updated_at':store.now(),'slides':slides,'metadata':metadata,'history':[],'exports':[],
            'job':{'status':'idle'},'audience':'Medical practitioners','specialty':'General medicine',
            'source_sha256':hashlib.sha256(source.read_bytes()).hexdigest()}
        store.event(p,'imported',f'{filename}: {len(slides)} slides. Active content and external relationships removed from render copy.')
        store.create(p)
        return p
    except Exception as exc:
        # Folder is a fresh server-generated UUID, never a user-supplied path.
        shutil.rmtree(folder,ignore_errors=True)
        raise HTTPException(400,f'Could not import presentation: {exc}') from exc
    finally:
        await file.close()

class ProjectEdit(BaseModel):
    name:str=Field(min_length=1,max_length=200)
    audience:str=Field(min_length=1,max_length=200)
    specialty:str=Field(min_length=1,max_length=100)

@app.patch('/api/projects/{project_id}')
def update_project(project_id:str,body:ProjectEdit):
    with store.edit(project_id) as p:
        idle(p)
        p.update(body.model_dump())
    return store.get(project_id)

class Knowledge(BaseModel):
    question:str=Field(min_length=1,max_length=500)
    options:list[str]=Field(min_length=3,max_length=3)
    correct:int=Field(ge=0,le=2)
    explanation:str=Field(min_length=1,max_length=1500)

class VisualCue(BaseModel):
    label:str=Field(min_length=1,max_length=120)
    x:float=Field(ge=0,le=1)
    y:float=Field(ge=0,le=1)
    width:float=Field(ge=.02,le=1,default=.24)
    height:float=Field(ge=.02,le=1,default=.24)

class SlideEdit(BaseModel):
    narration:str=Field(max_length=12000)
    revision:int=Field(ge=1)
    knowledge:Knowledge|None=None
    visual_cues:list[VisualCue]=Field(default_factory=list,max_length=6)

@app.put('/api/projects/{project_id}/slides/{number}')
def edit_slide(project_id:str,number:int,body:SlideEdit):
    with store.edit(project_id) as p:
        idle(p)
        slide=get_slide(p,number)
        if slide['revision']!=body.revision:
            raise HTTPException(409,'This slide changed in another window. Reload before saving.')
        knowledge=body.knowledge.model_dump() if body.knowledge else None
        visual_cues=[c.model_dump() for c in body.visual_cues]
        if any(not c['label'].strip() for c in visual_cues):
            raise HTTPException(400,'Every visual cue needs a label.')
        if knowledge and (not knowledge['question'].strip() or not knowledge['explanation'].strip()
                          or any(not v.strip() for v in knowledge['options'])
                          or len({v.strip().casefold() for v in knowledge['options']})<3):
            raise HTTPException(400,'A knowledge check needs three distinct, nonempty choices.')
        prior_cues=[VisualCue.model_validate(c).model_dump() for c in slide.get('visual_cues',[])]
        if slide['narration']!=body.narration or slide.get('knowledge')!=knowledge or prior_cues!=visual_cues:
            slide.update(narration=body.narration,revision=slide['revision']+1,approved=False,reviewer='',approved_at=None,draft_origin='reviewer edit')
            slide['knowledge']=knowledge
            slide['visual_cues']=visual_cues
            store.event(p,'script_edited',f'Slide {number}, revision {slide["revision"]}. Approval reset.')
    return store.get(project_id)

class Approval(BaseModel):
    revision:int=Field(ge=1)
    reviewer:str=Field(min_length=2,max_length=100)
    acknowledged:bool

@app.post('/api/projects/{project_id}/slides/{number}/approve')
def approve(project_id:str,number:int,body:Approval):
    with store.edit(project_id) as p:
        idle(p)
        s=get_slide(p,number)
        if body.revision!=s['revision']:
            raise HTTPException(409,'The script changed. Review its latest revision before approving.')
        if not body.acknowledged or not s['narration'].strip() or not body.reviewer.strip():
            raise HTTPException(400,'A named reviewer must confirm the narration and source checks.')
        if not s['image']:
            raise HTTPException(400,'Render and inspect the slide before approval.')
        s.update(approved=True,reviewer=body.reviewer.strip(),approved_at=store.now())
        store.event(p,'approved',f'Slide {number} revision {s["revision"]}, reviewer: {s["reviewer"]}')
    return store.get(project_id)

@app.post('/api/projects/{project_id}/render')
def render(project_id:str):
    folder=store.directory(project_id)
    def operation(cancel):
        media.render(folder,cancel)
        with store.edit(project_id) as p:
            for s in p['slides']:
                s['image']=(folder/'slides'/f'slide-{s["number"]}.png').is_file()
            if not all(s['image'] for s in p['slides']):
                raise ValueError('Renderer did not produce every slide. Retry rendering.')
    return submit(project_id,'render',operation)

class DraftRequest(BaseModel):
    model:str=Field(max_length=120)

@app.post('/api/projects/{project_id}/slides/{number}/draft')
def draft(project_id:str,number:int,body:DraftRequest):
    def operation(cancel):
        p=store.get(project_id)
        result=narration.generate(get_slide(p,number),body.model,p['audience'])
        media.check(cancel)
        with store.edit(project_id) as p:
            s=get_slide(p,number)
            s.update(narration=result.narration,revision=s['revision']+1,approved=False,approved_at=None,reviewer='',draft_origin=f'Local AI · {body.model}')
            s['ai_flags']=result.review_flags
            store.event(p,'ai_draft',f'Slide {number}; {body.model}; prompt {narration.PROMPT_VERSION}')
    get_slide(store.get(project_id),number)
    return submit(project_id,'draft',operation)

class VoiceRequest(BaseModel):
    engine:Literal['kokoro','piper','windows']='kokoro'
    voice:Literal['af_heart','af_bella','am_michael','bf_emma']='af_heart'
    rate:float=Field(ge=.7,le=1.4,default=1)

_preview_lock=threading.Lock()

@app.post('/api/voice-preview')
def preview_voice(body:VoiceRequest):
    # Fixed, nonclinical audition. Unapproved user scripts never reach this path.
    text="Let's take this one step at a time. A good lesson does more than deliver information. It gives you a moment to notice, to question, and to understand. Ready to try it? Choose a chapter, listen to the explanation, then pause and put the idea into your own words."
    key=hashlib.sha256(('voice-v2'+json.dumps(body.model_dump(),sort_keys=True)).encode()).hexdigest()
    folder=store.DATA/'voice-previews'
    folder.mkdir(parents=True,exist_ok=True)
    output=folder/f'{key}.wav'
    try:
        with _preview_lock:
            if not output.is_file():
                temporary=folder/f'{key}.part.wav'
                media.synthesize(text,temporary,body.engine,body.rate,threading.Event(),body.voice)
                temporary.replace(output)
    except Exception as exc:
        raise HTTPException(400,str(exc)) from exc
    return {'url':f'/api/voice-previews/{key}.wav'}

@app.get('/api/voice-previews/{filename}')
def voice_sample(filename:str):
    import re
    if not re.fullmatch(r'[a-f0-9]{64}\.wav',filename):
        raise HTTPException(404,'Voice sample not found.')
    path=store.DATA/'voice-previews'/filename
    if not path.is_file():
        raise HTTPException(404,'Generate this voice sample first.')
    return FileResponse(path,media_type='audio/wav')

class ExportRequest(VoiceRequest):
    start:int=Field(ge=1)
    end:int=Field(ge=1)
    burn_captions:bool=True
    visual_style:Literal['whiteboard','studio']='whiteboard'

@app.post('/api/projects/{project_id}/export')
def export(project_id:str,body:ExportRequest):
    def validate(p):
        if body.end<body.start or body.end>len(p['slides']):
            raise HTTPException(400,'Choose a valid slide range.')
        selected=p['slides'][body.start-1:body.end]
        if any(not s['approved'] for s in selected):
            raise HTTPException(400,'All slides in this range require approval before voice or video generation.')
    export_id=uuid.uuid4().hex
    def operation(cancel):
        snapshot=store.get(project_id)
        folder=store.directory(project_id)/export_id
        folder.mkdir()
        duration=media.export(snapshot,folder,body.model_dump(),cancel,lambda pc,msg:progress(project_id,pc,msg))
        media.check(cancel)
        manifest={'id':export_id,'created_at':store.now(),'settings':body.model_dump(),'duration':duration,
            'source_sha256':snapshot['source_sha256'],
            'quality':json.loads((folder/'quality.json').read_text(encoding='utf-8')),
            'slides':[{**{k:s[k] for k in ('number','narration','revision','reviewer','approved_at')},
                'knowledge':s.get('knowledge'),'visual_cues':s.get('visual_cues',[]),'sources':s['sources']}
                for s in snapshot['slides'][body.start-1:body.end]]}
        (folder/'manifest.json').write_text(json.dumps(manifest,indent=2),encoding='utf-8')
        with zipfile.ZipFile(folder/'interactive-lesson.zip','a') as bundle:
            for name in ('manifest.json','quality.json','chapters.json'):
                bundle.write(folder/name,name)
        with store.edit(project_id) as p:
            p['exports'].append({k:v for k,v in manifest.items() if k!='slides'})
    return submit(project_id,'export',operation,validate)

@app.post('/api/projects/{project_id}/cancel')
def cancel(project_id:str):
    store.get(project_id)
    with jobs_lock:
        if token:=cancellations.get(project_id):
            token.set()
    return {'ok':True}

@app.get('/api/projects/{project_id}/slides/{number}/image')
def image(project_id:str,number:int):
    get_slide(store.get(project_id),number)
    path=store.directory(project_id)/'slides'/f'slide-{number}.png'
    if not path.is_file():
        raise HTTPException(404,'Slide preview has not been rendered.')
    return FileResponse(path,media_type='image/png')

@app.get('/api/projects/{project_id}/exports/{export_id}/{filename}')
def download(project_id:str,export_id:str,filename:str):
    p=store.get(project_id)
    if filename not in {'presentation.mp4','captions.srt','transcript.txt','manifest.json','interactive-lesson.zip','quality.json','chapters.json'} or not any(e['id']==export_id for e in p['exports']):
        raise HTTPException(404,'Export not found.')
    path=store.directory(project_id)/export_id/filename
    if not path.is_file():
        raise HTTPException(404,'This export file is unavailable. Create a new export.')
    return FileResponse(path,filename=filename,media_type='video/mp4' if filename.endswith('.mp4') else None)

@app.get('/api/projects/{project_id}/review.json')
def review(project_id:str):
    return JSONResponse(store.get(project_id),headers={'Content-Disposition':'attachment; filename="review.json"'})

DIST=store.ROOT/'frontend'/'dist'
if DIST.is_dir():
    app.mount('/',StaticFiles(directory=DIST,html=True),name='studio')
