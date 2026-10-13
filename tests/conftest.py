import pytest
from loopgrid_langchain import HostBinding, LangChainBridge, LocalSqliteDispatchLease, LocalAsyncSqliteDispatchLease
from .fakes import FakeCore

@pytest.fixture
def core(): return FakeCore()

@pytest.fixture
def bridge(core, tmp_path):
    path=(tmp_path / "shared-dispatch.sqlite").absolute()
    return LangChainBridge(core, dispatch_lease=LocalSqliteDispatchLease(path),
                           async_dispatch_lease=LocalAsyncSqliteDispatchLease(path))

@pytest.fixture
def binding():
    return HostBinding(run_id="run_1", agent_id="billing_agent", policy_id="refund_policy",
                       authority={"role":"billing"}, model={"name":"test-model"},
                       context={"prompt_version":"v3"})

@pytest.fixture
def call(): return {"name":"sandbox_refund", "args":{"amount":100,"currency":"USD"}, "id":"call_1"}
