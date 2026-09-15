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
