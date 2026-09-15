import json
import threading

import pytest

from backend import evaluation as ev, media


def slide(text='Many items may need 5 mL. Do not discard them.'):
    return {'number': 1, 'revision': 2, 'text': text, 'notes': '', 'tables': []}


def empty_critic(*args, **kwargs):
    return ev.CriticOutput(summary='No additional issue identified; practitioner review remains required.', findings=[])


def test_evidence_stable_ids_and_source_changes():
    packet = ev.build_evidence(slide())
    assert packet == ev.build_evidence(slide())
    changed = ev.build_evidence(slide('Many items may need 6 mL.'))
    assert packet['hash'] != changed['hash']
    assert packet['entries'][0]['id'] != changed['entries'][0]['id']
    revised = ev.build_evidence({**slide(), 'revision': 3})
    assert revised['hash'] == packet['hash']
    assert revised['entries'] == packet['entries']


def test_diagnostics_catch_quantities_qualifiers_negation_without_clinical_pass(monkeypatch):
    monkeypatch.setattr(ev, 'local_json', empty_critic)
    report = ev.evaluate(ev.build_evidence(slide()), 'Most items need 10 mL. Always discard them.', 'local:4b', 'practitioner')
    assert {'many', 'may', 'not'} <= set(report['quality']['missing_source_qualifiers'])
    assert report['quality']['unsupported_numbers'] == ['10']
    assert report['quality']['unsupported_absolutes']
    assert {'quantity', 'qualifier'} <= {f['category'] for f in report['findings']}
    assert report['state'] == 'review_required'
    assert report['clinical_validation'] is False
    assert report['requires_practitioner_review'] is True


def test_empty_findings_never_approve(monkeypatch):
    monkeypatch.setattr(ev, 'local_json', empty_critic)
    report = ev.evaluate(ev.build_evidence(slide('Observe the diagram.')), 'Observe the diagram.', 'local:4b', 'learner')
    assert report['findings'] == []
    assert report['state'] == 'review_required' and not report['clinical_validation']


def test_range_normalization_does_not_hide_changed_units(monkeypatch):
    monkeypatch.setattr(ev, 'local_json', empty_critic)
    packet = ev.build_evidence(slide('Use an 18-20-gauge, 1.5-inch item.'))
    same = ev.evaluate(packet, 'Use an 18 to 20 gauge, 1.5 inch item.', 'local:4b', 'learner')
    assert same['quality']['missing_source_quantities'] == []
    altered = ev.evaluate(packet, 'Use an 18 to 20 gauge, 1.5 cm item.', 'local:4b', 'learner')
    assert altered['quality']['missing_source_quantities']


@pytest.mark.parametrize('mutation', ['source', 'draft', 'id', 'empty'])
def test_fabricated_critic_evidence_rejected(monkeypatch, mutation):
    packet = ev.build_evidence(slide())
    finding = dict(severity='high', category='qualifier', message='Check scope.',
        source_quote='Many items may', draft_quote='Most items',
        evidence_ids=[packet['entries'][0]['id']], remediation='Retain source uncertainty.')
    if mutation == 'source': finding['source_quote'] = 'All items must'
    if mutation == 'draft': finding['draft_quote'] = 'Every item'
    if mutation == 'id': finding['evidence_ids'] = ['made-up']
    if mutation == 'empty': finding.update(source_quote='', draft_quote='')
    monkeypatch.setattr(ev, 'local_json', lambda *a, **k: ev.CriticOutput(summary='Review.', findings=[finding]))
    with pytest.raises(ValueError, match='rejected'):
        ev.evaluate(packet, 'Most items need 5 mL.', 'local:4b', 'learner')


class Response:
    def __init__(self, body): self.body = body
    def raise_for_status(self): pass
    def json(self): return self.body


@pytest.mark.parametrize('body', [{'response': '{broken'}, {'response': '', 'done_reason': 'length'},
                                 {'response': '{}', 'done': False}])
def test_critic_invalid_json_is_failure_not_empty_findings(monkeypatch, body):
    class Client:
        def __init__(self, **kwargs): assert kwargs['trust_env'] is False
        def __enter__(self): return self
        def __exit__(self, *args): pass
        def post(self, url, json):
            assert url == 'http://127.0.0.1:11434/api/generate'
            assert json['think'] is False
            assert json['keep_alive'] == 0
            return Response(body)
    monkeypatch.setattr(ev.httpx, 'Client', Client)
    monkeypatch.setattr(ev, 'resolve_model', lambda *a: {'name': 'local:4b', 'digest': 'abc'})
    with pytest.raises(ValueError, match='No evaluation was accepted'):
        ev.local_json('local:4b', 'Critic.', {}, ev.CriticOutput)


def test_remote_alias_blocked_before_source_transmission(monkeypatch):
    calls = []
    class Client:
        def __init__(self, **kwargs): assert kwargs['trust_env'] is False
        def __enter__(self): return self
        def __exit__(self, *args): pass
        def get(self, url): return Response({'models': [{'name': 'alias:4b', 'digest': 'abc'}]})
        def post(self, url, json):
            calls.append((url, json))
            return Response({'remote_host': 'remote.invalid', 'remote_model': 'cloud-model'})
    monkeypatch.setattr(ev.httpx, 'Client', Client)
    with pytest.raises(ValueError, match='Remote-backed'):
        ev.local_json('alias:4b', 'Critic.', {'source': 'private content'}, ev.CriticOutput)
    assert len(calls) == 1 and calls[0][1] == {'model': 'alias:4b'}


def test_cancel_before_network_and_context_bound(monkeypatch):
    def forbidden(*a, **k): pytest.fail('Unexpected model access')
    monkeypatch.setattr(ev, 'resolve_model', forbidden)
    cancel = threading.Event(); cancel.set()
    with pytest.raises(media.Cancelled):
        ev.local_json('local:4b', 'Critic.', {}, ev.CriticOutput, cancel=cancel)
    with pytest.raises(ValueError, match='too large'):
        ev.local_json('local:4b', 'x' * 40001, {}, ev.CriticOutput)


def test_critic_receives_original_source_without_teacher_reasoning(monkeypatch):
    def critic(model, system, payload, schema, **kwargs):
        assert payload['evidence_packet']['entries'][0]['text'] == slide()['text']
        assert payload['candidate'] == 'Most items need 5 mL.'
        assert 'teacher_reasoning' not in json.dumps(payload)
        return empty_critic()
    monkeypatch.setattr(ev, 'local_json', critic)
    ev.evaluate(ev.build_evidence(slide()), 'Most items need 5 mL.', 'local:4b', 'learner')


def test_source_transcription_and_readability_are_distinct_findings(monkeypatch):
    monkeypatch.setattr(ev, 'local_json', empty_critic)
    text = ' '.join(['Observe'] * 30) + '.'
    packet = ev.build_evidence({**slide(text), 'visual_text': 'The source label.', 'source_reviewed': False})
    report = ev.evaluate(packet, text, 'local:4b', 'learner')
    categories = {f['category'] for f in report['findings']}
    assert {'readability', 'source_fidelity'} <= categories
    transcription = next(f for f in report['findings'] if f['category'] == 'source_fidelity')
    assert transcription['source_quote'] == 'The source label.'
    ev.validate_quotes(report['findings'], packet, text)


def test_ollama_transport_avoids_large_string_grammar_but_validates_output(monkeypatch):
    original = ev.CriticOutput.model_json_schema()
    wire = ev.transport_schema(ev.CriticOutput)
    assert 'maxLength' not in json.dumps(wire)
    assert wire['required'] == original['required']
    assert wire['$defs']['Finding']['properties']['severity']['enum'] == ['high','medium','low']
    assert wire['properties']['findings']['maxItems'] == 30
    assert 'maxLength' in json.dumps(original)
    class Client:
        def __init__(self, **kwargs): pass
        def __enter__(self): return self
        def __exit__(self, *args): pass
        def post(self, url, json):
            assert 'maxLength' not in str(json['format'])
            return Response({'response': __import__('json').dumps({'summary':'x'*2001,'findings':[]}), 'done': True})
    monkeypatch.setattr(ev.httpx, 'Client', Client)
    monkeypatch.setattr(ev, 'resolve_model', lambda *a: {'name':'local:4b','digest':'abc'})
    with pytest.raises(ValueError, match='No evaluation was accepted'):
        ev.local_json('local:4b', 'Critic.', {}, ev.CriticOutput)


@pytest.mark.parametrize('failure', ['quote','schema'])
def test_one_critic_validation_repair_receives_original_inputs(monkeypatch, failure):
    packet=ev.build_evidence(slide())
    calls=[]
    def critic(model,system,payload,schema,**kwargs):
        calls.append(payload)
        if len(calls)==1:
            if failure=='schema':
                raise ev.ModelOutputError('Bad JSON','{broken','Expected a JSON object')
            return ev.CriticOutput(summary='Check.',findings=[dict(severity='high',category='qualifier',
                message='Check.',source_quote='All items must',draft_quote='',
                evidence_ids=[packet['entries'][0]['id']],remediation='Check scope.')])
        assert system==ev.CRITIC_REPAIR_SYSTEM
        assert payload['candidate']==slide()['text']
        assert payload['evidence_packet']==calls[0]['evidence_packet']
        assert payload['rejected_response'] and payload['validation_error']
        return empty_critic()
    monkeypatch.setattr(ev,'local_json',critic)
    report=ev.evaluate(packet,slide()['text'],'local:4b','learner')
    assert len(calls)==2
    assert report['critic_validation_attempts']==2 and report['validation_repair_used']
    assert report['clinical_validation'] is False


def test_two_invalid_critic_responses_stop_and_preserve_private_failure(monkeypatch):
    calls=[]
    def critic(*args,**kwargs):
        calls.append(1)
        raise ev.ModelOutputError('Bad JSON','{broken','Expected JSON')
    monkeypatch.setattr(ev,'local_json',critic)
    with pytest.raises(ev.CriticValidationError) as caught:
        ev.evaluate(ev.build_evidence(slide()),slide()['text'],'local:4b','learner')
    assert len(calls)==2 and len(caught.value.validation_attempts)==2
    assert caught.value.validation_attempts[0]['raw_response']=='{broken'


def test_cancel_after_invalid_critic_does_not_request_repair(monkeypatch):
    cancel=threading.Event()
    calls=[]
    def critic(*args,**kwargs):
        calls.append(1); cancel.set()
        raise ev.ModelOutputError('Bad JSON','{broken','Expected JSON')
    monkeypatch.setattr(ev,'local_json',critic)
    with pytest.raises(media.Cancelled):
        ev.evaluate(ev.build_evidence(slide()),slide()['text'],'local:4b','learner',cancel=cancel)
    assert len(calls)==1
