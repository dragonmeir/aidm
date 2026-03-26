"""System-agnostic character model.

Stores attributes, skills, saves, and resources as dynamic dictionaries
rather than hardcoded fields, so it works for any TTRPG system.
"""

from __future__ import annotations

from typing import Any
from pydantic import BaseModel, Field

from ..systems.schema import RuleSystem, _resolve_modifier


class GenericCharacter(BaseModel):
    """A character that works with any rule system."""

    name: str = ""
    player_name: str = ""
    system_id: str = ""

    # Dynamic attributes: {"STR": 14, "DEX": 10} or {"Agility": 4, "Wits": 3}
    attributes: dict[str, int] = Field(default_factory=dict)

    # Optional character type (class, playbook, career)
    character_type: str = ""         # "Fighter", "The Chosen", "Scout"
    level: int = 1
    xp: int = 0

    # Health — flexible
    hp: int | None = None
    max_hp: int | None = None
    conditions: list[str] = Field(default_factory=list)

    # Defense
    defense_value: int = 0           # AC, armor rating, dodge, whatever
    defense_label: str = "AC"        # display label

    # Skills: {"Climb": 40, "Persuade": 55} or {"Marksmanship": 3}
    skills: dict[str, int] = Field(default_factory=dict)

    # Saves: {"Death/Poison": 12, "Wands": 13} — dynamic keys
    saves: dict[str, int] = Field(default_factory=dict)

    # Combat stats (system-specific)
    attack_value: int | None = None  # THAC0, attack bonus, combat skill, etc.
    attack_label: str = "THAC0"      # display label

    # Equipment
    inventory: list[str] = Field(default_factory=list)
    weapons: list[str] = Field(default_factory=list)
    armor: str = ""
    currency: dict[str, int] = Field(default_factory=dict)  # {"gp": 120, "sp": 30}

    # Magic / powers
    spells_known: list[str] = Field(default_factory=list)
    spells_memorized: list[str] = Field(default_factory=list)
    spell_slots: list[int] = Field(default_factory=list)
    powers: dict[str, Any] = Field(default_factory=dict)

    # Special resources: {"Sanity": 55, "Luck": 60, "Willpower": 3}
    resources: dict[str, int] = Field(default_factory=dict)

    # Status
    notes: str = ""

    # ── Attribute Access ─────────────────────────────────────

    def get_attribute(self, name: str) -> int:
        """Get attribute value by name or abbreviation (case-insensitive)."""
        name_upper = name.upper()
        # Try exact match first
        if name_upper in self.attributes:
            return self.attributes[name_upper]
        # Try case-insensitive
        for k, v in self.attributes.items():
            if k.upper() == name_upper:
                return v
        return 0

    def get_modifier(self, attribute: str, system: RuleSystem | None = None) -> int:
        """Get the modifier for an attribute score.

        If no system is provided, returns 0 (can't look up modifier table).
        """
        score = self.get_attribute(attribute)
        if not system:
            return 0
        attr_def = system.get_attribute_def(attribute)
        if not attr_def or not attr_def.modifier_table:
            return 0
        return _resolve_modifier(attr_def.modifier_table, score)

    def get_save(self, save_name: str) -> int:
        """Get saving throw target by name (case-insensitive partial match)."""
        name_lower = save_name.lower()
        for k, v in self.saves.items():
            if name_lower in k.lower():
                return v
        return 15  # safe default

    def get_skill(self, skill_name: str) -> int:
        """Get skill value by name (case-insensitive partial match)."""
        name_lower = skill_name.lower()
        for k, v in self.skills.items():
            if name_lower in k.lower():
                return v
        return 0

    # ── Health ───────────────────────────────────────────────

    def is_alive(self) -> bool:
        if self.hp is not None:
            return self.hp > 0
        # Condition-based: alive unless a fatal condition is present
        return "Dead" not in self.conditions

    def take_damage(self, amount: int) -> int:
        """Apply damage, return actual damage taken."""
        if self.hp is None:
            return 0
        actual = min(amount, self.hp)
        self.hp -= actual
        return actual

    def heal(self, amount: int) -> int:
        """Heal HP up to max, return actual healing."""
        if self.hp is None or self.max_hp is None:
            return 0
        actual = min(amount, self.max_hp - self.hp)
        self.hp += actual
        return actual

    # ── Spells ───────────────────────────────────────────────

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
        """Full rest: restore spell slots."""
        if not self.spell_slots:
            return
        total_slots = sum(self.spell_slots)
        if spells:
            self.spells_memorized = spells[:total_slots]
        else:
            clean = [s.replace("[USED] ", "") for s in self.spells_memorized]
            self.spells_memorized = clean[:total_slots]

    # ── Resources ────────────────────────────────────────────

    def get_resource(self, name: str) -> int:
        """Get a special resource value (sanity, luck, etc.)."""
        name_lower = name.lower()
        for k, v in self.resources.items():
            if k.lower() == name_lower:
                return v
        return 0

    def modify_resource(self, name: str, delta: int) -> int:
        """Modify a resource by delta, return new value."""
        for k in self.resources:
            if k.lower() == name.lower():
                self.resources[k] = max(0, self.resources[k] + delta)
                return self.resources[k]
        return 0

    # ── Display ──────────────────────────────────────────────

    def summary(self) -> str:
        """Short character summary string."""
        parts = [f"{self.name}"]
        if self.character_type:
            parts.append(f"Level {self.level} {self.character_type}")
        if self.hp is not None:
            parts.append(f"HP: {self.hp}/{self.max_hp}")
        if self.defense_value:
            parts.append(f"{self.defense_label}: {self.defense_value}")
        attrs = " ".join(f"{k}:{v}" for k, v in self.attributes.items())
        if attrs:
            parts.append(attrs)
        return " | ".join(parts)
