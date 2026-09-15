"""Isolated Office CreateVideo worker with an owned-process lifetime job."""
import json
import math
import sys
import time
from pathlib import Path

from .ppt_animation import inspect, plan_effects


def new_powerpoint_pid(before, app):
    """Identify only the newly created empty Office server, never an open deck."""
    import win32api
    import win32con
    import win32process
    if app.Presentations.Count:
        raise RuntimeError('PowerPoint has open presentations. Close PowerPoint before native export.')
    candidates=[]
    for pid in set(win32process.EnumProcesses())-before:
        handle=None
        try:
            handle=win32api.OpenProcess(win32con.PROCESS_QUERY_INFORMATION|win32con.PROCESS_VM_READ,False,pid)
            if Path(win32process.GetModuleFileNameEx(handle,0)).name.lower()=='powerpnt.exe':
                candidates.append(pid)
        except Exception:
            continue
        finally:
            if handle is not None:handle.Close()
    if len(candidates)!=1:
        raise RuntimeError('Could not identify an isolated PowerPoint process. Close PowerPoint and retry; existing presentations were not changed.')
    return candidates[0]


def main():
    import pythoncom
    import win32api
    import win32con
    import win32com.client
    import win32job
    import win32process

    request = json.loads(Path(sys.argv[1]).read_text(encoding='utf-8'))
    source = Path(request['source']).resolve()
    if source.name != 'safe.pptx':
        raise ValueError('The native video worker only accepts its private sanitized safe.pptx.')
    inspect(source)
    before = set(win32process.EnumProcesses())
    pythoncom.CoInitialize()
    app = deck = job = handle = None
    owned = False
    try:
        app = win32com.client.DispatchEx('PowerPoint.Application')
        pid = new_powerpoint_pid(before, app)
        if pid in before:
            raise RuntimeError('PowerPoint reused an existing process. Close PowerPoint and retry native video export; your open presentations were not changed.')
        owned = True
        job = win32job.CreateJobObject(None, '')
        limits = win32job.QueryInformationJobObject(job, win32job.JobObjectExtendedLimitInformation)
        limits['BasicLimitInformation']['LimitFlags'] = win32job.JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
        win32job.SetInformationJobObject(job, win32job.JobObjectExtendedLimitInformation, limits)
        handle = win32api.OpenProcess(win32con.PROCESS_SET_QUOTA | win32con.PROCESS_TERMINATE, False, pid)
        win32job.AssignProcessToJobObject(job, handle)
        app.AutomationSecurity = 3
        app.DisplayAlerts = 1
        deck = app.Presentations.Open(str(source), ReadOnly=True, Untitled=False, WithWindow=False)
        number = int(request['slide_number'])
        if not 1 <= number <= deck.Slides.Count:
            raise ValueError('Slide number is outside the presentation.')
        for index in range(deck.Slides.Count, 0, -1):
            if index != number:
                deck.Slides(index).Delete()
        slide = deck.Slides(1)
        if slide.TimeLine.InteractiveSequences.Count:
            raise ValueError('Shape-triggered animations cannot be flattened automatically.')
        sequence = slide.TimeLine.MainSequence
        effects = []
        for index in range(1, sequence.Count + 1):
            timing = sequence(index).Timing
            effects.append({'trigger': timing.TriggerType, 'duration': timing.Duration,
                            'delay': timing.TriggerDelayTime, 'repeat_count': timing.RepeatCount,
                            'repeat_duration': timing.RepeatDuration, 'auto_reverse': bool(timing.AutoReverse)})
        transition = slide.SlideShowTransition
        transition_duration = float(transition.Duration) if int(transition.EntryEffect) != 0 else 0
        plan = plan_effects(effects, transition_duration)
        duration = float(request['duration'])
        if plan['minimum_duration'] > duration + .001:
            raise ValueError(f"Native effects need at least {plan['minimum_duration']:.2f} seconds; narration provides {duration:.2f}. Lengthen the narration or shorten effects in PowerPoint.")
        for index, item in enumerate(plan['effects'], 1):
            sequence(index).Timing.TriggerType = item['trigger']
            sequence(index).Timing.TriggerDelayTime = item['delay']
        transition.Hidden = False
        transition.AdvanceOnTime = True
        transition.AdvanceOnClick = False
        transition.AdvanceTime = duration
        deck.SlideShowSettings.AdvanceMode = 2
        deck.SlideShowSettings.ShowWithAnimation = True
        deck.SlideShowSettings.ShowWithNarration = False
        started = time.monotonic()
        deck.CreateVideo(str(Path(request['output']).resolve()), True, math.ceil(duration), 1080, 30, 90)
        while True:
            state = int(deck.CreateVideoStatus)
            if state == 3:
                break
            if state == 4:
                raise RuntimeError('PowerPoint reported a native video export failure.')
            if time.monotonic() - started > float(request['timeout']):
                raise TimeoutError('PowerPoint native video export timed out.')
            pythoncom.PumpWaitingMessages()
            time.sleep(.2)
        Path(request['metadata']).write_text(json.dumps({
            'renderer': 'PowerPoint CreateVideo', 'powerpoint_version': str(app.Version),
            'effect_count': len(effects), 'transition_duration': transition_duration,
            'minimum_duration': plan['minimum_duration'], 'clicks_automated': plan['clicks_automated'],
            'effect_schedule': plan['effects'],
        }, indent=2), encoding='utf-8')
    finally:
        if owned:
            try:
                if deck is not None:
                    deck.Saved = True
                    deck.Close()
            finally:
                try:
                    if app is not None:
                        app.Quit()
                finally:
                    if handle is not None:
                        handle.Close()
                    if job is not None:
                        job.Close()
        pythoncom.CoUninitialize()


if __name__ == '__main__':
    main()
