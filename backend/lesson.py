"""Portable learning package with no CDN, server, account, or internet requirement."""
import json
import zipfile
from pathlib import Path
from html import escape


def _timestamp(seconds):
    milliseconds = max(0, round(seconds * 1000))
    hours, milliseconds = divmod(milliseconds, 3600000)
    minutes, milliseconds = divmod(milliseconds, 60000)
    seconds, milliseconds = divmod(milliseconds, 1000)
    return f'{hours:02}:{minutes:02}:{seconds:02}.{milliseconds:03}'

def package(folder,title,chapters,cues,burn_captions=False):
    folder = Path(folder)
    payload=json.dumps({'title':title,'chapters':chapters,'cues':cues,'burnedCaptions':bool(burn_captions)},ensure_ascii=True).replace('<','\\u003c').replace('>','\\u003e').replace('&','\\u0026')
    template=(Path(__file__).parent/'lesson.html').read_text(encoding='utf-8')
    html=template.replace('/*LESSON_DATA*/',payload)
    (folder/'index.html').write_text(html,encoding='utf-8')
    # A sidecar is useful in external players; the HTML also constructs its own
    # text track so captions work when opened directly with file://.
    vtt = 'WEBVTT\n\n' + '\n\n'.join(
        f'{_timestamp(c["start"])} --> {_timestamp(c["end"])}\n{escape(c["text"])}'
        for c in cues
    )
    (folder/'captions.vtt').write_text(vtt + '\n', encoding='utf-8')
    (folder/'README.txt').write_text(
        'Extract this entire ZIP into one folder, then open index.html in a modern browser.\n'
        'Keep presentation.mp4 alongside index.html. No internet connection is required.\n'
        + ('Captions are part of the video image. Additional player captions start off to avoid duplication.\n'
           if burn_captions else 'Captions start on and can be changed using the player controls.\n')
        + 'Search the transcript to revisit a passage.\n'
        'Knowledge checks and reflection notes are held only for the current page session.\n'
        'The transcript and captions can also be opened independently.\n', encoding='utf-8')
    with zipfile.ZipFile(folder/'interactive-lesson.zip','w',zipfile.ZIP_STORED) as z:
        for name in ['index.html','presentation.mp4','captions.srt','captions.vtt','transcript.txt','README.txt']:
            z.write(folder/name,name)
