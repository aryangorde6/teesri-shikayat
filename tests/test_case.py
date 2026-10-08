from teesri import case, policy, scenario, store, texts, tripwire, workflow

DIRTY = {"colour": "brown", "smell": True, "since_days": 2, "illness": [], "vulnerable": []}


class FakeSfn:
    def __init__(self):
        self.done = {}

    def send_task_success(self, taskToken, output):
        if taskToken in self.done:
            raise RuntimeError("token used twice")
        self.done[taskToken] = output


def incident(env):
    """The demo: A and B reported, the phone's report is the third. The phone also plays the volunteer."""
    store.upsert_household("tg42", lat=18.9622, lon=72.8368, ward="B", channel="telegram", consent_ts="2026-10-08T00:00:00Z")
    store.set_config("volunteer", hh_id="tg42")
    scenario.seed()
    for r in sorted(store.scan_prefix("RPT#"), key=lambda r: r["ts"]):
        tripwire.evaluate(store.get_report(r["PK"][4:]))
    store.put_report("tg42-1", store.get_household("tg42"), DIRTY, "nova")
    assert tripwire.evaluate(store.get_report("tg42-1")) == "incident"
    [inc] = store.scan_prefix("INC#")
    env.clear()
    return inc["inc_id"]


def evts(inc_id, action):
    return [(e["actor"], e["decision"], e.get("policy")) for e in store.events(inc_id) if e["action"] == action]


def test_closure_quorum_rules():
    yes, no = {"clean": True}, {"clean": False}
    assert case.closure_outcome([yes, yes, yes]) == "CLOSED_AT_TAP"
    assert case.closure_outcome([yes, yes, yes, no]) == "REOPENED"
    assert case.closure_outcome([]) == "STILL_OPEN"         # silence never closes a case
    assert case.closure_outcome([yes, yes]) == "STILL_OPEN"


def test_full_case_ward_says_resolved_residents_say_no(env, monkeypatch):
    sfn = FakeSfn()
    monkeypatch.setattr(workflow, "_sfn", lambda: sfn)
    inc_id = incident(env)

    case.prepare({"inc_id": inc_id})
    brief = store.get_incident(inc_id)["brief_hi"]
    assert brief.startswith("3 पड़ोसी घरों से गंदे पानी की शिकायत") and "बच्चे को दस्त" in brief

    case.ask_volunteer({"inc_id": inc_id, "token": "T-approve"})
    [(to, card)] = env
    assert to == "tg42" and "3 घर · 212 मीटर · 71 घंटे" in card
    short = store.get_incident(inc_id)["approve_tok"]
    assert workflow.approve("sim-C", short, True) == texts.EXPIRED          # only the volunteer can approve
    assert workflow.approve("tg42", short, True) == texts.APPROVED_ACK
    assert sfn.done["T-approve"] == '{"approved": true}'

    homes = case.ring({"inc_id": inc_id})["homes"]
    assert len(homes) == 23
    assert all(case.warn_home({"inc_id": inc_id, "hh_id": h})["sent"] for h in homes)
    assert sum(1 for _, text in env if text.startswith("⚠️ चेतावनी")) == 23 and "जे. जे. अस्पताल" in env[-1][1]
    assert case.warned({"inc_id": inc_id}) == {"warned": 23, "never_complained": 20}

    case.notify_ward({"inc_id": inc_id})
    [mail] = [i for i in store.table().scan()["Items"] if i["SK"].startswith("MAIL#")]
    assert "3 households within 212 m" in mail["body"] and "tg42" not in mail["body"]
    assert evts(inc_id, "send_evidence_email") == [("workflow", "ALLOW", "baseline")]

    case.await_reply({"inc_id": inc_id, "token": "T-ward"})
    assert workflow.ward_reply(inc_id, "Resolved") and sfn.done["T-ward"] == '{"text": "Resolved"}'
    env.clear()
    case.handle_reply({"inc_id": inc_id, "reply": {"text": "Resolved"}})
    assert evts(inc_id, "close_case") == [("ward_office", "DENY", "only-residents-close")]
    assert evts(inc_id, "schedule_checkins") == [("workflow", "ALLOW", "baseline")]
    assert env == [("tg42", texts.WARD_CLAIM_VOLUNTEER.format(claim="Resolved"))]

    env.clear()
    case.checkins({"inc_id": inc_id, "token": "T-check1"})
    assert len(env) == 23 and all(text == texts.CHECKIN for _, text in env)
    short = store.get_incident(inc_id)["checkin_tok"]
    assert workflow.answer_checkin("sim-C", short, True) == texts.CHECKIN_THANKS
    assert "T-check1" not in sfn.done                                          # a हाँ doesn't end the round
    workflow.answer_checkin("tg42", short, False)                              # my tap says no...
    assert "T-check1" in sfn.done                                              # ...which ends it at once
    assert case.evaluate({"inc_id": inc_id})["outcome"] == "REOPENED"
    env.clear()
    case.reopened({"inc_id": inc_id})
    assert store.get_incident(inc_id)["status"] == "REOPENED" and sum(t == texts.REOPENED for _, t in env) == 23

    # Next round: three homes say clean, nobody says dirty -> closed at the tap, by the quorum evaluator only.
    case.checkins({"inc_id": inc_id, "token": "T-check2"})
    short = store.get_incident(inc_id)["checkin_tok"]
    for h in ("sim-C", "sim-D", "sim-E"):
        workflow.answer_checkin(h, short, True)
    assert case.evaluate({"inc_id": inc_id}) == {"outcome": "CLOSED_AT_TAP", "round": 2, "clean": 3, "not_clean": 0}
    assert ("quorum_evaluator", "ALLOW", "baseline") in evts(inc_id, "close_case")


def test_warning_without_volunteer_approval_is_denied(env, monkeypatch):
    monkeypatch.setattr(workflow, "_sfn", lambda: FakeSfn())
    inc_id = incident(env)
    homes = case.ring({"inc_id": inc_id})["homes"]
    assert case.warn_home({"inc_id": inc_id, "hh_id": homes[0]}) == {"hh_id": homes[0], "sent": False}
    assert env == [] and evts(inc_id, "broadcast_warning")[0][1:] == ("DENY", "approval-before-broadcast")
