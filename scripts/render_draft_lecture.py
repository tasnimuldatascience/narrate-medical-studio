"""Render a complete local lecture manuscript for private, unapproved review.

No project writes or approval changes. Resume only in the same output directory
with the exact plan, source snapshot and settings. Qwen audio is independently
verified and reused per slide; interrupted video scenes are rebuilt.
"""
import argparse
import hashlib
import json
import math
from pathlib import Path
import shutil
import sys
import wave
from PIL import Image

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from backend import media, store, qwen_voice, whiteboard, focus_motion, lesson
from backend.evaluation import model_slot
from backend.scene_timing import paragraphs, paragraph_cue_starts, scene_spans
from scripts.render_draft_preview import banner, FileCancellation, source_fingerprint


def digest(value):
    return hashlib.sha256(json.dumps(value,sort_keys=True,ensure_ascii=True).encode()).hexdigest()


def write_json(path,value):
    temporary=path.with_name(path.name+'.tmp')
    temporary.write_text(json.dumps(value,indent=2,ensure_ascii=False),encoding='utf-8')
    temporary.replace(path)


def validate_knowledge(value):
    if value is None:return
    if not isinstance(value,dict) or set(value)!={'question','options','correct','explanation'}:
        raise ValueError('Knowledge checks require question, options, correct and explanation.')
    for key,maximum in [('question',500),('explanation',1500)]:
        if not isinstance(value[key],str) or not value[key].strip() or len(value[key])>maximum:
            raise ValueError(f'Knowledge check {key} is empty or too long.')
    options=value['options']
    if (not isinstance(options,list) or len(options)!=3
            or any(not isinstance(option,str) or not option.strip() for option in options)
            or len({option.strip().casefold() for option in options})!=3):
        raise ValueError('Knowledge checks require three distinct, nonempty answer choices.')
    if type(value['correct']) is not int or not 0<=value['correct']<3:
        raise ValueError('Knowledge check correct answer must be an index from zero to two.')


def validate_plan(project,plan):
    if plan.get('project_id')!=project['id'] or plan.get('source_sha256')!=project.get('source_sha256'):
        raise ValueError('The lecture plan must identify this project and its exact source deck checksum.')
    entries=plan.get('slides',[])
    expected=[slide['number'] for slide in project['slides']]
    if sorted(entry['number'] for entry in entries)!=sorted(expected):
        raise ValueError('The plan must contain every source slide exactly once.')
    indexed={entry['number']:entry for entry in entries}
    slides=[];fingerprints={}
    for original in project['slides']:
        number=original['number'];entry=indexed[number]
        if type(entry.get('source_rotation',0)) is not int or entry.get('source_rotation',0) not in (0,90,180,270):
            raise ValueError(f'Slide {number} source_rotation must be 0, 90, 180 or 270 clockwise degrees.')
        visual=store.directory(project['id'])/'slides'/f'slide-{number}.png'
        fingerprint=source_fingerprint(project,original,visual)
        if entry.get('source_fingerprint',fingerprint)!=fingerprint:
            raise ValueError(f'Slide {number} source fingerprint has changed.')
        text=entry['narration']
        qwen_voice.validate_request(text,'Aiden',1,'engaging')
        regions=entry.get('visual_cues',[])
        validate_knowledge(entry.get('knowledge'))
        if len(regions)>6:raise ValueError(f'Slide {number} has more than six focus regions.')
        for region in regions:
            if (not isinstance(region.get('label'),str) or not region['label'].strip()
                    or len(region['label'])>120):raise ValueError('Focus labels require 1–120 characters.')
            for field,minimum,default in [('x',0,None),('y',0,None),('width',.02,.24),('height',.02,.24)]:
                value=region.get(field,default)
                if isinstance(value,bool) or not isinstance(value,(int,float)) or not math.isfinite(value) or not minimum<=value<=1:
                    raise ValueError(f'Slide {number} has invalid region {field}.')
            paragraph=region.get('paragraph')
            if (region['x']-region.get('width',.24)/2 < -1e-9 or region['x']+region.get('width',.24)/2 > 1+1e-9
                    or region['y']-region.get('height',.24)/2 < -1e-9 or region['y']+region.get('height',.24)/2 > 1+1e-9):
                raise ValueError(f'Slide {number} focus rectangle extends beyond the source image.')
            if paragraph is not None and (isinstance(paragraph,bool) or not isinstance(paragraph,int)
                    or not 0<=paragraph<len(paragraphs(text))):
                raise ValueError(f'Slide {number} region refers to a missing paragraph.')
        linked=[region.get('paragraph') for region in regions]
        if any(value is not None for value in linked):
            if any(value is None for value in linked):
                raise ValueError(f'Slide {number} must link every focus region to a paragraph or use automatic placement for all.')
            try:
                scene_spans(len(paragraphs(text))+2,len(regions),[float(value)+.9 for value in linked],lead=.9,tail=.25)
            except ValueError as exc:
                raise ValueError(f'Slide {number}: {exc}') from exc
        slides.append({**original,**entry,'approved':False,'visual_cues':regions})
        fingerprints[str(number)]=fingerprint
    return slides,fingerprints


def transformed_source(visual,folder,rotation):
    """Rotate a derived PNG clockwise; keep the original source untouched."""
    if not rotation:return visual
    output=folder/'source-rotated.png'
    with Image.open(visual) as image:
        image.convert('RGB').transpose({90:Image.Transpose.ROTATE_270,
            180:Image.Transpose.ROTATE_180,270:Image.Transpose.ROTATE_90}[rotation]).save(output)
    return output


def render_scene(visual,output,title,slide,index,total,duration,starts,ffmpeg,cancel):
    """Burn the permanent banner into every generated image before encoding."""
    regions=slide['visual_cues']
    visual=transformed_source(visual,output.parent,slide.get('source_rotation',0))
    _,source,_,rectangles=whiteboard.prepare(visual,title,slide['title'],index,total,regions)
    folder=output.parent/'frames';folder.mkdir(exist_ok=True)
    frames=[]
    def add(image,seconds):
        media.check(cancel)
        if seconds<=0:return
        name=f'frame-{len(frames):03d}.png'
        banner(image).save(folder/name,compress_level=1)
        frames.append((name,seconds))
    lead,slots,tail=scene_spans(duration,len(regions),starts,
        lead=min(.9,duration*.1),tail=min(1.8,duration*.1))
    add(focus_motion.paint(source,regions,rectangles,0),lead)
    for active,slot in enumerate(slots):
        motion=min(.8,slot*.2)
        for step in range(1,13):
            add(focus_motion.paint(source,regions,rectangles,active+1,active,step/12),motion/12)
        add(focus_motion.paint(source,regions,rectangles,active+1,active,1),slot-2*motion)
        for step in range(11,-1,-1):
            add(focus_motion.paint(source,regions,rectangles,active+1,active,step/12),motion/12)
    add(focus_motion.paint(source,regions,rectangles,len(regions),overview=True),tail)
    listing=''.join(f"file '{name}'\nduration {seconds:.9f}\n" for name,seconds in frames)
    (folder/'frames.txt').write_text(listing+f"file '{frames[-1][0]}'\n",encoding='utf-8')
    media.run([ffmpeg,'-y','-v','error','-f','concat','-safe','0','-i','frames/frames.txt',
        '-vf','fps=24,ass=captions.ass','-t',str(duration),'-an','-c:v','libx264',
        '-preset','fast','-crf','18','-pix_fmt','yuv420p','scene.partial.mp4'],cancel,cwd=output.parent)
    (output.parent/'scene.partial.mp4').replace(output)


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--project-id',required=True)
    parser.add_argument('--plan',type=Path,required=True)
    parser.add_argument('--output-dir',type=Path,required=True)
    parser.add_argument('--voice',choices=list(qwen_voice.VOICES),default='Aiden')
    parser.add_argument('--delivery',choices=list(qwen_voice.STYLES),default='engaging')
    parser.add_argument('--rate',type=float,default=1)
    parser.add_argument('--cancel-file',type=Path)
    args=parser.parse_args()
    if str(args.output_dir).startswith(('\\\\','//')):raise ValueError('Use a local output directory.')
    project=store.get(args.project_id)
    plan=json.loads(args.plan.read_text(encoding='utf-8'))
    slides,fingerprints=validate_plan(project,plan)
    qwen_voice.validate_request(slides[0]['narration'],args.voice,args.rate,args.delivery)
    ffmpeg=shutil.which('ffmpeg');ffprobe=shutil.which('ffprobe')
    if not ffmpeg or not ffprobe:raise ValueError('FFmpeg and FFprobe are required.')
    folder=args.output_dir.resolve();folder.mkdir(parents=True,exist_ok=True)
    identity={'renderer_version':1,'project_id':project['id'],'source_sha256':project['source_sha256'],
        'plan_sha256':digest(plan),'source_fingerprints':fingerprints,
        'voice':args.voice,'delivery':args.delivery,'rate':args.rate,'model_revision':qwen_voice.REVISION}
    identity['code_hashes']={name:qwen_voice.file_hash(store.ROOT/name) for name in [
        'scripts/render_draft_lecture.py','scripts/render_draft_preview.py','backend/qwen_voice.py',
        'backend/media.py','backend/focus_motion.py','backend/whiteboard.py','backend/scene_timing.py',
        'backend/compositor.py','backend/speech_text.py','backend/lesson.py','backend/lesson.html']}
    snapshot=folder/'render-request.json'
    if snapshot.exists():
        if json.loads(snapshot.read_text(encoding='utf-8'))!=identity:
            raise ValueError('Output belongs to a different plan, source revision or voice. Choose a new directory.')
    elif any(folder.iterdir()):raise ValueError('A new render needs an empty output directory.')
    write_json(snapshot,identity)
    write_json(folder/'plan.json',plan)
    cancel=FileCancellation(args.cancel_file)
    def progress(percent,message):
        media.check(cancel)
        write_json(folder/'progress.json',{'percent':round(percent,2),'message':message})
        print(json.dumps({'percent':round(percent,2),'message':message}),flush=True)
    audio_dir=folder/'audio';audio_dir.mkdir(exist_ok=True)
    items=[{'text':slide['narration'],'output':audio_dir/f'slide-{slide["number"]}.wav'} for slide in slides]
    with model_slot(cancel):
        voiced=qwen_voice.synthesize_batch(items,args.voice,args.rate,cancel,style=args.delivery,
            progress=lambda percent,message:progress(percent*.8,message))
    all_cues=[];transcript=[];chapters=[];audio_parts=[];segments=[];elapsed=0.
    for index,(slide,item,(blocks,speech_duration)) in enumerate(zip(slides,items,voiced)):
        media.check(cancel)
        number=slide['number'];local=folder/f'part-{number}';local.mkdir(exist_ok=True)
        lead=.9;duration=math.ceil((lead+speech_duration+1.25)*24)/24
        cues=[{**cue,'start':cue['start']+lead,'end':cue['end']+lead} for cue in media.split_caption_cues(blocks)]
        media.write_captions(cues,local,light=True)
        with wave.open(str(item['output']),'rb') as source:
            with wave.open(str(local/'lead.wav'),'wb') as silence:
                silence.setparams(source.getparams());silence.writeframes(b'\0'*(round(lead*source.getframerate())*source.getnchannels()*source.getsampwidth()))
        audio_parts.extend([(local/'lead.wav',lead),(item['output'],duration-lead)])
        starts=paragraph_cue_starts(slide['narration'],slide['visual_cues'],blocks,duration,speech_lead=lead,style='focus')
        segment=local/'scene.mp4'
        scene_identity={'request':digest(identity),'number':number,'duration':duration,'audio_sha256':qwen_voice.file_hash(item['output'])}
        marker=local/'complete.json'
        cached=False
        if marker.exists() and segment.is_file():
            try:
                completed=json.loads(marker.read_text())
                cached=(completed.get('identity')==scene_identity and
                    completed.get('video_sha256')==qwen_voice.file_hash(segment))
            except (OSError,ValueError):pass
        if not cached:
            progress(80+index/len(slides)*15,f'Rendering watermarked scene {index+1}/{len(slides)}')
            render_scene(store.directory(project['id'])/'slides'/f'slide-{number}.png',segment,
                project['name'],slide,index+1,len(slides),duration,starts,ffmpeg,cancel)
            write_json(marker,{'identity':scene_identity,'video_sha256':qwen_voice.file_hash(segment)})
        segments.append(f'part-{number}/scene.mp4')
        all_cues.extend({**cue,'start':cue['start']+elapsed,'end':cue['end']+elapsed} for cue in cues)
        transcript.extend({**block,'start':block['start']+elapsed+lead,'end':block['end']+elapsed+lead} for block in blocks)
        chapters.append({'number':number,'title':slide['title'],'start':elapsed,'end':elapsed+duration,
            'knowledge':slide.get('knowledge'),'sources':slide.get('sources',[])})
        elapsed+=duration
    progress(95,'Joining the complete PCM lecture and encoding AAC once')
    media.join_audio(audio_parts,folder/'narration.wav',cancel)
    media.write_captions(all_cues,folder,light=True)
    (folder/'concat.txt').write_text('\n'.join(f"file '{name}'" for name in segments),encoding='utf-8')
    media.run([ffmpeg,'-y','-v','error','-f','concat','-safe','0','-i','concat.txt','-i','narration.wav',
        '-i','captions.srt','-map','0:v','-map','1:a','-map','2:0','-c:v','copy','-c:a','aac',
        '-b:a','192k','-ar','48000','-c:s','mov_text','-metadata','comment=DRAFT UNAPPROVED PRIVATE REVIEW ONLY',
        '-movflags','+faststart','presentation.mp4'],cancel,cwd=folder,timeout=7200)
    quality=media.audit_video(folder,elapsed,cancel)
    quality['caption_timing']='Estimated within measured speech blocks; paragraph-linked focus starts use measured block boundaries.'
    current=store.get(project['id'])
    _,current_fingerprints=validate_plan(current,plan)
    if current_fingerprints!=fingerprints:raise ValueError('Source project changed during rendering; output remains an unapproved draft.')
    flags=[{'number':slide['number'],'flags':slide.get('flags',[]),
        'review_flags':slide.get('review_flags',slide.get('ai_flags',[])),
        'source_reviewed':slide.get('source_reviewed',False)} for slide in slides]
    write_json(folder/'source-flags.json',flags)
    write_json(folder/'chapters.json',chapters)
    write_json(folder/'quality.json',quality)
    write_json(folder/'provenance.json',{**identity,'created_at':store.now(),
        'source_transforms':[{'number':slide['number'],'clockwise_rotation':slide.get('source_rotation',0),
            'original_preserved':True,'region_coordinates':'normalized in the displayed, rotated source image'} for slide in slides],
        'origins':[{'number':slide['number'],'origin':slide.get('origin',slide.get('draft_origin'))} for slide in slides]})
    manifest={'kind':'unapproved-full-lecture','clinical_approval':False,'slide_count':len(slides),
        'duration':elapsed,'quality':quality,**identity}
    write_json(folder/'manifest.json',manifest)
    (folder/'transcript.txt').write_text('DRAFT / UNAPPROVED / FOR PRIVATE REVIEW ONLY\n\n'+'\n\n'.join(
        f'Slide {slide["number"]}: {slide["title"]}\n{slide["narration"]}' for slide in slides),encoding='utf-8')
    media.check(cancel)
    lesson.package(folder,project['name'],chapters,all_cues,burn_captions=True,
        transcript=transcript,draft_banner=True)
    progress(100,'Complete unapproved lecture and offline interactive package are ready for private review.')
    print(json.dumps({'video':str(folder/'presentation.mp4'),'package':str(folder/'interactive-lesson.zip'),**manifest}),flush=True)


if __name__=='__main__':main()
