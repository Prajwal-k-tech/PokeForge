"""Run paired, side-swapped FoulPlay versus Minikazam Gen 9 OU games."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import os
import re
import socket
import subprocess
import time
import tomllib
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
MANIFEST = ROOT / "config/team_pools/gen9ou_control_v1.toml"
TEAM_DIRECTORY = ROOT / ".artifacts/metamon/teams/competitive/gen9ou"
FOULPLAY_REVISION = "6c467c081e862fb321adb405355beb41aba8e226"


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def require_server() -> None:
    try:
        with socket.create_connection(("127.0.0.1", 8000), timeout=1):
            return
    except OSError as error:
        raise SystemExit("Local Showdown is not listening on port 8000") from error


def load_teams(directory: Path) -> list[dict[str, str | Path]]:
    manifest = tomllib.loads(MANIFEST.read_text())
    teams = []
    for entry in manifest["teams"]:
        path = directory / entry["file"]
        actual = sha256(path) if path.is_file() else None
        if actual != entry["sha256"]:
            raise SystemExit(
                f"Team hash mismatch for {path}: expected {entry['sha256']}, found {actual}"
            )
        validation = subprocess.run(
            [
                "node",
                str(ROOT / "pokemon-showdown/pokemon-showdown"),
                "validate-team",
                manifest["format"],
            ],
            input=path.read_text(),
            text=True,
            capture_output=True,
            cwd=ROOT,
        )
        if validation.returncode:
            raise SystemExit(f"Pinned Showdown rejected {path}: {validation.stdout}{validation.stderr}")
        teams.append({"path": path.resolve(), "sha256": actual})
    return teams


def wait_for_log(process: subprocess.Popen[str], log_path: Path, marker: str, timeout: int) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if process.poll() is not None:
            raise RuntimeError(
                f"Process exited before readiness marker {marker!r}; see {log_path}"
            )
        if log_path.is_file() and marker in log_path.read_text(errors="replace"):
            time.sleep(0.5)
            return
        time.sleep(0.2)
    raise TimeoutError(f"Timed out waiting for {marker!r}; see {log_path}")


def stop_child(process: subprocess.Popen[str] | None) -> None:
    if process is None or process.poll() is not None:
        return
    process.terminate()
    try:
        process.wait(timeout=5)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait(timeout=5)


def parse_tagged_json(text: str, tag: str) -> dict:
    matches = re.findall(rf"^{re.escape(tag)}=(.+)$", text, flags=re.MULTILINE)
    if not matches:
        raise RuntimeError(f"Missing {tag} in captured log")
    return json.loads(matches[-1])


def write_progress(output: Path, games: list[dict]) -> None:
    """Persist every completed game so an interrupted long benchmark remains auditable."""
    path = output / "progress.json"
    path.write_text(
        json.dumps(
            {"schema_version": 1, "completed_games": games},
            indent=2,
            sort_keys=True,
        )
        + "\n"
    )


def run_game(
    *,
    game_index: int,
    foul_team: dict[str, str | Path],
    metamon_team: dict[str, str | Path],
    foul_role: str,
    output: Path,
    foulplay_source: Path,
    foulplay_python: Path,
    metamon_python: Path,
    search_time_ms: int,
    metamon_model: str,
    metamon_checkpoint: int | None,
    timeout: int,
    metamon_strict_policy_gate: bool = False,
) -> dict:
    game_dir = output / f"game_{game_index:03d}"
    game_dir.mkdir(parents=True, exist_ok=False)
    foul_log_path = game_dir / "foulplay.log"
    metamon_log_path = game_dir / "metamon.log"
    results_dir = game_dir / "metamon_results"
    trajectories_dir = game_dir / "trajectories"
    foul_username = f"PFF{game_index:04d}"
    metamon_username = f"PFM{game_index:04d}"
    metamon_role = "acceptor" if foul_role == "challenge" else "challenger"

    foul_command = [
        str(foulplay_python),
        str(ROOT / "scripts/reproduce_foulplay_baseline.py"),
        "--internal-agent",
        "--source",
        str(foulplay_source),
        "--team",
        str(foul_team["path"]),
        "--username",
        foul_username,
        "--opponent",
        metamon_username,
        "--role",
        foul_role,
        "--search-time-ms",
        str(search_time_ms),
        "--run-count",
        "1",
    ]
    metamon_command = [
        str(metamon_python),
        str(ROOT / "scripts/run_metamon_challenge.py"),
        "--team",
        str(metamon_team["path"]),
        "--username",
        metamon_username,
        "--opponent",
        foul_username,
        "--role",
        metamon_role,
        "--model",
        metamon_model,
        "--results",
        str(results_dir),
        "--trajectories",
        str(trajectories_dir),
    ]
    if metamon_checkpoint is not None:
        metamon_command.extend(["--checkpoint", str(metamon_checkpoint)])
    if metamon_strict_policy_gate:
        metamon_command.extend(["--strict-policy-gate", "--safety-log", str(game_dir / "safety.jsonl")])
    environment = os.environ.copy()
    environment.update(
        {
            "HF_HUB_OFFLINE": "1",
            "METAMON_CACHE_DIR": str(ROOT / ".artifacts/metamon"),
            "PYTHONUNBUFFERED": "1",
        }
    )

    foul_process = None
    metamon_process = None
    with foul_log_path.open("w") as foul_log, metamon_log_path.open("w") as metamon_log:
        try:
            if foul_role == "challenge":
                metamon_process = subprocess.Popen(
                    metamon_command,
                    stdout=metamon_log,
                    stderr=subprocess.STDOUT,
                    text=True,
                    cwd=ROOT,
                    env=environment,
                )
                wait_for_log(metamon_process, metamon_log_path, "Made Challenge Env", 90)
                foul_process = subprocess.Popen(
                    foul_command,
                    stdout=foul_log,
                    stderr=subprocess.STDOUT,
                    text=True,
                    cwd=ROOT,
                    env=environment,
                )
            else:
                foul_process = subprocess.Popen(
                    foul_command,
                    stdout=foul_log,
                    stderr=subprocess.STDOUT,
                    text=True,
                    cwd=ROOT,
                    env=environment,
                )
                wait_for_log(foul_process, foul_log_path, "Waiting for a gen9ou challenge", 30)
                metamon_process = subprocess.Popen(
                    metamon_command,
                    stdout=metamon_log,
                    stderr=subprocess.STDOUT,
                    text=True,
                    cwd=ROOT,
                    env=environment,
                )
            deadline = time.monotonic() + timeout
            while time.monotonic() < deadline:
                metamon_returncode = metamon_process.poll()
                foul_returncode = foul_process.poll()
                if metamon_returncode not in (None, 0) or foul_returncode not in (None, 0):
                    break
                if metamon_returncode == foul_returncode == 0:
                    break
                time.sleep(0.2)
            else:
                raise TimeoutError(f"Game {game_index} exceeded {timeout} seconds")
            if metamon_returncode or foul_returncode:
                raise RuntimeError(
                    f"Agent failed: metamon={metamon_returncode}, foulplay={foul_returncode}"
                )
        finally:
            stop_child(foul_process)
            stop_child(metamon_process)

    foul_text = foul_log_path.read_text(errors="replace")
    metamon_text = metamon_log_path.read_text(errors="replace")
    result_files = list(results_dir.glob("*.csv"))
    if len(result_files) != 1:
        raise RuntimeError(f"Expected one result CSV, found {len(result_files)}")
    with result_files[0].open(newline="") as stream:
        rows = list(csv.DictReader(stream))
    if len(rows) != 1:
        raise RuntimeError(f"Expected one result row, found {len(rows)}")
    row = {key.strip(): value.strip() for key, value in rows[0].items()}
    metamon_won = row["Result"] == "WIN"
    if row["Result"] not in {"WIN", "LOSS"}:
        raise RuntimeError(f"Ambiguous game outcome: {row['Result']}")
    winner = metamon_username if metamon_won else foul_username
    observed = re.findall(r"Winner: (\S+)", foul_text)
    if len(observed) != 1 or observed[0].lower() != winner.lower():
        raise RuntimeError("Agent outcomes do not agree")
    return {
        "game_index": game_index,
        "winner": winner,
        "metamon_won": metamon_won,
        "turn_count": int(row["Turn Count"]),
        "turn_count_semantics": "Metamon environment decision steps, not Showdown turns",
        "last_showdown_turn_logged": max(map(int, re.findall(r"Turn: (\d+)", foul_text))),
        "metamon_battle_id": row["Battle ID"],
        "showdown_battle_tag": (
            re.findall(r"Initialized (battle-gen9ou-\d+)", foul_text) or [None]
        )[-1],
        "foulplay": {
            "username": foul_username,
            "role": foul_role,
            "team": Path(foul_team["path"]).name,
            "team_sha256": foul_team["sha256"],
            "timing": parse_tagged_json(foul_text, "POKEFORGE_FOULPLAY_METRICS"),
            "log_sha256": sha256(foul_log_path),
        },
        "metamon": {
            "username": metamon_username,
            "role": metamon_role,
            "team": Path(metamon_team["path"]).name,
            "team_sha256": metamon_team["sha256"],
            "metrics": parse_tagged_json(metamon_text, "POKEFORGE_METAMON_METRICS"),
            "log_sha256": sha256(metamon_log_path),
            "safety_log_sha256": sha256(game_dir / "safety.jsonl") if metamon_strict_policy_gate else None,
        },
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--foulplay-source", type=Path, required=True)
    parser.add_argument("--pairs", type=int, default=1)
    parser.add_argument(
        "--start-pair",
        type=int,
        default=0,
        help="Zero-based pair index; enables a fresh, non-overlapping continuation run.",
    )
    parser.add_argument("--search-time-ms", type=int, default=25)
    parser.add_argument("--metamon-model", default="Minikazam")
    parser.add_argument("--metamon-checkpoint", type=int)
    parser.add_argument("--metamon-strict-policy-gate", action="store_true",
                        help="Evaluate the separately labeled PokeForge request-gated variant.")
    parser.add_argument("--timeout", type=int, default=600)
    parser.add_argument("--team-directory", type=Path, default=TEAM_DIRECTORY)
    parser.add_argument(
        "--foulplay-python",
        type=Path,
        default=ROOT / ".venvs/foulplay-rebuild/bin/python",
    )
    parser.add_argument(
        "--metamon-python",
        type=Path,
        default=ROOT / ".venvs/metamon-rebuild/bin/python",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=ROOT / ".artifacts/baseline_runs/head_to_head/paired",
    )
    args = parser.parse_args()
    if args.pairs < 1:
        parser.error("--pairs must be positive")
    if args.start_pair < 0:
        parser.error("--start-pair must be non-negative")
    require_server()
    revision = subprocess.check_output(
        ["git", "-C", str(args.foulplay_source), "rev-parse", "HEAD"], text=True
    ).strip()
    if revision != FOULPLAY_REVISION:
        raise SystemExit(f"FoulPlay revision mismatch: expected {FOULPLAY_REVISION}, found {revision}")
    teams = load_teams(args.team_directory)
    if args.start_pair + args.pairs > len(teams) // 2:
        parser.error(
            "--start-pair plus --pairs exceeds the available non-repeating team pairs "
            f"({len(teams) // 2})"
        )
    args.output.mkdir(parents=True, exist_ok=False)

    games = []
    for pair_index in range(args.start_pair, args.start_pair + args.pairs):
        team_a = teams[2 * pair_index]
        team_b = teams[2 * pair_index + 1]
        games.append(
            run_game(
                game_index=2 * pair_index + 1,
                foul_team=team_a,
                metamon_team=team_b,
                foul_role="challenge",
                output=args.output,
                foulplay_source=args.foulplay_source.resolve(),
                foulplay_python=args.foulplay_python.absolute(),
                metamon_python=args.metamon_python.absolute(),
                search_time_ms=args.search_time_ms,
                metamon_model=args.metamon_model,
                metamon_checkpoint=args.metamon_checkpoint,
                timeout=args.timeout,
                metamon_strict_policy_gate=args.metamon_strict_policy_gate,
            )
        )
        write_progress(args.output, games)
        games.append(
            run_game(
                game_index=2 * pair_index + 2,
                foul_team=team_b,
                metamon_team=team_a,
                foul_role="accept",
                output=args.output,
                foulplay_source=args.foulplay_source.resolve(),
                foulplay_python=args.foulplay_python.absolute(),
                metamon_python=args.metamon_python.absolute(),
                search_time_ms=args.search_time_ms,
                metamon_model=args.metamon_model,
                metamon_checkpoint=args.metamon_checkpoint,
                timeout=args.timeout,
                metamon_strict_policy_gate=args.metamon_strict_policy_gate,
            )
        )
        write_progress(args.output, games)
        print(f"completed source pair {pair_index + 1}", flush=True)

    summary = {
        "schema_version": 1,
        "created_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        "format": "gen9ou",
        "purpose": "engineering harness; not a strength claim at small sample sizes",
        "showdown_revision": tomllib.loads(MANIFEST.read_text())["showdown_revision"],
        "foulplay_revision": FOULPLAY_REVISION,
        "search_time_ms_per_world": args.search_time_ms,
        "metamon_model": args.metamon_model,
        "metamon_checkpoint": args.metamon_checkpoint,
        "metamon_policy_variant": "pokeforge-request-gated-v1" if args.metamon_strict_policy_gate else "upstream",
        "pairs": args.pairs,
        "start_pair": args.start_pair,
        "games": games,
        "metamon_wins": sum(game["metamon_won"] for game in games),
        "foulplay_wins": sum(not game["metamon_won"] for game in games),
    }
    summary_path = args.output / "summary.json"
    summary_path.write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n")
    print(summary_path)


if __name__ == "__main__":
    main()
