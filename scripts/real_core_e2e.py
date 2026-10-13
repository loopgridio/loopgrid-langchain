"""Disposable real LoopGrid Core integration test with synthetic tool handler.

Does NOT use a real LangChain Agent runtime. Run native_agent_e2e.py separately.
Do not point at production Core. Requires access to create disposable workspaces.
"""
from __future__ import annotations
import os, json, uuid, tempfile
import httpx
from loopgrid_langchain import (CoreClient, LangChainBridge, HostBinding, ApprovalRequired, PolicyDenied,
    ReconciliationRequired, LocalSqliteDispatchLease, LocalAsyncSqliteDispatchLease)

base=os.environ.get('LOOPGRID_BASE_URL','http://127.0.0.1:8000').rstrip('/')
if base not in ('http://127.0.0.1:8000','http://localhost:8000') and os.environ.get('LOOPGRID_ALLOW_TEST_ORIGIN')!='YES':
    raise SystemExit('E2E is localhost-only by default; nonloopback requires explicit opt-in')
key=os.environ.get('LOOPGRID_ADMIN_KEY') or os.environ.get('LOOPGRID_API_KEY')
headers={'X-LoopGrid-Key':key} if key else {}

def req(method,path,body=None):
    try:
        with httpx.Client(base_url=base,headers=headers,timeout=15,trust_env=False,follow_redirects=False) as http:
            r=http.request(method,path,json=body)
            r.raise_for_status()
            return r.json()
    except httpx.HTTPError as e:
        raise RuntimeError(f'Core sandbox setup failed: {type(e).__name__}') from None

ready=req('GET','/ready')
assert ready.get('ready') is True,'Core unavailable'
wid=req('POST','/api/v1/workspaces',{'name':'LangChain isolated e2e '+uuid.uuid4().hex[:8],
                                    'environment':'development','privacy_mode':'redacted'})['workspace_id']
policy_id='langchain-refund-test'
req('POST',f'/api/v1/workspaces/{wid}/policies',{
    'policy_id':policy_id,'name':'Synthetic refund policy','version':'1','active':True,
    'rule':{'type':'amount_threshold','field':'amount','auto_approve_max':500,'hard_limit':1500,'currency':'USD'}})
service=req('POST',f'/api/v1/workspaces/{wid}/keys',{
    'name':'LangChain isolated E2E','scopes':['ingest','read','review']})
client=CoreClient(base_url=base,workspace_id=wid,service_key=service['api_key'])
lease_path=os.path.join(tempfile.gettempdir(),f"lc-sandbox-{wid}.sqlite")
bridge=LangChainBridge(client,dispatch_lease=LocalSqliteDispatchLease(lease_path),
                       async_dispatch_lease=LocalAsyncSqliteDispatchLease(lease_path))
calls=[]

class ToolMessage:
    def __init__(self, content, tool_call_id, status='success'):
        self.content=content;self.tool_call_id=tool_call_id;self.status=status

def start(amount, op):
    call={'id':'call_'+op,'name':'refund','args':{'amount':amount,'currency':'USD'}}
    binding=HostBinding(run_id='run_'+op,agent_id='synthetic_langchain_agent',policy_id=policy_id,
                        authority={'limit_usd':1500},model={'name':'synthetic-model'},
                        context={'prompt_version':'synthetic-v1'})
    scope=bridge.propose(call,binding)
    return call,binding,scope

def dispatch(obj):
    call,binding,scope=obj
    def handler():
        calls.append(call['id'])
        return ToolMessage('sandbox-only receipt',call['id'])
    return bridge.dispatch(scope,call,binding,handler)

allowed=start(20,'allow')
bridge.observe_model(allowed[2]['decision_id'],model_name='synthetic-model',
                     observed={'proposed':20},source='sandbox.scripted_model')
dispatch(allowed)
bridge.record_execution(allowed[2]['decision_id'],external_reference='sb_action_allow',
                        source='sandbox_db',status='sandbox_confirmed',receipt={'money_moved':False})
bridge.record_outcome(allowed[2]['decision_id'],external_reference='sb_allow',
                      source='sandbox_db',status='confirmed',observed={'money_moved':False})
blocked=start(2000,'blocked')
try:dispatch(blocked);raise AssertionError('Blocked action executed')
except PolicyDenied:pass
approved=start(700,'approved')
try:dispatch(approved);raise AssertionError('Approval gate bypassed')
except ApprovalRequired:pass
client.review(approved[2]['decision_id'],'approve','synthetic_authorized_reviewer','sandbox only')
dispatch(approved)
bridge.record_execution(approved[2]['decision_id'],external_reference='sb_action_approved',
                        source='sandbox_db',status='sandbox_confirmed',receipt={'money_moved':False})
bridge.record_outcome(approved[2]['decision_id'],external_reference='sb_approved',
                      source='sandbox_db',status='confirmed',observed={'money_moved':False})
rejected=start(700,'rejected')
client.review(rejected[2]['decision_id'],'reject','synthetic_authorized_reviewer','sandbox only')
try:dispatch(rejected);raise AssertionError('Rejected action executed')
except PolicyDenied:pass
try:dispatch(allowed);raise AssertionError('Replay executed')
except ReconciliationRequired:pass
proof=client.verify_workspace()
assert proof.get('valid') is True and not proof.get('failures'), proof
assert calls==['call_allow','call_approved'],calls
for obj in (allowed,approved):
    detail=client.get_decision(obj[2]['decision_id'])
    assert detail['summary']['lifecycle']['state']=='evidence_complete',detail
    assert detail['coverage']['score']==100,detail
print(json.dumps({"core":ready.get('version'),"workspace_id":wid,
 "signed_workspace_verification":proof.get('valid'),"failures":proof.get('failures'),
 "sandbox_executions":len(calls),"real_money_moved":False,
 "lifecycle":"evidence_complete","applicable_coverage":100,
 "real_langchain_sdk":False},indent=2))
client.close()
