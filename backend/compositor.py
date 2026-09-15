"""Deterministic, offline visual scenes for reviewed presentation material."""
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter, ImageFont, ImageOps


WIDTH, HEIGHT = 1920, 1080
STAGE = (64, 136, 1856, 928)
INK = '#F2F5FA'
MUTED = '#9BABBF'
ACCENT = '#70DEC7'


def _font(size, bold=False):
    names = [
        Path('C:/Windows/Fonts') / ('segoeuib.ttf' if bold else 'segoeui.ttf'),
        Path('/usr/share/fonts/truetype/dejavu') / ('DejaVuSans-Bold.ttf' if bold else 'DejaVuSans.ttf'),
    ]
    for path in names:
        if path.is_file():
            return ImageFont.truetype(str(path), size)
    return ImageFont.load_default(size=size)


def _clean(text):
    return ' '.join(str(text).split())


def _ellipsis(draw, text, font, width):
    text = _clean(text)
    if draw.textlength(text, font=font) <= width:
        return text
    while text and draw.textlength(text + '…', font=font) > width:
        text = text[:-1]
    return text.rstrip() + '…'


def _background():
    canvas = Image.new('RGB', (WIDTH, HEIGHT))
    draw = ImageDraw.Draw(canvas)
    for y in range(HEIGHT):
        t = y / (HEIGHT - 1)
        draw.line((0, y, WIDTH, y), fill=(round(17-9*t), round(29-12*t), round(47-17*t)))
    # Broad, restrained light falls behind the stage instead of competing with it.
    glow = Image.new('RGBA', canvas.size)
    g = ImageDraw.Draw(glow)
    g.ellipse((-300, -500, 1450, 510), fill=(34, 95, 122, 40))
    g.ellipse((1320, 570, 2310, 1570), fill=(34, 96, 87, 20))
    return Image.alpha_composite(canvas.convert('RGBA'), glow.filter(ImageFilter.GaussianBlur(145)))


def _save(canvas, output_path):
    path = Path(output_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    canvas.convert('RGB').save(path, format='PNG', optimize=True)
    return path


def compose_slide(source_path, output_path, lesson_title, slide_title, number, total):
    """Frame the entire source slide, leaving y=945..1033 free for captions.

    The source is fitted without cropping, stretching, or content generation.
    The bottom line indicates chapter position, not elapsed playback time.
    """
    if total < 1 or not 1 <= number <= total:
        raise ValueError('Chapter number must be within the lesson range.')
    canvas = _background()
    draw = ImageDraw.Draw(canvas)
    draw.rounded_rectangle((64, 29, 69, 49), radius=2, fill=ACCENT)
    draw.text((83, 24), _ellipsis(draw, lesson_title, _font(22), 1420), font=_font(22), fill=MUTED)
    draw.text((64, 60), _ellipsis(draw, slide_title, _font(39, True), 1560), font=_font(39, True), fill=INK)
    chapter = f'{number:02d} / {total:02d}'
    label_font = _font(24)
    label_width = draw.textlength(chapter, font=label_font)
    draw.rounded_rectangle((1700, 52, 1856, 102), radius=25, fill='#182B3D', outline='#314354', width=1)
    draw.text((1778-label_width/2, 60), chapter, font=label_font, fill='#C9D8E6')

    shadow = Image.new('RGBA', canvas.size)
    ImageDraw.Draw(shadow).rounded_rectangle((62, 148, 1858, 944), radius=19, fill=(0, 0, 0, 145))
    canvas = Image.alpha_composite(canvas, shadow.filter(ImageFilter.GaussianBlur(22)))
    draw = ImageDraw.Draw(canvas)
    draw.rounded_rectangle((63, 135, 1857, 929), radius=14, fill='#0B1522', outline='#354556', width=1)
    with Image.open(source_path) as original:
        source = ImageOps.exif_transpose(original).convert('RGBA')
        fitted = ImageOps.contain(source, (STAGE[2]-STAGE[0], STAGE[3]-STAGE[1]), Image.Resampling.LANCZOS)
        x = STAGE[0] + (STAGE[2]-STAGE[0]-fitted.width)//2
        y = STAGE[1] + (STAGE[3]-STAGE[1]-fitted.height)//2
        # A white matte keeps transparent exported medical illustrations readable.
        matte = Image.new('RGBA', fitted.size, 'white')
        matte.alpha_composite(fitted)
        canvas.alpha_composite(matte, (x, y))
    draw = ImageDraw.Draw(canvas)
    draw.rounded_rectangle((64, 1052, 1856, 1055), radius=1, fill='#263646')
    draw.rounded_rectangle((64, 1052, 64+round(1792*number/total), 1055), radius=1, fill=ACCENT)
    return _save(canvas, output_path)


def _wrap(draw, text, font, width):
    lines, line = [], ''
    for word in _clean(text).split():
        candidate = f'{line} {word}'.strip()
        if line and draw.textlength(candidate, font=font) > width:
            lines.append(line)
            line = word
        else:
            line = candidate
    if line:
        lines.append(line)
    return lines


def compose_title(output_path, title, subtitle, chapter_number=None):
    """Create a chapter/lesson card using only the supplied editorial text."""
    canvas = _background()
    draw = ImageDraw.Draw(canvas)
    draw.rounded_rectangle((120, 240, 208, 247), radius=3, fill=ACCENT)
    if chapter_number is not None:
        draw.text((120, 279), f'CHAPTER {chapter_number:02d}', font=_font(26, True), fill=ACCENT)
    size = 92
    while True:
        font = _font(size, True)
        lines = _wrap(draw, title, font, 1640)
        if (len(lines) <= 3 and all(draw.textlength(line,font=font) <= 1640 for line in lines)) or size <= 40:
            break
        size -= 4
    y = 354
    for line in lines[:3]:
        draw.text((116, y), _ellipsis(draw,line,font,1640), font=font, fill=INK)
        y += round(size*1.23)
    subtitle_font = _font(32)
    for line in _wrap(draw, subtitle, subtitle_font, 1520)[:2]:
        draw.text((120, y+35), _ellipsis(draw,line,subtitle_font,1520), font=subtitle_font, fill=MUTED)
        y += 45
    draw.line((120, 934, 1800, 934), fill='#304353', width=1)
    return _save(canvas, output_path)
