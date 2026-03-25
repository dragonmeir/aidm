"""Game state tracking."""

from pydantic import BaseModel, Field
from .character import Character
from .combat import CombatState


class GameState(BaseModel):
    """Tracks the current state of the game session."""

    session_name: str = "New Adventure"
    turn_count: int = 0

    # Party
    players: list[Character] = Field(default_factory=list)

    # Location
    current_location: str = "Unknown"
    location_description: str = ""
    visited_locations: list[str] = Field(default_factory=list)

    # NPCs
    active_npcs: list[str] = Field(default_factory=list)

    # Combat
    in_combat: bool = False

    # Conversation history (kept trimmed for context window)
    history: list[dict[str, str]] = Field(default_factory=list)
    max_history: int = 50

    # Module/adventure context
    active_module: str = ""

    # Misc
    notes: list[str] = Field(default_factory=list)
    time_of_day: str = "morning"
    dungeon_level: int = 0

    def add_message(self, role: str, content: str) -> None:
        """Add a message to history, trimming if needed."""
        self.history.append({"role": role, "content": content})
        if len(self.history) > self.max_history:
            # Keep the first 5 messages (setup context) and the last max_history - 5
            keep_start = self.history[:5]
            keep_end = self.history[-(self.max_history - 5):]
            self.history = keep_start + keep_end

    def get_party_summary(self) -> str:
        """Get a summary of all party members."""
        if not self.players:
            return "No party members."
        return "\n".join(p.summary() for p in self.players)

    def get_state_summary(self) -> str:
        """Get a compact state summary for the DM context."""
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

        parts.append("\nParty:")
        parts.append(self.get_party_summary())

        return "\n".join(parts)
