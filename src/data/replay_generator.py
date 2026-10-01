"""Trajectory Collector & Dataset Generator for PokeForge.

Runs simulated battles on the local Showdown server between heuristic players,
extracting exact (state, action_mask, chosen_action) tuples on every turn.
Generates training and validation datasets saved to disk as PyTorch tensors.
"""

from __future__ import annotations

import asyncio
import os
import torch
from typing import List, Tuple
from poke_env import LocalhostServerConfiguration
from poke_env.player import Player, RandomPlayer
from poke_env.battle import AbstractBattle, Move, Pokemon

from src.data.state_encoder import encode_battle_state
from src.data.dataset import PokemonBattleDataset
from src.battle_agent.telemetry_player import estimate_move_damage


class TrajectoryCollectorPlayer(Player):
    """A smart player that logs every state-action pair it executes."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.recorded_states_cat: List[torch.Tensor] = []
        self.recorded_states_num: List[torch.Tensor] = []
        self.recorded_masks: List[torch.Tensor] = []
        self.recorded_actions: List[int] = []

    def choose_move(self, battle: AbstractBattle):
        cat, num, mask = encode_battle_state(battle)

        # Smart choice: evaluate best damaging move
        active = battle.active_pokemon
        opponent = battle.opponent_active_pokemon

        best_move_idx = 0
        best_damage = -1.0

        if battle.available_moves and active and opponent:
            for idx, move in enumerate(battle.available_moves[:4]):
                dmg = estimate_move_damage(move, active, opponent)
                if dmg > best_damage:
                    best_damage = dmg
                    best_move_idx = idx

        # Pick move (index 0..3) or switch if heavily disfavored
        chosen_action = best_move_idx

        # If opponent threatens a strong move and we have good switches, occasionally switch
        if best_damage <= 0.0 and battle.available_switches:
            chosen_action = 8  # Switch to first bench slot

        # Ensure chosen action is legal under mask
        if not mask[chosen_action]:
            # Fallback to first legal action
            for i in range(13):
                if mask[i]:
                    chosen_action = i
                    break

        # Record trajectory
        self.recorded_states_cat.append(cat)
        self.recorded_states_num.append(num)
        self.recorded_masks.append(mask)
        self.recorded_actions.append(chosen_action)

        # Return order
        if chosen_action < 4:
            if chosen_action < len(battle.available_moves):
                return self.create_order(battle.available_moves[chosen_action])
        elif chosen_action >= 8:
            switch_idx = chosen_action - 8
            if switch_idx < len(battle.available_switches):
                return self.create_order(battle.available_switches[switch_idx])

        return self.choose_random_move(battle)


async def generate_dataset(
    num_battles: int = 50,
    output_path: str = "data/train_dataset.pt",
) -> PokemonBattleDataset:
    """Run battles sequentially and extract a PokemonBattleDataset."""
    print(f"Generating dataset by simulating {num_battles} competitive battles on local Showdown...")

    collector = TrajectoryCollectorPlayer(
        server_configuration=LocalhostServerConfiguration,
        battle_format="gen9randombattle",
        max_concurrent_battles=1,
    )
    opponent = RandomPlayer(
        server_configuration=LocalhostServerConfiguration,
        battle_format="gen9randombattle",
        max_concurrent_battles=1,
    )

    for i in range(num_battles):
        await collector.battle_against(opponent, n_battles=1)

    # Convert to tensors
    cats = torch.stack(collector.recorded_states_cat)
    nums = torch.stack(collector.recorded_states_num)
    masks = torch.stack(collector.recorded_masks)
    actions = torch.tensor(collector.recorded_actions, dtype=torch.long)

    dataset = PokemonBattleDataset(cats, nums, masks, actions)
    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    dataset.save(output_path)
    print(f"Generated {len(dataset)} decision turns saved to {output_path}! ✅")
    return dataset


if __name__ == "__main__":
    asyncio.run(generate_dataset(num_battles=20, output_path="data/sample_dataset.pt"))
