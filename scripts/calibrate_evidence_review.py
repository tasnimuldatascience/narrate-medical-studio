"""Local, private source-fidelity regression experiment; no clinical certification.

Expected labels are evaluated after inference and never passed to the reviewer.
This is a development regression set, not clinician-labeled held-out validation.
"""
import argparse
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from backend import evaluation as ev, store
from scripts.render_draft_preview import FileCancellation


def cases(path):
    data=json.loads(path.read_text(encoding='utf-8'))
    rows=data.get('cases')
    if not isinstance(rows,list) or not 1<=len(rows)<=100:
        raise ValueError('A private calibration dataset needs 1–100 cases.')
    names=set()
    for row in rows:
        name=row.get('name','')
        if not __import__('re').fullmatch(r'[A-Za-z0-9_-]{1,100}',name) or name in names:
            raise ValueError('Case names must be unique safe identifiers.')
        names.add(name)
        if (not isinstance(row.get('slide'),dict) or not isinstance(row.get('script'),str)
                or not 0<len(row['script'])<=12000 or type(row.get('expected_discrepancy')) is not bool):
            raise ValueError('Each case needs source fields, a bounded script and a Boolean expected label.')
        for field in ('draft_anchors','source_anchors','expected_kinds'):
            if not isinstance(row.get(field),list) or any(not isinstance(x,str) or not x for x in row[field]):
                raise ValueError('Expected target anchors and kinds must be string lists.')
        if row['expected_discrepancy'] and (not row['expected_kinds'] or not (row['draft_anchors'] or row['source_anchors'])):
            raise ValueError('Positive cases need an expected discrepancy kind and an exact target anchor.')
        ev.build_evidence(row['slide'])
        yield row


def matches_target(case, finding):
    """Compare only after inference; expected target labels never enter prompts."""
    draft=' '.join(s['text'] for s in finding.get('draft_spans',[]))
    source=' '.join(s['text'] for s in finding.get('source_spans',[]))
    return (finding.get('kind') in case['expected_kinds']
        and all(anchor in draft for anchor in case['draft_anchors'])
        and all(anchor in source for anchor in case['source_anchors']))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--dataset', type=Path, required=True, help='Private JSON with cases and expected source-fidelity labels.')
    parser.add_argument('--model', default='qwen3.5:9b')
    parser.add_argument('--output-dir', type=Path, required=True)
    parser.add_argument('--cases', nargs='+', help='Run selected named development cases.')
    parser.add_argument('--cancel-file', type=Path)
    args = parser.parse_args()
    args.output_dir.mkdir(parents=True, exist_ok=True)
    identity = ev.resolve_model(args.model)
    fingerprint = ev.runtime_fingerprint()
    cancel = FileCancellation(args.cancel_file or args.output_dir/'cancel-requested')
    original_json = ev.local_json
    def observed_json(model, system, payload, schema, **kwargs):
        stage = ('alignment' if system == ev.evidence_review.ALIGN_SYSTEM else
                 'independent_alignment' if system == ev.evidence_review.BLIND_SYSTEM else 'challenge')
        message = {'case': current_case, 'stage': stage, 'status': 'running'}
        (args.output_dir/'progress.json').write_text(json.dumps(message), encoding='utf-8')
        print(json.dumps(message), flush=True)
        return original_json(model, system, payload, schema, **kwargs)
    ev.local_json = observed_json
    rows = []
    selected = list(cases(args.dataset))
    if args.cases:
        if set(args.cases) - {c['name'] for c in selected}:
            raise ValueError('Unknown calibration case name.')
        selected = [c for c in selected if c['name'] in args.cases]
    for case in selected:
        name,slide,script,expected=(case[k] for k in ('name','slide','script','expected_discrepancy'))
        current_case = name
        if cancel.is_set():
            print('Calibration cancelled between cases.', flush=True)
            break
        packet = ev.build_evidence(slide)
        key = ev.digest({'source': packet['hash'], 'script': script, 'model': identity,
                         'code': fingerprint, 'case': name, 'calibration_protocol': 'target-matched-v3', 'dataset_case_hash': ev.digest(case)})
        path = args.output_dir / (name + '.json')
        prior = json.loads(path.read_text(encoding='utf-8')) if path.exists() else None
        if prior and prior.get('key') == key and prior.get('status') == 'completed':
            row = prior
        else:
            started = time.monotonic()
            print(json.dumps({'case': name, 'status': 'running'}), flush=True)
            try:
                report = ev.evaluate(packet, script, args.model, 'Medical practitioners', identity=identity, cancel=cancel)
                detected = any(f.get('origin') == 'critic' for f in report['findings'])
                target = any(matches_target(case, f) for f in report['findings']) if expected else False
                abstained = bool(report['uncertain_findings']) and not target
                row = {'case': name, 'key': key, 'status': 'completed', 'expected_discrepancy': expected,
                       'detected_discrepancy': detected, 'target_detected': target,
                       'abstained': abstained, 'match': (target if expected else not detected) and not abstained,
                       'uncertain_count': len(report['uncertain_findings']), 'report': report}
            except Exception as exc:
                row = {'case': name, 'key': key, 'status': 'cancelled' if cancel.is_set() else 'failed', 'error': str(exc),
                       'validation_attempts': getattr(exc, 'validation_attempts', [])}
            row['elapsed_seconds'] = round(time.monotonic() - started, 2)
            path.write_text(json.dumps(row, indent=2), encoding='utf-8')
        rows.append(row)
        print(json.dumps({k: v for k, v in row.items() if k not in ('report', 'validation_attempts')}), flush=True)
        valid = [r for r in rows if r['status'] == 'completed']
        summary = {'scope': 'Development source-fidelity regression, not clinical validation or held-out accuracy.',
            'model_identity': identity, 'evaluator_fingerprint': fingerprint,
            'completed': len(valid), 'failed': len(rows) - len(valid),
            'matched': sum(r['match'] for r in valid), 'total_cases': len(rows),
            'planned_cases': len(selected), 'abstained': sum(r.get('abstained', False) for r in valid),
            'false_positives': [r['case'] for r in valid if not r['expected_discrepancy'] and r['detected_discrepancy']],
            'false_negatives': [r['case'] for r in valid if r['expected_discrepancy'] and not r.get('target_detected')],
            'uncertain_cases': [r['case'] for r in valid if r['uncertain_count']],
            'clinical_validation': False}
        (args.output_dir / 'summary.json').write_text(json.dumps(summary, indent=2), encoding='utf-8')
    print(json.dumps(summary if rows else {'status':'cancelled','completed':0}), flush=True)


if __name__ == '__main__':
    main()
