import pytest
import threading
from PIL import Image

from backend.scene_timing import paragraphs,paragraph_cue_starts,scene_spans


def blocks():
    return [{'text':'First thought.','start':0.,'end':2.},
            {'text':'Second thought.','start':2.2,'end':3.8},
            {'text':'More detail.','start':3.9,'end':5.},
            {'text':'Final thought.','start':5.2,'end':8.}]


TEXT='First thought.\n\nSecond thought. More detail.\n\nFinal thought.'


def test_paragraphs_preserve_single_lines_and_allow_whitespace_blank_lines():
    assert paragraphs(' One\r\nline.\r\n \r\nTwo.\n\n')==['One\nline.','Two.']


def test_measured_paragraph_start_includes_lead_and_multiple_blocks():
    starts=paragraph_cue_starts(TEXT,[{'paragraph':1},{'paragraph':2}],blocks(),9.)
    assert starts==pytest.approx([3.1,6.1])
    opening,slots,tail=scene_spans(9.,2,starts)
    assert opening==pytest.approx(3.1)
    assert sum([opening,*slots,tail])==pytest.approx(9.)
    assert 0<tail<9.-starts[-1]


def test_no_references_preserve_legacy_timing_without_block_matching():
    assert paragraph_cue_starts(TEXT,[{}],[],9.) is None
    assert scene_spans(10.,2,lead=.9,tail=1.)==(.9,[4.05,4.05],1.)


def test_unassigned_cues_keep_uniform_default_when_order_valid():
    starts=paragraph_cue_starts(TEXT,[{}, {'paragraph':2}],blocks(),9.)
    assert starts==pytest.approx([.9,6.1])


@pytest.mark.parametrize('cues',[[{'paragraph':3}], [{'paragraph':-1}], [{'paragraph':True}],
                              [{'paragraph':2},{'paragraph':1}], [{'paragraph':1},{'paragraph':1}],
                              [{'paragraph':2},{}]])
def test_invalid_missing_or_nonmonotonic_mixed_references_rejected(cues):
    with pytest.raises(ValueError,match='paragraph|Region'):
        paragraph_cue_starts(TEXT,cues,blocks(),9.)


def test_changed_text_and_combined_paragraph_blocks_rejected():
    with pytest.raises(ValueError,match='does not match'):
        paragraph_cue_starts(TEXT+' Changed.',[{'paragraph':0}],blocks(),9.)
    with pytest.raises(ValueError,match='combined paragraph'):
        paragraph_cue_starts(TEXT,[{'paragraph':1}],[{'text':TEXT,'start':0,'end':8}],9.)


@pytest.mark.parametrize('starts',[[1,1],[-1,2],[1,9],[1,float('nan')],[1]])
def test_invalid_direct_renderer_timings_rejected(starts):
    with pytest.raises(ValueError,match='start times'):
        scene_spans(9.,2,starts)


@pytest.mark.parametrize('kind',['focus','whiteboard'])
def test_renderers_hold_full_source_before_linked_cue_and_preserve_endpoint(tmp_path,monkeypatch,kind):
    from backend import focus_motion,whiteboard
    seen=[]
    canvas=Image.new('RGB',(8,8),'white')
    monkeypatch.setattr(whiteboard,'prepare',lambda *a:(canvas,canvas,None,[(0,0,4,4)]))
    def paint(*args,**kwargs):
        seen.append(kwargs)
        return canvas
    if kind=='focus':
        monkeypatch.setattr(focus_motion,'paint',paint)
        renderer=focus_motion.render_focus
    else:
        monkeypatch.setattr(whiteboard,'paint',paint)
        renderer=whiteboard.render_whiteboard
    renderer(tmp_path/'source.png',tmp_path/'video.mp4','Lesson','Slide',1,1,[{'label':'Detail'}],
             10.,'ffmpeg',threading.Event(),lambda *a,**k:None,cue_starts=[4.])
    listing=next(tmp_path.glob('*/frames.txt')).read_text()
    durations=[float(line.split()[1]) for line in listing.splitlines() if line.startswith('duration ')]
    assert durations[0]==pytest.approx(4.)
    assert sum(durations)==pytest.approx(10.,abs=1e-7)
    assert seen[-1]['overview'] is True
    if kind=='whiteboard': assert seen[0]['overview'] is True
