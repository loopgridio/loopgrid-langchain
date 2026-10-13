import asyncio
from dataclasses import replace
import pytest
from loopgrid_langchain import (LangChainBridge, HostBinding, EvidenceInvalid, PolicyDenied,
     ApprovalRequired, ReconciliationRequired, LocalSqliteDispatchLease)
from loopgrid_langchain.bridge import signed_matches, commitment, parse_tool_call
from .fakes import ToolMessage


def result(): return ToolMessage("sandbox receipt")

def test_auto_allowed(bridge, core, call, binding):
    scope = bridge.propose(call,binding)
    seen=[]
    out=bridge.dispatch(scope,call,binding,lambda: (seen.append(1),result())[1])
    assert out.content == "sandbox receipt" and seen==[1]
    evs=core.get_decision(scope['decision_id'])['events']
    assert [e['event_type'] for e in evs]==['decision_created','policy_evaluated','tool_requested','tool_result']
    assert 'amount' not in str(evs[0]['payload']['proposed_action'])
    with pytest.raises(ReconciliationRequired):
        bridge.dispatch(scope,call,binding,result)
    assert core.dispatch_requests==1


def test_policy_blocked(bridge, call, binding):
    call['args']['amount']=1600
    scope=bridge.propose(call,binding)
    with pytest.raises(PolicyDenied):
        bridge.dispatch(scope,call,binding,lambda:pytest.fail('executed'))


def test_approval_gate(bridge,core,call,binding):
    call['args']['amount']=600
    scope=bridge.propose(call,binding)
    with pytest.raises(ApprovalRequired):
        bridge.dispatch(scope,call,binding,lambda:pytest.fail('executed'))
    core.review(scope['decision_id'],'approve','authenticated_operator')
    assert bridge.dispatch(scope,call,binding,result).content == 'sandbox receipt'


def test_rejection_terminal(bridge,core,call,binding):
    call['args']['amount']=600
    scope=bridge.propose(call,binding)
    core.review(scope['decision_id'],'reject','authenticated_operator')
    core.review(scope['decision_id'],'approve','authenticated_operator')
    with pytest.raises(PolicyDenied):
        bridge.dispatch(scope,call,binding,result)

@pytest.mark.parametrize('field,new', [('agent_id','new_agent'), ('run_id','another_run'),
        ('policy_id','other_policy')])
def test_host_identity_cannot_change(bridge,call,binding,field,new):
    scope=bridge.propose(call,binding)
    with pytest.raises(EvidenceInvalid):
        bridge.dispatch(scope,call,replace(binding,**{field:new}),lambda:pytest.fail('executed'))

@pytest.mark.parametrize('field,new', [ ('authority',{'role':'admin'}),
        ('model',{'name':'other-model'}), ('context',{'prompt_version':'v4'}) ])
def test_host_context_cannot_change(bridge,call,binding,field,new):
    scope=bridge.propose(call,binding)
    with pytest.raises(EvidenceInvalid):
        bridge.dispatch(scope,call,replace(binding,**{field:new}),lambda:pytest.fail('executed'))


def test_tool_call_args_changed(bridge,call,binding):
    scope=bridge.propose(call,binding)
    call['args']['amount']=120
    with pytest.raises(EvidenceInvalid): bridge.dispatch(scope,call,binding,lambda:pytest.fail('executed'))


def test_tool_call_id_changed(bridge,call,binding):
    scope=bridge.propose(call,binding)
    call['id']='call_2'
    with pytest.raises(EvidenceInvalid): bridge.dispatch(scope,call,binding,lambda:pytest.fail('executed'))


def test_tool_name_changed(bridge,call,binding):
    scope=bridge.propose(call,binding)
    call['name']='other_tool'
    with pytest.raises(EvidenceInvalid): bridge.dispatch(scope,call,binding,lambda:pytest.fail('executed'))


def test_idempotent_proposal_scope(bridge,core,call,binding):
    first=bridge.propose(call,binding)
    again=bridge.propose(call,binding)
    assert again['decision_id']==first['decision_id']
    assert [x['event_type'] for x in core.get_decision(first['decision_id'])['events']].count('policy_evaluated')==1


def test_idempotent_change_refused(bridge,call,binding):
    bridge.propose(call,binding)
    call['args']['amount']=200
    with pytest.raises(EvidenceInvalid): bridge.propose(call,binding)


def test_idempotent_context_change_refused(bridge,call,binding):
    bridge.propose(call,binding)
    with pytest.raises(EvidenceInvalid):
        bridge.propose(call,replace(binding,context={'prompt_version':'v5'}))


def test_policy_rotation_refused(bridge,core,call,binding):
    scope=bridge.propose(call,binding)
    core.version='2'
    with pytest.raises(PolicyDenied): bridge.dispatch(scope,call,binding,lambda:pytest.fail('executed'))


def test_verify_failure_refused(bridge,core,call,binding):
    scope=bridge.propose(call,binding)
    core.valid=False
    with pytest.raises(EvidenceInvalid): bridge.dispatch(scope,call,binding,lambda:pytest.fail('executed'))


def test_wrong_workspace_refused(bridge,core,call,binding):
    scope=bridge.propose(call,binding)
    core.decisions[scope['decision_id']]['summary']['workspace_id']='ws_other'
    with pytest.raises(EvidenceInvalid): bridge.dispatch(scope,call,binding,lambda:pytest.fail('executed'))


def test_duplicate_reservation_refused(bridge,core,call,binding):
    scope=bridge.propose(call,binding)
    core.duplicate_reservation=True
    with pytest.raises(ReconciliationRequired): bridge.dispatch(scope,call,binding,lambda:pytest.fail('executed'))


def test_handler_error_after_barrier_requires_reconciliation(bridge,core,call,binding):
    scope=bridge.propose(call,binding)
    def fail(): raise RuntimeError('sensitive downstream error')
    with pytest.raises(ReconciliationRequired,match='reconcile') as ex:
        bridge.dispatch(scope,call,binding,fail)
    assert 'sensitive' not in str(ex.value)
    assert core.dispatch_requests==1


def test_unexpected_handler_return_refused(bridge,call,binding):
    scope=bridge.propose(call,binding)
    with pytest.raises(ReconciliationRequired): bridge.dispatch(scope,call,binding,lambda:{'foo':'bar'})


def test_wrong_tool_message_id_refused(bridge,call,binding):
    scope=bridge.propose(call,binding)
    with pytest.raises(ReconciliationRequired): bridge.dispatch(scope,call,binding,lambda:ToolMessage(tool_call_id='call_wrong'))


def test_error_tool_message_is_not_success(bridge,core,call,binding):
    scope=bridge.propose(call,binding)
    out=bridge.dispatch(scope,call,binding,lambda:ToolMessage(status='error'))
    assert out.status=='error'
    evs=[e['event_type'] for e in core.get_decision(scope['decision_id'])['events']]
    assert 'tool_result' in evs and 'tool_executed' not in evs


def test_outcome_requires_execution(bridge,call,binding):
    scope=bridge.propose(call,binding)
    with pytest.raises(EvidenceInvalid):
        bridge.record_outcome(scope['decision_id'],external_reference='receipt1',source='system',status='succeeded',observed={})


def test_external_outcome_explicit(bridge,core,call,binding):
    scope=bridge.propose(call,binding)
    bridge.dispatch(scope,call,binding,result)
    bridge.record_execution(scope['decision_id'], external_reference='sb_action1',
                            source='sandbox_db', status='sandbox_confirmed', receipt={'id':'sb_action1'})
    bridge.record_outcome(scope['decision_id'],external_reference='receipt1',source='sandbox_db',status='succeeded',observed={'reference':'receipt1'})
    kinds=[e['event_type'] for e in core.get_decision(scope['decision_id'])['events']]
    assert kinds[-1]=='outcome_observed'


def test_observed_model_explicit(bridge,core,call,binding):
    scope=bridge.propose(call,binding)
    bridge.observe_model(scope['decision_id'],model_name='test-model',observed={'answer':'hello'},source='host_complete_model_callback')
    kinds=[e['event_type'] for e in core.get_decision(scope['decision_id'])['events']]
    assert 'model_completed' in kinds


def test_redacted_core_replay(bridge,core,call,binding):
    core.typed_redaction=True
    scope=bridge.propose(call,binding)
    again=bridge.propose(call,binding)
    assert again['decision_id']==scope['decision_id']
    assert bridge.dispatch(again,call,binding,result).content=='sandbox receipt'


def test_redacted_tampered_model_refused(bridge,core,call,binding):
    core.typed_redaction=True
    scope=bridge.propose(call,binding)
    evs=core.decisions[scope['decision_id']]['events']
    evs[0]['payload']['model']['name']['sha256']='0'*64
    with pytest.raises(EvidenceInvalid): bridge.dispatch(scope,call,binding,lambda:pytest.fail('executed'))


def test_signed_matches_typed_redaction():
    value={'k': 'private', 'num': 7}
    assert signed_matches({'k':{'redacted':True,'sha256':commitment('private'),'type':'str'},'num':7},value)
    assert not signed_matches({'k':{'redacted':True,'sha256':'f'*64,'type':'str'},'num':7},value)


def test_reserved_context_rejected(bridge,call,binding):
    with pytest.raises(ValueError): bridge.propose(call, replace(binding,context={'run_id':'spoof'}))


def test_reserved_tool_rejected_before_create(bridge,core,call,binding):
    call['args']['tool']='other'
    with pytest.raises(ValueError): bridge.propose(call,binding)
    assert not core.decisions


def test_non_json_rejected(bridge,call,binding):
    call['args']['amount']=float('nan')
    with pytest.raises(ValueError): bridge.propose(call,binding)


def test_bad_identifier_rejected(bridge,call,binding):
    call['id']='bad/id'
    with pytest.raises(ValueError): bridge.propose(call,binding)


def test_missing_durable_lease_fail_closed(core,call,binding):
    guard=LangChainBridge(core,require_dispatch_lease=True)
    scope=guard.propose(call,binding)
    with pytest.raises(ReconciliationRequired): guard.dispatch(scope,call,binding,lambda:pytest.fail('executed'))


def test_core_api_refusal_fail_closed(bridge,core,call,binding):
    scope=bridge.propose(call,binding)
    core.outage.add('verify')
    with pytest.raises(RuntimeError): bridge.dispatch(scope,call,binding,lambda:pytest.fail('executed'))


def test_lock_type_rejected(core):
    with pytest.raises(TypeError): LangChainBridge(core,dispatch_lease=42)


def test_sync_handler_cannot_return_awaitable(bridge,call,binding):
    scope=bridge.propose(call,binding)
    async def coro(): return 1
    with pytest.raises(ReconciliationRequired): bridge.dispatch(scope,call,binding,coro)


@pytest.mark.asyncio
async def test_async_auto_allowed(bridge,core,call,binding):
    scope=bridge.propose(call,binding)
    async def handler():return result()
    assert (await bridge.dispatch_async(scope,call,binding,handler)).content=='sandbox receipt'
    with pytest.raises(ReconciliationRequired):
        await bridge.dispatch_async(scope,call,binding,handler)


@pytest.mark.asyncio
async def test_async_requires_durable_lease(core,call,binding):
    guard=LangChainBridge(core,require_dispatch_lease=True)
    scope=guard.propose(call,binding)
    async def handler(): pytest.fail('executed')
    with pytest.raises(ReconciliationRequired):
        await guard.dispatch_async(scope,call,binding,handler)


@pytest.mark.asyncio
async def test_async_approval(bridge,core,call,binding):
    call['args']['amount']=600
    scope=bridge.propose(call,binding)
    async def handler():return result()
    with pytest.raises(ApprovalRequired):
        await bridge.dispatch_async(scope,call,binding,handler)
    core.review(scope['decision_id'],'approve','authenticated_operator')
    assert (await bridge.dispatch_async(scope,call,binding,handler)).content=='sandbox receipt'


@pytest.mark.asyncio
async def test_async_reconcile_on_failure(bridge,core,call,binding):
    scope=bridge.propose(call,binding)
    async def handler():raise RuntimeError('downstream sensitive')
    with pytest.raises(ReconciliationRequired,match='reconcile') as ex:
        await bridge.dispatch_async(scope,call,binding,handler)
    assert 'sensitive' not in str(ex.value)


def test_sqlite_lease_local(tmp_path):
    lease=LocalSqliteDispatchLease((tmp_path/'lease.sqlite').absolute())
    with lease('lg-langchain-test'):
        assert (tmp_path/'lease.sqlite').exists()
