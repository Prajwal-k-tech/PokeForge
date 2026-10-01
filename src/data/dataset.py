"""PyTorch Dataset & DataLoader pipeline for PokeForge.

Implements PokemonBattleDataset, which manages:
  1. categorical_tokens: [N, 15] torch.long (species, types, moves)
  2. numeric_features:   [N, 35] torch.float32 (HP, stat boosts, status, hazards)
  3. action_masks:       [N, 13] torch.bool (legal action mask per turn)
  4. target_actions:     [N]     torch.long (the expert action chosen, 0..12)
"""

from __future__ import annotations

import torch
from torch.utils.data import Dataset, DataLoader
from typing import Dict, Optional, Tuple


class PokemonBattleDataset(Dataset):
    """Custom PyTorch Dataset for competitive Pokémon decision trajectories."""

    def __init__(
        self,
        categorical_tokens: torch.Tensor,
        numeric_features: torch.Tensor,
        action_masks: torch.Tensor,
        target_actions: torch.Tensor,
    ):
        """
        Args:
            categorical_tokens: LongTensor of shape [N, 15]
            numeric_features: FloatTensor of shape [N, 35]
            action_masks: BoolTensor of shape [N, 13]
            target_actions: LongTensor of shape [N]
        """
        assert len(categorical_tokens) == len(numeric_features) == len(action_masks) == len(target_actions), (
            f"Mismatched sample counts: {len(categorical_tokens)}, {len(numeric_features)}, "
            f"{len(action_masks)}, {len(target_actions)}"
        )
        self.categorical_tokens = categorical_tokens.long()
        self.numeric_features = numeric_features.float()
        self.action_masks = action_masks.bool()
        self.target_actions = target_actions.long()

    def __len__(self) -> int:
        return len(self.target_actions)

    def __getitem__(self, idx: int) -> Dict[str, torch.Tensor]:
        return {
            "categorical": self.categorical_tokens[idx],
            "numeric": self.numeric_features[idx],
            "action_mask": self.action_masks[idx],
            "target_action": self.target_actions[idx],
        }

    def save(self, filepath: str) -> None:
        """Serialize dataset tensors to disk."""
        torch.save(
            {
                "categorical": self.categorical_tokens,
                "numeric": self.numeric_features,
                "action_masks": self.action_masks,
                "target_actions": self.target_actions,
            },
            filepath,
        )

    @classmethod
    def load(cls, filepath: str) -> PokemonBattleDataset:
        """Load serialized dataset from disk."""
        data = torch.load(filepath, map_location="cpu", weights_only=True)
        return cls(
            categorical_tokens=data["categorical"],
            numeric_features=data["numeric"],
            action_masks=data["action_masks"],
            target_actions=data["target_actions"],
        )


def create_dataloader(
    dataset: PokemonBattleDataset,
    batch_size: int = 64,
    shuffle: bool = True,
    pin_memory: bool = True,
    num_workers: int = 0,
) -> DataLoader:
    """Create a high-throughput PyTorch DataLoader for GPU training."""
    return DataLoader(
        dataset,
        batch_size=batch_size,
        shuffle=shuffle,
        pin_memory=pin_memory,
        num_workers=num_workers,
    )
