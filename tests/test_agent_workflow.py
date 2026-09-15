import copy
import json
import threading
from uuid import uuid4

import pytest

from backend import agent_workflow as workflow, evaluation as ev, narration, media, store


@pytest.fixture
def setup(monkeypatch, tmp_path):
    monkeypatch.setattr(store, 'DATA', tmp_path)
    project = uuid4().hex
    store.create({'id': project, 'updated_at': 'now'})
    folder = tmp_path / project / 'agent-runs' / uuid4().hex
    monkeypatch.setattr(ev, 'resolve_model', lambda *a: {'name': 'local:4b', 'digest': 'abc'})
    calls = []
    def teacher(slide, model, audience, **kwargs):
        calls.append('teacher')
        return narration.Draft(narration=slide['text'], review_flags=[])
    def critic(packet, script, model, audience, **kwargs):
        calls.append('critic')
        return {'version': ev.VERSION, 'state': 'review_required', 'clinical_validation': False,
            'source_hash': packet['hash'], 'script_hash': ev.digest(script), 'findings': [],
            'requires_practitioner_review': True}
    monkeypatch.setattr(narration, 'generate', teacher)
    monkeypatch.setattr(ev, 'evaluate', critic)
    slide = {'number': 1, 'revision': 2, 'text': 'Observe the diagram.', 'notes': '', 'tables': []}
    return folder, slide, calls


def test_resume_reuses_only_matching_completed_stages(setup):
    folder, slide, calls = setup
    progress = []
    first = workflow.run(slide, 'local:4b', 'learner', run_folder=folder,
                         progress=lambda *args: progress.append(args))
    second = workflow.run(slide, 'local:4b', 'learner', run_folder=folder)
    assert calls == ['teacher', 'critic']
    assert first['candidate'] == second['candidate']
    assert all(t['status'] == 'cached' for t in second['trace'])
    assert progress[-1][0] == 100
    assert all(isinstance(p, int) and isinstance(message, str) for p, message in progress)
    assert (folder / first['fingerprint'] / 'result.json').exists()


@pytest.mark.parametrize('change', ['source', 'revision', 'model', 'style'])
def test_fingerprint_invalidates_changed_inputs(setup, monkeypatch, change):
    folder, slide, calls = setup
    first = workflow.run(slide, 'local:4b', 'learner', run_folder=folder)
    kwargs = {}
    if change == 'source': slide['text'] = 'Explain the diagram.'
    if change == 'revision': slide['revision'] += 1
    if change == 'model': monkeypatch.setattr(ev, 'resolve_model', lambda *a: {'name': 'local:4b', 'digest': 'new'})
    if change == 'style': kwargs['style'] = 'concise'
    second = workflow.run(slide, 'local:4b', 'learner', run_folder=folder, **kwargs)
    assert first['fingerprint'] != second['fingerprint']
    assert calls == ['teacher', 'critic', 'teacher', 'critic']


def test_manual_evaluation_never_runs_teacher_or_mutates_slide(setup):
    folder, slide, calls = setup
    before = copy.deepcopy(slide)
    result = workflow.evaluate(slide, 'Look at the diagram.', 'local:4b', 'learner', run_folder=folder)
    assert 'candidate' not in result and calls == ['critic']
    assert slide == before
    assert result['evaluation']['script_hash'] == ev.digest('Look at the diagram.')


def test_one_revision_then_reaudit_even_if_findings_remain(setup, monkeypatch):
    folder, slide, calls = setup
    original = ev.evaluate
    def critic(*args, **kwargs):
        result = original(*args, **kwargs)
        result['findings'] = [{'message': 'Needs a check.'}]
        return result
    def revise(model, system, payload, schema, **kwargs):
        calls.append('revision')
        assert payload['evidence_packet']['entries'][0]['text'] == slide['text']
        assert payload['candidate'] == slide['text']
        assert payload['findings']
        return narration.ModelDraft(narration='Look at the diagram.', review_flags=['Still requires review.'])
    monkeypatch.setattr(ev, 'evaluate', critic)
    monkeypatch.setattr(ev, 'local_json', revise)
    result = workflow.run(slide, 'local:4b', 'learner', run_folder=folder)
    assert calls == ['teacher', 'critic', 'revision', 'critic']
    assert result['candidate']['narration'] == 'Look at the diagram.'
    assert result['evaluation']['findings'] and not result['evaluation']['clinical_validation']


def test_failed_critic_can_resume_without_regenerating_teacher(setup, monkeypatch):
    folder, slide, calls = setup
    original = ev.evaluate
    def fail(*args, **kwargs): raise ValueError('Invalid critic JSON')
    monkeypatch.setattr(ev, 'evaluate', fail)
    with pytest.raises(ValueError, match='Invalid critic'):
        workflow.run(slide, 'local:4b', 'learner', run_folder=folder)
    failed = list(folder.glob('*/source_critic.json'))
    assert json.loads(failed[0].read_text())['status'] == 'failed'
    assert not list(folder.glob('*/result.json'))
    monkeypatch.setattr(ev, 'evaluate', original)
    workflow.run(slide, 'local:4b', 'learner', run_folder=folder)
    assert calls == ['teacher', 'critic']


def test_cancel_between_roles_preserves_completed_stage(setup):
    folder, slide, calls = setup
    cancel = threading.Event()
    def progress(percent, message):
        if percent == 50: cancel.set()
    with pytest.raises(media.Cancelled):
        workflow.run(slide, 'local:4b', 'learner', run_folder=folder, cancel=cancel, progress=progress)
    assert calls == ['teacher']
    assert not list(folder.glob('*/result.json'))
    cancel.clear()
    workflow.run(slide, 'local:4b', 'learner', run_folder=folder, cancel=cancel)
    assert calls.count('teacher') == 1


def test_invalid_paths_do_not_write_or_access_model(setup, tmp_path, monkeypatch):
    folder, slide, calls = setup
    def forbidden(*args): pytest.fail('Unexpected model access')
    monkeypatch.setattr(ev, 'resolve_model', forbidden)
    for invalid in [tmp_path / 'outside', folder / '..' / uuid4().hex,
                    tmp_path / uuid4().hex / 'agent-runs' / uuid4().hex]:
        with pytest.raises(ValueError, match='project'):
            workflow.run(slide, 'local:4b', 'learner', run_folder=invalid)


def test_corrupt_checkpoint_is_not_reused(setup):
    folder, slide, calls = setup
    result = workflow.run(slide, 'local:4b', 'learner', run_folder=folder)
    path = folder / result['fingerprint'] / 'teacher.json'
    data = json.loads(path.read_text())
    data['output']['narration'] = 'Altered without updating checksum.'
    path.write_text(json.dumps(data))
    workflow.run(slide, 'local:4b', 'learner', run_folder=folder)
    assert calls.count('teacher') == 2


def test_ocr_review_or_source_conflict_cannot_be_fixed_by_rewriting(setup, monkeypatch):
    folder, slide, calls = setup
    original = ev.evaluate
    def critic(*args, **kwargs):
        result = original(*args, **kwargs)
        result['findings'] = [
            {'origin':'deterministic','category':'source_fidelity','message':'OCR not reviewed.'},
            {'origin':'critic','category':'source_conflict','message':'Author must resolve source disagreement.'}]
        return result
    monkeypatch.setattr(ev, 'evaluate', critic)
    monkeypatch.setattr(ev, 'local_json', lambda *a, **k: pytest.fail('Source approval cannot be repaired by a writer.'))
    result = workflow.run(slide, 'local:4b', 'learner', run_folder=folder)
    assert result['evaluation']['findings']
    assert calls == ['teacher','critic']


def test_revision_new_quantity_retains_original_candidate_and_report(setup, monkeypatch):
    folder, slide, calls = setup
    slide['text'] = 'Use 5 mL.'
    original = ev.evaluate
    def critic(*args, **kwargs):
        result = original(*args, **kwargs)
        result['findings'] = [{'origin':'critic','category':'readability','message':'Simplify.'}]
        return result
    monkeypatch.setattr(ev, 'evaluate', critic)
    monkeypatch.setattr(ev, 'local_json', lambda *a, **k: narration.ModelDraft(narration='Use 10 mL.',review_flags=[]))
    result = workflow.run(slide, 'local:4b', 'learner', run_folder=folder)
    assert result['candidate']['narration'] == 'Use 5 mL.'
    assert result['evaluation']['script_hash'] == ev.digest('Use 5 mL.')
    selection = result['trace'][-1]
    assert selection['decision'] == 'retained_original'
    assert selection['new_diagnostic_issues']['unsupported_numbers'] == ['10']
    attempted = json.loads((folder/result['fingerprint']/'revision_critic.json').read_text())
    assert attempted['output']['script_hash'] == ev.digest('Use 10 mL.')


def test_rejected_critic_raw_attempts_stay_in_private_failed_checkpoint(setup, monkeypatch):
    folder, slide, calls = setup
    attempts=[{'attempt':1,'reason':'Not exact.','raw_response':'private rejected output'}]
    def fail(*args, **kwargs):
        raise ev.CriticValidationError('Critic validation failed.', attempts)
    monkeypatch.setattr(ev,'evaluate',fail)
    with pytest.raises(ev.CriticValidationError):
        workflow.run(slide,'local:4b','learner',run_folder=folder)
    record=json.loads(next(folder.glob('*/source_critic.json')).read_text())
    assert record['status']=='failed' and record['validation_attempts']==attempts
    assert not list(folder.glob('*/result.json'))
