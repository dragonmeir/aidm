"""Game state tracking with resource and turn management."""

from __future__ import annotations

from typing import Any
from pydantic import BaseModel, Field


class LightSource(BaseModel):
    kind: str = "torch"
    turns_remaining: int = 6
    bearer: str = ""


class Retainer(BaseModel):
    """A hired NPC retainer."""
    name: str
    char_class: str = "Fighter"
    level: int = 1
    hp: int = 4
    max_hp: int = 4
    ac: int = 7
    morale: int = 7
    loyalty: int = 7  # 2d6+CHA mod, checked like morale
    wage_gp_per_day: int = 1
    weapons: list[str] = Field(default_factory=list)
    armor: str = "Leather"
    inventory: list[str] = Field(default_factory=list)
    notes: str = ""

    def is_alive(self) -> bool:
        return self.hp > 0

    def summary(self) -> str:
        return f"{self.name} ({self.char_class} L{self.level}) HP:{self.hp}/{self.max_hp} AC:{self.ac} Loyalty:{self.loyalty}"


class TrackedNPC(BaseModel):
    """An NPC the party has encountered."""
    name: str
    location: str = ""
    disposition: str = "neutral"  # hostile, unfriendly, neutral, indifferent, friendly
    reaction_roll: int = 0
    description: str = ""
    alive: bool = True
    notes: str = ""
    met_on_turn: int = 0


class JournalEntry(BaseModel):
    """A logged game event."""
    turn: int = 0
    event_type: str = ""  # combat, treasure, npc, exploration, death, rest, level_up
    text: str = ""


class GameState(BaseModel):
    """Tracks the current state of the game session."""

    session_name: str = "New Adventure"
    turn_count: int = 0

    # Rule system
    system_id: str = "ose"

    # Party — uses GenericCharacter for universal system support.
    # For backward compat, also accepts legacy Character objects
    # (the list stores them as dicts via Pydantic serialization).
    players: list[Any] = Field(default_factory=list)

    # Retainers
    retainers: list[Retainer] = Field(default_factory=list)

    # Location
    current_location: str = "Unknown"
    location_description: str = ""
    visited_locations: list[str] = Field(default_factory=list)

    # NPCs
    active_npcs: list[str] = Field(default_factory=list)
    npc_tracker: list[TrackedNPC] = Field(default_factory=list)

    # Combat
    in_combat: bool = False

    # Conversation history
    history: list[dict[str, str]] = Field(default_factory=list)
    max_history: int = 50

    # Module/adventure context
    active_module: str = ""        # display name (for prompt/narration)
    module_key: str = ""           # library entry key (for lookups)

    # Dungeon tracking
    dungeon_level: int = 0
    time_of_day: str = "morning"

    # Resource tracking
    light_sources: list[LightSource] = Field(default_factory=list)
    party_rations: int = 0
    turns_since_rest: int = 0
    turns_since_wandering_check: int = 0

    # Mechanical log
    roll_log: list[dict] = Field(default_factory=list)

    # Journal
    journal: list[JournalEntry] = Field(default_factory=list)

    # Notes
    notes: list[str] = Field(default_factory=list)

    # ── Messages ────────────────────────────────────────────

    def add_message(self, role: str, content: str) -> None:
        self.history.append({"role": role, "content": content})
        if len(self.history) > self.max_history:
            keep_start = self.history[:5]
            keep_end = self.history[-(self.max_history - 5):]
            self.history = keep_start + keep_end

    def log_roll(self, tool_name: str, data: dict) -> None:
        self.roll_log.append({"turn": self.turn_count, "tool": tool_name, **data})
        if len(self.roll_log) > 200:
            self.roll_log = self.roll_log[-200:]

    # ── Journal ─────────────────────────────────────────────

    def log_event(self, event_type: str, text: str) -> None:
        self.journal.append(JournalEntry(turn=self.turn_count, event_type=event_type, text=text))
        if len(self.journal) > 500:
            self.journal = self.journal[-500:]

    # ── NPC Tracking ────────────────────────────────────────

    def track_npc(self, name: str, disposition: str = "neutral", location: str = "",
                  reaction_roll: int = 0, description: str = "") -> TrackedNPC:
        # Update existing or add new
        for npc in self.npc_tracker:
            if npc.name.lower() == name.lower():
                if disposition:
                    npc.disposition = disposition
                if location:
                    npc.location = location
                if description:
                    npc.description = description
                if reaction_roll:
                    npc.reaction_roll = reaction_roll
                return npc
        npc = TrackedNPC(
            name=name, location=location or self.current_location,
            disposition=disposition, reaction_roll=reaction_roll,
            description=description, met_on_turn=self.turn_count,
        )
        self.npc_tracker.append(npc)
        return npc

    # ── Retainers ───────────────────────────────────────────

    def hire_retainer(self, name: str, char_class: str = "Fighter", level: int = 1,
                      hp: int = 4, ac: int = 7, loyalty: int = 7,
                      wage: int = 1, weapons: list[str] = None,
                      armor: str = "Leather") -> Retainer:
        r = Retainer(
            name=name, char_class=char_class, level=level,
            hp=hp, max_hp=hp, ac=ac, loyalty=loyalty,
            wage_gp_per_day=wage, weapons=weapons or ["Sword"],
            armor=armor,
        )
        self.retainers.append(r)
        self.log_event("retainer", f"Hired {r.summary()}")
        return r

    def max_retainers(self) -> int:
        """Max retainers based on highest CHA in party."""
        if not self.players:
            return 4
        # Support both legacy Character (has .charisma) and GenericCharacter (has .attributes)
        best_cha = 10
        for p in self.players:
            if hasattr(p, "charisma"):
                cha = p.charisma
            elif hasattr(p, "get_attribute"):
                cha = p.get_attribute("CHA")
            elif hasattr(p, "attributes"):
                cha = p.attributes.get("CHA", 10)
            else:
                cha = 10
            best_cha = max(best_cha, cha)
        if best_cha <= 3:
            return 1
        elif best_cha <= 8:
            return 3
        elif best_cha <= 12:
            return 4
        elif best_cha <= 17:
            return 5
        else:
            return 7

    # ── Turns ───────────────────────────────────────────────

    def advance_turn(self) -> list[str]:
        self.turn_count += 1
        self.turns_since_rest += 1
        self.turns_since_wandering_check += 1
        events = []

        # Burn light sources
        expired = []
        for ls in self.light_sources:
            ls.turns_remaining -= 1
            if ls.turns_remaining <= 1:
                events.append(f"{ls.bearer}'s {ls.kind} is flickering — about to go out!")
            if ls.turns_remaining <= 0:
                expired.append(ls)
                events.append(f"{ls.bearer}'s {ls.kind} goes out!")
        for ls in expired:
            self.light_sources.remove(ls)

        # Rest warning
        if self.turns_since_rest >= 5 and self.turns_since_rest % 5 == 0:
            events.append(f"The party has been active for {self.turns_since_rest} turns without rest.")

        return events

    def needs_wandering_check(self, interval: int = 2) -> bool:
        return self.turns_since_wandering_check >= interval

    def reset_wandering_timer(self) -> None:
        self.turns_since_wandering_check = 0

    # ── Summaries ───────────────────────────────────────────

    def get_party_summary(self) -> str:
        if not self.players:
            return "No party members."
        lines = [p.summary() for p in self.players]
        if self.retainers:
            lines.append("Retainers:")
            lines.extend(f"  {r.summary()}" for r in self.retainers if r.is_alive())
        return "\n".join(lines)

    def get_state_summary(self) -> str:
        parts = [
            f"Location: {self.current_location}",
            f"Time: {self.time_of_day}",
            f"Turn: {self.turn_count}",
        ]
        if self.dungeon_level > 0:
            parts.append(f"Dungeon Level: {self.dungeon_level}")
        if self.active_npcs:
            parts.append(f"Present NPCs: {', '.join(self.active_npcs)}")
        if self.active_module:
            parts.append(f"Adventure: {self.active_module}")
        if self.in_combat:
            parts.append("STATUS: IN COMBAT")
        if self.light_sources:
            light_parts = [f"{ls.bearer}'s {ls.kind} ({ls.turns_remaining} turns)" for ls in self.light_sources]
            parts.append(f"Light: {', '.join(light_parts)}")
        elif self.dungeon_level > 0:
            parts.append("Light: NONE (darkness!)")
        if self.turns_since_rest > 0:
            parts.append(f"Turns without rest: {self.turns_since_rest}")
        if self.retainers:
            alive = [r for r in self.retainers if r.is_alive()]
            parts.append(f"Retainers: {len(alive)} ({', '.join(r.name for r in alive)})")

        parts.append("\nParty:")
        parts.append(self.get_party_summary())

        # Spell slots summary for casters
        for p in self.players:
            if p.spells_memorized:
                used = [s for s in p.spells_memorized if s.startswith("[USED] ")]
                avail = [s for s in p.spells_memorized if not s.startswith("[USED] ")]
                parts.append(f"{p.name} spells: {len(avail)} available, {len(used)} used")

        return "\n".join(parts)
