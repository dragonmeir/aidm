"""AI Dungeon Master - CLI entry point.

This is the terminal client. For the server, use: aidm-server
"""

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
from .dm.tools import DMToolkit
from .rag.store import VectorStore
from .rag.ingest import ingest_pdfs
from .rag.query import RAGQuery
from .persistence.db import GameDatabase

console = Console()

PROJECT_ROOT = Path(__file__).resolve().parent.parent


def load_config() -> dict:
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

    pdf_roots = rag_config.get("pdf_roots", None)
    if not pdf_roots:
        pdf_roots = [rag_config.get("pdf_root", os.path.expanduser("~/tabletop-rpg"))]

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
    """Start a game session (CLI mode)."""
    ui.print_banner()

    ollama_config = config.get("ollama", {})
    rag_config = config.get("rag", {})
    persist_config = config.get("persistence", {})
    game_config = config.get("game", {})

    # Initialize components
    db_path = str(PROJECT_ROOT / persist_config.get("db_path", "data/sessions/aidm.db"))
    db = GameDatabase(db_path)

    # RAG
    rag_query = None
    store = VectorStore(str(PROJECT_ROOT / "data" / "chroma_db"))
    if store.count() > 0:
        embedding_model = rag_config.get("embedding_model", "all-MiniLM-L6-v2")
        rag_query = RAGQuery(store, embedding_model)
        ui.print_system(f"RPG library loaded: {store.count()} indexed chunks")
    else:
        ui.print_system("No indexed PDFs. Run 'aidm ingest' to index your collection.")
        ui.print_system("Playing without reference material.\n")

    # Load rule system
    system_id = game_config.get("system", "ose")
    rule_system = None
    try:
        from .systems import load_system
        rule_system = load_system(system_id)
        ui.print_system(f"Rule system: {rule_system.name}")
    except FileNotFoundError:
        ui.print_system(f"Rule system '{system_id}' not found, using built-in OSE fallback")
    except Exception as e:
        ui.print_system(f"Error loading rule system: {e}")

    # DM engine
    dm = DMEngine(
        model=ollama_config.get("model", "llama3.2:3b"),
        base_url=ollama_config.get("base_url", "http://localhost:11434"),
        temperature=ollama_config.get("temperature", 0.8),
        context_length=ollama_config.get("context_length", 8192),
        rag_query=rag_query,
        top_k=rag_config.get("top_k", 8),
        rule_system=rule_system,
    )

    # Check Ollama
    ui.print_system("Connecting to Ollama...")
    if not dm.check_connection():
        model = ollama_config.get("model", "llama3.2:3b")
        ui.console.print(f"[danger]Could not connect to Ollama or model '{model}' not found![/danger]")
        ui.console.print(f"[warning]Make sure Ollama is running: ollama pull {model}[/warning]")
        return

    ui.print_system(f"Connected to Ollama ({ollama_config.get('model', 'llama3.2:3b')})\n")

    # Vision model for map analysis
    vision_model = ollama_config.get("vision_model", "")
    if vision_model:
        from .dm.vision import MapVision
        vision = MapVision(model=vision_model, base_url=ollama_config.get("base_url", "http://localhost:11434"))
        if vision.check_available():
            dm.context_manager.vision = vision
            ui.print_system(f"Vision model loaded: {vision_model}")
        else:
            ui.print_system(f"Vision model '{vision_model}' not found — using text-only map navigation")

    # Game state
    game_state = GameState()

    # Detect module from library
    from .library import load_library
    lib = load_library()
    modules = lib.modules()
    if modules:
        if len(modules) == 1:
            entry = list(modules.values())[0]
            game_state.active_module = entry.display_name
            ui.print_system(f"Adventure module: {entry.display_name}")
        else:
            ui.console.print("\n[bold]Available modules:[/bold]")
            mod_list = list(modules.items())
            for i, (k, entry) in enumerate(mod_list, 1):
                ui.console.print(f"  {i}. {entry.display_name}")
            choice = ui.console.input("[bold]Choose module (number): [/bold]").strip()
            try:
                idx = int(choice) - 1
                if 0 <= idx < len(mod_list):
                    entry = mod_list[idx][1]
                    game_state.active_module = entry.display_name
                    ui.print_system(f"Adventure module: {entry.display_name}")
            except (ValueError, IndexError):
                ui.print_system("No module selected.")

    # Load existing session?
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

    # Character creation
    if not game_state.players:
        ui.console.print("\n[bold]Create your characters![/bold]\n")

        while True:
            p_name = ui.console.input("[bold]Player name (or 'done' to finish): [/bold]").strip()
            if p_name.lower() == "done":
                if game_state.players:
                    break
                ui.print_system("You need at least one character!")
                continue
            if not p_name:
                continue

            char = ui.character_creation_wizard(p_name)
            game_state.players.append(char)
            db.save_character(char)

        game_state.session_name = ui.console.input(
            "[bold]Name this adventure: [/bold]"
        ).strip() or "Unnamed Adventure"

    # Command handler
    cmd_handler = CommandHandler(game_state, db)

    # Start adventure
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
        active = cmd_handler.active_player
        player_name = active.name if active else "Party"
        player_idx = cmd_handler.active_player_idx

        player_input = ui.get_player_input(player_name, player_idx + 1)
        if not player_input:
            continue

        # Handle commands
        cmd_result = cmd_handler.handle(player_input)
        if cmd_result is False:
            save_choice = ui.console.input("[bold]Save before quitting? (y/n): [/bold]").strip()
            if save_choice.lower() in ("y", "yes"):
                cmd_handler._cmd_save("")
            ui.print_system("Farewell, adventurers!")
            break
        elif cmd_result is True:
            continue
        elif cmd_result is None and player_input.startswith("/search"):
            query = player_input[7:].strip()
            if query and rag_query:
                results = rag_query.search(query, n_results=3)
                if results:
                    for r in results:
                        ui.console.print(f"\n[bold]{r['source']}:[/bold]")
                        preview = r["text"][:200] + "..." if len(r["text"]) > 200 else r["text"]
                        ui.console.print(f"  {preview}")
                else:
                    ui.print_system("No results found.")
            elif not rag_query:
                ui.print_system("No indexed PDFs. Run 'aidm ingest' first.")
            continue

        # Player action → DM
        game_state.add_message("player", f"[{player_name}]: {player_input}")

        # Advance turn and check events
        turn_events = game_state.advance_turn()
        for event in turn_events:
            ui.print_system(event)

        # Generate DM response (with tool execution)
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

        # Auto-save
        save_interval = game_config.get("auto_save_interval", 10)
        if game_config.get("auto_save", True) and game_state.turn_count % save_interval == 0:
            cmd_handler.session_id = db.save_session(game_state, cmd_handler.session_id)
            ui.print_system("(Auto-saved)")

        # Switch player in multi-player
        if len(game_state.players) > 1:
            cmd_handler.active_player_idx = (cmd_handler.active_player_idx + 1) % len(game_state.players)


def cmd_serve(config: dict) -> None:
    """Start the server (delegates to server module)."""
    from .server import main as server_main
    server_main()


def cmd_extract(config: dict) -> None:
    """Extract rules from ingested PDFs into a new rule system."""
    rag_config = config.get("rag", {})
    ollama_config = config.get("ollama", {})

    store = VectorStore(str(PROJECT_ROOT / "data" / "chroma_db"))
    if store.count() == 0:
        console.print("[red]No PDFs indexed. Run 'aidm ingest' first.[/red]")
        return

    embedding_model = rag_config.get("embedding_model", "all-MiniLM-L6-v2")
    rag_query = RAGQuery(store, embedding_model)

    # Get extraction parameters from user
    console.print("\n[bold]Rule System Extraction[/bold]")
    console.print("This will analyze your ingested PDFs and extract game mechanics.\n")

    source_filter = console.input("[bold]Source filter[/bold] (name of the rulebook, or blank for all): ").strip()
    system_id = console.input("[bold]System ID[/bold] (short, no spaces, e.g. 'coc7e'): ").strip()
    system_name = console.input("[bold]System name[/bold] (display name, e.g. 'Call of Cthulhu 7e'): ").strip()

    if not system_id:
        console.print("[red]System ID is required.[/red]")
        return

    from .systems.extractor import RuleExtractor
    from .systems.loader import save_system

    extractor = RuleExtractor(
        rag_query=rag_query,
        base_url=ollama_config.get("base_url", "http://localhost:11434"),
        model=ollama_config.get("model", "dolphin-llama3:8b"),
        context_length=ollama_config.get("context_length", 8192),
    )

    console.print(f"\n[bold]Extracting rules from indexed PDFs...[/bold]\n")
    system = extractor.extract_system(
        source_filter=source_filter,
        system_id=system_id,
        system_name=system_name,
    )
    path = save_system(system)

    console.print(f"\n[bold green]Extraction complete![/bold green]")
    console.print(f"  System: {system.name} ({system.id})")
    console.print(f"  Genre: {system.genre}")
    console.print(f"  Attributes: {', '.join(a.abbreviation for a in system.attributes.attributes)}")
    if system.has_classes:
        console.print(f"  {system.character_types.label}es: {', '.join(t.name for t in system.character_types.types)}")
    console.print(f"  Combat: {system.combat.attack.method}")
    console.print(f"  Saved to: {path}")
    console.print(f"\n  To use this system, set game.system: \"{system_id}\" in config.yaml")
    console.print(f"  Or start a session with: POST /sessions/create {{\"system\": \"{system_id}\"}}")
    console.print(f"\n  Review and edit the YAML at: {path}")


def main():
    """CLI entry point."""
    config = load_config()

    if len(sys.argv) < 2:
        cmd_play(config)
        return

    command = sys.argv[1].lower()

    if command == "ingest":
        cmd_ingest(config)
    elif command == "play":
        cmd_play(config)
    elif command == "serve":
        cmd_serve(config)
    elif command == "status":
        store = VectorStore(str(PROJECT_ROOT / "data" / "chroma_db"))
        console.print(f"Indexed chunks: {store.count()}")
        db_path = config.get("persistence", {}).get("db_path", "data/sessions/aidm.db")
        db = GameDatabase(str(PROJECT_ROOT / db_path))
        sessions = db.list_sessions()
        console.print(f"Saved sessions: {len(sessions)}")
        chars = db.list_characters()
        console.print(f"Saved characters: {len(chars)}")
    elif command == "extract":
        cmd_extract(config)
    elif command == "systems":
        from .systems import list_systems, load_system
        systems = list_systems()
        if not systems:
            console.print("No rule systems found in data/systems/")
        else:
            console.print(f"[bold]Available rule systems ({len(systems)}):[/bold]")
            for sid in systems:
                try:
                    s = load_system(sid)
                    console.print(f"  {sid:20s} {s.name} ({s.genre})")
                except Exception as e:
                    console.print(f"  {sid:20s} [error] {e}")
    else:
        console.print(f"Unknown command: {command}")
        console.print("Usage: aidm [ingest|play|serve|status|extract|systems]")
        console.print("  ingest  - Index your PDF collection")
        console.print("  play    - Start a CLI game session")
        console.print("  serve   - Start the HTTP/WebSocket server")
        console.print("  status  - Check system status")
        console.print("  extract - Extract rules from ingested PDFs into a new system")
        console.print("  systems - List available rule systems")


if __name__ == "__main__":
    main()
