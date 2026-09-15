"""Synthetic source-fidelity failure classes; no clinical-certification claims."""
import threading

import pytest

from backend import evaluation as ev, evidence_review as review, media


def packet(text):
    return ev.build_evidence({'number':1,'revision':1,'text':text,'notes':'','tables':[]})


def alignment(source,draft,status='covered'):
    return review.Alignment(source_checks=[dict(source_id=p['id'],status=status,
        draft_ids=[draft[min(i,len(draft)-1)]['id']],related_source_ids=[],reason='Compare the complete statement.')
        for i,p in enumerate(source)], draft_checks=[dict(draft_id=p['id'],status='supported',
        source_ids=[source[min(i,len(source)-1)]['id']],reason='The source supplies this statement.')
        for i,p in enumerate(draft)])


def install(monkeypatch,align,verdict_factory=None):
    calls=[]
    def local(model,system,payload,schema,**kwargs):
        calls.append((schema,payload))
        if issubclass(schema,review.Alignment):
            return align
        assert issubclass(schema,review.Verification)
        assert verdict_factory is not None
        return review.Verification(verdicts=verdict_factory(payload))
    monkeypatch.setattr(ev,'local_json',local)
    return calls


def verdict(payload,decision='confirmed',**overrides):
    return [dict(proposal_id=p['id'],decision=decision,source_ids=p['source_ids'],
                 draft_ids=p['draft_ids'],reason='Compare the cited wording.',**overrides)
            for p in payload['proposals']]


@pytest.mark.parametrize('source_text,script',[
    ('Measure 5 mL.','Measure 5 mg.'),
    ('Do not discard the sample.','Discard the sample.'),
    ('Many items may require adjustment.','Most items always require adjustment.')])
def test_changed_units_negation_and_qualifiers_keep_exact_immutable_quotes(monkeypatch,source_text,script):
    evidence=packet(source_text);source,draft=review.passages(evidence,script)
    calls=install(monkeypatch,alignment(source,draft,'changed'),verdict)
    result=review.run(ev,evidence,script,'local:model','learner')
    assert len(calls)==3
    assert result['model_call_count']==3 and result['stage_count']==3
    finding=result['findings'][0]
    assert finding['source_quote']==source_text and finding['draft_quote']==script
    assert finding['auto_revision_allowed'] is False
    assert finding['verification']=='two_pass_model_agreement'
    assert 'may have changed' in finding['message']
    ev.validate_quotes(result['findings'],evidence,script)


def test_exact_existing_claim_falsely_omitted_is_dismissed_without_verifier(monkeypatch):
    source_text='The label remains attached.'
    script='First observe the diagram. The label remains attached.'
    evidence=packet(source_text);source,draft=review.passages(evidence,script)
    calls=install(monkeypatch,alignment(source,draft,'omitted'))
    result=review.run(ev,evidence,script,'local:model','learner')
    assert result['findings']==[] and len(calls)==2
    assert result['model_call_count']==2 and result['stage_count']==2
    assert result['dismissed'][0]['verification']=='exact_text_present'


def test_spoken_range_omission_requires_visible_semantic_refutation(monkeypatch):
    evidence=packet('Use 18-20 items.');script='Use 18 to 20 items.'
    source,draft=review.passages(evidence,script)
    calls=install(monkeypatch,alignment(source,draft,'omitted'),lambda p:verdict(p,'refuted'))
    result=review.run(ev,evidence,script,'local:model','learner')
    assert len(calls)==3 and result['findings']==[]
    assert result['dismissed'][0]['decision']=='refuted'
    assert result['dismissed'][0].get('verification')!='exact_text_present'


def test_passage_offsets_reproduce_exact_source_and_draft_substrings():
    evidence=packet('  Measure 1.5 mL.\nKeep the label.  ')
    script='Measure 1.5 mL. Keep the label.'
    source,draft=review.passages(evidence,script)
    entries={e['id']:e['text'] for e in evidence['entries']}
    assert len(source)==2 and len(draft)==2
    for p in source: assert entries[p['evidence_id']][p['start']:p['end']]==p['text']
    for p in draft: assert script[p['start']:p['end']]==p['text']
    assert source[0]['text']=='Measure 1.5 mL.'


@pytest.mark.parametrize('fault',['missing_source','duplicate_source','missing_draft','duplicate_draft',
    'unknown_draft','unknown_related_source','duplicate_related_source','unknown_source','duplicate_source_ref'])
def test_invalid_ids_or_incomplete_alignment_rejected(fault):
    source,draft=review.passages(packet('Observe it. Keep it.'),'Observe it. Keep it.')
    obj=alignment(source,draft)
    if fault=='missing_source':obj.source_checks.pop()
    if fault=='duplicate_source':obj.source_checks[1]=obj.source_checks[0]
    if fault=='missing_draft':obj.draft_checks.pop()
    if fault=='duplicate_draft':obj.draft_checks[1]=obj.draft_checks[0]
    if fault=='unknown_draft':obj.source_checks[0].draft_ids=['d999']
    if fault=='unknown_related_source':obj.source_checks[0].related_source_ids=['s999']
    if fault=='duplicate_related_source':obj.source_checks[0].related_source_ids=['s2','s2']
    if fault=='unknown_source':obj.draft_checks[0].source_ids=['s999']
    if fault=='duplicate_source_ref':obj.draft_checks[0].source_ids=['s1','s1']
    with pytest.raises(ValueError,match='rejected'):
        review.validate_alignment(obj,source,draft)


def test_source_conflict_requires_distinct_source_passages():
    source,draft=review.passages(packet('Keep it. Discard it.'),'Review the source.')
    obj=alignment(source,draft)
    obj.source_checks[0].status='conflict'
    obj.source_checks[0].related_source_ids=['s1']
    with pytest.raises(ValueError,match='two distinct'):
        review.validate_alignment(obj,source,draft)


@pytest.mark.parametrize('decision',['refuted','uncertain'])
def test_verifier_refutation_or_uncertainty_never_becomes_confirmed_finding(monkeypatch,decision):
    evidence=packet('Retain the label.');script='Keep the label attached.'
    source,draft=review.passages(evidence,script)
    install(monkeypatch,alignment(source,draft,'omitted'),lambda p:verdict(p,decision))
    result=review.run(ev,evidence,script,'local:model','learner')
    assert result['findings']==[]
    assert result['dismissed' if decision=='refuted' else 'uncertain'][0]['decision']==decision


def verification_fixture(kind='changed'):
    source,draft=review.passages(packet('Keep it. Discard it. Observe it.'),'Keep it. Inspect it.')
    proposals=[{'id':'p1','type':kind,'source_ids':['s1'],'draft_ids':['d1']}]
    valid=dict(proposal_id='p1',decision='confirmed',source_ids=['s1'],draft_ids=['d1'],reason='Compare the wording.')
    return source,draft,proposals,valid


@pytest.mark.parametrize('fault',['missing','duplicate','unknown_proposal','unknown_source','unknown_draft','source_replaced'])
def test_verifier_invalid_coverage_and_changed_source_anchors_rejected(fault):
    source,draft,proposals,valid=verification_fixture()
    if fault=='unknown_proposal':valid['proposal_id']='p2'
    if fault=='unknown_source':valid['source_ids']=['s999']
    if fault=='unknown_draft':valid['draft_ids']=['d999']
    if fault=='source_replaced':valid['source_ids']=['s2']
    values=[] if fault=='missing' else [valid,valid] if fault=='duplicate' else [valid]
    with pytest.raises(ValueError,match='rejected'):
        review.validate_verification(review.Verification(verdicts=values),proposals,source,draft)


def test_verifier_cannot_change_draft_side_of_changed_claim():
    source,draft,proposals,valid=verification_fixture()
    valid['draft_ids']=['d2']
    with pytest.raises(ValueError,match='rejected'):
        review.validate_verification(review.Verification(verdicts=[valid]),proposals,source,draft)


def test_verifier_cannot_replace_one_side_of_proposed_source_conflict():
    source,draft,proposals,valid=verification_fixture('conflict')
    proposals[0]['source_ids']=['s1','s2']
    valid['source_ids']=['s1','s3']
    with pytest.raises(ValueError,match='rejected'):
        review.validate_verification(review.Verification(verdicts=[valid]),proposals,source,draft)


def test_unsupported_claim_confirmation_retains_original_draft_anchor():
    source,draft,proposals,valid=verification_fixture('unsupported')
    valid['draft_ids']=['d2']
    with pytest.raises(ValueError,match='changed the draft'):
        review.validate_verification(review.Verification(verdicts=[valid]),proposals,source,draft)


def test_refuted_omission_requires_a_matching_draft_anchor():
    source,draft,proposals,valid=verification_fixture('omitted')
    valid.update(decision='refuted',draft_ids=[])
    with pytest.raises(ValueError,match='Refuted omission'):
        review.validate_verification(review.Verification(verdicts=[valid]),proposals,source,draft)


def test_unresolved_alignment_is_visible_without_model_confirmation(monkeypatch):
    evidence=packet('Inspect the marked item.');script='Look at this.'
    source,draft=review.passages(evidence,script)
    obj=alignment(source,draft,'uncertain');obj.draft_checks[0].status='uncertain'
    calls=install(monkeypatch,obj)
    result=review.run(ev,evidence,script,'local:model','learner')
    assert len(result['uncertain'])==2 and result['findings']==[] and len(calls)==2


def test_cancel_before_verifier_makes_no_second_model_call(monkeypatch):
    evidence=packet('Keep the label.');script='Discard the label.'
    source,draft=review.passages(evidence,script)
    cancel=threading.Event();calls=[]
    def local(*args,**kwargs):
        calls.append(1);cancel.set();return alignment(source,draft,'changed')
    monkeypatch.setattr(ev,'local_json',local)
    with pytest.raises(media.Cancelled):
        review.run(ev,evidence,script,'local:model','learner',cancel=cancel)
    assert len(calls)==1


@pytest.mark.parametrize('kind',['changed','unsupported','conflict'])
def test_refutation_cannot_dismiss_proposal_without_evidence(kind):
    source,draft,proposals,valid=verification_fixture(kind)
    if kind=='conflict':proposals[0]['source_ids']=['s1','s2']
    valid.update(decision='refuted',source_ids=[],draft_ids=[])
    with pytest.raises(ValueError,match='rejected'):
        review.validate_verification(review.Verification(verdicts=[valid]),proposals,source,draft)


def test_source_and_draft_are_wholly_available_to_verifier(monkeypatch):
    evidence=packet('The first item has a label. Keep the second item.');script='The first item has a label. Retain the second item.'
    source,draft=review.passages(evidence,script)
    obj=alignment(source,draft);obj.source_checks[1].status='omitted'
    def verification(payload):
        assert payload['source_passages']==source and payload['draft_passages']==draft
        assert payload['proposals'][0]['source_ids']==['s2']
        return verdict(payload,'refuted')
    install(monkeypatch,obj,verification)
    result=review.run(ev,evidence,script,'local:model','learner')
    assert result['findings']==[] and len(result['dismissed'])==1


def test_case_sensitive_units_are_not_treated_as_exact_existing_claim(monkeypatch):
    evidence=packet('Measure 5 mW.');script='Measure 5 MW.'
    source,draft=review.passages(evidence,script)
    calls=install(monkeypatch,alignment(source,draft,'omitted'),verdict)
    result=review.run(ev,evidence,script,'local:model','learner')
    assert len(calls)==3
    assert result['dismissed']==[]
    assert result['findings'][0]['source_quote']=='Measure 5 mW.'
    assert result['findings'][0]['draft_quote']=='Measure 5 MW.'


def test_oversized_evidence_fails_before_any_model_or_transport_access(monkeypatch):
    def forbidden(*args,**kwargs):
        pytest.fail('An oversized source must not be sent to the model.')
    monkeypatch.setattr(ev,'resolve_model',forbidden)
    monkeypatch.setattr(ev.httpx,'Client',forbidden)
    with pytest.raises(ValueError,match='complete evidence cannot fit'):
        ev.local_json('local:model','Review the complete source.',{'source':'x'*14000},
            review.Alignment,options={'num_ctx':16384,'num_predict':10000})


def test_fitting_context_caps_generation_without_mutating_config(monkeypatch):
    configured={'num_ctx':16384,'num_predict':10000,'seed':73}
    class Response:
        def raise_for_status(self):pass
        def json(self):return {'done':True,'response':'{"source_checks":[],"draft_checks":[]}'}
    class Client:
        def __init__(self,**kwargs):assert kwargs['trust_env'] is False
        def __enter__(self):return self
        def __exit__(self,*args):pass
        def post(self,url,json):
            bound=len((json['system']+json['prompt']).encode('utf-8'))+1024
            assert 2000<=json['options']['num_predict']<10000
            assert bound+json['options']['num_predict']<=16384
            assert json['options']['seed']==73
            return Response()
    monkeypatch.setattr(ev,'resolve_model',lambda *a:{'name':'local:model','digest':'test'})
    monkeypatch.setattr(ev.httpx,'Client',Client)
    ev.local_json('local:model','Review.',{'source':'x'*7000},review.Alignment,options=configured)
    assert configured=={'num_ctx':16384,'num_predict':10000,'seed':73}


def test_blind_alignment_finds_claim_first_reviewer_marked_covered(monkeypatch):
    evidence=packet('Do not discard the sample.');script='Discard the sample.'
    source,draft=review.passages(evidence,script)
    align_calls=[]
    def local(model,system,payload,schema,**kwargs):
        if issubclass(schema,review.Alignment):
            align_calls.append((system,payload,kwargs['options']))
            if len(align_calls)==1:return alignment(source,draft,'covered')
            assert system==review.BLIND_SYSTEM
            assert payload==align_calls[0][1]
            assert set(payload)=={'audience','source_passages','draft_passages'}
            assert kwargs['options']['seed']!=align_calls[0][2]['seed']
            return alignment(source,draft,'changed')
        return review.Verification(verdicts=verdict(payload))
    monkeypatch.setattr(ev,'local_json',local)
    result=review.run(ev,evidence,script,'local:model','learner')
    assert len(align_calls)==2
    assert len(result['findings'])==1
    assert result['findings'][0]['kind']=='changed'
    assert result['findings'][0]['auto_revision_allowed'] is False


def runtime_fixture():
    source,draft=review.passages(packet('Keep the label. Inspect the item.'),'Retain the label. Inspect the item.')
    data=alignment(source,draft).model_dump()
    for check in [*data['source_checks'],*data['draft_checks']]:
        check.pop('reason');check.pop('status');check['comparison']='Meaning retained'
    return source,draft,data


def test_runtime_schema_binds_namespace_enums_counts_and_field_order():
    source,draft,data=runtime_fixture()
    schema=review.alignment_schema(source,draft)
    assert issubclass(schema,review.Alignment)
    schema.model_validate(data)
    wire=ev.transport_schema(schema)
    source_fields=wire['$defs']['BoundSourceCheck']['properties']
    draft_fields=wire['$defs']['BoundDraftCheck']['properties']
    assert source_fields['source_id']['enum']==['s1','s2']
    assert source_fields['related_source_ids']['items']['enum']==['s1','s2']
    assert source_fields['draft_ids']['items']['enum']==['d1','d2']
    assert draft_fields['source_ids']['items']['enum']==['s1','s2']
    assert set(source_fields['comparison']['enum'])==set(review.SOURCE_COMPARISONS)
    assert set(draft_fields['comparison']['enum'])==set(review.DRAFT_COMPARISONS)
    assert 'reason' not in source_fields and 'status' not in source_fields
    assert 'reason' not in draft_fields and 'status' not in draft_fields
    assert list(source_fields)[-1]=='comparison'
    for key in ['source_checks','draft_checks']:
        assert wire['properties'][key]['minItems']==wire['properties'][key]['maxItems']==2


@pytest.mark.parametrize('collection,key,value',[
    ('source_checks','source_id','d1'),('source_checks','source_id','s999'),
    ('source_checks','draft_ids',['s1']),('source_checks','related_source_ids',['d1']),
    ('draft_checks','draft_id','s1'),('draft_checks','source_ids',['d1'])])
def test_runtime_alignment_rejects_wrong_namespace_or_invented_id(collection,key,value):
    source,draft,data=runtime_fixture()
    data[collection][0][key]=value
    with pytest.raises(ValueError,match='Input should be'):
        review.alignment_schema(source,draft).model_validate(data)


@pytest.mark.parametrize('collection,reason,status',[
    ('source_checks','Meaning retained','changed'),
    ('source_checks','Claim not found','covered'),
    ('source_checks','Quantity differs','uncertain'),
    ('draft_checks','Claim not supported','supported'),
    ('draft_checks','Meaning retained','unsupported')])
def test_runtime_rejects_legacy_contradictory_fields_instead_of_correcting(collection,reason,status):
    source,draft,data=runtime_fixture()
    data[collection][0].update(reason=reason,status=status)
    with pytest.raises(ValueError,match='Extra inputs are not permitted'):
        review.alignment_schema(source,draft).model_validate(data)


def test_runtime_reason_is_finite_but_domain_model_remains_compatible():
    source,draft,data=runtime_fixture()
    alignment(source,draft) # Existing domain reasons remain compatible.
    data['source_checks'][0]['comparison']='A long and unnecessary speculative discussion.'
    with pytest.raises(ValueError,match='Input should be'):
        review.alignment_schema(source,draft).model_validate(data)


@pytest.mark.parametrize('collection,mapping',[
    ('source_checks',review.SOURCE_COMPARISONS),('draft_checks',review.DRAFT_COMPARISONS)])
def test_single_comparison_decodes_exactly_one_domain_status(collection,mapping):
    source,draft,data=runtime_fixture()
    schema=review.alignment_schema(source,draft)
    for comparison,status in mapping.items():
        data[collection][0]['comparison']=comparison
        decoded=review.domain_alignment(schema.model_validate(data))
        check=getattr(decoded,collection)[0]
        assert check.status==status and check.reason==comparison
    assert 'comparison' not in decoded.model_dump()[collection][0]


@pytest.mark.parametrize('collection,comparison',[
    ('source_checks','Claim not supported'),('draft_checks','Claim not found'),
    ('draft_checks','Conflicting sources')])
def test_role_inappropriate_comparison_rejected(collection,comparison):
    source,draft,data=runtime_fixture()
    data[collection][0]['comparison']=comparison
    with pytest.raises(ValueError):review.alignment_schema(source,draft).model_validate(data)


def test_comparison_contract_is_explicit_in_both_prompts():
    for system in (review.ALIGN_SYSTEM,review.BLIND_SYSTEM):
        assert 'NO reason or status fields' in system
        for comparison in review.COMPARISON_REASONS:assert comparison in system
        assert 'not just because the passage' in system


def test_wire_difference_is_challenged_before_becoming_a_finding(monkeypatch):
    evidence=packet('Measure 5 mL.');script='Measure 5 mg.'
    calls=[]
    def local(model,system,payload,schema,**kwargs):
        calls.append(system)
        if issubclass(schema,review.Alignment):
            return schema.model_validate({'source_checks':[{'source_id':'s1',
                'draft_ids':['d1'],'related_source_ids':[],'comparison':'Unit differs'}],
                'draft_checks':[{'draft_id':'d1','source_ids':['s1'],
                                 'comparison':'Meaning retained'}]})
        assert payload['proposals'][0]['type']=='changed'
        assert payload['proposals'][0]['reason']=='Unit differs'
        return schema.model_validate({'verdicts':[dict(proposal_id=p['id'],
            source_ids=p['source_ids'],draft_ids=p['draft_ids'],outcome='Comparison uncertain')
            for p in payload['proposals']]})
    monkeypatch.setattr(ev,'local_json',local)
    result=review.run(ev,evidence,script,'local:model','learner')
    assert calls==[review.ALIGN_SYSTEM,review.BLIND_SYSTEM,review.VERIFY_SYSTEM]
    assert not result['findings'] and result['uncertain'][0]['decision']=='uncertain'
    assert result['alignment']['source_checks'][0]['status']=='changed'


@pytest.mark.parametrize('change',['missing','extra','duplicate'])
def test_runtime_exact_list_count_and_remaining_duplicate_validator(change):
    source,draft,data=runtime_fixture();schema=review.alignment_schema(source,draft)
    if change=='missing':data['source_checks'].pop()
    if change=='extra':data['source_checks'].append(data['source_checks'][0])
    if change=='duplicate':data['source_checks'][1]=dict(data['source_checks'][0])
    with pytest.raises(ValueError):
        parsed=schema.model_validate(data)
        review.validate_alignment(parsed,source,draft)


@pytest.mark.parametrize('key,value',[
    ('proposal_id','s1'),('proposal_id','p999'),('source_ids',['d1']),('draft_ids',['s1'])])
def test_runtime_verifier_references_are_bound_to_actual_proposals(key,value):
    source,draft,proposals,valid=verification_fixture()
    schema=review.verification_schema(source,draft,proposals)
    assert issubclass(schema,review.Verification)
    valid.pop('reason');valid.pop('decision');valid['outcome']='Discrepancy demonstrated'
    schema.model_validate({'verdicts':[valid]})
    valid[key]=value
    with pytest.raises(ValueError,match='Input should be'):
        schema.model_validate({'verdicts':[valid]})


def test_runtime_verifier_rejects_redundant_verdict_fields_and_empty_coverage():
    source,draft,proposals,valid=verification_fixture()
    schema=review.verification_schema(source,draft,proposals)
    valid['outcome']='Discrepancy demonstrated'
    valid['decision']='refuted'
    with pytest.raises(ValueError,match='Extra inputs are not permitted'):
        schema.model_validate({'verdicts':[valid]})
    assert valid['decision']=='refuted'
    with pytest.raises(ValueError):schema.model_validate({'verdicts':[]})


def test_single_verification_outcome_has_one_unambiguous_domain_verdict():
    source,draft,proposals,valid=verification_fixture()
    valid.pop('reason');valid.pop('decision')
    schema=review.verification_schema(source,draft,proposals)
    properties=ev.transport_schema(schema)['$defs']['BoundVerdict']['properties']
    assert 'decision' not in properties and 'reason' not in properties
    assert list(properties)[-1]=='outcome'
    for outcome,(decision,reason) in review.VERIFICATION_OUTCOMES.items():
        assert outcome in review.VERIFY_SYSTEM
        valid['outcome']=outcome
        parsed=review.domain_verification(schema.model_validate({'verdicts':[valid]}))
        assert parsed.verdicts[0].decision==decision and parsed.verdicts[0].reason==reason
        review.validate_verification(parsed,proposals,source,draft)
    valid['outcome']='Unknown outcome'
    with pytest.raises(ValueError):schema.model_validate({'verdicts':[valid]})
