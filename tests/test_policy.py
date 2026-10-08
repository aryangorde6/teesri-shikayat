import pytest

from teesri import policy

INC = 'Incident::"inc-1"'
HOME = 'Household::"sim-C"'


def test_only_residents_can_close_a_case():
    assert policy.decide("case_agent", "close_case", INC)[:2] == (False, "only-residents-close")
    assert policy.decide("ward_office", "close_case", INC)[0] is False
    assert policy.decide("quorum_evaluator", "close_case", INC)[0] is False             # no quorum, no close
    assert policy.decide("quorum_evaluator", "close_case", INC, quorum_met=True)[0] is True


def test_evidence_email_never_carries_names_or_phone_numbers():
    ok, pid, reason = policy.decide("case_agent", "send_evidence_email", INC,
                                    fields=["counts", "phone_number"], recipient_allowlisted=True)
    assert (ok, pid) == (False, "no-pii-to-authority") and "never leave the lane" in reason
    assert policy.decide("case_agent", "send_evidence_email", INC, fields=["counts", "reports"],
                         recipient_allowlisted=True)[0] is True
    assert policy.decide("case_agent", "send_evidence_email", INC, fields=["counts"])[1] == "allowlisted-recipients"


def test_broadcast_needs_volunteer_approval_an_approved_template_and_consent():
    good = {"volunteer_approved": True, "template_id": "ring_warning_v1", "consent": True, "recipient_allowlisted": True}
    assert policy.decide("workflow", "broadcast_warning", HOME, **good)[0] is True
    assert policy.decide("workflow", "broadcast_warning", HOME, **{**good, "volunteer_approved": False})[1] == "approval-before-broadcast"
    assert policy.decide("workflow", "broadcast_warning", HOME, **{**good, "template_id": "free_text"})[1] == "approved-templates-only"
    assert policy.decide("workflow", "broadcast_warning", HOME, **{**good, "consent": False})[1] == "consent-before-message"


def test_agent_may_only_read_while_preparing_a_case():
    assert policy.decide("case_agent", "get_reports", INC, phase="prepare_case")[0] is True
    assert policy.decide("case_agent", "send_evidence_email", INC, phase="prepare_case", fields=["counts"],
                         recipient_allowlisted=True)[1] == "read-only-before-approval"


def test_unknown_context_is_rejected_not_ignored():
    with pytest.raises(ValueError):
        policy.decide("workflow", "broadcast_warning", HOME, volunteer_aproved=True)  # typo must not slip through
