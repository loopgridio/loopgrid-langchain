# LoopGrid LangChain

**Native LangChain 1.x agent middleware for signed, tamper-evident decision evidence and application-controlled tool authorization.**

`loopgrid-langchain` wraps real `create_agent` tool execution through LangChain's `AgentMiddleware.wrap_tool_call` and `awrap_tool_call`. The integration is independent of [LoopGrid's LangGraph adapter](https://github.com/loopgridio/loopgrid-langgraph): LangGraph users can keep their existing StateGraph integration unchanged.

**Compatibility:** Python 3.10+; `langchain>=1.2,<2`. Validated on Windows/Python 3.12.6 with installed LangChain 1.4.5 and LoopGrid Core `0.8.1-design-partner`. For exact test results and their limits, see [VALIDATION.md](VALIDATION.md).

## Install

```bash
python -m pip install loopgrid-langchain==0.1.0
```

For source development and testing in a repository checkout:

```bash
python -m pip install -e ".[test]"
```

A running LoopGrid Core instance, a workspace, its authorized service key, and an application-managed policy are required for actual evidence recording. **The package is an adapter—not a hosted LoopGrid Core service and not a substitute for application authentication.**

## What it records and controls

1. The model proposes a LangChain `ToolCallRequest`; this is **not** proof of authority.
2. A trusted host callback supplies the real run, agent, policy, model, context and delegated authority. These must never be copied from model output or untrusted messages.
3. LoopGrid creates a redacted, decision-scoped record binding the exact tool call and SHA-256 argument commitment; it obtains versioned policy evidence from Core.
4. The guard verifies Core's signed workspace history, checks policy and any authentic human review, and writes a conservative `tool_requested` dispatch reservation **before** forwarding a snapshotted call to the real handler.
5. A native `ToolMessage`/`Command` produces **`tool_result`** evidence only. A separate trusted application integration may record an independently observed action receipt using `record_execution()` (`tool_executed`), and later an observed external state using `record_outcome()`.
6. Core verifies signed ledger integrity; verification does **not** prove a particular model assertion, external transaction or compliance status was true.

A signed rejected decision is terminal. Once dispatch may have occurred, the library refuses automatic replay and raises `ReconciliationRequired`; the host must reconcile with its authoritative external service.

## Try the validated demos (repository checkout)

These scripts use **synthetic** model outputs and tools. They do not contact paid model providers or move real money.

```powershell
python -m pytest -q --cov=loopgrid_langchain --cov-fail-under=90
python .\scripts\native_agent_e2e.py

# For isolated local Core testing (after starting your own disposable Core):
$env:LOOPGRID_BASE_URL = "http://127.0.0.1:8000"
python .\scripts\real_core_e2e.py
python .\scripts\native_core_agent_e2e.py
```

The native demo uses a deterministic `create_agent` model and native sync/async middleware. The real-Core script exercises policy, review and replay; the combined script executes a real installed LangChain agent against a real local Core and verifies its signed evidence. Core runs must point to an **isolated development instance**.

## Embedding middleware in a host application

```python
from langchain.agents import create_agent
from loopgrid_langchain import (
    CoreClient, LangChainBridge, HostBinding,
    create_loopgrid_middleware, LocalSqliteDispatchLease,
    LocalAsyncSqliteDispatchLease,
)

# Configuration values (CORE_URL, WORKSPACE_ID, SERVICE_KEY, RUN_ID,
# application_policy_id, model, sandbox_refund) MUST be provided by your host.
client = CoreClient(
    base_url=CORE_URL, workspace_id=WORKSPACE_ID, service_key=SERVICE_KEY,
)
# One shared local SQLite file is suitable for a single-host sandbox only.
lease_file = "./sandbox-dispatch.sqlite"
bridge = LangChainBridge(
    client,
    dispatch_lease=LocalSqliteDispatchLease(lease_file),
    async_dispatch_lease=LocalAsyncSqliteDispatchLease(lease_file),
)

def binding_provider(request):
    # Read ONLY authenticated host-managed values; never model/chat input.
    return HostBinding(
        run_id=RUN_ID, agent_id="sandbox-agent", policy_id=application_policy_id,
        authority={"role": "sandbox"}, model={"name": "host-selected-model"},
        context={"prompt_version": "v1"},
    )

middleware = create_loopgrid_middleware(bridge, binding_provider)
agent = create_agent(
    model=model, tools=[sandbox_refund], middleware=[middleware],
)
```

This is a **host-integration sketch**, not a standalone example: the uppercase configuration variables, the policy, the model, and the tool intentionally come from your application. For a fully executable no-key native example, use `scripts/native_agent_e2e.py` in the source repository. For a genuine Core integration example, use `scripts/native_core_agent_e2e.py`.

When using multiple middleware components, place LoopGrid **last/innermost** so the guarded call matches the effective handler arguments. By default **all tools are guarded**; `protected_tools` permits explicitly unguarded tools and must be reviewed carefully.

## Evidence and safety boundaries

- **Host ownership:** application code—not the LLM—provides identity, permission, policy and authenticated review.
- **Model evidence:** `observe_model()` only when a real completed model output was actually observed. The combined sample shows how to correlate a genuine native `AIMessage`; it uses a deterministic synthetic model, **not a live model-provider API call**.
- **External actions:** native tool completion is not a verified payment/refund/provider outcome. Call `record_execution()` only with a trusted, verified external receipt; call `record_outcome()` only with separately observed state.
- **Concurrency:** dispatch requires sync and async shared leases by default. The bundled SQLite lease is **single-host**, not a distributed guarantee; production needs host-managed durability/fencing and provider idempotency/reconciliation. No distributed exactly-once effect guarantee.
- **Privacy:** secrets and raw sensitive payloads are not intended for the evidence ledger; hashes of low-entropy values are potentially guessable. A remote Core endpoint requires HTTPS.
- **Scope:** the guard protects only tool calls routed through this middleware instance; it does not protect arbitrary unwrapped LangChain tools.

See [SECURITY.md](SECURITY.md), [INTEGRATION-CONTRACT.md](INTEGRATION-CONTRACT.md), [VALIDATION.md](VALIDATION.md), [architecture](docs/ARCHITECTURE-AND-BOUNDARIES.md), and [release engineering](docs/RELEASE-ENGINEERING.md).

**Project:** [LoopGrid](https://loopgrid.io/) · [GitHub](https://github.com/loopgridio/loopgrid-langchain) · [Issues](https://github.com/loopgridio/loopgrid-langchain/issues) · [Apache-2.0 License](LICENSE)

This is an independent open-source integration, not an endorsement or certification by LangChain.
