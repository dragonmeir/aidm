"""AI Dungeon Master - Main entry point."""

import sys
import os
import yaml
from pathlib import Path

from rich.console import Console

from .cli import interface as ui
from .cli.commands import CommandHandler
from .game.state import GameState
from .game.character import Character
from .dm.engine import DMEngine
from .rag.store import VectorStore
from .rag.ingest import ingest_pdfs
from .rag.query import RAGQuery
from .persistence.db import GameDatabase

console = Console()

# Resolve project root relative to this file
PROJECT_ROOT = Path(__file__).resolve().parent.parent


def load_config() -> dict:
    """Load configuration from config.yaml."""
    config_path = PROJECT_ROOT / "config.yaml"
    if config_path.exists():
        with open(config_path) as f:
            return yaml.safe_load(f)
    return {}


def cmd_ingest(config: dict) -> None:
    """Ingest PDFs into the vector store."""
    rag_config = config.get("rag", {})
    chunk_size = rag_config.get("chunk_size", 500)
    chunk_overlap = rag_config.get("chunk_overlap", 50)
    embedding_model = rag_config.get("embedding_model", "all-MiniLM-L6-v2")
    include_folders = rag_config.get("include_folders", None)
    include_files = rag_config.get("include_files", None)

    # Support both pdf_root (single) and pdf_roots (multiple)
    pdf_roots = rag_config.get("pdf_roots", None)
    if not pdf_roots:
        pdf_roots = [rag_config.get("pdf_root", "E:/Tabletop rpg")]

    store = VectorStore(str(PROJECT_ROOT / "data" / "chroma_db"))
    ingest_pdfs(
        pdf_roots=pdf_roots,
        store=store,
        embedding_model_name=embedding_model,
        chunk_size=chunk_size,
        chunk_overlap=chunk_overlap,
        include_folders=include_folders,
        include_files=include_files,
    )


def cmd_play(config: dict) -> None:
    """Start a game session."""
    ui.print_banner()

    # Load config values
    ollama_config = config.get("ollama", {})
    rag_config = config.get("rag", {})
    persist_config = config.get("persistence", {})

    # Initialize components
    db_path = str(PROJECT_ROOT / persist_config.get("db_path", "data/sessions/aidm.db"))
    db = GameDatabase(db_path)

    # Try to set up RAG
    rag_query = None
    store = VectorStore(str(PROJECT_ROOT / "data" / "chroma_db"))
    if store.count() > 0:
        embedding_model = rag_config.get("embedding_model", "all-MiniLM-L6-v2")
        rag_query = RAGQuery(store, embedding_model)
        ui.print_system(f"RPG library loaded: {store.count()} indexed chunks")
    else:
        ui.print_system("No indexed PDFs. Run 'aidm ingest' to index your collection.")
        ui.print_system("Playing without reference material.\n")

    # Initialize DM engine
    dm = DMEngine(
        model=ollama_config.get("model", "mistral"),
        base_url=ollama_config.get("base_url", "http://localhost:11434"),
        temperature=ollama_config.get("temperature", 0.8),
        context_length=ollama_config.get("context_length", 8192),
        rag_query=rag_query,
        top_k=rag_config.get("top_k", 5),
    )

    # Check Ollama connection
    ui.print_system("Connecting to Ollama...")
    if not dm.check_connection():
        ui.console.print(
            "[danger]Could not connect to Ollama or model not found![/danger]"
        )
        ui.console.print(
            f"[warning]Make sure Ollama is running and the model "
            f"'{ollama_config.get('model', 'mistral')}' is pulled.[/warning]"
        )
        ui.console.print("[warning]Run: ollama pull mistral[/warning]")
        return

    ui.print_system(f"Connected to Ollama ({ollama_config.get('model', 'mistral')})\n")

    # Initialize game state
    game_state = GameState()

    # Auto-detect adventure module from config
    include_files = rag_config.get("include_files", [])
    for f in include_files:
        f_lower = f.lower()
        if "xyntillan" in f_lower:
            game_state.active_module = "Xyntillan"
            ui.print_system("Adventure module: Castle Xyntillan")
            break
        elif "barrowmaze" in f_lower:
            game_state.active_module = "Barrowmaze"
            ui.print_system("Adventure module: Barrowmaze")
            break
        elif "serpent kings" in f_lower:
            game_state.active_module = "Serpent Kings"
            ui.print_system("Adventure module: Tomb of the Serpent Kings")
            break

    # Check for existing sessions
    sessions = db.list_sessions()
    if sessions:
        ui.console.print("[bold]Saved sessions found:[/bold]")
        ui.show_session_list(sessions)
        choice = ui.console.input(
            "\n[bold]Load a session (enter ID) or start new (press Enter): [/bold]"
        ).strip()
        if choice:
            try:
                loaded = db.load_session(int(choice))
                if loaded:
                    game_state = loaded
                    ui.print_system(f"Loaded: {game_state.session_name}")
            except (ValueError, TypeError):
                ui.print_system("Invalid ID. Starting new session.")

    # Character creation if no characters
    if not game_state.players:
        ui.console.print("\n[bold]Let's create your characters![/bold]\n")

        # Player 1
        p1_name = ui.console.input("[bold]Player 1 name: [/bold]").strip() or "Player 1"
        char1 = ui.character_creation_wizard(p1_name)
        game_state.players.append(char1)
        db.save_character(char1)

        # Player 2
        p2_name = ui.console.input("[bold]Player 2 name: [/bold]").strip() or "Player 2"
        char2 = ui.character_creation_wizard(p2_name)
        game_state.players.append(char2)
        db.save_character(char2)

        # Session name
        game_state.session_name = ui.console.input(
            "[bold]Name this adventure: [/bold]"
        ).strip() or "Unnamed Adventure"

    # Set up command handler
    cmd_handler = CommandHandler(game_state, db)

    # Start adventure if new session
    if game_state.turn_count == 0:
        ui.print_system("The adventure begins...\n")
        ui.print_dm_stream_start()
        full_response = []
        for chunk in dm.start_adventure(game_state, stream=True):
            ui.print_dm_stream_chunk(chunk)
            full_response.append(chunk)
        ui.print_dm_stream_end()
        game_state.add_message("dm", "".join(full_response))
        game_state.turn_count = 1

    # Main game loop
    while True:
        # Get active player
        active = cmd_handler.active_player
        player_name = active.name if active else "Party"
        player_idx = cmd_handler.active_player_idx

        # Get input
        player_input = ui.get_player_input(player_name, player_idx + 1)
        if not player_input:
            continue

        # Handle commands
        cmd_result = cmd_handler.handle(player_input)
        if cmd_result is False:
            # Quit
            save_choice = ui.console.input("[bold]Save before quitting? (y/n): [/bold]").strip()
            if save_choice.lower() in ("y", "yes"):
                cmd_handler._cmd_save("")
            ui.print_system("Farewell, adventurers!")
            break
        elif cmd_result is True:
            continue
        elif cmd_result is None and player_input.startswith("/search"):
            # Special handling for /search which needs RAG
            query = player_input[7:].strip()
            if query and rag_query:
                results = rag_query.search(query, n_results=3)
                if results:
                    for r in results:
                        ui.console.print(f"\n[bold]{r['source']}:[/bold]")
                        # Show first 200 chars of each result
                        preview = r["text"][:200] + "..." if len(r["text"]) > 200 else r["text"]
                        ui.console.print(f"  {preview}")
                else:
                    ui.print_system("No results found.")
            elif not rag_query:
                ui.print_system("No indexed PDFs. Run 'aidm ingest' first.")
            continue

        # Regular player input - send to DM
        game_state.add_message("player", f"[{player_name}]: {player_input}")
        game_state.turn_count += 1

        # Generate DM response
        ui.print_dm_stream_start()
        full_response = []
        try:
            for chunk in dm.generate_response(game_state, player_input, stream=True):
                ui.print_dm_stream_chunk(chunk)
                full_response.append(chunk)
        except Exception as e:
            ui.console.print(f"\n[danger]Error from Ollama: {e}[/danger]")
            continue
        ui.print_dm_stream_end()

        response_text = "".join(full_response)
        game_state.add_message("dm", response_text)

        # Auto-save periodically
        if config.get("game", {}).get("auto_save", True) and game_state.turn_count % 10 == 0:
            cmd_handler.session_id = db.save_session(game_state, cmd_handler.session_id)
            ui.print_system("(Auto-saved)")

        # Switch to next player for two-player mode
        if len(game_state.players) > 1:
            cmd_handler.active_player_idx = (cmd_handler.active_player_idx + 1) % len(game_state.players)


def main():
    """CLI entry point."""
    config = load_config()

    if len(sys.argv) < 2:
        # Default to play
        cmd_play(config)
        return

    command = sys.argv[1].lower()

    if command == "ingest":
        cmd_ingest(config)
    elif command == "play":
        cmd_play(config)
    elif command == "status":
        # Quick status check
        store = VectorStore(str(PROJECT_ROOT / "data" / "chroma_db"))
        console.print(f"Indexed chunks: {store.count()}")
        db_path = config.get("persistence", {}).get("db_path", "data/sessions/aidm.db")
        db = GameDatabase(str(PROJECT_ROOT / db_path))
        sessions = db.list_sessions()
        console.print(f"Saved sessions: {len(sessions)}")
        chars = db.list_characters()
        console.print(f"Saved characters: {len(chars)}")
    else:
        console.print(f"Unknown command: {command}")
        console.print("Usage: aidm [ingest|play|status]")
        console.print("  ingest - Index your PDF collection")
        console.print("  play   - Start a game session")
        console.print("  status - Check system status")


if __name__ == "__main__":
    main()
