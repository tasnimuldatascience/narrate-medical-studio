"""Compare spoken narration on local source slides. No approval or media export.

Results contain source text and therefore remain under ignored local data.
"""
import argparse
import hashlib
import json
import re
import subprocess
import sys
import time
import types
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from backend import narration, store


def metrics(text):
    # Readability aids only: neither sentence length nor a model establishes
    # clinical correctness or whether a learner understands the explanation.
    words=re.findall(r"\b[\w]+(?:[’'-][\w]+)*\b",text)
    sentences=[part.strip() for part in re.split(r'(?<=[.!?])\s+',text) if part.strip()]
    lengths=[len(re.findall(r"\b[\w]+(?:[’'-][\w]+)*\b",s)) for s in sentences]
    return {'words':len(words),'sentences':len(sentences),
            'mean_sentence_words':round(len(words)/max(1,len(sentences)),1),
            'long_sentences_over_26_words':sum(n>26 for n in lengths),
            'paragraphs':len([p for p in text.split('\n\n') if p.strip()])}


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--project-id',required=True)
    parser.add_argument('--slides',default='4,6,13')
    parser.add_argument('--model',default='qwen3:4b')
    parser.add_argument('--baseline',default='e18702f')
    parser.add_argument('--style',choices=['conversational','concise'],default='conversational')
    parser.add_argument('--ocr-source',type=Path,help='Local OCR JSON keyed by slide number; used only in this evaluation.')
    parser.add_argument('--skip-baseline',action='store_true',help='Compare the saved script with the candidate without rerunning the previous model prompt.')
    args=parser.parse_args()
    project=store.get(args.project_id)
    selected={int(n.strip()) for n in args.slides.split(',')}
    slides=[s for s in project['slides'] if s['number'] in selected]
    if len(slides)!=len(selected):
        raise ValueError('One or more requested slides do not exist.')
    baseline=None
    if not args.skip_baseline:
        old_code=subprocess.check_output(['git','show',f'{args.baseline}:backend/narration.py'],cwd=store.ROOT,text=True,encoding='utf-8')
        baseline=types.ModuleType('narration_baseline')
        sys.modules[baseline.__name__]=baseline
        exec(compile(old_code,'narration_baseline','exec'),baseline.__dict__)
    ocr=json.loads(args.ocr_source.read_text(encoding='utf-8')) if args.ocr_source else {}
    model_name=re.sub(r'[^A-Za-z0-9_.-]','-',args.model)
    stamp=time.strftime('%Y%m%d-%H%M%S')
    out=store.DATA/'validation'/f'narration-{args.project_id}-{model_name}-{args.style}-{stamp}'
    out.mkdir(parents=True,exist_ok=True)
    results=[]
    for slide in slides:
        if str(slide['number']) in ocr:
            slide=dict(slide,visual_text=ocr[str(slide['number'])]['text'],source_reviewed=False)
        path=out/f'slide-{slide["number"]}.json'
        print(f'Slide {slide["number"]}: {narration.PROMPT_VERSION}',flush=True)
        before=baseline.generate(slide,args.model,project['audience']) if baseline else narration.Draft(narration=slide['narration'],review_flags=[])
        source={key:slide.get(key) for key in ('text','notes','tables','visual_text','source_reviewed')}
        after=narration.generate(slide,args.model,project['audience'],style=args.style)
        result={'number':slide['number'],'title':slide['title'],
            'source':source,
            'source_sha256':hashlib.sha256(json.dumps(source,sort_keys=True).encode()).hexdigest(),
            'original':slide['narration'],'baseline':before.model_dump(),'candidate':after.model_dump(),
            'metrics':{'original':metrics(slide['narration']),'baseline':metrics(before.narration),'candidate':metrics(after.narration)}}
        path.write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
        results.append(result)
        print(json.dumps({'slide':slide['number'],'metrics':result['metrics'],'flags':after.review_flags}),flush=True)
    report={'project_id':project['id'],'model':args.model,'style':args.style,
        'baseline_version':baseline.PROMPT_VERSION if baseline else 'saved-script','candidate_version':narration.PROMPT_VERSION,
        'created_at':store.now(),'clinical_approval':False,'results':results}
    (out/'comparison.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    md=['# Spoken narration comparison','',f'Local model: {args.model}. Style: {args.style}.',
        '','Draft comparison for review. No clinical approval or audio/video generation.',
        'Sentence counts are editing aids, not measures of comprehension or clinical accuracy.','']
    for result in results:
        md.extend([f'## Slide {result["number"]}', '', '### Previous narration', '', result['original'],
            '', '### New spoken draft', '', result['candidate']['narration'], '', '### Review flags', '',
            *['- '+flag for flag in result['candidate']['review_flags']], '',
            '### Writing measurements', '', '```json',json.dumps(result['metrics'],indent=2),'```',''])
    (out/'comparison.md').write_text('\n'.join(md),encoding='utf-8')
    print('Comparison report: '+str(out/'comparison.md'),flush=True)


if __name__=='__main__':
    main()
