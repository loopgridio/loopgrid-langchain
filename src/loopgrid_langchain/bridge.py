"""LangChain 1.x guarded tool boundary backed by LoopGrid Core signed evidence.

Do not treat agent messages, model-supplied metadata, tracing callbacks or
ToolMessage content as authorization or authoritative business outcomes.
"""
from __future__ import annotations

import asyncio
from contextlib import nullcontext
from dataclasses import dataclass
import hashlib
import inspect
import json
import threading
from typing import Any, Callable, Mapping, ContextManager, AsyncContextManager

from .core import require_id

FRAMEWORK = "langchain"
VERSION = "0.1.0"


class EvidenceInvalid(RuntimeError):
    """Trusted Core evidence is absent, changed, or inconsistent."""


class PolicyDenied(RuntimeError):
    """The Core policy or signed review prohibits the proposed action."""


class ApprovalRequired(RuntimeError):
    """Core requires a separate authenticated human review before execution."""


class ReconciliationRequired(RuntimeError):
    """A dispatch may have occurred. Reconcile externally; never retry blindly."""


def canonical_json(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False,
                      allow_nan=False).encode("utf-8")


def snapshot(value: Any) -> Any:
    return json.loads(canonical_json(value))


def commitment(value: Any) -> str:
    return hashlib.sha256(canonical_json(value)).hexdigest()


def idem(*parts: Any) -> str:
    return "lg-langchain-" + commitment(parts)


def mapping(value: Any, name: str) -> dict:
    if not isinstance(value, Mapping):
        raise ValueError(f"{name} must be a mapping")
    result = snapshot(dict(value))
    if not isinstance(result, dict):
        raise ValueError(f"{name} must be a JSON object")
    return result


def signed_matches(signed: Any, expected: Any) -> bool:
    """Compare actual Core redaction commitments, never treat redaction as a wildcard.

    Only use this after verify_workspace() successfully verifies the Core ledger.
    """
    if isinstance(signed, dict) and signed.get("redacted") is True:
        return (set(signed) == {"redacted", "sha256", "type"}
                and isinstance(signed.get("sha256"), str)
                and len(signed["sha256"]) == 64
                and signed.get("type") == type(expected).__name__
                and signed["sha256"] == commitment(expected))
    if type(signed) is not type(expected):
        return False
    if isinstance(signed, dict):
        return signed.keys() == expected.keys() and all(
            signed_matches(signed[k], expected[k]) for k in signed)
    if isinstance(signed, list):
        return len(signed) == len(expected) and all(
            signed_matches(s, e) for s, e in zip(signed, expected))
    return signed == expected


def _events(detail: dict) -> list[dict]:
    events = detail.get("events")
    if not isinstance(events, list) or not events:
        raise EvidenceInvalid("Signed decision history unavailable")
    return events


def _payload(event: dict) -> dict:
    payload = event.get("payload")
    if not isinstance(payload, dict):
        raise EvidenceInvalid("Signed decision payload unavailable")
    return payload


@dataclass(frozen=True)
class HostBinding:
    """Values supplied by authenticated application code, NEVER by the language model.

    run_id must be stable for retries, unique across distinct agent invocations.
    The application must enforce authority, reviewer identity and actual actions.
    """
    run_id: str
    agent_id: str
    policy_id: str
    authority: Mapping[str, Any]
    model: Mapping[str, Any]
    context: Mapping[str, Any]


def validate_binding(binding: HostBinding) -> tuple[dict, dict, dict]:
    if not isinstance(binding, HostBinding):
        raise TypeError("Expected host-owned HostBinding")
    for ident in (binding.run_id, binding.agent_id, binding.policy_id):
        require_id(ident)
    authority = mapping(binding.authority, "authority")
    model = mapping(binding.model, "model")
    context = mapping(binding.context, "context")
    if not authority or not context or not model.get("name"):
        raise ValueError("Explicit host authority, context and model identity required")
    if any(k in context for k in ("run_id", "tool_call_id")):
        raise ValueError("Host context cannot override reserved correlation fields")
    return authority, model, context


def parse_tool_call(call: Mapping[str, Any]) -> tuple[str, str, dict]:
    call = mapping(call, "tool_call")
    name = require_id(call.get("name"))
    call_id = require_id(call.get("id"))
    args = mapping(call.get("args"), "tool_call.args")
    return name, call_id, args


class LangChainBridge:
    """Core-backed exact-action authorization for one LangChain tool handler.

    A signed `tool_requested` event is a conservative irreversible replay barrier.
    A shared dispatch lease is required by default. The optional explicit
    single-process opt-out is UNSAFE across distinct bridge instances/workers.
    Even a durable lease cannot guarantee a downstream exactly-once action.
    """

    def __init__(self, client: Any, *, dispatch_lease: Callable[[str], ContextManager[Any]] | None = None,
                 async_dispatch_lease: Callable[[str], AsyncContextManager[Any]] | None = None,
                 require_dispatch_lease: bool = True):
        self.client = client
        self._lock = threading.RLock()
        self._async_lock = asyncio.Lock()
        self._dispatch_lease = dispatch_lease
        self._async_dispatch_lease = async_dispatch_lease
        self.require_dispatch_lease = require_dispatch_lease
        if dispatch_lease is not None and not callable(dispatch_lease):
            raise TypeError("dispatch_lease must be callable")
        if async_dispatch_lease is not None and not callable(async_dispatch_lease):
            raise TypeError("async_dispatch_lease must be callable")

    def _verified_events(self, decision_id: str) -> list[dict]:
        proof = self.client.verify_workspace()
        if (proof.get("valid") is not True or proof.get("failures")
                or proof.get("workspace_id") not in (None, self.client.workspace_id)):
            raise EvidenceInvalid("Signed Core workspace verification failed")
        detail = self.client.get_decision(require_id(decision_id))
        if (detail.get("summary") or {}).get("workspace_id") != self.client.workspace_id:
            raise EvidenceInvalid("Decision workspace mismatch")
        return _events(detail)

    def _check_created(self, events: list[dict], spec: dict, binding: HostBinding,
                       authority: dict, model: dict, context: dict) -> None:
        created = next((e for e in events if e.get("event_type") == "decision_created"), None)
        if created is None:
            raise EvidenceInvalid("Missing decision_created")
        payload = _payload(created)
        expected_context = {**context, "run_id": binding.run_id,
                            "tool_call_id": spec["tool_call_id"]}
        if (payload.get("proposed_action") != spec
                or not signed_matches(payload.get("agent"), {"id": binding.agent_id})
                or not signed_matches(payload.get("authority"), authority)
                or not signed_matches(payload.get("model"), model)
                or not signed_matches(payload.get("context"), expected_context)):
            raise EvidenceInvalid("Signed decision identity or action changed")

    def propose(self, call: Mapping[str, Any], binding: HostBinding) -> dict:
        """Create or idempotently recover a decision for an exact native tool call."""
        tool, tool_call_id, args = parse_tool_call(call)
        authority, model, context = validate_binding(binding)
        if "tool" in args:
            raise ValueError("tool arguments cannot override trusted tool identity")
        spec = {"tool": tool, "arguments_sha256": commitment(args),
                "run_id": binding.run_id, "tool_call_id": tool_call_id,
                "policy_id": binding.policy_id}
        created = self.client.create_decision({
            "decision_type": "agent_tool_action",
            "service_name": "loopgrid-langchain",
            "privacy_mode": "redacted",
            "agent": {"id": binding.agent_id},
            "model": model, "authority": authority,
            "context": {**context, "run_id": binding.run_id,
                        "tool_call_id": tool_call_id},
            "proposed_action": spec,
            "metadata": {"framework": FRAMEWORK, "integration_version": VERSION},
            "idempotency_key": idem("create", self.client.workspace_id,
                                    binding.run_id, tool_call_id),
        })
        decision_id = require_id(created["decision_id"])
        if created.get("idempotent_replay"):
            events = self._verified_events(decision_id)
            self._check_created(events, spec, binding, authority, model, context)
        policy_input = {"tool": tool, **args}
        policy = self.client.evaluate_policy(binding.policy_id, policy_input,
                                             authority, context)
        if (policy.get("policy_id") != binding.policy_id
                or policy.get("decision") not in {"auto_allowed", "blocked",
                    "manual_review_required", "human_approval_required"}
                or not all(policy.get(k) for k in (
                    "version", "policy_digest", "input_commitment"))):
            raise EvidenceInvalid("Core policy provenance missing or invalid")
        if created.get("idempotent_replay"):
            prev_event = next((e for e in events if e.get("event_type") == "policy_evaluated"), None)
            if prev_event is None:
                raise EvidenceInvalid("Replayed decision lacks signed policy")
            prev = _payload(prev_event)
            keys = ("policy_id", "version", "policy_digest", "input_commitment", "decision")
            if any(prev.get(k) != policy.get(k) for k in keys):
                raise PolicyDenied("Current policy differs from signed proposal")
        else:
            self.client.add_event(decision_id, "policy_evaluated", policy,
                                  actor_type="policy", actor_id=binding.policy_id,
                                  idempotency_key=idem("policy", self.client.workspace_id, decision_id))
        # No raw tool args returned or retained in the bridge scope.
        return {"decision_id": decision_id, "spec": spec, "policy": policy,
                "agent_id": binding.agent_id, "authority": authority,
                "model": model, "context": context}

    def _preflight_and_reserve(self, scope: Mapping, call: Mapping, binding: HostBinding) -> tuple[str, str, str, dict]:
        tool, tool_call_id, args = parse_tool_call(call)
        authority, model, context = validate_binding(binding)
        saved = mapping(scope, "scope")
        spec = saved.get("spec")
        expected_spec = {"tool": tool, "arguments_sha256": commitment(args),
                         "run_id": binding.run_id, "tool_call_id": tool_call_id,
                         "policy_id": binding.policy_id}
        if (spec != expected_spec or saved.get("agent_id") != binding.agent_id
                or saved.get("authority") != authority or saved.get("model") != model
                or saved.get("context") != context):
            raise EvidenceInvalid("Host/tool binding changed before dispatch")
        decision_id = require_id(saved.get("decision_id"))
        events = self._verified_events(decision_id)
        self._check_created(events, spec, binding, authority, model, context)
        if any(e.get("event_type") in ("tool_requested", "tool_executed", "tool_result", "outcome_observed")
               for e in events):
            raise ReconciliationRequired("Prior dispatch reservation exists")
        recorded = next((e for e in events if e.get("event_type") == "policy_evaluated"), None)
        if recorded is None:
            raise EvidenceInvalid("Missing signed policy decision")
        prior = _payload(recorded)
        policy = saved.get("policy") or {}
        fields = ("policy_id", "version", "policy_digest", "input_commitment", "decision")
        if any(prior.get(k) != policy.get(k) or not prior.get(k) for k in fields):
            raise EvidenceInvalid("Signed policy evidence changed")
        current = self.client.evaluate_policy(binding.policy_id,
                                              {"tool": tool, **args}, authority, context)
        if any(current.get(k) != policy.get(k) for k in fields):
            raise PolicyDenied("Current Core policy changed; create a new decision")
        if policy["decision"] in ("blocked", "manual_review_required"):
            raise PolicyDenied("Core policy did not authorize this action")
        if any(e.get("event_type") == "human_rejected" for e in events):
            raise PolicyDenied("Signed human rejection is terminal")
        if policy["decision"] == "human_approval_required":
            reviews = [e for e in events if e.get("event_type") in ("human_approved", "human_rejected")]
            if not reviews:
                raise ApprovalRequired("Core signed human approval required")
            if reviews[-1]["event_type"] != "human_approved" or _payload(reviews[-1]).get("approved") is not True:
                raise PolicyDenied("Signed human approval absent")
        reservation = self.client.add_event(decision_id, "tool_requested", {
            "framework": FRAMEWORK, "tool": tool, "arguments_sha256": commitment(args),
            "run_id": binding.run_id, "tool_call_id": tool_call_id,
        }, actor_type="tool", actor_id=tool,
            idempotency_key=idem("tool-request", self.client.workspace_id, decision_id))
        if isinstance(reservation, Mapping) and reservation.get("idempotent_replay") is True:
            raise ReconciliationRequired("Tool request previously reserved")
        return decision_id, tool, tool_call_id, args

    def _record_result(self, decision_id: str, tool: str, tool_call_id: str, result: Any) -> None:
        # Native LangChain returns ToolMessage or LangGraph Command. Never serialize
        # an arbitrary Python repr or treat the result as an external business receipt.
        kind = type(result).__name__
        if kind == "ToolMessage" and hasattr(result, "tool_call_id"):
            if result.tool_call_id != tool_call_id:
                raise ReconciliationRequired("Handler result tool_call_id mismatch")
            content_hash = commitment(result.content)
            if getattr(result, "status", "success") == "error":
                self.client.add_event(decision_id, "tool_result", {
                    "framework": FRAMEWORK, "tool": tool, "status": "error",
                    "result_sha256": content_hash, "external_outcome_verified": False,
                }, actor_type="tool", actor_id=tool)
                return
            detail = {"framework": FRAMEWORK, "tool": tool, "status": "returned",
                      "result_sha256": content_hash, "external_outcome_verified": False}
        elif kind == "Command" and type(result).__module__.startswith("langgraph"):
            detail = {"framework": FRAMEWORK, "tool": tool, "status": "command_returned",
                      "external_outcome_verified": False}
        else:
            raise ReconciliationRequired("Unexpected native handler result; reconcile")
        self.client.add_event(decision_id, "tool_result", detail,
                              actor_type="tool", actor_id=tool)

    def dispatch(self, scope: Mapping, call: Mapping, binding: HostBinding,
                 handler: Callable[[], Any]) -> Any:
        if self.require_dispatch_lease and self._dispatch_lease is None:
            raise ReconciliationRequired("Durable shared synchronous dispatch lease required")
        lease_key = idem("lease", self.client.workspace_id, binding.run_id, call.get("id"))
        lock = self._dispatch_lease(lease_key) if self._dispatch_lease else nullcontext()
        with lock, self._lock:
            decision_id, tool, tool_call_id, _ = self._preflight_and_reserve(scope, call, binding)
            try:
                result = handler()
                if inspect.isawaitable(result):
                    if inspect.iscoroutine(result):
                        result.close()
                    raise TypeError("Sync tool handler returned an awaitable")
            except BaseException:
                try:
                    self.client.add_event(decision_id, "tool_result", {
                        "framework": FRAMEWORK, "tool": tool, "status": "error",
                        "external_outcome_verified": False}, actor_type="tool", actor_id=tool)
                except Exception:
                    pass
                raise ReconciliationRequired("Tool may have run; reconcile external state") from None
            try:
                self._record_result(decision_id, tool, tool_call_id, result)
            except Exception:
                raise ReconciliationRequired("Tool returned but receipt not verified; reconcile") from None
            return result

    async def dispatch_async(self, scope: Mapping, call: Mapping, binding: HostBinding,
                             handler: Callable[[], Any]) -> Any:
        if self.require_dispatch_lease and self._async_dispatch_lease is None:
            raise ReconciliationRequired("Durable shared asynchronous dispatch lease required")
        lease_key = idem("lease", self.client.workspace_id, binding.run_id, call.get("id"))
        from contextlib import asynccontextmanager
        @asynccontextmanager
        async def noop():
            yield
        lock = self._async_dispatch_lease(lease_key) if self._async_dispatch_lease else noop()
        async with lock, self._async_lock:
            decision_id, tool, tool_call_id, _ = await asyncio.to_thread(
                self._preflight_and_reserve, scope, call, binding)
            try:
                result = await handler()
            except BaseException:
                try:
                    await asyncio.to_thread(self.client.add_event, decision_id, "tool_result", {
                        "framework": FRAMEWORK, "tool": tool, "status": "error",
                        "external_outcome_verified": False}, actor_type="tool", actor_id=tool)
                except Exception:
                    pass
                raise ReconciliationRequired("Async tool may have run; reconcile external state") from None
            try:
                await asyncio.to_thread(self._record_result, decision_id, tool, tool_call_id, result)
            except Exception:
                raise ReconciliationRequired("Async result receipt failed; reconcile") from None
            return result

    def observe_model(self, decision_id: str, *, model_name: str, observed: Any,
                      source: str) -> dict:
        if not model_name or not source:
            raise ValueError("Actual observed model and source required")
        self._verified_events(require_id(decision_id))
        return self.client.add_event(decision_id, "model_completed", {
            "framework": FRAMEWORK, "model": model_name, "source": source,
            "output_sha256": commitment(observed)}, actor_type="agent",
            actor_id="host-model-observer",
            idempotency_key=idem("model", self.client.workspace_id, decision_id, commitment(observed)))

    def record_execution(self, decision_id: str, *, external_reference: str,
                         source: str, status: str, receipt: Mapping) -> dict:
        """Attest a host-verified execution receipt, not a LangChain handler return.

        Caller is trusted application integration code which actually consulted a
        downstream action system or a clearly identified sandbox. The adapter
        cannot verify provider identity or turn a fabricated receipt into truth.
        No raw provider receipt is stored; only its canonical SHA-256 commitment.
        """
        for field in (external_reference, source, status):
            if not isinstance(field, str) or not field.strip():
                raise ValueError("Trusted action receipt provenance required")
        if status not in ("succeeded", "confirmed", "accepted", "sandbox_confirmed"):
            raise ValueError("Only an explicitly confirmed action receipt may establish execution")
        receipt_hash = commitment(mapping(receipt, "receipt"))
        decision_id = require_id(decision_id)
        events = self._verified_events(decision_id)
        if any(e.get("event_type") == "tool_executed" for e in events):
            raise ReconciliationRequired("Execution receipt already recorded; reconcile")
        completed = [e for e in events if e.get("event_type") == "tool_result"]
        if not completed or _payload(completed[-1]).get("status") not in ("returned", "command_returned"):
            raise EvidenceInvalid("Missing successful native handler result")
        return self.client.add_event(decision_id, "tool_executed", {
            "framework": FRAMEWORK, "source": source,
            "external_reference": external_reference, "status": status,
            "receipt_sha256": receipt_hash,
            "receipt_provenance": "trusted_host_attestation",
            "sandbox": source.startswith("sandbox"),
        }, actor_type="integration", actor_id="host-action-receipt",
            idempotency_key=idem("execution", self.client.workspace_id, decision_id,
                                 external_reference))

    def record_outcome(self, decision_id: str, *, external_reference: str,
                       source: str, status: str, observed: Mapping) -> dict:
        for value in (external_reference, source, status):
            if not isinstance(value, str) or not value.strip():
                raise ValueError("Host-observed external outcome provenance required")
        events = self._verified_events(require_id(decision_id))
        if not any(e.get("event_type") == "tool_executed" for e in events):
            raise EvidenceInvalid("No signed successful tool execution receipt")
        return self.client.add_event(decision_id, "outcome_observed", {
            "status": status, "source": source, "external_reference": external_reference,
            "observed_sha256": commitment(mapping(observed, "observed")),
            "source_attested_by_host": True,
        }, actor_type="integration", actor_id="host-outcome-observer",
            idempotency_key=idem("outcome", self.client.workspace_id, decision_id, external_reference))
