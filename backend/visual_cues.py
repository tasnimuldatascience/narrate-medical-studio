"""Source-anchored educational annotations, rendered offline by libass.

Only explicitly authored labels and coordinates are used. Rings identify a
location; they do not depict anatomical or procedural movement.
"""
import math
from pathlib import Path


STAGE = (64, 136, 1856, 928)


def map_point(x, y, source_size, stage=STAGE):
    """Map a normalized point through Pillow's contain fit and centering."""
    width, height = source_size
    left, top, right, bottom = stage
    if width <= 0 or height <= 0 or right <= left or bottom <= top:
        raise ValueError('Source and stage dimensions must be positive.')
    if not all(math.isfinite(float(value)) for value in (x, y)):
        raise ValueError('Visual cue coordinates must be finite.')
    # Match ImageOps.contain integer dimensions, including rounding.
    # Calculate the contain result without allocating a source-sized image.
    ratio = width / height
    target_ratio = (right-left)/(bottom-top)
    fitted_width, fitted_height = right-left, bottom-top
    if ratio > target_ratio:
        fitted_height = round((right-left)/width*height)
    elif ratio < target_ratio:
        fitted_width = round((bottom-top)/height*width)
    offset_x = left+(right-left-fitted_width)//2
    offset_y = top+(bottom-top-fitted_height)//2
    return (round(offset_x+min(1,max(0,float(x)))*(fitted_width-1)),
            round(offset_y+min(1,max(0,float(y)))*(fitted_height-1)))


def escape_label(value):
    """Use literal lookalike glyphs for ASS controls; retain readable content."""
    return ' '.join(str(value).split()).replace('\\','＼').replace('{','｛').replace('}','｝')


def _timestamp(seconds):
    centiseconds = max(0,round(seconds*100))
    seconds, fraction = divmod(centiseconds,100)
    minutes, seconds = divmod(seconds,60)
    hours, minutes = divmod(minutes,60)
    return f'{hours}:{minutes:02}:{seconds:02}.{fraction:02}'


def write_visual_cues(cues, duration, source_size, output_path, stage=STAGE):
    """Write one sequential callout per authored cue, leaving captions clear.

    Cue labels are at most 120 characters. The ring briefly expands in place;
    the source artwork itself is never modified or interpreted.
    """
    if len(cues) > 6:
        raise ValueError('A slide supports up to six visual cues.')
    if not math.isfinite(duration) or duration <= 0:
        raise ValueError('Narration duration must be positive and finite.')
    if cues and duration/len(cues) < .1:
        raise ValueError('Narration is too short to display the visual cues.')
    header = '''[Script Info]
ScriptType: v4.00+
PlayResX: 1920
PlayResY: 1080
ScaledBorderAndShadow: yes
WrapStyle: 2

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: VCLabel,Segoe UI,30,&H00F5F8FC,&H00F5F8FC,&H001B1009,&H001B1009,-1,0,0,0,100,100,0,0,3,12,0,7,0,0,0,1
Style: VCMarker,Segoe UI,30,&H00C7DE70,&H00C7DE70,&H00C7DE70,&HFF000000,0,0,0,0,100,100,0,0,1,2,0,5,0,0,0,1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
'''
    events = []
    slot = duration/max(1,len(cues))
    for index,cue in enumerate(cues):
        label = escape_label(cue['label'])
        if not label or len(label) > 120:
            raise ValueError('Visual cue labels must contain 1–120 characters.')
        x,y = map_point(cue['x'],cue['y'],source_size,stage)
        # Pixel measurement prevents unexpectedly wide labels overflowing.
        from .compositor import _font
        font = _font(30,True)
        lines=[]
        line=''
        for word in label.split():
            proposed=f'{line} {word}'.strip()
            if font.getlength(proposed)>470:
                if line:
                    lines.append(line)
                    line=''
                while font.getlength(word)>470:
                    split=1
                    while split<len(word) and font.getlength(word[:split+1])<=470:
                        split+=1
                    lines.append(word[:split])
                    word=word[split:]
                line=word
            else:
                line=proposed
        if line:
            lines.append(line)
        label_width=math.ceil(max(font.getlength(line) for line in lines))+28
        label_height=39*len(lines)+20
        label_x=x+58 if x+58+label_width<1850 else x-58-label_width
        label_x=max(80,min(1830-label_width,label_x))
        label_y=max(156,min(916-label_height,y-(39*len(lines))//2))
        anchor_x=label_x-14 if label_x>x else label_x+label_width
        anchor_y=label_y+(39*len(lines))//2
        start=index*slot
        end=(index+1)*slot
        fade=min(160,round(slot*1000/5))
        def event(layer,style,text):
            events.append(f'Dialogue: {layer},{_timestamp(start)},{_timestamp(end)},{style},,0,0,0,,{text}')
        common=f'\\fad({fade},{fade})'
        # Line and ring are fixed to the authored position throughout the cue.
        event(10,'VCMarker',f'{{\\an7\\pos(0,0)\\p1\\bord0\\1a&H55&{common}}}'
              f'm {x} {y-1} l {anchor_x} {anchor_y-1} {anchor_x} {anchor_y+1} {x} {y+1}{{\\p0}}')
        # Nonnegative drawing coordinates keep libass's bounding-box alignment
        # centered exactly on the source point (negative coordinates offset it).
        circle='m 0 23 b 0 10 10 0 23 0 b 36 0 46 10 46 23 b 46 36 36 46 23 46 b 10 46 0 36 0 23'
        event(11,'VCMarker',f'{{\\an5\\pos({x},{y})\\p1\\1a&HFF&\\bord3\\fscx55\\fscy55\\t(0,{min(360,round(slot*500))},\\fscx100\\fscy100){common}}}{circle}{{\\p0}}')
        text='\\N'.join(lines)
        event(12,'VCLabel',f'{{\\pos({label_x},{label_y}){common}}}{text}')
    path=Path(output_path)
    path.parent.mkdir(parents=True,exist_ok=True)
    path.write_text(header+'\n'.join(events)+'\n',encoding='utf-8')
    return path
