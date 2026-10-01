# Damage and Simulation Conformance Plan

**Status:** pre-integration audit, 2026-09-30<br>
**Scope:** Gen 9 OU<br>
**Decision:** use `poke-engine` in the live search path behind a small canonical adapter. Use
Pokémon Showdown and `@smogon/calc` only as offline conformance oracles. Do not add a second damage
implementation to the live agent.

This decision is intentionally provisional: the adapter cannot be connected to the live agent until
the differential suite and the gates at the end of this document pass.

**2026-09-30 measured update:** the offline 32-case pilot agrees between Showdown and Smogon on all
controlled rolls, but the locked engine agrees on only 17 regular/critical maximum pairs. Thirteen
cases have modifier-stage/arithmetic discrepancies; two expose incorrect boosted critical offensive
stats (Body Press and Foul Play). See
[`DAMAGE_CONFORMANCE_PILOT.md`](../status/DAMAGE_CONFORMANCE_PILOT.md) for exact artifacts, integrity
checks, adjudications, latency and scope. **Classification is not conformance; live integration is
still gated.** The pinned baseline remains unchanged.

An isolated `critstats-v1` variant now removes the diagnosed critical-stat/Unaware defects in the
tested slice. The expanded 50-case paired run still has 17 arithmetic discrepancies and no full
engine rolls. [`ENGINE_CRITICAL_STATS_VARIANT.md`](../status/ENGINE_CRITICAL_STATS_VARIANT.md)
records the corrected oracle context, single-file patch, wheel/source pins, tests and remaining
gates. It is not the unchanged baseline or a live Safety Shield.

**2026-10-01 complete-turn update:** 19 controlled joint-action probes and 1,216 seeded full
Showdown turns now verify initial projections, normalized native branches and reversible/non-mutating
applications. The pilot exposes unfixed Recover rounding, Rocky Helmet fraction and speed-tie
secondary-effect duplication defects in the isolated variant. See
[`JOINT_TURN_CONFORMANCE_PILOT.md`](../status/JOINT_TURN_CONFORMANCE_PILOT.md).
Finite sampled supports and an intentionally limited final-state projection do not certify exact
transition probabilities or the frozen OU team pool; all live integration gates remain open.

The separately labeled `jointfix-v1` wheel now corrects those diagnosed defects, retains all 50
direct maxima, and passes five additional Showdown weather-recovery controls. See
[`ENGINE_JOINT_FIX_VARIANT.md`](../status/ENGINE_JOINT_FIX_VARIANT.md). Its fixed-point recovery
behavior was independently checked rather than assuming exact mathematical two-thirds. This remains
offline fixture evidence; frozen-team/multi-turn coverage and live gates are still incomplete.

The 2026-10-01 frozen-pool scan now schedules every actual move instance and one switch per lead
in eleven accepted local OU teams (330 jobs/5,280 seeded first-turn observations). Twenty-eight
non-HP support misses identify additional targeted defects after correcting harness status/faint
normalizations. Four multi-turn Showdown oracle histories are saved, but not yet compared to native
parsers/Rust. [`FROZEN_POOL_CONFORMANCE_SCAN.md`](../status/FROZEN_POOL_CONFORMANCE_SCAN.md) records
the complete move coverage matrix, unsupported projections, witnesses and exact limitations.

## Audited artifacts

| Artifact | Exact revision | License | Role |
|---|---|---|---|
| Pokémon Showdown | `a5df8274e85b0889bf2a9b3422a08b39732374fc` | MIT | Authoritative full battle-transition oracle |
| `@smogon/calc` | `660b9b85f39ee59f4768f40a07676e7ad7d5ac0a`, package 0.12.0 | MIT | Independent exact direct-damage oracle |
| `poke-engine` | PyPI 0.0.48 sdist, SHA256 `070010686f2aedff11e25137e696e301ccd80fd57c805d255464067fc905ca12` | MIT | Candidate live damage, transition, and search backend |

The repository pin `f4e224c75bf7af885c85c1dcba982b4143ebf582` is useful provenance, but it
is not interchangeable with FoulPlay's exact PyPI 0.0.48 runtime.

## What each backend actually supplies

### Pokémon Showdown

Showdown is the rules authority. Its internal `getDamage`/`modifyDamage` path evaluates damage in a
live `Battle` with event handlers and the battle PRNG; ordinary damage uses the 85–100 randomizer.
That makes it the right transition oracle, but not a stable low-latency query API for our Python
agent. We will drive controlled, seeded battles in an offline harness rather than call it during
search.

### `@smogon/calc`

The official calculator accepts a generation, fully specified attacker, defender, move, and field.
It returns the exact direct-damage support, range, recoil/recovery information, and KO descriptions.
It is not a turn simulator and does not represent a belief over hidden sets. It is therefore an
excellent independent oracle for isolated damage fixtures, but not a live planner.

### `poke-engine` 0.0.48

The pinned Python binding exposes both:

- `calculate_damage(state, side_one_move, side_two_move, side_one_moves_first)`; and
- `generate_instructions(state, side_one_action, side_two_action)`, which returns weighted outcome
  branches for a joint action.

This is the correct computational boundary for live search. However, the exact 0.0.48
`calculate_damage` result is `[maximum regular damage, maximum critical-hit damage]` for each side,
not the full 16-roll distribution described by newer repository documentation. The adapter is needed
to give PokeForge stable semantics and to prevent maximum damage from being mistaken for expected
damage or a roll distribution.

## Canonical query contract

`DamageQuery` is a versioned, deterministic query for one fully specified hidden world. It contains:

- `schema_version` and the simulator/data `snapshot_hash`;
- `world_id` and `world_weight`;
- generation and format;
- stable team-slot IDs for actor and target;
- both players' semantic actions and actor-first, actor-second, or speed-tie ordering;
- complete actor and target state: species/form, level, current/max HP, types/Tera, status, boosts,
  exact stats or EVs/IVs/nature, ability, item, moves, and volatiles;
- field state: weather, terrain, rooms, screens, hazards, side conditions, counters, and required
  prior-turn state; and
- requested fidelity: direct damage only or complete joint-action transition.

Missing required information is an error. The deterministic backend must never silently fill a
hidden item, ability, spread, move, or Tera type with an average.

`ConditionalDamageResult` contains:

- backend name and exact artifact revision;
- an integer `damage -> probability` support when the backend provides it;
- regular and critical min/max/mean;
- `p_hit` and `p_crit`;
- separate `p_ko_on_hit`, `p_ko_before_residual`, and `p_ko_end_of_turn` values;
- probability-weighted transition branches when requested;
- fidelity flags: `exact`, `approximate`, `unsupported`, or `oracle_disagreement`;
- warnings and measured query latency.

Unavailable quantities are `null`, never zero. This avoids converting “not computed” into “cannot
KO.” Stable semantic identifiers cross the PokeForge boundary; raw backend enum indices do not.

## Hidden-set uncertainty

Damage calculation is conditional on one coherent possible world. Belief inference remains outside
the deterministic adapter:

`P(damage | history, actions) = sum_world P(world | history) P(damage | world, actions)`

Each world must contain a legal, internally consistent set. We do not independently average items,
abilities, EVs, moves, and Tera types because those variables are correlated. The aggregated result
retains both:

- aleatoric uncertainty: accuracy, critical hits, damage rolls, and other in-turn randomness; and
- epistemic uncertainty: which hidden set/world is real.

The consumer must retain explicit zero-damage/immunity mass and lower-tail outcomes. Expected damage
alone is not a decision rule: an Air Balloon world can make Earthquake fail completely even when its
conditional damage is largest in every non-Balloon world. Conformance fixtures therefore include
Great Tusk versus hidden-item Gholdengo and verify that the belief layer can distinguish expected
value, probability of zero progress, lower-tail value, and item-revealing alternatives such as Knock
Off.

World weights, removed worlds, observation likelihoods, and effective sample size must be logged.

## Initial measured evidence

For a fully specified level-100 Modest 252 SpA Light Ball Pikachu using Thunderbolt into level-100
Calm 252 HP / 0 SpD Leftovers Heatran:

- `@smogon/calc` produced
  `[156, 157, 160, 162, 163, 165, 166, 169, 171, 172, 174, 177, 178, 180, 181, 184]` and described a
  guaranteed 3HKO after Leftovers;
- pinned `poke-engine` produced `[184, 276]`, meaning maximum regular and maximum critical damage;
- the regular maximum agreed at 184.

This is a plumbing check, not sufficient evidence of global rules conformance.

An in-process microbenchmark on this machine measured:

| Backend/query | Calls | Total | Mean |
|---|---:|---:|---:|
| `poke-engine.calculate_damage` | 100,000 | 4.888554 s | 48.886 microseconds |
| `@smogon/calc` direct calculation | 100,000 | 5.7455 s | 57.455 microseconds |

These timings exclude state construction, serialization, process startup, and belief batching. They
show that either formula is cheap in-process; they do not justify placing a Node calculator in the
live loop.

## Known fidelity limits to test explicitly

Pinned `poke-engine` is a search engine, not a bit-for-bit Showdown clone. Source inspection found
intentional approximations including:

- using `0.925 * maximum_damage` as ordinary expected damage in common transition paths;
- expanding individual rolls primarily when the roll can cross a KO boundary;
- treating ordinary 2–5-hit moves as three hits and Loaded Dice as four;
- fixed hit-count approximations for Population Bomb and Triple Axel; and
- fixed or averaged handling for some durations and secondary outcomes.

These do not automatically disqualify it for planning, but every approximation affecting a frozen
team pool must be measured and surfaced. Unsupported mechanics require conservative fallbacks and
telemetry, not silent guesses.

## Differential test plan

The suite is layered so state-translation defects are not misdiagnosed as formula defects.

1. **State mapping:** serialize one canonical state into all three backends and compare displayed
   species/form, typing, stats, HP, status, boosts, item, ability, move, Tera, and field conditions.
2. **Direct damage:** compare all 16 controlled Showdown rolls with `@smogon/calc`; compare
   `poke-engine` maximums and any future min/mean/full-roll extension against the same fixture.
3. **Joint transitions:** compare probability-normalized `generate_instructions` branches with
   seeded Showdown outcomes, including order, HP deltas, status, switches, residuals, and faints.
4. **Belief mixtures:** enumerate tiny hand-checkable hidden-world distributions and verify exact
   weighted aggregation without leaking hidden truth.

Fixture families include ordinary STAB/resistance/immunity and low-damage floors; Tera and Stellar;
items, abilities, boosts, burn, weather, terrain, screens, and critical hits; priority, Sucker Punch,
Trick Room, speed ties, and switching; fixed/variable/recoil/drain/protect/substitute/multi-hit moves;
hazards, residual damage, faint/replacement order; and every mechanic used by the frozen evaluation
teams.

Every mismatch is recorded with the query, expected and observed distributions, backend revisions,
seed, and classification: mapping bug, supported-engine bug, intentional approximation, unsupported
mechanic, or oracle ambiguity.

Latency reports use p50/p95/p99/max separately for state conversion and backend execution, plus a
realistic multi-world batch under the agent's decision budget.

## Integration gates

The live agent remains untouched until all of the following are true:

1. Supported direct-damage fixtures agree exactly, or the oracle difference is documented and
   adjudicated.
2. Every full-transition mismatch in the frozen team pool is classified.
3. Unsupported mechanics have conservative fallbacks and observable telemetry.
4. Branch probabilities normalize correctly and null/zero semantics are tested.
5. Hidden worlds are coherent, legal, and correctly weighted.
6. End-to-end p99 latency fits the allocated search budget.
7. Exact revisions, hashes, licenses, and test evidence are saved.

Only after these gates pass may we claim a safety shield or use the adapter inside live search. If
full damage-roll support proves decision-relevant, the preferred next step is a minimal extension of
the pinned Rust binding, tested against both oracles—not a third formula implementation in Python.
