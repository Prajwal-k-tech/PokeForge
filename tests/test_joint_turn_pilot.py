import copy
from pathlib import Path
import unittest

from scripts.check_joint_turns import comparable, engine_actions, expand
from scripts.audit_joint_engine_fix import compare_turns


class JointTurnPilotTests(unittest.TestCase):
    def test_paired_correction_rejects_an_unrelated_state_change(self):
        fixtures = expand(Path(__file__).parent / "fixtures/joint_turn_pilot_v1.json")
        before, after = [], []
        for fixture in fixtures:
            case = fixture["id"]
            old_hp = 226 if case == "recover_and_burn" else 361 if case.startswith("contact_helmet") else 100
            new_hp = 227 if case == "recover_and_burn" else 360 if case.startswith("contact_helmet") else 100
            state = [{"pokemon": [{"hp": old_hp, "pp": [7]}]}]
            oracle_state = [{"pokemon": [{"hp": new_hp, "pp": [7]}]}]
            outcomes = [{"seed": [1, n, 3, 4], "before": {}, "after": oracle_state, "turn": 2,
                         "request_state": "move", "ended": False} for n in range(64)]
            row = {"fixture": fixture, "initial_engine_state_sha256": "same", "initial_projection": {},
                   "showdown_outcomes": outcomes,
                   "engine_outcomes": [{"probability": 1, "after": state, "instructions": []}]}
            before.append(row)
            fixed = copy.deepcopy(row)
            fixed["engine_outcomes"][0]["after"] = copy.deepcopy(oracle_state)
            if case.startswith("contact_helmet"):
                fixed["engine_outcomes"][0]["instructions"] = ["Heal SideOne: -72"]
            after.append(fixed)
        self.assertEqual(compare_turns(before, after)["unchanged_cases"], 15)
        after[0]["engine_outcomes"][0]["after"][0]["pokemon"][0]["pp"] = [6]
        with self.assertRaisesRegex(ValueError, "Unexpected engine outcome change"):
            compare_turns(before, after)

    def test_weather_controls_include_fixed_point_and_half_ties(self):
        fixtures = expand(Path(__file__).parent / "fixtures/joint_turn_recovery_v1.json")
        self.assertEqual(len(fixtures), 5)
        cases = {c["id"]: c for c in fixtures}
        self.assertEqual(cases["morning_sun_fixed_point"]["teams"][0][0]["evs"]["hp"], 8)
        self.assertEqual(cases["morning_sun_bad_weather_half_tie_down"]["teams"][0][0]["ivs"]["hp"], 30)

    def test_fixtures_keep_item_worlds_and_order_controls_distinct(self):
        cases = {f["id"]: f for f in expand(Path(__file__).parent / "fixtures/joint_turn_pilot_v1.json")}
        self.assertEqual(len(cases), 19)
        self.assertEqual(engine_actions(cases["switch_into_rocks"]), ["blissey", "splash"])
        self.assertEqual(cases["boots_ignore_rocks"]["teams"][0][1]["item"], "Heavy-Duty Boots")
        self.assertEqual(cases["contact_helmet"]["teams"][0][0]["evs"]["spe"], 0)
        self.assertEqual(cases["contact_helmet_attacker_faster"]["teams"][0][0]["evs"]["spe"], 4)
        self.assertEqual(cases["contact_helmet_attacker_slower"]["teams"][1][0]["evs"]["spe"], 4)

    def test_non_hp_comparison_keeps_pp_items_boosts_and_switches(self):
        before = [{"active_index": 0, "hazards": {"spikes": 1}, "pokemon": [
            {"species_id": "tusk", "hp": 100, "maxhp": 371, "item": "leftovers", "pp": [8],
             "status": "", "boosts": {"atk": 0}, "stats": {"atk": 359}}]}]
        saved = copy.deepcopy(before)
        altered = copy.deepcopy(before)
        altered[0]["pokemon"][0]["hp"] = 90
        self.assertEqual(comparable(before, hp=False), comparable(altered, hp=False))
        self.assertNotEqual(comparable(before), comparable(altered))
        for field, value in (("pp", [7]), ("item", ""), ("boosts", {"atk": 2})):
            changed = copy.deepcopy(before)
            changed[0]["pokemon"][0][field] = value
            self.assertNotEqual(comparable(before, hp=False), comparable(changed, hp=False))
        self.assertEqual(before, saved)
