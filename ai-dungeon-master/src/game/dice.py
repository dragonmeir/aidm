"""Dice roller supporting standard RPG notation."""

import random
import re
from dataclasses import dataclass


@dataclass
class DiceResult:
    notation: str
    rolls: list[int]
    modifier: int
    total: int

    def __str__(self) -> str:
        parts = [f"{self.notation}: "]
        if len(self.rolls) > 1:
            parts.append(f"[{', '.join(str(r) for r in self.rolls)}]")
        else:
            parts.append(str(self.rolls[0]) if self.rolls else "0")
        if self.modifier > 0:
            parts.append(f" + {self.modifier}")
        elif self.modifier < 0:
            parts.append(f" - {abs(self.modifier)}")
        parts.append(f" = {self.total}")
        return "".join(parts)


# Pattern: optional count, 'd', sides, optional modifier
DICE_PATTERN = re.compile(
    r"^(\d+)?d(\d+|%)((?:[+-]\d+)?)$", re.IGNORECASE
)


def roll(notation: str) -> DiceResult:
    """Roll dice using standard notation (e.g., 2d6+3, d20, d%, 3d8-1)."""
    notation = notation.strip().lower()
    match = DICE_PATTERN.match(notation)
    if not match:
        raise ValueError(f"Invalid dice notation: {notation}")

    count = int(match.group(1)) if match.group(1) else 1
    sides_str = match.group(2)
    sides = 100 if sides_str == "%" else int(sides_str)
    modifier = int(match.group(3)) if match.group(3) else 0

    if count < 1 or count > 100:
        raise ValueError("Dice count must be between 1 and 100")
    if sides < 1:
        raise ValueError("Dice must have at least 1 side")

    rolls = [random.randint(1, sides) for _ in range(count)]
    total = sum(rolls) + modifier

    return DiceResult(
        notation=notation,
        rolls=rolls,
        modifier=modifier,
        total=total,
    )


def roll_stats() -> list[int]:
    """Roll 3d6 for each of the 6 ability scores (OSE style)."""
    return [roll("3d6").total for _ in range(6)]


def roll_hp(hit_die: str) -> int:
    """Roll hit points, minimum 1."""
    result = roll(hit_die)
    return max(1, result.total)


def check_morale(morale_score: int) -> bool:
    """Roll 2d6 morale check. Returns True if morale holds."""
    result = roll("2d6")
    return result.total <= morale_score


def reaction_roll(modifier: int = 0) -> str:
    """2d6 reaction roll table (OSE B/X)."""
    result = roll("2d6").total + modifier
    if result <= 2:
        return "Hostile, attacks"
    elif result <= 5:
        return "Unfriendly, may attack"
    elif result <= 8:
        return "Neutral, uncertain"
    elif result <= 11:
        return "Indifferent, uninterested"
    else:
        return "Friendly, helpful"
