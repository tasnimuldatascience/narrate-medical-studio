"""Offline, authored whiteboard reveals using only reviewed source regions.

The renderer never invents anatomy. Its drawing motion reveals source pixels;
all locations, extents, order, and labels come from the reviewed visual story.
"""
import math
from pathlib import Path

from PIL import Image, ImageDraw, ImageOps

from .compositor import _font, _ellipsis, _wrap

STAGE = (72, 174, 1432, 912)
INK = '#213D43'
MUTED = '#687C7D'
COLORS = ['#167D8D', '#D16E55', '#6C72A8', '#548968', '#AB7B32', '#9A6089']


def source_bounds(size):
    """The exact integer fitted extent, shared with region mapping and tests."""
    width, height = size
    if width <= 0 or height <= 0:
        raise ValueError('Source image dimensions must be positive.')
    fitted = ImageOps.contain(Image.new('RGB', (width, height)),
                             (STAGE[2]-STAGE[0], STAGE[3]-STAGE[1])).size
    x = STAGE[0] + (STAGE[2]-STAGE[0]-fitted[0])//2
    y = STAGE[1] + (STAGE[3]-STAGE[1]-fitted[1])//2
    return (x, y, x+fitted[0], y+fitted[1])


def region_bounds(cue, bounds):
    x, y = float(cue['x']), float(cue['y'])
    width, height = float(cue.get('width', .24)), float(cue.get('height', .24))
    if not all(math.isfinite(v) for v in (x, y, width, height)):
        raise ValueError('Region coordinates must be finite.')
    if not (0 <= x <= 1 and 0 <= y <= 1 and .02 <= width <= 1 and .02 <= height <= 1):
        raise ValueError('Region coordinates are outside the source image.')
    left, top, right, bottom = bounds
    w, h = right-left, bottom-top
    return (left+round(max(0, x-width/2)*w), top+round(max(0, y-height/2)*h),
            left+round(min(1, x+width/2)*w), top+round(min(1, y+height/2)*h))


def label_lines(draw, text, width=280, height=94):
    """Fit the complete reviewed label; never silently omit source wording."""
    text = ' '.join(str(text).split())
    if not text or len(text) > 120:
        raise ValueError('Visual labels must contain 1–120 characters.')
    for size in range(24, 9, -1):
        font = _font(size, True)
        lines, line = [], ''
        for char in text:
            if line and draw.textlength(line+char, font=font) > width:
                split = line.rfind(' ')
                if split > 0:
                    lines.append(line[:split])
                    line = line[split+1:]+char
                else:
                    lines.append(line)
                    line = char
            else:
                line += char
        if line:
            lines.append(line)
        if len(lines)*(size+4) <= height:
            return font, size+4, lines
    raise ValueError('This visual label cannot fit. Shorten the reviewed label.')


def prepare(source_path, lesson_title, slide_title, number, total, cues):
    if len(cues) > 6 or not 1 <= number <= total:
        raise ValueError('Invalid whiteboard chapter or cue count.')
    canvas = Image.new('RGB', (1920, 1080), '#FBFCFA')
    draw = ImageDraw.Draw(canvas)
    draw.text((72, 27), _ellipsis(draw, lesson_title, _font(23), 1550), font=_font(23), fill=MUTED)
    draw.text((70, 63), _ellipsis(draw, slide_title, _font(43, True), 1650), font=_font(43, True), fill=INK)
    draw.text((1742, 40), f'{number:02d} / {total:02d}', font=_font(25), fill=MUTED)
    draw.line((72, 137, 1848, 137), fill='#CCDAD7', width=2)
    draw.line((1462, 174, 1462, 912), fill='#DFE7E2', width=2)
    draw.text((1500, 176), 'FOLLOW THE EXPLANATION', font=_font(17, True), fill=MUTED)
    with Image.open(source_path) as original:
        source = ImageOps.exif_transpose(original).convert('RGBA')
        bounds = source_bounds(source.size)
        fitted = ImageOps.contain(source, (STAGE[2]-STAGE[0], STAGE[3]-STAGE[1]), Image.Resampling.LANCZOS)
        white = Image.new('RGBA', fitted.size, 'white')
        white.alpha_composite(fitted)
        full = canvas.copy()
        full.paste(white.convert('RGB'), bounds[:2])
    # The light page boundary communicates the space being progressively revealed.
    draw.rectangle(bounds, fill='white', outline='#E2E8E1', width=1)
    draw.rounded_rectangle((72, 1050, 1848, 1054), radius=2, fill='#E3EAE4')
    draw.rounded_rectangle((72, 1050, 72+round(1776*number/total), 1054), radius=2, fill=COLORS[0])
    # Bring the source onto a matching page, preserving all editorial decoration.
    full.paste(canvas.crop((0, 930, 1920, 1080)), (0, 930))
    regions = [region_bounds(c, bounds) for c in cues]
    return canvas, full, bounds, regions


def paint(base, source, cues, regions, completed, active=None, fraction=1., overview=False):
    canvas = base.copy()
    if overview or not cues:
        canvas.paste(source.crop(STAGE), STAGE[:2])
    else:
        for rect in regions[:completed]:
            canvas.paste(source.crop(rect), rect[:2])
        if active is not None:
            left, top, right, bottom = regions[active]
            edge = left+round((right-left)*fraction)
            if edge > left:
                canvas.paste(source.crop((left, top, edge, bottom)), (left, top))
    draw = ImageDraw.Draw(canvas)
    for i, cue in enumerate(cues):
        y = 235+i*106
        visible = i < completed or i == active or overview
        color = COLORS[i] if visible else '#BDC9C4'
        draw.ellipse((1500, y, 1536, y+36), fill=color)
        draw.text((1511, y+4), str(i+1), font=_font(21, True), fill='white')
        # Hidden labels avoid giving the entire explanation away immediately.
        if visible:
            font, line_height, lines = label_lines(draw, cue['label'])
            for j, line in enumerate(lines):
                draw.text((1552, y-2+j*line_height), line, font=font, fill=INK)
        else:
            draw.rounded_rectangle((1552, y+9, 1750, y+14), radius=2, fill='#E3EAE4')
    if active is not None and not overview:
        left, top, right, bottom = regions[active]
        color = COLORS[active]
        # An irregular double stroke gives an editorial marker treatment while
        # leaving the supplied anatomical drawing unchanged underneath it.
        draw.line([(left, bottom+4), (left-3, top-3), (right+2, top-2),
                   (right+4, bottom+3), (left, bottom+4)], fill=color, width=3)
        if fraction < 1:
            edge = left+round((right-left)*fraction)
            draw.line((edge, top, edge, bottom), fill=color, width=3)
            draw.ellipse((edge-7, bottom-7, edge+7, bottom+7), fill=color)
    if not cues:
        for j, line in enumerate(_wrap(draw, 'Notice the key relationships in this visual.', _font(29, True), 330)):
            draw.text((1500, 255+j*38), line, font=_font(29, True), fill=INK)
    return canvas


def render_whiteboard(source_path, output_path, lesson_title, slide_title, number,
                      total, cues, duration, ffmpeg, cancel, run, captions=None,cue_starts=None):
    from .media import check
    if not math.isfinite(duration) or duration <= 0:
        raise ValueError('Whiteboard duration must be positive.')
    base, source, bounds, regions = prepare(source_path, lesson_title, slide_title, number, total, cues)
    output = Path(output_path)
    frames_dir = output.parent/f'board-{number}'
    frames_dir.mkdir(exist_ok=True)
    sequence = []
    def frame(canvas, seconds):
        check(cancel)
        if seconds <= 0:
            return
        path = frames_dir/f'frame-{len(sequence):03d}.png'
        canvas.save(path, compress_level=1)
        sequence.append((path.name, seconds))
    if not cues:
        frame(paint(base, source, cues, regions, 0), duration)
    else:
        lead = min(.9, duration*.12)
        overview_time = min(1.8, duration*.15)
        from .scene_timing import scene_spans
        lead,slots,overview_time=scene_spans(duration,len(cues),cue_starts,lead=lead,tail=overview_time)
        frame(paint(base, source, cues, regions, 0,overview=cue_starts is not None), lead)
        for i in range(len(cues)):
            slot=slots[i]
            reveal = min(.5, slot*.3)
            for step in range(1, 7):
                frame(paint(base, source, cues, regions, i, i, step/6), reveal/6)
            frame(paint(base, source, cues, regions, i+1, i), slot-reveal)
        frame(paint(base, source, cues, regions, len(cues), overview=True), overview_time)
    listing = ''.join(f"file '{name}'\nduration {seconds:.9f}\n" for name, seconds in sequence)
    listing += f"file '{sequence[-1][0]}'\n"
    (frames_dir/'frames.txt').write_text(listing, encoding='utf-8')
    filters = 'fps=24'
    if captions:
        filters += f',ass={captions}'
    run([ffmpeg, '-y', '-v', 'error', '-f', 'concat', '-safe', '0', '-i',
         f'{frames_dir.name}/frames.txt', '-vf', filters, '-t', str(duration),
         '-c:v', 'libx264', '-preset', 'fast', '-crf', '18', '-pix_fmt', 'yuv420p',
         '-an', output.name], cancel, cwd=output.parent)
    return output
