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
from backend import media, store, whiteboard
from backend.compositor import _font


def banner(frame):
    frame=frame.copy()
    draw=ImageDraw.Draw(frame)
    draw.rectangle((0,0,1920,70),fill='#80302D')
    draw.text((72,18),'DRAFT PREVIEW  /  UNAPPROVED  /  FOR REVIEW ONLY',font=_font(28,True),fill='white')
    return frame


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--project-id',required=True)
    parser.add_argument('--slide',required=True,type=int)
    parser.add_argument('--direction',type=Path,help='Local JSON: title and optional regions with paragraph index (zero-based).')
    parser.add_argument('--voice',default='af_bella',choices=['af_heart','af_bella','am_michael','bf_emma'])
    parser.add_argument('--rate',type=float,default=.97)
    args=parser.parse_args()
    if not .7<=args.rate<=1.4:raise ValueError('Rate must be 0.7–1.4.')
    project=store.get(args.project_id)
    slide=next(s for s in project['slides'] if s['number']==args.slide)
    visual=store.directory(project['id'])/'slides'/f'slide-{args.slide}.png'
    if not visual.is_file():raise ValueError('Render the source slide first.')
    paragraphs=[p.strip() for p in slide['narration'].split('\n\n') if p.strip()]
    if not paragraphs:raise ValueError('Save a narration draft first.')
    direction=json.loads(args.direction.read_text(encoding='utf-8')) if args.direction else {}
    regions=direction.get('regions',[])
    if len(regions)>6:raise ValueError('At most six authored regions are supported.')
    if any(not isinstance(r.get('paragraph'),int) or not 0<=r['paragraph']<len(paragraphs) for r in regions):
        raise ValueError('Each region must reference an existing paragraph.')
    ffmpeg=shutil.which('ffmpeg')
    if not ffmpeg or not shutil.which('ffprobe'):raise ValueError('FFmpeg and ffprobe are required.')
    import uuid
    folder=store.DATA/'validation'/f'draft-preview-slide-{args.slide}-{uuid.uuid4().hex[:8]}'
    folder.mkdir(parents=True)
    cancel=threading.Event()
    base,full,bounds,rectangles=whiteboard.prepare(visual,project['name'],
        direction.get('title',slide['title']),1,1,regions)
    frames=[]
    def frame(canvas,seconds):
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
        local,duration=media.synthesize(paragraph,wav,'kokoro',args.rate,cancel,args.voice)
        cues.extend({**c,'start':c['start']+cursor,'end':c['end']+cursor} for c in media.split_caption_cues(local))
        slot=duration+.4
        active=next((j for j,r in enumerate(regions) if r['paragraph']==i),None)
        if active is not None:
            reveal=min(.45,slot*.2)
            for step in range(1,7):
                frame(whiteboard.paint(full,full,regions,rectangles,completed,active,step/6),reveal/6)
            completed=max(completed,active+1)
            frame(whiteboard.paint(full,full,regions,rectangles,completed,active),slot-reveal)
        else:
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
    manifest={'kind':'unapproved-draft-preview','clinical_approval':False,'project_id':project['id'],
        'slide':args.slide,'revision':slide['revision'],'source_sha256':hashlib.sha256(visual.read_bytes()).hexdigest(),
        'narration':slide['narration'],'origin':slide.get('draft_origin'),'review_flags':slide.get('ai_flags',[]),
        'direction':direction,'voice':args.voice,'rate':args.rate,'duration':duration,'quality':quality,
        'timing':'Region changes follow measured paragraph starts; subtitles are estimated within speech blocks.'}
    (folder/'manifest.json').write_text(json.dumps(manifest,ensure_ascii=False,indent=2),encoding='utf-8')
    (folder/'transcript.txt').write_text('UNAPPROVED DRAFT PREVIEW\n\n'+slide['narration'],encoding='utf-8')
    print(json.dumps({'video':str(folder/'presentation.mp4'),'duration':duration,'quality':quality}),flush=True)


if __name__=='__main__':main()
