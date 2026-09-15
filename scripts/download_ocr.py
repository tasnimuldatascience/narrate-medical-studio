"""Explicit OCR setup from the official, pinned RapidAI PyPI wheel.

RapidOCR 3.9.2 bundles its ONNX assets, so this step makes verified project-local
copies and extracts the embedded character table. No additional network call is
needed after pip installs requirements.txt. Runtime never downloads assets.
"""
import hashlib
import importlib.metadata
from pathlib import Path
import shutil
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from backend import ocr


def main():
    if importlib.metadata.version('rapidocr') != ocr.VERSION:
        raise SystemExit(f'Install rapidocr=={ocr.VERSION} from requirements.txt first.')
    import rapidocr
    import onnxruntime as ort
    source = Path(rapidocr.__file__).parent/'models'
    ocr.MODEL_DIR.mkdir(parents=True, exist_ok=True)
    for name, expected in ocr.MODEL_HASHES.items():
        original = source/name
        if not original.is_file() or hashlib.sha256(original.read_bytes()).hexdigest() != expected:
            raise SystemExit(f'The official RapidOCR wheel asset is missing or invalid: {name}. Reinstall the pinned dependency.')
        target = ocr.MODEL_DIR/name
        temporary = target.with_suffix('.part')
        shutil.copyfile(original, temporary)
        temporary.replace(target)
        print(f'Installed verified local OCR asset: {name}')
    options = ort.SessionOptions()
    options.intra_op_num_threads = 2
    options.inter_op_num_threads = 1
    session = ort.InferenceSession(str(ocr.MODEL_DIR/'PP-OCRv6_rec_small.onnx'),
                                  sess_options=options, providers=['CPUExecutionProvider'])
    characters = session.get_modelmeta().custom_metadata_map.get('character', '')
    if len(characters.splitlines()) < 100:
        raise SystemExit('Recognition model does not contain the expected character table.')
    (ocr.MODEL_DIR/ocr.DICTIONARY).write_text(characters, encoding='utf-8')
    if not ocr.available():
        raise SystemExit('OCR asset verification did not complete.')
    print('Offline OCR ready. Image transcription still requires source review; no clinical approval is granted.')


if __name__ == '__main__':
    main()
