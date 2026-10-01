import json
import unittest
from pathlib import Path

from src.integration.contracts import ActionKind, BattlePhase
from src.integration.showdown_request import legal_actions_from_request


def request(
    *, moves=None, trapped=False, force=False, wait=False, preview=False, fainted=None
):
    payload = {
        "rqid": 9,
        "side": {
            "pokemon": [
                {"active": True, "condition": "300/300"},
                {"active": False, "condition": "250/250"},
                {"active": False, "condition": "200/200"},
                {"active": False, "condition": "200/200"},
                {"active": False, "condition": "100/100"},
                {"active": False, "condition": "150/150"},
            ]
        },
    }
    if fainted is not None:
        payload["side"]["pokemon"][fainted]["condition"] = "0 fnt"
    if moves is not None:
        payload["active"] = [
            {"moves": moves, "trapped": trapped, "canTerastallize": "Ghost"}
        ]
    if force:
        payload["forceSwitch"] = [True]
    if wait:
        payload["wait"] = True
    if preview:
        payload["teamPreview"] = True
    return json.dumps(payload, separators=(",", ":"))


MOVES = [
    {"id": "moveone", "pp": 8, "disabled": False},
    {"id": "movetwo", "pp": 8, "disabled": False},
    {"id": "movethree", "pp": 8, "disabled": False},
    {"id": "movefour", "pp": 8, "disabled": False},
]
FIXTURES = Path(__file__).with_name("fixtures")


class ShowdownRequestTests(unittest.TestCase):
    def test_full_turn_has_thirteen_semantic_actions(self):
        result = legal_actions_from_request(request(moves=MOVES), tuple(range(6)))
        self.assertEqual(result.phase, BattlePhase.TURN)
        self.assertEqual(len(result.actions), 13)
        self.assertEqual([a.move_slot for a in result.actions[:8]], [0, 0, 1, 1, 2, 2, 3, 3])
        self.assertEqual([a.team_slot for a in result.actions[8:]], [1, 2, 3, 4, 5])

    def test_disabled_moves_and_trapping_do_not_shift_slots(self):
        moves = [dict(move) for move in MOVES]
        moves[1]["disabled"] = True
        result = legal_actions_from_request(
            request(moves=moves, trapped=True), tuple(range(6))
        )
        ordinary = [a for a in result.actions if not a.tera]
        self.assertEqual([a.move_slot for a in ordinary], [0, 2, 3])
        self.assertFalse(any(a.kind is ActionKind.SWITCH for a in result.actions))

    def test_forced_switch_uses_external_stable_slot_map(self):
        mapping = (3, 0, 5, 2, 1, 4)
        result = legal_actions_from_request(request(force=True, fainted=2), mapping)
        self.assertEqual(result.phase, BattlePhase.FORCED_SWITCH)
        self.assertEqual([a.team_slot for a in result.actions], [0, 2, 1, 4])

    def test_team_preview_wait_finished_and_struggle(self):
        preview = legal_actions_from_request(request(preview=True), tuple(range(6)))
        waiting = legal_actions_from_request(request(wait=True), tuple(range(6)))
        finished = legal_actions_from_request(
            request(wait=True), tuple(range(6)), finished=True
        )
        struggle = legal_actions_from_request(
            request(moves=[{"id": "struggle", "pp": 1, "disabled": False}]),
            tuple(range(6)),
        )
        self.assertEqual(len(preview.actions), 720)
        self.assertEqual(waiting.phase, BattlePhase.WAIT)
        self.assertEqual(finished.phase, BattlePhase.FINISHED)
        self.assertEqual(struggle.actions[0].kind, ActionKind.STRUGGLE)

    def test_captured_foulplay_request_preserves_full_team_slots(self):
        """Pelipper moved from initial slot 1 to request position 0 after leading."""
        payload = (FIXTURES / "foulplay_local_normal_request.json").read_text()
        result = legal_actions_from_request(payload, (1, 0, 2, 3, 4, 5))
        self.assertEqual(result.phase, BattlePhase.TURN)
        self.assertEqual(result.rqid, 4)
        self.assertEqual(len(result.actions), 13)
        self.assertEqual(
            [(action.kind, action.move_slot, action.move_id, action.tera) for action in result.actions[:8]],
            [
                (ActionKind.MOVE, 0, "hurricane", False),
                (ActionKind.MOVE, 0, "hurricane", True),
                (ActionKind.MOVE, 1, "uturn", False),
                (ActionKind.MOVE, 1, "uturn", True),
                (ActionKind.MOVE, 2, "surf", False),
                (ActionKind.MOVE, 2, "surf", True),
                (ActionKind.MOVE, 3, "roost", False),
                (ActionKind.MOVE, 3, "roost", True),
            ],
        )
        self.assertEqual(
            [action.team_slot for action in result.actions[8:]], [0, 2, 3, 4, 5]
        )


if __name__ == "__main__":
    unittest.main()
