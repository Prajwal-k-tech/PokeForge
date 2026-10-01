# Offline damage conformance pilot

**Verified:** 2026-09-30. **Status:** direct-hit audit complete for 32 fixtures; live integration
and full-transition conformance remain **not passed**.

Follow-up: [`ENGINE_CRITICAL_STATS_VARIANT.md`](ENGINE_CRITICAL_STATS_VARIANT.md) records the
isolated correction, expanded 50-case oracle comparison and remaining rounding errors. The
historical 32-case evidence below is unchanged; it is not full coverage.

## Decision

Keep `poke-engine` as the candidate search/transition backend. It already exposes damage and joint
transition queries; PokeForge needs a small semantic/fidelity adapter, not another damage formula.
However, pinned 0.0.48 cannot currently supply **exact** roll/KO guarantees for a Safety Shield.
Its binding returns regular/critical maxima only, and this pilot finds two supported-mechanic bugs
plus thirteen integer/modifier-stage discrepancies. Do not silently patch the pinned baseline or
integrate a live calculator to hide this result.

Next: evaluate any minimal, explicitly versioned engine correction offline, then expand joint-action
and frozen-team coverage. Classification alone does not make a mismatch safe or pass the gate.

## Artifacts actually checked

| Backend | Revision | License | Integrity boundary |
|---|---|---|---|
| Showdown | `a5df8274e85b0889bf2a9b3422a08b39732374fc` | MIT | HEAD checked; only existing package-lock modification accepted; actual compiled JS hashes recorded |
| Smogon calc 0.12.0 | `660b9b85f39ee59f4768f40a07676e7ad7d5ac0a` | MIT | HEAD and clean tracked worktree checked; compiled JS hashes recorded |
| poke-engine 0.0.48 | locked PyPI sdist + local Gen 9/Tera wheel | MIT | Archive/wheel hashes checked; all 46 audited Rust files match the source archive; installed native binary and Python wrapper match the wheel |

Source archive SHA256:
`070010686f2aedff11e25137e696e301ccd80fd57c805d255464067fc905ca12`.
Wheel SHA256:
`ac0b98444a1eaffc858c0c2d3b9cc0f49e9c4b886d25da6ff63442ef864394e7`.
Native binary SHA256:
`c3f680651c120627239213603d9d877a8457071614cd03d575acd5760524552e`.

The report records per-file hashes of compiled oracles and the audited Rust tree. Compiled-file
hashing identifies the actual files executed; it is not a claim of reproducible compiler output.
The engine repository HEAD is **not** substituted for the locked PyPI runtime.

## Method and results

`tests/fixtures/damage_pilot_v1.json` specifies full sets, including explicit level, nature, EVs,
IVs, item, ability, status, boosts, Tera and field. These are controlled fixtures, **not** inferred
opponent sets. One-Pokémon Custom Game instances exercise Gen 9 mechanics; this does not validate
six-Pokémon OU teams or either live server's rules.

The Node oracle controls only Showdown's integer randomizer stage to enumerate rolls 85–100,
forces regular/critical conditions separately, and retains damage event handlers. Smogon calc
independently computes both supports. Raw stats agree in every fixture. Python checks projected
engine stats/types/HP/status/item/ability/nature/EVs/Tera/boosts before comparing maxima; weight
conversion permits only floating-point representation tolerance.

- Showdown and Smogon agree on **all 1,024 controlled outputs**: 32 cases × 16 rolls × 2 critical conditions.
- Engine regular/critical maximum pairs agree in **17/32** cases.
- **13** mismatch cases are classified as modifier-stage/integer-arithmetic approximations.
- **2** mismatch cases expose incorrect critical offensive-stat handling.
- **0** mismatch cases are unclassified in this fixture set. No claim extends to untested cases.

| Controlled case | Engine maxima: regular / critical | Both oracle maxima | Finding |
|---|---:|---:|---|
| Body Press, user Defense +2 | 1014 / 765 | 1014 / 1520 | Critical path ignores positive Defense boost |
| Body Press, unboosted control | 510 / 765 | 510 / 764 | Only staged arithmetic discrepancy remains |
| Foul Play, target Attack +2 | 97 / 73 | 97 / 145 | Critical path ignores positive target Attack boost |
| Foul Play, target Attack −2 | 25 / 73 | 25 / 73 | Negative-boost bypass control agrees |
| Great Tusk Earthquake → Gholdengo | 291 / 436 | 290 / 434 | Modifier/critical stages differ |
| Knock Off → removable item | 190 / 285 | 188 / 282 | Engine retains float base power after 1.5 multiplier |
| Life Orb Thunderbolt | 489 / 733 | 491 / 736 | Engine boosts base power rather than final damage |

Evidence is in `tests/fixtures/damage_pilot_adjudications_v1.json`, with exact observed/expected
pairs and extracted-sdist source references. Changed pairs do **not** inherit an old adjudication.
Body Press and Foul Play defects are in `src/genx/damage_calc.rs`'s offensive-stat overrides;
Showdown selects the overridden stat before deciding whether a negative boost is ignored on a crit.
Modifier discrepancies follow the engine's aggregated floats/late critical multiplier versus
Showdown's staged integer arithmetic. This is a source-supported diagnosis, not a claim that each
approximation was deliberately designed by its author.

Air Balloon, Levitate, Flying-type and Tera-Flying Ground immunities agree at zero in the tested
cases. Other passing cases include the tested Light Ball, burn, Psyshock, rain, snow, Choice Specs,
Assault Vest, Light Screen and Aurora Veil scenarios. Passing one scenario does not certify all
interactions involving that mechanic.

## Damage probabilities and uncertainty

Oracle supports coalesce duplicate rolls while preserving their frequencies. The report includes
min/max/mean and KO probability **conditional on hit and the selected critical condition**. Overall
hit/crit probability, overall KO-on-hit, pre-residual KO and end-of-turn KO stay `null`: this harness
does not calculate them. Engine full support and mean also stay `null`, never fabricated by scaling
its maximum or confused with an immunity's genuine zero.

An offline illustration mixes the coherent Leftovers and Air Balloon Gholdengo worlds at an
**arbitrary 50/50 weight**, using oracle noncritical direct-hit distributions:

| Move | Mean damage | Zero-damage probability | 10th percentile damage |
|---|---:|---:|---:|
| Earthquake | 134 | 0.5 | 0 |
| Knock Off | 173 | 0 | 160 |

These are not learned priors, not move-policy results, and exclude opponent action, accuracy,
critical chance, item-removal consequences, residuals and longer-term value. They demonstrate why
immunity mass and lower tails must remain visible to belief search. `tests/test_damage_pilot.py`
checks duplicate-roll mass, null/zero-related semantics, mixture normalization and classification
drift; the complete project suite currently has **36 passing tests**.

The physical/special wall lesson is also concrete: the specified mixed Iron Valiant's Close Combat
does 780–918 to the specified 651-HP Blissey, while Moonblast does 70–84. This demonstrates using
move-specific offensive and defensive stats rather than a blanket “special wall” label. It does
not establish that switching in the recorded Amoonguss replay was optimal; that requires the actual
sets, available bench, incoming damage, hazards, tempo and opponent responses.

## Latency: local microbenchmark only

Recorded in the verified report, warm in-process engine damage query timings for 1,600 calls:

| Metric | Microseconds |
|---|---:|
| Mean | 17.27 |
| p50 | 16.64 |
| p95 | 22.92 |
| p99 | 26.88 |
| Maximum | 37.49 |

State mapping (one measurement per fixture, including explicit projection checks): p50 42.51 µs,
p95 66.91 µs, p99/max 143.94 µs. These small measurements exclude process startup, wire parsing,
neural inference, multiple worlds, joint transitions, search, network and deadline overhead.
Node reports time for 32 controlled Showdown calls and two calculator distributions per fixture;
these are different workloads and should not be marketed as a backend speed ranking.

## Reproduce and evidence history

```bash
.venvs/foulplay-rebuild/bin/python scripts/check_damage_conformance.py \
  --calc /tmp/pokeforge-damage-calc-audit \
  --engine-wheel /tmp/pokeforge-uv-cache/sdists-v9/pypi/poke-engine/0.0.48/N5_IsUx1tYDPqS1U/src/target/wheels/poke_engine-0.0.48-cp312-cp312-linux_x86_64.whl \
  --engine-source /tmp/pokeforge-uv-cache/sdists-v9/pypi/poke-engine/0.0.48/N5_IsUx1tYDPqS1U/src/src \
  --engine-sdist .artifacts/conformance/damage/poke_engine-0.0.48.tar.gz \
  --output .artifacts/conformance/damage/NEW_RUN.json

PYTHONPATH=. python -m pytest -q tests
```

Source paths are this machine's cache locations, not a portable install contract. The runner checks
pins and refuses to overwrite an output. Timings vary, so repeated report file hashes will differ.
Deterministic fixtures, projections, supports, maxima and classifications should be identical.
The saved `direct_pilot_v5_repeat.json` rerun was checked: all 32 engine state hashes, conditional
supports, maxima and classifications, both mixtures, source integrity records and compiled-oracle
hashes matched the authoritative run. Timing-dependent report hashes are not expected to match.

Authoritative report: `.artifacts/conformance/damage/direct_pilot_v5_verified.json`, SHA256
`f92db191732a3a61678e967e00bd3b6d349a9f91e5d4007145e0ba9517a526e9`.

Earlier files are retained, not pooled: v1 used incorrect Showdown snow ID (`snow`, not `snowscape`)
and is **quarantined harness evidence**, not engine-failure evidence. V2 corrected field mapping
for 28 cases; v3 added controls; v4 added classification/supports and installed-binary verification;
v5 additionally verified Rust source against the locked archive and the installed wrapper against
the wheel. The initial v4 attempt stopped on float weight representation before writing a report.

## Remaining gates

Full joint transitions, roll support from engine, move accuracy/crit chance, end-of-turn residuals,
multi-hit moves, Stellar, Unaware interactions, low-damage floors, protect/substitute, switches,
hazards, speed ties, priority, rooms, identity-changing mechanics and frozen-team coverage remain
incomplete. Existing engine hit-count/duration/average-damage approximations are still documented
in `docs/research/damage_and_simulation_conformance.md`.

No engine source, checkpoint weights, live policy, public ladder or PokéAgent state was changed.
No training started. This pilot advances the simulator gate; it does not pass it or prove Elo.
