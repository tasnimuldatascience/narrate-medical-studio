"""Local, source-linked editorial evaluation. Findings never grant approval."""
import hashlib
import inspect
import json
import re
import threading
from contextlib import contextmanager
from typing import Literal

import httpx
from pydantic import BaseModel, Field, ConfigDict

from . import media, narration, evidence_review
from .ollama_schema import transport_schema

VERSION='local-evaluation-v2-evidence-addressed'
CRITIC_VERSION=evidence_review.VERSION
OPTIONS={'temperature':0,'seed':73,'num_predict':3500,'num_ctx':16384}
MODEL_LOCK=threading.RLock()
CRITIC_SYSTEM=evidence_review.ALIGN_SYSTEM
CRITIC_REPAIR_SYSTEM=evidence_review.VERIFY_SYSTEM



class ModelOutputError(ValueError):
    def __init__(self, message, raw_response, validation_error):
        super().__init__(message)
        self.raw_response=raw_response
        self.validation_error=validation_error


class QuoteValidationError(ValueError):
    pass


class CriticValidationError(ValueError):
    def __init__(self, message, attempts):
        super().__init__(message)
        self.validation_attempts=attempts


def canonical(value):
    return json.dumps(value,sort_keys=True,separators=(',',':'),ensure_ascii=False)


def digest(value):
    return hashlib.sha256(canonical(value).encode('utf-8')).hexdigest()


def runtime_fingerprint():
    return digest({'protocol': evidence_review.VERSION, 'options': OPTIONS,
        'reviewer': inspect.getsource(evidence_review),
        'evaluation': inspect.getsource(__import__(__name__, fromlist=['evaluate'])),
        'source_preparation': inspect.getsource(narration.prepare_source),
        'transport': inspect.getsource(transport_schema)})


def prompt_evidence(packet):
    # Avoid serializing source twice; entries already carry its complete content.
    return {k:v for k,v in packet.items() if k != 'source'}


def check(cancel):
    if cancel is not None:
        media.check(cancel)


@contextmanager
def model_slot(cancel=None):
    while not MODEL_LOCK.acquire(timeout=.1):
        check(cancel)
    try:
        check(cancel)
        yield
    finally:
        MODEL_LOCK.release()


def build_evidence(slide):
    source=narration.prepare_source(slide)
    entries=[]
    def add(kind,location,text):
        if text.strip():
            entry={'kind':kind,'location':location,'text':text}
            entry['id']='ev-'+digest({'slide':slide.get('number'),**entry})[:24]
            entries.append(entry)
    for kind in ('text','notes','image_text'):
        # Keep full context together so qualifier/condition quotes remain visible.
        add(kind,kind,source[kind])
    for t,table in enumerate(source['tables']):
        for r,row in enumerate(table):
            for c,cell in enumerate(row):
                add('table',f'table:{t}/row:{r}/column:{c}',cell)
    packet={'version':'source-evidence-v1','slide':slide.get('number'),
            'revision':slide.get('revision',1),'source':source,'entries':entries,
            'original_source_hash':slide.get('source_sha256'),
            'source_image_hash':slide.get('source_image_sha256'),
            'source_reviewed':source['source_reviewed']}
    # Editorial/quiz revisions do not change the source. The workflow separately
    # fingerprints revision, while reports retain a content-bound source hash.
    packet['hash']=digest({k:v for k,v in packet.items() if k != 'revision'})
    return packet


class Finding(BaseModel):
    model_config=ConfigDict(extra='forbid')
    severity:Literal['high','medium','low']
    category:Literal['quantity','qualifier','source_fidelity','source_conflict','readability']
    message:str=Field(min_length=1,max_length=2000)
    source_quote:str=Field(max_length=12000)
    draft_quote:str=Field(max_length=12000)
    evidence_ids:list[str]=Field(max_length=20)
    remediation:str=Field(min_length=1,max_length=2000)


class CriticOutput(BaseModel):
    model_config=ConfigDict(extra='forbid')
    summary:str=Field(min_length=1,max_length=2000)
    findings:list[Finding]=Field(max_length=30)


def resolve_model(model,cancel=None):
    """Inspect local model identity without sending any presentation content."""
    if not re.fullmatch(r'[A-Za-z0-9_.:/-]{1,120}',model) or 'cloud' in model.lower():
        raise ValueError('Choose an installed, fully local model.')
    with model_slot(cancel),httpx.Client(trust_env=False,timeout=15) as client:
        response=client.get(narration.OLLAMA+'/api/tags')
        check(cancel)
        response.raise_for_status()
        found=next((m for m in response.json().get('models',[]) if m.get('name')==model),None)
        if found is None:
            raise ValueError('The evaluation model is not installed locally.')
        response=client.post(narration.OLLAMA+'/api/show',json={'model':model})
        check(cancel)
        response.raise_for_status()
        metadata=response.json()
        if (metadata.get('remote_model') or metadata.get('remote_host') or
            re.search(r'^\s*FROM\s+\S*cloud\S*',metadata.get('modelfile',''),re.I|re.M)):
            raise ValueError('Remote-backed models are disabled for evaluation.')
        if not isinstance(found.get('digest'),str) or not found['digest']:
            raise ValueError('The installed model has no digest; restart/update the local model runtime before resumable evaluation.')
        return {'name':model,'digest':found['digest']}


def local_json(model,system,payload,schema,*,cancel=None,identity=None,options=None):
    prompt=canonical(payload)
    if len(system)+len(prompt)>40000:
        raise ValueError('The combined evaluation context is too large. Split the source slide before evaluating.')
    configured=dict(options or OPTIONS)
    # A conservative UTF-8 byte bound reserves room for every input token and
    # template overhead, instead of relying on a characters/4 approximation.
    # Never let the local runtime silently drop the start of the source packet.
    input_bound=len((system+prompt).encode('utf-8'))+512
    available=int(configured.get('num_ctx',16384))-input_bound-512
    if available<2000:
        raise ValueError('The complete evidence cannot fit with a bounded response in the local context. Split this slide; no partial-source audit was requested.')
    configured['num_predict']=min(int(configured.get('num_predict',3500)),available)
    with model_slot(cancel):
        current=resolve_model(model,cancel)
        if identity is not None and current!=identity:
            raise ValueError('The installed model changed during this run. Start a new run.')
        check(cancel)
        with httpx.Client(trust_env=False,timeout=300) as client:
            response=client.post(narration.OLLAMA+'/api/generate',json={
                'model':model,'stream':False,'think':False,'keep_alive':0,'system':system,'prompt':prompt,
                'format':transport_schema(schema),'options':configured})
            check(cancel)
            response.raise_for_status()
            try:
                result=response.json()
                if (not isinstance(result,dict) or result.get('done') is False or
                    result.get('done_reason')=='length' or not str(result.get('response','')).strip()):
                    raise ValueError('empty or incomplete output')
            except (ValueError,TypeError,KeyError) as exc:
                raise ValueError('The local evaluator returned empty, incomplete, or invalid JSON. No evaluation was accepted; retry or use practitioner review.') from exc
            try:
                parsed=schema.model_validate_json(result['response'])
            except (ValueError,TypeError,KeyError) as exc:
                raise ModelOutputError('The local evaluator returned invalid JSON. No evaluation was accepted.',
                    result.get('response',''),str(exc)[:2000]) from exc
        return parsed


def validate_quotes(findings,packet,script):
    evidence={entry['id']:entry['text'] for entry in packet['entries']}
    for index,finding in enumerate(findings):
        f=finding.model_dump() if isinstance(finding,Finding) else finding
        if any(identifier not in evidence for identifier in f['evidence_ids']):
            raise QuoteValidationError(f'The critic cited an unknown source evidence ID in finding {index+1}. Evaluation was rejected. IDs: {f["evidence_ids"]}')
        if not f['source_quote'] and not f['draft_quote']:
            raise QuoteValidationError('A critic finding has no source or draft quotation. Evaluation was rejected.')
        if f['source_quote'] and not any(f['source_quote'] in evidence[i] for i in f['evidence_ids']):
            raise QuoteValidationError(f'The critic fabricated or altered a source quotation. Evaluation was rejected. Finding {index+1}, source_quote={f["source_quote"]!r}, evidence_ids={f["evidence_ids"]}')
        if f['draft_quote'] and f['draft_quote'] not in script:
            raise QuoteValidationError(f'The critic fabricated or altered a draft quotation. Evaluation was rejected. Finding {index+1}, draft_quote={f["draft_quote"]!r}')


def deterministic_findings(packet,script,quality):
    findings=[]
    cases=[('unsupported_numbers','quantity','high','Some draft numeric spellings were not matched literally in the source.'),
           ('missing_source_numbers','quantity','high','Some source numeric spellings were not matched literally in the draft.'),
           ('missing_source_quantities','quantity','high','Source quantity/unit wording was not matched in the draft.'),
           ('missing_source_qualifiers','qualifier','high','Source qualifiers or negations were not matched in the draft.'),
           ('unsupported_absolutes','qualifier','high','Absolute or mandatory wording differs lexically from the source.')]
    for key,category,severity,message in cases:
        if not quality.get(key):
            continue
        findings.append({'severity':severity,'category':category,
            'message':message+' Lexical hints: '+', '.join(quality[key])[:1000],
            'source_quote':'','draft_quote':script[:300],'evidence_ids':[],
            'remediation':'Compare the complete source and draft statements. Confirm quantities, conditions, and claim scope; literal mismatch alone is not proof of a clinical error.'})
    if quality.get('long_sentence_count'):
        findings.append({'severity':'low','category':'readability',
            'message':f"{quality['long_sentence_count']} sentence(s) exceed 25 words.",
            'source_quote':'','draft_quote':script[:300],'evidence_ids':[],
            'remediation':'Split dense spoken thoughts while retaining each condition with its action.'})
    if packet['source']['image_text'] and not packet['source_reviewed']:
        entry=next(e for e in packet['entries'] if e['kind']=='image_text')
        findings.append({'severity':'high','category':'source_fidelity',
            'message':'Image transcription has not been checked by a practitioner.',
            'source_quote':entry['text'],'draft_quote':'','evidence_ids':[entry['id']],
            'remediation':'Check the transcription, including every quantity and unit, against the original image before approving.'})
    return [{'id':'finding-'+digest(f)[:20],'origin':'deterministic',**f} for f in findings]


def evaluate(packet,script,model,audience,*,cancel=None,identity=None):
    check(cancel)
    if not isinstance(script,str) or not script.strip() or len(script)>12000:
        raise ValueError('Evaluation needs a nonempty script of at most 12000 characters.')
    identity=identity or resolve_model(model,cancel)
    quality=narration.assess_quality(script,packet['source'])
    audit=evidence_review.run(__import__(__name__,fromlist=['evaluate']),packet,script,model,audience,
        cancel=cancel,identity=identity)
    diagnostics=deterministic_findings(packet,script,quality)
    notices=[f for f in diagnostics if f['category']=='source_fidelity']
    hints=[{**f,'severity':'low','auto_revision_allowed':False,'verification':'lexical_hint_only'}
           for f in diagnostics if f['category']!='source_fidelity']
    findings=notices+audit['findings']
    count=len(audit['findings']); uncertain=len(audit['uncertain']); dismissed=len(audit['dismissed'])
    summary=(f'{count} potential source discrepancies retained after source alignment and challenge review; '
             f'{uncertain} unresolved comparisons; {dismissed} proposed findings refuted. '
             'Model agreement is not proof. Practitioner source review remains required.')
    return {'version':VERSION,'state':'review_required','clinical_validation':False,
        'source_hash':packet['hash'],'script_hash':digest(script),'model':model,
        'model_identity':identity,'evaluator_fingerprint':runtime_fingerprint(),'audience':audience,
        'findings':findings,'review_hints':hints,'quality':quality,'summary':summary,
        'uncertain_findings':audit['uncertain'],'dismissed_findings':audit['dismissed'],
        'evidence_audit':audit,'evaluation_protocol':evidence_review.VERSION,
        'critic_validation_attempts':audit['model_call_count'],
        'review_stage_count':audit['stage_count'],
        'validation_repair_used':bool(audit['validation_attempts']),
        'validation_attempt_reasons':[a['reason'] for a in audit['validation_attempts']],
        'auto_revision_allowed':False,'requires_practitioner_review':True}
