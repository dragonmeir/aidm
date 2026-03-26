"""Random tables for OSE - encounters, treasure, dungeon dressing, traps."""

from .dice import roll


# ── Wandering Monsters by Dungeon Level ─────────────────────

WANDERING_MONSTERS = {
    1: [
        {"name": "Giant Rats", "num": "2d4", "hp": 1, "ac": 9, "thac0": 19, "damage": "1d3", "morale": 8},
        {"name": "Goblins", "num": "2d4", "hp": 3, "ac": 6, "thac0": 19, "damage": "1d6", "morale": 7},
        {"name": "Kobolds", "num": "4d4", "hp": 2, "ac": 7, "thac0": 19, "damage": "1d4", "morale": 6},
        {"name": "Skeletons", "num": "3d4", "hp": 4, "ac": 7, "thac0": 19, "damage": "1d6", "morale": 12},
        {"name": "Giant Centipedes", "num": "1d6", "hp": 1, "ac": 9, "thac0": 19, "damage": "poison", "morale": 7},
        {"name": "Bandits", "num": "1d8", "hp": 4, "ac": 6, "thac0": 19, "damage": "1d6", "morale": 8},
        {"name": "Fire Beetles", "num": "1d8", "hp": 5, "ac": 4, "thac0": 19, "damage": "2d4", "morale": 7},
        {"name": "Giant Bats", "num": "1d10", "hp": 2, "ac": 6, "thac0": 19, "damage": "1d4", "morale": 8},
    ],
    2: [
        {"name": "Zombies", "num": "2d4", "hp": 9, "ac": 8, "thac0": 19, "damage": "1d8", "morale": 12},
        {"name": "Orcs", "num": "2d4", "hp": 4, "ac": 6, "thac0": 19, "damage": "1d6", "morale": 8},
        {"name": "Hobgoblins", "num": "1d6", "hp": 5, "ac": 6, "thac0": 19, "damage": "1d8", "morale": 8},
        {"name": "Giant Spiders", "num": "1d3", "hp": 9, "ac": 7, "thac0": 19, "damage": "1d6+poison", "morale": 8},
        {"name": "Troglodytes", "num": "1d8", "hp": 9, "ac": 5, "thac0": 19, "damage": "1d4", "morale": 9},
        {"name": "Gnolls", "num": "1d6", "hp": 9, "ac": 5, "thac0": 19, "damage": "2d4", "morale": 8},
        {"name": "Lizardmen", "num": "2d4", "hp": 9, "ac": 5, "thac0": 19, "damage": "1d6+1", "morale": 11},
        {"name": "Giant Ferrets", "num": "1d8", "hp": 5, "ac": 5, "thac0": 19, "damage": "1d8", "morale": 8},
    ],
    3: [
        {"name": "Ghouls", "num": "1d6", "hp": 13, "ac": 6, "thac0": 19, "damage": "1d3+paralysis", "morale": 9},
        {"name": "Wights", "num": "1d4", "hp": 13, "ac": 5, "thac0": 17, "damage": "energy drain", "morale": 12},
        {"name": "Ogres", "num": "1d3", "hp": 19, "ac": 5, "thac0": 17, "damage": "1d10", "morale": 10},
        {"name": "Shadows", "num": "1d4", "hp": 13, "ac": 7, "thac0": 19, "damage": "1d4+STR drain", "morale": 12},
        {"name": "Bugbears", "num": "2d4", "hp": 14, "ac": 5, "thac0": 17, "damage": "2d4", "morale": 9},
        {"name": "Harpies", "num": "1d6", "hp": 14, "ac": 7, "thac0": 17, "damage": "1d4+charm", "morale": 7},
        {"name": "Gargoyles", "num": "1d4", "hp": 18, "ac": 5, "thac0": 17, "damage": "1d4/1d4/1d6/1d4", "morale": 11},
        {"name": "Wraiths", "num": "1d3", "hp": 18, "ac": 3, "thac0": 17, "damage": "1d6+energy drain", "morale": 12},
    ],
    4: [
        {"name": "Minotaurs", "num": "1d4", "hp": 27, "ac": 6, "thac0": 15, "damage": "1d6/1d6", "morale": 12},
        {"name": "Mummies", "num": "1d4", "hp": 27, "ac": 3, "thac0": 15, "damage": "1d12+disease", "morale": 12},
        {"name": "Trolls", "num": "1d3", "hp": 30, "ac": 4, "thac0": 15, "damage": "1d6/1d6/1d10", "morale": 10},
        {"name": "Cockatrices", "num": "1d4", "hp": 22, "ac": 6, "thac0": 15, "damage": "1d6+petrify", "morale": 7},
        {"name": "Manticores", "num": "1d2", "hp": 30, "ac": 4, "thac0": 15, "damage": "1d4/1d4/2d4", "morale": 9},
        {"name": "Werewolves", "num": "1d4", "hp": 18, "ac": 5, "thac0": 17, "damage": "2d4", "morale": 8},
    ],
}


# ── Treasure ────────────────────────────────────────────────

TREASURE_INDIVIDUAL = {
    "poor": {"copper": "3d8", "silver": "0", "gold": "0"},
    "average": {"copper": "2d6", "silver": "2d6", "gold": "0"},
    "good": {"copper": "0", "silver": "2d6", "gold": "1d6"},
    "rich": {"copper": "0", "silver": "3d6", "gold": "2d6"},
    "hoard": {"copper": "0", "silver": "1d6", "gold": "3d6", "gems": "1d4"},
}

GEMS = [
    ("agate", 10), ("quartz", 10), ("turquoise", 10),
    ("bloodstone", 50), ("onyx", 50), ("jasper", 50),
    ("amber", 100), ("coral", 100), ("garnet", 100),
    ("pearl", 500), ("topaz", 500), ("opal", 500),
    ("ruby", 1000), ("emerald", 1000), ("sapphire", 1000),
    ("diamond", 5000),
]

MAGIC_ITEMS_MINOR = [
    "Potion of Healing",
    "Potion of ESP",
    "Potion of Speed",
    "Scroll of Protection from Evil",
    "Scroll of Light",
    "Scroll of Hold Portal",
    "+1 Dagger",
    "+1 Arrows (1d6)",
    "Ring of Protection +1",
    "Wand of Magic Detection (2d10 charges)",
]

MAGIC_ITEMS_MEDIUM = [
    "+1 Sword",
    "+1 Shield",
    "+1 Leather Armor",
    "Potion of Invisibility",
    "Potion of Giant Strength",
    "Scroll of Fireball",
    "Ring of Fire Resistance",
    "Wand of Paralysis (2d10 charges)",
    "Boots of Elvenkind",
    "Cloak of Displacement",
]


# ── Dungeon Dressing ───────────────────────────────────────

DUNGEON_NOISES = [
    "dripping water echoes from somewhere ahead",
    "a faint scratching sound from behind the walls",
    "distant, rhythmic hammering — too regular to be natural",
    "a low moan carried on a cold draft",
    "chains rattling somewhere below",
    "the skitter of many tiny legs across stone",
    "a faint chanting in an unknown tongue",
    "the creak and groan of old timber",
    "a sudden, sharp crack — then silence",
    "the splash of something moving through standing water",
]

DUNGEON_SMELLS = [
    "damp stone and old rot",
    "acrid smoke, recently burned",
    "the copper tang of blood, not yet dry",
    "a sickly-sweet floral scent, entirely wrong for underground",
    "sulfur and brimstone",
    "animal musk — something lives nearby",
    "the musty smell of ancient parchment",
    "stale air that hasn't moved in decades",
]

DUNGEON_AIR = [
    "the air is stale and heavy",
    "a cold draft blows from the left passage",
    "the air is unnaturally warm here",
    "condensation drips from the ceiling",
    "a thin mist clings to the floor",
    "the air tastes of dust and iron",
]

TRAP_TYPES = [
    {"name": "Pit Trap", "damage": "1d6", "save": "paralysis", "description": "The floor gives way!"},
    {"name": "Poison Needle", "damage": "poison", "save": "death", "description": "A needle jabs from the lock!"},
    {"name": "Arrow Trap", "damage": "1d6", "save": "wands", "description": "Arrows fire from the walls!"},
    {"name": "Falling Block", "damage": "2d6", "save": "paralysis", "description": "A stone block drops from the ceiling!"},
    {"name": "Scything Blade", "damage": "1d8", "save": "breath", "description": "A blade swings from the wall!"},
    {"name": "Gas Trap", "damage": "sleep", "save": "spells", "description": "A cloud of soporific gas fills the area!"},
    {"name": "Spear Trap", "damage": "1d8", "save": "breath", "description": "Spears thrust up from the floor!"},
]


# ── Functions ──────────────────────────────────────────────

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


def roll_gem() -> tuple[str, int]:
    """Roll a random gem."""
    idx = roll(f"1d{len(GEMS)}").total - 1
    return GEMS[idx]


def roll_magic_item(level: str = "minor") -> str:
    """Roll a random magic item."""
    table = MAGIC_ITEMS_MINOR if level == "minor" else MAGIC_ITEMS_MEDIUM
    idx = roll(f"1d{len(table)}").total - 1
    return table[idx]


def roll_dungeon_noise() -> str:
    idx = roll(f"1d{len(DUNGEON_NOISES)}").total - 1
    return DUNGEON_NOISES[idx]


def roll_dungeon_smell() -> str:
    idx = roll(f"1d{len(DUNGEON_SMELLS)}").total - 1
    return DUNGEON_SMELLS[idx]


def roll_dungeon_air() -> str:
    idx = roll(f"1d{len(DUNGEON_AIR)}").total - 1
    return DUNGEON_AIR[idx]


def roll_trap() -> dict:
    idx = roll(f"1d{len(TRAP_TYPES)}").total - 1
    return TRAP_TYPES[idx].copy()
