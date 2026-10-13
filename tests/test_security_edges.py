"""Boundary/negative tests to keep cross-platform CI coverage honest."""
from dataclasses import replace
import asyncio
import httpx
import pytest
from loopgrid_langchain import (LangChainBridge, HostBinding, EvidenceInvalid,
    PolicyDenied, ApprovalRequired, ReconciliationRequired, LocalSqliteDispatchLease,
    LeaseUnavailable, CoreClient, LoopGridError)
from loopgrid_langchain.bridge import signed_matches, commitment, parse_tool_call, snapshot
from .fakes import FakeCore, ToolMessage


def test_signed_lists_and_types():
    assert signed_matches(['x',42],['x',42])
    assert not signed_matches(['x'],['x',42])
    assert not signed_matches({'flag':True},{'flag':1})
    assert not signed_matches({'a':1},{'b':1})
    assert not signed_matches({'redacted':True,'sha256':commitment('hi'),'type':'bytes'},'hi')
    assert not signed_matches({'redacted':True,'sha256':'bad','type':'str'},'hi')
    assert not signed_matches({'redacted':True,'sha256':commitment('hi'),'type':'str','unused':1},'hi')


def test_invalid_payload_types(bridge,binding):
    with pytest.raises(ValueError): bridge.propose({'name':'tool','id':'call_1','args':['bad']},binding)
    with pytest.raises(ValueError): bridge.propose({'name': 'bad tool', 'id':'call_1','args':{}},binding)
    with pytest.raises(ValueError): bridge.propose({'name':'tool','id':None,'args':{}},binding)


def test_empty_context_model_authority(bridge,call,binding):
    for changed in [replace(binding,context={}),replace(binding,authority={}),replace(binding,model={})]:
        with pytest.raises(ValueError): bridge.propose(call,changed)


def test_event_history_missing(bridge,core,call,binding):
    scope=bridge.propose(call,binding)
    core.decisions[scope['decision_id']]['events']=[]
    with pytest.raises(EvidenceInvalid): bridge.dispatch(scope,call,binding,lambda:pytest.fail('handler ran'))


def test_signed_created_tampered(bridge,core,call,binding):
    scope=bridge.propose(call,binding)
    core.decisions[scope['decision_id']]['events'][0]['payload']['proposed_action']['tool']='wrong'
    with pytest.raises(EvidenceInvalid): bridge.dispatch(scope,call,binding,lambda:pytest.fail('handler ran'))


def test_signed_policy_tampered(bridge,core,call,binding):
    scope=bridge.propose(call,binding)
    core.decisions[scope['decision_id']]['events'][1]['payload']['policy_digest']='tampered'
    with pytest.raises(EvidenceInvalid): bridge.dispatch(scope,call,binding,lambda:pytest.fail('handler ran'))


def test_missing_policy_event(bridge,core,call,binding):
    scope=bridge.propose(call,binding)
    del core.decisions[scope['decision_id']]['events'][1]
    with pytest.raises(EvidenceInvalid): bridge.dispatch(scope,call,binding,lambda:pytest.fail('handler ran'))


def test_modified_saved_scope(bridge,call,binding):
    scope=bridge.propose(call,binding)
    scope['agent_id']='attacker'
    with pytest.raises(EvidenceInvalid): bridge.dispatch(scope,call,binding,lambda:pytest.fail('handler ran'))


def test_review_rejected_only(bridge,core,call,binding):
    call['args']['amount']=700
    scope=bridge.propose(call,binding)
    core.review(scope['decision_id'],'reject','host_reviewer')
    with pytest.raises(PolicyDenied): bridge.dispatch(scope,call,binding,lambda:pytest.fail('handler ran'))


def test_policy_manual_review_refused(bridge,core,call,binding):
    original=core.evaluate_policy
    def policy(*args):
        response=original(*args);response['decision']='manual_review_required';return response
    core.evaluate_policy=policy
    scope=bridge.propose(call,binding)
    with pytest.raises(PolicyDenied): bridge.dispatch(scope,call,binding,lambda:pytest.fail('handler ran'))


def test_core_reservation_outage_blocks_tool(bridge,core,call,binding):
    scope=bridge.propose(call,binding)
    core.outage.add('tool_requested')
    with pytest.raises(RuntimeError): bridge.dispatch(scope,call,binding,lambda:pytest.fail('handler ran'))


def test_policy_provenance_missing(bridge,core,call,binding):
    orig=core.evaluate_policy
    def incomplete(*a):
        d=orig(*a); d.pop('policy_digest'); return d
    core.evaluate_policy=incomplete
    with pytest.raises(EvidenceInvalid): bridge.propose(call,binding)


def test_http_client_path_actions():
    requested=[]
    def handler(request):
        requested.append((request.method,request.url.path,request.content))
        return httpx.Response(200,json={'valid':True})
    c=CoreClient(base_url='https://core.example.invalid',workspace_id='ws_test',transport=httpx.MockTransport(handler))
    c.get_decision('dec_good')
    c.add_event('dec_good','tool_requested',{'tool':'x'})
    c.evaluate_policy('test_policy',{'tool':'x'}, {'role':'operator'}, {'scope':'sandbox'})
    c.review('dec_good','approve','operator')
    assert [x[0] for x in requested]==['GET','POST','POST','POST']
    assert requested[0][1].endswith('/dec_good')
    assert b'test_policy' in requested[2][2]
    with pytest.raises(ValueError): c.review('dec_good','approve','')
    with pytest.raises(ValueError): c.review('dec_good','override','operator')
    with pytest.raises(ValueError): c.get_decision('bad/id')
    c.close()


def test_http_bad_timeout():
    with pytest.raises(ValueError):CoreClient(base_url='https://core.example.invalid',workspace_id='ws_test',timeout=0)


def test_sqlite_bad_config(tmp_path):
    with pytest.raises(ValueError):LocalSqliteDispatchLease('relative.sqlite')
    with pytest.raises(ValueError):LocalSqliteDispatchLease((tmp_path/'a.sqlite').absolute(), timeout=0)
    lease=LocalSqliteDispatchLease((tmp_path/'a.sqlite').absolute())
    with pytest.raises(ValueError):
        with lease('bad'):pass


def test_sqlite_lease_contention(tmp_path):
    db=(tmp_path/'lease.sqlite').absolute()
    first=LocalSqliteDispatchLease(db, timeout=1)
    second=LocalSqliteDispatchLease(db, timeout=0.05)
    with first('lg-langchain-first'):
        with pytest.raises(LeaseUnavailable):
            with second('lg-langchain-second'):pytest.fail('lock acquired')


@pytest.mark.asyncio
async def test_async_native_failure_no_replay(bridge,core,call,binding):
    scope=bridge.propose(call,binding)
    async def fail():raise RuntimeError('secret business backend')
    with pytest.raises(ReconciliationRequired):await bridge.dispatch_async(scope,call,binding,fail)
    assert core.dispatch_requests==1
    with pytest.raises(ReconciliationRequired):await bridge.dispatch_async(scope,call,binding,fail)


@pytest.mark.asyncio
async def test_async_tool_message_id_check(bridge,call,binding):
    scope=bridge.propose(call,binding)
    async def bad():return ToolMessage(tool_call_id='other_call')
    with pytest.raises(ReconciliationRequired):await bridge.dispatch_async(scope,call,binding,bad)
