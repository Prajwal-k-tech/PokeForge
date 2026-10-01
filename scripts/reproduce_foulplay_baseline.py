"""Run one pinned FoulPlay Gen 9 OU battle against a local random opponent.

Start the pinned local Showdown server first, then run with the project interpreter:
    node pokemon-showdown/pokemon-showdown start --skip-build --no-security
    .venv/bin/python scripts/reproduce_foulplay_baseline.py \
      --source /path/to/foul-play-at-the-pinned-revision
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import shutil
import socket
import statistics
import subprocess
import sys
import tempfile
import time
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
FOULPLAY_REVISION = "6c467c081e862fb321adb405355beb41aba8e226"
TEAM = ROOT / "data/teams/smoke/pokeforge_smoke.gen9ou_team"
ARTIFACTS = ROOT / ".artifacts/baseline_runs/foulplay_vs_random"
LOCKED_DATA = {
    "gen9ou-0.json": "7f602aed04fc0e42d16420f905b0166711aa4a894a0b87c4f380504e56cea729",
    "showdown_sets.json": "898612165656b5969ef7fbecd764faf8a623039a27eaa2f912c16881b3fba087",
    "pokemon_full_sets.json": "e6129b38f2a605a5464d014a817ca3083986eae87617033a4f82266565b51772",
    "replay_moves.json": "c9fc21cedf5b4468b767285fba7e9a998dd3d3a4c775a5b02827895fe9647889",
}


def normalize_team_export_for_foulplay(export: str) -> str:
    """Normalize observed Showdown forms that pinned FoulPlay cannot map to its team."""
    normalized = export.strip()
    if "Keldeo @" in normalized and "- Secret Sword" in normalized:
        normalized = normalized.replace("Keldeo @", "Keldeo-Resolute @", 1)
    return normalized + "\n"


def battle_protocol_record(message: str) -> dict | None:
    """Preserve exact received battle messages and request strings for hash-keyed fixtures."""
    if not message.startswith(">battle-"):
        return None
    requests = [
        line.removeprefix("|request|")
        for line in message.split("\n")
        if line.startswith("|request|") and line != "|request|"
    ]
    return {
        "schema_version": 1,
        "message": message,
        "message_sha256": hashlib.sha256(message.encode("utf-8")).hexdigest(),
        "requests": [
            {"payload": payload, "sha256": hashlib.sha256(payload.encode("utf-8")).hexdigest()}
            for payload in requests
        ],
    }


def mirrored_result(agent_output: str, opponent_output: str) -> bool:
    """A reproduction smoke succeeds on a consistent completed game, not a required win."""
    return (
        "Winner: PokeForgeFoulPlay" in agent_output
        and "won=False lost=True" in opponent_output
    ) or (
        "Winner: PokeForgeRandom" in agent_output
        and "won=True lost=False" in opponent_output
    )


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def require_local_server() -> None:
    try:
        with socket.create_connection(("127.0.0.1", 8000), timeout=1):
            return
    except OSError as error:
        raise SystemExit("Local Showdown is not listening on port 8000") from error


def require_source(source: Path) -> None:
    actual = subprocess.check_output(
        ["git", "-C", str(source), "rev-parse", "HEAD"], text=True
    ).strip()
    if actual != FOULPLAY_REVISION:
        raise SystemExit(
            f"FoulPlay revision mismatch: expected {FOULPLAY_REVISION}, found {actual}"
        )

    cache_files = {
        "gen9ou-0.json": source / "fp/data/smogon_stats_cache/gen9ou-0.json",
        "showdown_sets.json": source
        / "fp/data/pkmn_sets_cache/gen9ou/showdown_sets.json",
        "pokemon_full_sets.json": source
        / "fp/data/pkmn_sets_cache/gen9ou/pokemon_full_sets.json",
        "replay_moves.json": source
        / "fp/data/pkmn_sets_cache/gen9ou/replay_moves.json",
    }
    for name, expected in LOCKED_DATA.items():
        path = cache_files[name]
        local_copy = ROOT / ".artifacts/foulplay-data/gen9ou" / name
        if not path.is_file() and local_copy.is_file() and sha256(local_copy) == expected:
            path.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(local_copy, path)
        if not path.is_file() or sha256(path) != expected:
            raise SystemExit(f"Missing or changed locked FoulPlay inference data: {path}")


async def run_opponent(output: Path = ARTIFACTS) -> None:
    from poke_env import AccountConfiguration, LocalhostServerConfiguration
    from poke_env.player import RandomPlayer

    player = RandomPlayer(
        account_configuration=AccountConfiguration("PokeForgeRandom", None),
        battle_format="gen9ou",
        team=TEAM.read_text(),
        server_configuration=LocalhostServerConfiguration,
        save_replays=str(output / "replays"),
        start_timer_on_battle_start=False,
    )
    await player.accept_challenges(None, 1)
    battle = next(iter(player.battles.values()))
    print(
        f"tag={battle.battle_tag} won={battle.won} lost={battle.lost} "
        f"turns={battle.turn}"
    )


async def run_agent(source: Path, args: argparse.Namespace) -> None:
    sys.path.insert(0, str(source))
    import fp.modes.base as base_mode
    import fp.run_battle as run_battle
    from fp.main import run_foul_play
    from fp.websocket_client import PSWebsocketClient

    if args.capture_requests is not None or args.capture_protocol is not None:
        capture_path = args.capture_requests.resolve() if args.capture_requests else None
        if capture_path:
            capture_path.parent.mkdir(parents=True, exist_ok=True)
        protocol_path = args.capture_protocol.resolve() if args.capture_protocol else None
        if protocol_path:
            protocol_path.parent.mkdir(parents=True, exist_ok=True)
            # A transcript is experimental evidence; do not append to or replace an older run.
            with protocol_path.open("x"):
                pass
        captured_requests: list[dict[str, object]] = []
        original_receive_message = PSWebsocketClient.receive_message

        async def capture_receive_message(client):
            message = await original_receive_message(client)
            if protocol_path:
                record = battle_protocol_record(message)
                if record is not None:
                    with protocol_path.open("a") as stream:
                        stream.write(json.dumps(record, ensure_ascii=False) + "\n")
            for line in message.splitlines():
                if not line.startswith("|request|"):
                    continue
                payload = line.split("|request|", 1)[1]
                try:
                    captured_requests.append(json.loads(payload))
                except json.JSONDecodeError:
                    continue
            if capture_path:
                capture_path.write_text(
                    json.dumps(captured_requests, indent=2, sort_keys=True) + "\n"
                )
            return message

        PSWebsocketClient.receive_message = capture_receive_message

    async def local_login(client):
        await client.get_id_and_challstr()
        await client.send_message("", [f"/trn {client.username},0,"])
        await asyncio.sleep(0.25)
        return client.username

    PSWebsocketClient.login = local_login
    decision_ms = []
    original_pick_move = base_mode.async_pick_move

    async def timed_pick_move(battle):
        started = time.perf_counter_ns()
        result = await original_pick_move(battle)
        elapsed_ms = (time.perf_counter_ns() - started) / 1_000_000
        decision_ms.append(elapsed_ms)
        print(f"POKEFORGE_DECISION_MS={elapsed_ms:.6f}", flush=True)
        return result

    base_mode.async_pick_move = timed_pick_move
    run_battle.async_pick_move = timed_pick_move
    mode = "challenge_user" if args.role == "challenge" else "accept_challenge"
    team_directory = tempfile.TemporaryDirectory(prefix="pokeforge-foulplay-team-")
    normalized_team = Path(team_directory.name) / args.team.name
    normalized_team.write_text(normalize_team_export_for_foulplay(args.team.read_text()))
    sys.argv = [
        "run.py",
        "--websocket-uri",
        "local",
        "--ps-username",
        args.username,
        "--bot-mode",
        mode,
        "--pokemon-format",
        "gen9ou",
        "--team-name",
        str(normalized_team),
        "--search-time-ms",
        str(args.search_time_ms),
        "--search-parallelism",
        "1",
        "--search-threads",
        "1",
        "--run-count",
        str(args.run_count),
        "--save-replay",
        "never",
        "--log-level",
        args.log_level,
    ]
    if args.role == "challenge":
        sys.argv.extend(["--user-to-challenge", args.opponent])
    try:
        await run_foul_play()
    finally:
        team_directory.cleanup()
    if decision_ms:
        ordered = sorted(decision_ms)
        metrics = {
            "count": len(ordered),
            "mean_ms": statistics.fmean(ordered),
            "p50_ms": statistics.median(ordered),
            "p95_ms": ordered[max(0, int(0.95 * len(ordered) + 0.999999) - 1)],
            "max_ms": ordered[-1],
        }
        print("POKEFORGE_FOULPLAY_METRICS=" + json.dumps(metrics), flush=True)


def orchestrate(
    source: Path, foulplay_python: Path, capture_requests: Path | None = None,
    capture_protocol: Path | None = None,
    output: Path = ARTIFACTS, search_time_ms: int = 25,
) -> None:
    require_local_server()
    require_source(source)
    subprocess.run(
        [
            "node",
            str(ROOT / "pokemon-showdown/pokemon-showdown"),
            "validate-team",
            "gen9ou",
        ],
        input=TEAM.read_text(),
        text=True,
        check=True,
        cwd=ROOT,
    )
    if capture_protocol is not None and capture_protocol.exists():
        raise SystemExit(f"Protocol capture already exists: {capture_protocol}")
    output.mkdir(parents=True, exist_ok=True)
    opponent = subprocess.Popen(
        [str(ROOT / ".venv/bin/python"), __file__, "--internal-opponent", "--output", str(output.resolve())],
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        cwd=ROOT,
    )
    time.sleep(1)
    try:
        agent = subprocess.run(
            [
                str(foulplay_python),
                __file__,
                "--internal-agent",
                "--source",
                str(source),
                "--team",
                str(TEAM),
                "--username",
                "PokeForgeFoulPlay",
                "--opponent",
                "PokeForgeRandom",
                "--search-time-ms",
                str(search_time_ms),
            ]
            + (
                ["--capture-requests", str(capture_requests.resolve())]
                if capture_requests is not None
                else []
            )
            + (
                ["--capture-protocol", str(capture_protocol.resolve())]
                if capture_protocol is not None
                else []
            ),
            capture_output=True,
            text=True,
            timeout=180,
            cwd=source,
        )
        opponent_output, _ = opponent.communicate(timeout=15)
    finally:
        if opponent.poll() is None:
            opponent.terminate()
            try:
                opponent.wait(timeout=5)
            except subprocess.TimeoutExpired:
                opponent.kill()
                opponent.wait(timeout=5)

    (output / "foulplay.stdout.log").write_text(agent.stdout + agent.stderr)
    (output / "opponent.stdout.log").write_text(opponent_output)
    if agent.returncode or opponent.returncode:
        raise SystemExit(
            f"baseline failed: foulplay={agent.returncode}, opponent={opponent.returncode}"
        )
    if not mirrored_result(agent.stdout, opponent_output):
        raise SystemExit("battle completed without a consistent mirrored result")
    print(opponent_output.strip())
    print("FoulPlay completed one pinned local Gen 9 OU battle")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", type=Path)
    parser.add_argument("--output", type=Path, default=ARTIFACTS)
    parser.add_argument(
        "--foulplay-python",
        type=Path,
        default=ROOT / ".venvs/foulplay/bin/python",
    )
    parser.add_argument("--internal-opponent", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument("--internal-agent", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument("--team", type=Path, default=TEAM)
    parser.add_argument("--username", default="PokeForgeFoulPlay")
    parser.add_argument("--opponent", default="PokeForgeRandom")
    parser.add_argument("--role", choices=["challenge", "accept"], default="challenge")
    parser.add_argument("--search-time-ms", type=int, default=25)
    parser.add_argument("--run-count", type=int, default=1)
    parser.add_argument("--log-level", choices=["DEBUG", "INFO"], default="INFO")
    parser.add_argument(
        "--capture-requests",
        type=Path,
        help="Write parsed request objects (for exact payloads use --capture-protocol).",
    )
    parser.add_argument(
        "--capture-protocol",
        type=Path,
        help="Write exact received battle messages and request hashes to a new JSONL file.",
    )
    args = parser.parse_args()
    if args.internal_opponent:
        asyncio.run(run_opponent(args.output))
    elif args.internal_agent:
        if args.source is None:
            parser.error("--source is required")
        asyncio.run(run_agent(args.source.resolve(), args))
    else:
        if args.source is None:
            parser.error("--source is required")
        foulplay_python = (
            args.foulplay_python
            if args.foulplay_python.is_absolute()
            else ROOT / args.foulplay_python
        )
        orchestrate(
            args.source.resolve(), foulplay_python, args.capture_requests,
            args.capture_protocol, args.output, args.search_time_ms,
        )


if __name__ == "__main__":
    main()
