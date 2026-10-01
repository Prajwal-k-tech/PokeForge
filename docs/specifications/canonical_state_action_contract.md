# Canonical State and Action Contract

**Version:** 1<br>
**Status:** core identifiers and first observed-state adapter slice implemented; full conformance incomplete<br>
**Code:** `src/integration/contracts.py`

## Purpose

FoulPlay, Metamon, poke-env, and the educational PokeForge prototype use different state objects and
different integer action layouts. No framework-specific integer or mutable battle object may cross
the competitive-agent boundary. Every adapter must independently produce the same immutable
`BattleSnapshot` and semantic `ActionKey` values from the same player-visible Showdown history and
request.

This contract does not combine the frameworks. It creates the comparison boundary required before a
hybrid is allowed.

## Identity and hashing

- `request_hash` is SHA-256 of the exact UTF-8 Showdown request payload as received. It is never the
  hash of a parsed and re-serialized object.
- `history_hash` is SHA-256 over every player-visible protocol line in order, with an eight-byte
  length prefix before each line. Private truth from the server or opponent is forbidden.
- `snapshot_hash` covers every field of the canonical snapshot, including adapter version, request
  and history hashes, stable teams, legal actions, phase, and canonical public-state JSON.
- `semantic_hash` excludes adapter provenance and sorts team records by stable slot and legal
  actions as a set. Independent adapter versions should agree on this hash, not on the
  provenance-bearing `snapshot_hash`.
- Cached logits, worlds, search results, or fallbacks must match the current `request_hash`. A turn
  number or battle tag alone is not a cache key.

The public-state payload uses UTF-8 JSON with sorted keys, no insignificant whitespace, and no NaN or
Infinity. Adapters must canonicalize it before constructing a snapshot.

## Stable team and move slots

`TeamSlot(slot, species_id)` refers to the full Team Preview order, with slots `0..5`. The slot does
not change when a Pokémon faints, becomes unavailable, or is filtered out of
`available_switches`. Opponent slots are fixed from Team Preview in the order observed by that
player.

A move action carries both:

- `move_slot` in the active Pokémon's stable full moveset order, `0..3`; and
- normalized Showdown `move_id`.

The ID prevents two adapters from appearing to agree when one has shifted a disabled move out of its
list. A move is legal only when both slot and identity match the current request.

## Semantic actions

| Kind | Required fields | Meaning |
|---|---|---|
| `move` | stable `move_slot`, `move_id`, `tera` | ordinary or Terastallized move |
| `switch` | stable full-team `team_slot` | voluntary or forced replacement |
| `team_preview` | permutation of slots `0..5` | ordered Gen 9 OU lead/team submission |
| `struggle` | none | explicit engine-required Struggle action |
| `pass` | none | only when the exact Showdown request explicitly permits pass |

There is no universal 13-action integer layout in this contract. A normal fully available turn can
contain four moves, four Tera variants, and five switches, but adapters map those semantic keys to
their own local indices independently. Missing, disabled, trapped, fainted, or otherwise illegal
choices are absent; they are never compacted into different stable slots.

## Phases

| Phase | Permitted legal action kinds |
|---|---|
| `team_preview` | `team_preview` |
| `turn` | `move`, `switch`, `struggle` |
| `forced_switch` | `switch` |
| `wait` | none |
| `finished` | none |

The current v1 core reserves `pass`, but does not admit it into a phase until a real Gen 9 OU request
fixture demonstrates the protocol condition. This prevents a speculative emergency action from
becoming silently legal.

## Public-state payload schema

Adapter version 1 must emit the following top-level JSON sections. This payload is intentionally
semantic and player-relative; backend enum values and object addresses are forbidden.

```text
format
rules
self
  active_slot
  team[slot]
opponent
  active_slot
  team[slot]
field
  weather, terrain, rooms, pseudo-weather
  self side conditions, opponent side conditions
history_summary
  revealed moves/items/abilities/Tera
  speed-order and damage observations
request
  rqid, wait, teamPreview, forceSwitch, trapped, maybeTrapped
```

Each Pokémon record must distinguish unknown from known-empty. Required fields are stable slot,
species/form, level when known, displayed HP interval, fainted/active flags, status, boosts,
volatiles, types, Tera state, revealed moves in stable slots, item state, and ability state. Our own
private team information may be exact; opponent fields may contain only legally observed information.

An unavailable quantity is `null`, not zero, empty string, or a guessed population value. Belief
worlds and imputed opponent sets live outside this snapshot and reference its hash.

## Adapter conformance

Given the same exact player-visible transcript and request, independent adapters pass only if they
agree on:

1. phase, perspective, turn, `rqid`, and both active stable slots;
2. all six preview species and stable slots on both sides;
3. the set of legal `ActionKey` values;
4. the defined public-state projection; and
5. request, history, and semantic hashes. Each adapter separately records its provenance-bearing
   snapshot hash; different adapter versions need not have identical snapshot hashes.

Golden fixtures must cover:

- all 13 normal semantic choices;
- disabled moves without slot shifting;
- trapped turns without switch renumbering;
- fainted and unavailable bench slots;
- ordinary and Tera versions of the same move;
- forced replacement;
- Team Preview;
- Struggle;
- wait and finished requests; and
- stale-request rejection by hash.

An adapter disagreement is an integration failure. It must not be resolved by selecting whichever
framework produced the preferred action.

## Current implementation boundary

The core immutable types, validation, exact hashing, canonical JSON, phase compatibility, all 13
normal action identities, stable filtered switches, Team Preview, Struggle, and wait states have
stdlib unit coverage in `tests/test_integration_contracts.py`.

The first public-state payload and native framework projections now live in
`src/integration/framework_state.py`. One exact player transcript produces 25 equal semantic
snapshots across both pinned native parsers, with documented supplements for information those
parsers lose. See [`STATE_ADAPTER_PILOT.md`](../status/STATE_ADAPTER_PILOT.md). This is not a
completed all-mechanics adapter: shared provenance/identity helpers are not independent parsers,
unknown counters stay null, unsupported cases are rejected, and live attachment has not occurred.

Still required before Gate 0B passes:

- completion of the versioned public-state payload's counter/history and special-mechanic coverage;
- a complete raw Showdown golden-fixture suite;
- independent FoulPlay and Metamon adapters;
- same-request differential tests; and
- an explicit project release-license decision.

### First protocol capture (not Gate 0B completion)

The pinned local FoulPlay client captured 27 **parsed and re-serialized request objects** from one local battle on
2026-09-30 at `.artifacts/golden_requests/foulplay_vs_random_raw.json` (SHA256
`086226d06a124caafc970f7dbaa513261327d0b00333dde7de42a569ca8cdd19`). The test fixture
`tests/fixtures/foulplay_local_normal_request.json` is a deliberately reduced projection of its
first normal request (SHA256 `0a0caa1a68cc01502d9f8ef5bc1b236bee7b3b48595a6c6b578cb239d3ac880c`).
The older capture preserves semantic data, not exact received payload bytes, so it cannot establish
the exact-request hash contract.

It matters because Pelipper was initial team slot 1 but request-list position 0 after leading. The
test therefore supplies request-order map `(1, 0, 2, 3, 4, 5)` and proves that legal switches remain
stable slots `0, 2, 3, 4, 5`; positional indexing would silently switch the wrong Pokémon. This is
one real protocol fixture for the shared request-to-action reference translator, not evidence that
either framework adapter is complete or that the two frameworks agree.

### Implemented framework action translations

`src/integration/framework_actions.py` now translates the two pinned framework encodings through
that shared request and stable-slot map:

- FoulPlay's named `/choose move <id> [terastallize]` and one-based `/switch N` wire commands;
- Metamon `DefaultActionSpace` indices: alphabetic moves `0..3`, alphabetic switches `4..8`, and
  alphabetic Tera moves `9..12` (ordinary indices `0..3` alias Struggle while switches remain usable).

`tests/test_framework_actions.py` proves the Metamon indices cover all 13 semantic actions and checks
FoulPlay move/switch commands, malformed and stale commands, disabled/exhausted moves, and forced
replacement. The offline differential below exercises **all** FoulPlay formatter choices. It does not yet
construct a complete canonical `BattleSnapshot`, public-state payload, or a live hybrid agent.

### Actual upstream differential and exact protocol capture

`scripts/reproduce_foulplay_baseline.py --capture-protocol` now preserves exact received battle
messages and request strings, excluding login messages and request-like text inside chat. It refuses
to overwrite an existing capture. The verified capture from local `battle-gen9ou-227` contains
75 messages and 24 requests (preview, ordinary choices, waiting, and forced replacement):

- `.artifacts/golden_requests/foulplay_protocol_v1.jsonl`, SHA256
  `f545c81a5c09a8b364f708d56b6cc79def61d56574f8a8ea5dd069f200240dc2`.
- Both message and exact-payload hashes were recomputed successfully.

`scripts/check_framework_actions.py` imports each pinned framework's actual parser/formatter.
Eight projected/synthetic scenarios and all 18 actionable captured requests pass for both frameworks:
normal, disabled/exhausted moves, trapped, fainted bench, forced replacement, unavailable Tera, and
Struggle. Stable own slots in the captured tests are recovered from the first preview's unique
own `ident` values; no hard-coded active/request order is used for those requests.

```bash
.venvs/foulplay-rebuild/bin/python scripts/check_framework_actions.py \
  --framework foulplay --source /tmp/pokeforge-audit.SrV7C4/foul-play \
  --capture .artifacts/golden_requests/foulplay_protocol_v1.jsonl \
  --output .artifacts/conformance/actions/foulplay_v3_capture.json
.venvs/metamon-rebuild/bin/python scripts/check_framework_actions.py \
  --framework metamon --source /tmp/pokeforge-audit.SrV7C4/metamon \
  --capture .artifacts/golden_requests/foulplay_protocol_v1.jsonl \
  --output .artifacts/conformance/actions/metamon_v3_sampling.json
```

Reports: FoulPlay SHA256 `d71bc4b8ec22dfa4e8e971e3e7d3aa1249d75067da98c3244936e2e38c3331d7`;
Metamon SHA256 `ac5babfa696c61df4bad513e941a4e651b0166419435b05a67c24ea92be55be4`.
FoulPlay's projected fixture uses placeholder stats only for formatter initialization; no search or
damage claim follows. Metamon is checked against real `BattleOrder` objects, not a second copy of our
integer mapper. Its unavailable-Tera indices silently downgrade upstream; PokeForge intentionally
rejects those aliases rather than interpreting them as ordinary move intent.

The observed-state pilot additionally checks preview/wait/forced/finished snapshots and current
state on one complete transcript. Still unverified: full public state/history reconstruction,
Team Preview framework action translation,
Recharge, revival, Transform and mutable movesets, Illusion/identity changes, and every Gen 9 mechanic.
Current move slots are request-bound; full historical moveset tracking is not complete. **Gate 0B
remains open.**

The Metamon report also contains a separate CPU distribution probe: upstream's probability floor
restores positive mass after masked logits are softmaxed. With three legal switches out of 13
indices, masked-out choices receive total probability about `0.00990099`. Action translation
correctness therefore does not establish sampling safety; the future policy boundary must reapply
legality after probability clipping and before sampling, and reject stale request hashes.
