import json
from pathlib import Path

import pytest

from src.integration.contracts import ActionKey, ActionKind
from src.integration.framework_actions import (
    foulplay_wire_choice_to_action_key,
    metamon_action_index_to_action_key,
)
from src.integration.showdown_request import legal_actions_from_request


FIXTURE = (
    Path(__file__).with_name("fixtures") / "foulplay_local_normal_request.json"
)
REQUEST_ORDER_SLOTS = (1, 0, 2, 3, 4, 5)


def test_foulplay_wire_commands_resolve_to_stable_semantic_actions():
    request = FIXTURE.read_text()
    assert foulplay_wire_choice_to_action_key(
        "/choose move surf terastallize", request, REQUEST_ORDER_SLOTS
    ) == ActionKey.move(2, "surf", tera=True)
    # FoulPlay's one-based request position 2 is Ting-Lu, whose stable preview slot is 0.
    assert foulplay_wire_choice_to_action_key(
        "/switch 2|4", request, REQUEST_ORDER_SLOTS
    ) == ActionKey.switch(0)


def test_metamon_default_action_indices_cover_the_same_real_request_actions():
    request = FIXTURE.read_text()
    expected = set(
        legal_actions_from_request(request, REQUEST_ORDER_SLOTS).actions
    )
    translated = {
        metamon_action_index_to_action_key(index, request, REQUEST_ORDER_SLOTS)
        for index in range(13)
    }
    assert translated == expected
    # Metamon sorts moves/switches alphabetically; these are not Showdown request positions.
    assert metamon_action_index_to_action_key(1, request, REQUEST_ORDER_SLOTS) == ActionKey.move(
        3, "roost"
    )
    assert metamon_action_index_to_action_key(4, request, REQUEST_ORDER_SLOTS) == ActionKey.switch(
        2
    )
    assert metamon_action_index_to_action_key(11, request, REQUEST_ORDER_SLOTS) == ActionKey.move(
        2, "surf", tera=True
    )


def test_framework_special_action_encodings_are_not_treated_as_moves():
    payload = json.dumps(
        {
            "rqid": 10,
            "side": {
                "pokemon": [
                    {"active": True, "condition": "100/100", "details": "Zangoose"},
                    {"active": False, "condition": "100/100", "details": "Porygon2"},
                ]
            },
            "active": [{"moves": [{"id": "struggle", "pp": 1, "disabled": False}]}],
        }
    )
    assert foulplay_wire_choice_to_action_key(
        "/choose move struggle|10", payload, (0, 1)
    ) == ActionKey(ActionKind.STRUGGLE)
    for index in range(4):
        assert metamon_action_index_to_action_key(index, payload, (0, 1)) == ActionKey(
            ActionKind.STRUGGLE
        )
    assert metamon_action_index_to_action_key(4, payload, (0, 1)) == ActionKey.switch(1)


def test_metamon_forced_switch_starts_at_its_switch_offset():
    payload = json.dumps(
        {
            "rqid": 11,
            "forceSwitch": [True],
            "side": {
                "pokemon": [
                    {"active": True, "condition": "0 fnt", "details": "Zangoose"},
                    {"active": False, "condition": "100/100", "details": "Porygon2"},
                ]
            },
        }
    )
    assert metamon_action_index_to_action_key(4, payload, (0, 1)) == ActionKey.switch(1)
    with pytest.raises(ValueError, match="illegal"):
        metamon_action_index_to_action_key(0, payload, (0, 1))


def test_disabled_and_exhausted_moves_preserve_metamon_policy_indices():
    request = json.loads(FIXTURE.read_text())
    # Sorted Metamon order is hurricane, roost, surf, uturn. Masking hurricane must not
    # turn index 0 into roost or shift surf away from index 2.
    request["active"][0]["moves"][0]["disabled"] = True
    request["active"][0]["moves"][3]["pp"] = 0
    request["active"][0]["moves"][3]["disabled"] = True
    payload = json.dumps(request)
    for index in (0, 1, 9, 10):
        with pytest.raises(ValueError, match="illegal"):
            metamon_action_index_to_action_key(index, payload, REQUEST_ORDER_SLOTS)
    assert metamon_action_index_to_action_key(2, payload, REQUEST_ORDER_SLOTS) == ActionKey.move(
        2, "surf"
    )
    assert metamon_action_index_to_action_key(12, payload, REQUEST_ORDER_SLOTS) == ActionKey.move(
        1, "uturn", tera=True
    )


@pytest.mark.parametrize("command", ["/switch", "/choose switch", "/switch nope", "/switch 2 extra", "/choose move surf mega", "/choose move surf extra"])
def test_malformed_foulplay_commands_fail_at_the_boundary(command):
    with pytest.raises(ValueError):
        foulplay_wire_choice_to_action_key(command, FIXTURE.read_text(), REQUEST_ORDER_SLOTS)


def test_stale_foulplay_request_id_is_rejected():
    with pytest.raises(ValueError, match="stale"):
        foulplay_wire_choice_to_action_key(
            "/choose move surf|3", FIXTURE.read_text(), REQUEST_ORDER_SLOTS
        )
