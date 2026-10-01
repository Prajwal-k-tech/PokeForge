"""Residual Multi-Layer Perceptron (Residual MLP) Policy Network.

The Phase A "Walking Skeleton" backbone for PokeForge:
1. Embeds categorical entities (species, moves, types) using learned nn.Embedding layers.
2. Concatenates embeddings with continuous normalized battle metrics.
3. Passes the fused state through Residual Blocks with LayerNorm, GELU, and Dropout.
4. Outputs 13 action logits, with illegal actions masked to -1e9 before decision.
"""

from __future__ import annotations

import torch
import torch.nn as nn
import torch.nn.functional as F
from typing import Dict, Optional

from src.data.vocab import get_vocab_sizes
from src.data.action_space import NUM_ACTIONS
from src.data.state_encoder import NUM_CATEGORICAL, NUM_NUMERIC


class ResidualBlock(nn.Module):
    """A single residual layer: Linear -> LayerNorm -> GELU -> Dropout -> Linear -> LayerNorm + x."""

    def __init__(self, hidden_dim: int, dropout: float = 0.1):
        super().__init__()
        self.block = nn.Sequential(
            nn.Linear(hidden_dim, hidden_dim),
            nn.LayerNorm(hidden_dim),
            nn.GELU(),
            nn.Dropout(dropout),
            nn.Linear(hidden_dim, hidden_dim),
            nn.LayerNorm(hidden_dim),
        )

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        return x + self.block(x)


class ResidualMLPPolicy(nn.Module):
    """The complete battle decision policy network."""

    def __init__(
        self,
        num_species: int,
        num_moves: int,
        num_types: int,
        species_embed_dim: int = 32,
        move_embed_dim: int = 32,
        type_embed_dim: int = 16,
        num_numeric_features: int = NUM_NUMERIC,
        hidden_dim: int = 256,
        num_residual_blocks: int = 3,
        dropout: float = 0.1,
    ):
        super().__init__()

        # -------------------------------------------------------------
        # 1. Embedding Layers (index 0 is padding/unknown)
        # -------------------------------------------------------------
        self.species_embed = nn.Embedding(num_species, species_embed_dim, padding_idx=0)
        self.move_embed = nn.Embedding(num_moves, move_embed_dim, padding_idx=0)
        self.type_embed = nn.Embedding(num_types, type_embed_dim, padding_idx=0)

        # -------------------------------------------------------------
        # 2. Compute Fused Input Dimension
        # Categorical layout (15 tokens):
        #   [0] active species (32)
        #   [1, 2] active types (2 * 16 = 32)
        #   [3..6] active moves (4 * 32 = 128)
        #   [7] opp species (32)
        #   [8, 9] opp types (2 * 16 = 32)
        #   [10..14] bench species (5 * 32 = 160)
        # Total categorical embedding size = 32 + 32 + 128 + 32 + 32 + 160 = 416 dims
        # -------------------------------------------------------------
        total_embed_dim = (
            species_embed_dim * 1       # Active species
            + type_embed_dim * 2        # Active types
            + move_embed_dim * 4        # Active moves
            + species_embed_dim * 1     # Opponent species
            + type_embed_dim * 2        # Opponent types
            + species_embed_dim * 5     # Bench species
        )
        fused_in_dim = total_embed_dim + num_numeric_features

        # -------------------------------------------------------------
        # 3. Input Projection & Residual Backbone
        # -------------------------------------------------------------
        self.input_proj = nn.Sequential(
            nn.Linear(fused_in_dim, hidden_dim),
            nn.LayerNorm(hidden_dim),
            nn.GELU(),
            nn.Dropout(dropout),
        )

        self.res_blocks = nn.ModuleList([
            ResidualBlock(hidden_dim, dropout=dropout) for _ in range(num_residual_blocks)
        ])

        # -------------------------------------------------------------
        # 4. Action Policy Head (Outputs 13 Action Logits)
        # -------------------------------------------------------------
        self.policy_head = nn.Sequential(
            nn.Linear(hidden_dim, hidden_dim // 2),
            nn.GELU(),
            nn.Linear(hidden_dim // 2, NUM_ACTIONS),
        )

    def forward(
        self,
        categorical: torch.Tensor,
        numeric: torch.Tensor,
        action_mask: Optional[torch.Tensor] = None,
    ) -> torch.Tensor:
        """Forward pass through the network.
        
        Args:
            categorical: [B, 15] LongTensor
            numeric: [B, 35] FloatTensor
            action_mask: [B, 13] BoolTensor (optional, True = legal, False = illegal)
            
        Returns:
            logits: [B, 13] FloatTensor of unnormalized action scores
        """
        # Embed each category slot
        emb_active_sp = self.species_embed(categorical[:, 0])             # [B, 32]
        emb_active_t1 = self.type_embed(categorical[:, 1])                # [B, 16]
        emb_active_t2 = self.type_embed(categorical[:, 2])                # [B, 16]
        emb_moves = self.move_embed(categorical[:, 3:7]).flatten(1)       # [B, 128]
        emb_opp_sp = self.species_embed(categorical[:, 7])                # [B, 32]
        emb_opp_t1 = self.type_embed(categorical[:, 8])                   # [B, 16]
        emb_opp_t2 = self.type_embed(categorical[:, 9])                   # [B, 16]
        emb_bench = self.species_embed(categorical[:, 10:15]).flatten(1)  # [B, 160]

        # Concatenate embeddings and numeric features into one vector
        fused = torch.cat([
            emb_active_sp, emb_active_t1, emb_active_t2,
            emb_moves,
            emb_opp_sp, emb_opp_t1, emb_opp_t2,
            emb_bench,
            numeric,
        ], dim=-1)

        # Pass through backbone
        x = self.input_proj(fused)
        for block in self.res_blocks:
            x = block(x)

        # Policy logits
        logits = self.policy_head(x)  # [B, 13]

        # Apply Action Masking: mask out illegal actions with -1e9 so softmax = 0.0%
        if action_mask is not None:
            logits = logits.masked_fill(~action_mask, -1e9)

        return logits

    @torch.no_grad()
    def predict_action(
        self,
        categorical: torch.Tensor,
        numeric: torch.Tensor,
        action_mask: torch.Tensor,
        deterministic: bool = True,
    ) -> int:
        """Inference helper for live battles (Batch size = 1).
        
        Returns:
            Selected action index (0..12)
        """
        if categorical.dim() == 1:
            categorical = categorical.unsqueeze(0)
        if numeric.dim() == 1:
            numeric = numeric.unsqueeze(0)
        if action_mask.dim() == 1:
            action_mask = action_mask.unsqueeze(0)

        logits = self.forward(categorical, numeric, action_mask=action_mask)

        if deterministic:
            return int(torch.argmax(logits, dim=-1).item())
        else:
            probs = F.softmax(logits, dim=-1)
            dist = torch.distributions.Categorical(probs)
            return int(dist.sample().item())


def create_policy_model(device: str = "cuda" if torch.cuda.is_available() else "cpu") -> ResidualMLPPolicy:
    """Factory function to instantiate the model with official Gen 9 vocab sizes."""
    sizes = get_vocab_sizes()
    model = ResidualMLPPolicy(
        num_species=sizes["num_species"],
        num_moves=sizes["num_moves"],
        num_types=sizes["num_types"],
    )
    return model.to(device)
