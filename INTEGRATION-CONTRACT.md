# LoopGrid LangChain v0.1.0 integration contract

- **Native extension:** `langchain.agents.middleware.AgentMiddleware.wrap_tool_call` and `awrap_tool_call`, not LangGraph `StateGraph` nodes and not observational callbacks.
- **One decision per consequential tool call**, correlated by host `run_id` and model tool-call `id`; Core idempotency refuses replay or changing signed context.
- **Authority:** host `HostBinding` from application-controlled source; never model text, tool args, chat messages or AI-generated permission.
- **Created evidence:** `decision_created` includes agent/model/authority/context, redacted `proposed_action` (tool, run/call identity, argument SHA-256 and policy ID).
- **Policy:** genuine Core policy ID/version/digest/input commitment/verdict, signed `policy_evaluated`, refreshed immediately before dispatch.
- **Review:** signed `human_approved` from trusted real Core review; missing approval blocks; rejection terminal.
- **Handler boundary:** `tool_requested` is written before exact native tool handler runs and is a conservative replay barrier. All subsequent attempts require external reconciliation.
- **Native handler result:** returned ToolMessage content commitment or supported Command marker maps to `tool_result` only; errors do not imply a successful downstream action.
- **Execution receipt:** trusted host-observed provider/sandbox confirmation is explicitly appended using `record_execution` as `tool_executed`, with provenance and committed receipt, not raw secret content.
- **Observed outcome:** a distinct host-observed downstream status via `record_outcome` after confirmed execution; no model or callback can self-certify an external business outcome. No raw model/tool/provider secret payloads stored by default.
- **Model evidence:** only host-observed genuine completed model output via explicit `observe_model()`, optionally called from `on_proposed` after inspecting an actual native AIMessage; never inferred from an intended model call.
- **Outcomes:** only host-recorded observed external outcome with reference and source, never inferred from ToolMessage success.
- **Verification:** signed workspace chain checked before consequential execution, distinct from independent offline ledger verification with trusted public key.
- **Retry/concurrency:** shared sync/async dispatch lease required **by default**; in-process locks alone are insufficient. Production requires cross-worker/distributed durability/fencing and external action idempotency/reconciliation. SQLite helper single host only.
- **Async:** native LangChain async tool interception; Core synchronous operations moved to worker threads, host must provide async distributed lease for production.
- **Scope:** selected tools only if `protected_tools` is given; does not provide universal LangChain agent enforcement outside the registered middleware instance.
- **Privacy:** SHA-256 alone does not anonymize low-entropy arguments; Core records commitments and deployment must protect model/context/host identities.
