# Observed-state adapter pilot

**Verified:** 2026-09-30. **Status:** one complete transcript passes the checked snapshot slice.
**Gate 0B remains open.** This is not all-mechanics, simulator, policy or strength conformance.

## Implemented boundary

`src/integration/framework_state.py` projects native FoulPlay and Metamon/poke-env battle objects
into the existing immutable `BattleSnapshot`. `TranscriptContext` retains exact player-visible
lines, request bytes, preview identities and observation provenance that either native object
otherwise loses. It contains no species stat calculator, opponent team truth or hidden-set sampler.

The native parsers are independent. The identity/evidence ledger, legal-action reference and
snapshot schema are shared, so this is **not two independently implemented protocol parsers**.
The comparison exercises independently parsed current state, with explicit supplements for facts
lost by a native parser. It does not independently re-prove the shared components' correctness.

The payload covers versioned format/rules; both six-slot teams and active identities; species,
level, types/Tera, exact own stats/HP, displayed opponent HP intervals, status, boosts, proven
volatiles, known moves/items/abilities; weather/terrain/rooms/pseudo-weather and observed side
conditions; move/damage/reveal history; and current request flags. Private EVs/IVs/nature, counters
and timers not established by these inputs stay `null`.

Key invariants:

- Exact request bytes and every visible line participate in the appropriate hashes. A native
  parser holding a different parsed request is rejected, not silently paired with fresh metadata.
- Own slots remain fixed across request reorderings. Opponent species must resolve unambiguously
  to a preview slot; this slice rejects form/Illusion identity changes rather than guessing.
- FoulPlay's inferred opponent spreads/stats and unproven items/abilities/effects are excluded.
  A native value contradicting a proven item/status/stat/HP observation is an error.
- Unknown items differ from known-empty items. Opponent move slots and PP remain unknown;
  observed moves are not assigned fictitious moveset positions.
- Native side-condition durations are not copied as if they were known timers. Metamon's
  nonstacking values are activation turns, whereas FoulPlay's may be remaining-duration guesses.
- Bench opponent HP observations remain in history, but their **current** HP interval is unknown
  after leaving the field. Silent Regenerator healing must not become exact observed HP.
- Finished snapshots retain the last exact request hash, have no legal actions, and use final
  visible HP changes. They do not reset to the last decision request's pre-action health or PP.

## Verified transcript result

Input: `.artifacts/golden_requests/foulplay_protocol_v1.jsonl`, SHA256
`f545c81a5c09a8b364f708d56b6cc79def61d56574f8a8ea5dd069f200240dc2`.

Both native parser/projection paths agree on **all 25 semantic snapshots**:

| Phase | Checkpoints |
|---|---:|
| Team Preview | 1 |
| Ordinary turn | 17 |
| Waiting | 5 |
| Forced replacement | 1 |
| Finished | 1 |

Request/history hashes, stable identities, legal action sets, active slots, defined public payload
and semantic hashes match. Provenance-bearing snapshot hashes differ by adapter version, as intended.
The comparison reconstructs the saved snapshots and recomputes their hashes; it does not trust
saved `semantic_hash` labels. Message/request hashes and request-index entries are also checked
against the exact protocol strings.

No policy/checkpoint inference or local server was needed. FoulPlay used its actual
`StandardBattleMode` with **empty inference datasets**: this is a public parser audit, not a repeat
of the baseline's belief/search computation. The Metamon side exercises its pinned poke-env
parser; it does not test a neural encoder consuming the new snapshot.

## Normalizations supported by evidence

1. **HP Percentage Mod:** Showdown uses ceiling percentages but maps an injured value that would
   display 100% to 99%. Thus 99/100 means `(0.98, 1.0)`, not `(0.98, 0.99]`; 100/100 means full HP.
   Pinned source: `pokemon-showdown/sim/pokemon.ts:getHealth`.
2. **Fainted own max HP:** FoulPlay's decision-time request update parses `0 fnt` with max HP zero.
   Zero is not the true maximum. The snapshot retains the last private maximum and avoids division
   by zero; it does not alter the native tracker or pinned source.
3. **Private Tera type:** pinned poke-env does not retain request `teraType` here. The adapter supplies
   it from the exact own request and records an `adapter_notes` entry. It never supplies an
   unrevealed opponent Tera type.
4. **Weather ability reveal:** the pinned poke-env parser misses the observed opponent Drizzle in
   this trace. A native unknown can be supplemented from the visible reveal ledger, with a note;
   a contradictory known ability is rejected.
5. **Transient expiry:** at the forced replacement after turn 14's upkeep, poke-env still exposes
   Roost until the next `turn` event; FoulPlay already removed it on upkeep. The adapter uses the
   observed `-singleturn`/`upkeep` lifecycle, records normalization, and leaves both native objects
   unchanged. It does not drop arbitrary mismatching persistent effects.
6. **Terminal freshness:** our Iron Valiant has 175/289 in the final request, then 67/289 at the
   win event. Both completed snapshots contain 67, not the stale request value 175.

The Metamon report has 150 private-Tera supplements (six members × 25 checkpoints), seven missing
observed-ability supplements, and one transient-expiry normalization. These counts are annotations,
not independent games or policy errors. Other unit checks protect Water Absorb ownership in heal
messages and prevent a consumed berry's later heal message from resurrecting a held item.

## Pins, hashes and reproduction

- FoulPlay source: `6c467c081e862fb321adb405355beb41aba8e226`, GPL-3.0.
- Metamon source: `0a00a759c9a4382a2877088d828302ec294a05a5`, MIT.
- Actual Metamon poke-env: version 0.8.3.3, Git commit
  `e1268d270c3f2bd32c7ff5713e01062302020579`, MIT; install-origin metadata is checked.
- Source checkouts must be clean. Reports record actual runtime Python/static JSON file hashes
  (58 FoulPlay files and 69 poke-env files), plus adapter/runner hashes.

```bash
.venvs/foulplay-rebuild/bin/python scripts/check_framework_states.py \
  --framework foulplay --source /tmp/pokeforge-audit.SrV7C4/foul-play \
  --capture .artifacts/golden_requests/foulplay_protocol_v1.jsonl \
  --output .artifacts/conformance/states/NEW_FOULPLAY.json

.venvs/metamon-rebuild/bin/python scripts/check_framework_states.py \
  --framework metamon --source /tmp/pokeforge-audit.SrV7C4/metamon \
  --capture .artifacts/golden_requests/foulplay_protocol_v1.jsonl \
  --compare .artifacts/conformance/states/NEW_FOULPLAY.json \
  --output .artifacts/conformance/states/NEW_METAMON.json

PYTHONPATH=. python -m pytest -q tests
```

Output paths must be new; this machine's cached source paths are not a portable installation recipe.

Authoritative reports:

- `foulplay_v9_observed.json`: SHA256
  `297b5f7e7036c9ba67190339067c27da58d9e604d2f026da192ef84652aaee82`.
- `metamon_v9_observed.json`: SHA256
  `e56a8b8b1d0876dffa4d3f57e62b3b9bb153d5290c4b1ba04f0769c6c62e6751`.

Earlier v1–v8 reports are development evidence and are not pooled as additional tests/games.
The v9 checked reports cover the current observation-preserving implementation. Eight portable
unit tests were added; the complete project suite has **44 passing tests**.
Both v9 runs were repeated to new output paths; each framework's repeated report has exactly the
same SHA256 as its authoritative report. This establishes determinism for this transcript/run scope.

## Remaining before production/hybrid integration

- More native-parser transcripts, including the other player perspective, nicknames, disabled/
  mutable movesets, Struggle, status/boost/persistent-volatile families and every frozen team's mechanics.
- Correct handling for identity/form changes and called/reflected moves. Current unsupported-event
  flags reject Transform/Illusion, ability/type transfers, revival, Recharge, delayed-move counters,
  selected field changes, volatile transfers, prepare/singlemove and activate paths.
- Counters, delayed effects, exact known durations versus uncertain durations, linked critical
  damage/speed observations, own move-history/PP intervals and a versioned complete coverage matrix.
- Live single-stream attachment, adapter-failure telemetry and explicit conservative fallback.
- Format profiles, project release-license decision, independent broader integration/latency tests,
  simulator corrections and transition conformance. No benchmark-server conformance is claimed.

The new adapters are **not connected to the live agent**. Existing pinned source, weights, baseline
behaviour, educational v0 and public/leaderboard state were not changed. No training started.
