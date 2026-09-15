import hashlib
import json
import os
import shutil
import sys
import threading
import time
import uuid
import zipfile
from concurrent.futures import ThreadPoolExecutor
from contextlib import asynccontextmanager, nullcontext
from pathlib import Path
from typing import Literal

import httpx
from fastapi import FastAPI, File, HTTPException, UploadFile, Request
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field, model_validator
from starlette.middleware.trustedhost import TrustedHostMiddleware

from . import store, extract, media, narration, voice
from .scene_timing import paragraphs as narration_paragraphs

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
    from . import ocr, qwen_voice
    return {'offline':True,'models':models,'ollama_error':ollama_error,'ffmpeg':bool(shutil.which('ffmpeg') and shutil.which('ffprobe')),
        'renderer':powerpoint or bool(os.environ.get('NARRATE_SOFFICE') or shutil.which('soffice')),
        'renderer_name':'Microsoft PowerPoint' if powerpoint else 'LibreOffice','powerpoint_animation':powerpoint,
        'piper':media.voice_path().is_file(),'kokoro':voice.available(),'qwen_tts':qwen_voice.available(),'ocr':ocr.available(),'windows_voice':os.name=='nt','data_path':str(store.DATA),
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
    paragraph:int|None=Field(default=None,ge=0)

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
        visual_cues=[c.model_dump(exclude_none=True) for c in body.visual_cues]
        paragraph_count=len(narration_paragraphs(body.narration))
        if any(c.get('paragraph',-1)>=paragraph_count for c in visual_cues):
            raise HTTPException(400,'Choose a paragraph that exists in the saved narration for every visual cue.')
        if any(not c['label'].strip() for c in visual_cues):
            raise HTTPException(400,'Every visual cue needs a label.')
        if knowledge and (not knowledge['question'].strip() or not knowledge['explanation'].strip()
                          or any(not v.strip() for v in knowledge['options'])
                          or len({v.strip().casefold() for v in knowledge['options']})<3):
            raise HTTPException(400,'A knowledge check needs three distinct, nonempty choices.')
        prior_cues=[VisualCue.model_validate(c).model_dump(exclude_none=True) for c in slide.get('visual_cues',[])]
        if slide['narration']!=body.narration or slide.get('knowledge')!=knowledge or prior_cues!=visual_cues:
            narration_changed=slide['narration']!=body.narration
            if narration_changed:
                slide['narration_quality']=None
                slide['evaluation']=None
                slide.pop('evaluation_error',None)
                slide['ai_flags']=['Narration was edited. Previous draft diagnostics no longer apply; compare this revision with all source material.']
            slide.update(narration=body.narration,revision=slide['revision']+1,approved=False,reviewer='',approved_at=None)
            if narration_changed:
                slide['draft_origin']='reviewer edit'
            if slide.get('evaluation'):
                slide['evaluation']['assessed_revision']=slide['revision']
            slide['knowledge']=knowledge
            slide['visual_cues']=visual_cues
            store.event(p,'script_edited',f'Slide {number}, revision {slide["revision"]}. Approval reset.')
    return store.get(project_id)

class Approval(BaseModel):
    revision:int=Field(ge=1)
    reviewer:str=Field(min_length=2,max_length=100)
    acknowledged:bool


class SourceEdit(BaseModel):
    revision:int=Field(ge=1)
    visual_text:str=Field(max_length=18000)
    source_reviewed:bool=False


@app.put('/api/projects/{project_id}/slides/{number}/source')
def edit_source(project_id:str,number:int,body:SourceEdit):
    with store.edit(project_id) as p:
        idle(p)
        s=get_slide(p,number)
        if s['revision']!=body.revision:
            raise HTTPException(409,'This slide changed. Reload before saving its source text.')
        if body.source_reviewed and not body.visual_text.strip():
            raise HTTPException(400,'Add a transcription before marking it checked.')
        if s.get('visual_text','')!=body.visual_text or s.get('source_reviewed',False)!=body.source_reviewed:
            s.update(visual_text=body.visual_text,source_reviewed=body.source_reviewed,
                revision=s['revision']+1,approved=False,reviewer='',approved_at=None,narration_quality=None,evaluation=None)
            s.pop('evaluation_error',None)
            s['ai_flags']=list(dict.fromkeys(s.get('ai_flags',[])+['Source transcription changed. Review or regenerate the narration against this source.']))
            store.event(p,'source_edited',f'Slide {number}; image text checked: {body.source_reviewed}; narration approval reset.')
    return store.get(project_id)


@app.post('/api/projects/{project_id}/slides/{number}/ocr')
def read_image_text(project_id:str,number:int):
    folder=store.directory(project_id)
    get_slide(store.get(project_id),number)
    def operation(cancel):
        from . import ocr
        result=ocr.extract_text(folder/'slides'/f'slide-{number}.png',cancel)
        media.check(cancel)
        with store.edit(project_id) as p:
            s=get_slide(p,number)
            s['ocr']=result
            # Existing edited text is retained; OCR supplies a separate candidate.
            if not s.get('visual_text','').strip():
                s.update(visual_text=result['text'],source_reviewed=False,revision=s['revision']+1,
                    approved=False,reviewer='',approved_at=None,narration_quality=None,evaluation=None)
                s.pop('evaluation_error',None)
            store.event(p,'image_text_detected',f'Slide {number}; local OCR candidate requires visual verification.')
    return submit(project_id,'ocr',operation)

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
        if s.get('visual_text','').strip() and not s.get('source_reviewed',False):
            raise HTTPException(400,'Check the image transcription against the slide before approving narration.')
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
    style:Literal['conversational','concise']='conversational'
    workflow:Literal['agents','legacy']='legacy'


def agent_folder(project_id,number,model,mode):
    """Resume the same requested revision; fingerprints validate checkpoints."""
    with store.edit(project_id) as p:
        s=get_slide(p,number)
        prior=s.get('agent_run') or {}
        reusable=(prior.get('input_revision')==s['revision'] and prior.get('model')==model
                  and prior.get('mode')==mode and prior.get('status') in {'running','failed','cancelled'})
        run_id=prior['id'] if reusable else uuid.uuid4().hex
        # Run IDs only originate here; validate persisted values before path use.
        import re
        if not re.fullmatch(r'[a-f0-9]{32}',run_id):raise ValueError('Invalid local agent run identifier.')
        s['agent_run']={'id':run_id,'mode':mode,'model':model,'input_revision':s['revision'],'status':'running'}
    folder=store.directory(project_id)/'agent-runs'/run_id
    folder.mkdir(parents=True,exist_ok=True)
    return folder


def agent_failure(project_id,number,exc):
    with store.edit(project_id) as p:
        s=get_slide(p,number)
        if s.get('agent_run'):
            s['agent_run']['status']='cancelled' if isinstance(exc,media.Cancelled) else 'failed'
        s['evaluation_error']=str(exc)[-1500:]


def evidence_slide(project,slide):
    result=dict(slide)
    result['source_sha256']=project['source_sha256']
    visual=store.directory(project['id'])/'slides'/f'slide-{slide["number"]}.png'
    if visual.is_file():
        result['source_image_sha256']=hashlib.sha256(visual.read_bytes()).hexdigest()
    return result


class EvaluationRequest(BaseModel):
    model:str=Field(max_length=120)


@app.post('/api/projects/{project_id}/slides/{number}/evaluate')
def evaluate_slide(project_id:str,number:int,body:EvaluationRequest):
    get_slide(store.get(project_id),number)
    def operation(cancel):
        from . import agent_workflow
        p=store.get(project_id)
        s=get_slide(p,number)
        folder=agent_folder(project_id,number,body.model,'evaluate')
        try:
            if s.get('image') and not s.get('text','').strip() and not s.get('visual_text','').strip():
                raise ValueError('Add the visible image text under Source before evaluation so the critic can compare the whole slide.')
            result=agent_workflow.evaluate(evidence_slide(p,s),s['narration'],body.model,p['audience'],run_folder=folder,
                cancel=cancel,progress=lambda pc,msg:progress(project_id,pc,msg))
            media.check(cancel)
            with store.edit(project_id) as current:
                saved=get_slide(current,number)
                if saved['revision']!=s['revision']:raise ValueError('The script changed during evaluation. Evaluate the saved revision again.')
                saved['evaluation']={**result['evaluation'],'assessed_revision':saved['revision']}
                saved.pop('evaluation_error',None)
                saved['agent_run'].update(status='completed',trace=result['trace'],fingerprint=result['fingerprint'])
                store.event(current,'script_evaluated',f'Slide {number}, revision {saved["revision"]}; local critic {body.model}; no clinical approval.')
        except Exception as exc:
            agent_failure(project_id,number,exc)
            raise
    return submit(project_id,'evaluate',operation)

@app.post('/api/projects/{project_id}/slides/{number}/draft')
def draft(project_id:str,number:int,body:DraftRequest):
    def operation(cancel):
        p=store.get(project_id)
        source_slide=evidence_slide(p,get_slide(p,number))
        detected=None
        if source_slide.get('image') and not source_slide.get('text','').strip() and not source_slide.get('visual_text','').strip():
            from . import ocr
            if not ocr.available():
                raise ValueError('This slide stores its text in an image. Set up offline OCR or add the visible text under Source > Image text before drafting.')
            detected=ocr.extract_text(store.directory(project_id)/'slides'/f'slide-{number}.png',cancel)
            source_slide.update(visual_text=detected['text'],source_reviewed=False)
        workflow_result=None
        if body.workflow=='agents':
            from . import agent_workflow
            folder=agent_folder(project_id,number,body.model,'draft')
            try:
                workflow_result=agent_workflow.run(source_slide,body.model,p['audience'],run_folder=folder,
                    style=body.style,cancel=cancel,progress=lambda pc,msg:progress(project_id,pc,msg))
                result=narration.Draft.model_validate(workflow_result['candidate'])
                media.check(cancel)
            except Exception as exc:
                agent_failure(project_id,number,exc)
                raise
        else:
            from .evaluation import model_slot
            with model_slot(cancel):
                result=narration.generate(source_slide,body.model,p['audience'],style=body.style,cancel=cancel)
        media.check(cancel)
        with store.edit(project_id) as p:
            s=get_slide(p,number)
            if s['revision']!=source_slide['revision']:
                raise ValueError('The source changed during drafting. Build a draft from the saved revision again.')
            if detected is not None:
                s.update(ocr=detected,visual_text=detected['text'],source_reviewed=False)
                store.event(p,'image_text_detected',f'Slide {number}; automatically included local OCR in drafting; requires visual verification.')
            s.update(narration=result.narration,revision=s['revision']+1,approved=False,approved_at=None,reviewer='',draft_origin=f'Local AI · {body.model}')
            s['ai_flags']=result.review_flags
            s['narration_quality']=result.quality
            s['evaluation']=({**workflow_result['evaluation'],'assessed_revision':s['revision']} if workflow_result else None)
            s.pop('evaluation_error',None)
            if workflow_result:
                s['agent_run'].update(status='completed',trace=workflow_result['trace'],fingerprint=workflow_result['fingerprint'])
            store.event(p,'ai_draft',f'Slide {number}; {body.model}; {body.style}; prompt {narration.PROMPT_VERSION}')
    get_slide(store.get(project_id),number)
    return submit(project_id,'draft',operation)

class VoiceRequest(BaseModel):
    engine:Literal['kokoro','piper','windows','qwen']='kokoro'
    voice:Literal['af_heart','af_bella','am_michael','bf_emma','Ryan','Aiden']='af_heart'
    rate:float=Field(ge=.7,le=1.4,default=1)
    delivery:Literal['warm','clear','engaging']='warm'

    @model_validator(mode='after')
    def compatible_voice(self):
        if self.engine=='qwen' and self.voice not in {'Ryan','Aiden'}:
            raise ValueError('Choose Aiden or Ryan for the Qwen narrator.')
        if self.engine=='kokoro' and self.voice in {'Ryan','Aiden'}:
            raise ValueError('Choose a Kokoro voice for the Kokoro engine.')
        return self


class DraftPreviewRequest(VoiceRequest):
    engine:Literal['kokoro','qwen']='kokoro'
    visual_style:Literal['focus','whiteboard']='focus'


class PreviewCancellation:
    """Gracefully stop CLI children, then let media.run enforce termination."""
    def __init__(self,token,marker):
        self.token=token
        self.marker=marker
        self.requested_at=None
    def is_set(self):
        if not self.token.is_set():
            return False
        if self.requested_at is None:
            self.marker.touch()
            self.requested_at=time.monotonic()
        return time.monotonic()-self.requested_at>=8


@app.post('/api/projects/{project_id}/slides/{number}/preview')
def preview_slide(project_id:str,number:int,body:DraftPreviewRequest):
    from scripts.render_draft_preview import source_fingerprint
    preview_id=uuid.uuid4().hex
    snapshot={}
    def validate(p):
        slide=get_slide(p,number)
        visual=store.DATA/project_id/'slides'/f'slide-{number}.png'
        if not slide['narration'].strip():
            raise HTTPException(400,'Save a narration draft before generating its private preview.')
        if not slide.get('image') or not visual.is_file():
            raise HTTPException(400,'Render this slide before generating its private preview.')
        snapshot.update(project=json.loads(json.dumps(p)),slide=json.loads(json.dumps(slide)),
                        fingerprint=source_fingerprint(p,slide,visual))
    def operation(cancel):
        p=snapshot['project'];slide=snapshot['slide']
        visual=store.directory(project_id)/'slides'/f'slide-{number}.png'
        current=store.get(project_id)
        if source_fingerprint(current,get_slide(current,number),visual)!=snapshot['fingerprint']:
            raise ValueError('The source or script changed while this preview was queued. Retry the saved revision.')
        folder=store.directory(project_id)/'draft-previews'/preview_id
        folder.mkdir(parents=True)
        paragraphs=narration_paragraphs(slide['narration'])
        cues=slide.get('visual_cues',[])
        regions=[{**cue,'paragraph':min(len(paragraphs)-1,max(0,cue.get('paragraph') if cue.get('paragraph') is not None else index*len(paragraphs)//len(cues)))}
                 for index,cue in enumerate(cues)]
        direction={'title':slide['title'],'regions':regions,
                   'timing_note':'Authored paragraph choices are used when present; automatic placement follows paragraph order and is not semantic alignment.'}
        (folder/'direction.json').write_text(json.dumps(direction),encoding='utf-8')
        progress(project_id,5,'Creating a private video with a permanent unapproved draft banner')
        marker=folder/'cancel.requested'
        command=[sys.executable,str(store.ROOT/'scripts'/'render_draft_preview.py'),
            '--project-id',project_id,'--slide',str(number),'--engine',body.engine,'--voice',body.voice,
            '--delivery',body.delivery,'--rate',str(body.rate),'--visual-style',body.visual_style,
            '--direction',str(folder/'direction.json'),'--output-dir',str(folder),
            '--expected-revision',str(slide['revision']),'--expected-fingerprint',snapshot['fingerprint'],
            '--cancel-file',str(marker)]
        try:
            from .evaluation import model_slot
            with model_slot(cancel) if body.engine=='qwen' else nullcontext():
                media.run(command,PreviewCancellation(cancel,marker),cwd=store.ROOT,timeout=7200)
        except Exception:
            media.check(cancel)
            raise
        media.check(cancel)
        manifest=json.loads((folder/'manifest.json').read_text(encoding='utf-8'))
        duration=manifest.get('duration')
        if (manifest.get('kind')!='unapproved-draft-preview' or manifest.get('clinical_approval') is not False
                or manifest.get('revision')!=slide['revision'] or manifest.get('source_fingerprint')!=snapshot['fingerprint']
                or manifest.get('project_id')!=project_id or manifest.get('slide')!=number
                or manifest.get('text_sha256')!=hashlib.sha256(slide['narration'].encode('utf-8')).hexdigest()
                or any(manifest.get(key)!=value for key,value in body.model_dump().items())
                or not isinstance(duration,(int,float)) or not 0<duration<7200
                or not manifest.get('quality',{}).get('verified') or not (folder/'presentation.mp4').is_file()):
            raise ValueError('Draft preview verification failed. No preview was published.')
        metadata={'id':preview_id,'url':f'/api/projects/{project_id}/draft-previews/{preview_id}/presentation.mp4',
                  'slide':number,'revision':slide['revision'],'created_at':store.now(),
                  'engine':body.engine,'voice':body.voice,'delivery':body.delivery,'rate':body.rate,
                  'visual_style':body.visual_style,'duration':duration,'source_fingerprint':snapshot['fingerprint'],
                  'clinical_approval':False}
        with store.edit(project_id) as current:
            media.check(cancel)
            saved=get_slide(current,number)
            if source_fingerprint(current,saved,visual)!=snapshot['fingerprint']:
                raise ValueError('The source or script changed during this preview. Retry the saved revision.')
            saved['draft_preview']=metadata
            current.setdefault('draft_previews',[]).append(metadata)
            store.event(current,'draft_preview_created',f'Slide {number}, revision {slide["revision"]}; private, permanently marked unapproved.')
    return submit(project_id,'preview',operation,validate)


@app.get('/api/projects/{project_id}/draft-previews/{preview_id}/{filename}')
def draft_preview_video(project_id:str,preview_id:str,filename:str):
    import re
    p=store.get(project_id)
    if (filename!='presentation.mp4' or not re.fullmatch(r'[a-f0-9]{32}',preview_id)
            or not any(item.get('id')==preview_id for item in p.get('draft_previews',[]))):
        raise HTTPException(404,'Private draft preview not found.')
    root=store.directory(project_id).resolve()
    path=(root/'draft-previews'/preview_id/'presentation.mp4').resolve()
    if not path.is_relative_to(root) or not path.is_file():
        raise HTTPException(404,'This private draft preview is unavailable. Generate a new preview.')
    return FileResponse(path,media_type='video/mp4')

_preview_lock=threading.Lock()

@app.post('/api/voice-preview')
def preview_voice(body:VoiceRequest):
    # Fixed, nonclinical audition. Unapproved user scripts never reach this path.
    text="Let's take this one step at a time. A good lesson does more than deliver information. It gives you a moment to notice, to question, and to understand. Ready to try it? Choose a chapter, listen to the explanation, then pause and put the idea into your own words."
    key=hashlib.sha256(('voice-v3'+json.dumps(body.model_dump(),sort_keys=True)).encode()).hexdigest()
    folder=store.DATA/'voice-previews'
    folder.mkdir(parents=True,exist_ok=True)
    output=folder/f'{key}.wav'
    try:
        with _preview_lock:
            if not output.is_file():
                temporary=folder/f'{key}.part.wav'
                if body.engine=='qwen':
                    media.synthesize(text,temporary,body.engine,body.rate,threading.Event(),body.voice,delivery=body.delivery)
                else:
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
    visual_style:Literal['whiteboard','studio','focus','powerpoint']='whiteboard'

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
                'knowledge':s.get('knowledge'),'visual_cues':s.get('visual_cues',[]),'sources':s['sources'],
                'visual_text':s.get('visual_text',''),'source_reviewed':s.get('source_reviewed',False)}
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
