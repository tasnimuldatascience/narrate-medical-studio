"""Map authored paragraph references to measured, content-preserving speech blocks."""
import math
import re


def paragraphs(text):
    return [part.strip() for part in re.split(r'\n\s*\n', text.replace('\r\n','\n')) if part.strip()]


def scene_spans(duration, count, cue_starts=None, *, lead=.9, tail=1.8):
    if not math.isfinite(duration) or duration <= 0:
        raise ValueError('Scene duration must be positive.')
    if not count:
        if cue_starts:
            raise ValueError('Scene timings require matching authored regions.')
        return duration, [], 0.
    if cue_starts is None:
        slot=(duration-lead-tail)/count
        if slot<=0:
            raise ValueError('The scene is too short for its opening and overview.')
        return lead,[slot]*count,tail
    if (len(cue_starts)!=count or any(isinstance(t,bool) or not isinstance(t,(int,float))
            or not math.isfinite(t) or t<0 or t>=duration for t in cue_starts)
            or any(a>=b for a,b in zip(cue_starts,cue_starts[1:]))):
        raise ValueError('Region start times must match the region count, increase strictly, and stay inside the scene. Reorder or reassign paragraph references.')
    overview=min(tail,(duration-cue_starts[-1])*.2)
    ends=[*cue_starts[1:],duration-overview]
    return cue_starts[0],[end-start for start,end in zip(cue_starts,ends)],overview


def paragraph_cue_starts(text, cues, speech_blocks, duration, *, speech_lead=.9, style='focus'):
    """Return None for legacy uniform timing; otherwise one start per region.

    Matching only normalizes whitespace. It never estimates within a speech block
    or silently remaps edited text to an unrelated spoken passage.
    """
    if not any(cue.get('paragraph') is not None for cue in cues):
        return None
    parts=paragraphs(text)
    compact=lambda value: ''.join(value.split())
    normalized=[compact(part) for part in parts]
    block_text=[compact(block['text']) for block in speech_blocks]
    if ''.join(normalized) != ''.join(block_text):
        raise ValueError('Measured speech text does not match the saved narration. Regenerate the voice before using paragraph-linked regions.')
    offsets={};cursor=0;previous_end=0.
    for block,spoken in zip(speech_blocks,block_text):
        start,end=block['start'],block['end']
        if (not spoken or not all(isinstance(t,(int,float)) and not isinstance(t,bool) and math.isfinite(t) for t in (start,end))
                or start<previous_end-1e-6 or end<=start or end+speech_lead>duration+1e-6):
            raise ValueError('Measured speech blocks have invalid or overlapping timing. Regenerate the voice.')
        offsets[cursor]=start+speech_lead
        cursor+=len(spoken);previous_end=end
    paragraph_offsets=[];cursor=0
    for part in normalized:
        paragraph_offsets.append(cursor);cursor+=len(part)
    lead=min(.9,duration*(.1 if style=='focus' else .12))
    tail=min(1.8,duration*(.1 if style=='focus' else .15))
    slot=(duration-lead-tail)/len(cues)
    starts=[lead+i*slot for i in range(len(cues))]
    for index,cue in enumerate(cues):
        paragraph=cue.get('paragraph')
        if paragraph is None:
            continue
        if isinstance(paragraph,bool) or not isinstance(paragraph,int) or not 0<=paragraph<len(parts):
            raise ValueError(f'Region {index+1} references a missing narration paragraph. Reassign it to one of the {len(parts)} paragraphs.')
        offset=paragraph_offsets[paragraph]
        if offset not in offsets:
            raise ValueError('The voice combined paragraph boundaries into one speech block. Regenerate paragraph-separated voice before using linked regions.')
        starts[index]=offsets[offset]
    scene_spans(duration,len(cues),starts,lead=lead,tail=tail)
    return starts
