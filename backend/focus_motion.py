"""A smooth camera over supplied source pixels, with context before/after detail."""
import math
from pathlib import Path
from PIL import Image
from . import whiteboard


def camera_box(rect, amount):
    if not math.isfinite(amount) or not 0<=amount<=1:
        raise ValueError('Camera progress must be between zero and one.')
    left,top,right,bottom=whiteboard.STAGE
    width,height=right-left,bottom-top
    x0,y0,x1,y1=rect
    target=min(3.,width/max(1,(x1-x0)*1.2),height/max(1,(y1-y0)*1.35))
    zoom=1+(max(1,target)-1)*(amount*amount*(3-2*amount))
    w,h=width/zoom,height/zoom
    weight=amount*amount*(3-2*amount)
    x=width/2+(((x0+x1)/2-left)-width/2)*weight
    y=height/2+(((y0+y1)/2-top)-height/2)*weight
    x=min(width-w/2,max(w/2,x));y=min(height-h/2,max(h/2,y))
    return (x-w/2,y-h/2,x+w/2,y+h/2)


def paint(source,cues,regions,completed,active=None,amount=0,overview=False):
    frame=whiteboard.paint(source,source,cues,regions,completed,active,overview=overview)
    if active is None or amount==0 or overview:
        return frame
    stage=source.crop(whiteboard.STAGE)
    box=camera_box(regions[active],amount)
    focused=stage.transform(stage.size,Image.Transform.EXTENT,box,
        resample=Image.Resampling.BICUBIC)
    # Fade surrounding content out as the authored detail grows. Adjacent
    # partially cropped headings must not compete with the explanation.
    left,top,_,_=whiteboard.STAGE
    x0,y0,x1,y1=regions[active]
    scale=stage.width/(box[2]-box[0])
    detail=(max(0,round((x0-left-box[0])*scale)-4),max(0,round((y0-top-box[1])*scale)-4),
        min(stage.width,round((x1-left-box[0])*scale)+4),min(stage.height,round((y1-top-box[1])*scale)+4))
    isolated=Image.new('RGB',stage.size,'white')
    isolated.paste(focused.crop(detail),detail[:2])
    focused=Image.blend(focused,isolated,amount*amount*(3-2*amount))
    frame.paste(focused,whiteboard.STAGE[:2])
    return frame


def render_focus(source_path,output_path,lesson_title,slide_title,number,total,cues,
                 duration,ffmpeg,cancel,run,captions=None,cue_starts=None):
    from .media import check
    if not math.isfinite(duration) or duration<=0:
        raise ValueError('Focus duration must be positive.')
    _,source,_,regions=whiteboard.prepare(source_path,lesson_title,slide_title,number,total,cues)
    output=Path(output_path);frames_dir=output.parent/f'focus-{number}'
    frames_dir.mkdir(exist_ok=True);sequence=[]
    def add(frame,seconds):
        check(cancel)
        if seconds<=0:return
        path=frames_dir/f'frame-{len(sequence):03d}.png'
        frame.save(path,compress_level=1);sequence.append((path.name,seconds))
    if not cues:
        add(paint(source,cues,regions,0),duration)
    else:
        lead=min(.9,duration*.1);tail=min(1.8,duration*.1)
        from .scene_timing import scene_spans
        lead,slots,tail=scene_spans(duration,len(cues),cue_starts,lead=lead,tail=tail)
        add(paint(source,cues,regions,0),lead)
        for i in range(len(cues)):
            slot=slots[i]
            motion=min(.8,slot*.2)
            for step in range(1,13):
                add(paint(source,cues,regions,i+1,i,step/12),motion/12)
            add(paint(source,cues,regions,i+1,i,1),slot-2*motion)
            for step in range(11,-1,-1):
                add(paint(source,cues,regions,i+1,i,step/12),motion/12)
        add(paint(source,cues,regions,len(cues),overview=True),tail)
    listing=''.join(f"file '{name}'\nduration {seconds:.9f}\n" for name,seconds in sequence)
    (frames_dir/'frames.txt').write_text(listing+f"file '{sequence[-1][0]}'\n",encoding='utf-8')
    filters='fps=24'+(f',ass={captions}' if captions else '')
    run([ffmpeg,'-y','-v','error','-f','concat','-safe','0','-i',f'{frames_dir.name}/frames.txt',
        '-vf',filters,'-t',str(duration),'-c:v','libx264','-preset','fast','-crf','18',
        '-pix_fmt','yuv420p','-an',output.name],cancel,cwd=output.parent)
    return output
