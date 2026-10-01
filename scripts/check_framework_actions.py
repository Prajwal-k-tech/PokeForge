"""Offline differential check against a pinned framework's actual action formatter.

Run once in each isolated environment; no server, GPU, checkpoint, or network is required.
"""

from __future__ import annotations

import argparse
import copy
import json
import logging
import os
import subprocess
import sys
from dataclasses import asdict
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from src.integration.contracts import ActionKey, ActionKind, canonical_json, hash_protocol_payload
from src.integration.framework_actions import (
    foulplay_wire_choice_to_action_key,
    metamon_action_index_to_action_key,
)
from src.integration.showdown_request import legal_actions_from_request


REVISIONS = {
    "foulplay": "6c467c081e862fb321adb405355beb41aba8e226",
    "metamon": "0a00a759c9a4382a2877088d828302ec294a05a5",
}


def scenarios(capture: Path | None = None):
    normal = json.loads((ROOT / "tests/fixtures/foulplay_local_normal_request.json").read_text())
    yield "normal", normal
    request = copy.deepcopy(normal)
    request["active"][0]["moves"][0]["disabled"] = True
    yield "disabled_first_sorted_move", request
    request = copy.deepcopy(normal)
    request["active"][0]["moves"][3].update(pp=0, disabled=True)
    yield "exhausted_middle_sorted_move", request
    request = copy.deepcopy(normal)
    request["active"][0]["trapped"] = True
    yield "trapped", request
    request = copy.deepcopy(normal)
    request["side"]["pokemon"][2]["condition"] = "0 fnt"
    yield "fainted_first_sorted_bench", request
    request = copy.deepcopy(normal)
    request.pop("active")
    request["forceSwitch"] = [True]
    request["side"]["pokemon"][0]["condition"] = "0 fnt"
    yield "forced_switch", request
    request = copy.deepcopy(normal)
    request["active"][0].pop("canTerastallize")
    yield "tera_unavailable", request
    request = copy.deepcopy(normal)
    request["active"] = [{"moves": [
        {"id": "struggle", "move": "Struggle", "pp": 1, "disabled": False, "target": "randomNormal"}
    ]}]
    yield "struggle_with_switches", request

    if capture is not None:
        preview_idents = None
        for line in capture.read_text().splitlines():
            record = json.loads(line)
            if hash_protocol_payload(record["message"]) != record["message_sha256"]:
                raise AssertionError("capture message hash mismatch")
            for captured in record["requests"]:
                payload = captured["payload"]
                if hash_protocol_payload(payload) != captured["sha256"]:
                    raise AssertionError("capture request hash mismatch")
                request = json.loads(payload)
                idents = [member["ident"] for member in request.get("side", {}).get("pokemon", [])]
                if request.get("teamPreview"):
                    if len(idents) != 6 or len(set(idents)) != 6:
                        raise AssertionError("capture needs six unique own preview identities")
                    preview_idents = idents
                elif not request.get("wait"):
                    if preview_idents is None or sorted(idents) != sorted(preview_idents):
                        raise AssertionError("request identities no longer match captured preview")
                    yield f"captured_rqid_{request['rqid']}", request, tuple(
                        preview_idents.index(ident) for ident in idents
                    ), payload


def metamon_orders(request, mapping):
    from poke_env.environment import Battle, Move, Pokemon
    from metamon.interface import UniversalAction

    battle = Battle("battle-gen9ou-conformance", "PokeForgeFoulPlay", logging.getLogger("conformance"), 9)
    battle.parse_request(request)
    legal = set(legal_actions_from_request(canonical_json(request), mapping).actions)
    rows = []
    for index in range(13):
        order = UniversalAction.action_idx_to_BattleOrder(battle, index)
        try:
            translated = metamon_action_index_to_action_key(index, canonical_json(request), mapping)
        except ValueError:
            translated = None
        observed = None
        if order is not None and isinstance(order.order, Move):
            if order.order.id == "struggle":
                observed = ActionKey(ActionKind.STRUGGLE)
            else:
                matches = [
                    slot for slot, move in enumerate(request.get("active", [{}])[0].get("moves", []))
                    if move["id"] == order.order.id
                ]
                if len(matches) != 1:
                    raise AssertionError(f"ambiguous or missing emitted move {order.message}")
                observed = ActionKey.move(matches[0], order.order.id, tera=order.terastallize)
        elif order is not None and isinstance(order.order, Pokemon):
            ident = next(ident for ident, member in battle.team.items() if member is order.order)
            position = next(i for i, member in enumerate(request["side"]["pokemon"]) if member["ident"] == ident)
            observed = ActionKey.switch(mapping[position])

        # Upstream silently downgrades unavailable Tera indices to ordinary moves. The bridge
        # rejects these indices: the policy's legal mask must remove them before use.
        downgrade = index >= 9 and not request.get("active", [{}])[0].get("canTerastallize")
        if downgrade:
            if translated is not None:
                raise AssertionError("unavailable Tera index was accepted")
        elif observed != translated:
            raise AssertionError(f"index {index}: framework={observed}, bridge={translated}")
        if translated is not None and translated not in legal:
            raise AssertionError(f"translated illegal action at index {index}")
        rows.append({"index": index, "wire_command": order.message if order else None,
                     "action": asdict(translated) if translated else None,
                     "rejected_tera_alias": downgrade})
    covered = {canonical_json(row["action"]) for row in rows if row["action"] is not None}
    expected = {canonical_json(asdict(action)) for action in legal}
    if covered != expected:
        raise AssertionError("policy indices do not cover the request's legal action set")
    return rows


def foulplay_orders(request, mapping):
    from fp.battle.state import Battler
    from fp.config import FoulPlayConfig
    from fp.modes.base import format_decision
    from types import SimpleNamespace

    # The reduced fixture omits stats. Supply placeholders only for formatter initialization;
    # these tests perform no damage calculation or search.
    request = copy.deepcopy(request)
    for member in request["side"]["pokemon"]:
        member["stats"] = dict.fromkeys(("atk", "def", "spa", "spd", "spe"), 100)
    FoulPlayConfig.pokemon_format = "gen9ou"
    side = Battler()
    side.initialize_first_turn_user_from_json(request)
    battle = SimpleNamespace(user=side, rqid=request["rqid"])
    payload = canonical_json(request)
    rows = []
    for action in legal_actions_from_request(payload, mapping).actions:
        if action.kind is ActionKind.SWITCH:
            position = mapping.index(action.team_slot)
            reserve = next(member for member in side.reserve if member.index == position + 1)
            decision = f"switch {reserve.name}"
        elif action.kind is ActionKind.STRUGGLE:
            decision = "struggle"
        else:
            decision = action.move_id + ("-tera" if action.tera else "")
        wire, rqid = format_decision(battle, decision)
        translated = foulplay_wire_choice_to_action_key(f"{wire}|{rqid}", payload, mapping)
        if translated != action:
            raise AssertionError(f"{wire}: expected={action}, translated={translated}")
        rows.append({"decision": decision, "wire_command": wire, "action": asdict(translated)})
    return rows


def metamon_sampling_probe():
    """Test the actual distribution separately from the request/action formatter."""
    import torch
    from metamon.rl.metamon_to_amago import MetamonDiscrete

    logits = torch.full((1, 13), -float("inf"))
    logits[0, 4:7] = 0  # Forced replacement with exactly three switch candidates.
    probs = MetamonDiscrete(d_action=13)(logits).probs
    illegal = torch.isneginf(logits)
    return {
        "scope": "synthetic CPU distribution probe; not the recorded game's causal trace",
        "legal_indices": [4, 5, 6],
        "probabilities": probs[0].tolist(),
        "illegal_probability_mass": probs[illegal].sum().item(),
        "issue": "positive probability floor restores masked-out indices after softmax",
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--framework", choices=REVISIONS, required=True)
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--capture", type=Path, help="Also check hash-verified exact requests from one local protocol capture.")
    args = parser.parse_args()
    revision = subprocess.check_output(["git", "-C", str(args.source), "rev-parse", "HEAD"], text=True).strip()
    if revision != REVISIONS[args.framework]:
        raise SystemExit(f"Wrong {args.framework} revision: {revision}")
    sys.path.insert(0, str(args.source.resolve()))
    os.environ.setdefault("METAMON_CACHE_DIR", str(ROOT / ".artifacts/metamon"))
    # Upstream RL imports initialize GenData directly; do this before Battle initializes it.
    sampling_probe = metamon_sampling_probe() if args.framework == "metamon" else None
    check = metamon_orders if args.framework == "metamon" else foulplay_orders
    results = []
    for scenario in scenarios(args.capture):
        name, request = scenario[:2]
        mapping, raw_payload = scenario[2:] if len(scenario) == 4 else ((1, 0, 2, 3, 4, 5), None)
        rows = check(request, mapping)
        results.append({"name": name, "input_projection_sha256": hash_protocol_payload(canonical_json(request)),
                        "received_request_sha256": hash_protocol_payload(raw_payload) if raw_payload else None,
                        "rows": rows})
        print(f"PASS {name}: {len(rows)} framework choices", flush=True)
    report = {"schema_version": 1, "framework": args.framework, "source_revision": revision,
              "scope": "action formatter/parser differential; projected/synthetic cases and optional exact capture",
              "capture_sha256": hash_protocol_payload(args.capture.read_bytes()) if args.capture else None,
              "scenarios": results}
    if args.framework == "metamon":
        report["sampling_probe"] = sampling_probe
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n")
    print(args.output)


if __name__ == "__main__":
    main()
