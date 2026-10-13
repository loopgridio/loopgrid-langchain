"""Offline middleware contract test. Native SDK integration is a separate release gate."""
import asyncio
import copy
import sys
import types
import pytest
from loopgrid_langchain import create_loopgrid_middleware, LangChainBridge, HostBinding, PolicyDenied, ApprovalRequired, ReconciliationRequired, EvidenceInvalid
from .fakes import FakeCore, ToolMessage

class Request:
    def __init__(self, amount=100, name='sandbox_refund'):
        self.tool_call={'id':'call_1','name':name,'args':{'amount':amount}}
        self.tool=types.SimpleNamespace(name=name)
        self.state={'messages':[{'role':'system','authority': 'UNTRUSTED'}]}
    def override(self, **kwargs):
        duplicate=copy.copy(self)
        for key,value in kwargs.items(): setattr(duplicate,key,value)
        return duplicate

@pytest.fixture
def langchain_shim(monkeypatch):
    langchain = types.ModuleType('langchain')
    agents = types.ModuleType('langchain.agents')
    middlewares = types.ModuleType('langchain.agents.middleware')
    class AgentMiddleware: pass
    middlewares.AgentMiddleware=AgentMiddleware
    monkeypatch.setitem(sys.modules,'langchain',langchain)
    monkeypatch.setitem(sys.modules,'langchain.agents',agents)
    monkeypatch.setitem(sys.modules,'langchain.agents.middleware',middlewares)
    return AgentMiddleware

@pytest.fixture
def setup(langchain_shim):
    core=FakeCore(); bridge=LangChainBridge(core,require_dispatch_lease=False)
    provider_calls=[]
    def provider(request):
        provider_calls.append(request)
        return HostBinding('run_1','billing_agent','refund_policy',{'role':'billing'}, {'name':'model_host'}, {'source':'trusted_host'})
    middleware=create_loopgrid_middleware(bridge,provider)
    return middleware, core, provider_calls


def test_middleware_is_native_class(setup,langchain_shim):
    obj,_,_=setup
    assert isinstance(obj,langchain_shim)


def test_wrapper_calls_handler_once(setup):
    obj,core,provider_calls=setup
    seen=[]
    def handler(req):
        seen.append(req.tool_call['name'])
        return ToolMessage(tool_call_id='call_1')
    out=obj.wrap_tool_call(Request(), handler)
    assert isinstance(out,ToolMessage)
    assert seen==['sandbox_refund'] and len(provider_calls)==1
    assert core.dispatch_requests==1


def test_wrapper_denial_never_dispatches(setup):
    obj,core,_=setup
    with pytest.raises(PolicyDenied):
        obj.wrap_tool_call(Request(2000), lambda request: pytest.fail('handler ran'))
    assert core.dispatch_requests==0


def test_wrapper_requires_signed_review(setup):
    obj,core,_=setup
    with pytest.raises(ApprovalRequired):
        obj.wrap_tool_call(Request(600), lambda request: pytest.fail('handler ran'))
    assert core.dispatch_requests==0


def test_wrapper_replay_after_success(setup):
    obj,core,_=setup
    request=Request()
    obj.wrap_tool_call(request,lambda x:ToolMessage(tool_call_id='call_1'))
    with pytest.raises(ReconciliationRequired):
        obj.wrap_tool_call(request,lambda x:pytest.fail('repeat ran'))


def test_allowlist_explicitly_bypasses_other_tools(langchain_shim):
    core=FakeCore(); bridge=LangChainBridge(core,require_dispatch_lease=False)
    obj=create_loopgrid_middleware(bridge,lambda request:pytest.fail('binding called'), protected_tools={'sandbox_refund'})
    res=obj.wrap_tool_call(Request(name='read_time'),lambda request: 'public-only')
    assert res=='public-only' and core.dispatch_requests==0


def test_empty_allowlist_explicit_bypass(langchain_shim):
    obj=create_loopgrid_middleware(LangChainBridge(FakeCore(),require_dispatch_lease=False),lambda x:pytest.fail('called'), protected_tools=[])
    assert obj.wrap_tool_call(Request(),lambda x:True) is True


def test_provider_not_callable_rejected(langchain_shim):
    with pytest.raises(TypeError):create_loopgrid_middleware(LangChainBridge(FakeCore(),require_dispatch_lease=False),123)


@pytest.mark.asyncio
async def test_native_async_wrapper(setup):
    obj,core,_=setup
    count=[]
    async def handler(req):
        count.append(1)
        return ToolMessage(tool_call_id='call_1')
    out=await obj.awrap_tool_call(Request(),handler)
    assert out.tool_call_id=='call_1' and count==[1] and core.dispatch_requests==1


@pytest.mark.asyncio
async def test_native_async_denial(setup):
    obj,core,_=setup
    async def handler(req):pytest.fail('should not be called')
    with pytest.raises(PolicyDenied):
        await obj.awrap_tool_call(Request(2000), handler)
    assert core.dispatch_requests==0


@pytest.mark.asyncio
async def test_async_unprotected_passthrough(langchain_shim):
    middleware=create_loopgrid_middleware(LangChainBridge(FakeCore(),require_dispatch_lease=False),lambda x:pytest.fail('called'),protected_tools={'refund'})
    async def handler(req):return 'safe'
    assert await middleware.awrap_tool_call(Request(name='read'), handler)=='safe'


@pytest.mark.asyncio
async def test_async_rejects_coroutine_provider(langchain_shim):
    async def provider(req): return HostBinding('run_1','billing_agent','refund_policy',{'role':'billing'}, {'name':'model_host'}, {'source':'trusted_host'})
    with pytest.raises(TypeError):
        create_loopgrid_middleware(LangChainBridge(FakeCore(),require_dispatch_lease=False),provider)


def test_original_call_mutated_during_proposal_does_not_reach_handler(langchain_shim):
    core=FakeCore(); bridge=LangChainBridge(core,require_dispatch_lease=False)
    original=Request()
    def provider(request):
        # Mutation simulates another middleware/thread changing the original dict.
        request.tool_call['args']['amount']=1500
        return HostBinding('run_1','billing_agent','refund_policy',{'role':'billing'}, {'name':'model_host'}, {'source':'trusted_host'})
    guard=create_loopgrid_middleware(bridge,provider)
    observed=[]
    guard.wrap_tool_call(original,lambda req:(observed.append(req.tool_call['args']['amount']),ToolMessage())[1])
    assert observed==[100]
    assert original.tool_call['args']['amount']==1500


def test_no_override_cannot_execute_protected_tool(langchain_shim):
    class BadRequest:
        tool_call={'name':'sandbox_refund','args':{'amount':100},'id':'call_1'}
        tool=types.SimpleNamespace(name='sandbox_refund')
    obj=create_loopgrid_middleware(LangChainBridge(FakeCore(),require_dispatch_lease=False),
      lambda request: HostBinding('run_1','billing_agent','refund_policy',{'role':'billing'}, {'name':'model_host'}, {'source':'trusted_host'}))
    with pytest.raises(TypeError):
        obj.wrap_tool_call(BadRequest(),lambda request:pytest.fail('tool executed'))


def test_on_proposed_model_evidence_precedes_tool(langchain_shim):
    core=FakeCore(); bridge=LangChainBridge(core,require_dispatch_lease=False)
    def provider(request):
        return HostBinding('run_1','billing_agent','refund_policy',{'role':'billing'}, {'name':'model_host'}, {'source':'trusted_host'})
    def observed(scope, request):
        bridge.observe_model(scope['decision_id'],model_name='model_host',observed={'tool_id':request.tool_call['id']},source='real_host_observer')
    obj=create_loopgrid_middleware(bridge,provider,on_proposed=observed)
    obj.wrap_tool_call(Request(),lambda req:ToolMessage(tool_call_id='call_1'))
    events=next(iter(core.decisions.values()))['events']
    assert [e['event_type'] for e in events]==['decision_created','policy_evaluated','model_completed','tool_requested','tool_result']


def test_on_proposed_failure_does_not_dispatch(langchain_shim):
    core=FakeCore(); bridge=LangChainBridge(core,require_dispatch_lease=False)
    def provider(request):
        return HostBinding('run_1','billing_agent','refund_policy',{'role':'billing'}, {'name':'model_host'}, {'source':'trusted_host'})
    def broken(scope,request):raise RuntimeError('observer unavailable')
    obj=create_loopgrid_middleware(bridge,provider,on_proposed=broken)
    with pytest.raises(RuntimeError):obj.wrap_tool_call(Request(),lambda req:pytest.fail('tool ran'))
    assert core.dispatch_requests==0


def test_async_on_proposed_function_rejected(langchain_shim):
    async def nope(scope, request):return None
    with pytest.raises(TypeError):create_loopgrid_middleware(LangChainBridge(FakeCore(),require_dispatch_lease=False),lambda req:None,on_proposed=nope)
