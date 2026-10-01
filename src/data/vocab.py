"""Vocabulary and Entity Encoding for Gen 9 Pokémon.

Maps discrete game entities (species, moves, types) to integer indices
for use with PyTorch nn.Embedding layers.

Index 0 is strictly reserved across all vocabularies for <PAD> / <UNKNOWN>.
"""

from __future__ import annotations

from typing import Dict, List, Tuple
from poke_env.data import GenData

# Load official Gen 9 competitive data
_GEN9_DATA = GenData.from_gen(9)

# 1. Types Vocabulary (18 standard types + Stellar)
TYPES: List[str] = [
    "normal", "fire", "water", "grass", "electric", "ice",
    "fighting", "poison", "ground", "flying", "psychic", "bug",
    "rock", "ghost", "dragon", "steel", "dark", "fairy", "stellar"
]
TYPE_TO_ID: Dict[str, int] = {t: idx + 1 for idx, t in enumerate(TYPES)}
TYPE_TO_ID["<pad>"] = 0
TYPE_TO_ID["<unk>"] = 0
ID_TO_TYPE: Dict[int, str] = {idx: t for t, idx in TYPE_TO_ID.items() if idx != 0}
ID_TO_TYPE[0] = "<unk>"

# 2. Species Vocabulary (All legal Gen 9 Pokémon)
SPECIES_LIST: List[str] = sorted(list(_GEN9_DATA.pokedex.keys()))
SPECIES_TO_ID: Dict[str, int] = {s: idx + 1 for idx, s in enumerate(SPECIES_LIST)}
SPECIES_TO_ID["<pad>"] = 0
SPECIES_TO_ID["<unk>"] = 0
ID_TO_SPECIES: Dict[int, str] = {idx: s for s, idx in SPECIES_TO_ID.items() if idx != 0}
ID_TO_SPECIES[0] = "<unk>"

# 3. Moves Vocabulary (All legal Gen 9 moves)
MOVES_LIST: List[str] = sorted(list(_GEN9_DATA.moves.keys()))
MOVE_TO_ID: Dict[str, int] = {m: idx + 1 for idx, m in enumerate(MOVES_LIST)}
MOVE_TO_ID["<pad>"] = 0
MOVE_TO_ID["<unk>"] = 0
ID_TO_MOVE: Dict[int, str] = {idx: m for m, idx in MOVE_TO_ID.items() if idx != 0}
ID_TO_MOVE[0] = "<unk>"


def encode_species(name: str | None) -> int:
    """Convert a Pokémon species name into its integer embedding index."""
    if not name:
        return 0
    clean = name.lower().replace(" ", "").replace("-", "").replace(".", "").replace("'", "")
    return SPECIES_TO_ID.get(clean, 0)


def encode_move(name: str | None) -> int:
    """Convert a Move name into its integer embedding index."""
    if not name:
        return 0
    clean = name.lower().replace(" ", "").replace("-", "").replace(".", "").replace("'", "")
    return MOVE_TO_ID.get(clean, 0)


def encode_type(name: str | None) -> int:
    """Convert a Pokémon type name into its integer embedding index."""
    if not name:
        return 0
    clean = name.lower().strip()
    return TYPE_TO_ID.get(clean, 0)


def get_vocab_sizes() -> Dict[str, int]:
    """Return vocabulary sizes (useful for setting nn.Embedding num_embeddings)."""
    return {
        "num_species": len(SPECIES_TO_ID),
        "num_moves": len(MOVE_TO_ID),
        "num_types": len(TYPE_TO_ID),
    }
