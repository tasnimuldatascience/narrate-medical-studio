import json
import shutil
import subprocess
import zipfile

import pytest

from backend.lesson import package


def make_package(folder, **kwargs):
    for name in ('presentation.mp4','captions.srt','transcript.txt'):
        (folder/name).write_bytes(b'test')
    package(folder,'Caption test',[{'number':1,'title':'Chapter','start':0,'end':1}],
        [{'start':0,'end':1,'text':'Review <source> & verify.'}],**kwargs)
    html=(folder/'index.html').read_text(encoding='utf-8')
    payload=json.JSONDecoder().raw_decode(html.split('const lesson=',1)[1])[0]
    return html,payload


@pytest.mark.parametrize('burned',[False,True])
def test_package_records_caption_mode_and_retains_portable_captions(tmp_path,burned):
    html,payload=make_package(tmp_path,burn_captions=burned)
    assert payload['burnedCaptions'] is burned
    assert payload['cues'][0]['text']=='Review <source> & verify.'
    assert '<source>' not in html
    with zipfile.ZipFile(tmp_path/'interactive-lesson.zip') as bundle:
        assert {'captions.vtt','captions.srt','index.html','presentation.mp4'}<=set(bundle.namelist())
        assert '00:00:00.000 --> 00:00:01.000' in bundle.read('captions.vtt').decode()
        note=bundle.read('README.txt').decode()
        assert ('Additional player captions start off' if burned else 'Captions start on') in note


def test_package_backwards_compatible_default_shows_native_captions(tmp_path):
    _,payload=make_package(tmp_path)
    assert payload['burnedCaptions'] is False


def test_reading_transcript_preserves_complete_thoughts_separately_from_subtitles(tmp_path):
    passage={'start':0,'end':1,'text':'Read the complete thought. Then revisit the source.','chapter':1}
    _,payload=make_package(tmp_path,transcript=[passage])
    assert payload['transcript']==[passage]
    assert payload['cues'][0]['text']=='Review <source> & verify.'


@pytest.mark.skipif(not shutil.which('node'),reason='Node is required to execute player JavaScript')
@pytest.mark.parametrize('burned',[False,True])
def test_player_caption_initialization_avoids_duplicate_tracks(tmp_path,burned):
    html,payload=make_package(tmp_path,burn_captions=burned)
    # Execute the actual embedded caption initializer against a minimal media
    # interface, including an MP4 subtitle track discovered with metadata.
    initializer=html.split('// Construct cues from embedded data:',1)[1].split('function setChapter(',1)[0]
    initializer='// Construct cues from embedded data:'+initializer
    script='''
const assert=require('node:assert/strict');
const existing={mode:'showing'};
const video={
  textTracks:[existing],
  addTextTrack(){const track={cues:[],addCue(cue){this.cues.push(cue);}};this.textTracks.push(track);return track;},
  addEventListener(name,callback){assert.equal(name,'loadedmetadata');this.onMetadata=callback;}
};
class VTTCue{constructor(start,end,text){Object.assign(this,{start,end,text});}}
'''+'const lesson='+json.dumps(payload)+';\n'+initializer+'''
const added=video.textTracks[1];
assert.equal(existing.mode,'disabled');
assert.equal(added.mode,lesson.burnedCaptions?'disabled':'showing');
assert.equal(added.cues.length,1);
assert.equal(added.cues[0].text,'Review &lt;source&gt; &amp; verify.');
const discovered={mode:'showing'};video.textTracks.push(discovered);
video.onMetadata();
assert.equal(discovered.mode,'disabled');
assert.equal(added.mode,lesson.burnedCaptions?'disabled':'showing');
// A viewer can still enable the available native track after initialization.
added.mode='showing';assert.equal(added.cues.length,1);
'''
    subprocess.run([shutil.which('node')],input=script.encode('utf-8'),check=True,capture_output=True)


def test_reading_transcript_escapes_markup_without_affecting_captions(tmp_path):
    passage={'start':0,'end':1,'text':'</script><script>unexpected()</script> & source','chapter':1}
    html,payload=make_package(tmp_path,transcript=[passage])
    assert payload['transcript']==[passage]
    assert '</script><script>unexpected()' not in html
    assert payload['cues'][0]['text']=='Review <source> & verify.'
    assert 'unexpected()' not in (tmp_path/'captions.vtt').read_text(encoding='utf-8')


def test_export_keeps_complete_reading_passages_and_correct_chapter_offsets(tmp_path,monkeypatch):
    import threading
    import wave
    from PIL import Image
    from backend import media,whiteboard

    source=tmp_path/'slides'
    source.mkdir()
    for number in (3,4):
        Image.new('RGB',(160,90),'white').save(source/f'slide-{number}.png')
    output=tmp_path/'export'
    output.mkdir()
    long_thought=('Notice the supplied pattern and explain the relationship in your own words. '
                  'Then compare your explanation with the source before continuing.')
    blocks=[{'start':0.,'end':1.2,'text':long_thought},
            {'start':1.38,'end':2.,'text':'This is the final thought.'}]
    def synthesize(text,path,*args,**kwargs):
        with wave.open(str(path),'wb') as audio:
            audio.setparams((1,2,1000,0,'NONE','not compressed'))
            audio.writeframes(b'\0'*4000)
        return [dict(block) for block in blocks],2.
    def run(args,cancel,cwd=None,**kwargs):
        if args[-1]=='presentation.mp4':
            (cwd/'presentation.mp4').write_bytes(b'synthetic video')
        return ''
    monkeypatch.setattr(media,'synthesize',synthesize)
    monkeypatch.setattr(media.shutil,'which',lambda name:name)
    monkeypatch.setattr(media,'run',run)
    monkeypatch.setattr(media,'audit_video',lambda *args:{'verified':True})
    monkeypatch.setattr(whiteboard,'render_whiteboard',lambda *args,**kwargs:None)
    slides=[{'number':number,'approved':True,'title':f'Chapter {number}',
             'narration':long_thought+' This is the final thought.','sources':[]} for number in (3,4)]
    media.export({'name':'Synthetic lesson','slides':slides},output,
        {'start':3,'end':4,'engine':'kokoro','voice':'af_heart','rate':1.,
         'burn_captions':True,'visual_style':'whiteboard'},threading.Event(),lambda *args:None)
    html=(output/'index.html').read_text(encoding='utf-8')
    lesson=json.JSONDecoder().raw_decode(html.split('const lesson=',1)[1])[0]
    passages=lesson['transcript']
    assert len(passages)==4 and len(lesson['cues'])>4
    assert [passage['chapter'] for passage in passages]==[3,3,4,4]
    assert passages[0]['text']==long_thought
    assert passages[0]['start']==pytest.approx(.9)
    assert passages[1]['start']-passages[0]['end']==pytest.approx(.18)
    assert passages[2]['start']==pytest.approx(lesson['chapters'][1]['start']+.9)
    for chapter in lesson['chapters']:
        reading=[passage for passage in passages if passage['chapter']==chapter['number']]
        subtitles=[cue for cue in lesson['cues'] if chapter['start']<=cue['start']<chapter['end']]
        assert subtitles[0]['start']==pytest.approx(reading[0]['start'])
        assert subtitles[-1]['end']==pytest.approx(reading[-1]['end'])
    assert blocks[0]['start']==0 and blocks[1]['end']==2
