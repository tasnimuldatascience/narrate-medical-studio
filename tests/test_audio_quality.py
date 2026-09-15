import wave
import numpy as np
import pytest
from backend.audio_quality import inspect_audio


def wav(tmp_path,samples):
    path=tmp_path/'voice.wav'
    with wave.open(str(path),'wb') as audio:
        audio.setnchannels(1);audio.setsampwidth(2);audio.setframerate(24000)
        audio.writeframes(np.asarray(samples,dtype='<i2').tobytes())
    return path


def test_silence_is_flagged_without_naturalness_score(tmp_path):
    report=inspect_audio(wav(tmp_path,np.zeros(96000)))
    assert report['duration_seconds']==4
    assert len(report['warnings'])==2
    assert report['listening_review_required'] is True
    assert 'naturalness' in report['not_assessed']


def test_clipped_audio_is_detected(tmp_path):
    report=inspect_audio(wav(tmp_path,[32767,-32768]*12000))
    assert report['near_clipping_fraction']==1
    assert any('clipping' in text for text in report['warnings'])


def test_empty_audio_fails(tmp_path):
    with pytest.raises(ValueError,match='empty'):
        inspect_audio(wav(tmp_path,[]))
