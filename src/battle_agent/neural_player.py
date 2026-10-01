"""Neural Policy Battle Player for PokeForge.

Autonomous competitive battle agent that:
1. Extracts real-time state tensors using encode_battle_state.
2. Runs low-latency forward pass on RTX 3050 GPU (< 1ms).
3. Applies the Deterministic Safety Shield (Lethal execution + hazard math).
4. Submits orders to Pokémon Showdown within tournament timer constraints.
"""

from __future__ import annotations

import torch
from typing import Optional
from poke_env.battle import AbstractBattle
from poke_env.player import Player, BattleOrder

from src.models.residual_mlp import ResidualMLPPolicy, create_policy_model
from src.models.transformer_policy import TransformerSetPolicy, create_transformer_model
from src.data.state_encoder import encode_battle_state
from src.data.action_space import action_index_to_order
from src.battle_agent.safety_shield import SafetyShield


class NeuralBattlePlayer(Player):
    """The complete autonomous deep learning battle agent."""

    def __init__(
        self,
        checkpoint_path: Optional[str] = "checkpoints/best_policy_mlp.pt",
        model_type: str = "mlp",
        device: str = "cuda" if torch.cuda.is_available() else "cpu",
        use_safety_shield: bool = True,
        *args,
        **kwargs,
    ):
        super().__init__(*args, **kwargs)
        self.device = device
        self.use_safety_shield = use_safety_shield
        self.safety_shield = SafetyShield()

        # Load appropriate model onto GPU
        if model_type == "transformer":
            self.model = create_transformer_model(device=device)
        else:
            self.model = create_policy_model(device=device)

        if checkpoint_path and torch.cuda.is_available():
            try:
                ckpt = torch.load(checkpoint_path, map_location=device, weights_only=True)
                if "model_state_dict" in ckpt:
                    self.model.load_state_dict(ckpt["model_state_dict"])
                else:
                    self.model.load_state_dict(ckpt)
                print(f"[{self.username}] Loaded {model_type.upper()} policy weights from {checkpoint_path} on {device}! ✅")
            except Exception as e:
                print(f"[{self.username}] Note: Starting with initialized weights ({e}).")

        self.model.eval()

    def choose_move(self, battle: AbstractBattle) -> BattleOrder:
        """The real-time decision loop called every turn by Showdown."""
        # 1. State tensor extraction (CPU)
        cats, nums, mask = encode_battle_state(battle)

        # 2. Transfer to RTX 3050 (CUDA)
        cats = cats.to(self.device)
        nums = nums.to(self.device)
        mask = mask.to(self.device)

        # 3. Neural inference
        raw_action = self.model.predict_action(cats, nums, mask, deterministic=True)

        # 4. Apply Deterministic Safety Shield
        final_action = raw_action
        if self.use_safety_shield:
            final_action, reason = self.safety_shield.apply_guardrails(raw_action, battle)

        # 5. Format order and return to WebSocket
        return action_index_to_order(final_action, battle)
