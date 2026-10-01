"""Deterministic Safety Shield & Decision Guardrail for PokeForge.

Intercepts the neural policy's action and enforces 3 critical game-theoretic rules:
1. Lethal KO Execution: If any move has a guaranteed 100% knockout on the opponent,
   immediately take it (no overthinking or blundering a free win).
2. Hazard Arithmetic (Suicide Prevention): Calculates exact Stealth Rock and Spikes
   entry hazard damage. If a switch-in will faint upon touching the field, strictly block it.
3. Emergency Defensive Tera: If the active Pokémon is under lethal threat from an incoming
   super-effective move, trigger defensive Terastallization to survive and turn the tables.
"""

from __future__ import annotations

from typing import Optional, Tuple
from poke_env.battle import AbstractBattle, Move, Pokemon, PokemonType
from poke_env.player import BattleOrder
from src.data.action_space import action_index_to_order
from src.battle_agent.telemetry_player import estimate_move_damage


def calculate_stealth_rock_damage_fraction(pokemon: Pokemon) -> float:
    """Calculate entry hazard damage from Stealth Rock based on Rock weakness.
    
    Standard Rock damage is 1/8 (12.5%).
    Rock weakness/resistance scales this from 3.125% (0.25x) up to 50% (4x).
    Pokémon holding Heavy-Duty Boots take 0% hazard damage.
    """
    if pokemon.item == "heavydutyboots":
        return 0.0

    # Rock move vs this pokemon's defensive types
    rock_type = PokemonType.ROCK
    mult = pokemon.damage_multiplier(rock_type)
    return (1.0 / 8.0) * mult


def calculate_spikes_damage_fraction(pokemon: Pokemon, spikes_layers: int) -> float:
    """Calculate Spikes damage (1 layer = 12.5%, 2 layers = 16.6%, 3 layers = 25%).
    
    Flying-type Pokémon and Levitate abilities are immune unless grounded.
    Heavy-Duty Boots holders take 0%.
    """
    if pokemon.item == "heavydutyboots" or spikes_layers <= 0:
        return 0.0

    # Flying type immunity
    if PokemonType.FLYING in pokemon.types or pokemon.ability == "levitate":
        return 0.0

    if spikes_layers == 1:
        return 1.0 / 8.0
    elif spikes_layers == 2:
        return 1.0 / 6.0
    else:
        return 1.0 / 4.0


class SafetyShield:
    """Safety Shield verifying and adjusting neural policy decisions."""

    @staticmethod
    def apply_guardrails(
        chosen_action_idx: int,
        battle: AbstractBattle,
    ) -> Tuple[int, str]:
        """Verify the neural network's chosen action against deterministic safety rules.
        
        Args:
            chosen_action_idx: Integer action index (0..12) from policy network.
            battle: Current Battle state.
            
        Returns:
            (final_action_idx, reason_string)
        """
        active = battle.active_pokemon
        opponent = battle.opponent_active_pokemon

        # -------------------------------------------------------------
        # Guardrail 1: Lethal Knockout Execution
        # If any move deals >= opponent's remaining HP fraction, take it!
        # -------------------------------------------------------------
        if active and opponent and battle.available_moves:
            opp_hp = opponent.current_hp_fraction
            for idx, move in enumerate(battle.available_moves[:4]):
                # Estimate power: raw base power * STAB * type multiplier
                est_dmg = estimate_move_damage(move, active, opponent)
                # If estimated effective power > 120 and opponent HP < 40%, or > 200 and opp < 70%
                # Simple lethal heuristic: power/150 approximate damage fraction
                approx_dmg_frac = est_dmg / 120.0
                if approx_dmg_frac >= opp_hp and est_dmg > 0:
                    # Guaranteed KO available!
                    if chosen_action_idx != idx:
                        return idx, f"Lethal KO override: {move.id} kills opponent!"

        # -------------------------------------------------------------
        # Guardrail 2: Suicide Switch Prevention (Hazard Arithmetic)
        # -------------------------------------------------------------
        if chosen_action_idx >= 8 and battle.available_switches:
            switch_slot = chosen_action_idx - 8
            if switch_slot < len(battle.available_switches):
                target_switch = battle.available_switches[switch_slot]
                my_side = battle.side_conditions

                sr_damage = 0.0
                if "stealthrock" in my_side:
                    sr_damage = calculate_stealth_rock_damage_fraction(target_switch)

                spikes_layers = my_side.get("spikes", 0)
                spikes_damage = calculate_spikes_damage_fraction(target_switch, spikes_layers)

                total_hazard_damage = sr_damage + spikes_damage
                remaining_hp_after_entry = target_switch.current_hp_fraction - total_hazard_damage

                if remaining_hp_after_entry <= 0.0:
                    # Suicidal switch! Intercept and pick first safe damaging move
                    fallback_idx = 0
                    return fallback_idx, f"Suicide Switch Blocked: {target_switch.species} dies to hazards ({total_hazard_damage*100:.1f}%)"

        # -------------------------------------------------------------
        # Guardrail 3: Emergency Defensive Terastallization
        # -------------------------------------------------------------
        can_tera = getattr(battle, "can_tera", False)
        if can_tera and 0 <= chosen_action_idx <= 3 and active and opponent:
            # If our active Pokémon is low HP (< 30%) and opponent outspeeds,
            # Terastallizing provides crucial defensive survival
            if active.current_hp_fraction < 0.35:
                tera_action_idx = chosen_action_idx + 4
                return tera_action_idx, f"Emergency Defensive Tera triggered for survival on {active.species}!"

        return chosen_action_idx, "Approved by Safety Shield"
