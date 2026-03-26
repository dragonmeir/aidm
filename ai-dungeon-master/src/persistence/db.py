"""SQLite persistence for game sessions and characters."""

import json
import os
import sqlite3
from datetime import datetime

from ..game.state import GameState
from ..game.character import Character
from ..game.generic_character import GenericCharacter


class GameDatabase:
    """Save and load game sessions and characters."""

    def __init__(self, db_path: str = "data/sessions/aidm.db"):
        os.makedirs(os.path.dirname(db_path), exist_ok=True)
        self.db_path = db_path
        self._init_db()

    def _init_db(self) -> None:
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS sessions (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    name TEXT NOT NULL,
                    game_state TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                )
            """)
            conn.execute("""
                CREATE TABLE IF NOT EXISTS characters (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    name TEXT NOT NULL,
                    player_name TEXT NOT NULL,
                    character_data TEXT NOT NULL,
                    created_at TEXT NOT NULL
                )
            """)
            conn.commit()

    def save_session(self, game_state: GameState, session_id: int | None = None) -> int:
        """Save or update a game session. Returns session ID."""
        now = datetime.now().isoformat()
        state_json = game_state.model_dump_json()

        with sqlite3.connect(self.db_path) as conn:
            if session_id:
                conn.execute(
                    "UPDATE sessions SET game_state = ?, updated_at = ?, name = ? WHERE id = ?",
                    (state_json, now, game_state.session_name, session_id),
                )
                return session_id
            else:
                cursor = conn.execute(
                    "INSERT INTO sessions (name, game_state, created_at, updated_at) VALUES (?, ?, ?, ?)",
                    (game_state.session_name, state_json, now, now),
                )
                return cursor.lastrowid

    def load_session(self, session_id: int) -> GameState | None:
        """Load a game session by ID.

        Auto-migrates legacy Character objects to GenericCharacter format.
        """
        with sqlite3.connect(self.db_path) as conn:
            row = conn.execute(
                "SELECT game_state FROM sessions WHERE id = ?", (session_id,)
            ).fetchone()
            if not row:
                return None

            state = GameState.model_validate_json(row[0])

            # Migrate legacy Character dicts to GenericCharacter
            migrated_players = []
            for p in state.players:
                if isinstance(p, dict):
                    if "char_class" in p and "system_id" not in p:
                        # Legacy OSE Character — migrate
                        migrated_players.append(_migrate_ose_character(p))
                    elif "system_id" in p:
                        migrated_players.append(GenericCharacter.model_validate(p))
                    else:
                        migrated_players.append(p)
                elif hasattr(p, "system_id"):
                    migrated_players.append(p)
                else:
                    migrated_players.append(p)
            state.players = migrated_players

            # Ensure system_id is set
            if not state.system_id:
                state.system_id = "ose"

            return state

    def list_sessions(self) -> list[dict]:
        """List all saved sessions."""
        with sqlite3.connect(self.db_path) as conn:
            rows = conn.execute(
                "SELECT id, name, created_at, updated_at FROM sessions ORDER BY updated_at DESC"
            ).fetchall()
            return [
                {"id": r[0], "name": r[1], "created_at": r[2], "updated_at": r[3]}
                for r in rows
            ]

    def delete_session(self, session_id: int) -> None:
        """Delete a saved session."""
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("DELETE FROM sessions WHERE id = ?", (session_id,))
            conn.commit()

    def save_character(self, character: Character) -> int:
        """Save a character to the roster."""
        now = datetime.now().isoformat()
        char_json = character.model_dump_json()
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.execute(
                "INSERT INTO characters (name, player_name, character_data, created_at) VALUES (?, ?, ?, ?)",
                (character.name, character.player_name, char_json, now),
            )
            return cursor.lastrowid

    def load_character(self, char_id: int) -> Character | None:
        """Load a character by ID."""
        with sqlite3.connect(self.db_path) as conn:
            row = conn.execute(
                "SELECT character_data FROM characters WHERE id = ?", (char_id,)
            ).fetchone()
            if row:
                return Character.model_validate_json(row[0])
        return None

    def list_characters(self) -> list[dict]:
        """List all saved characters."""
        with sqlite3.connect(self.db_path) as conn:
            rows = conn.execute(
                "SELECT id, name, player_name, created_at FROM characters ORDER BY name"
            ).fetchall()
            return [
                {"id": r[0], "name": r[1], "player_name": r[2], "created_at": r[3]}
                for r in rows
            ]


def _migrate_ose_character(data: dict) -> GenericCharacter:
    """Convert a legacy OSE Character dict to GenericCharacter."""
    return GenericCharacter(
        name=data.get("name", ""),
        player_name=data.get("player_name", ""),
        system_id="ose",
        attributes={
            "STR": data.get("strength", 10),
            "DEX": data.get("dexterity", 10),
            "CON": data.get("constitution", 10),
            "INT": data.get("intelligence", 10),
            "WIS": data.get("wisdom", 10),
            "CHA": data.get("charisma", 10),
        },
        character_type=data.get("char_class", "Fighter"),
        level=data.get("level", 1),
        xp=data.get("xp", 0),
        hp=data.get("hp", 1),
        max_hp=data.get("max_hp", 1),
        defense_value=data.get("ac", 9),
        defense_label="AC",
        attack_value=data.get("thac0", 19),
        attack_label="THAC0",
        saves={
            "Death/Poison": data.get("save_death", 14),
            "Wands": data.get("save_wands", 15),
            "Paralysis/Petrify": data.get("save_paralysis", 16),
            "Breath Attacks": data.get("save_breath", 17),
            "Spells/Rods/Staves": data.get("save_spells", 18),
        },
        inventory=data.get("inventory", []),
        weapons=data.get("weapons", []),
        armor=data.get("armor", ""),
        currency={"gp": data.get("gold", 0)},
        spells_known=data.get("spells_known", []),
        spells_memorized=data.get("spells_memorized", []),
        spell_slots=data.get("spell_slots", []),
        notes=data.get("notes", ""),
    )
