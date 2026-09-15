import pytest

from backend.visual_cues import escape_label, map_point, write_visual_cues


def test_mapping_uses_fitted_source_and_clamps():
    assert map_point(.5,.5,(1600,900))==(960,532)
    assert map_point(0,0,(1200,900))==(432,136)
    assert map_point(1,1,(1200,900))==(1487,927)
    assert map_point(-3,8,(1200,900))==(432,927)
    with pytest.raises(ValueError,match='finite'):
        map_point(float('nan'),0,(1200,900))


def test_label_escapes_ass_injection():
    label=escape_label(r'Inspect {\pos(0,0)} here\Nnext')
    assert '{' not in label and '}' not in label and '\\' not in label
    assert 'Inspect' in label and 'here' in label


def test_visual_cues_have_sequential_intervals_and_unique_styles(tmp_path):
    output=write_visual_cues([
        {'label':'First authored landmark','x':.2,'y':.3},
        {'label':'Second authored landmark','x':.8,'y':.7},
    ],8,(1600,900),tmp_path/'cues.ass')
    text=output.read_text(encoding='utf-8')
    events=[line for line in text.splitlines() if line.startswith('Dialogue:')]
    assert len(events)==6
    assert all(',0:00:00.00,0:00:04.00,' in line for line in events[:3])
    assert all(',0:00:04.00,0:00:08.00,' in line for line in events[3:])
    assert 'Style: Default' not in text
    assert '\\t(' in text and '\\fad(' in text
    assert 'First authored landmark' in text


def test_visual_cues_limits_and_empty_export(tmp_path):
    cue={'label':'Label','x':0,'y':0}
    with pytest.raises(ValueError,match='six'):
        write_visual_cues([cue]*7,20,(1600,900),tmp_path/'invalid.ass')
    output=write_visual_cues([],5,(1600,900),tmp_path/'empty.ass')
    assert 'Dialogue:' not in output.read_text(encoding='utf-8')
