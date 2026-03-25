"""Rich-based terminal UI for the AI Dungeon Master."""

from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from rich.text import Text
from rich.theme import Theme
from rich.markdown import Markdown

from ..game.character import Character, CharacterClass, ABILITY_NAMES, ability_modifier
from ..game.dice import DiceResult

# Custom theme for the game
GAME_THEME = Theme({
    "dm": "bold yellow",
    "player1": "bold cyan",
    "player2": "bold magenta",
    "combat": "bold red",
    "system": "dim white",
    "success": "bold green",
    "warning": "bold yellow",
    "danger": "bold red",
    "loot": "bold yellow",
    "title": "bold white on blue",
})

console = Console(theme=GAME_THEME)


def print_banner() -> None:
    """Display the game title banner."""
    banner = """
     _    ___   ____                                    __  __           _
    / \\  |_ _| |  _ \\ _   _ _ __   __ _  ___  ___  _ _|  \\/  | __ _ __| |_ ___ _ _
   / _ \\  | |  | | | | | | | '_ \\ / _` |/ _ \\/ _ \\| ' \\ |\\/| |/ _` (_-<  _/ -_) '_|
  / ___ \\ | |  | |_| | |_| | | | | (_| |  __/ (_) | || |  | | \\__,_/__/\\__\\___|_|
 /_/   \\_\\___| |____/ \\__,_|_| |_|\\__, |\\___|\\___/|_||_|  |_|
                                   |___/             Old-School Essentials Edition
"""
    console.print(banner, style="bold cyan")
    console.print("  Type [bold]/help[/bold] for commands. Type anything else to play.\n")


def print_dm(text: str) -> None:
    """Print DM narration in a styled panel."""
    console.print(Panel(
        Text(text),
        title="[dm]Dungeon Master[/dm]",
        border_style="yellow",
        padding=(1, 2),
    ))


def print_dm_stream_start() -> None:
    """Start a streaming DM response."""
    console.print("\n[dm]Dungeon Master:[/dm]")
    console.print("─" * 60, style="yellow")


def print_dm_stream_chunk(chunk: str) -> None:
    """Print a chunk of streaming DM response."""
    console.print(chunk, end="", highlight=False)


def print_dm_stream_end() -> None:
    """End a streaming DM response."""
    console.print()
    console.print("─" * 60, style="yellow")
    console.print()


def print_system(text: str) -> None:
    """Print a system message."""
    console.print(f"[system]>> {text}[/system]")


def print_combat(text: str) -> None:
    """Print combat information."""
    console.print(Panel(text, title="[combat]Combat[/combat]", border_style="red"))


def print_dice_result(result: DiceResult) -> None:
    """Print a dice roll result."""
    console.print(f"  [success]{result}[/success]")


def get_player_input(player_name: str = "", player_num: int = 0) -> str:
    """Get input from a player."""
    if player_name:
        style = "player1" if player_num <= 1 else "player2"
        prompt = f"[{style}]{player_name}>[/{style}] "
    else:
        prompt = "[bold]> [/bold]"
    try:
        return console.input(prompt).strip()
    except (EOFError, KeyboardInterrupt):
        return "/quit"


def print_character_sheet(char: Character) -> None:
    """Display a full character sheet."""
    table = Table(title=f"{char.name} - {char.char_class.value} Level {char.level}",
                  border_style="cyan")

    # Ability scores
    table.add_column("Ability", style="bold")
    table.add_column("Score", justify="center")
    table.add_column("Modifier", justify="center")

    abilities = {
        "STR": char.strength, "DEX": char.dexterity, "CON": char.constitution,
        "INT": char.intelligence, "WIS": char.wisdom, "CHA": char.charisma,
    }
    for name, score in abilities.items():
        mod = ability_modifier(score)
        mod_str = f"+{mod}" if mod > 0 else str(mod)
        table.add_row(name, str(score), mod_str)

    console.print(table)

    # Stats
    stats = Table.grid(padding=(0, 3))
    stats.add_row(
        f"[bold]HP:[/bold] {char.hp}/{char.max_hp}",
        f"[bold]AC:[/bold] {char.ac}",
        f"[bold]THAC0:[/bold] {char.thac0}",
        f"[bold]XP:[/bold] {char.xp}",
        f"[bold]Gold:[/bold] {char.gold}",
    )
    console.print(stats)

    # Saves
    saves = Table(title="Saving Throws", border_style="dim")
    saves.add_column("Death", justify="center")
    saves.add_column("Wands", justify="center")
    saves.add_column("Paralysis", justify="center")
    saves.add_column("Breath", justify="center")
    saves.add_column("Spells", justify="center")
    saves.add_row(
        str(char.save_death), str(char.save_wands), str(char.save_paralysis),
        str(char.save_breath), str(char.save_spells),
    )
    console.print(saves)

    # Inventory
    if char.inventory or char.weapons:
        console.print("\n[bold]Equipment:[/bold]")
        if char.armor != "None":
            console.print(f"  Armor: {char.armor}")
        for w in char.weapons:
            console.print(f"  Weapon: {w}")
        for item in char.inventory:
            console.print(f"  - {item}")
    console.print()


def _roll_and_display_stats() -> list[int]:
    """Roll 3d6-in-order and display the results. Returns the stat array."""
    from ..game.dice import roll_stats
    stats = roll_stats()
    console.print("\n[bold]Rolling 3d6 for abilities (in order):[/bold]")
    for name, score in zip(ABILITY_NAMES, stats):
        mod = ability_modifier(score)
        mod_str = f"+{mod}" if mod > 0 else str(mod)
        console.print(f"  {name}: [bold]{score}[/bold] ({mod_str})")
    return stats


def character_creation_wizard(player_name: str) -> Character:
    """Interactive character creation with reroll support."""
    console.print(Panel(
        f"Character Creation for [bold]{player_name}[/bold]",
        style="title",
    ))

    # Roll stats with reroll option
    stats = _roll_and_display_stats()

    while True:
        reroll_choice = console.input("\n[bold]Keep these stats? (y/n): [/bold]").strip().lower()
        if reroll_choice in ("y", "yes", ""):
            break
        stats = _roll_and_display_stats()

    # Choose class
    console.print("\n[bold]Available Classes:[/bold]")
    classes = list(CharacterClass)
    for i, cls in enumerate(classes, 1):
        console.print(f"  {i}. {cls.value}")

    while True:
        choice = console.input("\n[bold]Choose class (1-7): [/bold]").strip()
        try:
            idx = int(choice) - 1
            if 0 <= idx < len(classes):
                char_class = classes[idx]
                break
        except ValueError:
            pass
        console.print("[warning]Invalid choice. Try again.[/warning]")

    # Character name
    char_name = console.input("[bold]Character name: [/bold]").strip()
    if not char_name:
        char_name = f"{player_name}'s {char_class.value}"

    # Build character
    char = Character(
        name=char_name,
        player_name=player_name,
        char_class=char_class,
        strength=stats[0],
        dexterity=stats[1],
        constitution=stats[2],
        intelligence=stats[3],
        wisdom=stats[4],
        charisma=stats[5],
    )
    char.apply_class_data()
    char.roll_hit_points()
    from ..game.dice import roll as roll_dice
    char.gold = roll_dice("3d6").total * 10

    console.print(f"\n[success]Character created![/success]")
    print_character_sheet(char)

    return char


def show_help() -> None:
    """Display available commands."""
    table = Table(title="Commands", border_style="cyan")
    table.add_column("Command", style="bold")
    table.add_column("Description")

    commands = [
        ("/roll <dice>", "Roll dice (e.g., /roll 2d6+3, /roll d20)"),
        ("/character", "Show your character sheet"),
        ("/party", "Show all party members"),
        ("/inventory", "Show your inventory"),
        ("/save", "Save the current session"),
        ("/load", "Load a saved session"),
        ("/module <name>", "Set active adventure module (filters RAG search)"),
        ("/search <query>", "Search your RPG library for specific content"),
        ("/newchar", "Create a new character"),
        ("/reroll", "Replace your current character with a fresh roll"),
        ("/switch", "Switch active player"),
        ("/quit", "Exit the game"),
        ("/help", "Show this help"),
    ]
    for cmd, desc in commands:
        table.add_row(cmd, desc)

    console.print(table)


def show_session_list(sessions: list[dict]) -> None:
    """Display saved sessions."""
    if not sessions:
        print_system("No saved sessions found.")
        return

    table = Table(title="Saved Sessions", border_style="cyan")
    table.add_column("ID", justify="center")
    table.add_column("Name")
    table.add_column("Last Played")
    for s in sessions:
        table.add_row(str(s["id"]), s["name"], s["updated_at"][:16])
    console.print(table)
