"""Real installed LangChain create_agent + isolated LoopGrid Core signed workspace.

Runs deterministic synthetic model and a synthetic tool. No external money action.
Host credentials must allow creation of a disposable test workspace.
"""
from __future__ import annotations
import json
import os
import uuid
import tempfile
import httpx
from langchain_core.messages import HumanMessage, AIMessage
from loopgrid_langchain import CoreClient, LangChainBridge, LocalSqliteDispatchLease, LocalAsyncSqliteDispatchLease
from native_agent_e2e import create_sandbox_agent

base=os.environ.get('LOOPGRID_BASE_URL','http://127.0.0.1:8000').rstrip('/')
if base not in ('http://127.0.0.1:8000','http://localhost:8000') and os.environ.get('LOOPGRID_ALLOW_TEST_ORIGIN')!='YES':
    raise SystemExit('Native Core E2E localhost-only by default')
key=os.environ.get('LOOPGRID_ADMIN_KEY') or os.environ.get('LOOPGRID_API_KEY')
headers={'X-LoopGrid-Key':key} if key else {}

def req(method,path,body=None):
    try:
        with httpx.Client(base_url=base,headers=headers,timeout=15,trust_env=False,follow_redirects=False) as http:
            r=http.request(method,path,json=body)
            r.raise_for_status()
            return r.json()
    except httpx.HTTPError as e:
        raise RuntimeError(f'Core disposable workspace setup failed: {type(e).__name__}') from None

ready=req('GET','/ready')
assert ready.get('ready') is True
wid=req('POST','/api/v1/workspaces',{'name':'LangChain SDK+Core E2E '+uuid.uuid4().hex[:8],
   'environment':'development','privacy_mode':'redacted'})['workspace_id']
req('POST',f'/api/v1/workspaces/{wid}/policies',{
    'policy_id':'refund_policy','name':'Synthetic refund','version':'1','active':True,
    'rule':{'type':'amount_threshold','field':'amount','auto_approve_max':500,
            'hard_limit':1500,'currency':'USD'}})
key_result=req('POST',f'/api/v1/workspaces/{wid}/keys',{
   'name':'LangChain SDK+Core sandbox','scopes':['ingest','read','review']})
client=CoreClient(base_url=base,workspace_id=wid,service_key=key_result['api_key'])

class RecordingBridge(LangChainBridge):
    last_scope=None
    def propose(self, call, binding):
        self.last_scope=super().propose(call,binding)
        return self.last_scope

lease_path=os.path.join(tempfile.gettempdir(),f"lc-native-{wid}.sqlite")
bridge=RecordingBridge(client,dispatch_lease=LocalSqliteDispatchLease(lease_path),
                       async_dispatch_lease=LocalAsyncSqliteDispatchLease(lease_path))
executions=[]
def record_real_model_output(scope, request):
    # A genuine LangChain AIMessage persisted in the running native agent state;
    # source is described accurately, not cryptographically attested by provider.
    messages=request.state.get('messages') or []
    latest=messages[-1] if messages else None
    assert isinstance(latest, AIMessage), 'Expected completed model message in agent state'
    assert any(c['id']=='call_1' and c['name']=='sandbox_refund' for c in latest.tool_calls)
    bridge.observe_model(scope['decision_id'], model_name='synthetic-chat-model',
       observed=latest.model_dump(mode='json'),source='langchain.state.completed_ai_message')

agent=create_sandbox_agent(client,run_id='run_real_core_1',executions=executions,
                           bridge=bridge,on_proposed=record_real_model_output)
agent.invoke({'messages':[HumanMessage(content='Execute sandbox-only refund')]},
             config={'configurable':{'thread_id':'run_real_core_1'}})
assert len(executions)==1,executions
scope=bridge.last_scope
assert scope is not None
bridge.record_execution(scope['decision_id'],external_reference='sandbox_action_1',
    source='sandbox_action_log',status='sandbox_confirmed',receipt={'money_moved':False})
bridge.record_outcome(scope['decision_id'],external_reference='sandbox_langchain_1',
    source='isolated_sandbox_record',status='confirmed',observed={'money_moved':False})
proof=client.verify_workspace()
assert proof.get('valid') is True and not proof.get('failures'),proof
detail=client.get_decision(scope['decision_id'])
assert detail['summary']['lifecycle']['state']=='evidence_complete',detail
assert detail['coverage']['score']==100,detail
print('PASS: REAL installed LangChain create_agent tool middleware + REAL local LoopGrid Core signed evidence')
print(json.dumps({'workspace_id':wid,'decision_id':scope['decision_id'],
    'signed_workspace_verification':True,'failures':[], 'sandbox_executions':1,
    'real_money_moved':False,'lifecycle':'evidence_complete','applicable_coverage':100},indent=2))
client.close()
