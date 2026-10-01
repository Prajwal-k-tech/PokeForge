import hashlib
import json
import unittest

from scripts.reproduce_foulplay_baseline import (
    battle_protocol_record,
    normalize_team_export_for_foulplay,
    mirrored_result,
)


class FoulPlayTeamBoundaryTests(unittest.TestCase):
    def test_smoke_accepts_either_consistent_winner_not_only_foulplay(self):
        self.assertTrue(mirrored_result("Winner: PokeForgeFoulPlay", "won=False lost=True"))
        self.assertTrue(mirrored_result("Winner: PokeForgeRandom", "won=True lost=False"))
        self.assertFalse(mirrored_result("Winner: PokeForgeFoulPlay", "won=True lost=False"))
        self.assertFalse(mirrored_result("incomplete", "won=False lost=False"))

    def test_protocol_capture_retains_exact_payload_and_ignores_chat_request_text(self):
        payload = ' { "rqid" : 7, "label" : "Pokémon" }'
        message = '>battle-gen9ou-1\n|chat|alice|example |request|{}\n|request|' + payload
        record = battle_protocol_record(message)
        restored = json.loads(json.dumps(record, ensure_ascii=False))
        self.assertEqual(restored["message"], message)
        self.assertEqual(restored["requests"], [{
            "payload": payload,
            "sha256": hashlib.sha256(payload.encode("utf-8")).hexdigest(),
        }])
        self.assertNotEqual(
            restored["requests"][0]["sha256"],
            hashlib.sha256(json.dumps(json.loads(payload)).encode("utf-8")).hexdigest(),
        )

    def test_protocol_capture_omits_login_messages_and_empty_requests(self):
        self.assertIsNone(battle_protocol_record("|challstr|1|private-login-data"))
        self.assertEqual(battle_protocol_record(">battle-gen9ou-1\n|request|")["requests"], [])

    def test_keldeo_secret_sword_uses_showdown_battle_form(self):
        export = "Keldeo @ Choice Specs\n- Surf\n- Secret Sword\n\n\n"
        normalized = normalize_team_export_for_foulplay(export)
        self.assertTrue(normalized.startswith("Keldeo-Resolute @"))
        self.assertFalse(normalized.endswith("\n\n"))

    def test_unrelated_keldeo_and_other_teams_are_unchanged(self):
        keldeo = "Keldeo @ Choice Specs\n- Surf\n"
        pikachu = "Pikachu @ Light Ball\n- Thunderbolt\n\n"
        self.assertEqual(normalize_team_export_for_foulplay(keldeo), keldeo)
        self.assertEqual(
            normalize_team_export_for_foulplay(pikachu),
            "Pikachu @ Light Ball\n- Thunderbolt\n",
        )


if __name__ == "__main__":
    unittest.main()
