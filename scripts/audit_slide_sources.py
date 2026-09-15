"""Audit every rendered slide in one local project with offline OCR.

Reads the project database in SQLite read-only mode. Writes a separate report
under ignored data/validation; it never saves source text, reviews, or approvals
back into a project. Confidence and quantity flags are transcription aids only.
"""
import argparse
from contextlib import contextmanager
import hashlib
import json
from pathlib import Path
import re
import socket
import sqlite3
import sys
import threading
import time

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from backend import ocr, store


def read_project(project_id):
    if not re.fullmatch(r'[a-f0-9]{32}', project_id):
        raise ValueError('Supply a local project ID, not a path or URL.')
    database = store.DATA/'studio.sqlite3'
    with sqlite3.connect(database.as_uri()+'?mode=ro', uri=True) as connection:
        row = connection.execute('SELECT body FROM projects WHERE id=?', (project_id,)).fetchone()
    if row is None:
        raise ValueError('The project does not exist in local storage.')
    return json.loads(row[0]), hashlib.sha256(row[0].encode('utf-8')).hexdigest()


@contextmanager
def no_python_network():
    def denied(*args, **kwargs):
        raise RuntimeError('Network access is disabled during this offline OCR audit.')
    targets = [(socket.socket,'connect'), (socket.socket,'connect_ex'),
               (socket,'create_connection'), (socket,'getaddrinfo')]
    original = [(owner,name,getattr(owner,name)) for owner,name in targets]
    try:
        for owner,name in targets:
            setattr(owner,name,denied)
        yield
    finally:
        for owner,name,value in original:
            setattr(owner,name,value)


def summarize(results):
    successful = [value for key,value in results.items() if key != '_audit' and 'error' not in value]
    all_lines = [line for result in successful for line in result['lines']]
    numeric = [line for line in all_lines if re.search(r'\d',line['text'])]
    return {
        'processed': len(results)-('_audit' in results),
        'readable_slides': sum(bool(result['text'].strip()) for result in successful),
        'empty_slides': sum(not result['text'].strip() for result in successful),
        'failed_slides': sum('error' in value for key,value in results.items() if key != '_audit'),
        'recognized_lines': len(all_lines),
        'low_confidence_lines': sum(line['confidence'] < .9 for line in all_lines),
        'slides_with_low_confidence_lines': sum(any(line['confidence'] < .9 for line in result['lines']) for result in successful),
        'numeric_lines': len(numeric),
        'low_confidence_numeric_lines': sum(line['confidence'] < .9 for line in numeric),
        'slides_with_numeric_lines': sum(any(re.search(r'\d',line['text']) for line in result['lines']) for result in successful),
    }


def save_report(path, results):
    temporary = path.with_suffix('.json.part')
    temporary.write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding='utf-8')
    temporary.replace(path)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--project-id', required=True)
    parser.add_argument('--output', required=True, type=Path,
                        help='JSON report path inside the local data/validation directory.')
    args = parser.parse_args()
    output = args.output.resolve()
    if output.suffix.lower() != '.json' or not output.is_relative_to((store.DATA/'validation').resolve()):
        parser.error('Keep source-containing JSON reports under the ignored local data/validation directory.')
    project, original_digest = read_project(args.project_id)
    if not ocr.available():
        parser.error('Run scripts/download_ocr.py to prepare the complete local OCR assets first.')
    output.parent.mkdir(parents=True, exist_ok=True)
    results = {}
    metadata = {
        'project_id': args.project_id, 'created_at': store.now(),
        'engine': ocr.ENGINE, 'total_slides': len(project['slides']),
        'source_sha256': project.get('source_sha256'),
        'project_record_sha256_before': original_digest,
        'clinical_approval': False, 'database_access': 'read-only',
        'low_confidence_threshold': .9,
        'network_guards': 'Python connection/DNS calls blocked; OCR dependency downloads and ONNX telemetry disabled.',
        'status': 'running',
    }
    started = time.monotonic()
    cancel = threading.Event()
    try:
        with no_python_network():
            for slide in sorted(project['slides'], key=lambda value:value['number']):
                number = slide['number']
                slide_started = time.monotonic()
                try:
                    result = ocr.extract_text(store.DATA/args.project_id/'slides'/f'slide-{number}.png', cancel)
                    result['elapsed_seconds'] = round(time.monotonic()-slide_started, 3)
                    results[str(number)] = result
                    print(f'Slide {number}: {len(result["lines"])} lines, {result["elapsed_seconds"]:.3f}s', flush=True)
                except Exception as exc:
                    results[str(number)] = {'error': str(exc), 'elapsed_seconds': round(time.monotonic()-slide_started,3)}
                    print(f'Slide {number}: failed: {exc}', flush=True)
                results['_audit'] = {**metadata, **summarize(results), 'elapsed_seconds': round(time.monotonic()-started,3)}
                save_report(output, results)
        metadata['status'] = 'completed'
    except KeyboardInterrupt:
        cancel.set()
        metadata['status'] = 'cancelled'
    _, final_digest = read_project(args.project_id)
    metadata.update(project_record_sha256_after=final_digest,
                    project_record_unchanged_during_audit=original_digest == final_digest)
    results['_audit'] = {**metadata, **summarize(results), 'elapsed_seconds': round(time.monotonic()-started,3)}
    save_report(output, results)
    print(json.dumps(results['_audit'], indent=2), flush=True)
    return 130 if metadata['status'] == 'cancelled' else int(results['_audit']['failed_slides'] > 0)


if __name__ == '__main__':
    raise SystemExit(main())
