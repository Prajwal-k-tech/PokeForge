"""Action Space and Action Masking for PokeForge.

Defines the 13-action discrete space for Gen 9 Singles:
  - 0..3: Standard Moves (1 to 4)
  - 4..7: Terastallized Moves (1 to 4)
  - 8..12: Switches to Bench Slots (1 to 5)

Provides utilities to generate boolean action masks from Battle objects
and translate between network action indices and poke-env BattleOrders.
"""

from __future__ import annotations

import torch
from typing import List, Optional
from poke_env.battle import AbstractBattle, Move, Pokemon
from poke_env.player import Player, BattleOrder

NUM_ACTIONS = 13


def get_action_mask(battle: AbstractBattle) -> torch.Tensor:
    """Generate a [13] boolean tensor indicating legal actions for the current turn.
    
    Returns:
        torch.Tensor of shape [13] with dtype=torch.bool.
        True = Legal action, False = Illegal action.
    """
    mask = torch.zeros(NUM_ACTIONS, dtype=torch.bool)

    # 1. Check Standard Moves (Indices 0..3)
    available_moves_list = battle.available_moves
    for idx, move in enumerate(available_moves_list):
        if idx < 4:
            mask[idx] = True

    # 2. Check Terastallized Moves (Indices 4..7)
    # Only legal if Terastallize is available this turn
    if getattr(battle, "can_tera", False):
        for idx in range(len(available_moves_list)):
            if idx < 4:
                mask[idx + 4] = True

    # 3. Check Switches to Bench Slots (Indices 8..12)
    # Note: battle.available_switches contains only healthy, unfainted bench Pokémon
    num_available_switches = len(battle.available_switches)
    for idx in range(num_available_switches):
        if idx < 5:
            mask[8 + idx] = True

    # Safety check: In rare trap scenarios with no moves/switches, enable Struggle (Action 0)
    if not mask.any():
        mask[0] = True

    return mask


def action_index_to_order(action_idx: int, battle: AbstractBattle) -> BattleOrder:
    """Translate an integer action index (0..12) into a poke-env BattleOrder.
    
    Args:
        action_idx: Integer from 0 to 12.
        battle: Current Battle state.
        
    Returns:
        BattleOrder ready to send to the Pokémon Showdown engine.
    """
    can_tera = getattr(battle, "can_tera", False)

    # Case 1: Standard Move (0..3)
    if 0 <= action_idx <= 3:
        if action_idx < len(battle.available_moves):
            return Player.create_order(battle.available_moves[action_idx], terastallize=False)
        if battle.available_moves:
            return Player.create_order(battle.available_moves[0], terastallize=False)

    # Case 2: Terastallized Move (4..7)
    elif 4 <= action_idx <= 7:
        move_idx = action_idx - 4
        if move_idx < len(battle.available_moves) and can_tera:
            return Player.create_order(battle.available_moves[move_idx], terastallize=True)
        if battle.available_moves:
            return Player.create_order(battle.available_moves[0], terastallize=False)

    # Case 3: Switch (8..12)
    elif 8 <= action_idx <= 12:
        switch_idx = action_idx - 8
        if switch_idx < len(battle.available_switches):
            return Player.create_order(battle.available_switches[switch_idx])

    # Fallback to first available action
    if battle.available_moves:
        return Player.create_order(battle.available_moves[0])
    if battle.available_switches:
        return Player.create_order(battle.available_switches[0])

    return Player.create_order(None)
