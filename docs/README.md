# Project documentation

## Start here

- [Current build status](status/BUILD_STATUS.md): active milestone, verified work, and limits on what may be called complete.
- [Gen 9 OU research plan](research/GEN9OU_RESEARCH_PLAN.md): project hypothesis, baseline-first sequence, and decision gates.
- [Artifact provenance and licensing](research/artifact_license_and_provenance.md): source, model, replay, and team restrictions.

## Reproduction and evaluation

- [M0 baseline reproduction](status/M0_BASELINE_REPRODUCTION.md): pinned FoulPlay and Metamon revisions, local battle evidence, and commands.
- [M1 paired baseline pilot](status/M1_BASELINE_BENCHMARK.md): selected games, exclusions, runtime records, and interpretation limits.
- [Damage and simulation conformance](research/damage_and_simulation_conformance.md): comparison methodology and unresolved mechanics gaps.
- Other files in [`status/`](status/) record the scoped action, state, request, turn, and engine investigations. Each report names its fixture coverage and what it does not prove.

## Interface contract

- [Canonical state/action contract](specifications/canonical_state_action_contract.md): typed boundary between simulator adapters and agent logic.

The full game server, model weights, replay/team archives, and raw local artifacts are not mirrored here. Consult the provenance matrix before obtaining or reusing external artifacts.
