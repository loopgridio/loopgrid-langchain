# Security and trust boundaries

- Never trust agent/model/tool output for reviewer identity, policy changes, model identity or delegated authority.
- Never retry after `tool_requested` without external reconciliation; HTTP write ambiguity must fail closed.
- Core `verify_workspace()` authenticates workspace ledger only under Core's own trust roots. Detached verification needs independent trusted key and verifier.
- A successful `ToolMessage` is *not* proof of the result of an external business operation.
- Distributed exactly-once execution is **not guaranteed** by the current Core REST interface; require a durable cross-worker lease and idempotency at the downstream business system.
- The adapter does not implement a human login or reviewer authentication system; the host must authenticate reviewer and use the trusted Core review route.
- By default a shared host-supplied lease is mandatory for both sync and async dispatch. A local SQLite lease is for one host only; production multi-worker/distributed locking needs host-managed durability/fencing plus provider idempotency and reconciliation. Disabling lease enforcement is unsafe across bridge instances.
- Protected middleware must run at the innermost native tool boundary and receive the final transformed tool call; other middlewares that mutate after authorization break this assumption.
- Core key is never supplied by the model, placed into prompts, committed to source control, or included in exception bodies.
- Unknown return objects and mismatched ToolMessage IDs are ambiguous and fail for manual reconciliation rather than fabricating receipts.
- Local test Core and synthetic scripts must never be connected to production payment or notification systems.
