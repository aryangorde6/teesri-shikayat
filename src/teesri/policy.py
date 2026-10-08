"""Cedar guardrails. Every side effect (and every agent tool call) asks `check()` first; the decision is logged as
an EVT# item on the incident, which the console's Safety tab shows.

Fail closed: every context key has a safe default, and a policy that errors counts as DENY
(Cedar skips a forbid that errors, which would otherwise allow the action).
"""
import cedarpy

from teesri import store

# (id, human reason shown on a DENY, policy). Order matters: Cedar names them policy0, policy1, ...
POLICIES = [
    ("baseline", "", "permit(principal, action, resource);"),
    ("only-residents-close", "only residents can close a case", """
forbid(principal, action == Action::"close_case", resource)
unless { principal == Actor::"quorum_evaluator" && context.quorum_met == true };"""),
    ("no-pii-to-authority", "names and phone numbers never leave the lane", """
forbid(principal, action == Action::"send_evidence_email", resource)
when { context.fields.containsAny(["name", "names", "phone", "phones", "phone_number", "chat_id", "address"]) };"""),
    ("allowlisted-recipients", "recipient is not on the allowlist", """
forbid(principal, action in [Action::"send_evidence_email", Action::"broadcast_warning",
                             Action::"message_household", Action::"notify_volunteer"], resource)
unless { context.recipient_allowlisted == true };"""),
    ("approval-before-broadcast", "a volunteer has not approved this warning", """
forbid(principal, action == Action::"broadcast_warning", resource)
unless { context.volunteer_approved == true };"""),
    ("approved-templates-only", "only approved message templates can be broadcast", """
forbid(principal, action == Action::"broadcast_warning", resource)
unless { ["ring_warning_v1", "reopened_v1"].contains(context.template_id) };"""),
    ("consent-before-message", "this home has not given consent", """
forbid(principal, action in [Action::"broadcast_warning", Action::"message_household"], resource)
unless { context.consent == true };"""),
    ("read-only-before-approval", "while preparing a case the agent may only read", """
forbid(principal == Actor::"case_agent", action, resource)
when { context.phase == "prepare_case" }
unless { action in [Action::"get_reports", Action::"get_ring_stats", Action::"get_nearby_clinic"] };"""),
]
_TEXT = "\n".join(p for _, _, p in POLICIES)
DEFAULTS = {"quorum_met": False, "fields": [], "recipient_allowlisted": False, "volunteer_approved": False,
            "template_id": "", "consent": False, "phase": ""}


def decide(actor: str, action: str, resource: str, **context) -> tuple[bool, str, str]:
    """(allowed, policy id, reason). Pure: no logging."""
    unknown = set(context) - set(DEFAULTS)
    if unknown:
        raise ValueError(f"unknown policy context: {unknown}")
    req = {"principal": f'Actor::"{actor}"', "action": f'Action::"{action}"', "resource": resource,
           "context": {**DEFAULTS, **context}}
    r = cedarpy.is_authorized(req, _TEXT, [])
    if r.diagnostics.errors:
        return False, "evaluation-error", "; ".join(str(e) for e in r.diagnostics.errors)
    ids = [POLICIES[int(p.removeprefix("policy"))] for p in r.diagnostics.reasons]
    if r.allowed:
        return True, "baseline", ""
    return False, ", ".join(i for i, _, _ in ids), "; ".join(reason for _, reason, _ in ids)


def check(actor: str, action: str, resource: str, inc_id: str | None = None, **context) -> bool:
    allowed, pid, reason = decide(actor, action, resource, **context)
    if inc_id:
        store.log_evt(inc_id, actor=actor, action=action, resource=resource,
                      decision="ALLOW" if allowed else "DENY", policy=pid, reason=reason)
    return allowed
