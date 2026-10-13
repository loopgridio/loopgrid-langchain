# Changelog

## 0.1.0 — Initial release

Initial version of the independent `loopgrid-langchain` Python integration:

- Genuine LangChain 1.x `AgentMiddleware` covering synchronous and asynchronous tool execution.
- Decision-scoped model/context/authority correlation, SHA-256 proposal commitments, signed LoopGrid Core policy and review verification.
- Fail-closed conservative dispatch reservation, shared-leasing requirement, durable single-host SQLite lease helpers, and replay rejection.
- Exact tool argument snapshot and tool-object/name consistency checks.
- Native `tool_result` separated from trusted application `tool_executed` receipts and independently observed `outcome_observed` evidence.
- Explicit genuine model observation, privacy-preserving commitments, E2E scripts, security regression suite and cross-platform CI configuration.

See [VALIDATION.md](VALIDATION.md) for dated test evidence and [SECURITY.md](SECURITY.md) for security boundaries. This version does not claim third-party marketplace validation, live model-provider execution or production operational certification.
