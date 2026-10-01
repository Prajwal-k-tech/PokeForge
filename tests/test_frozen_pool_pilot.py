from types import SimpleNamespace
import copy
import unittest

from scripts.check_damage_conformance import STATUS
from scripts.check_frozen_pool_turns import jobs_for, UNCHECKED
from scripts.check_joint_turns import native_projection
from scripts.capture_frozen_multiturn import validate, checked_player_records
import json


class FrozenPoolPilotTests(unittest.TestCase):
    def test_player_stream_rejects_private_opponent_requests_hp_and_split_lines(self):
        request = {'teamPreview': True, 'side': {'id': 'p1', 'pokemon': [{}] * 6}}
        preview = '|request|' + json.dumps(request)
        records = checked_player_records([preview, '|-damage|p2a: Other|73/100'], 'p1', 'battle-test')
        self.assertEqual(len(records), 2)
        for leaked in ['|-damage|p2a: Other|301/404', '|split|p2',
                       '|request|' + json.dumps(request | {'side': {'id': 'p2', 'pokemon': [{}] * 6}})]:
            with self.assertRaises(ValueError):
                checked_player_records([preview, leaked], 'p1', 'battle-test')
        with self.assertRaisesRegex(ValueError, 'request ID'):
            checked_player_records(['|request|' + json.dumps(request | {'rqid': 1})], 'p1', 'battle-test')
        wrapped = '|request|' + json.dumps(request | {'rqid': 2})
        checked_player_records([wrapped], 'p1', 'battle-test', room_envelope=True)
        with self.assertRaisesRegex(ValueError, 'request ID'):
            checked_player_records([wrapped, wrapped], 'p1', 'battle-test', room_envelope=True)

    def test_multiturn_validator_rejects_missing_delay_and_discontinuity(self):
        initial = {"slot_conditions": [[{}], [{}]], "projection": [{"active_index": 0}]}
        pending = {"slot_conditions": [[{}], [{"futuremove": {"move": "futuresight"}}]],
                   "projection": [{"active_index": 0}]}
        switched = copy.deepcopy(pending)
        switched["projection"][0]["active_index"] = 1
        finished = copy.deepcopy(switched)
        finished["slot_conditions"][1] = [{}]
        transitions = [{"before": copy.deepcopy(initial), "after": copy.deepcopy(pending)},
                       {"before": copy.deepcopy(pending), "after": copy.deepcopy(switched)},
                       {"before": copy.deepcopy(switched), "after": copy.deepcopy(finished)}]
        scenarios = [{"id": "future_sight_survives_source_switch", "trajectories": [{"transitions": transitions}]}]
        validate(scenarios)
        broken = copy.deepcopy(scenarios)
        broken[0]["trajectories"][0]["transitions"][1]["before"]["projection"][0]["active_index"] = 2
        with self.assertRaisesRegex(ValueError, "Discontinuous"):
            validate(broken)
        broken = copy.deepcopy(scenarios)
        broken[0]["trajectories"][0]["transitions"][2]["after"]["slot_conditions"][1][0] = {"futuremove": {}}
        with self.assertRaisesRegex(ValueError, "did not resolve"):
            validate(broken)

    def test_scheduler_covers_each_move_instance_and_each_lead_switch(self):
        teams = [{"file": f"team_{i}", "sets": [{"moves": ["a", "b", "c", "d"]} for _ in range(6)]}
                 for i in range(11)]
        jobs = jobs_for(teams)
        self.assertEqual(len(jobs), 330)
        self.assertEqual(len({job["id"] for job in jobs}), 330)
        self.assertEqual(sum(job["move"] is None for job in jobs), 66)
        self.assertEqual(sum(job["move"] is not None for job in jobs), 264)
        self.assertIn("futuresight", UNCHECKED)
        self.assertIn("wish", UNCHECKED)
        self.assertIn("voltswitch", UNCHECKED)

    def test_native_status_full_moves_and_fainted_boost_normalization(self):
        self.assertEqual(STATUS["par"], "paralyze")
        poke = SimpleNamespace(id="PIKACHU", hp=90, maxhp=100, status="PARALYZE", item="NONE",
                               ability="STATIC", tera_type="TYPELESS", terastallized=False,
                               moves=[SimpleNamespace(pp=n) for n in [8, 7, 6, 5]])
        conditions = SimpleNamespace(stealth_rock=0, spikes=0, toxic_spikes=0, sticky_web=0)
        side = SimpleNamespace(pokemon=[poke], active_index="0", side_conditions=conditions,
                               attack_boost=2, defense_boost=0, special_attack_boost=0,
                               special_defense_boost=0, speed_boost=0, accuracy_boost=0, evasion_boost=0)
        state = SimpleNamespace(side_one=side, side_two=side)
        p = native_projection(state, (1, 1), [[4], [4]])[0]["pokemon"][0]
        self.assertEqual(p["status"], "par")
        self.assertEqual(p["pp"], [8, 7, 6, 5])
        self.assertEqual(p["boosts"]["atk"], 2)
        poke.hp = 0
        p = native_projection(state, (1, 1), [[4], [4]])[0]["pokemon"][0]
        self.assertEqual(p["status"], "")
        self.assertTrue(all(v == 0 for v in p["boosts"].values()))
