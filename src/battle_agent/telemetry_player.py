"""Telemetry & Smart Heuristic Player for Milestone 1.

Demonstrates how an AI agent interacts with the poke-env Battle object,
evaluates available actions, and makes decisions under the Showdown protocol.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional
from poke_env.player import Player
from poke_env.battle import AbstractBattle, Move, Pokemon


def estimate_move_damage(move: Move, attacker: Pokemon, defender: Pokemon) -> float:
    """Calculate an approximate damage score for a move.
    
    Factors in:
    1. Base Power: Raw move strength (e.g. 80 for Shadow Ball).
    2. STAB (Same Type Attack Bonus): 1.5x multiplier if move type matches attacker.
    3. Type Effectiveness: 0x (immune), 0.5x (resisted), 1x (neutral), 2x or 4x (super-effective).
    """
    if move.base_power == 0:
        return 0.0

    power = float(move.base_power)

    # 1. Apply STAB (1.5x if move type matches one of the attacker's types)
    if move.type in attacker.types:
        power *= 1.5

    # 2. Apply Type Effectiveness multiplier against the defender
    effectiveness = defender.damage_multiplier(move)
    power *= effectiveness

    # 3. Factor in Move Accuracy (e.g. 85% accuracy discounts expected power)
    if move.accuracy is not None and move.accuracy is not True:
        power *= (move.accuracy / 100.0)

    return power


class TelemetryPlayer(Player):
    """An educational battle agent that logs real-time state telemetry

    and chooses the move with the highest estimated damage.
    """

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.recorded_telemetry: List[Dict[str, Any]] = []

    def choose_move(self, battle: AbstractBattle):
        """The core decision method called by poke-env every single turn.
        
        Args:
            battle: The full state of the current match.
            
        Returns:
            A BattleOrder (an attack or a switch) to send over the WebSocket.
        """
        active = battle.active_pokemon
        opponent = battle.opponent_active_pokemon

        # Snapshot of turn telemetry for learning & inspection
        telemetry = {
            "turn": battle.turn,
            "active_pokemon": active.species if active else "None",
            "active_hp_percent": round(active.current_hp_fraction, 2) if active else 0.0,
            "opponent_pokemon": opponent.species if opponent else "None",
            "opponent_hp_percent": round(opponent.current_hp_fraction, 2) if opponent else 0.0,
            "available_moves": [],
            "available_switches": [s.species for s in battle.available_switches],
            "chosen_action": None,
        }

        # 1. Evaluate Damaging Moves
        best_move: Optional[Move] = None
        best_damage = -1.0

        if battle.available_moves and active and opponent:
            for move in battle.available_moves:
                damage = estimate_move_damage(move, active, opponent)
                telemetry["available_moves"].append({
                    "name": move.id,
                    "type": str(move.type.name),
                    "base_power": move.base_power,
                    "estimated_damage": damage,
                })
                if damage > best_damage:
                    best_damage = damage
                    best_move = move

        # 2. Make Decision
        if best_move and best_damage > 0:
            telemetry["chosen_action"] = f"MOVE: {best_move.id} (Est. Power: {best_damage:.1f})"
            self.recorded_telemetry.append(telemetry)
            return self.create_order(best_move)

        # 3. If no damaging move is viable, pick a random move or switch
        telemetry["chosen_action"] = "FALLBACK: Random Action"
        self.recorded_telemetry.append(telemetry)
        return self.choose_random_move(battle)
