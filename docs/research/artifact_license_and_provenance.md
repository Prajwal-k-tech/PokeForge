# PokeForge Artifact License and Provenance Matrix

**Audit date:** 2026-09-30<br>
**Status:** Preliminary gate; verify again before copying code, training derived weights, or publishing

This is an engineering provenance record, not legal advice. A repository-level license does not
automatically cover checkpoints, replay datasets, team archives, or derived weights.

| Artifact | Audited revision/source | Declared license | Planned use | Required action |
|---|---|---|---|---|
| PokeForge current code | local workspace | No root license found | original teaching and integration code | Choose a license before public release; do not imply third-party code is original |
| FoulPlay code | `6c467c081e862fb321adb405355beb41aba8e226` | GPL-3.0 | public search baseline; possible modification | Preserve notices; do not copy/link into a differently licensed distributed derivative without a GPL-compatible release decision |
| FoulPlay inference data | Smogon August 2026 usage plus three sets/replay files, exact hashes in `config/artifacts.lock.toml` | No artifact-specific license found | hidden-set proposal distribution | Keep local during research; resolve redistribution terms before packaging or publishing the cache |
| poke-engine code | `f4e224c75bf7af885c85c1dcba982b4143ebf582` | MIT | simulator/search backend | Preserve copyright and license notice |
| Smogon damage calculator | `660b9b85f39ee59f4768f40a07676e7ad7d5ac0a`, `@smogon/calc` 0.12.0 | MIT | offline formula/conformance oracle | Preserve copyright and license notice; do not treat it as the authoritative full-turn simulator |
| Metamon code | `0a00a759c9a4382a2877088d828302ec294a05a5` | MIT | neural baselines, evaluation, adapters | Preserve copyright and license notice |
| Metamon checkpoints | `jakegrigsby/metamon`, HF revision `ac8e88e7da8dc2a2b85176d88f81fd8854b1445b` | Apache-2.0 | inference baseline; possible adapters/distillation | Preserve notices; record exact checkpoint hash; review derived-model obligations |
| Metamon raw replays | `jakegrigsby/metamon-raw-replays`, v6 / 2.68M rows | No license declared in HF card at audit | longitudinal/data audit | Do not assume reuse rights; resolve terms before training or redistributing derived artifacts |
| Metamon parsed replays | `jakegrigsby/metamon-parsed-replays` | CC-BY-NC-4.0 | offline action/belief experiments | Attribute; mark noncommercial constraint; review whether derived weights can be distributed for intended use |
| Metamon parsed self-play pile | `jakegrigsby/metamon-parsed-pile` | No license declared in HF card at audit | possible adapter/student training | Resolve terms before use; stream shards rather than assume full download |
| Metamon teams | `jakegrigsby/metamon-teams` | No license declared in HF card at audit | controlled team pools | Resolve source/redistribution terms; retain team provenance |
| Pokémon Showdown | local checkout | MIT | authoritative local simulator/server | Preserve copyright and license notice; pin commit for experiments |
| PokéAgent server replays | public replay archive | No bulk dataset license found | verification and analysis | Save our own battle logs; do not scrape/redistribute at scale without checking organizer terms |

## Release boundary decision

Before hybrid implementation, choose one:

1. **GPL-compatible integrated project:** simplest if modifying or incorporating FoulPlay code.
2. **Original orchestration with unmodified external executables/services:** keep clear source boundaries,
   but do not assume process separation alone resolves derivative-work questions.
3. **Clean-room reimplementation of ideas:** use papers/public behavior as specification, avoid copying
   GPL implementation, and document independent authorship.

Whichever route is chosen, publish:

- `THIRD_PARTY_NOTICES`;
- exact Git/model/data revisions and hashes;
- training-data licenses and intended-use restrictions;
- which weights were reused, fine-tuned, or distilled;
- which benchmark code was modified;
- a reproducible environment manifest.

## Data governance rules

- Identity-blind evaluation is primary.
- Raw usernames are never stored in PokeForge research artifacts.
- Stable pseudonyms may be used only for approved longitudinal experiments.
- Public human profiles are session-local or opt-in.
- Noncommercial and no-license-declared data are never silently mixed into a supposedly unrestricted
  commercial artifact.

## Primary records

- [FoulPlay repository and GPL-3.0 license](https://github.com/pmariglia/foul-play)
- [poke-engine repository and MIT license](https://github.com/pmariglia/poke-engine)
- [Metamon code and MIT license](https://github.com/UT-Austin-RPL/metamon)
- [Metamon checkpoint repository and Apache-2.0 card](https://huggingface.co/jakegrigsby/metamon)
- [Metamon raw replay dataset card](https://huggingface.co/datasets/jakegrigsby/metamon-raw-replays)
- [Metamon parsed replay dataset card](https://huggingface.co/datasets/jakegrigsby/metamon-parsed-replays)
- [Metamon parsed self-play dataset card](https://huggingface.co/datasets/jakegrigsby/metamon-parsed-pile)
- [Metamon team dataset card](https://huggingface.co/datasets/jakegrigsby/metamon-teams)
- [Pokémon Showdown repository and MIT license](https://github.com/smogon/pokemon-showdown)
