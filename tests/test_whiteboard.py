import math
import shutil
import threading
import json

from PIL import Image, ImageChops, ImageOps
import pytest

from backend.whiteboard import prepare, paint, region_bounds, source_bounds, STAGE


@pytest.mark.parametrize('label', ['A reviewed medical label with every source word retained in the rendered lesson, including the final clarification.', 'W'*120])
def test_reviewed_labels_are_never_silently_truncated(label):
    from PIL import ImageDraw
    from backend.whiteboard import label_lines
    draw = ImageDraw.Draw(Image.new('RGB', (1920,1080)))
    font, height, lines = label_lines(draw,label)
    assert ''.join(lines).replace(' ','') == label.replace(' ','')
    assert height*len(lines) <= 94
    assert all(draw.textlength(line,font=font)<=280 for line in lines)


@pytest.mark.parametrize('size', [(1600, 900), (1200, 900), (600, 1000)])
def test_whiteboard_reveals_only_reviewed_regions_then_whole_source(tmp_path, size):
    path = tmp_path/'source.png'
    Image.new('RGB', size, '#EF6040').save(path)
    cues = [{'label': 'Source region', 'x': .25, 'y': .5, 'width': .2, 'height': .3}]
    base, source, bounds, regions = prepare(path, 'Lesson', 'Chapter', 1, 1, cues)
    first = paint(base, source, cues, regions, 1)
    left, top, right, bottom = regions[0]
    assert first.getpixel(((left+right)//2, (top+bottom)//2)) == (239, 96, 64)
    unreviewed = (bounds[2]-20, (bounds[1]+bounds[3])//2)
    assert first.getpixel(unreviewed) == (255, 255, 255)
    full = paint(base, source, cues, regions, 1, overview=True)
    assert full.getpixel(unreviewed) == (239, 96, 64)
    assert full.size == (1920, 1080)


def test_regions_clip_to_source_and_reject_invalid_coordinates():
    bounds = (100, 200, 1100, 700)
    assert region_bounds({'x': 0, 'y': 0, 'width': .4, 'height': .4}, bounds) == (100, 200, 300, 300)
    for value in (float('nan'), -1, 2):
        with pytest.raises(ValueError):
            region_bounds({'x': value, 'y': .5}, bounds)


def test_partial_reveal_hides_remaining_source(tmp_path):
    path = tmp_path/'source.png'
    Image.new('RGB', (800, 600), 'red').save(path)
    cues = [{'label': 'A source region', 'x': .5, 'y': .5, 'width': .5, 'height': .5}]
    base, source, _, regions = prepare(path, 'Lesson', 'Chapter', 1, 1, cues)
    frame = paint(base, source, cues, regions, 0, 0, .5)
    left, top, right, bottom = regions[0]
    assert frame.getpixel((left+10, top+10)) == (255, 0, 0)
    assert frame.getpixel((right-10, top+10)) == (255, 255, 255)


def test_overview_preserves_entire_fitted_source_with_transparency(tmp_path):
    source_image=Image.new('RGBA',(256,128),(32,80,170,100))
    source_image.paste((250,10,20,255),(30,20,80,70))
    path=tmp_path/'transparent.png'
    source_image.save(path)
    cue={'label':'Reviewed detail','x':.25,'y':.5,'width':.2,'height':.3}
    base,source,bounds,regions=prepare(path,'Lesson','Chapter',1,1,[cue])
    overview=paint(base,source,[cue],regions,1,overview=True)
    fitted=ImageOps.contain(source_image,(STAGE[2]-STAGE[0],STAGE[3]-STAGE[1]),Image.Resampling.LANCZOS)
    expected=Image.new('RGBA',fitted.size,'white')
    expected.alpha_composite(fitted)
    assert ImageChops.difference(overview.crop(bounds),expected.convert('RGB')).getbbox() is None


@pytest.mark.parametrize('cue_count',[0,1,6])
def test_whiteboard_sequence_has_exact_duration_and_safe_relative_frames(tmp_path,cue_count):
    from backend.whiteboard import render_whiteboard
    path=tmp_path/'source.png'
    Image.new('RGB',(400,300),'red').save(path)
    cues=[{'label':f'Region {i}','x':.5,'y':.5} for i in range(cue_count)]
    calls=[]
    duration=7.125
    render_whiteboard(path,tmp_path/'output.mp4','Lesson','Chapter',1,1,cues,duration,
        'ffmpeg',threading.Event(),lambda *args,**kwargs:calls.append((args,kwargs)),captions='part-1/captions.ass')
    lines=(tmp_path/'board-1'/'frames.txt').read_text().splitlines()
    durations=[float(line.split()[1]) for line in lines if line.startswith('duration ')]
    assert all(value>0 for value in durations)
    assert math.isclose(sum(durations),duration,abs_tol=1e-7)
    files=[line[6:-1] for line in lines if line.startswith("file '")]
    assert files[-1]==files[-2]
    assert len(files)==len(durations)+1
    assert all((tmp_path/'board-1'/name).is_file() for name in files)
    args,kwargs=calls[0]
    assert kwargs['cwd']==tmp_path
    command=args[0]
    assert command[command.index('-i')+1]=='board-1/frames.txt'
    assert command[command.index('-vf')+1]=='fps=24,ass=part-1/captions.ass'
    assert float(command[command.index('-t')+1])==duration


def test_cancelled_whiteboard_does_not_write_frames_or_start_encoder(tmp_path):
    from backend.whiteboard import render_whiteboard
    from backend.media import Cancelled
    path=tmp_path/'source.png'
    Image.new('RGB',(20,20),'white').save(path)
    cancel=threading.Event()
    cancel.set()
    with pytest.raises(Cancelled):
        render_whiteboard(path,tmp_path/'output.mp4','Lesson','Chapter',1,1,[],2,
            'ffmpeg',cancel,lambda *args,**kwargs:pytest.fail('Cancelled encoder started'))
    assert not list(tmp_path.glob('board-*/*.png'))


@pytest.mark.parametrize('duration',[0,-1,float('nan'),float('inf')])
def test_whiteboard_invalid_duration_rejected_before_source_access(tmp_path,duration):
    from backend.whiteboard import render_whiteboard
    with pytest.raises(ValueError,match='duration'):
        render_whiteboard(tmp_path/'missing.png',tmp_path/'output.mp4','Lesson','Chapter',1,1,[],duration,
            'ffmpeg',threading.Event(),lambda *args,**kwargs:pytest.fail('Invalid duration reached encoder'))


@pytest.mark.skipif(not shutil.which('ffmpeg') or not shutil.which('ffprobe'),reason='Local FFmpeg tools required')
def test_whiteboard_real_concat_frame_timing(tmp_path):
    from backend.whiteboard import render_whiteboard
    from backend.media import run
    path=tmp_path/'source.png'
    Image.new('RGB',(160,90),'#347ABC').save(path)
    output=tmp_path/'output.mp4'
    duration=1.125
    render_whiteboard(path,output,'Lesson','Chapter',1,1,
        [{'label':'Source detail','x':.5,'y':.5}],duration,
        shutil.which('ffmpeg'),threading.Event(),run)
    metadata=json.loads(run([shutil.which('ffprobe'),'-v','error','-show_entries',
        'stream=width,height,nb_frames,duration,avg_frame_rate','-of','json',str(output)],threading.Event()))
    video=metadata['streams'][0]
    assert (video['width'],video['height'])==(1920,1080)
    assert video['avg_frame_rate']=='24/1'
    assert int(video['nb_frames'])==27
    assert abs(float(video['duration'])-duration)<.001
