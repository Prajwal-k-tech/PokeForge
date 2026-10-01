import json
import unittest
from dataclasses import replace

from src.integration.contracts import (
    ActionKey,
    ActionKind,
    BattlePhase,
    BattleSnapshot,
    TeamSlot,
    canonical_json,
    hash_history,
    hash_protocol_payload,
)


class ContractTests(unittest.TestCase):
    def snapshot(self, phase, actions):
        request = '{"active":[{}],"rqid":7}'
        return BattleSnapshot(
            adapter_version="test-v1",
            battle_tag="battle-gen9ou-1",
            perspective="p1",
            request_hash=hash_protocol_payload(request),
            history_hash=hash_history(["|turn|1", f"|request|{request}"]),
            rqid=7,
            turn=1,
            phase=phase,
            self_team=tuple(TeamSlot(i, f"selfmon{i}") for i in range(6)),
            opponent_team=tuple(TeamSlot(i, f"foemon{i}") for i in range(6)),
            self_active_slot=0,
            opponent_active_slot=0,
            legal_actions=tuple(actions),
            public_state_json=canonical_json({"weather": None}),
        )

    def test_all_thirteen_turn_actions_are_semantic_and_unique(self):
        actions = [ActionKey.move(i, f"move{i}") for i in range(4)]
        actions += [ActionKey.move(i, f"move{i}", tera=True) for i in range(4)]
        actions += [ActionKey.switch(i) for i in range(1, 6)]
        snapshot = self.snapshot(BattlePhase.TURN, actions)
        self.assertEqual(len(snapshot.legal_actions), 13)
        self.assertEqual(snapshot.legal_actions[8].team_slot, 1)
        self.assertEqual(snapshot.legal_actions[-1].team_slot, 5)

    def test_filtered_switches_keep_full_team_slots(self):
        snapshot = self.snapshot(
            BattlePhase.FORCED_SWITCH, [ActionKey.switch(2), ActionKey.switch(5)]
        )
        self.assertEqual([a.team_slot for a in snapshot.legal_actions], [2, 5])

    def test_semantic_hash_ignores_adapter_and_set_order_but_not_state(self):
        original = self.snapshot(BattlePhase.TURN, [ActionKey.move(0, "tackle"), ActionKey.switch(2)])
        other = replace(original, adapter_version="other-v1",
                        legal_actions=tuple(reversed(original.legal_actions)),
                        self_team=tuple(reversed(original.self_team)))
        self.assertNotEqual(original.snapshot_hash, other.snapshot_hash)
        self.assertEqual(original.semantic_hash, other.semantic_hash)
        self.assertNotEqual(original.semantic_hash, replace(other, turn=2).semantic_hash)

    def test_special_phases_and_actions(self):
        preview = self.snapshot(
            BattlePhase.TEAM_PREVIEW,
            [ActionKey.team_preview((5, 4, 3, 2, 1, 0))],
        )
        struggle = self.snapshot(
            BattlePhase.TURN, [ActionKey(ActionKind.STRUGGLE)]
        )
        waiting = self.snapshot(BattlePhase.WAIT, [])
        self.assertNotEqual(preview.snapshot_hash, struggle.snapshot_hash)
        self.assertFalse(waiting.legal_actions)

    def test_invalid_phase_action_and_noncanonical_state_fail(self):
        with self.assertRaises(ValueError):
            self.snapshot(BattlePhase.FORCED_SWITCH, [ActionKey.move(0, "tackle")])
        snapshot = self.snapshot(BattlePhase.TURN, [ActionKey.move(0, "tackle")])
        data = {field: getattr(snapshot, field) for field in snapshot.__dataclass_fields__}
        data["public_state_json"] = json.dumps({"z": 1, "a": 2})
        with self.assertRaises(ValueError):
            BattleSnapshot(**data)


if __name__ == "__main__":
    unittest.main()
