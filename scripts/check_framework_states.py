"""Replay one hash-verified player transcript through a pinned native framework parser.

Run in each isolated baseline environment, then compare complete semantic snapshots. This checks
parser/projection conformance, not search, simulator transitions, or competitive strength.
"""

from __future__ import annotations

import argparse
import json
import logging
import subprocess
import sys
from importlib.metadata import distribution
from dataclasses import asdict, fields
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from scripts.check_framework_actions import REVISIONS
from src.integration.contracts import (ActionKey, ActionKind, BattlePhase, BattleSnapshot, TeamSlot,
                                       canonical_json, hash_protocol_payload)
from src.integration.framework_state import TranscriptContext, snapshot_from_framework

SHOWDOWN_REVISION = "a5df8274e85b0889bf2a9b3422a08b39732374fc"
POKE_ENV_REVISION = "e1268d270c3f2bd32c7ff5713e01062302020579"


def checked_report_snapshot(row):
    values = {f.name: row[f.name] for f in fields(BattleSnapshot) if f.name != "public_state_json"}
    values["phase"] = BattlePhase(values["phase"])
    for side in ("self_team", "opponent_team"):
        values[side] = tuple(TeamSlot(**p) for p in values[side])
    values["legal_actions"] = tuple(ActionKey(**(a | {"kind": ActionKind(a["kind"]),
                                                        "preview_order": tuple(a["preview_order"])}))
                                     for a in values["legal_actions"])
    values["public_state_json"] = canonical_json(row["public_state"])
    snapshot = BattleSnapshot(**values)
    if snapshot.semantic_hash != row["semantic_hash"] or snapshot.snapshot_hash != row["snapshot_hash"]:
        raise ValueError("comparison snapshot contents do not match recorded hashes")
    return snapshot


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--framework", choices=REVISIONS, required=True)
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--capture", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--compare", type=Path)
    args = parser.parse_args()
    revision = subprocess.check_output(["git", "-C", str(args.source), "rev-parse", "HEAD"], text=True).strip()
    if revision != REVISIONS[args.framework]:
        raise ValueError("wrong source revision")
    dirty = subprocess.check_output(["git", "-C", str(args.source), "status", "--short"], text=True).strip()
    if dirty:
        raise ValueError("native source checkout is not clean")
    sys.path.insert(0, str(args.source.resolve()))
    logging.disable(logging.CRITICAL)
    captures = [json.loads(line) for line in args.capture.read_text().splitlines()]
    for capture in captures:
        if hash_protocol_payload(capture["message"]) != capture["message_sha256"]:
            raise ValueError("bad message hash")
        for request in capture["requests"]:
            if hash_protocol_payload(request["payload"]) != request["sha256"]:
                raise ValueError("bad request hash")
        actual = [line[len("|request|"):] for line in capture["message"].split("\n")[1:]
                  if line.startswith("|request|") and line != "|request|"]
        if actual != [r["payload"] for r in capture["requests"]]:
            raise ValueError("request index differs from exact message payloads")
    battle_tag = captures[0]["message"].splitlines()[0].removeprefix(">")
    context = TranscriptContext(battle_tag, format_id="gen9ou-local-pinned", rules_revision=SHOWDOWN_REVISION)
    first = next(json.loads(r["payload"]) for c in captures for r in c["requests"])
    if args.framework == "foulplay":
        import fp
        from fp.battle.state import Battle
        from fp.battle.protocol import process_battle_updates, update_battle
        from fp.config import FoulPlayConfig
        from fp.modes.standard_battle import StandardBattleMode
        FoulPlayConfig.pokemon_format = "gen9ou"
        battle = Battle(battle_tag)
        battle.pokemon_format, battle.generation, battle.mode = "gen9ou", "gen9", StandardBattleMode()
        battle.user.name, battle.opponent.name = first["side"]["id"], "p2" if first["side"]["id"] == "p1" else "p1"
        initialized = False
        library_root = Path(fp.__file__).parent
        runtime = {"library": "fp", "revision": revision, "license": "GPL-3.0"}
    else:
        import poke_env
        from poke_env.environment import Battle
        package = distribution("poke-env")
        origin = json.loads(package.read_text("direct_url.json") or "{}")
        if package.version != "0.8.3.3" or origin.get("vcs_info", {}).get("commit_id") != POKE_ENV_REVISION:
            raise ValueError("wrong pinned Metamon poke-env runtime")
        battle = Battle(battle_tag, first["side"]["name"], logging.getLogger("state-conformance"), 9)
        initialized = True
        library_root = Path(poke_env.__file__).parent
        runtime = {"library": "poke-env", "version": package.version, "revision": POKE_ENV_REVISION, "license": "MIT"}
    runtime["file_sha256"] = {str(p.relative_to(library_root)): hash_protocol_payload(p.read_bytes())
                              for p in sorted(library_root.rglob("*")) if p.is_file() and p.suffix in {".py", ".json"}}
    snapshots = []
    for number, capture in enumerate(captures):
        message = capture["message"]
        context.consume(message)
        if args.framework == "foulplay":
            if not initialized and capture["requests"]:
                battle.user.initialize_first_turn_user_from_json(context.request)
                opponent = "p2" if context.perspective == "p1" else "p1"
                battle.initialize_team_preview(context.preview[opponent], "gen9ou")
                initialized = True
            update_battle(battle, message)
            if context.finished:
                process_battle_updates(battle)
        else:
            for line in message.split("\n")[1:]:
                if not line.startswith("|"):
                    continue
                fields = line.split("|")
                if fields[1] == "request" and fields[2]:
                    battle.parse_request(json.loads(line[len("|request|"):]))
                elif fields[1] == "win":
                    battle.won_by(fields[2])
                elif fields[1] == "tie":
                    battle.tied()
                elif fields[1] in {"t:", "init", "title", "j", "l", "html", "deinit"}:
                    continue
                else:
                    battle.parse_message(fields)
        if capture["requests"] or (context.finished and not any(s["phase"] == "finished" for s in snapshots)):
            snapshot = snapshot_from_framework(args.framework, battle, context)
            row = asdict(snapshot)
            row["public_state"] = json.loads(row.pop("public_state_json"))
            row |= {"message_index": number, "semantic_hash": snapshot.semantic_hash, "snapshot_hash": snapshot.snapshot_hash}
            row["adapter_notes"] = context.adapter_notes
            snapshots.append(row)
            print(f"rqid={snapshot.rqid} turn={snapshot.turn} {snapshot.phase}: {snapshot.semantic_hash[:12]}")
    comparison = None
    if args.compare:
        other = json.loads(args.compare.read_text())
        if other["framework"] == args.framework or other["source_revision"] != REVISIONS[other["framework"]]:
            raise ValueError("comparison requires the other pinned framework")
        if other["adapter_sha256"] != hash_protocol_payload((ROOT / "src/integration/framework_state.py").read_bytes()):
            raise ValueError("comparison report used different adapter code")
        if other["capture_sha256"] != hash_protocol_payload(args.capture.read_bytes()):
            raise ValueError("comparison used different capture")
        if len(other["snapshots"]) != len(snapshots):
            raise ValueError("different snapshot count")
        for left, right in zip(other["snapshots"], snapshots, strict=True):
            if checked_report_snapshot(left).semantic_hash != checked_report_snapshot(right).semantic_hash:
                raise ValueError(f"semantic mismatch at rqid={right['rqid']} turn={right['turn']}")
        comparison = {"framework": other["framework"], "report_sha256": hash_protocol_payload(args.compare.read_bytes()),
                      "equal_semantic_snapshots": len(snapshots)}
    report = {"schema_version": 1, "framework": args.framework, "source_revision": revision,
              "capture_sha256": hash_protocol_payload(args.capture.read_bytes()),
              "adapter_sha256": hash_protocol_payload((ROOT / "src/integration/framework_state.py").read_bytes()),
              "runner_sha256": hash_protocol_payload(Path(__file__).read_bytes()),
              "native_runtime": runtime,
              "scope": "native parser/projector differential on one transcript; not all mechanics or Gate 0B completion",
              "inference_scope": "FoulPlay native mode with empty datasets: public parser audit, not baseline belief/search reproduction" if args.framework == "foulplay" else "pinned poke-env native parser; no checkpoint/policy inference",
              "snapshots": snapshots, "comparison": comparison, "gate_0b_passed": False}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("x") as stream:
        stream.write(json.dumps(report, indent=2, sort_keys=True) + "\n")
    print(args.output)


if __name__ == "__main__":
    main()
