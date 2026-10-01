"""Run one pinned Minikazam Gen 9 OU battle against Metamon's random baseline.

Start the pinned local Showdown server first:
    node pokemon-showdown/pokemon-showdown start --skip-build --no-security

Run this script with the isolated Metamon interpreter:
    METAMON_CACHE_DIR=$PWD/.artifacts/metamon \
      .venvs/metamon/bin/python scripts/reproduce_metamon_baseline.py
"""

from __future__ import annotations

import json
import os
import socket
import subprocess
from importlib import metadata
from pathlib import Path
from types import MethodType


ROOT = Path(__file__).resolve().parents[1]
METAMON_REVISION = "0a00a759c9a4382a2877088d828302ec294a05a5"
CHECKPOINT_REVISION = "ac8e88e7da8dc2a2b85176d88f81fd8854b1445b"
CHECKPOINT_FILE = "minikazam/ckpts/policy_weights/policy_epoch_40.pt"


def require_local_server() -> None:
    try:
        with socket.create_connection(("127.0.0.1", 8000), timeout=1):
            return
    except OSError as error:
        raise SystemExit("Local Showdown is not listening on port 8000") from error


def require_revision(source: Path, expected: str) -> None:
    if (source / ".git").exists():
        actual = subprocess.check_output(
            ["git", "-C", str(source), "rev-parse", "HEAD"], text=True
        ).strip()
    else:
        direct_url = json.loads(metadata.distribution("metamon").read_text("direct_url.json"))
        actual = direct_url.get("vcs_info", {}).get("commit_id")
    if actual != expected:
        raise SystemExit(f"Metamon revision mismatch: expected {expected}, found {actual}")


def main() -> None:
    cache = Path(os.environ.get("METAMON_CACHE_DIR", ROOT / ".artifacts/metamon"))
    os.environ["METAMON_CACHE_DIR"] = str(cache)
    require_local_server()

    import metamon
    import metamon.env.wrappers as wrappers
    from huggingface_hub import hf_hub_download
    from metamon.env import TeamSet
    from metamon.env.metamon_player import PokeAgentPlayer
    from metamon.rl.evaluate import pretrained_vs_baselines
    from metamon.rl.pretrained import get_pretrained_model

    require_revision(Path(metamon.__file__).resolve().parents[1], METAMON_REVISION)

    checkpoint_path = hf_hub_download(
        repo_id="jakegrigsby/metamon",
        filename=CHECKPOINT_FILE,
        revision=CHECKPOINT_REVISION,
        cache_dir=cache / "pretrained_models",
    )

    # Upstream 1.6.0 defines this class but omits the import in wrappers.py.
    wrappers.PokeAgentPlayer = PokeAgentPlayer
    model = get_pretrained_model("Minikazam")
    model.gin_overrides = (model.gin_overrides or {}) | {
        # AMAGO 3.4.0 annotates this as int but its default literal is the float 1e10.
        "MetamonAMAGOExperiment.traj_save_len": 10_000_000_000,
    }
    model.get_path_to_checkpoint = MethodType(
        lambda self, checkpoint: str(checkpoint_path), model
    )

    teams = TeamSet(str(ROOT / "data/teams/smoke"), "gen9ou")
    results = pretrained_vs_baselines(
        pretrained_model=model,
        battle_format="gen9ou",
        team_set=teams,
        checkpoint=40,
        total_battles=1,
        parallel_actors_per_baseline=1,
        action_temperature=1.0,
        async_mp_context="spawn",
        battle_backend="pokeagent",
        log_to_wandb=False,
        save_results_to=str(ROOT / ".artifacts/baseline_runs/metamon_minikazam_frozen"),
        baselines=["RandomBaseline"],
    )
    print(json.dumps({key: float(value) for key, value in results.items()}, indent=2))


if __name__ == "__main__":
    main()
