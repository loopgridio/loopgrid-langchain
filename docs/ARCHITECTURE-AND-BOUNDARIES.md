# Native LangChain adapter architecture and attack surface

## Why a separate package from LangGraph?

`loopgrid-langgraph` wraps ordinary StateGraph nodes and uses checkpoint correlation. `loopgrid-langchain` wraps the **actual LangChain 1.x tool handler** through native AgentMiddleware (sync + async). It depends directly on LangChain, not on another LoopGrid adapter. Neither package modifies Core signing semantics.

## Trust boundaries

1. LangChain `AIMessage.tool_calls` is an **untrusted proposal**, not authorization.
2. The `HostBinding` provider is trusted host code; must derive identity, policy ID, scoped permissions and run ID from authenticated application context, never chat state.
3. `ToolCallRequest.override(tool_call=snapshot(...))` supplies the actual handler with an immutable-in-practice snapshot of the committed arguments, preventing accidental TOCTOU from the caller's mutable request. Place the guard LAST in the middleware order, closest to the real ToolNode handler. This is not protection against intentionally malicious middleware operating after the guard or a compromised tool implementation.
4. Core `decision_created` records `agent`, `authority`, `model`, `context`, exact proposed tool and SHA-256 argument commitment. On idempotent re-entry compare both raw signed values and typed redaction commitments.
5. Fresh Core policy and signed review verified before dispatch. A Core `tool_requested` event conservatively reserves the attempt; no automatic retry after that point.
6. Native `ToolMessage`/`Command` records `tool_result` (local handler completion), **not** a verified external payment or business outcome. Only a trusted host integration observing a real provider/sandbox receipt may call `record_execution()` to append `tool_executed`. Separately observed downstream status may then call `record_outcome()`.
7. Workspace signature verification through Core is *service-side*. Independent offline signature verification requires pinned external public key and a suitable export.

## Non-goals

- No autonomous policy authority or reliance on LLM text as approval.
- No automatic replay of externally consequential tools after LangChain or LangGraph retries.
- No global exactly-once transaction across Core and a payment or business system.
- No guaranteed globally persistent tracing or model observation when an application does not explicitly provide it.
- No automatic masking of all PII in existing agent state or external LangSmith traces.
- No endorsement, certification, verified marketplace status or automatic LangChain docs inclusion.
