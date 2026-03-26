"""Player command handling."""

from ..game.dice import roll, DiceResult
from ..game.state import GameState
from ..game.character import Character
from ..persistence.db import GameDatabase
from . import interface as ui


class CommandHandler:
    """Processes player slash commands."""

    def __init__(self, game_state: GameState, db: GameDatabase):
        self.game_state = game_state
        self.db = db
        self.session_id: int | None = None
        self.active_player_idx: int = 0

    @property
    def active_player(self) -> Character | None:
        if self.game_state.players:
            idx = self.active_player_idx % len(self.game_state.players)
            return self.game_state.players[idx]
        return None

    def handle(self, input_text: str) -> bool | None:
        """Handle a command. Returns True if handled, False to quit, None if not a command."""
        if not input_text.startswith("/"):
            return None

        parts = input_text.split(maxsplit=1)
        cmd = parts[0].lower()
        args = parts[1] if len(parts) > 1 else ""

        handlers = {
            "/roll": self._cmd_roll,
            "/r": self._cmd_roll,
            "/character": self._cmd_character,
            "/char": self._cmd_character,
            "/party": self._cmd_party,
            "/inventory": self._cmd_inventory,
            "/inv": self._cmd_inventory,
            "/save": self._cmd_save,
            "/load": self._cmd_load,
            "/module": self._cmd_module,
            "/search": self._cmd_search,
            "/newchar": self._cmd_newchar,
            "/reroll": self._cmd_reroll,
            "/switch": self._cmd_switch,
            "/log": self._cmd_log,
            "/light": self._cmd_light,
            "/help": self._cmd_help,
            "/quit": self._cmd_quit,
            "/exit": self._cmd_quit,
        }

        handler = handlers.get(cmd)
        if handler:
            return handler(args)

        ui.print_system(f"Unknown command: {cmd}. Type /help for commands.")
        return True

    def _cmd_roll(self, args: str) -> bool:
        if not args:
            args = "1d20"
        try:
            result = roll(args)
            ui.print_dice_result(result)
        except ValueError as e:
            ui.print_system(str(e))
        return True

    def _cmd_character(self, _args: str) -> bool:
        if self.active_player:
            ui.print_character_sheet(self.active_player)
        else:
            ui.print_system("No active character.")
        return True

    def _cmd_party(self, _args: str) -> bool:
        if not self.game_state.players:
            ui.print_system("No party members.")
        else:
            for p in self.game_state.players:
                ui.print_character_sheet(p)
        return True

    def _cmd_inventory(self, _args: str) -> bool:
        if not self.active_player:
            ui.print_system("No active character.")
            return True
        char = self.active_player
        ui.console.print(f"\n[bold]{char.name}'s Inventory:[/bold]")
        ui.console.print(f"  Gold: {char.gold} gp")
        if char.armor != "None":
            ui.console.print(f"  Armor: {char.armor}")
        for w in char.weapons:
            ui.console.print(f"  Weapon: {w}")
        for item in char.inventory:
            ui.console.print(f"  - {item}")
        if not char.inventory and not char.weapons:
            ui.console.print("  (empty)")
        ui.console.print()
        return True

    def _cmd_save(self, _args: str) -> bool:
        self.session_id = self.db.save_session(self.game_state, self.session_id)
        ui.print_system(f"Session saved! (ID: {self.session_id})")
        return True

    def _cmd_load(self, args: str) -> bool:
        if args:
            try:
                sid = int(args)
                loaded = self.db.load_session(sid)
                if loaded:
                    for field_name in loaded.model_fields:
                        setattr(self.game_state, field_name, getattr(loaded, field_name))
                    self.session_id = sid
                    ui.print_system(f"Loaded session: {self.game_state.session_name}")
                    return True
            except (ValueError, TypeError):
                pass

        sessions = self.db.list_sessions()
        ui.show_session_list(sessions)
        if sessions:
            choice = ui.console.input("[bold]Enter session ID to load (or press Enter to cancel): [/bold]").strip()
            if choice:
                return self._cmd_load(choice)
        return True

    def _cmd_module(self, args: str) -> bool:
        if args == "clear":
            self.game_state.active_module = ""
            ui.print_system("Module filter cleared.")
        elif args:
            self.game_state.active_module = args
            ui.print_system(f"Active module set to: {args}")
        else:
            if self.game_state.active_module:
                ui.print_system(f"Current module: {self.game_state.active_module}")
            else:
                ui.print_system("No active module. Use /module <name> to set one.")
        return True

    def _cmd_search(self, args: str) -> bool:
        return None  # Handled by main.py which has RAG access

    def _cmd_newchar(self, _args: str) -> bool:
        player_name = ui.console.input("[bold]Player name: [/bold]").strip()
        if player_name:
            char = ui.character_creation_wizard(player_name)
            self.game_state.players.append(char)
            self.db.save_character(char)
            ui.print_system(f"{char.name} joined the party!")
        return True

    def _cmd_reroll(self, _args: str) -> bool:
        if not self.active_player:
            ui.print_system("No active character to reroll.")
            return True

        old_name = self.active_player.name
        player_name = self.active_player.player_name
        ui.console.print(f"\n[warning]Rerolling {old_name}. This replaces your current character![/warning]")
        confirm = ui.console.input("[bold]Are you sure? (y/n): [/bold]").strip().lower()
        if confirm not in ("y", "yes"):
            ui.print_system("Reroll cancelled.")
            return True

        new_char = ui.character_creation_wizard(player_name)
        self.game_state.players[self.active_player_idx] = new_char
        self.db.save_character(new_char)
        ui.print_system(f"{old_name} has been replaced by {new_char.name}!")
        return True

    def _cmd_switch(self, _args: str) -> bool:
        if len(self.game_state.players) < 2:
            ui.print_system("Only one player in the party.")
            return True
        self.active_player_idx = (self.active_player_idx + 1) % len(self.game_state.players)
        ui.print_system(f"Switched to {self.active_player.name}")
        return True

    def _cmd_log(self, args: str) -> bool:
        """Show recent dice rolls and mechanical events."""
        count = 10
        if args:
            try:
                count = int(args)
            except ValueError:
                pass
        entries = self.game_state.roll_log[-count:]
        if not entries:
            ui.print_system("No rolls yet.")
            return True
        ui.console.print("\n[bold]Recent Rolls:[/bold]")
        for entry in entries:
            tool = entry.get("tool", "?")
            turn = entry.get("turn", "?")
            detail = {k: v for k, v in entry.items() if k not in ("tool", "turn")}
            ui.console.print(f"  Turn {turn} | {tool}: {detail}")
        ui.console.print()
        return True

    def _cmd_light(self, args: str) -> bool:
        """Manage light sources."""
        if not args:
            if self.game_state.light_sources:
                for ls in self.game_state.light_sources:
                    ui.console.print(f"  {ls.bearer}'s {ls.kind}: {ls.turns_remaining} turns remaining")
            else:
                ui.print_system("No active light sources.")
            return True

        parts = args.split()
        kind = parts[0].lower() if parts else "torch"
        bearer = self.active_player.name if self.active_player else "Party"
        if len(parts) > 1:
            bearer = parts[1]

        from ..game.state import LightSource
        if kind == "torch":
            ls = LightSource(kind="torch", turns_remaining=6, bearer=bearer)
        elif kind == "lantern":
            ls = LightSource(kind="lantern", turns_remaining=24, bearer=bearer)
        else:
            ui.print_system("Use: /light torch [name] or /light lantern [name]")
            return True

        self.game_state.light_sources.append(ls)
        ui.print_system(f"{bearer} lights a {kind} ({ls.turns_remaining} turns).")
        return True

    def _cmd_help(self, _args: str) -> bool:
        ui.show_help()
        return True

    def _cmd_quit(self, _args: str) -> bool:
        return False
