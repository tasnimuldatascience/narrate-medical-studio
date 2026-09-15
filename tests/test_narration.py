import json

import pytest

from backend import narration


def source(text='',notes='',tables=None):
    return {'text':text,'notes':notes,'tables':tables or []}


def test_reference_numbers_are_excluded_from_semantic_context_and_checks():
    slide=source('Use 5 mL. PMID: 12345678',
        'Keep the label. [Sources]\n2024 article PMID 98765432 https://example.invalid/88\n[/Sources]\nDo not discard it.')
    cleaned=narration.prepare_source(slide)
    serialized=json.dumps(cleaned)
    for value in ['12345678','2024','98765432','https://','88']:
        assert value not in serialized
    quality=narration.assess_quality('Use 5 mL. Keep the label; do not discard it.',slide)
    assert quality['missing_source_numbers']==[]
    assert quality['missing_source_quantities']==[]
    quality=narration.assess_quality('Use 88 mL.',slide)
    assert quality['unsupported_numbers']==['88']


def test_missing_quantities_and_changed_units_are_reported():
    quality=narration.assess_quality('Use 5 mg.',source('Use 5 mL. Wait 10 minutes.'))
    assert quality['missing_source_numbers']==['10']
    assert quality['missing_source_quantities']==['10minutes','5ml']
    assert quality['unsupported_numbers']==[]
    assert 'not clinical verification' in quality['diagnostic_scope']


def test_quantities_tolerate_spacing_and_ignore_list_enumeration():
    quality=narration.assess_quality('Use 5mL. Wait 10 minutes.',source('1. Use 5 mL.\n2. Wait 10 minutes.'))
    assert not quality['unsupported_numbers']
    assert not quality['missing_source_numbers']
    assert not quality['missing_source_quantities']


def test_table_values_checked_and_excessively_long_sentences_detected():
    quality=narration.assess_quality(' '.join(['word']*28)+'.',source(tables=[[['Quantity','5 mL']]]))
    assert quality['long_sentence_count']==1
    assert quality['longest_sentence_words']==28
    assert quality['missing_source_numbers']==['5']
    quality=narration.assess_quality('Use 1.5 mL. Keep the label.',source('Use 1.5 mL. Keep the label.'))
    assert quality['sentence_count']==2
    assert quality['missing_source_numbers']==[]


def test_oversized_context_rejected_without_silent_truncation():
    with pytest.raises(ValueError,match='Split it'):
        narration.prepare_source(source('important '*2000))


def test_generate_keeps_local_style_contract_and_adds_diagnostics(monkeypatch):
    calls=[]
    class Response:
        def __init__(self,payload):self.payload=payload
        def raise_for_status(self):pass
        def json(self):return self.payload
    class Client:
        def __init__(self,**kwargs):assert kwargs['trust_env'] is False
        def __enter__(self):return self
        def __exit__(self,*args):pass
        def get(self,url):return Response({'models':[{'name':'local-model'}]})
        def post(self,url,json):
            calls.append((url,json))
            if url.endswith('/api/show'):
                return Response({})
            return Response({'response':'{"narration":"Use 7 mL.","review_flags":["Review the source."]}'})
    monkeypatch.setattr(narration.httpx,'Client',Client)
    draft=narration.generate({**source('Use 5 mL.',notes='[Sources]PMID 7[/Sources]'),
                              'visual_text':'Use 5 mL.','source_reviewed':False},
                             'local-model','Practitioners',style='concise')
    assert draft.quality['unsupported_numbers']==['7']
    assert draft.quality['missing_source_numbers']==['5']
    assert any('absent from the source' in flag for flag in draft.review_flags)
    assert any('transcription has not been reviewed' in flag for flag in draft.review_flags)
    generation=calls[-1][1]
    payload=json.loads(generation['prompt'])
    assert payload['delivery_style']=='concise'
    assert 'PMID' not in generation['prompt']
    assert 'quality' not in generation['format']['properties']
    assert '<nonmedical_editing_examples>' in generation['system']
    assert 'usually, only, before, and after' in generation['system']
    # The pre-existing three-argument interface remains supported.
    narration.generate(source('Use 5 mL.'),'local-model','Practitioners')
    assert json.loads(calls[-1][1]['prompt'])['delivery_style']=='conversational'


def test_invalid_style_rejected_before_model_access():
    with pytest.raises(ValueError,match='conversational or concise'):
        narration.generate(source('Hello'),'local-model','Practitioners','dramatic')


def test_image_transcription_is_retained_as_separate_bounded_evidence():
    slide={**source('A heading','Use the smaller container.'),
           'visual_text':'Use the larger container. Capacity: 20 mL. PMID 111111',
           'source_reviewed':False}
    cleaned=narration.prepare_source(slide)
    assert cleaned['notes']=='Use the smaller container.'
    assert '20 mL' in cleaned['image_text']
    assert '111111' not in cleaned['image_text']
    assert narration.prepare_source(cleaned)==cleaned
    quality=narration.assess_quality('Use the smaller container.',slide)
    assert quality['missing_source_numbers']==['20']
    assert quality['image_text_present'] is True
    assert quality['source_reviewed'] is False
    assert 'Do not silently prefer notes over image_text' in narration.SYSTEM
    with pytest.raises(ValueError,match='Split it'):
        narration.prepare_source({**slide,'visual_text':'OCR '*4000})


def test_hyphenated_gauge_and_inch_quantities_are_checked():
    # Equipment notation observed in the supplied slide; no clinical inference.
    slide=source('18–20-gauge; 1.5-inch')
    matching=narration.assess_quality('18–20 gauge; 1.5 inch',slide)
    assert matching['missing_source_quantities']==[]
    changed=narration.assess_quality('18–20 gauge; 1.5 cm',slide)
    assert changed['missing_source_quantities']==['1.5inch']


@pytest.mark.parametrize('original,draft,missing',[
    ('A larger-bore needle is usually needed for thick aspirate.',
     'A larger-bore needle handles thick aspirate better.','usually'),
    ('A smaller needle is adequate for many injections.',
     'A smaller needle is adequate for most injections.','many'),
    ('Aspiration can reduce pressure.','Aspiration lowers pressure.','can'),
    ('Infection should be reasonably excluded.','Infection should be ruled out.','reasonably'),
    ('Suspected infection may need review.','Infection needs review.','suspected'),
])
def test_dropped_qualifiers_signal_claim_strength_changes(original,draft,missing):
    # Observed rewrite failures, tested as lexical diagnostics, not clinical rules.
    quality=narration.assess_quality(draft,source(original))
    assert missing in quality['missing_source_qualifiers']
    assert 'not clinical verification' in quality['diagnostic_scope']


def test_new_absolutes_are_flagged_but_existing_source_absolutes_are_not():
    quality=narration.assess_quality('Always check the label. This guarantees a result.',
                                   source('Check the label.'))
    assert quality['unsupported_absolutes']==['always','guarantees']
    assert narration.assess_quality('Never discard the label.',
        source('Never discard the label.'))['unsupported_absolutes']==[]


def test_preserved_qualifiers_and_contracted_negation_do_not_raise_omission():
    quality=narration.assess_quality("This can usually help many cases. Don't discard the label.",
        source('This can usually help many cases. Do not discard the label.'))
    assert quality['missing_source_qualifiers']==[]


def mock_two_pass_model(monkeypatch,metadata,outputs):
    calls=[]
    remaining=iter(outputs)
    class Response:
        def __init__(self,payload):self.payload=payload
        def raise_for_status(self):pass
        def json(self):return self.payload
    class Client:
        def __init__(self,**kwargs):
            assert kwargs['trust_env'] is False
        def __enter__(self):return self
        def __exit__(self,*args):pass
        def get(self,url):
            assert url=='http://127.0.0.1:11434/api/tags'
            return Response({'models':[{'name':'local-model'}]})
        def post(self,url,json):
            assert url.startswith('http://127.0.0.1:11434/')
            calls.append((url,json))
            if url.endswith('/api/show'):
                return Response(metadata)
            result=next(remaining)
            if callable(result):
                result=result()
            if isinstance(result,Exception):
                raise result
            return Response(result if isinstance(result,dict) else {'response':result})
    monkeypatch.setattr(narration.httpx,'Client',Client)
    return calls


def test_editor_receives_original_evidence_first_draft_and_diagnostics(monkeypatch):
    first={'narration':'Use 7 mL. It helps.','review_flags':['Check the uncertain wording.']}
    final={'narration':'Use 5 mL. It may help.','review_flags':[]}
    calls=mock_two_pass_model(monkeypatch,{'capabilities':['completion','thinking']},
        [json.dumps(first),json.dumps(final)])
    slide={**source('Use 5 mL.','It may help. [Sources]PMID 7654321[/Sources]'),
           'visual_text':'Use 5 mL.','source_reviewed':True}
    draft=narration.generate(slide,'local-model','Practitioners',style='concise')
    assert len(calls)==3
    editor=calls[-1][1]
    payload=json.loads(editor['prompt'])
    assert payload['source']==narration.prepare_source(slide)
    assert payload['first_draft']==first
    assert payload['diagnostics']['unsupported_numbers']==['7']
    assert payload['diagnostics']['missing_source_qualifiers']==['may']
    assert payload['delivery_style']=='concise'
    assert '7654321' not in editor['prompt']
    assert editor['system']==narration.EDITOR
    assert draft.narration==final['narration']
    assert draft.quality['unsupported_numbers']==[]
    assert draft.quality['missing_source_qualifiers']==[]


@pytest.mark.parametrize('capabilities',[
    ['completion','thinking'],['completion'],[],None])
def test_both_passes_disable_thinking_even_when_model_advertises_it(monkeypatch,capabilities):
    response=json.dumps({'narration':'Keep the source.','review_flags':[]})
    calls=mock_two_pass_model(monkeypatch,{'capabilities':capabilities},[response,response])
    narration.generate(source('Keep the source.'),'local-model','Practitioners')
    assert calls[1][1]['think'] is False
    assert calls[2][1]['think'] is False
    assert calls[2][1]['options']['num_predict']==3500
    assert calls[2][1]['options']['num_ctx']==16384


@pytest.mark.parametrize('metadata',[
    {'remote_host':'https://remote.invalid'},
    {'remote_model':'remote-name'},
    {'modelfile':'FROM remote-model:cloud\nPARAMETER temperature 0'},
])
def test_remote_alias_rejected_before_either_pass_receives_source(monkeypatch,metadata):
    calls=mock_two_pass_model(monkeypatch,metadata,[])
    with pytest.raises(ValueError,match='Remote-backed'):
        narration.generate(source('Private supplied source phrase.'),'local-model','Practitioners')
    assert len(calls)==1 and calls[0][0].endswith('/api/show')
    assert calls[0][1]=={'model':'local-model'}
    assert 'Private supplied source phrase' not in json.dumps(calls)


def test_spoken_range_normalization_preserves_equivalence_but_detects_changes():
    slide=source('Use an 18–20-gauge item measuring 1.5-inch.')
    equivalent=narration.assess_quality('Use an 18 to 20 gauge item measuring 1.5 inch.',slide)
    assert equivalent['unsupported_numbers']==[]
    assert equivalent['missing_source_numbers']==[]
    assert equivalent['missing_source_quantities']==[]
    suspended=narration.assess_quality('Use an 18- to 20-gauge item measuring 1.5-inch.',slide)
    assert suspended['unsupported_numbers']==[]
    assert suspended['missing_source_quantities']==[]
    units=narration.assess_quality('Use an 18 to 20 mm item measuring 1.5 cm.',slide)
    assert set(units['missing_source_quantities'])=={'18-20gauge','1.5inch'}
    changed=narration.assess_quality('Use a 19 to 20 gauge item measuring 1.5 inch.',slide)
    assert changed['unsupported_numbers']==['19-20']
    assert changed['missing_source_numbers']==['18-20']


def test_editor_failure_does_not_return_unreviewed_first_pass(monkeypatch):
    first=json.dumps({'narration':'A first pass only.','review_flags':[]})
    calls=mock_two_pass_model(monkeypatch,{},[first,RuntimeError('Editor request failed')])
    with pytest.raises(RuntimeError,match='Editor request failed'):
        narration.generate(source('A first pass only.'),'local-model','Practitioners')
    assert len(calls)==3


def test_invalid_first_pass_json_stops_before_editor(monkeypatch):
    calls=mock_two_pass_model(monkeypatch,{},['not valid JSON'])
    with pytest.raises(ValueError):
        narration.generate(source('Keep the source.'),'local-model','Practitioners')
    assert len(calls)==2


@pytest.mark.parametrize('response,message',[
    ({'response':'','done':True},'no narration'),
    ({'response':' ','done':True},'no narration'),
    ({'response':'{}','done':False},'stopped before finishing'),
    ({'response':'{"narration":"A partial answer.","review_flags":[]}',
      'done':True,'done_reason':'length'},'stopped before finishing'),
    ({'response':'{"narration":" " ,"review_flags":[]}','done':True},'blank narration'),
    ({'response':'{"narration":','done':True},'incomplete or invalid'),
])
def test_incomplete_editor_response_has_clear_failure_without_fallback(monkeypatch,response,message):
    first=json.dumps({'narration':'Keep the source.','review_flags':[]})
    mock_two_pass_model(monkeypatch,{},[first,response])
    with pytest.raises(ValueError,match=message):
        narration.generate(source('Keep the source.'),'local-model','Practitioners')


def test_cancelled_generation_does_not_start_editor(monkeypatch):
    import threading
    from backend.media import Cancelled
    cancel=threading.Event()
    def complete_first_pass():
        cancel.set()
        return json.dumps({'narration':'Keep the source.','review_flags':[]})
    calls=mock_two_pass_model(monkeypatch,{},[complete_first_pass])
    with pytest.raises(Cancelled):
        narration.generate(source('Keep the source.'),'local-model','Practitioners',cancel=cancel)
    assert len(calls)==2


def test_already_cancelled_request_does_not_access_model(monkeypatch):
    import threading
    from backend.media import Cancelled
    cancel=threading.Event()
    cancel.set()
    def client(**kwargs):
        pytest.fail('An already-cancelled request must not initialize HTTP access.')
    monkeypatch.setattr(narration.httpx,'Client',client)
    with pytest.raises(Cancelled):
        narration.generate(source('Keep the source.'),'local-model','Practitioners',cancel=cancel)


def test_combined_editor_context_is_bounded_without_silent_truncation(monkeypatch):
    first=json.dumps({'narration':'Draft sentence. '*500,'review_flags':['Reviewer note. '*100]*20})
    calls=mock_two_pass_model(monkeypatch,{},[first])
    with pytest.raises(ValueError,match='combined source, draft, and diagnostics'):
        narration.generate(source('Source sentence. '*500),'local-model','Practitioners')
    assert len(calls)==2
