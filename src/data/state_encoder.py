"""State Encoder for PokeForge.

Converts a poke-env Battle object into structured PyTorch tensors:
1. Categorical Tokens (LongTensor): Species, types, and move IDs for nn.Embedding.
2. Numeric Features (FloatTensor): Normalized HP %, stat stages, status flags,
   hazard counts, and damage calculator estimates.
3. Action Mask (BoolTensor): Boolean mask of legal actions for the current turn.
"""

from __future__ import annotations

import torch
from typing import Dict, Tuple
from poke_env.battle import AbstractBattle, Move, Pokemon, Status, Weather, Field
from src.data.vocab import encode_species, encode_move, encode_type
from src.data.action_space import get_action_mask

# Dimensions
NUM_CATEGORICAL = 15  # 1 active sp + 2 types + 4 moves + 1 opp sp + 2 opp types + 5 bench sp
NUM_NUMERIC = 35      # All normalized battle metrics and calculator features


def _encode_status(pokemon: Pokemon | None) -> list[float]:
    """One-hot vector of length 6 for non-volatile status conditions."""
    # [burn, paralysis, poison, toxic, sleep, freeze]
    vec = [0.0] * 6
    if not pokemon or not pokemon.status:
        return vec
    st = pokemon.status
    if st == Status.BRN:
        vec[0] = 1.0
    elif st == Status.PAR:
        vec[1] = 1.0
    elif st == Status.PSN:
        vec[2] = 1.0
    elif st == Status.TOX:
        vec[3] = 1.0
    elif st == Status.SLP:
        vec[4] = 1.0
    elif st == Status.FRZ:
        vec[5] = 1.0
    return vec


def _encode_boosts(pokemon: Pokemon | None) -> list[float]:
    """Normalized stat boost stages (-6 to +6 mapped to -1.0 to +1.0)."""
    # [atk, def, spa, spd, spe]
    if not pokemon:
        return [0.0] * 5
    boosts = pokemon.boosts
    return [
        boosts.get("atk", 0) / 6.0,
        boosts.get("def", 0) / 6.0,
        boosts.get("spa", 0) / 6.0,
        boosts.get("spd", 0) / 6.0,
        boosts.get("spe", 0) / 6.0,
    ]


def encode_battle_state(battle: AbstractBattle) -> Tuple[torch.Tensor, torch.Tensor, torch.Tensor]:
    """Extract tensors from a live Battle state.
    
    Returns:
        categorical_tokens: torch.LongTensor of shape [15]
        numeric_features: torch.FloatTensor of shape [35]
        action_mask: torch.BoolTensor of shape [13]
    """
    active = battle.active_pokemon
    opponent = battle.opponent_active_pokemon

    # -------------------------------------------------------------
    # 1. Categorical Tokens (15 IDs)
    # -------------------------------------------------------------
    cat_ids = []

    # Active Pokémon & Types (3 IDs)
    cat_ids.append(encode_species(active.species if active else None))
    active_types = active.types if active else (None, None)
    cat_ids.append(encode_type(active_types[0].name.lower() if active_types[0] else None))
    cat_ids.append(encode_type(active_types[1].name.lower() if len(active_types) > 1 and active_types[1] else None))

    # Active Moves (4 IDs)
    moves = battle.available_moves if battle.available_moves else []
    for i in range(4):
        if i < len(moves):
            cat_ids.append(encode_move(moves[i].id))
        else:
            cat_ids.append(0)

    # Opponent Active & Types (3 IDs)
    cat_ids.append(encode_species(opponent.species if opponent else None))
    opp_types = opponent.types if opponent else (None, None)
    cat_ids.append(encode_type(opp_types[0].name.lower() if opp_types[0] else None))
    cat_ids.append(encode_type(opp_types[1].name.lower() if len(opp_types) > 1 and opp_types[1] else None))

    # Bench Pokémon (5 IDs)
    switches = battle.available_switches if battle.available_switches else []
    for i in range(5):
        if i < len(switches):
            cat_ids.append(encode_species(switches[i].species))
        else:
            cat_ids.append(0)

    categorical_tokens = torch.tensor(cat_ids, dtype=torch.long)

    # -------------------------------------------------------------
    # 2. Numeric Continuous Features (35 Floats)
    # -------------------------------------------------------------
    num_feats: list[float] = []

    # Active stats (1 + 5 + 6 = 12 floats)
    num_feats.append(active.current_hp_fraction if active else 0.0)
    num_feats.extend(_encode_boosts(active))
    num_feats.extend(_encode_status(active))

    # Opponent stats (1 + 5 + 6 = 12 floats)
    num_feats.append(opponent.current_hp_fraction if opponent else 0.0)
    num_feats.extend(_encode_boosts(opponent))
    num_feats.extend(_encode_status(opponent))

    # Bench HP percentages (5 floats)
    bench_hps = []
    for i in range(5):
        if i < len(switches):
            bench_hps.append(switches[i].current_hp_fraction)
        else:
            bench_hps.append(0.0)
    num_feats.extend(bench_hps)

    # Hazards (2 floats: our rocks, opp rocks)
    my_side = battle.side_conditions
    opp_side = battle.opponent_side_conditions
    num_feats.append(1.0 if "stealthrock" in my_side else 0.0)
    num_feats.append(1.0 if "stealthrock" in opp_side else 0.0)

    # Weather (2 floats: Sun/Rain)
    num_feats.append(1.0 if battle.weather == Weather.SUNNYDAY else 0.0)
    num_feats.append(1.0 if battle.weather == Weather.RAINDANCE else 0.0)

    # Calculator / Tactical estimates (2 floats)
    # Speed advantage
    speed_adv = 0.5
    if active and opponent:
        active_spe_base = (active.stats.get("spe") if active.stats else None) or 100
        opp_spe_base = (opponent.stats.get("spe") if opponent.stats else None) or 100
        my_spe = active_spe_base * (1.0 + active.boosts.get("spe", 0) * 0.5)
        opp_spe = opp_spe_base * (1.0 + opponent.boosts.get("spe", 0) * 0.5)
        speed_adv = 1.0 if my_spe >= opp_spe else 0.0
    num_feats.append(speed_adv)

    # Max damaging move power estimate normalized (0..200 -> 0..1.0)
    max_pow = 0.0
    if moves:
        max_pow = max(m.base_power for m in moves) / 200.0
    num_feats.append(min(max_pow, 1.0))

    numeric_features = torch.tensor(num_feats, dtype=torch.float32)

    # -------------------------------------------------------------
    # 3. Action Mask (13 Booleans)
    # -------------------------------------------------------------
    action_mask = get_action_mask(battle)

    return categorical_tokens, numeric_features, action_mask
