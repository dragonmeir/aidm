"""Pydantic models defining any TTRPG's mechanical DNA.

These models form a universal schema capable of representing rule systems
from OSE to Call of Cthulhu to Forbidden Lands to Monster of the Week.
The schema is populated either by hand-written YAML or by the LLM
extraction pipeline.
"""

from __future__ import annotations

from typing import Any
from pydantic import BaseModel, Field


# ── Attributes ──────────────────────────────────────────────

class AttributeDefinition(BaseModel):
    """A single character attribute (e.g. STR, Agility, Cool)."""
    name: str                        # "Strength", "Agility", "Cool"
    abbreviation: str                # "STR", "AGL", "COOL"
    min_value: int = 1
    max_value: int = 18
    generation_method: str = "3d6"   # dice notation or "point_buy", "fixed_array"
    # Modifier lookup: key is a range string like "3", "4-5", "6-8"
    # value is the modifier integer.  None means no modifiers.
    modifier_table: dict[str, int] | None = None


class AttributeSystem(BaseModel):
    """How character attributes work in this system."""
    attributes: list[AttributeDefinition]
    # "in_order" = roll in sequence, "assign" = roll pool then assign,
    # "point_buy" = spend points, "fixed" = use fixed values
    generation_order: str = "in_order"


# ── Skills ──────────────────────────────────────────────────

class SkillDefinition(BaseModel):
    """A single skill (e.g. Spot Hidden 25%, Melee 2, Defy Danger)."""
    name: str
    base_value: str = "0"            # "1d100/2", "0", "1"
    linked_attribute: str = ""       # "DEX", "Agility", ""
    category: str = ""               # "combat", "investigation", "social"
    description: str = ""


class SkillSystem(BaseModel):
    """Skill resolution mechanics.  None for skill-less systems like OSE."""
    # How skill checks are resolved
    resolution: str                  # "percentile_roll_under", "d6_pool",
                                     # "2d6_plus_stat", "d20_roll_under",
                                     # "d20_roll_over", "stat_test"
    dice: str = ""                   # "d100", "d6", "2d6", "d20"
    skills: list[SkillDefinition] = Field(default_factory=list)
    # How skills improve between sessions
    improvement_method: str = ""     # "check_and_roll", "xp_spend", "advance_on_fail"


# ── Character Types ─────────────────────────────────────────

class CharacterTypeDefinition(BaseModel):
    """A character class, playbook, career, or archetype."""
    name: str                        # "Fighter", "The Chosen", "Scout"
    category: str = ""               # "class", "playbook", "career", "kin"
    hit_die: str = ""                # "1d8", "1d6", ""
    prime_attribute: str = ""        # "STR", "Cool"
    requirements: dict[str, int] = Field(default_factory=dict)  # {"CON": 9}
    save_values: dict[str, int] = Field(default_factory=dict)
    thac0: int | None = None         # Only for THAC0 systems
    special_abilities: list[str] = Field(default_factory=list)
    starting_equipment: list[str] = Field(default_factory=list)
    armor_allowed: list[str] = Field(default_factory=list)  # ["any"], ["leather"], ["none"]
    weapons_allowed: list[str] = Field(default_factory=list)
    # Spells at creation
    starting_spells: list[str] = Field(default_factory=list)
    spell_slots_by_level: list[int] = Field(default_factory=list)  # [1, 0, 0] = 1 L1 slot
    # Arbitrary system-specific data
    extra: dict[str, Any] = Field(default_factory=dict)


class CharacterTypeSystem(BaseModel):
    """Character type selection (classes, playbooks, careers)."""
    label: str = "Class"             # "Class", "Playbook", "Career", "Kin"
    types: list[CharacterTypeDefinition] = Field(default_factory=list)
    optional: bool = False           # True for classless systems


# ── Combat ──────────────────────────────────────────────────

class AttackResolution(BaseModel):
    """How attacks/hits are determined."""
    method: str                      # "thac0_minus_ac", "d20_vs_ac",
                                     # "percentile_skill", "dice_pool",
                                     # "2d6_plus_stat", "opposed_roll",
                                     # "d20_roll_under"
    dice: str = "1d20"               # primary attack die/dice
    success_condition: str = ""      # human-readable, e.g. "roll >= thac0 - target_ac"
    critical_success: str = ""       # "natural 20", "01-05", "extra sixes"
    critical_failure: str = ""       # "natural 1", "96-100", "all ones"
    damage_default: str = "1d6"      # default damage die


class InitiativeSystem(BaseModel):
    """How turn order is determined in combat."""
    method: str = "group_d6"         # "group_d6", "individual_d20",
                                     # "individual_d10", "dex_order",
                                     # "draw_cards", "no_initiative",
                                     # "individual_d6"
    dice: str = "1d6"
    modifier_attribute: str = ""     # "DEX" if added to roll
    reroll_each_round: bool = True


class MoraleSystem(BaseModel):
    """NPC morale mechanics.  None for systems without morale."""
    dice: str = "2d6"
    holds_on: str = "roll <= morale_score"  # human-readable condition
    default_score: int = 7
    check_triggers: list[str] = Field(default_factory=lambda: [
        "first ally killed", "half the group down"
    ])


class CombatSystem(BaseModel):
    """Complete combat resolution mechanics."""
    attack: AttackResolution
    initiative: InitiativeSystem = Field(default_factory=InitiativeSystem)
    morale: MoraleSystem | None = None
    rounds_description: str = "10 seconds"
    ranged_combat_notes: str = ""
    special_rules: list[str] = Field(default_factory=list)


# ── Health & Defense ────────────────────────────────────────

class HitPointConfig(BaseModel):
    """Configuration for HP-based health systems."""
    base_die: str = "1d8"            # per-level hit die (may be overridden by class)
    modifier_attribute: str = "CON"  # ability that modifies HP
    minimum_hp: int = 1


class HealthSystem(BaseModel):
    """How health/damage/death work."""
    model: str = "hit_points"        # "hit_points", "conditions", "stress_tracks",
                                     # "harm_clock", "wound_levels"
    hit_points: HitPointConfig | None = None
    # For condition-based systems (Forbidden Lands, etc.)
    conditions: list[str] = Field(default_factory=list)
    death_at: str = "0 HP"           # "0 HP", "4th condition", "harm clock full"
    healing: str = ""                # rules text
    death_rules: str = ""            # what happens at 0 / death threshold


class DefenseSystem(BaseModel):
    """How armor/defense works."""
    model: str = "descending_ac"     # "descending_ac", "ascending_ac",
                                     # "armor_value", "dodge_roll",
                                     # "parry_dice", "none"
    base_value: int = 9              # unarmored value (9 descending, 10 ascending)
    better_direction: str = "lower"  # "lower" or "higher"
    modifier_attribute: str = ""     # "DEX" if it modifies defense
    armor_examples: dict[str, int] = Field(default_factory=dict)


# ── Saves ───────────────────────────────────────────────────

class SaveCategory(BaseModel):
    """A saving throw or resistance category."""
    name: str                        # "Death/Poison", "Fortitude", "POW"
    default_target: int = 15
    roll_method: str = "d20_roll_over"  # "d20_roll_over", "percentile_under",
                                        # "2d6_plus_stat", "attribute_roll"


class SaveSystem(BaseModel):
    """Saving throw / resistance mechanics."""
    categories: list[SaveCategory] = Field(default_factory=list)
    per_class: bool = True           # True if each class has different save values
    roll_dice: str = "1d20"          # what to roll for saves


# ── Magic ───────────────────────────────────────────────────

class SpellListEntry(BaseModel):
    """A spell or power available in the system."""
    name: str
    level: int = 1
    type: str = ""                   # "arcane", "divine", "psychic"
    description: str = ""
    character_types: list[str] = Field(default_factory=list)  # which types can use it


class MagicSystem(BaseModel):
    """Spellcasting / powers mechanics."""
    model: str = "memorize"          # "memorize", "prepare", "spontaneous",
                                     # "mana_points", "power_points", "none"
    spell_lists: list[SpellListEntry] = Field(default_factory=list)
    recovery: str = "full_rest"      # "full_rest", "short_rest", "per_scene"
    notes: str = ""                  # extra rules text


# ── Equipment ───────────────────────────────────────────────

class WeaponDefinition(BaseModel):
    """A weapon available in the system."""
    name: str
    damage: str = "1d6"
    cost: str = ""                   # "10 gp", "100 credits"
    weight: str = ""                 # "60 coins", "1 kg"
    properties: list[str] = Field(default_factory=list)  # "two-handed", "ranged"
    range: str = ""                  # "short: 20', medium: 40', long: 60'"


class ArmorDefinition(BaseModel):
    """An armor type available in the system."""
    name: str
    defense_value: int = 7           # AC, armor rating, etc.
    cost: str = ""
    weight: str = ""
    properties: list[str] = Field(default_factory=list)


class EquipmentDefinitions(BaseModel):
    """Equipment catalog for the system."""
    weapons: list[WeaponDefinition] = Field(default_factory=list)
    armor: list[ArmorDefinition] = Field(default_factory=list)
    currency_unit: str = "gp"        # "gp", "credits", "silver", "dollars"
    currency_types: list[str] = Field(default_factory=lambda: ["gp"])
    starting_wealth: str = "3d6 * 10 gp"
    encumbrance_unit: str = "coins"  # "coins", "kg", "slots", "items"
    encumbrance_thresholds: dict[str, str] = Field(default_factory=dict)


# ── Special Mechanics ───────────────────────────────────────

class SpecialMechanic(BaseModel):
    """Catch-all for unique system mechanics (sanity, luck, push rolls, etc.)."""
    name: str                        # "Sanity", "Luck", "Push Rolls", "Willpower"
    description: str = ""
    mechanic_type: str = "resource"  # "resource", "roll_modifier", "condition_track",
                                     # "meta_currency", "subsystem"
    starting_value: str = ""         # "SAN * 5", "3d6 * 5", "equal to POW"
    linked_attribute: str = ""       # "POW", "CHA"
    resolution: str = ""             # how checks involving this work
    depletion_effect: str = ""       # what happens when it runs out
    recovery: str = ""               # how to restore it


# ── Dice Conventions ────────────────────────────────────────

class DiceConventions(BaseModel):
    """System-wide dice usage patterns."""
    primary_dice: str = "d20"        # "d20", "d100", "2d6", "d6_pool"
    stat_generation: str = "3d6"     # "3d6", "2d6+6", "4d6_drop_lowest", "point_buy"
    ability_check_method: str = "d20_roll_under"  # how raw attribute checks work
    common_notation: str = ""        # notes on dice conventions


# ── Random Tables ───────────────────────────────────────────

class MonsterEntry(BaseModel):
    """A monster/enemy for encounter tables."""
    name: str
    hp: int = 4
    defense: int = 7                 # AC or equivalent
    attack_value: int = 19           # THAC0, attack bonus, or skill
    damage: str = "1d6"
    morale: int = 7
    special: str = ""
    count_dice: str = "1d4"          # how many appear


class TreasureTable(BaseModel):
    """Loot table configuration."""
    quality: str = "average"         # "poor", "average", "good", "rich", "hoard"
    coins: dict[str, str] = Field(default_factory=dict)  # {"gp": "2d6", "sp": "3d8"}
    gems_chance: float = 0.0
    gems_value: str = ""
    magic_items: list[str] = Field(default_factory=list)


class RandomTables(BaseModel):
    """Encounter and treasure tables for the system."""
    wandering_monsters: dict[str, list[MonsterEntry]] = Field(default_factory=dict)
    treasure_tables: list[TreasureTable] = Field(default_factory=list)
    trap_types: list[dict[str, str]] = Field(default_factory=list)


# ── Exploration ─────────────────────────────────────────────

class ExplorationRules(BaseModel):
    """Dungeon/wilderness exploration mechanics."""
    turn_length: str = "10 minutes"
    wandering_monster_frequency: str = "every 2 turns"
    wandering_monster_chance: str = "1-in-6"
    light_sources: dict[str, str] = Field(default_factory=dict)  # {"torch": "6 turns"}
    search_mechanic: str = ""        # "1-in-6 (elves 2-in-6)"
    door_mechanic: str = ""          # "d6, 1-2 opens"
    listen_mechanic: str = ""        # "1-in-6 (demihumans 2-in-6)"
    rest_rules: str = ""
    movement_rates: dict[str, str] = Field(default_factory=dict)
    notes: str = ""


# ── Reaction / Social ──────────────────────────────────────

class ReactionTable(BaseModel):
    """NPC reaction roll table."""
    dice: str = "2d6"
    modifier_attribute: str = "CHA"
    results: dict[str, str] = Field(default_factory=dict)
    # e.g. {"2-3": "Hostile, attacks", "4-5": "Unfriendly", ...}


# ── Top-Level Rule System ──────────────────────────────────

class RuleSystem(BaseModel):
    """Complete mechanical definition of a tabletop RPG system.

    This is the top-level model that the loader, prompt builder,
    tool builder, and character factory all consume.
    """
    id: str                          # "ose", "coc7e", "traveller", "forbidden-lands"
    name: str                        # "Old-School Essentials"
    version: str = ""                # "Classic Fantasy 1.3"
    genre: str = ""                  # "fantasy", "horror", "sci-fi"

    # Core mechanics
    attributes: AttributeSystem
    skills: SkillSystem | None = None
    character_types: CharacterTypeSystem | None = None
    combat: CombatSystem
    health: HealthSystem = Field(default_factory=HealthSystem)
    defense: DefenseSystem = Field(default_factory=DefenseSystem)
    saves: SaveSystem | None = None
    magic: MagicSystem | None = None
    equipment: EquipmentDefinitions | None = None
    special_mechanics: list[SpecialMechanic] = Field(default_factory=list)

    # Dice conventions
    dice_conventions: DiceConventions = Field(default_factory=DiceConventions)

    # Exploration (optional — not all systems have structured exploration)
    exploration: ExplorationRules | None = None

    # Reaction / social
    reaction_table: ReactionTable | None = None

    # Random tables (optional — can also come from separate YAML)
    tables: RandomTables | None = None

    # Prompt generation metadata
    dm_title: str = "Game Master"    # "DM", "Keeper", "Referee", "MC"
    player_term: str = "player"      # "player", "investigator", "traveller"
    tone: str = ""                   # "gritty and deadly", "cinematic", "narrative-first"
    gm_principles: list[str] = Field(default_factory=list)

    # ── Helper Methods ──────────────────────────────────────

    def get_attribute_def(self, name: str) -> AttributeDefinition | None:
        """Find an attribute definition by name or abbreviation (case-insensitive)."""
        name_lower = name.lower()
        for attr in self.attributes.attributes:
            if attr.name.lower() == name_lower or attr.abbreviation.lower() == name_lower:
                return attr
        return None

    def get_character_type(self, name: str) -> CharacterTypeDefinition | None:
        """Find a character type by name (case-insensitive)."""
        if not self.character_types:
            return None
        name_lower = name.lower()
        for ct in self.character_types.types:
            if ct.name.lower() == name_lower:
                return ct
        return None

    def lookup_modifier(self, attribute_name: str, score: int) -> int:
        """Look up the modifier for an attribute score using the modifier table."""
        attr_def = self.get_attribute_def(attribute_name)
        if not attr_def or not attr_def.modifier_table:
            return 0
        return _resolve_modifier(attr_def.modifier_table, score)

    def has_mechanic(self, name: str) -> bool:
        """Check if a special mechanic exists by name (case-insensitive)."""
        name_lower = name.lower()
        return any(m.name.lower() == name_lower for m in self.special_mechanics)

    def get_mechanic(self, name: str) -> SpecialMechanic | None:
        """Get a special mechanic by name."""
        name_lower = name.lower()
        for m in self.special_mechanics:
            if m.name.lower() == name_lower:
                return m
        return None

    @property
    def attribute_names(self) -> list[str]:
        return [a.abbreviation for a in self.attributes.attributes]

    @property
    def has_skills(self) -> bool:
        return self.skills is not None and len(self.skills.skills) > 0

    @property
    def has_classes(self) -> bool:
        return (self.character_types is not None
                and not self.character_types.optional
                and len(self.character_types.types) > 0)


def _resolve_modifier(table: dict[str, int], score: int) -> int:
    """Resolve a modifier from a range-keyed table.

    Keys can be single values ("3") or ranges ("4-5", "6-8").
    """
    for key, mod in table.items():
        if "-" in key:
            parts = key.split("-", 1)
            try:
                low, high = int(parts[0]), int(parts[1])
                if low <= score <= high:
                    return mod
            except ValueError:
                continue
        else:
            try:
                if score == int(key):
                    return mod
            except ValueError:
                continue
    return 0
