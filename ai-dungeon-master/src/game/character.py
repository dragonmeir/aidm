"""OSE character sheet model and creation."""

from enum import Enum
from pydantic import BaseModel, Field
from .dice import roll, roll_stats, roll_hp


class CharacterClass(str, Enum):
    FIGHTER = "Fighter"
    MAGIC_USER = "Magic-User"
    CLERIC = "Cleric"
    THIEF = "Thief"
    DWARF = "Dwarf"
    ELF = "Elf"
    HALFLING = "Halfling"


# Class requirements and hit dice
CLASS_DATA = {
    CharacterClass.FIGHTER: {
        "hit_die": "1d8",
        "prime_req": "STR",
        "min_reqs": {},
        "saves": {"death": 12, "wands": 13, "paralysis": 14, "breath": 15, "spells": 16},
        "thac0": 19,
        "armor": ["any"],
        "weapons": ["any"],
    },
    CharacterClass.MAGIC_USER: {
        "hit_die": "1d4",
        "prime_req": "INT",
        "min_reqs": {},
        "saves": {"death": 13, "wands": 14, "paralysis": 13, "breath": 16, "spells": 15},
        "thac0": 19,
        "armor": ["none"],
        "weapons": ["dagger", "staff"],
    },
    CharacterClass.CLERIC: {
        "hit_die": "1d6",
        "prime_req": "WIS",
        "min_reqs": {},
        "saves": {"death": 11, "wands": 12, "paralysis": 14, "breath": 16, "spells": 15},
        "thac0": 19,
        "armor": ["any"],
        "weapons": ["blunt"],
    },
    CharacterClass.THIEF: {
        "hit_die": "1d4",
        "prime_req": "DEX",
        "min_reqs": {},
        "saves": {"death": 13, "wands": 14, "paralysis": 13, "breath": 16, "spells": 15},
        "thac0": 19,
        "armor": ["leather"],
        "weapons": ["any"],
    },
    CharacterClass.DWARF: {
        "hit_die": "1d8",
        "prime_req": "STR",
        "min_reqs": {"CON": 9},
        "saves": {"death": 8, "wands": 9, "paralysis": 10, "breath": 13, "spells": 12},
        "thac0": 19,
        "armor": ["any"],
        "weapons": ["any", "no_long_bows", "no_two_handed_swords"],
    },
    CharacterClass.ELF: {
        "hit_die": "1d6",
        "prime_req": "STR",
        "min_reqs": {"INT": 9},
        "saves": {"death": 12, "wands": 13, "paralysis": 13, "breath": 15, "spells": 15},
        "thac0": 19,
        "armor": ["any"],
        "weapons": ["any"],
    },
    CharacterClass.HALFLING: {
        "hit_die": "1d6",
        "prime_req": "DEX",
        "min_reqs": {"CON": 9, "DEX": 9},
        "saves": {"death": 8, "wands": 9, "paralysis": 10, "breath": 13, "spells": 12},
        "thac0": 19,
        "armor": ["any"],
        "weapons": ["any", "no_long_bows", "no_two_handed_swords"],
    },
}

ABILITY_NAMES = ["STR", "DEX", "CON", "INT", "WIS", "CHA"]

# OSE Level 1 Spell Lists
MAGIC_USER_SPELLS_L1 = [
    "Charm Person", "Detect Magic", "Floating Disc",
    "Hold Portal", "Light", "Magic Missile",
    "Protection from Evil", "Read Languages",
    "Read Magic", "Shield", "Sleep", "Ventriloquism",
]

CLERIC_SPELLS_L1 = [
    "Cure Light Wounds", "Detect Evil", "Detect Magic",
    "Light", "Protection from Evil", "Purify Food and Water",
    "Remove Fear", "Resist Cold",
]


def ability_modifier(score: int) -> int:
    """OSE ability score modifier table."""
    if score <= 3:
        return -3
    elif score <= 5:
        return -2
    elif score <= 8:
        return -1
    elif score <= 12:
        return 0
    elif score <= 15:
        return 1
    elif score <= 17:
        return 2
    else:
        return 3


def xp_adjustment(prime_req_score: int) -> int:
    """XP bonus/penalty percentage based on prime requisite."""
    if prime_req_score <= 5:
        return -20
    elif prime_req_score <= 8:
        return -10
    elif prime_req_score <= 12:
        return 0
    elif prime_req_score <= 15:
        return 5
    else:
        return 10


class Character(BaseModel):
    name: str = ""
    player_name: str = ""
    char_class: CharacterClass = CharacterClass.FIGHTER
    level: int = 1
    xp: int = 0

    # Ability scores
    strength: int = 10
    dexterity: int = 10
    constitution: int = 10
    intelligence: int = 10
    wisdom: int = 10
    charisma: int = 10

    # Combat
    hp: int = 1
    max_hp: int = 1
    ac: int = 9  # unarmored
    thac0: int = 19

    # Saves
    save_death: int = 14
    save_wands: int = 15
    save_paralysis: int = 16
    save_breath: int = 17
    save_spells: int = 18

    # Equipment
    inventory: list[str] = Field(default_factory=list)
    gold: int = 0
    weapons: list[str] = Field(default_factory=list)
    armor: str = "None"

    # Spells (for casters)
    spells_known: list[str] = Field(default_factory=list)
    spells_memorized: list[str] = Field(default_factory=list)
    # Spell slots: how many spells per spell level this character can memorize
    spell_slots: list[int] = Field(default_factory=list)  # [level1_slots, level2_slots, ...]

    # Status
    conditions: list[str] = Field(default_factory=list)
    notes: str = ""

    def get_ability(self, name: str) -> int:
        mapping = {
            "STR": self.strength, "DEX": self.dexterity,
            "CON": self.constitution, "INT": self.intelligence,
            "WIS": self.wisdom, "CHA": self.charisma,
        }
        return mapping.get(name.upper(), 10)

    def get_modifier(self, ability: str) -> int:
        return ability_modifier(self.get_ability(ability))

    def apply_class_data(self) -> None:
        """Apply class-specific data (saves, thac0, spells, etc.)."""
        data = CLASS_DATA[self.char_class]
        self.thac0 = data["thac0"]
        self.save_death = data["saves"]["death"]
        self.save_wands = data["saves"]["wands"]
        self.save_paralysis = data["saves"]["paralysis"]
        self.save_breath = data["saves"]["breath"]
        self.save_spells = data["saves"]["spells"]

        # Spell slots for casters (OSE level 1)
        if self.char_class == CharacterClass.MAGIC_USER:
            self.spell_slots = [1]  # 1 first-level spell
            self.spells_known = MAGIC_USER_SPELLS_L1.copy()
            self.spells_memorized = [self.spells_known[0]] if self.spells_known else []
        elif self.char_class == CharacterClass.CLERIC:
            self.spell_slots = [0]  # Clerics get no spells at L1 in OSE
            self.spells_known = CLERIC_SPELLS_L1.copy()
        elif self.char_class == CharacterClass.ELF:
            self.spell_slots = [1]  # 1 first-level spell
            self.spells_known = MAGIC_USER_SPELLS_L1.copy()
            self.spells_memorized = [self.spells_known[0]] if self.spells_known else []

    def cast_spell(self, spell_name: str) -> bool:
        """Cast a memorized spell. Returns True if successful."""
        for i, s in enumerate(self.spells_memorized):
            if s.lower() == spell_name.lower() and not s.startswith("[USED] "):
                self.spells_memorized[i] = f"[USED] {s}"
                return True
        return False

    def available_spells(self) -> list[str]:
        """Get list of spells that haven't been cast yet."""
        return [s for s in self.spells_memorized if not s.startswith("[USED] ")]

    def rest_and_memorize(self, spells: list[str] | None = None) -> None:
        """Full rest: restore spell slots. Optionally choose new spells to memorize."""
        if not self.spell_slots:
            return
        total_slots = sum(self.spell_slots)
        if spells:
            self.spells_memorized = spells[:total_slots]
        else:
            # Re-memorize whatever was there before, minus [USED] tags
            clean = [s.replace("[USED] ", "") for s in self.spells_memorized]
            self.spells_memorized = clean[:total_slots]

    def roll_hit_points(self) -> None:
        """Roll HP for level 1 with CON modifier."""
        data = CLASS_DATA[self.char_class]
        base_hp = roll_hp(data["hit_die"])
        con_mod = ability_modifier(self.constitution)
        self.max_hp = max(1, base_hp + con_mod)
        self.hp = self.max_hp

    def is_alive(self) -> bool:
        return self.hp > 0

    def take_damage(self, amount: int) -> int:
        """Apply damage, return actual damage taken."""
        actual = min(amount, self.hp)
        self.hp -= actual
        return actual

    def heal(self, amount: int) -> int:
        """Heal HP up to max, return actual healing."""
        actual = min(amount, self.max_hp - self.hp)
        self.hp += actual
        return actual

    def melee_attack_bonus(self) -> int:
        return ability_modifier(self.strength)

    def ranged_attack_bonus(self) -> int:
        return ability_modifier(self.dexterity)

    def ac_bonus(self) -> int:
        return ability_modifier(self.dexterity)

    def summary(self) -> str:
        """Short character summary string."""
        return (
            f"{self.name} - Level {self.level} {self.char_class.value} | "
            f"HP: {self.hp}/{self.max_hp} | AC: {self.ac} | "
            f"STR:{self.strength} DEX:{self.dexterity} CON:{self.constitution} "
            f"INT:{self.intelligence} WIS:{self.wisdom} CHA:{self.charisma}"
        )


def create_character(name: str, player_name: str, char_class: CharacterClass, auto_equip: bool = True) -> Character:
    """Create a new level 1 character with rolled stats and starting equipment."""
    stats = roll_stats()
    char = Character(
        name=name,
        player_name=player_name,
        char_class=char_class,
        strength=stats[0],
        dexterity=stats[1],
        constitution=stats[2],
        intelligence=stats[3],
        wisdom=stats[4],
        charisma=stats[5],
        gold=roll("3d6").total * 10,
    )
    char.apply_class_data()
    char.roll_hit_points()

    if auto_equip:
        from .equipment import equip_starting_package
        equip_starting_package(char)

    return char
