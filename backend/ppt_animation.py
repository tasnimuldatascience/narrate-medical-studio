"""Optional native PowerPoint animation export from a private sanitized copy.

Native playback is flattened to silent video. Page-click effects become a
deterministic sequence; shape-triggered/media effects are rejected explicitly.
The entire native clip is time-scaled, never silently cropped, to the requested
frame-aligned segment duration. See Microsoft's Presentation.CreateVideo API.
"""
import json
import contextlib
import logging
import math
import os
import posixpath
import shutil
import sys
import tempfile
import time
import zipfile
from pathlib import Path

from lxml import etree

from . import extract, media, store

NS = {'p': 'http://schemas.openxmlformats.org/presentationml/2006/main',
      'r': 'http://schemas.openxmlformats.org/officeDocument/2006/relationships'}


@contextlib.contextmanager
def native_workspace(parent):
    """Allow asynchronous Office job termination to release its video handles."""
    parent = Path(parent).resolve()
    work = Path(tempfile.mkdtemp(prefix='ppt-video-', dir=parent)).resolve()
    try:
        yield work
    finally:
        if work.parent != parent or not work.name.startswith('ppt-video-'):
            raise RuntimeError('Native workspace cleanup escaped its owned output directory.')
        for attempt in range(50):
            try:
                shutil.rmtree(work)
                break
            except FileNotFoundError:
                break
            except PermissionError:
                if attempt == 49:
                    # Preserve the original cancellation/error if a third-party
                    # scanner temporarily holds this private generated file.
                    logging.getLogger(__name__).warning('Native temporary files remain locked: %s', work)
                else:
                    time.sleep(.1)


def available():
    if os.name != 'nt' or not shutil.which('ffmpeg') or not shutil.which('ffprobe'):
        return False
    try:
        import winreg
        with winreg.OpenKey(winreg.HKEY_CLASSES_ROOT, 'PowerPoint.Application'):
            return True
    except (ImportError, OSError):
        return False


def inspect(source):
    """Read actual slide order and effect metadata without launching Office."""
    extract.validate(source)
    parser = etree.XMLParser(resolve_entities=False, no_network=True)
    with zipfile.ZipFile(source) as archive:
        def xml(name):
            root = etree.fromstring(archive.read(name), parser)
            if root.getroottree().docinfo.doctype:
                raise ValueError('XML document type declarations are not supported.')
            return root
        relationships = xml('ppt/_rels/presentation.xml.rels')
        targets = {item.get('Id'): posixpath.normpath(posixpath.join('ppt', item.get('Target', '').lstrip('/')))
                   if not item.get('Target', '').startswith('/') else item.get('Target', '').lstrip('/')
                   for item in relationships if item.get('TargetMode', '').lower() != 'external'}
        records = []
        for number, item in enumerate(xml('ppt/presentation.xml').findall('p:sldIdLst/p:sldId', NS), 1):
            part = targets.get(item.get('{%s}id' % NS['r']))
            if not part or not part.startswith('ppt/slides/'):
                raise ValueError('The presentation has an invalid slide relationship.')
            root = xml(part)
            records.append({
                'number': number, 'part': part,
                'has_timing': bool(root.findall('p:timing', NS)),
                'effect_count': len(root.xpath('.//p:cTn[@presetClass]', namespaces=NS)),
                'has_transition': bool(root.findall('p:transition', NS)),
                'interactive': bool(root.xpath('.//p:cTn[@nodeType="interactiveSeq"]', namespaces=NS)),
                'embedded_media': bool(root.xpath('.//*[local-name()="video" or local-name()="audio" or local-name()="videoFile" or local-name()="audioFile" or local-name()="media"]')),
            })
    return {'slide_count': len(records), 'timing_slides': sum(r['has_timing'] for r in records),
            'transition_slides': sum(r['has_transition'] for r in records), 'slides': records}


def plan_effects(effects, transition_duration=0):
    """Conservative finite timeline bound, retaining automatic effect groups."""
    if not math.isfinite(transition_duration) or not 0 <= transition_duration <= 3600:
        raise ValueError('The slide transition needs a finite nonnegative duration.')
    cursor = 0.0
    group_start = 0.0
    converted = 0
    schedule = []
    for effect in effects:
        trigger = int(effect['trigger'])
        if trigger not in (0, 1, 2, 3):
            raise ValueError('Shape-click or media-triggered animations need authoring changes before native video export.')
        values = [float(effect.get(key, 0)) for key in ('duration', 'delay', 'repeat_count', 'repeat_duration')]
        if any(not math.isfinite(value) or value < 0 or value > 3600 for value in values):
            raise ValueError('An animation has indefinite or unsupported timing. Give it finite timing in PowerPoint.')
        length, delay, repeats, repeated_seconds = values
        length *= max(1, repeats)
        if effect.get('auto_reverse'):
            length *= 2
        length = max(length, repeated_seconds)
        if trigger in (0, 1):
            converted += 1
            trigger = 3
            delay = max(delay, .35)
        start = (group_start if trigger == 2 else cursor) + delay
        if trigger != 2:
            group_start = start
        cursor = max(cursor, start + length)
        schedule.append({'trigger': trigger, 'delay': delay, 'start': start, 'end': start + length})
    minimum = float(transition_duration) + cursor + .5
    if not math.isfinite(minimum) or minimum > 3600:
        raise ValueError('Native animation timing exceeds the supported duration.')
    return {'effects': schedule, 'clicks_automated': converted, 'minimum_duration': minimum}


def render_slide(source_safe_pptx, slide_number, output_mp4, duration, cancel):
    """Return rendering/timing metadata; no source file or native audio is kept."""
    media.check(cancel)
    if isinstance(slide_number, bool) or not isinstance(slide_number, int) or slide_number < 1:
        raise ValueError('Choose a valid one-based slide number.')
    if not math.isfinite(duration) or duration < .5 or duration > 3600:
        raise ValueError('Native slide video duration must be between 0.5 and 3600 seconds.')
    source, output = Path(source_safe_pptx).resolve(), Path(output_mp4).resolve()
    if source.suffix.lower() != '.pptx' or source == output:
        raise ValueError('Native animation export requires a sanitized PPTX source and a separate MP4 output.')
    if output.suffix.lower() != '.mp4':
        raise ValueError('The native animation output must be an MP4 file.')
    if output.exists():
        raise ValueError('The native animation output already exists. Choose a fresh output path.')
    metadata = inspect(source)
    if slide_number > metadata['slide_count']:
        raise ValueError('The requested slide is outside this presentation.')
    slide = metadata['slides'][slide_number - 1]
    if slide['interactive'] or slide['embedded_media']:
        raise ValueError('Native export cannot flatten shape-triggered animation or embedded media safely. Use a source-based style or simplify this slide in PowerPoint.')
    if not available():
        raise ValueError('Native animation export requires Windows PowerPoint, FFmpeg, and ffprobe.')
    output.parent.mkdir(parents=True, exist_ok=True)
    frames = max(1, round(duration * 24))
    target_duration = frames / 24
    with native_workspace(output.parent) as work:
        safe = work / 'safe.pptx'
        extract.sanitize(source, safe)
        request = {'source': str(safe), 'slide_number': slide_number,
                   'output': str(work / 'native.mp4'), 'duration': target_duration,
                   'metadata': str(work / 'native.json'), 'timeout': min(1800, max(120, target_duration * 12))}
        (work / 'request.json').write_text(json.dumps(request), encoding='utf-8')
        media.run([sys.executable, '-m', 'backend.ppt_video_worker', str(work / 'request.json')],
                  cancel, cwd=store.ROOT, timeout=request['timeout'] + 30)
        native = Path(request['output'])
        if not native.is_file() or native.stat().st_size < 100:
            raise RuntimeError('PowerPoint did not produce a usable video.')
        probe = json.loads(media.run([shutil.which('ffprobe'), '-v', 'error', '-show_streams',
                                     '-show_format', '-of', 'json', str(native)], cancel))
        streams = [s for s in probe['streams'] if s.get('codec_type') == 'video']
        raw_duration = float(streams[0].get('duration', probe['format']['duration'])) if streams else 0
        if not math.isfinite(raw_duration) or raw_duration <= 0:
            raise RuntimeError('PowerPoint produced a video with invalid timing.')
        # Preserve the complete native timeline, including its final state.
        scale = target_duration / raw_duration
        target = work / 'fitted.mp4'
        media.run([shutil.which('ffmpeg'), '-y', '-i', str(native), '-an',
                   '-vf', f'setpts={scale:.12f}*(PTS-STARTPTS),fps=24,scale=1920:1080:force_original_aspect_ratio=decrease,pad=1920:1080:(ow-iw)/2:(oh-ih)/2:color=white,setsar=1,tpad=stop_mode=clone:stop_duration=1',
                   '-frames:v', str(frames), '-c:v', 'libx264', '-preset', 'fast', '-crf', '18',
                   '-pix_fmt', 'yuv420p', '-movflags', '+faststart', str(target)], cancel,
                  timeout=min(1800, max(120, target_duration * 5)))
        verified = json.loads(media.run([shutil.which('ffprobe'), '-v', 'error', '-show_streams', '-of', 'json', str(target)], cancel))
        visual = next(s for s in verified['streams'] if s['codec_type'] == 'video')
        if visual['codec_name'] != 'h264' or visual['width'] != 1920 or visual['height'] != 1080 or abs(float(visual['duration']) - target_duration) > 1 / 24 + .001:
            raise RuntimeError('Native animation output failed format or duration verification.')
        media.check(cancel)
        report = json.loads(Path(request['metadata']).read_text(encoding='utf-8'))
        report.update(source_slide=slide, native_duration=raw_duration, duration=target_duration,
                      timeline_scale=scale, frames=frames, audio='removed',
                      transition_policy='Isolated-slide entry transition; previous-slide pixels are not retained.',
                      timing_policy='Page clicks advance automatically; complete native timeline uniformly fitted to narration duration.')
        target.replace(output)
        return report
