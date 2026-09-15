import os
import json
import re
import shutil
import subprocess
import sys
import time
import wave
from pathlib import Path
from . import store

class Cancelled(Exception):
    pass

def check(cancel):
    if cancel.is_set():
        raise Cancelled('Job cancelled. Your reviewed scripts are preserved.')

def run(args, cancel, cwd=None, timeout=600):
    check(cancel)
    # File-backed logs avoid pipe deadlocks during long FFmpeg jobs.
    import tempfile
    with tempfile.TemporaryFile() as log:
        p = subprocess.Popen(args, cwd=cwd, stdin=subprocess.DEVNULL, stdout=log, stderr=log,
            creationflags=subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0)
        start = time.monotonic()
        try:
            while p.poll() is None:
                check(cancel)
                if time.monotonic() - start > timeout:
                    raise RuntimeError('The local processing step timed out. Check the runtime and retry.')
                time.sleep(.2)
            if p.returncode:
                log.seek(0, 2)
                log.seek(max(0, log.tell() - 3000))
                raise RuntimeError(log.read().decode(errors='replace'))
            check(cancel)
            log.seek(0)
            return log.read(1024 * 1024).decode(errors='replace')
        finally:
            if p.poll() is None:
                p.kill()
                p.wait()

def render(folder, cancel):
    target = folder / 'slides'
    target.mkdir(exist_ok=True)
    if os.name == 'nt':
        run([sys.executable, '-m', 'backend.render_worker', str(folder/'safe.pptx'), str(target)], cancel, cwd=store.ROOT)
    else:
        # Set an explicit executable on systems where LibreOffice is provided.
        binary = os.environ.get('NARRATE_SOFFICE') or shutil.which('soffice')
        if not binary:
            raise RuntimeError('Slide rendering needs LibreOffice. Set NARRATE_SOFFICE to its executable.')
        run([binary, '--headless', f'-env:UserInstallation={(folder/"lo-profile").as_uri()}', '--convert-to', 'pdf', '--outdir', str(target), str(folder/'safe.pptx')], cancel)
        import pymupdf
        with pymupdf.open(target/'safe.pdf') as pdf:
            for i, page in enumerate(pdf, 1):
                check(cancel)
                page.get_pixmap(matrix=pymupdf.Matrix(1920/page.rect.width,1920/page.rect.width)).save(target/f'slide-{i}.png')

def voice_path():
    return Path(os.environ.get('NARRATE_VOICE', store.ROOT/'models'/'en_US-lessac-medium.onnx'))

def caption_chunks(text):
    # Display chunks only: never use subtitle length to split voice synthesis.
    chunks, current = [], ''
    for word in text.split():
        if current and len(current) + len(word) + 1 > 78:
            chunks.append(current)
            current = ''
        current = (current + ' ' + word).strip()
        if re.search(r'[.!?;:]$', word) and len(current) > 24:
            chunks.append(current)
            current = ''
    if current:
        chunks.append(current)
    return chunks


def caption_lines(text):
    """Wrap within the lower stage width using the same font as libass."""
    from .compositor import _font
    font = _font(34)
    lines, current = [], ''
    for word in text.split():
        candidate = (current+' '+word).strip()
        if font.getlength(candidate) <= 1560:
            current = candidate
            continue
        if current:
            lines.append(current)
            current = ''
        while font.getlength(word) > 1560:
            count = 1
            while count < len(word) and font.getlength(word[:count+1]) <= 1560:
                count += 1
            lines.append(word[:count])
            word = word[count:]
        current = word
    if current:
        lines.append(current)
    return lines


def split_caption_cues(blocks):
    """Estimate readable caption timing inside measured natural speech blocks.

    Audio is unchanged. Character-proportional boundaries are display estimates,
    not forced alignment or measured word timestamps. Original block gaps and
    endpoints are preserved, so estimates cannot drift into the next block.
    """
    result = []
    for block in blocks:
        if block['end'] <= block['start']:
            raise ValueError('A narration block must have positive duration.')
        parts = []
        for chunk in caption_chunks(block['text']):
            lines = caption_lines(chunk)
            parts.extend('\n'.join(lines[i:i+2]) for i in range(0,len(lines),2))
        if not parts:
            continue
        weights = [len(re.sub(r'\s','',part)) for part in parts]
        total = sum(weights)
        cumulative = 0
        start = block['start']
        for index,(part,weight) in enumerate(zip(parts,weights)):
            cumulative += weight
            end = block['end'] if index == len(parts)-1 else (
                block['start']+(block['end']-block['start'])*cumulative/total)
            result.append({**block,'start':start,'end':end,'text':part,
                'timing':'estimated-proportional' if len(parts)>1 else 'measured-block'})
            start = end
    return result

def synthesize(text, output, engine, rate, cancel, voice='af_heart'):
    if engine == 'kokoro':
        from .voice import synthesize as kokoro_synthesize
        return kokoro_synthesize(text,output,voice,rate,cancel)
    from .speech_text import natural_blocks
    chunks = natural_blocks(text)
    if not chunks:
        raise ValueError('Narration is empty.')
    piper = speaker = pythoncom = None
    if engine == 'piper':
        from piper import PiperVoice, SynthesisConfig
        if not voice_path().is_file():
            raise ValueError('Piper voice is not installed. Install it in Setup or select Windows voice.')
        piper = PiperVoice.load(str(voice_path()))
        config = SynthesisConfig(length_scale=1/rate)
    elif engine == 'windows' and os.name == 'nt':
        import pythoncom
        import win32com.client
        pythoncom.CoInitialize()
        speaker = win32com.client.Dispatch('SAPI.SpVoice')
        speaker.Rate = max(-10, min(10, round((rate-1)*8)))
    else:
        raise ValueError('This voice engine is unavailable on this system.')
    cues, cursor, params, frames = [], 0., None, []
    try:
        for i, chunk in enumerate(chunks):
            check(cancel)
            part = output.with_name(f'{output.stem}-phrase-{i}.wav')
            if piper:
                with wave.open(str(part), 'wb') as wav:
                    piper.synthesize_wav(chunk, wav, syn_config=config)
            else:
                stream = win32com.client.Dispatch('SAPI.SpFileStream')
                stream.Format.Type = 22  # 22 kHz, 16-bit, mono PCM
                stream.Open(str(part), 3)
                try:
                    speaker.AudioOutputStream = stream
                    speaker.Speak(chunk, 0)
                finally:
                    stream.Close()
            with wave.open(str(part), 'rb') as wav:
                params = wav.getparams()
                duration = wav.getnframes()/wav.getframerate()
                frames.append(wav.readframes(wav.getnframes()))
            cues.append({'start':cursor, 'end':cursor+duration, 'text':chunk})
            cursor += duration
            part.unlink()
        with wave.open(str(output), 'wb') as wav:
            wav.setparams(params)
            wav.writeframes(b''.join(frames))
        return cues, cursor
    finally:
        if pythoncom:
            pythoncom.CoUninitialize()

def timestamp(t, ass=False):
    total = round(t * (100 if ass else 1000))
    scale = 100 if ass else 1000
    seconds, frac = divmod(total, scale)
    minutes, seconds = divmod(seconds,60)
    hours, minutes = divmod(minutes,60)
    return f'{hours}:{minutes:02}:{seconds:02}.{frac:02}' if ass else f'{hours:02}:{minutes:02}:{seconds:02},{frac:03}'

def write_captions(cues, folder, light=False):
    srt = '\n\n'.join(f'{i}\n{timestamp(c["start"])} --> {timestamp(c["end"])}\n{c["text"]}' for i,c in enumerate(cues,1))+'\n'
    (folder/'captions.srt').write_text(srt, encoding='utf-8')
    header = '[Script Info]\n; Timing: display boundaries estimated within measured speech blocks.\nScriptType: v4.00+\nPlayResX: 1920\nPlayResY: 1080\nWrapStyle: 2\n\n[V4+ Styles]\nFormat: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding\nStyle: Default,Segoe UI,34,&H00FFFFFF,&H00FFFFFF,&H0014151C,&H0014151C,0,0,0,0,100,100,0,0,1,1,0,2,120,120,62,1\n\n[Events]\nFormat: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text\n'
    if light:
        header=header.replace('&H00FFFFFF,&H00FFFFFF,&H0014151C,&H0014151C',
                              '&H00433D21,&H00433D21,&H00FAFCFB,&H00FAFCFB')
    lines = []
    for c in cues:
        text = c['text'].replace('\\','＼').replace('{','｛').replace('}','｝').replace('\n',r'\N')
        lines.append(f'Dialogue: 0,{timestamp(c["start"],True)},{timestamp(c["end"],True)},Default,,0,0,0,,{text}')
    (folder/'captions.ass').write_text(header+'\n'.join(lines), encoding='utf-8')


def join_audio(parts, output, cancel):
    """Pad PCM at chapter boundaries; encode AAC only once in the final video."""
    audio_format = None
    elapsed = 0.
    written = 0
    with wave.open(str(output), 'wb') as dst:
        for path, duration in parts:
            check(cancel)
            with wave.open(str(path), 'rb') as src:
                current = (src.getnchannels(), src.getsampwidth(), src.getframerate())
                if audio_format is None:
                    audio_format = current
                    dst.setnchannels(current[0])
                    dst.setsampwidth(current[1])
                    dst.setframerate(current[2])
                elif current != audio_format:
                    raise ValueError('Narration audio formats differ between slides.')
                count = src.getnframes()
                elapsed += duration
                target = round(elapsed * current[2]) - written
                if count > target:
                    raise ValueError('Narration is longer than its video chapter.')
                while block := src.readframes(65536):
                    check(cancel)
                    dst.writeframesraw(block)
                # PCM unsigned 8-bit silence is 128; wider PCM silence is zero.
                silence = b'\x80' if current[1] == 1 else b'\x00'
                dst.writeframesraw(silence * ((target-count)*current[0]*current[1]))
                written += target


def audit_video(folder, expected_duration, cancel):
    ffprobe = shutil.which('ffprobe')
    if not ffprobe:
        raise ValueError('FFprobe is required to verify the generated video. Install it with FFmpeg.')
    result = json.loads(run([ffprobe,'-v','error','-show_entries',
        'stream=codec_type,codec_name,width,height,duration:format=duration',
        '-of','json',str(folder/'presentation.mp4')],cancel,timeout=30))
    streams = result.get('streams',[])
    videos = [s for s in streams if s.get('codec_type')=='video']
    audios = [s for s in streams if s.get('codec_type')=='audio']
    if not videos or not audios or not any(s.get('codec_type')=='subtitle' for s in streams):
        raise ValueError('Output verification failed: video, audio, or captions are missing.')
    if videos[0].get('width') != 1920 or videos[0].get('height') != 1080:
        raise ValueError('Output verification failed: video is not 1080p.')
    for stream in [videos[0],audios[0],result.get('format',{})]:
        if abs(float(stream.get('duration',0))-expected_duration) > .15:
            raise ValueError('Output verification failed: audio/video timing differs from the lesson timeline.')
    return {'verified':True,'expected_duration':expected_duration,**result}

def export(project, folder, settings, cancel, progress):
    selected = [s for s in project['slides'] if settings['start'] <= s['number'] <= settings['end']]
    if not selected or any(not s['approved'] for s in selected):
        raise ValueError('Every selected slide requires narration approval before export.')
    ffmpeg = shutil.which('ffmpeg')
    if not ffmpeg:
        raise ValueError('FFmpeg is not installed or is missing from PATH.')
    if not shutil.which('ffprobe'):
        raise ValueError('FFprobe is required to verify the generated video. Install it with FFmpeg.')
    all_cues, elapsed, segments, chapters, audio_parts = [], 0., [], [], []
    for index, slide in enumerate(selected):
        check(cancel)
        n = slide['number']
        visual = folder.parent/'slides'/f'slide-{n}.png'
        if not visual.is_file():
            raise ValueError(f'Slide {n} has no rendered preview. Render slides first.')
        progress(round(index/len(selected)*90),f'Creating voice and video for slide {n}')
        wav = folder/f'slide-{n}.wav'
        cues, duration = synthesize(slide['narration'], wav, settings['engine'],settings['rate'],cancel,settings.get('voice','af_heart'))
        speech_duration = duration
        cues = split_caption_cues(cues)
        # Give the visual a deliberate opening beat before the narration begins.
        lead,tail=.9,.25
        with wave.open(str(wav),'rb') as source_audio:
            parameters=source_audio.getparams()
            raw=source_audio.readframes(source_audio.getnframes())
        silence=lambda seconds:b'\0'*(round(seconds*parameters.framerate)*parameters.sampwidth*parameters.nchannels)
        with wave.open(str(wav),'wb') as target_audio:
            target_audio.setparams(parameters)
            target_audio.writeframes(silence(lead)+raw+silence(tail))
        for cue in cues:
            cue['start']+=lead;cue['end']+=lead
        duration+=lead+tail
        # Align each segment to a frame boundary to prevent cumulative caption drift.
        import math
        duration = math.ceil(duration*24)/24
        local = folder/f'part-{n}'
        local.mkdir(exist_ok=True)
        write_captions(cues,local,light=settings.get('visual_style','whiteboard')=='whiteboard')
        segment = f'segment-{n}.mp4'
        if settings.get('visual_style','whiteboard') == 'whiteboard':
            from .whiteboard import render_whiteboard
            render_whiteboard(visual,folder/segment,project['name'],slide['title'],index+1,
                len(selected),slide.get('visual_cues',[]),duration,ffmpeg,cancel,run,
                captions=f'part-{n}/captions.ass' if settings['burn_captions'] else None)
        else:
            from .compositor import compose_slide,compose_title
            compose_slide(visual,folder/f'scene-{n}.png',project['name'],slide['title'],index+1,len(selected))
            compose_title(folder/f'chapter-{n}.png',slide['title'],project['name'],index+1)
            motion = f"zoompan=z='1+0.006*min(on/{max(1,round(duration*24))},1)':x='iw/2-iw/zoom/2':y='ih/2-ih/zoom/2':d=1:s=1920x1080:fps=24"
            base='[0:v]'
            if slide.get('visual_cues'):
                from .visual_cues import write_visual_cues
                from PIL import Image
                with Image.open(visual) as source_image:
                    source_size=source_image.size
                write_visual_cues(slide['visual_cues'],speech_duration,source_size,folder/f'visual-cues-{n}.ass')
                # Evaluate annotation events on the speech timeline, after the card.
                base+=f'setpts=PTS-{lead}/TB,ass=visual-cues-{n}.ass,setpts=PTS+{lead}/TB,'
            filters=base+motion+'[scene];[1:v]format=rgba,fade=t=out:st=0.5:d=0.35:alpha=1[opening];[scene][opening]overlay=0:0:enable=\'lt(t,0.85)\''
            if settings['burn_captions']:
                filters+=f',ass=part-{n}/captions.ass'
            filters+=f',fade=t=out:st={max(0,duration-.2)}:d=0.2[out]'
            run([ffmpeg,'-y','-v','error','-loop','1','-framerate','24','-i',f'scene-{n}.png','-loop','1','-framerate','24','-i',f'chapter-{n}.png','-filter_complex',filters,'-map','[out]','-t',str(duration),'-c:v','libx264','-preset','fast','-crf','18','-pix_fmt','yuv420p','-an',segment],cancel,cwd=folder)
        segments.append(segment)
        audio_parts.append((wav,duration))
        chapters.append({'number':n,'title':slide['title'],'start':elapsed,'end':elapsed+duration,'knowledge':slide.get('knowledge'),'sources':slide['sources']})
        all_cues.extend({**c,'start':c['start']+elapsed,'end':c['end']+elapsed} for c in cues)
        elapsed += duration
    write_captions(all_cues,folder)
    (folder/'concat.txt').write_text('\n'.join(f"file '{s}'" for s in segments),encoding='utf-8')
    progress(94,'Assembling 1080p video and captions')
    join_audio(audio_parts,folder/'narration.wav',cancel)
    run([ffmpeg,'-y','-v','error','-f','concat','-safe','0','-i','concat.txt','-i','narration.wav','-i','captions.srt','-map','0:v','-map','1:a','-map','2:0','-c:v','copy','-c:a','aac','-b:a','192k','-ar','48000','-c:s','mov_text','-metadata:s:s:0','language=eng','-movflags','+faststart','presentation.mp4'],cancel,cwd=folder)
    (folder/'chapters.json').write_text(json.dumps(chapters,indent=2),encoding='utf-8')
    audit = audit_video(folder,elapsed,cancel)
    audit['caption_timing']='Character-proportional estimates within measured natural speech blocks; not word-aligned timestamps.'
    (folder/'quality.json').write_text(json.dumps(audit,indent=2),encoding='utf-8')
    (folder/'transcript.txt').write_text('\n\n'.join(f'Slide {s["number"]}: {s["title"]}\n{s["narration"]}' for s in selected),encoding='utf-8')
    from .lesson import package
    package(folder,project['name'],chapters,all_cues,burn_captions=settings['burn_captions'])
    return elapsed
