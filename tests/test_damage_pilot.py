import unittest
from pathlib import Path
import copy

from scripts.check_damage_conformance import adjudications, classify, fixtures, mixture_summary, roll_summary
from scripts.compare_damage_reports import compare_cases


class DamagePilotTests(unittest.TestCase):
    def test_report_comparison_checks_oracles_and_rejects_regressions(self):
        before = {"fixture": {"id": "crit"}, "engine_state_sha256": "same-input",
                  "oracle": {"showdown": {"regular": [100] * 16, "critical": [150] * 16},
                             "smogon_calc": {"regular": [100] * 16, "critical": [150] * 16},
                             "state": {}, "calc_stats": {}, "seed": [1,2,3,4]},
                  "engine_maxima": [100, 75], "engine_maximum_agreement": False,
                  "classification": "supported-engine-bug"}
        after = copy.deepcopy(before)
        after.update(engine_maxima=[100,150], engine_maximum_agreement=True, classification="direct-damage-match")
        result = compare_cases([before], [after])
        self.assertEqual(result["changed"], 1)
        self.assertEqual(result["variant_exact_maximum_pairs"], 1)
        after["engine_maxima"] = [100,250]
        after["engine_maximum_agreement"] = False
        with self.assertRaisesRegex(ValueError, "worsened"):
            compare_cases([before], [after])
        after["oracle"]["showdown"]["regular"] = [101] * 16
        with self.assertRaisesRegex(ValueError, "oracle mismatch"):
            compare_cases([before], [after])

    def test_extended_fixtures_and_variant_classifications_keep_baseline_separate(self):
        folder = Path(__file__).parent / "fixtures"
        base = fixtures(folder / "damage_pilot_v1.json")
        extended = fixtures(folder / "damage_critical_stats_v1.json")
        self.assertEqual(extended[:32], base)
        self.assertEqual(len(extended), 50)
        self.assertEqual(len({f["id"] for f in extended}), 50)
        baseline = adjudications(folder / "damage_critical_stats_adjudications_v1.json")
        variant = adjudications(folder / "damage_critical_stats_variant_adjudications_v1.json")
        self.assertEqual(baseline["body_press_defense_override"]["classification"], "supported-engine-bug")
        self.assertEqual(variant["body_press_defense_override"]["classification"], "modifier-stage-approximation")
        self.assertEqual(baseline["body_press_defense_override"]["engine_maxima"], [1014, 765])
        self.assertEqual(variant["body_press_defense_override"]["engine_maxima"], [1014, 1521])

    def test_duplicate_rolls_are_probability_mass_not_unique_equiprobable_values(self):
        result = roll_summary([0] * 12 + [100] * 4, 100)
        self.assertEqual(result["support"], [{"damage": 0, "probability": .75},
                                             {"damage": 100, "probability": .25}])
        self.assertEqual(result["mean"], 25)
        self.assertEqual(result["p_ko_given_hit_and_critical_condition"], .25)
        self.assertEqual(roll_summary([0] * 16, 100)["max"], 0)

    def test_hidden_item_worlds_retain_immunity_and_lower_tail(self):
        result = mixture_summary([(.5, [200] * 16), (.5, [0] * 16)], 100)
        self.assertEqual(result["mean"], 100)
        self.assertEqual(result["p_zero"], .5)
        self.assertEqual(result["q10"], 0)
        self.assertEqual(result["p_ko_given_hit_and_no_critical"], .5)
        safe = mixture_summary([(.5, [110] * 16), (.5, [110] * 16)], 100)
        self.assertEqual(safe["p_zero"], 0)
        self.assertEqual(safe["p_ko_given_hit_and_no_critical"], 1)

    def test_invalid_weights_or_rolls_fail_instead_of_silent_normalization(self):
        for worlds in ([], [(.4, [0] * 16)], [(-.1, [0] * 16), (1.1, [0] * 16)],
                       [(float("nan"), [0] * 16)]):
            with self.assertRaises(ValueError):
                mixture_summary(worlds, 100)
        for rolls in ([1] * 15, [-1] * 16, [True] * 16, [1.5] * 16):
            with self.assertRaises(ValueError):
                roll_summary(rolls, 100)

    def test_new_mismatches_do_not_inherit_old_adjudication(self):
        known = {"bodypress": {"engine_maxima": [1014, 765], "oracle_maxima": [1014, 1520],
                              "classification": "supported-engine-bug"}}
        self.assertEqual(classify("bodypress", [1014, 765], [1014, 1520], True, known),
                         "supported-engine-bug")
        self.assertEqual(classify("bodypress", [1014, 766], [1014, 1520], True, known),
                         "unclassified-mismatch")
        self.assertEqual(classify("bodypress", [1014, 765], [1014, 765], False, known),
                         "oracle-ambiguity")


if __name__ == "__main__":
    unittest.main()
