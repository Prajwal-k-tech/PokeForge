"""Print a JSON snapshot of the local PokeForge toolchain and repository state."""

from __future__ import annotations

import importlib.metadata
import json
import platform
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def run(*command: str, cwd: Path = ROOT) -> dict[str, object]:
    try:
        result = subprocess.run(
            command,
            cwd=cwd,
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired) as error:
        return {"ok": False, "error": type(error).__name__}

    output = (result.stdout or result.stderr).strip()
    return {"ok": result.returncode == 0, "output": output, "returncode": result.returncode}


def git_state(path: Path) -> dict[str, object]:
    revision = run("git", "rev-parse", "HEAD", cwd=path)
    status = run("git", "status", "--short", cwd=path)
    return {
        "path": str(path.relative_to(ROOT)) if path != ROOT else ".",
        "revision": revision.get("output"),
        "clean": status.get("ok") and not status.get("output"),
        "status": status.get("output", ""),
    }


def package_versions() -> dict[str, str]:
    versions: dict[str, str] = {}
    for package in ("torch", "poke-env", "numpy", "PyYAML", "websockets", "requests"):
        try:
            versions[package] = importlib.metadata.version(package)
        except importlib.metadata.PackageNotFoundError:
            versions[package] = "missing"
    return versions


def torch_state() -> dict[str, object]:
    try:
        import torch

        state: dict[str, object] = {
            "version": torch.__version__,
            "built_cuda": torch.version.cuda,
            "cuda_available": torch.cuda.is_available(),
            "device_count": torch.cuda.device_count(),
        }
        if torch.cuda.is_available():
            devices = []
            for index in range(torch.cuda.device_count()):
                properties = torch.cuda.get_device_properties(index)
                devices.append(
                    {
                        "index": index,
                        "name": properties.name,
                        "capability": list(torch.cuda.get_device_capability(index)),
                        "total_memory_bytes": properties.total_memory,
                    }
                )
            state["devices"] = devices
            try:
                state["operation_smoke"] = float(
                    (torch.ones(1, device="cuda") + 1).cpu().item()
                )
            except Exception as error:
                state["operation_error"] = f"{type(error).__name__}: {error}"
        return state
    except Exception as error:  # diagnostic command must report broken imports
        return {"error": f"{type(error).__name__}: {error}"}


def main() -> None:
    snapshot = {
        "recorded_at": datetime.now(timezone.utc).isoformat(),
        "platform": platform.platform(),
        "python": sys.version.replace("\n", " "),
        "packages": package_versions(),
        "torch": torch_state(),
        "tools": {
            name: run(*command)
            for name, command in {
                "node": ("node", "--version"),
                "rustc": ("rustc", "--version"),
                "cargo": ("cargo", "--version"),
                "uv": ("uv", "--version"),
                "kaggle": ("kaggle", "--version"),
                "nvidia_smi": ("nvidia-smi",),
                "nvidia_pci": ("lspci", "-d", "10de:"),
            }.items()
        },
        "repositories": {
            "pokeforge": git_state(ROOT),
            "pokemon_showdown": git_state(ROOT / "pokemon-showdown"),
        },
    }
    print(json.dumps(snapshot, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
