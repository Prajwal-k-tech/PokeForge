# Research plan: opponent adaptation in Gen 9 OU

**Status:** hypothesis and evaluation plan; the proposed PokeForge method has not yet been validated.<br>
**Benchmark:** Gen 9 OU, with each rules profile and timer reported separately.

## Question

Can a confidence-gated model of an opponent's hidden team and action tendencies improve decisions when added to a strong search or sequence-policy baseline, without increasing invalid actions or deadline failures?

This is narrower than training a new competitive policy from scratch. The project first reproduces existing public agents, then tests whether calibrated opponent adaptation adds measurable value under controlled conditions.

## Starting point

The repository contains an educational MLP/transformer prototype and local reproductions of pinned FoulPlay and Metamon baselines. The ten-game pilot favors FoulPlay 9–1, but its size and run conditions do not support a ranking. These systems are controls for future experiments, not evidence that PokeForge is competitive.

The hidden state includes the opponent's unrevealed Pokémon, moves, items, abilities, and choices. Candidate sets must obey the target format's legality rules. Public Gen 9 OU and PokéAgent rules may differ; observations and results from those profiles must not be combined without an explicit compatibility mapping.

## Falsifiable hypothesis

For a fixed baseline, adding opponent-conditioned beliefs improves paired decision quality or win rate over both:

1. the unchanged baseline; and
2. a history-aware population model that uses the same public evidence but no opponent-specific adaptation.

The method fails this hypothesis if its apparent gain disappears on chronological or unseen-opponent holdouts, depends on player identity shortcuts, or materially increases invalid actions, timeouts, or worst-case latency.

## Evaluation sequence

### 1. Establish the execution boundary

- Pin the simulator, baseline revisions, checkpoints, rules, team pool, runtime, and decision budget.
- Match requests and legal actions exactly; keep a raw intended action separate from any fallback chosen by the framework.
- Check state projections against observed battle requests. Keep private simulator truth in the test oracle, never in policy input.
- Resolve simulator mismatches for mechanics exercised by the evaluation teams.

### 2. Test the opponent model offline

- Predict only information that can be inferred from public history.
- Report calibration and log loss as well as accuracy.
- Use chronological, leave-opponent-out, and leave-team-archetype-out splits.
- Include opponents that change behavior and tests with shuffled identities.
- Compare against population priors and a history-aware non-personalized baseline.

### 3. Test policy integration

- Freeze the baseline, simulator, team pairings, and time budget before the comparison.
- Use side-swapped paired games across multiple teams and opponents.
- Report uncertainty intervals, invalid intent, fallback rate, timeout rate, cold/warm latency, and the full selection/exclusion record.
- Keep exploratory runs separate from confirmatory evaluation; do not tune on held-out opponents or teams.

## Reporting rules

- A completed battle proves execution, not competitive strength.
- Small pilots are labeled exploratory; never convert their win fraction into an Elo claim.
- Report revisions, hashes, format, timer, teams, seeds where available, sample size, uncertainty, and excluded runs.
- Public Showdown ladder use is a separate operational decision. Follow platform rules and rate limits; a local result is not a ladder result.
- Do not collect or redistribute replays, teams, checkpoints, or derived weights until artifact-level terms and provenance are resolved.

## Current blockers

- Full end-to-end PokeForge search integration does not exist.
- Framework and simulator coverage is partial; known mechanics gaps remain.
- The M1 pilot is too small and not fully isolated for a strength conclusion.
- Data, team-pool, and checkpoint licenses are mixed; the root project license is undecided.

See [build status](../status/BUILD_STATUS.md), [baseline evidence](../status/M0_BASELINE_REPRODUCTION.md), [paired pilot](../status/M1_BASELINE_BENCHMARK.md), and [artifact provenance](artifact_license_and_provenance.md).
