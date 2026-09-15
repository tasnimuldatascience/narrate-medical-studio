from PIL import Image
import json
import wave
import pytest

from scripts.render_draft_preview import banner,cached_paragraphs


def test_draft_banner_covers_header_on_every_frame_without_changing_source():
    source=Image.new('RGB',(1920,1080),'white')
    first=banner(source)
    repeated=banner(first)
    assert source.getpixel((0,0))==(255,255,255)
    assert first.getpixel((0,60))==(128,48,45)
    assert first.getpixel((0,80))==(255,255,255)
    assert first.tobytes()==repeated.tobytes()
    assert first.crop((72,18,1300,68)).getextrema()[0]!=(128,128)


def test_audio_reuse_requires_same_script_and_voice(tmp_path):
    path=tmp_path/'cached.wav'
    with wave.open(str(path),'wb') as wav:
        wav.setnchannels(1);wav.setsampwidth(2);wav.setframerate(24000)
        wav.writeframes(b'\0'*96000)
    report={'voice':'Aiden','style':'engaging','requested_rate':1,
        'cues':[{'text':'First idea.','start':0,'end':1},{'text':'Second idea.','start':1,'end':2}]}
    path.with_suffix('.qwen.json').write_text(json.dumps(report),encoding='utf-8')
    groups=cached_paragraphs(path,['First idea.','Second idea.'],'Aiden','engaging',1)
    assert len(groups)==2 and groups[1][-1]==1
    assert groups[1][2][0]['start']==0
    with pytest.raises(ValueError,match='does not match'):
        cached_paragraphs(path,['Changed meaning.'],'Aiden','engaging',1)
    with pytest.raises(ValueError,match='does not match'):
        cached_paragraphs(path,['First idea.','Second idea.'],'Ryan','engaging',1)
