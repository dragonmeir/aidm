"""Random tables for OSE - encounters, treasure, etc."""

from .dice import roll


# Basic dungeon encounter tables (by dungeon level)
WANDERING_MONSTERS = {
    1: [
        {"name": "Giant Rats", "num": "2d4", "hp": 1, "ac": 9, "thac0": 19, "damage": "1d3", "morale": 8},
        {"name": "Goblins", "num": "2d4", "hp": 3, "ac": 6, "thac0": 19, "damage": "1d6", "morale": 7},
        {"name": "Kobolds", "num": "4d4", "hp": 2, "ac": 7, "thac0": 19, "damage": "1d4", "morale": 6},
        {"name": "Skeletons", "num": "3d4", "hp": 4, "ac": 7, "thac0": 19, "damage": "1d6", "morale": 12},
        {"name": "Giant Centipedes", "num": "1d6", "hp": 1, "ac": 9, "thac0": 19, "damage": "poison", "morale": 7},
        {"name": "Bandits", "num": "1d8", "hp": 4, "ac": 6, "thac0": 19, "damage": "1d6", "morale": 8},
    ],
    2: [
        {"name": "Zombies", "num": "2d4", "hp": 9, "ac": 8, "thac0": 19, "damage": "1d8", "morale": 12},
        {"name": "Orcs", "num": "2d4", "hp": 4, "ac": 6, "thac0": 19, "damage": "1d6", "morale": 8},
        {"name": "Hobgoblins", "num": "1d6", "hp": 5, "ac": 6, "thac0": 19, "damage": "1d8", "morale": 8},
        {"name": "Giant Spiders", "num": "1d3", "hp": 9, "ac": 7, "thac0": 19, "damage": "1d6+poison", "morale": 8},
        {"name": "Troglodytes", "num": "1d8", "hp": 9, "ac": 5, "thac0": 19, "damage": "1d4", "morale": 9},
        {"name": "Gnolls", "num": "1d6", "hp": 9, "ac": 5, "thac0": 19, "damage": "2d4", "morale": 8},
    ],
    3: [
        {"name": "Ghouls", "num": "1d6", "hp": 13, "ac": 6, "thac0": 19, "damage": "1d3+paralysis", "morale": 9},
        {"name": "Wights", "num": "1d4", "hp": 13, "ac": 5, "thac0": 17, "damage": "energy drain", "morale": 12},
        {"name": "Ogres", "num": "1d3", "hp": 19, "ac": 5, "thac0": 17, "damage": "1d10", "morale": 10},
        {"name": "Shadows", "num": "1d4", "hp": 13, "ac": 7, "thac0": 19, "damage": "1d4+STR drain", "morale": 12},
        {"name": "Bugbears", "num": "2d4", "hp": 14, "ac": 5, "thac0": 17, "damage": "2d4", "morale": 9},
        {"name": "Harpies", "num": "1d6", "hp": 14, "ac": 7, "thac0": 17, "damage": "1d4+charm", "morale": 7},
    ],
}

# Treasure types (simplified)
TREASURE_INDIVIDUAL = {
    "poor": {"copper": "3d8", "silver": "0", "gold": "0"},
    "average": {"copper": "2d6", "silver": "2d6", "gold": "0"},
    "good": {"copper": "0", "silver": "2d6", "gold": "1d6"},
    "rich": {"copper": "0", "silver": "3d6", "gold": "2d6"},
}


def check_wandering_monster() -> bool:
    """1-in-6 chance of wandering monster."""
    return roll("1d6").total == 1


def roll_wandering_monster(dungeon_level: int = 1) -> dict | None:
    """Roll a random wandering monster for the dungeon level."""
    level = min(dungeon_level, max(WANDERING_MONSTERS.keys()))
    if level not in WANDERING_MONSTERS:
        level = 1

    monsters = WANDERING_MONSTERS[level]
    idx = roll(f"1d{len(monsters)}").total - 1
    monster = monsters[idx].copy()

    # Roll number appearing
    monster["count"] = roll(monster["num"]).total
    return monster


def roll_treasure(quality: str = "average") -> dict:
    """Roll individual treasure."""
    if quality not in TREASURE_INDIVIDUAL:
        quality = "average"

    treasure = {}
    for coin, dice in TREASURE_INDIVIDUAL[quality].items():
        if dice != "0":
            amount = roll(dice).total
            if amount > 0:
                treasure[coin] = amount
    return treasure
