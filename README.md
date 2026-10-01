# PokeForge: Research on Pokémon Battle Agents

PokeForge is an undergraduate project on building and evaluating agents for Pokémon Showdown's Gen 9 OU format. The current work focuses on reproducible baselines, simulator and action conformance, and carefully scoped experiments.

**Status:** pinned FoulPlay and Metamon baselines have each completed a legal local battle. A small paired pilot is recorded below. PokeForge's own agent is not a validated competitive bot, and no ladder submission has been made.

## What the evidence says

| Work | Result | What it establishes |
| --- | --- | --- |
| Baseline reproduction | Pinned FoulPlay and Metamon revisions each completed a legal local Gen 9 OU battle in isolated environments. | The local install, simulator and agent harnesses can complete a game. |
| Paired baseline pilot | Ten selected games across five team pairings: FoulPlay won 9, Metamon Minikazam won 1. | An exploratory result with too few games and uncontrolled host/resource conditions for an Elo or strength claim. |
| Integration checks | Targeted offline fixtures cover action mapping, request parsing, selected state projections, and direct-damage cases. | Specific checked slices only; not full Showdown conformance or an end-to-end competitive agent. |
| Educational neural prototype | Small heuristic-labeled MLP and transformer experiments are retained as v0. | A learning artifact and evaluation case study, not expert play or a validated policy. |

The v0 training tensors and model checkpoints are not distributed. Its historical accuracy and ten-game results therefore cannot be reproduced from this repository; they are not used as evidence for the current research direction.

The exact revisions, commands, caveats, and run records are documented in [`docs/status/`](docs/status/) and [`docs/research/`](docs/research/). Small samples and offline fixtures are labeled at their source so they are not mistaken for competitive results.

## Research direction

The next research question is whether an opponent-conditioned belief model can improve a pinned search baseline under controlled, side-swapped evaluation. The work is gated on simulator compatibility, legal action selection, runtime budgets, and data provenance. The existing v0 safety heuristics are not treated as universally safe. Read the [research plan](docs/research/GEN9OU_RESEARCH_PLAN.md) for the hypothesis and evaluation gates.

No human-replay dataset, third-party model checkpoint, or local Showdown checkout is included in this repository. The artifact and data restrictions are tracked in [`artifact_license_and_provenance.md`](docs/research/artifact_license_and_provenance.md).

## Repository map

- [`src/battle_agent/`](src/battle_agent/) contains the educational v0 neural prototype.
- [`src/integration/`](src/integration/) contains framework-neutral action/state contracts and scoped adapter experiments.
- [`scripts/`](scripts/) contains local reproduction and conformance utilities.
- [`tests/`](tests/) contains offline contract and fixture tests.
- [`config/`](config/) pins baseline revisions, runtime dependencies, and experiment selections.
- [`docs/status/`](docs/status/) records current milestones and evidence boundaries.

## Reproduction notes

The baseline environments and Python runtimes are separate. Start with [`M0_BASELINE_REPRODUCTION.md`](docs/status/M0_BASELINE_REPRODUCTION.md) and its pinned requirements. The local Showdown server, external baseline checkouts, model weights, raw datasets, team exports, and run outputs are not vendored here. The control-pool manifest records team hashes and provenance but does not redistribute the teams. Reproducing the recorded runs requires obtaining the exact inputs at their declared revisions and respecting their licenses.

The recorded offline test command is:

```sh
PYTHONPATH=. python -m pytest -q tests
```

The existing status report records 60 passing tests for the documented integration slices. That does not establish complete simulator compatibility or competitive strength.

## Scope and licensing

This repository does not grant a project-wide reuse license yet. Third-party code, weights, teams, and datasets have separate terms; see [`artifact_license_and_provenance.md`](docs/research/artifact_license_and_provenance.md) and [`patches/README.md`](patches/README.md). In particular, the FoulPlay implementation is GPL-3.0 and is not copied into this repository.

The Pokémon names and game mechanics belong to their respective owners. PokeForge is an independent research and learning project and is not affiliated with or endorsed by Nintendo, Game Freak, The Pokémon Company, Pokémon Showdown, or PokéAgent.
