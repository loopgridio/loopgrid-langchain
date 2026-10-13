# Native LangChain 1.x extension contract

The adapter uses native LangChain 1.x `AgentMiddleware` rather than LangGraph `StateGraph` node wrappers. Upstream references:

- [Custom middleware and `create_agent`](https://docs.langchain.com/oss/python/langchain/middleware/custom)
- [`AgentMiddleware.wrap_tool_call`](https://reference.langchain.com/python/langchain/agents/middleware/types/AgentMiddleware/wrap_tool_call)
- [`AgentMiddleware.awrap_tool_call`](https://reference.langchain.com/python/langchain/agents/middleware/types/AgentMiddleware/awrap_tool_call)
- [`ToolCallRequest.override`](https://reference.langchain.com/python/langgraph.prebuilt/tool_node/ToolCallRequest/override)
- [`ToolMessage.tool_call_id`](https://reference.langchain.com/python/langchain-core/messages/tool/ToolMessage)

**Observed installed SDK behavior (October 13, 2026):** on Windows Python 3.12.6 using LangChain 1.4.5, the native `create_agent` sync and async smoke passed, including handler interception and refusal to replay a duplicated consequential tool call. The separate combined test passed actual installed LangChain + LoopGrid Core 0.8.1-design-partner signed ledger verification and 100% applicable coverage. See [validation record](../VALIDATION.md).

The smoke uses a **deterministic synthetic chat model**; success does not establish live model-provider integration. Tool hooks alone are not trusted proof of a third-party business outcome. Future LangChain SDK upgrades must rerun the native handler, async, exception, policy and action evidence checks. Other unwrapped tools are outside this middleware's enforcement boundary.
