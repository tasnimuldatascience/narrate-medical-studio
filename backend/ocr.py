"""Local source transcription, never clinical interpretation or approval.

RapidOCR is pinned and all three ONNX assets plus its character dictionary are
validated before initialization. Runtime downloads are explicitly disabled.
"""
import hashlib
import importlib.metadata
import math
import os
from pathlib import Path
import re
import threading

import numpy as np
from PIL import Image

from . import store

VERSION = '3.9.2'
ENGINE = 'RapidOCR 3.9.2 / PP-OCRv6 small / CPU'
MODEL_DIR = Path(os.environ.get('NARRATE_OCR_MODELS', store.ROOT/'models'/'ocr')).resolve()
# Hashes from RapidAI's pinned 3.9.2 wheel and default_models.yaml.
MODEL_HASHES = {
    'PP-OCRv6_det_small.onnx': '090f04abcd9d9a7498bc4ebf677e4cb9bdce1fe4197ddb7e529f1ef44e1ff94f',
    'ch_ppocr_mobile_v2.0_cls_mobile.onnx': 'e47acedf663230f8863ff1ab0e64dd2d82b838fceb5957146dab185a89d6215c',
    'PP-OCRv6_rec_small.onnx': '6f327246b50388f3c176ae304bd95767ea6dc0c9ae92153ef8cbe210b3c14884',
}
DICTIONARY = 'characters.txt'
DICTIONARY_HASH = 'f7aa897ca828a4c7c9e2739c30f9161a33306d532f020bcdb91dcfb664a5507e'
_lock = threading.Lock()
_engine = None
_engine_signature = None
_verified = {}


def _sha256(path):
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def _assets():
    if importlib.metadata.version('rapidocr') != VERSION:
        raise ValueError(f'Install the pinned RapidOCR {VERSION} dependency using Setup.ps1.')
    signature = []
    for name, expected in MODEL_HASHES.items():
        path = MODEL_DIR/name
        stat = path.stat()
        stamp = (str(path), stat.st_size, stat.st_mtime_ns, stat.st_ctime_ns)
        if _verified.get(stamp) != expected:
            if _sha256(path) != expected:
                raise ValueError('An OCR model failed integrity verification. Run scripts/download_ocr.py.')
            _verified[stamp] = expected
        signature.append(stamp)
    dictionary = MODEL_DIR/DICTIONARY
    content = dictionary.read_text(encoding='utf-8')
    if hashlib.sha256(content.encode('utf-8')).hexdigest() != DICTIONARY_HASH:
        raise ValueError('The local OCR character dictionary is missing or invalid. Run scripts/download_ocr.py.')
    # The pinned recognition model embeds its authoritative character table;
    # this explicit local copy prevents any dictionary-download fallback.
    signature.append((str(dictionary), _sha256(dictionary)))
    return tuple(signature)


def available():
    try:
        _assets()
        importlib.metadata.version('onnxruntime')
        return True
    except (OSError, ValueError, importlib.metadata.PackageNotFoundError):
        return False


def _deny_download(*args, **kwargs):
    raise RuntimeError('OCR runtime downloads are disabled. Run explicit OCR setup first.')


def _build_engine():
    import onnxruntime
    onnxruntime.disable_telemetry_events()
    from rapidocr import RapidOCR
    from rapidocr.utils.download_file import DownloadFile
    # Defense in depth for this pinned dependency: no model, dictionary, or
    # optional visualization-font fallback may access the network at runtime.
    DownloadFile.run = staticmethod(_deny_download)
    return RapidOCR(params={
        'Det.model_path': str(MODEL_DIR/'PP-OCRv6_det_small.onnx'),
        'Cls.model_path': str(MODEL_DIR/'ch_ppocr_mobile_v2.0_cls_mobile.onnx'),
        'Rec.model_path': str(MODEL_DIR/'PP-OCRv6_rec_small.onnx'),
        'Rec.rec_keys_path': str(MODEL_DIR/DICTIONARY),
        'Global.model_root_dir': str(MODEL_DIR),
        'Global.log_level': 'error',
        'Global.text_score': .3,
        'EngineConfig.onnxruntime.intra_op_num_threads': 2,
        'EngineConfig.onnxruntime.inter_op_num_threads': 1,
        'EngineConfig.onnxruntime.use_cuda': False,
        'EngineConfig.onnxruntime.use_dml': False,
    })


def _image_path(image_path):
    raw = str(image_path)
    if '://' in raw or raw.startswith(('\\\\', '//')):
        raise ValueError('OCR accepts only a rendered local project PNG.')
    path = Path(image_path).resolve()
    try:
        relative = path.relative_to(store.DATA.resolve())
    except ValueError as exc:
        raise ValueError('OCR accepts only a rendered local project PNG.') from exc
    if (len(relative.parts) != 3 or not re.fullmatch(r'[a-f0-9]{32}', relative.parts[0])
            or relative.parts[1] != 'slides' or not re.fullmatch(r'slide-[1-9][0-9]*\.png', relative.parts[2])):
        raise ValueError('OCR accepts only a rendered local project PNG.')
    if not path.is_file():
        raise ValueError('Render this slide before transcribing its image.')
    return path


def extract_text(image_path, cancel):
    """Return text and normalized quadrilateral boxes from a known slide PNG.

    Confidence measures OCR recognition only. It is not a medical-confidence
    score. Cancellation is checked before/after native inference, which cannot
    be interrupted while an individual ONNX operation is executing.
    """
    global _engine, _engine_signature
    from .media import check
    check(cancel)
    path = _image_path(image_path)
    try:
        signature = _assets()
    except (OSError, ValueError, importlib.metadata.PackageNotFoundError) as exc:
        raise ValueError('Offline OCR is not ready. Run scripts/download_ocr.py from Setup.') from exc
    with Image.open(path) as source:
        if source.format != 'PNG' or source.width * source.height > 20_000_000:
            raise ValueError('OCR requires a rendered PNG no larger than 20 megapixels.')
        width, height = source.size
        # Pass decoded pixels, never a path or URL, into the OCR dependency.
        pixels = np.asarray(source.convert('RGB'))[:, :, ::-1].copy()
    while not _lock.acquire(timeout=.1):
        check(cancel)
    try:
        check(cancel)
        if _engine is None or _engine_signature != signature:
            _engine = _build_engine()
            _engine_signature = signature
        check(cancel)
        result = _engine(pixels)
        check(cancel)
    finally:
        _lock.release()
    lines = []
    texts = result.txts if result.txts is not None else []
    scores = result.scores if result.scores is not None else []
    boxes = result.boxes if result.boxes is not None else []
    if not len(texts) == len(scores) == len(boxes):
        raise ValueError('OCR returned inconsistent text and coordinates. Retry transcription.')
    for text, score, box in zip(texts, scores, boxes):
        confidence = float(score)
        coordinates = np.asarray(box, dtype=float)
        if (not math.isfinite(confidence) or not 0 <= confidence <= 1
                or coordinates.shape != (4, 2) or not np.isfinite(coordinates).all()):
            raise ValueError('OCR returned invalid recognition data. Retry transcription.')
        if not str(text).strip():
            continue
        normalized = np.clip(coordinates / [width, height], 0, 1).tolist()
        lines.append({'text': str(text), 'confidence': confidence, 'box': normalized})
    warnings = ['OCR is an unreviewed transcription, not clinical validation. Compare every line with the slide image.']
    if any(re.search(r'\d', line['text']) for line in lines):
        warnings.append('Verify every number, decimal, range, and unit against the image before using this text.')
    uncertain = [str(i+1) for i, line in enumerate(lines) if line['confidence'] < .9]
    if uncertain:
        warnings.append('Lower-confidence OCR lines need particular attention: ' + ', '.join(uncertain) + '.')
    if not lines:
        warnings.append('No readable text was detected. Transcribe the visible source manually.')
    return {'text': '\n'.join(line['text'] for line in lines), 'lines': lines,
            'engine': ENGINE, 'warnings': warnings}
