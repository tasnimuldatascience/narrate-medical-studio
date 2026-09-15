import hashlib
import socket
import threading
from types import SimpleNamespace

import numpy as np
import pytest
from PIL import Image, ImageDraw, ImageFont

from backend import ocr, store
from backend.media import Cancelled


@pytest.fixture(autouse=True)
def clear_engine(monkeypatch):
    monkeypatch.setattr(ocr,'_engine',None)
    monkeypatch.setattr(ocr,'_engine_signature',None)
    monkeypatch.setattr(ocr,'_verified',{})


@pytest.fixture
def source(tmp_path,monkeypatch):
    monkeypatch.setattr(store,'DATA',tmp_path)
    path=tmp_path/('a'*32)/'slides'/'slide-1.png'
    path.parent.mkdir(parents=True)
    Image.new('RGB',(400,200),'white').save(path)
    return path


@pytest.fixture
def mock_assets(tmp_path,monkeypatch):
    model_dir=tmp_path/'ocr'
    model_dir.mkdir()
    model=model_dir/'model.onnx'
    model.write_bytes(b'model')
    dictionary=model_dir/ocr.DICTIONARY
    dictionary.write_text('characters',encoding='utf-8')
    monkeypatch.setattr(ocr,'MODEL_DIR',model_dir)
    monkeypatch.setattr(ocr,'MODEL_HASHES',{'model.onnx':hashlib.sha256(b'model').hexdigest()})
    monkeypatch.setattr(ocr,'DICTIONARY_HASH',hashlib.sha256(b'characters').hexdigest())
    monkeypatch.setattr(ocr.importlib.metadata,'version',lambda name:ocr.VERSION if name=='rapidocr' else '1.30.0')
    return model_dir


def test_availability_requires_every_verified_asset(mock_assets):
    assert ocr.available()
    (mock_assets/ocr.DICTIONARY).write_text('changed',encoding='utf-8')
    assert not ocr.available()
    (mock_assets/ocr.DICTIONARY).write_text('characters',encoding='utf-8')
    (mock_assets/'model.onnx').write_bytes(b'broken')
    assert not ocr.available()
    (mock_assets/'model.onnx').unlink()
    assert not ocr.available()


@pytest.mark.parametrize('path',[
    'https://example.invalid/image.png',r'\\server\share\slide-1.png',
    '//server/share/image.png','source.pptx','data/validation/slide-1.png',
])
def test_ocr_rejects_urls_and_nonproject_inputs_before_model_access(source,monkeypatch,path):
    monkeypatch.setattr(ocr,'_assets',lambda:pytest.fail('Unsafe path reached model initialization'))
    with pytest.raises(ValueError,match='local project PNG'):
        ocr.extract_text(path,threading.Event())


def test_missing_assets_fail_before_inference(source,mock_assets,monkeypatch):
    (mock_assets/ocr.DICTIONARY).unlink()
    monkeypatch.setattr(ocr,'_build_engine',lambda:pytest.fail('Missing assets reached inference'))
    with pytest.raises(ValueError,match='not ready'):
        ocr.extract_text(source,threading.Event())


def test_result_preserves_quantities_and_normalizes_boxes(source,mock_assets,monkeypatch):
    def engine(pixels):
        assert isinstance(pixels,np.ndarray) and pixels.shape==(200,400,3)
        return SimpleNamespace(txts=('Sample 1.5 mL','Uncertain label'),scores=(.99,.65),
            boxes=np.array([[[0,0],[200,0],[200,100],[0,100]],
                            [[-2,100],[410,100],[410,205],[-2,205]]]))
    monkeypatch.setattr(ocr,'_build_engine',lambda:engine)
    result=ocr.extract_text(source,threading.Event())
    assert result['text']=='Sample 1.5 mL\nUncertain label'
    assert result['lines'][0]['box']==[[0,0],[.5,0],[.5,.5],[0,.5]]
    assert result['lines'][1]['box']==[[0,.5],[1,.5],[1,1],[0,1]]
    assert result['lines'][0]['confidence']==.99
    assert any('number, decimal, range, and unit' in warning for warning in result['warnings'])
    assert any('2.' in warning for warning in result['warnings'])
    assert 'not clinical validation' in result['warnings'][0]


def test_no_text_is_reported_without_fabrication(source,mock_assets,monkeypatch):
    monkeypatch.setattr(ocr,'_build_engine',lambda:lambda pixels:SimpleNamespace(txts=None,scores=None,boxes=None))
    result=ocr.extract_text(source,threading.Event())
    assert result['text']=='' and result['lines']==[]
    assert any('No readable text' in warning for warning in result['warnings'])


def test_cancel_during_inference_discards_result(source,mock_assets,monkeypatch):
    cancel=threading.Event()
    def engine(pixels):
        cancel.set()
        return SimpleNamespace(txts=None,scores=None,boxes=None)
    monkeypatch.setattr(ocr,'_build_engine',lambda:engine)
    with pytest.raises(Cancelled):
        ocr.extract_text(source,cancel)
    assert not ocr._lock.locked()


def test_precancelled_request_does_not_touch_image(monkeypatch):
    cancel=threading.Event()
    cancel.set()
    monkeypatch.setattr(ocr,'_image_path',lambda path:pytest.fail('Cancelled request opened image'))
    with pytest.raises(Cancelled):
        ocr.extract_text('missing.png',cancel)


def test_dependency_downloader_is_explicitly_disabled():
    with pytest.raises(RuntimeError,match='runtime downloads are disabled'):
        ocr._deny_download('https://example.invalid/model.onnx')


def test_real_local_ocr_with_network_blocked(source,monkeypatch):
    if not ocr.available():
        pytest.skip('Explicit OCR setup required for real inference test')
    def no_network(*args,**kwargs):
        pytest.fail('Network access attempted during OCR')
    monkeypatch.setattr(socket.socket,'connect',no_network)
    monkeypatch.setattr(socket,'create_connection',no_network)
    monkeypatch.setattr(ocr,'_deny_download',no_network)
    image=Image.new('RGB',(1000,220),'white')
    try:
        font=ImageFont.truetype('arial.ttf',48)
    except OSError:
        font=ImageFont.load_default(size=48)
    ImageDraw.Draw(image).text((35,55),'Sample 1.5 mL',fill='black',font=font)
    image.save(source)
    result=ocr.extract_text(source,threading.Event())
    assert '1.5' in result['text']
    assert 'Sample' in result['text']
    assert result['lines']
    assert all(0<=coordinate<=1 for line in result['lines'] for point in line['box'] for coordinate in point)
