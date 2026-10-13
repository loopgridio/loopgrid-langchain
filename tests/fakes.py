"""Synthetic Core; does not cryptographically sign. Real Core E2E is separate."""
import copy
import uuid
from loopgrid_langchain.bridge import commitment

class FakeCore:
    workspace_id = "ws_test"
    def __init__(self):
        self.decisions = {}
        self.keys = {}
        self.outage = set()
        self.valid = True
        self.version = "1"
        self.digest = "policy-digest"
        self.dispatch_requests = 0
        self.typed_redaction = False
        self.duplicate_reservation = False
    def _fail(self, kind):
        if kind in self.outage:
            raise RuntimeError("Synthetic Core outage")
    def create_decision(self, payload):
        self._fail("create")
        key = payload["idempotency_key"]
        if key in self.keys:
            return {"decision_id": self.keys[key], "idempotent_replay": True}
        did = "dec_" + uuid.uuid4().hex[:24]
        self.keys[key] = did
        original = copy.deepcopy(payload)
        if self.typed_redaction:
            for field in ("model", "context"):
                for k,v in original[field].items():
                    if field == "model" and k != "name":
                        continue
                    if field == "context" and k in ("run_id","tool_call_id"):
                        continue
                    original[field][k] = {"redacted":True, "sha256":commitment(v),"type":type(v).__name__}
        self.decisions[did] = {"summary":{"workspace_id":self.workspace_id},
                               "events":[{"event_type":"decision_created","payload":original}]}
        return {"decision_id": did}
    def add_event(self, decision_id, kind, payload, **kwargs):
        self._fail(kind)
        if kind == "tool_requested":
            self.dispatch_requests += 1
            if self.duplicate_reservation:
                return {"idempotent_replay": True}
        entry = {"event_type":kind, "payload":copy.deepcopy(payload)}
        self.decisions[decision_id]["events"].append(entry)
        return entry
    def evaluate_policy(self, policy_id, action, authority, context):
        self._fail("policy")
        amount = action.get("amount", 0)
        verdict = "blocked" if amount > 1500 else ("human_approval_required" if amount > 500 else "auto_allowed")
        return {"policy_id":policy_id,"version":self.version,"policy_digest":self.digest,
                "input_commitment":commitment({"action":action,"authority":authority,"context":context}),
                "decision":verdict}
    def get_decision(self, did):
        self._fail("get")
        return copy.deepcopy(self.decisions[did])
    def verify_workspace(self):
        self._fail("verify")
        return {"valid":self.valid,"failures":[] if self.valid else [{"seq":1}],
                "workspace_id":self.workspace_id}
    def review(self, did, action, reviewer):
        self._fail("review")
        if action not in ("approve","reject"):
            raise ValueError("action")
        return self.add_event(did,"human_approved" if action=="approve" else "human_rejected",
                              {"approved": action=="approve", "reviewer":reviewer})

class ToolMessage:
    def __init__(self, content="synthetic", tool_call_id="call_1", status="success"):
        self.content=content;self.tool_call_id=tool_call_id;self.status=status
