import json
from pathlib import Path

import pytest

from src.integration.contracts import hash_protocol_payload
from src.integration.policy_gate import RequestPolicyGate, restrict_probabilities
from scripts.check_policy_trace import audit_trace


def gate_and_request():
    request = json.loads((Path(__file__).parent / "fixtures/foulplay_local_normal_request.json").read_text())
    preview = {"rqid": 2, "teamPreview": True, "side": {"pokemon": request["side"]["pokemon"]}}
    gate = RequestPolicyGate()
    gate.observe("battle-gen9ou-1", json.dumps(preview))
    gate.observe("battle-gen9ou-1", json.dumps(request))
    return gate, request


def test_post_clipping_mask_has_exact_zero_illegal_mass_and_preserves_ratios():
    gate, request = gate_and_request()
    request.pop("active")
    request["forceSwitch"] = [True]
    gate.observe("battle-gen9ou-1", json.dumps(request))
    ticket = gate.activate("battle-gen9ou-1", request)
    probs = [0.001] * 13
    probs[4:9] = [0.1, 0.2, 0.3, 0.2, 0.192]
    safe, removed = restrict_probabilities(probs, ticket, ticket.request_hash)
    assert removed == pytest.approx(0.008)
    assert sum(safe) == pytest.approx(1)
    assert safe[5] / safe[4] == pytest.approx(2)
    assert all(p == 0 for p, legal in zip(safe, ticket.legal_mask) if not legal)
    gate.validate(ticket, request)
    assert ticket.wire_choice(4).endswith("|4")
    with pytest.raises(ValueError, match="illegal"):
        ticket.wire_choice(1)


def test_stale_exact_bytes_rejected_even_if_json_semantics_and_rqid_match():
    gate, request = gate_and_request()
    ticket = gate.activate("battle-gen9ou-1", request)
    gate.observe("battle-gen9ou-1", json.dumps(request, indent=2))
    assert ticket.request_hash != hash_protocol_payload(gate.latest_payload)
    with pytest.raises(ValueError, match="stale"):
        gate.validate(ticket, request)
    with pytest.raises(ValueError, match="stale"):
        restrict_probabilities([1 / 13] * 13, ticket, hash_protocol_payload(gate.latest_payload))


def test_no_silent_identity_changes_or_zero_mass_fallback():
    gate, request = gate_and_request()
    request["active"][0].pop("canTerastallize")
    gate.observe("battle-gen9ou-1", json.dumps(request))
    ticket = gate.activate("battle-gen9ou-1", request)
    with pytest.raises(ValueError, match="no probability"):
        restrict_probabilities([0] * 9 + [0.25] * 4, ticket, ticket.request_hash)
    for bad in ([float("nan")] * 13, [-1] * 13, [1] * 13, [0] * 12):
        with pytest.raises(ValueError):
            restrict_probabilities(bad, ticket, ticket.request_hash)
    request["side"]["pokemon"][0]["ident"] = "p1: unexpected"
    gate.observe("battle-gen9ou-1", json.dumps(request))
    with pytest.raises(ValueError, match="identities"):
        gate.activate("battle-gen9ou-1", request)


def test_preview_slots_survive_request_reordering_and_bad_indices_fail():
    gate, request = gate_and_request()
    first_ident = request["side"]["pokemon"][0]["ident"]
    request["side"]["pokemon"] = request["side"]["pokemon"][1:] + request["side"]["pokemon"][:1]
    gate.observe("battle-gen9ou-1", json.dumps(request))
    ticket = gate.activate("battle-gen9ou-1", request)
    assert request["side"]["pokemon"][-1]["ident"] == first_ident
    assert ticket.slots == (1, 2, 3, 4, 5, 0)
    for index, action in enumerate(ticket.indices):
        if action is not None and action.team_slot is not None:
            position = ticket.slots.index(action.team_slot) + 1
            assert ticket.wire_choice(index) == f"/choose switch {position}|{ticket.rqid}"
    for bad in (-1, 13, 1.5):
        with pytest.raises(ValueError):
            ticket.wire_choice(bad)


def test_trace_audit_rejects_tampered_choice_or_unlogged_fallback(tmp_path):
    gate, request = gate_and_request()
    ticket = gate.activate("battle-gen9ou-1", request)
    preview = {"rqid": 2, "teamPreview": True, "side": {"pokemon": request["side"]["pokemon"]}}
    events = []
    for payload in (json.dumps(preview), ticket.payload):
        events.append({"event": "request", "battle_tag": ticket.battle_tag, "payload": payload,
                       "request_hash": hash_protocol_payload(payload)})
    identity = {"battle_tag": ticket.battle_tag, "rqid": ticket.rqid, "request_hash": ticket.request_hash}
    probs = [1 / 13] * 13
    safe, removed = restrict_probabilities(probs, ticket, ticket.request_hash)
    events += [{"event": "activate", **identity, "legal_mask": ticket.legal_mask},
               {"event": "distribution", **identity, "raw_probabilities": probs,
                "legal_probabilities": safe, "removed_illegal_mass": removed},
               {"event": "choice", **identity, "index": 0, "wire_command": ticket.wire_choice(0)}]
    path = tmp_path / "trace.jsonl"
    path.write_text("\n".join(json.dumps(event) for event in events))
    assert audit_trace(path)["choices"] == 1
    events[-1]["wire_command"] = "/choose default"
    path.write_text("\n".join(json.dumps(event) for event in events))
    with pytest.raises(ValueError, match="wire action"):
        audit_trace(path)
    events[-1] = {"event": "fallback_rejected"}
    path.write_text("\n".join(json.dumps(event) for event in events))
    with pytest.raises(ValueError, match="failure event"):
        audit_trace(path)
