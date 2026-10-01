# Build status

**Last updated:** 1 October 2026<br>
**Target format:** Pokémon Showdown Gen 9 OU<br>
**Project stage:** baseline reproduction and adapter research; PokeForge policy not yet validated

PokeForge is currently strongest as an engineering and evaluation project. The evidence below is local and scoped. It does not show that PokeForge plays competitively.

## Milestones

| Milestone | Status | Evidence |
| --- | --- | --- |
| M0: pin and reproduce public baselines | Complete for the documented local smoke runs | [M0 report](M0_BASELINE_REPRODUCTION.md) |
| M1: paired baseline measurement | Pilot recorded; controlled follow-up remains | [M1 report](M1_BASELINE_BENCHMARK.md) |
| Simulator and framework conformance | Partial, offline fixture coverage | Reports listed below |
| PokeForge competitive policy | Not yet evaluated end to end | No competitive-strength result or public ladder submission |

## Baseline evidence

Pinned FoulPlay and Metamon revisions each completed a legal local Gen 9 OU battle using separate environments and a pinned local Showdown server. This demonstrates that the two reproduction paths can run through a complete local battle.

The selected M1 pilot contains ten games across five team pairings. FoulPlay won nine and Metamon Minikazam won one. The continuation overlapped with a duplicate run on the same host, the sample is small, and controlled random seeds/resource isolation were not established. Treat this as a harness and runtime pilot, not an Elo estimate or agent-strength comparison.

## PokeForge prototype and conformance work

- The original MLP and transformer are educational prototypes trained on a small heuristic-labeled set. Their validation accuracy measures agreement with those labels, not expert decisions.
- Action-format, request-parsing, and selected state-projection checks cover specified fixtures only. They do not establish complete adapter or Showdown protocol conformance.
- A 32-case direct-damage comparison found remaining engine discrepancies. The experimental engine variants are isolated from the reproduced baseline; see [damage conformance](../research/damage_and_simulation_conformance.md) and the [variant reports](.).
- Offline request-gated experiments do not establish live PokéAgent compatibility.

## Reproduction boundaries

- M0 and M1 use a local pinned Showdown build. They are not PokéAgent-server results or public-ladder games.
- The local server, external FoulPlay/Metamon source trees, checkpoints, raw datasets, replay archives, and run artifacts are not included in this repository.
- Some Metamon data and team sources have noncommercial or unresolved redistribution terms. See the [provenance matrix](../research/artifact_license_and_provenance.md).
- This repository has no project-wide reuse license yet. Third-party artifact terms remain separate.
- The recorded test suite covers offline helpers and integration slices; even a passing suite cannot replace full mechanics conformance or playing-strength evaluation.

## Next evidence gates

1. Keep the pinned baseline comparisons reproducible, side-swapped, and isolated; report exclusions and runtime alongside outcomes.
2. Complete exact request/action and observed-state handling for the supported framework paths.
3. Resolve the known damage/transition discrepancies before using the affected simulator path in search.
4. Evaluate an original opponent-conditioned method against strong, fixed baselines using predeclared held-out conditions and enough paired games for uncertainty estimates.
5. Keep PokéAgent and public Showdown results separate, and do not submit or ladder an agent before the rules, action, timer, and data gates are cleared.
