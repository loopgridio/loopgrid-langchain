"""Native LangChain 1.x AgentMiddleware factory; no LangGraph-node aliasing."""
from __future__ import annotations
import asyncio
import inspect
from typing import Any, Callable, Collection
from .bridge import HostBinding, LangChainBridge, EvidenceInvalid, parse_tool_call, snapshot


def create_loopgrid_middleware(
    bridge: LangChainBridge,
    binding_provider: Callable[[Any], HostBinding],
    *,
    protected_tools: Collection[str] | None = None,
    on_proposed: Callable[[dict, Any], None] | None = None,
):
    """Return a genuine LangChain AgentMiddleware guarding actual tool handlers.

    `binding_provider` is trusted host code; it must not copy identity, policy or
    authority from model messages or request.state. By default ALL tools guarded.
    With `protected_tools`, other tools are deliberately passed through unguarded.
    Put this middleware LAST (innermost) in create_agent(middleware=[...])
    so it observes the final tool call after other middleware transformations.
    """
    from langchain.agents.middleware import AgentMiddleware

    if not callable(binding_provider):
        raise TypeError("binding_provider must be callable")
    if inspect.iscoroutinefunction(binding_provider):
        raise TypeError("binding_provider must synchronously return host-owned binding")
    if on_proposed is not None and (not callable(on_proposed) or inspect.iscoroutinefunction(on_proposed)):
        raise TypeError("on_proposed must be a synchronous trusted host callback")
    names = None if protected_tools is None else frozenset(protected_tools)
    if names is not None and not all(isinstance(x, str) and x for x in names):
        raise ValueError("protected_tools must contain nonempty names")

    def inspect_target(request, tool_name: str, guarded: bool) -> None:
        # The name in tool_call and the actual BaseTool object must agree.
        # ToolCallRequest.override does not allow swapping request.tool, so
        # a mismatched pair could otherwise bypass a protected-tools filter.
        concrete = getattr(request, "tool", None)
        if concrete is None:
            if guarded:
                raise EvidenceInvalid("Protected native tool object is missing")
            return
        real_name = getattr(concrete, "name", None)
        if real_name != tool_name:
            raise EvidenceInvalid("Native tool object/name mismatch")

    class LoopGridDecisionMiddleware(AgentMiddleware):
        def wrap_tool_call(self, request, handler):
            call = snapshot(request.tool_call)
            tool, _, _ = parse_tool_call(call)
            guarded = names is None or tool in names
            inspect_target(request, tool, guarded)
            if not guarded:
                return handler(request)
            if not callable(getattr(request, "override", None)):
                raise TypeError("Native ToolCallRequest.override is required for protected tools")
            binding = binding_provider(request)
            # The actual handler must receive the same snapshotted arguments that
            # were signed and authorized; never forward a concurrently mutable call.
            frozen = request.override(tool_call=snapshot(call))
            scope = bridge.propose(call, binding)
            if on_proposed is not None:
                on_proposed(scope, request)  # Genuine model evidence, if host actually observed it
            return bridge.dispatch(scope, call, binding, lambda: handler(frozen))

        async def awrap_tool_call(self, request, handler):
            call = snapshot(request.tool_call)
            tool, _, _ = parse_tool_call(call)
            guarded = names is None or tool in names
            inspect_target(request, tool, guarded)
            if not guarded:
                return await handler(request)
            if not callable(getattr(request, "override", None)):
                raise TypeError("Native ToolCallRequest.override is required for protected tools")
            binding = binding_provider(request)
            if asyncio.iscoroutine(binding) or hasattr(binding, "__await__"):
                raise TypeError("binding_provider must synchronously supply trusted host binding")
            frozen = request.override(tool_call=snapshot(call))
            scope = await asyncio.to_thread(bridge.propose, call, binding)
            if on_proposed is not None:
                await asyncio.to_thread(on_proposed, scope, request)
            return await bridge.dispatch_async(scope, call, binding, lambda: handler(frozen))

    return LoopGridDecisionMiddleware()
