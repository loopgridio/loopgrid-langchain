"""Actual installed LangChain create_agent + AgentMiddleware smoke.

Uses deterministic synthetic chat model and synthetic Core. Not a real model
provider, not a real Core signature, and not an external financial action.
Run separately from the offline pytest suite.
"""
from __future__ import annotations
import asyncio
import json
import sys
import tempfile
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from langchain.agents import create_agent
from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage
from langchain_core.outputs import ChatGeneration, ChatResult
from langchain_core.tools import tool

from loopgrid_langchain import (LangChainBridge, HostBinding, create_loopgrid_middleware,
    ReconciliationRequired, LocalSqliteDispatchLease, LocalAsyncSqliteDispatchLease)
from tests.fakes import FakeCore

class ScriptedToolModel(BaseChatModel):
    @property
    def _llm_type(self) -> str:
        return "loopgrid-synthetic-tool-model"

    def bind_tools(self, tools, *, tool_choice=None, **kwargs):
        # We generate a deterministic tool call, never call a model provider.
        return self

    def _generate(self, messages, stop=None, run_manager=None, **kwargs):
        had_tool = any(isinstance(m, ToolMessage) for m in messages)
        response = (AIMessage(content="Synthetic final reply") if had_tool
                    else AIMessage(content="", tool_calls=[{
                        "id": "call_1", "name": "sandbox_refund", "args": {"amount": 10, "currency": "USD"},
                    }]))
        return ChatResult(generations=[ChatGeneration(message=response)])


def create_sandbox_agent(core, *, run_id, executions, bridge=None, on_proposed=None):
    @tool
    def sandbox_refund(amount: int, currency: str) -> str:
        """Simulate a refund without transferring real funds."""
        executions.append({"amount": amount, "currency": currency})
        return "sandbox receipt only"

    if bridge is None:
        path=Path(tempfile.gettempdir()) / ("loopgrid-langchain-"+run_id+".sqlite")
        bridge=LangChainBridge(core,dispatch_lease=LocalSqliteDispatchLease(path),
                               async_dispatch_lease=LocalAsyncSqliteDispatchLease(path))
    def host_binding(request):
        return HostBinding(run_id=run_id, agent_id="sandbox_langchain_agent",
                           policy_id="refund_policy", authority={"role": "sandbox"},
                           model={"name":"synthetic-chat-model"},
                           context={"prompt_version":"synthetic-v1"})
    middleware=create_loopgrid_middleware(bridge, host_binding, on_proposed=on_proposed)
    agent=create_agent(model=ScriptedToolModel(), tools=[sandbox_refund],
                       middleware=[middleware])
    return agent


def main():
    core=FakeCore()
    calls=[]
    agent=create_sandbox_agent(core,run_id="run_native_1",executions=calls)
    result=agent.invoke({"messages":[HumanMessage(content="simulate refund")]},
                        config={"configurable":{"thread_id":"run_native_1"}})
    assert calls==[{"amount":10,"currency":"USD"}],calls
    assert isinstance(result["messages"][-1],AIMessage),result
    assert core.verify_workspace()["valid"] is True
    native_events=[e["event_type"] for row in core.decisions.values() for e in row["events"]]
    assert "tool_result" in native_events and "tool_executed" not in native_events, native_events
    try:
        agent.invoke({"messages":[HumanMessage(content="simulate refund")]},
                     config={"configurable":{"thread_id":"run_native_1"}})
    except ReconciliationRequired:
        pass
    else:
        raise AssertionError("Replay was not denied")
    assert len(calls)==1,calls
    async def async_smoke():
        async_calls=[]
        agent_async=create_sandbox_agent(core,run_id="run_native_async_2",executions=async_calls)
        completed=await agent_async.ainvoke({"messages":[HumanMessage(content="simulate refund async")]},
                                            config={"configurable":{"thread_id":"run_native_async_2"}})
        assert len(async_calls)==1,async_calls
        assert isinstance(completed["messages"][-1],AIMessage)
    asyncio.run(async_smoke())
    print("PASS: synchronous and asynchronous installed LangChain create_agent + replay refusal")
    print(json.dumps({"synthetic_core": True,"real_sdk":True,"sync_tool_calls":len(calls),"async_tool_calls":1,"money_moved":False}))

if __name__ == "__main__":
    main()
