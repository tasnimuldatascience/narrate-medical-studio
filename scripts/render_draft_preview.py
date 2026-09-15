"""Render one explicitly requested, visibly unapproved video for private review.

This is separate from the reviewed-lesson exporter. It never changes a project,
grants approval, or creates a publishable lesson package. Every frame carries a
permanent draft banner. Optional region labels/coordinates are author supplied.
"""
import argparse
import hashlib
import json
import math
import shutil
import sys
import threading
import wave
from pathlib import Path

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from PIL import ImageDraw
from backend import media, store, whiteboard, focus_motion
from backend.compositor import _font
from backend.scene_timing import paragraphs as narration_paragraphs


def source_fingerprint(project,slide,visual):
    """Bind the preview to the exact saved script, source, and authored cues."""
    evidence={'project_id':project['id'],'name':project['name'],
        'source_sha256':project.get('source_sha256'),
        'slide':{key:slide.get(key) for key in ('number','title','revision','narration',
            'text','notes','tables','visual_text','source_reviewed','visual_cues')},
        'image_sha256':hashlib.sha256(Path(visual).read_bytes()).hexdigest()}
    return hashlib.sha256(json.dumps(evidence,sort_keys=True,ensure_ascii=True).encode()).hexdigest()


class FileCancellation:
    """Let the API ask nested voice/encoder processes to stop before CLI exit."""
    def __init__(self,path=None):
        self.path=path
    def is_set(self):
        return self.path is not None and self.path.is_file()


def banner(frame):
    frame=frame.copy()
    draw=ImageDraw.Draw(frame)
    draw.rectangle((0,0,1920,70),fill='#80302D')
    draw.text((72,18),'DRAFT PREVIEW  /  UNAPPROVED  /  FOR REVIEW ONLY',font=_font(28,True),fill='white')
    return frame


def cached_paragraphs(path,paragraphs,voice,delivery,rate):
    """Reuse only audio whose measured passages match this exact saved script."""
    report=json.loads(path.with_suffix('.qwen.json').read_text(encoding='utf-8'))
    normalize=lambda text:' '.join(text.split())
    cues=report['cues']
    if (report['voice']!=voice or report['style']!=delivery or report['requested_rate']!=rate
            or normalize(' '.join(c['text'] for c in cues))!=normalize(' '.join(paragraphs))):
        raise ValueError('Cached audio does not match the saved narration and requested voice settings.')
    with wave.open(str(path),'rb') as wav:
        params=wav.getparams();raw=wav.readframes(wav.getnframes())
    groups=[];offset=0
    for paragraph in paragraphs:
        parts=[]
        while offset<len(cues) and normalize(' '.join(c['text'] for c in parts))!=normalize(paragraph):
            parts.append(cues[offset]);offset+=1
        if normalize(' '.join(c['text'] for c in parts))!=normalize(paragraph):
            raise ValueError('Cached speech blocks do not preserve the paragraph boundaries.')
        start=parts[0]['start'];end=parts[-1]['end']
        if not 0<=start<end<=params.nframes/params.framerate+.01:
            raise ValueError('Cached speech timing lies outside its audio.')
        begin=round(start*params.framerate);finish=round(end*params.framerate)
        stride=params.nchannels*params.sampwidth
        groups.append((params,raw[begin*stride:finish*stride],
            [{**c,'start':c['start']-start,'end':c['end']-start} for c in parts],(finish-begin)/params.framerate))
    return groups


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--project-id',required=True)
    parser.add_argument('--slide',required=True,type=int)
    parser.add_argument('--direction',type=Path,help='Local JSON: title and optional regions with paragraph index (zero-based).')
    parser.add_argument('--engine',default='kokoro',choices=['kokoro','qwen'])
    parser.add_argument('--voice',default='af_bella',choices=['af_heart','af_bella','am_michael','bf_emma','Ryan','Aiden'])
    parser.add_argument('--delivery',default='warm',choices=['warm','clear','engaging'])
    parser.add_argument('--visual-style',default='focus',choices=['focus','whiteboard'])
    parser.add_argument('--audio-cache',type=Path,help='Reuse matching Qwen WAV and its .qwen.json measured passage report.')
    parser.add_argument('--rate',type=float,default=.97)
    parser.add_argument('--output-dir',type=Path,help='Explicit new local output folder, optionally containing direction.json.')
    parser.add_argument('--expected-revision',type=int)
    parser.add_argument('--expected-fingerprint',help='Require this exact saved source/script fingerprint before rendering.')
    parser.add_argument('--cancel-file',type=Path,help='Local cancellation marker controlled by the private preview job.')
    args=parser.parse_args()
    if not .7<=args.rate<=1.4:raise ValueError('Rate must be 0.7–1.4.')
    if (args.engine=='qwen') != (args.voice in {'Ryan','Aiden'}):
        raise ValueError('Choose Ryan or Aiden for Qwen, or a Kokoro voice for Kokoro.')
    project=store.get(args.project_id)
    slide=next(s for s in project['slides'] if s['number']==args.slide)
    visual=store.directory(project['id'])/'slides'/f'slide-{args.slide}.png'
    if not visual.is_file():raise ValueError('Render the source slide first.')
    fingerprint=source_fingerprint(project,slide,visual)
    if args.expected_revision is not None and args.expected_revision!=slide['revision']:
        raise ValueError('The slide revision changed before preview rendering. Retry the saved revision.')
    if args.expected_fingerprint is not None and args.expected_fingerprint!=fingerprint:
        raise ValueError('The source or script changed before preview rendering. Retry the saved revision.')
    paragraphs=narration_paragraphs(slide['narration'])
    if not paragraphs:raise ValueError('Save a narration draft first.')
    cached=cached_paragraphs(args.audio_cache,paragraphs,args.voice,args.delivery,args.rate) if args.audio_cache else None
    direction=json.loads(args.direction.read_text(encoding='utf-8')) if args.direction else {}
    regions=direction.get('regions',[])
    if len(regions)>6:raise ValueError('At most six authored regions are supported.')
    if any(not isinstance(r.get('paragraph'),int) or not 0<=r['paragraph']<len(paragraphs) for r in regions):
        raise ValueError('Each region must reference an existing paragraph.')
    ffmpeg=shutil.which('ffmpeg')
    if not ffmpeg or not shutil.which('ffprobe'):raise ValueError('FFmpeg and ffprobe are required.')
    import uuid
    folder=args.output_dir or store.DATA/'validation'/f'draft-preview-slide-{args.slide}-{uuid.uuid4().hex[:8]}'
    if str(folder).startswith(('\\\\','//')):
        raise ValueError('Draft previews require a local output folder.')
    folder=folder.resolve()
    if folder.exists() and any(p.name!='direction.json' for p in folder.iterdir()):
        raise ValueError('Choose a new draft preview output folder; existing output is never overwritten.')
    folder.mkdir(parents=True,exist_ok=True)
    cancel=FileCancellation(args.cancel_file)
    media.check(cancel)
    if args.engine=='qwen' and cached is None:
        print('Creating the complete draft narration in one local Qwen model session',flush=True)
        whole_audio=folder/'full-narration.wav'
        media.synthesize(slide['narration'],whole_audio,args.engine,args.rate,cancel,args.voice,delivery=args.delivery)
        cached=cached_paragraphs(whole_audio,paragraphs,args.voice,args.delivery,args.rate)
    base,full,bounds,rectangles=whiteboard.prepare(visual,project['name'],
        direction.get('title',slide['title']),1,1,regions)
    frames=[]
    def frame(canvas,seconds):
        media.check(cancel)
        path=folder/f'frame-{len(frames):03d}.png'
        banner(canvas).save(path)
        frames.append((path.name,seconds))
    def silence(name,seconds):
        path=folder/name
        with wave.open(str(path),'wb') as out:
            out.setnchannels(1);out.setsampwidth(2);out.setframerate(24000)
            out.writeframes(b'\0'*(round(seconds*24000)*2))
        return path
    lead,tail=.9,1.25
    audio=[(silence('lead.wav',lead),lead)]
    cues=[];cursor=lead;completed=0
    frame(whiteboard.paint(full,full,regions,rectangles,0),lead)
    for i,paragraph in enumerate(paragraphs):
        print(f'Creating draft voice paragraph {i+1}/{len(paragraphs)}',flush=True)
        wav=folder/f'paragraph-{i}.wav'
        if cached:
            params,raw,local,duration=cached[i]
            with wave.open(str(wav),'wb') as out:
                out.setparams(params);out.writeframes(raw)
        else:
            local,duration=media.synthesize(paragraph,wav,args.engine,args.rate,cancel,args.voice,delivery=args.delivery)
        cues.extend({**c,'start':c['start']+cursor,'end':c['end']+cursor} for c in media.split_caption_cues(local))
        slot=duration+.4
        active_regions=[j for j,r in enumerate(regions) if r['paragraph']==i]
        for active in active_regions:
            region_slot=slot/len(active_regions)
            if args.visual_style=='focus':
                reveal=min(.8,region_slot*.2)
                for step in range(1,13):
                    frame(focus_motion.paint(full,regions,rectangles,active+1,active,step/12),reveal/12)
                completed=max(completed,active+1)
                frame(focus_motion.paint(full,regions,rectangles,completed,active,1),region_slot-2*reveal)
                for step in range(11,-1,-1):
                    frame(focus_motion.paint(full,regions,rectangles,completed,active,step/12),reveal/12)
            else:
                reveal=min(.45,region_slot*.2)
                for step in range(1,7):
                    frame(whiteboard.paint(full,full,regions,rectangles,completed,active,step/6),reveal/6)
                completed=max(completed,active+1)
                frame(whiteboard.paint(full,full,regions,rectangles,completed,active),region_slot-reveal)
        if not active_regions:
            frame(whiteboard.paint(full,full,regions,rectangles,completed),slot)
        audio.append((wav,slot));cursor+=slot
    duration=math.ceil((cursor+tail)*24)/24
    tail=duration-cursor
    audio.append((silence('tail.wav',tail),tail))
    frame(whiteboard.paint(full,full,regions,rectangles,len(regions),overview=True),tail)
    listing=''.join(f"file '{name}'\nduration {seconds:.9f}\n" for name,seconds in frames)
    (folder/'frames.txt').write_text(listing+f"file '{frames[-1][0]}'\n",encoding='utf-8')
    media.join_audio(audio,folder/'narration.wav',cancel)
    media.write_captions(cues,folder,light=True)
    print('Encoding the source-slide draft preview',flush=True)
    media.run([ffmpeg,'-y','-v','error','-f','concat','-safe','0','-i','frames.txt',
        '-i','narration.wav','-i','captions.srt','-vf','fps=24,ass=captions.ass',
        '-map','0:v','-map','1:a','-map','2:0','-t',str(duration),
        '-c:v','libx264','-preset','fast','-crf','18','-pix_fmt','yuv420p',
        '-c:a','aac','-b:a','192k','-ar','48000','-c:s','mov_text',
        '-metadata','comment=Unapproved draft preview for private review only',
        '-movflags','+faststart','presentation.mp4'],cancel,cwd=folder)
    quality=media.audit_video(folder,duration,cancel)
    from backend.audio_quality import inspect_audio
    quality['audio']=inspect_audio(folder/'narration.wav')
    current=store.get(project['id'])
    current_slide=next(s for s in current['slides'] if s['number']==args.slide)
    if source_fingerprint(current,current_slide,visual)!=fingerprint:
        raise ValueError('The source or script changed during preview rendering. Retry the saved revision.')
    media.check(cancel)
    manifest={'kind':'unapproved-draft-preview','clinical_approval':False,'project_id':project['id'],
        'source_fingerprint':fingerprint,'text_sha256':hashlib.sha256(slide['narration'].encode('utf-8')).hexdigest(),
        'slide':args.slide,'revision':slide['revision'],'source_sha256':hashlib.sha256(visual.read_bytes()).hexdigest(),
        'narration':slide['narration'],'origin':slide.get('draft_origin'),'review_flags':slide.get('ai_flags',[]),
        'direction':direction,'visual_style':args.visual_style,'engine':args.engine,'voice':args.voice,'delivery':args.delivery,'rate':args.rate,'duration':duration,'quality':quality,
        'timing':'Authored regions are assigned to paragraphs in order; multiple regions share paragraph time evenly. This is not semantic alignment. Subtitles are estimated within speech blocks.'}
    (folder/'manifest.json').write_text(json.dumps(manifest,ensure_ascii=False,indent=2),encoding='utf-8')
    (folder/'transcript.txt').write_text('UNAPPROVED DRAFT PREVIEW\n\n'+slide['narration'],encoding='utf-8')
    print(json.dumps({'video':str(folder/'presentation.mp4'),'duration':duration,'quality':quality}),flush=True)


if __name__=='__main__':main()
