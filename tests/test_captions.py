from copy import deepcopy

from backend import media
from backend.compositor import _font


def test_long_natural_blocks_split_without_changing_content_or_measured_gaps():
    text=('Review the provided source carefully before proceeding. '
          'Notice the relationship between the labels and the highlighted area. '
          'Pause to compare the explanation with the original slide, then continue when ready.')
    blocks=[{'start':0.,'end':12.,'text':text},
            {'start':12.18,'end':14.,'text':'Continue to the next chapter.'}]
    original=deepcopy(blocks)
    cues=media.split_caption_cues(blocks)
    assert blocks==original
    assert len(cues)>len(blocks)
    first=[cue for cue in cues if cue['start']<12]
    assert first[0]['start']==0 and first[-1]['end']==12
    assert all(left['end']==right['start'] for left,right in zip(first,first[1:]))
    assert cues[-1]['start']==12.18
    assert ' '.join(cue['text'].replace('\n',' ') for cue in first)==text
    assert all(cue['timing']=='estimated-proportional' for cue in first)
    assert all(cue['end']>cue['start'] for cue in cues)


def test_caption_font_width_and_two_line_limit_even_for_long_tokens():
    cues=media.split_caption_cues([{'start':0,'end':30,'text':'W'*280}])
    assert ''.join(cue['text'].replace('\n','') for cue in cues)=='W'*280
    for cue in cues:
        lines=cue['text'].splitlines()
        assert len(lines)<=2
        assert all(_font(34).getlength(line)<=1560 for line in lines)


def test_caption_files_preserve_linebreaks_and_escape_control_sequences(tmp_path):
    media.write_captions([{'start':0,'end':3,'text':'First line\nSecond {\\pos(0,0)} line'}],tmp_path)
    srt=(tmp_path/'captions.srt').read_text(encoding='utf-8')
    ass=(tmp_path/'captions.ass').read_text(encoding='utf-8')
    assert 'First line\nSecond' in srt
    assert r'First line\NSecond' in ass
    assert r'{\pos(' not in ass
    assert 'WrapStyle: 2' in ass
    assert '120,120,62,1' in ass
    assert 'estimated within measured speech blocks' in ass
