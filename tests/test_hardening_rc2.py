"""Prepublication regressions for trust-boundary classification and lease races."""
import asyncio
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from pathlib import Path
import threading
from types import SimpleNamespace
import pytest

from loopgrid_langchain import (LangChainBridge, HostBinding, LocalSqliteDispatchLease,
    LocalAsyncSqliteDispatchLease, ReconciliationRequired, EvidenceInvalid,
    create_loopgrid_middleware)
from .fakes import FakeCore, ToolMessage
from .test_middleware import Request, langchain_shim


class RealShapeIdempotentFakeCore(FakeCore):
    """Core event dedup returns a stored event WITHOUT idempotent_replay marker."""
    def __init__(self):
        super().__init__()
        self._event_lock = threading.Lock()
        self._unique_events = {}

    def add_event(self, decision_id, kind, payload, **kwargs):
        key = kwargs.get('idempotency_key')
        with self._event_lock:
            if key and key in self._unique_events:
                return self._unique_events[key].copy()
            saved = super().add_event(decision_id, kind, payload, **kwargs)
            if key:
                self._unique_events[key] = saved.copy()
            return saved


def test_default_requires_shared_lease(core, call, binding):
    bridge = LangChainBridge(core)
    assert bridge.require_dispatch_lease is True
    scope = bridge.propose(call, binding)
    with pytest.raises(ReconciliationRequired, match='lease'):
        bridge.dispatch(scope, call, binding, lambda: pytest.fail('executed'))
    assert core.dispatch_requests == 0


def test_execution_needs_explicit_receipt(bridge, core, call, binding):
    scope = bridge.propose(call, binding)
    bridge.dispatch(scope, call, binding, lambda: ToolMessage())
    events = core.get_decision(scope['decision_id'])['events']
    assert events[-1]['event_type'] == 'tool_result'
    assert not any(x['event_type']=='tool_executed' for x in events)
    with pytest.raises(EvidenceInvalid, match='execution'):
        bridge.record_outcome(scope['decision_id'], external_reference='sb1',
                              source='sandbox', status='confirmed', observed={'done': True})
    bridge.record_execution(scope['decision_id'], external_reference='provider-r1',
                            source='sandbox_action_log', status='sandbox_confirmed',
                            receipt={'id':'provider-r1', 'secret':'should not store'})
    events = core.get_decision(scope['decision_id'])['events']
    assert events[-1]['event_type'] == 'tool_executed'
    assert 'should not store' not in str(events)
    with pytest.raises(ReconciliationRequired):
        bridge.record_execution(scope['decision_id'], external_reference='provider-r2',
                                source='sandbox_action_log', status='sandbox_confirmed', receipt={})


def test_failed_result_cannot_be_promoted_to_execution(bridge, call, binding):
    scope = bridge.propose(call, binding)
    bridge.dispatch(scope, call, binding, lambda: ToolMessage(status='error'))
    with pytest.raises(EvidenceInvalid):
        bridge.record_execution(scope['decision_id'], external_reference='r1',
                                source='sandbox_provider', status='confirmed', receipt={})


@pytest.mark.parametrize('bad_status', ['', 'error', 'pending', 'unverified'])
def test_execution_receipt_status_validation(bridge, call, binding, bad_status):
    scope = bridge.propose(call, binding)
    bridge.dispatch(scope, call, binding, lambda: ToolMessage())
    with pytest.raises(ValueError):
        bridge.record_execution(scope['decision_id'], external_reference='r1',
                                source='sandbox', status=bad_status, receipt={})


def test_two_bridges_shared_sqlite_lock_allows_one_dispatch(tmp_path, call, binding):
    core = RealShapeIdempotentFakeCore()
    path = (tmp_path/'dispatch.sqlite').absolute()
    guard_a = LangChainBridge(core,dispatch_lease=LocalSqliteDispatchLease(path))
    guard_b = LangChainBridge(core,dispatch_lease=LocalSqliteDispatchLease(path))
    scope = guard_a.propose(call, binding)
    entered = threading.Barrier(2)
    calls = []
    def run(guard):
        entered.wait(timeout=5)
        try:
            guard.dispatch(scope, call, binding,
                lambda: (calls.append('ran'), ToolMessage())[1])
            return 'ran'
        except ReconciliationRequired:
            return 'blocked'
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(run, [guard_a, guard_b]))
    assert sorted(results)==['blocked', 'ran']
    assert calls == ['ran']
    assert core.dispatch_requests == 1


@pytest.mark.asyncio
async def test_sync_async_bridge_same_lease_serializes(tmp_path, call, binding):
    core = RealShapeIdempotentFakeCore()
    path = (tmp_path/'cross-mode.sqlite').absolute()
    guard_a = LangChainBridge(core,async_dispatch_lease=LocalAsyncSqliteDispatchLease(path))
    guard_b = LangChainBridge(core,async_dispatch_lease=LocalAsyncSqliteDispatchLease(path))
    scope = guard_a.propose(call,binding)
    calls=[]
    async def worker(guard):
        await asyncio.sleep(0)
        async def handler():
            calls.append('ran')
            await asyncio.sleep(0.03)
            return ToolMessage()
        try:
            await guard.dispatch_async(scope,call,binding,handler)
            return 'ran'
        except ReconciliationRequired:
            return 'blocked'
    results = await asyncio.gather(worker(guard_a),worker(guard_b))
    assert sorted(results)==['blocked','ran']
    assert calls==['ran']
    assert core.dispatch_requests==1


@pytest.mark.parametrize('allowed', [None, {'sandbox_refund'}, {'safe_read'}])
def test_mismatched_concrete_tool_denied_before_filter(langchain_shim, allowed):
    core=FakeCore()
    guard=LangChainBridge(core, require_dispatch_lease=False)
    middleware=create_loopgrid_middleware(guard,
        lambda req: HostBinding('run1','agent1','policy1',{'role':'trusted'},
                                {'name':'model1'},{'prompt_version':'v1'}),
        protected_tools=allowed)
    request=Request()
    request.tool=SimpleNamespace(name='other_tool')
    with pytest.raises(EvidenceInvalid, match='mismatch'):
        middleware.wrap_tool_call(request,lambda req:pytest.fail('bypass'))
    assert not core.decisions


@pytest.mark.asyncio
async def test_async_mismatched_concrete_tool_denied(langchain_shim):
    core=FakeCore()
    middleware=create_loopgrid_middleware(LangChainBridge(core,require_dispatch_lease=False),
        lambda req: HostBinding('run1','agent1','policy1',{'role':'trusted'},
                                {'name':'model1'},{'prompt_version':'v1'}))
    req=Request();req.tool=SimpleNamespace(name='different')
    async def unauthorized(req):
        pytest.fail('bypass')
    with pytest.raises(EvidenceInvalid, match='mismatch'):
        await middleware.awrap_tool_call(req,unauthorized)
    assert not core.decisions


def test_protected_tool_object_absent_denied(langchain_shim):
    core=FakeCore()
    middleware=create_loopgrid_middleware(LangChainBridge(core,require_dispatch_lease=False),lambda req:pytest.fail('binding'))
    req=Request();req.tool=None
    with pytest.raises(EvidenceInvalid,match='missing'):
        middleware.wrap_tool_call(req,lambda req:pytest.fail('handler'))
