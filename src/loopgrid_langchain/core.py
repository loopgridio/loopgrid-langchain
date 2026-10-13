"""Restricted LoopGrid Core REST client. No secrets are read from ambient environment."""
from __future__ import annotations
import re
from urllib.parse import urlsplit
from typing import Any
import httpx

class LoopGridError(RuntimeError):
    """Sanitized API/transport error without response bodies or credentials."""

def validate_origin(origin: str) -> str:
    if not isinstance(origin, str):
        raise ValueError("Core origin must be a string")
    try:
        u = urlsplit(origin)
        host = (u.hostname or "").lower()
        localhost = host in ("localhost", "127.0.0.1", "::1")
        if (u.scheme != "https" and not (u.scheme == "http" and localhost)) or not host:
            raise ValueError("Core requires HTTPS except loopback HTTP")
        if u.username or u.password or u.query or u.fragment or u.path not in ("", "/") or u.port == 0:
            raise ValueError("Core origin cannot contain credentials, path, query or fragment")
        if re.search(r"[\\\s]", origin):
            raise ValueError("Unsafe Core origin")
        return origin.rstrip("/")
    except (ValueError, TypeError) as exc:
        raise ValueError("Invalid Core origin") from None


def require_id(s: str) -> str:
    if not isinstance(s, str) or not re.fullmatch(r"[a-zA-Z0-9_-]{1,160}", s):
        raise ValueError("Invalid identifier")
    return s

class CoreClient:
    def __init__(self, *, base_url: str, workspace_id: str, service_key: str | None = None,
                 timeout: float = 15.0, transport: httpx.BaseTransport | None = None):
        self.base_url = validate_origin(base_url)
        self.workspace_id = require_id(workspace_id)
        if not 0 < timeout <= 60: raise ValueError("Invalid timeout")
        self._http = httpx.Client(base_url=self.base_url, timeout=timeout, transport=transport,
                                  trust_env=False, follow_redirects=False,
                                  headers={"X-LoopGrid-Key": service_key} if service_key else {})

    def _request(self, method: str, path: str, *, body: dict | None = None) -> dict:
        # All paths supplied internally only; IDs must be checked at boundaries.
        try:
            with self._http.stream(method, path, json=body) as r:
                if not 200 <= r.status_code < 300:
                    raise LoopGridError(f"LoopGrid Core HTTP {r.status_code}")
                raw = bytearray()
                for piece in r.iter_bytes():
                    raw.extend(piece)
                    if len(raw) > 2_000_000: raise LoopGridError("Core response too large")
                try: result = httpx.Response(200, content=bytes(raw)).json()
                except ValueError: raise LoopGridError("Core returned invalid JSON") from None
                if not isinstance(result, dict): raise LoopGridError("Unexpected Core response type")
                return result
        except LoopGridError: raise
        except httpx.HTTPError: raise LoopGridError("LoopGrid Core transport failure") from None

    def create_decision(self, payload: dict) -> dict:
        return self._request("POST", "/api/v1/decisions", body={**payload, "workspace_id": self.workspace_id})

    def add_event(self, decision_id: str, kind: str, payload: dict, *, actor_type: str = "integration",
                  actor_id: str = "loopgrid-langchain", idempotency_key: str | None = None) -> dict:
        return self._request("POST", f"/api/v1/decisions/{require_id(decision_id)}/events", body={
            "event_type":kind, "actor_type": actor_type, "actor_id":actor_id,
            "payload":payload, "idempotency_key":idempotency_key})

    def evaluate_policy(self, policy_id: str, action: dict, authority: dict, context: dict) -> dict:
        return self._request("POST", f"/api/v1/workspaces/{self.workspace_id}/policies/evaluate", body={
            "policy_id":require_id(policy_id), "proposed_action":action,
            "authority":authority,"context":context})

    def get_decision(self, decision_id: str) -> dict:
        return self._request("GET", f"/api/v1/decisions/{require_id(decision_id)}")

    def verify_workspace(self) -> dict:
        return self._request("GET", f"/api/v1/integrity/verify?workspace_id={self.workspace_id}")

    def review(self, decision_id: str, action: str, reviewer: str, reason: str = "") -> dict:
        if action not in {"approve", "reject"} or not reviewer:
            raise ValueError("Explicit authenticated review required")
        return self._request("POST", f"/api/v1/decisions/{require_id(decision_id)}/review", body={
            "action":action, "reviewer":reviewer,"reason":reason})

    def close(self): self._http.close()
