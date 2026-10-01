"""Transformer Set-Encoder Policy Network for PokeForge.

Phase B Architectural Upgrade:
Instead of treating teammates as a flat vector, this model formulates
the battle state as a set of interacting entity tokens:
  - Token 0: Active Pokémon representation (Species + Types + Moves)
  - Token 1: Opponent Active Pokémon representation (Species + Types)
  - Tokens 2..6: Five Bench Teammates (Species + HP fraction)
  - Token 7: Environmental Field Token (Hazards + Weather)

Uses Multi-Head Self-Attention (Query, Key, Value) to compute cross-team
synergies and threat interactions directly in latent space.
"""

from __future__ import annotations

import torch
import torch.nn as nn
import torch.nn.functional as F
from typing import Optional

from src.data.vocab import get_vocab_sizes
from src.data.action_space import NUM_ACTIONS
from src.data.state_encoder import NUM_NUMERIC


class TransformerSetPolicy(nn.Module):
    """Transformer-based policy network with self-attention across battle entities."""

    def __init__(
        self,
        num_species: int,
        num_moves: int,
        num_types: int,
        token_dim: int = 128,
        num_heads: int = 4,
        num_layers: int = 2,
        dim_feedforward: int = 256,
        dropout: float = 0.1,
    ):
        super().__init__()
        self.token_dim = token_dim

        # 1. Entity Embeddings
        self.species_embed = nn.Embedding(num_species, token_dim // 2, padding_idx=0)
        self.move_embed = nn.Embedding(num_moves, token_dim // 4, padding_idx=0)
        self.type_embed = nn.Embedding(num_types, token_dim // 4, padding_idx=0)

        # 2. Token Encoders (Mapping heterogeneous inputs to uniform token_dim)
        # Active token: species(64) + 2 types(32+32) + 4 moves pooled(32) + active HP(1) + boosts(5) = 166 -> 128
        self.active_encoder = nn.Sequential(
            nn.Linear((token_dim // 2) + (token_dim // 4 * 2) + (token_dim // 4) + 6, token_dim),
            nn.LayerNorm(token_dim),
            nn.GELU(),
        )

        # Opponent token: species(64) + 2 types(64) + opp HP(1) + boosts(5) = 134 -> 128
        self.opp_encoder = nn.Sequential(
            nn.Linear((token_dim // 2) + (token_dim // 4 * 2) + 6, token_dim),
            nn.LayerNorm(token_dim),
            nn.GELU(),
        )

        # Bench token: species(64) + HP(1) = 65 -> 128
        self.bench_encoder = nn.Sequential(
            nn.Linear((token_dim // 2) + 1, token_dim),
            nn.LayerNorm(token_dim),
            nn.GELU(),
        )

        # Field token: Remaining continuous features (hazards, weather, speeds) = 17 -> 128
        self.field_encoder = nn.Sequential(
            nn.Linear(17, token_dim),
            nn.LayerNorm(token_dim),
            nn.GELU(),
        )

        # 3. Multi-Head Self-Attention Transformer Backbone
        encoder_layer = nn.TransformerEncoderLayer(
            d_model=token_dim,
            nhead=num_heads,
            dim_feedforward=dim_feedforward,
            dropout=dropout,
            activation="gelu",
            batch_first=True,
            norm_first=True,
        )
        self.transformer = nn.TransformerEncoder(encoder_layer, num_layers=num_layers)

        # 4. Action Policy Head
        # Global average pool over the 8 tokens + Active token projection -> 13 Action Logits
        self.policy_head = nn.Sequential(
            nn.Linear(token_dim * 2, token_dim),
            nn.GELU(),
            nn.Dropout(dropout),
            nn.Linear(token_dim, NUM_ACTIONS),
        )

    def forward(
        self,
        categorical: torch.Tensor,
        numeric: torch.Tensor,
        action_mask: Optional[torch.Tensor] = None,
    ) -> torch.Tensor:
        """Forward pass with self-attention over battle tokens.
        
        Args:
            categorical: [B, 15] LongTensor
            numeric: [B, 35] FloatTensor
            action_mask: [B, 13] BoolTensor
            
        Returns:
            logits: [B, 13] FloatTensor
        """
        B = categorical.shape[0]

        # -------------------------------------------------------------
        # 1. Assemble Tokens
        # -------------------------------------------------------------
        # Token 0: Active Pokémon
        sp_emb = self.species_embed(categorical[:, 0])
        t1_emb = self.type_embed(categorical[:, 1])
        t2_emb = self.type_embed(categorical[:, 2])
        moves_emb = self.move_embed(categorical[:, 3:7]).mean(dim=1)  # Average pool over 4 moves
        active_nums = numeric[:, 0:6]  # HP + 5 boosts
        token_active = self.active_encoder(torch.cat([sp_emb, t1_emb, t2_emb, moves_emb, active_nums], dim=-1))

        # Token 1: Opponent Active
        opp_sp = self.species_embed(categorical[:, 7])
        opp_t1 = self.type_embed(categorical[:, 8])
        opp_t2 = self.type_embed(categorical[:, 9])
        opp_nums = numeric[:, 12:18]  # Opp HP + 5 boosts
        token_opp = self.opp_encoder(torch.cat([opp_sp, opp_t1, opp_t2, opp_nums], dim=-1))

        # Tokens 2..6: Five Bench Teammates
        bench_tokens = []
        for i in range(5):
            bench_sp = self.species_embed(categorical[:, 10 + i])
            bench_hp = numeric[:, 24 + i : 25 + i]
            token_bench_i = self.bench_encoder(torch.cat([bench_sp, bench_hp], dim=-1))
            bench_tokens.append(token_bench_i)

        # Token 7: Field condition (hazards, weather, speed advantage)
        field_nums = torch.cat([numeric[:, 6:12], numeric[:, 18:24], numeric[:, 29:]], dim=-1)
        token_field = self.field_encoder(field_nums[:, :17])

        # Sequence of 8 tokens: [B, 8, token_dim]
        tokens = torch.stack([token_active, token_opp] + bench_tokens + [token_field], dim=1)

        # -------------------------------------------------------------
        # 2. Self-Attention Processing
        # -------------------------------------------------------------
        attended = self.transformer(tokens)  # [B, 8, token_dim]

        # -------------------------------------------------------------
        # 3. Action Policy Readout
        # Combine Active Pokémon attended token with Global Mean Pool
        # -------------------------------------------------------------
        active_rep = attended[:, 0]               # [B, token_dim]
        global_rep = attended.mean(dim=1)         # [B, token_dim]
        fused = torch.cat([active_rep, global_rep], dim=-1)  # [B, token_dim * 2]

        logits = self.policy_head(fused)  # [B, 13]

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


def create_transformer_model(device: str = "cuda" if torch.cuda.is_available() else "cpu") -> TransformerSetPolicy:
    """Factory function for TransformerSetPolicy."""
    sizes = get_vocab_sizes()
    model = TransformerSetPolicy(
        num_species=sizes["num_species"],
        num_moves=sizes["num_moves"],
        num_types=sizes["num_types"],
    )
    return model.to(device)
