import copy
import json
import unittest
from pathlib import Path
from dataclasses import asdict
from types import SimpleNamespace as NS

from src.integration.contracts import BattlePhase, hash_protocol_payload
from src.integration.framework_state import (
    TranscriptContext, displayed_hp, normalized, snapshot_from_framework,
)
from scripts.check_framework_states import checked_report_snapshot
from scripts.check_multiturn_states import verify_public_delays

FIXTURE = Path(__file__).parent / "fixtures/foulplay_local_normal_request.json"
STAT_NAMES = {"atk": "attack", "def": "defense", "spa": "special-attack",
              "spd": "special-defense", "spe": "speed"}


def context_and_mock():
    """A unit-only native-shaped object; not an upstream framework conformance claim."""
    request = json.loads(FIXTURE.read_text())
    for p in request["side"]["pokemon"]:
        p["stats"] = dict.fromkeys(STAT_NAMES, 100)
    preview = copy.deepcopy(request)
    preview.pop("active")
    preview.update(teamPreview=True, rqid=2)
    context = TranscriptContext("battle-gen9ou-test", format_id="gen9ou-test", rules_revision="unit-only")
    lines = [f"|poke|{side}|{p['details']}|" for side in ("p1", "p2") for p in preview["side"]["pokemon"]]
    context.consume(">battle-gen9ou-test\n" + "\n".join(lines))
    context.consume(">battle-gen9ou-test\n|request|" + json.dumps(preview))
    context.consume(">battle-gen9ou-test\n|switch|p1a: Pelipper|Pelipper, M|262/262\n"
                    "|switch|p2a: Pelipper|Pelipper, M|100/100\n|turn|1")
    context.consume(">battle-gen9ou-test\n|request|" + json.dumps(request))

    def member(p, own):
        hp, maxhp = [int(v) for v in p["condition"].split("/")] if own else (600, 600)
        return NS(name=normalized(p["details"].split(",", 1)[0]), nickname=p["ident"].split(": ")[1],
                  level=100, hp=hp, max_hp=maxhp, status=None, terastallized=False,
                  tera_type=normalized(p["teraType"]) if own else None, types=["normal"],
                  item=p["item"] if own else "choicescarf", ability=p["ability"] if own else "madeupability",
                  stats={v: 100 if own else 999 for v in STAT_NAMES.values()}, boosts={},
                  moves=[NS(name=m) for m in p["moves"]], volatile_statuses=[])
    own = [member(p, True) for p in request["side"]["pokemon"]]
    opp = [member(p, False) for p in request["side"]["pokemon"]]
    side = lambda members: NS(active=members[0], reserve=members[1:], side_conditions={},
                              update_from_request_json=lambda request: None)
    battle = NS(user=side(own), opponent=side(opp), request_json=request,
                weather=None, field=None, trick_room=False, gravity=False, turn=1)
    return context, battle


class FrameworkStateTests(unittest.TestCase):
    def test_oracle_checker_detects_shared_clock_error_and_hidden_wish_amount(self):
        context, battle = context_and_mock()
        public = json.loads(snapshot_from_framework('foulplay', battle, context).public_state_json)
        truth = {'turn': 2, 'slot_conditions': [[{}], [{}]], 'volatiles': [{}, {}]}
        verify_public_delays(public, truth, 'p1')
        truth['slot_conditions'][1][0]['wish'] = {'hp': 299.5, 'startingTurn': 0}
        public['field']['opponent_wish'] = {'remaining_residuals': 1, 'heal_hp': None}
        verify_public_delays(public, truth, 'p1')
        public['field']['opponent_wish']['heal_hp'] = 299
        with self.assertRaisesRegex(ValueError, 'leaks'):
            verify_public_delays(public, truth, 'p1')
        public['field']['opponent_wish'].update(heal_hp=None, remaining_residuals=2)
        with self.assertRaisesRegex(ValueError, 'clock'):
            verify_public_delays(public, truth, 'p1')

    def test_delays_use_residual_clock_and_future_survives_source_switch(self):
        context, _ = context_and_mock()
        context.consume('>battle-gen9ou-test\n|move|p1a: Pelipper|Future Sight|p2a: Pelipper\n'
                        '|-start|p1a: Pelipper|move: Future Sight\n|upkeep\n|turn|2')
        self.assertEqual(context.future_moves['p1']['remaining_residuals'], 2)
        request = context.request
        replacement = request['side']['pokemon'][1]
        context.consume('>battle-gen9ou-test\n|switch|' + replacement['ident'].replace('p1:', 'p1a:') +
                        '|' + replacement['details'] + '|' + replacement['condition'])
        self.assertEqual(context.future_moves['p1']['source_slot'], 0)
        self.assertNotIn('futuresight', context.persistent_effects.get(('p1', 0), set()))
        context.consume('>battle-gen9ou-test\n|upkeep\n|turn|3\n|-end|p2a: Pelipper|move: Future Sight\n|upkeep')
        self.assertNotIn('p1', context.future_moves)

    def test_wish_failure_expiry_and_no_opponent_hp_guess(self):
        context, _ = context_and_mock()
        context.own_maxhp[0] = 263  # Wish calls Battle.heal, which truncates the half-HP amount.
        context.consume('>battle-gen9ou-test\n|move|p1a: Pelipper|Wish|p1a: Pelipper\n'
                        '|move|p2a: Pelipper|Wish|p2a: Pelipper')
        self.assertEqual(context.wishes['p1']['heal_hp'], 131)
        self.assertIsNone(context.wishes['p2']['heal_hp'])
        context.consume('>battle-gen9ou-test\n|-fail|p2a: Pelipper\n|upkeep\n|turn|2\n'
                        '|move|p1a: Pelipper|Wish|p1a: Pelipper\n|-fail|p1a: Pelipper')
        self.assertNotIn('p2', context.wishes)
        self.assertEqual(context.wishes['p1']['started_turn'], 1)
        context.consume('>battle-gen9ou-test\n|upkeep')  # Full-HP Wish can expire without a heal line.
        self.assertFalse(context.wishes)
        with self.assertRaisesRegex(ValueError, 'duplicate upkeep'):
            context.consume('>battle-gen9ou-test\n|upkeep')

    def test_encore_lock_and_duration_do_not_copy_hidden_native_counter(self):
        context, _ = context_and_mock()
        context.consume('>battle-gen9ou-test\n|move|p2a: Pelipper|Calm Mind|p2a: Pelipper\n'
                        '|upkeep\n|turn|2\n|-start|p2a: Pelipper|Encore\n|upkeep')
        lock = context.encores[('p2', 0)]
        self.assertEqual((lock['move_id'], lock['duration_residuals_lower'], lock['duration_residuals_upper']),
                         ('calmmind', 2, 3))
        context.consume('>battle-gen9ou-test\n|turn|3\n|-end|p2a: Pelipper|Encore')
        self.assertFalse(context.encores)

    def test_late_turn_delay_clock_is_explicitly_unsupported(self):
        context, _ = context_and_mock()
        context.consume('>battle-gen9ou-test\n|turn|253\n|move|p1a: Pelipper|Wish|p1a: Pelipper')
        self.assertIn('late-turn-delay-clock', context.unsupported)

    def test_chilly_announcement_is_not_a_two_turn_charge(self):
        context, _ = context_and_mock()
        context.consume('>battle-gen9ou-test\n|-prepare|p1a: Pelipper|Chilly Reception|[premajor]')
        self.assertNotIn('-prepare', context.unsupported)
        context.consume('>battle-gen9ou-test\n|-prepare|p1a: Pelipper|Fly|p2a: Pelipper')
        self.assertIn('-prepare', context.unsupported)

    def test_percentage_hp_special_99_bucket_and_unknown_vs_exact(self):
        almost_full = displayed_hp("99/100", exact=False)
        self.assertEqual((almost_full["fraction_lower"], almost_full["fraction_upper"]), (.98, 1))
        self.assertFalse(almost_full["upper_inclusive"])
        self.assertFalse(almost_full["exact"])
        self.assertTrue(displayed_hp("100/100", exact=False)["exact"])
        self.assertEqual(displayed_hp("0 fnt", exact=False)["fraction_upper"], 0)
        self.assertEqual(displayed_hp("67/289 brn", exact=True)["fraction_lower"], 67 / 289)
        with self.assertRaises(ValueError):
            displayed_hp("20/48", exact=False)

    def test_snapshot_excludes_native_guessed_opponent_sets_and_stale_bench_hp(self):
        context, battle = context_and_mock()
        battle.opponent.active.volatile_statuses = ["unburden"]
        snapshot = snapshot_from_framework("foulplay", battle, context)
        public = json.loads(snapshot.public_state_json)
        active = public["opponent"]["team"][0]
        self.assertIsNone(active["exact_stats"])
        self.assertIsNone(active["max_hp"])
        self.assertIsNone(active["current_hp"])
        self.assertEqual(active["item"], {"state": "unknown", "id": None})
        self.assertEqual(active["ability"], {"state": "unknown", "id": None})
        self.assertEqual(active["moves"], [])
        self.assertEqual(active["volatiles"], [])
        self.assertIsNone(public["opponent"]["team"][1]["hp_observation"])
        self.assertIsNone(public["opponent"]["team"][1]["hp_current_interval"])
        self.assertEqual(snapshot.request_hash, hash_protocol_payload(context.payload))

    def test_native_contradiction_and_stale_request_fail_closed(self):
        context, battle = context_and_mock()
        context.consume(">battle-gen9ou-test\n|-item|p2a: Pelipper|Leftovers")
        with self.assertRaisesRegex(ValueError, "opponent item"):
            snapshot_from_framework("foulplay", battle, context)
        context, battle = context_and_mock()
        battle.request_json = dict(battle.request_json, rqid=1)
        with self.assertRaisesRegex(ValueError, "stale"):
            snapshot_from_framework("foulplay", battle, context)

    def test_terminal_snapshot_uses_new_health_without_mutating_last_request(self):
        context, battle = context_and_mock()
        original_hash = hash_protocol_payload(context.payload)
        context.consume(">battle-gen9ou-test\n|-damage|p1a: Pelipper|67/262\n|win|PokeForgeFoulPlay")
        battle.user.active.hp = 67
        result = snapshot_from_framework("foulplay", battle, context)
        self.assertEqual(result.phase, BattlePhase.FINISHED)
        self.assertEqual(result.legal_actions, ())
        self.assertEqual(result.request_hash, original_hash)
        member = json.loads(result.public_state_json)["self"]["team"][0]
        self.assertEqual(member["current_hp"], 67)
        self.assertEqual(member["max_hp"], 262)
        self.assertTrue(all(m["pp"] is None for m in member["moves"]))

    def test_transient_roost_expires_on_upkeep_before_next_turn(self):
        context, battle = context_and_mock()
        context.consume(">battle-gen9ou-test\n|-singleturn|p2a: Pelipper|move: Roost")
        battle.opponent.active.volatile_statuses = ["roost"]
        first = snapshot_from_framework("foulplay", battle, context)
        self.assertEqual(json.loads(first.public_state_json)["opponent"]["team"][0]["volatiles"], ["roost"])
        context.consume(">battle-gen9ou-test\n|upkeep")
        result = snapshot_from_framework("foulplay", battle, context)
        self.assertEqual(json.loads(result.public_state_json)["opponent"]["team"][0]["volatiles"], [])
        self.assertTrue(any(n["field"] == "singleturn_volatiles" for n in context.adapter_notes))

    def test_heal_ability_owner_and_consumed_berry_are_not_misattributed(self):
        context, _ = context_and_mock()
        context.consume(">battle-gen9ou-test\n|-heal|p2a: Pelipper|100/100|[from] ability: Water Absorb|[of] p1a: Pelipper")
        self.assertEqual(context.evidence[("p2", 0)]["ability"], "waterabsorb")
        self.assertEqual(context.evidence[("p1", 0)]["ability"], "drizzle")
        context.consume(">battle-gen9ou-test\n|-enditem|p2a: Pelipper|Sitrus Berry\n"
                        "|-heal|p2a: Pelipper|100/100|[from] item: Sitrus Berry")
        self.assertIsNone(context.evidence[("p2", 0)]["item"])
        self.assertEqual(context.evidence[("p2", 0)]["removed_item"], "sitrusberry")

    def test_wrong_battle_multiple_requests_and_unsupported_mechanics_are_rejected(self):
        context, battle = context_and_mock()
        with self.assertRaises(ValueError):
            context.consume(">battle-gen9ou-other\n|turn|1")
        with self.assertRaises(ValueError):
            context.consume(">battle-gen9ou-test\n|request|{}\n|request|{}")
        context.consume(">battle-gen9ou-test\n|-transform|p2a: Pelipper|p1a: Pelipper")
        with self.assertRaisesRegex(ValueError, "unsupported"):
            snapshot_from_framework("foulplay", battle, context)

    def test_report_comparison_recomputes_hashes_not_just_trusting_labels(self):
        context, battle = context_and_mock()
        snapshot = snapshot_from_framework("foulplay", battle, context)
        row = json.loads(json.dumps(asdict(snapshot)))
        row["public_state"] = json.loads(row.pop("public_state_json"))
        row.update(semantic_hash=snapshot.semantic_hash, snapshot_hash=snapshot.snapshot_hash)
        self.assertEqual(checked_report_snapshot(row).semantic_hash, snapshot.semantic_hash)
        row["public_state"]["opponent"]["team"][0]["exact_stats"] = {"atk": 999}
        with self.assertRaisesRegex(ValueError, "recorded hashes"):
            checked_report_snapshot(row)


if __name__ == "__main__":
    unittest.main()
