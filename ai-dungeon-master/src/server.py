"""AI Dungeon Master - FastAPI Server.

Run with: aidm-server
Or: uvicorn src.server:app --host 0.0.0.0 --port 8000 --reload
"""

import asyncio
import json
import uuid
import yaml
from pathlib import Path
from contextlib import asynccontextmanager

import uvicorn
from fastapi import FastAPI, WebSocket, WebSocketDisconnect, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from .game.state import GameState
from .game.character import Character, CharacterClass, create_character, CLASS_DATA, ABILITY_NAMES
from .game.generic_character import GenericCharacter
from .game.character_factory import create_generic_character, get_eligible_types
from .game.dice import roll
from .dm.engine import DMEngine
from .dm.tools import DMToolkit, process_dm_output
from .rag.store import VectorStore
from .rag.ingest import ingest_pdfs
from .rag.query import RAGQuery
from .persistence.db import GameDatabase
from .library import Library, LibraryEntry, load_library, save_library, init_default_library, generate_briefing_prompt
from .systems.loader import load_system, list_systems as list_available_systems, save_system

# ── Config ──────────────────────────────────────────────────

PROJECT_ROOT = Path(__file__).resolve().parent.parent


def load_config() -> dict:
    config_path = PROJECT_ROOT / "config.yaml"
    if config_path.exists():
        with open(config_path) as f:
            return yaml.safe_load(f)
    return {}


# ── App State ───────────────────────────────────────────────

class AppState:
    """Shared application state across all sessions."""

    def __init__(self):
        self.config: dict = {}
        self.db: GameDatabase | None = None
        self.dm_engine: DMEngine | None = None
        self.rag_query: RAGQuery | None = None
        self.vector_store: VectorStore | None = None
        # Active game sessions: session_id -> GameSession
        self.sessions: dict[str, "GameSession"] = {}
        self.library: Library | None = None


class GameSession:
    """A single active game session with connected players."""

    def __init__(self, session_id: str, game_state: GameState, dm_engine: DMEngine):
        self.session_id = session_id
        self.game_state = game_state
        self.dm_engine = dm_engine
        self.db_session_id: int | None = None
        self.connected_clients: list[WebSocket] = []
        self.toolkit: DMToolkit | None = None
        self._lock = asyncio.Lock()

    async def broadcast(self, message: dict):
        """Send a message to all connected clients."""
        dead = []
        for ws in self.connected_clients:
            try:
                await ws.send_json(message)
            except Exception:
                dead.append(ws)
        for ws in dead:
            self.connected_clients.remove(ws)


app_state = AppState()


# ── Lifecycle ───────────────────────────────────────────────

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup
    config = load_config()
    app_state.config = config

    ollama_config = config.get("ollama", {})
    rag_config = config.get("rag", {})
    persist_config = config.get("persistence", {})

    # Database
    db_path = str(PROJECT_ROOT / persist_config.get("db_path", "data/sessions/aidm.db"))
    app_state.db = GameDatabase(db_path)

    # Vector store + RAG
    store = VectorStore(str(PROJECT_ROOT / "data" / "chroma_db"))
    app_state.vector_store = store
    if store.count() > 0:
        embedding_model = rag_config.get("embedding_model", "all-MiniLM-L6-v2")
        app_state.rag_query = RAGQuery(store, embedding_model)

    # Load rule system
    game_config = config.get("game", {})
    system_id = game_config.get("system", "ose")
    rule_system = None
    try:
        rule_system = load_system(system_id)
        print(f"  Rule system: {rule_system.name} ({rule_system.id})")
    except FileNotFoundError:
        print(f"  Rule system '{system_id}' not found, using built-in OSE fallback")
    except Exception as e:
        print(f"  Error loading rule system '{system_id}': {e}, using fallback")

    # DM Engine
    app_state.dm_engine = DMEngine(
        model=ollama_config.get("model", "llama3.2:3b"),
        base_url=ollama_config.get("base_url", "http://localhost:11434"),
        temperature=ollama_config.get("temperature", 0.8),
        context_length=ollama_config.get("context_length", 8192),
        rag_query=app_state.rag_query,
        top_k=rag_config.get("top_k", 8),
        rule_system=rule_system,
    )

    # Library
    app_state.library = init_default_library()
    app_state.dm_engine.context_manager.library = app_state.library
    print(f"  Library: {len(app_state.library.entries)} entries ({len(app_state.library.rules())} rules, {len(app_state.library.modules())} modules)")

    # Vision model for map analysis
    vision_model = ollama_config.get("vision_model", "")
    if vision_model:
        from .dm.vision import MapVision
        vision = MapVision(
            model=vision_model,
            base_url=ollama_config.get("base_url", "http://localhost:11434"),
        )
        if vision.check_available():
            app_state.dm_engine.context_manager.vision = vision
            print(f"  Vision model loaded: {vision_model}")
        else:
            print(f"  Vision model '{vision_model}' not available — maps will use text graph only")

    yield
    # Shutdown — nothing to clean up


app = FastAPI(
    title="AI Dungeon Master",
    description="Universal TTRPG AI Dungeon Master Server",
    version="0.2.0",
    lifespan=lifespan,
)

# CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ── Static Files & Frontend ─────────────────────────────────

STATIC_DIR = PROJECT_ROOT / "static"
if STATIC_DIR.exists():
    @app.get("/play")
    async def serve_frontend():
        """Serve the game frontend."""
        return FileResponse(str(STATIC_DIR / "index.html"), media_type="text/html")

    @app.get("/library-manager")
    async def serve_library():
        """Serve the library management page."""
        return FileResponse(str(STATIC_DIR / "library.html"), media_type="text/html")


# ── Request/Response Models ─────────────────────────────────

class CreateSessionRequest(BaseModel):
    session_name: str = "New Adventure"
    module: str = ""       # library entry name for the adventure module
    rules: str = ""        # library entry name for the rules system
    system: str = ""       # rule system id (e.g. "ose", "coc7e") — overrides default


class CreateCharacterRequest(BaseModel):
    name: str
    player_name: str
    char_class: str = ""   # "Fighter", "Thief", etc. (for class-based systems)
    character_type: str = ""  # Generic alias for char_class


class PlayerActionRequest(BaseModel):
    session_id: str
    player_name: str
    action: str


class RollDiceRequest(BaseModel):
    notation: str = "1d20"


class IngestRequest(BaseModel):
    pdf_roots: list[str] = []
    include_files: list[str] = []


# ── REST Endpoints ──────────────────────────────────────────

@app.get("/")
async def root():
    return {"name": "AI Dungeon Master", "version": "0.2.0", "status": "running"}


@app.get("/status")
async def server_status():
    """Server health and status."""
    ollama_ok = app_state.dm_engine.check_connection() if app_state.dm_engine else False
    chunk_count = app_state.vector_store.count() if app_state.vector_store else 0
    sessions = app_state.db.list_sessions() if app_state.db else []
    return {
        "ollama_connected": ollama_ok,
        "ollama_model": app_state.config.get("ollama", {}).get("model", "unknown"),
        "indexed_chunks": chunk_count,
        "saved_sessions": len(sessions),
        "active_sessions": len(app_state.sessions),
    }


# ── Session Management ──────────────────────────────────────

@app.post("/sessions/create")
async def create_session(req: CreateSessionRequest):
    """Create a new game session."""
    session_id = str(uuid.uuid4())[:8]

    # Determine which rule system to use
    system_id = req.system or app_state.config.get("game", {}).get("system", "ose")
    game_state = GameState(session_name=req.session_name, system_id=system_id)

    if req.module:
        lib = app_state.library
        entry = lib.entries.get(req.module)
        if entry:
            game_state.active_module = entry.display_name
            game_state.module_key = req.module
        else:
            # Try fuzzy lookup
            entry = lib.get_entry_for_module(req.module)
            if entry:
                game_state.active_module = entry.display_name
                game_state.module_key = entry.name
            else:
                game_state.active_module = req.module

    # If session uses a different system than the default engine, create a per-session engine
    dm_engine = app_state.dm_engine
    if system_id and system_id != (app_state.dm_engine.rule_system.id if app_state.dm_engine.rule_system else "ose"):
        try:
            rule_sys = load_system(system_id)
            dm_engine = DMEngine(
                model=app_state.config.get("ollama", {}).get("model", "llama3.2:3b"),
                base_url=app_state.config.get("ollama", {}).get("base_url", "http://localhost:11434"),
                temperature=app_state.config.get("ollama", {}).get("temperature", 0.8),
                context_length=app_state.config.get("ollama", {}).get("context_length", 8192),
                rag_query=app_state.rag_query,
                top_k=app_state.config.get("rag", {}).get("top_k", 8),
                rule_system=rule_sys,
            )
            dm_engine.context_manager.library = app_state.library
        except Exception:
            pass  # Fall back to default engine

    session = GameSession(session_id, game_state, dm_engine)
    app_state.sessions[session_id] = session

    return {
        "session_id": session_id,
        "session_name": game_state.session_name,
        "active_module": game_state.active_module,
        "system": system_id,
    }


@app.get("/sessions")
async def list_sessions():
    """List all active and saved sessions."""
    active = [
        {
            "session_id": sid,
            "session_name": s.game_state.session_name,
            "players": [getattr(p, "name", str(p)) for p in s.game_state.players],
            "turn_count": s.game_state.turn_count,
            "connected_clients": len(s.connected_clients),
        }
        for sid, s in app_state.sessions.items()
    ]
    saved = app_state.db.list_sessions() if app_state.db else []
    return {"active": active, "saved": saved}


@app.post("/sessions/{session_id}/save")
async def save_session(session_id: str):
    """Save a session to the database."""
    session = app_state.sessions.get(session_id)
    if not session:
        raise HTTPException(404, "Session not found")
    session.db_session_id = app_state.db.save_session(
        session.game_state, session.db_session_id
    )
    return {"saved": True, "db_session_id": session.db_session_id}


@app.post("/sessions/load/{db_session_id}")
async def load_session(db_session_id: int):
    """Load a saved session into an active game."""
    game_state = app_state.db.load_session(db_session_id)
    if not game_state:
        raise HTTPException(404, "Saved session not found")

    session_id = str(uuid.uuid4())[:8]
    session = GameSession(session_id, game_state, app_state.dm_engine)
    session.db_session_id = db_session_id
    app_state.sessions[session_id] = session

    return {
        "session_id": session_id,
        "session_name": game_state.session_name,
        "turn_count": game_state.turn_count,
        "players": [getattr(p, "name", str(p)) for p in game_state.players],
    }


# ── Character Management ────────────────────────────────────

@app.post("/sessions/{session_id}/characters/create")
async def add_character(session_id: str, req: CreateCharacterRequest):
    """Create a character and add to session.

    Uses the session's rule system for character creation. Falls back
    to legacy OSE character creation if no system is loaded.
    """
    session = app_state.sessions.get(session_id)
    if not session:
        raise HTTPException(404, "Session not found")

    char_type = req.character_type or req.char_class
    rule_system = session.dm_engine.rule_system

    if rule_system:
        # Generic system-aware character creation
        char = create_generic_character(
            name=req.name,
            player_name=req.player_name,
            system=rule_system,
            character_type=char_type,
        )
        session.game_state.players.append(char)
        char_data = json.loads(char.model_dump_json())
    else:
        # Legacy OSE fallback
        try:
            char_class = CharacterClass(char_type)
        except ValueError:
            raise HTTPException(400, f"Invalid class: {char_type}. Options: {[c.value for c in CharacterClass]}")
        char = create_character(req.name, req.player_name, char_class)
        session.game_state.players.append(char)
        if app_state.db:
            app_state.db.save_character(char)
        char_data = json.loads(char.model_dump_json())

    await session.broadcast({
        "type": "character_joined",
        "character": char_data,
    })

    return char_data


@app.get("/sessions/{session_id}/characters")
async def list_characters(session_id: str):
    """List all characters in a session."""
    session = app_state.sessions.get(session_id)
    if not session:
        raise HTTPException(404, "Session not found")
    result = []
    for p in session.game_state.players:
        if hasattr(p, "model_dump_json"):
            result.append(json.loads(p.model_dump_json()))
        elif isinstance(p, dict):
            result.append(p)
        else:
            result.append({"name": str(p)})
    return result


@app.get("/characters/roll-stats")
async def roll_character_stats():
    """Roll 3d6-in-order for a new character. Returns stats + modifiers + class eligibility."""
    from .game.dice import roll_stats, roll as dice_roll
    from .game.character import ability_modifier, CLASS_DATA, CharacterClass

    stats = roll_stats()
    names = ["STR", "DEX", "CON", "INT", "WIS", "CHA"]
    abilities = {}
    for name, score in zip(names, stats):
        mod = ability_modifier(score)
        abilities[name] = {"score": score, "modifier": mod}

    # Check which classes this character qualifies for
    eligible = {}
    for cls in CharacterClass:
        data = CLASS_DATA[cls]
        meets_reqs = all(
            stats[names.index(req)] >= val
            for req, val in data["min_reqs"].items()
        )
        prime_score = stats[names.index(data["prime_req"])]
        from .game.character import xp_adjustment
        xp_adj = xp_adjustment(prime_score)
        eligible[cls.value] = {
            "eligible": meets_reqs,
            "hit_die": data["hit_die"],
            "prime_req": data["prime_req"],
            "prime_score": prime_score,
            "xp_adjustment": xp_adj,
            "min_reqs": data["min_reqs"],
            "armor": data["armor"],
            "weapons": data["weapons"],
        }

    gold = dice_roll("3d6").total * 10

    return {
        "abilities": abilities,
        "stats_array": stats,
        "gold": gold,
        "classes": eligible,
    }


class CreateCharacterFromRollRequest(BaseModel):
    name: str
    player_name: str
    char_class: str
    stats: list[int]  # [STR, DEX, CON, INT, WIS, CHA]
    gold: int = 0


@app.post("/sessions/{session_id}/characters/create-from-roll")
async def add_character_from_roll(session_id: str, req: CreateCharacterFromRollRequest):
    """Create a character using pre-rolled stats (from /characters/roll-stats)."""
    session = app_state.sessions.get(session_id)
    if not session:
        raise HTTPException(404, "Session not found")

    try:
        char_class = CharacterClass(req.char_class)
    except ValueError:
        raise HTTPException(400, f"Invalid class: {req.char_class}")

    if len(req.stats) != 6 or not all(3 <= s <= 18 for s in req.stats):
        raise HTTPException(400, "Stats must be 6 values between 3 and 18")

    from .game.character import Character, ability_modifier
    from .game.equipment import equip_starting_package

    char = Character(
        name=req.name,
        player_name=req.player_name,
        char_class=char_class,
        strength=req.stats[0],
        dexterity=req.stats[1],
        constitution=req.stats[2],
        intelligence=req.stats[3],
        wisdom=req.stats[4],
        charisma=req.stats[5],
        gold=req.gold,
    )
    char.apply_class_data()
    char.roll_hit_points()
    equip_starting_package(char)

    session.game_state.players.append(char)
    if app_state.db:
        app_state.db.save_character(char)

    await session.broadcast({
        "type": "character_joined",
        "character": json.loads(char.model_dump_json()),
    })

    return json.loads(char.model_dump_json())


@app.get("/sessions/{session_id}/state")
async def get_game_state(session_id: str):
    """Get the full game state for a session."""
    session = app_state.sessions.get(session_id)
    if not session:
        raise HTTPException(404, "Session not found")
    return json.loads(session.game_state.model_dump_json())


# ── Dice Rolling ────────────────────────────────────────────

@app.post("/roll")
async def roll_dice(req: RollDiceRequest):
    """Roll dice using standard notation."""
    try:
        result = roll(req.notation)
        return {
            "notation": result.notation,
            "rolls": result.rolls,
            "modifier": result.modifier,
            "total": result.total,
            "display": str(result),
        }
    except ValueError as e:
        raise HTTPException(400, str(e))


# ── Character Classes Info ──────────────────────────────────

@app.get("/rules/classes")
async def get_classes(system: str = ""):
    """Get available character types for a rule system.

    If no system is specified, uses the server's default.
    Falls back to legacy OSE class data if no system is loaded.
    """
    rule_system = None
    sys_id = system or (app_state.dm_engine.rule_system.id if app_state.dm_engine.rule_system else "")
    if sys_id:
        try:
            rule_system = load_system(sys_id)
        except Exception:
            pass

    if rule_system and rule_system.character_types:
        return {
            ct.name: {
                "hit_die": ct.hit_die,
                "prime_attribute": ct.prime_attribute,
                "requirements": ct.requirements,
                "save_values": ct.save_values,
                "armor_allowed": ct.armor_allowed,
                "weapons_allowed": ct.weapons_allowed,
                "special_abilities": ct.special_abilities,
            }
            for ct in rule_system.character_types.types
        }

    # Legacy OSE fallback
    return {
        cls.value: {
            "hit_die": data["hit_die"],
            "prime_req": data["prime_req"],
            "min_reqs": data["min_reqs"],
            "saves": data["saves"],
            "armor": data["armor"],
            "weapons": data["weapons"],
        }
        for cls, data in CLASS_DATA.items()
    }


# ── Rule Systems ──────────────────────────────────────────

@app.get("/systems")
async def get_systems():
    """List all available rule systems."""
    systems = list_available_systems()
    result = []
    for sys_id in systems:
        try:
            s = load_system(sys_id)
            result.append({
                "id": s.id,
                "name": s.name,
                "version": s.version,
                "genre": s.genre,
                "dm_title": s.dm_title,
                "has_classes": s.has_classes,
                "has_skills": s.has_skills,
            })
        except Exception:
            result.append({"id": sys_id, "name": sys_id, "error": "failed to load"})
    return {"systems": result}


@app.get("/systems/{system_id}")
async def get_system(system_id: str):
    """Get full rule system definition."""
    try:
        s = load_system(system_id)
        return json.loads(s.model_dump_json(exclude_none=True))
    except FileNotFoundError:
        raise HTTPException(404, f"Rule system '{system_id}' not found")
    except Exception as e:
        raise HTTPException(500, f"Error loading system: {e}")


@app.get("/systems/{system_id}/character-types")
async def get_system_character_types(system_id: str):
    """Get character types (classes, playbooks, careers) for a system."""
    try:
        s = load_system(system_id)
    except FileNotFoundError:
        raise HTTPException(404, f"Rule system '{system_id}' not found")

    if not s.character_types:
        return {"label": "None", "types": [], "optional": True}

    return {
        "label": s.character_types.label,
        "optional": s.character_types.optional,
        "types": [
            {
                "name": ct.name,
                "hit_die": ct.hit_die,
                "prime_attribute": ct.prime_attribute,
                "requirements": ct.requirements,
                "special_abilities": ct.special_abilities,
            }
            for ct in s.character_types.types
        ],
    }


class ExtractSystemRequest(BaseModel):
    source_filter: str = ""   # filter RAG chunks to this source name
    system_id: str = ""       # desired ID for the new system
    system_name: str = ""     # display name override


@app.post("/systems/extract")
async def extract_system(req: ExtractSystemRequest):
    """Extract a rule system from ingested PDFs using the LLM.

    Requires PDFs to be already ingested via the RAG pipeline.
    Returns the extracted system definition.
    """
    if not app_state.rag_query:
        raise HTTPException(400, "No PDFs indexed. Run ingestion first.")

    from .systems.extractor import RuleExtractor
    ollama_config = app_state.config.get("ollama", {})

    extractor = RuleExtractor(
        rag_query=app_state.rag_query,
        base_url=ollama_config.get("base_url", "http://localhost:11434"),
        model=ollama_config.get("model", "dolphin-llama3:8b"),
        context_length=ollama_config.get("context_length", 8192),
    )

    try:
        system = extractor.extract_system(
            source_filter=req.source_filter,
            system_id=req.system_id,
            system_name=req.system_name,
        )
        path = save_system(system)
        return {
            "success": True,
            "system_id": system.id,
            "system_name": system.name,
            "saved_to": str(path),
            "system": json.loads(system.model_dump_json(exclude_none=True)),
        }
    except Exception as e:
        raise HTTPException(500, f"Extraction failed: {e}")


# ── Library Management ──────────────────────────────────────

@app.get("/library")
async def get_library():
    """Get all library entries — rulesets and modules.

    Includes system availability info: which systems have extracted
    RuleSystem definitions and which are just tagged PDFs.
    """
    lib = app_state.library
    return {
        "entries": {k: v.model_dump() for k, v in lib.entries.items()},
        "rules": {k: {"display_name": v.display_name, "system": v.system, "description": v.description,
                       "has_system_definition": lib.has_system_definition(v.system) if v.system else False}
                  for k, v in lib.rules().items()},
        "modules": {k: {"display_name": v.display_name, "system": v.system, "description": v.description,
                         "has_briefing": bool(v.briefing),
                         "setting": v.setting, "starting_location": v.starting_location,
                         "compatible_systems": v.compatible_systems}
                    for k, v in lib.modules().items()},
        "systems_in_use": lib.systems_in_use(),
        "available_system_definitions": list_available_systems(),
    }


class AddLibraryEntryRequest(BaseModel):
    name: str                # unique key, e.g. "ose", "barrowmaze"
    display_name: str        # human name, e.g. "Old-School Essentials"
    entry_type: str          # "rules", "module", or "both"
    system: str = ""         # game system tag (e.g. "ose", "coc7e")
    pdf_files: list[str] = []
    description: str = ""
    briefing: str = ""
    setting: str = ""
    starting_location: str = ""
    intro_queries: list[str] = []
    compatible_systems: list[str] = []


@app.post("/library/add")
async def add_library_entry(req: AddLibraryEntryRequest):
    """Add or update a library entry.

    When adding a 'rules' entry, check if a RuleSystem definition
    exists for the given system tag. If not, suggest running extraction.
    """
    if req.entry_type not in ("rules", "module", "both"):
        raise HTTPException(400, "entry_type must be 'rules', 'module', or 'both'")

    entry = LibraryEntry(**req.model_dump())
    app_state.library.entries[req.name] = entry
    save_library(app_state.library)

    result = {"added": req.name, "total_entries": len(app_state.library.entries)}

    # Check if this system has a RuleSystem definition
    if req.system and req.entry_type in ("rules", "both"):
        has_def = app_state.library.has_system_definition(req.system)
        result["has_system_definition"] = has_def
        if not has_def:
            result["suggestion"] = (
                f"No rule system definition found for '{req.system}'. "
                f"After ingesting the PDFs, run POST /systems/extract with "
                f"source_filter='{req.display_name}' and system_id='{req.system}' "
                f"to extract game mechanics for this system."
            )

    return result


@app.get("/library/for-system/{system}")
async def get_library_for_system(system: str):
    """Get all library entries (rules and modules) compatible with a system."""
    lib = app_state.library
    rules = lib.rules_for_system(system)
    modules = lib.modules_for_system(system)
    has_def = lib.has_system_definition(system)

    return {
        "system": system,
        "has_system_definition": has_def,
        "rules": [{"name": e.name, "display_name": e.display_name, "description": e.description} for e in rules],
        "modules": [{"name": e.name, "display_name": e.display_name, "description": e.description,
                      "has_briefing": bool(e.briefing), "setting": e.setting} for e in modules],
    }


@app.post("/library/{name}/extract-rules")
async def extract_rules_from_entry(name: str):
    """Extract a RuleSystem from a library rules entry's ingested PDFs.

    Convenience endpoint: combines the library entry's display name as the
    source filter and system tag as the system ID, then runs extraction.
    """
    entry = app_state.library.entries.get(name)
    if not entry:
        raise HTTPException(404, f"Entry '{name}' not found")
    if entry.entry_type not in ("rules", "both"):
        raise HTTPException(400, "Can only extract rules from 'rules' or 'both' type entries")
    if not app_state.rag_query:
        raise HTTPException(400, "No PDFs indexed. Ingest this entry's PDFs first.")

    from .systems.extractor import RuleExtractor
    ollama_config = app_state.config.get("ollama", {})

    extractor = RuleExtractor(
        rag_query=app_state.rag_query,
        base_url=ollama_config.get("base_url", "http://localhost:11434"),
        model=ollama_config.get("model", "dolphin-llama3:8b"),
        context_length=ollama_config.get("context_length", 8192),
    )

    system_id = entry.system or entry.name
    system = extractor.extract_system(
        source_filter=entry.display_name,
        system_id=system_id,
        system_name=entry.display_name,
    )
    path = save_system(system)

    # Update the entry's system tag if it wasn't set
    if not entry.system:
        entry.system = system.id
        save_library(app_state.library)

    return {
        "success": True,
        "system_id": system.id,
        "system_name": system.name,
        "saved_to": str(path),
        "genre": system.genre,
        "attributes": system.attribute_names,
        "has_classes": system.has_classes,
        "has_skills": system.has_skills,
        "combat_method": system.combat.attack.method,
    }


@app.delete("/library/{name}")
async def remove_library_entry(name: str):
    """Remove a library entry."""
    if name not in app_state.library.entries:
        raise HTTPException(404, f"Entry '{name}' not found")
    del app_state.library.entries[name]
    save_library(app_state.library)
    return {"removed": name}


@app.post("/library/{name}/generate-briefing")
async def generate_module_briefing(name: str):
    """Auto-generate a DM briefing for a module using the LLM.

    Pulls relevant chunks from RAG and asks the LLM to summarize them
    into a structured briefing document.
    """
    lib = app_state.library
    entry = lib.entries.get(name)
    if not entry:
        raise HTTPException(404, f"Entry '{name}' not found")

    if entry.entry_type == "rules":
        raise HTTPException(400, "Cannot generate briefing for a rules-only entry")

    if not app_state.rag_query:
        raise HTTPException(400, "No PDFs indexed. Run /ingest first.")

    # Pull chunks ONLY from this entry's PDFs using source_labels
    source_labels = entry.source_labels if entry.source_labels else None
    source_filter = entry.display_name  # fallback for substring matching

    queries = [
        f"{entry.display_name} introduction background overview",
        f"{entry.display_name} town village starting NPCs shops",
        f"{entry.display_name} rumors hooks adventure",
        f"{entry.display_name} key locations map rooms",
        f"{entry.display_name} monsters encounters treasure",
        f"{entry.display_name} important NPCs characters",
    ]

    chunks = []
    seen = set()
    for q in queries:
        results = app_state.rag_query.search(
            q, n_results=4,
            source_filter=source_filter,
            source_labels=source_labels,
        )
        if not results:
            # Only fall back to unfiltered if no source_labels were set
            if not source_labels:
                results = app_state.rag_query.search(q, n_results=4)
        for r in results:
            sig = r["text"][:80]
            if sig not in seen:
                seen.add(sig)
                chunks.append(r["text"])

    if not chunks:
        hint = " Re-ingest to record source labels." if not source_labels else ""
        raise HTTPException(400, f"No indexed content found for '{entry.display_name}'.{hint} Ingest its PDFs first.")

    # Get system info for genre-aware briefing generation
    system_name = ""
    genre = ""
    if entry.system:
        try:
            rule_sys = load_system(entry.system)
            system_name = rule_sys.name
            genre = rule_sys.genre
        except Exception:
            pass

    # Ask the LLM to generate the briefing
    prompt = generate_briefing_prompt(entry.display_name, chunks, system_name=system_name, genre=genre)

    import ollama as ollama_client
    ollama_config = app_state.config.get("ollama", {})
    client = ollama_client.Client(host=ollama_config.get("base_url", "http://localhost:11434"))

    dm_title = "GM"
    if system_name:
        try:
            rule_sys = load_system(entry.system)
            dm_title = rule_sys.dm_title
        except Exception:
            pass

    response = client.chat(
        model=ollama_config.get("model", "dolphin-llama3:8b"),
        messages=[
            {"role": "system", "content": f"You are a tabletop RPG expert. Generate a concise, accurate {dm_title} briefing from the provided module excerpts. Use ONLY facts from the excerpts."},
            {"role": "user", "content": prompt},
        ],
        options={"temperature": 0.3, "num_ctx": 8192},
    )

    briefing = response.message.content

    # Save it
    entry.briefing = briefing
    save_library(lib)

    # Also save as a file
    briefing_dir = PROJECT_ROOT / "data" / "maps" / name
    briefing_dir.mkdir(parents=True, exist_ok=True)
    (briefing_dir / "module_briefing.md").write_text(briefing)

    return {"name": name, "briefing_length": len(briefing), "briefing_preview": briefing[:500]}


@app.post("/library/{name}/set-briefing")
async def set_module_briefing(name: str, briefing: str = ""):
    """Manually set or edit a module's briefing text."""
    entry = app_state.library.entries.get(name)
    if not entry:
        raise HTTPException(404, f"Entry '{name}' not found")

    # Read briefing from request body
    import json as json_mod
    from fastapi import Request

    entry.briefing = briefing
    save_library(app_state.library)
    return {"name": name, "briefing_length": len(briefing)}


@app.post("/library/{name}/ingest")
async def ingest_library_entry(name: str):
    """Ingest the PDFs for a specific library entry into the vector store.

    Records the source labels used during ingestion on the library entry
    so that RAG queries can precisely filter to this entry's chunks.
    """
    entry = app_state.library.entries.get(name)
    if not entry:
        raise HTTPException(404, f"Entry '{name}' not found")

    if not entry.pdf_files:
        raise HTTPException(400, "No PDF files listed for this entry")

    import os
    rag_config = app_state.config.get("rag", {})

    # Check if paths are absolute (from file browser) or relative (from config)
    abs_files = [f for f in entry.pdf_files if os.path.isabs(f)]
    rel_files = [f for f in entry.pdf_files if not os.path.isabs(f)]

    chunk_count = 0
    ingested_source_labels = set()

    # Ingest absolute paths directly
    if abs_files:
        from .rag.ingest import extract_text_from_pdf, chunk_text, make_chunk_id, get_source_label
        from sentence_transformers import SentenceTransformer
        from rich.console import Console

        console = Console()
        embed_model = SentenceTransformer(rag_config.get("embedding_model", "all-MiniLM-L6-v2"))
        chunk_size = rag_config.get("chunk_size", 500)
        chunk_overlap = rag_config.get("chunk_overlap", 50)

        all_texts, all_metas, all_ids = [], [], []

        for pdf_path in abs_files:
            if not os.path.isfile(pdf_path):
                console.print(f"[yellow]Skipping (not found): {pdf_path}[/yellow]")
                continue

            source_label = os.path.splitext(os.path.basename(pdf_path))[0]
            ingested_source_labels.add(source_label)
            text = extract_text_from_pdf(pdf_path)
            if not text:
                continue

            chunks = chunk_text(text, chunk_size, chunk_overlap)
            for i, chunk_text_val in enumerate(chunks):
                all_texts.append(chunk_text_val)
                all_metas.append({"source": source_label, "pdf_path": pdf_path, "chunk_index": i})
                all_ids.append(make_chunk_id(pdf_path, i))
            chunk_count += len(chunks)
            console.print(f"[green]{source_label}: {len(chunks)} chunks[/green]")

        if all_texts:
            embeddings = embed_model.encode(all_texts, show_progress_bar=False).tolist()
            app_state.vector_store.add_documents(all_texts, all_metas, all_ids, embeddings)

    # Ingest relative paths via the standard pipeline
    if rel_files:
        from .rag.ingest import get_source_label
        pdf_roots = rag_config.get("pdf_roots", [])
        count = ingest_pdfs(
            pdf_roots=pdf_roots,
            store=app_state.vector_store,
            embedding_model_name=rag_config.get("embedding_model", "all-MiniLM-L6-v2"),
            chunk_size=rag_config.get("chunk_size", 500),
            chunk_overlap=rag_config.get("chunk_overlap", 50),
            include_files=rel_files,
        )
        chunk_count += count
        # Compute source labels for relative paths
        for rel_path in rel_files:
            for root in pdf_roots:
                full_path = os.path.join(root, rel_path)
                if os.path.isfile(full_path):
                    ingested_source_labels.add(get_source_label(full_path, root))
                    break

    # Record source labels on the library entry for precise RAG filtering
    if ingested_source_labels:
        # Merge with existing labels (in case of incremental ingestion)
        existing = set(entry.source_labels)
        entry.source_labels = sorted(existing | ingested_source_labels)
        save_library(app_state.library)

    # Reinit RAG
    if app_state.vector_store.count() > 0:
        embedding_model = rag_config.get("embedding_model", "all-MiniLM-L6-v2")
        app_state.rag_query = RAGQuery(app_state.vector_store, embedding_model)
        app_state.dm_engine.context_manager.rag_query = app_state.rag_query

    return {
        "name": name,
        "chunks_indexed": chunk_count,
        "total_in_store": app_state.vector_store.count(),
        "source_labels": sorted(ingested_source_labels),
    }


# ── File Browser ────────────────────────────────────────────

@app.get("/files/browse")
async def browse_files(path: str = "", root: str = ""):
    """Browse the filesystem for PDFs. Returns directories and PDF files.

    If root is empty, returns the configured pdf_roots as starting points,
    plus common locations like home directory.
    """
    import os

    rag_config = app_state.config.get("rag", {})
    pdf_roots = rag_config.get("pdf_roots", [])

    # If no path given, show the root options
    if not path:
        roots = []
        # Configured pdf_roots
        for r in pdf_roots:
            if os.path.isdir(r):
                roots.append({"name": os.path.basename(r) or r, "path": r, "type": "root"})

        # Home directory
        home = os.path.expanduser("~")
        roots.append({"name": "Home", "path": home, "type": "root"})

        # Common locations
        for d in ["/home", os.path.join(home, "Documents"), os.path.join(home, "Downloads"), os.path.join(home, "Desktop")]:
            if os.path.isdir(d) and d != home:
                roots.append({"name": os.path.basename(d), "path": d, "type": "root"})

        # Project data dir
        data_dir = str(PROJECT_ROOT / "data")
        if os.path.isdir(data_dir):
            roots.append({"name": "AIDM Data", "path": data_dir, "type": "root"})

        return {"path": "", "parent": "", "roots": roots, "dirs": [], "files": []}

    # Sanitize — no path traversal
    real_path = os.path.realpath(path)
    if not os.path.isdir(real_path):
        raise HTTPException(400, "Not a directory")

    parent = os.path.dirname(real_path)
    dirs = []
    files = []

    try:
        for entry in sorted(os.listdir(real_path)):
            full = os.path.join(real_path, entry)
            if entry.startswith("."):
                continue
            if os.path.isdir(full):
                dirs.append({"name": entry, "path": full})
            elif entry.lower().endswith(".pdf"):
                size = os.path.getsize(full)
                files.append({
                    "name": entry,
                    "path": full,
                    "size": size,
                    "size_mb": round(size / (1024 * 1024), 1),
                })
    except PermissionError:
        raise HTTPException(403, "Permission denied")

    return {
        "path": real_path,
        "parent": parent,
        "roots": [],
        "dirs": dirs,
        "files": files,
    }


# ── Inventory Management ────────────────────────────────────

class InventoryActionRequest(BaseModel):
    character_name: str
    action: str  # "buy", "sell", "drop", "add"
    item: str
    category: str = "gear"  # "weapons", "armor", "gear", "ammo"
    cost: int = 0


@app.post("/sessions/{session_id}/inventory")
async def manage_inventory(session_id: str, req: InventoryActionRequest):
    """Buy, sell, drop, or add items to a character's inventory."""
    session = app_state.sessions.get(session_id)
    if not session:
        raise HTTPException(404, "Session not found")

    char = None
    for p in session.game_state.players:
        if req.character_name.lower() in p.name.lower():
            char = p
            break
    if not char:
        raise HTTPException(404, f"Character '{req.character_name}' not found")

    from .game.equipment import WEAPONS, ARMOR, GEAR, AMMO

    if req.action == "buy":
        # Look up cost from tables if not provided
        cost = req.cost
        if not cost:
            if req.item in WEAPONS:
                cost = WEAPONS[req.item][0]
            elif req.item in ARMOR:
                cost = ARMOR[req.item][0]
            elif req.item in GEAR:
                cost = GEAR[req.item][0]
            elif req.item in AMMO:
                cost = AMMO[req.item][0]
        if cost > char.gold:
            raise HTTPException(400, f"Not enough gold ({char.gold} gp, need {cost})")
        char.gold -= cost
        if req.category == "weapons":
            char.weapons.append(req.item)
        elif req.category == "armor":
            char.armor = req.item
        else:
            char.inventory.append(req.item)
        session.game_state.log_event("treasure", f"{char.name} bought {req.item} for {cost}gp")

    elif req.action == "sell":
        # Sell at half price
        cost = req.cost // 2 if req.cost else 0
        if req.item in char.weapons:
            char.weapons.remove(req.item)
        elif req.item in char.inventory:
            char.inventory.remove(req.item)
        char.gold += cost
        session.game_state.log_event("treasure", f"{char.name} sold {req.item} for {cost}gp")

    elif req.action == "drop":
        if req.item in char.weapons:
            char.weapons.remove(req.item)
        elif req.item in char.inventory:
            char.inventory.remove(req.item)
        session.game_state.log_event("exploration", f"{char.name} dropped {req.item}")

    elif req.action == "add":
        if req.category == "weapons":
            char.weapons.append(req.item)
        else:
            char.inventory.append(req.item)

    await session.broadcast({
        "type": "game_state",
        "state": json.loads(session.game_state.model_dump_json()),
    })

    return {"character": char.name, "action": req.action, "item": req.item, "gold": char.gold}


# ── Spell Management ────────────────────────────────────────

@app.post("/sessions/{session_id}/spells/cast")
async def cast_spell(session_id: str, character_name: str, spell: str):
    session = app_state.sessions.get(session_id)
    if not session:
        raise HTTPException(404, "Session not found")
    for p in session.game_state.players:
        if character_name.lower() in p.name.lower():
            if p.cast_spell(spell):
                await session.broadcast({"type": "game_state", "state": json.loads(session.game_state.model_dump_json())})
                return {"cast": True, "spell": spell, "remaining": len(p.available_spells())}
            else:
                raise HTTPException(400, f"Spell '{spell}' not available")
    raise HTTPException(404, "Character not found")


@app.post("/sessions/{session_id}/spells/memorize")
async def memorize_spells(session_id: str, character_name: str, spells: list[str]):
    session = app_state.sessions.get(session_id)
    if not session:
        raise HTTPException(404, "Session not found")
    for p in session.game_state.players:
        if character_name.lower() in p.name.lower():
            p.rest_and_memorize(spells)
            await session.broadcast({"type": "game_state", "state": json.loads(session.game_state.model_dump_json())})
            return {"memorized": p.spells_memorized}
    raise HTTPException(404, "Character not found")


# ── Retainer Management ────────────────────────────────────

@app.get("/sessions/{session_id}/retainers")
async def list_retainers(session_id: str):
    session = app_state.sessions.get(session_id)
    if not session:
        raise HTTPException(404, "Session not found")
    return [json.loads(r.model_dump_json()) for r in session.game_state.retainers]


@app.delete("/sessions/{session_id}/retainers/{name}")
async def dismiss_retainer(session_id: str, name: str):
    session = app_state.sessions.get(session_id)
    if not session:
        raise HTTPException(404, "Session not found")
    for i, r in enumerate(session.game_state.retainers):
        if r.name.lower() == name.lower():
            session.game_state.retainers.pop(i)
            session.game_state.log_event("retainer", f"Dismissed {r.name}")
            await session.broadcast({"type": "game_state", "state": json.loads(session.game_state.model_dump_json())})
            return {"dismissed": r.name}
    raise HTTPException(404, f"Retainer '{name}' not found")


# ── Journal & NPC Tracker ──────────────────────────────────

@app.get("/sessions/{session_id}/journal")
async def get_journal(session_id: str, event_type: str = ""):
    session = app_state.sessions.get(session_id)
    if not session:
        raise HTTPException(404, "Session not found")
    entries = session.game_state.journal
    if event_type:
        entries = [e for e in entries if e.event_type == event_type]
    return [e.model_dump() for e in entries]


@app.get("/sessions/{session_id}/npcs")
async def get_npc_tracker(session_id: str):
    session = app_state.sessions.get(session_id)
    if not session:
        raise HTTPException(404, "Session not found")
    return [n.model_dump() for n in session.game_state.npc_tracker]


# ── Map Management ──────────────────────────────────────────

@app.get("/files/browse-maps")
async def browse_maps(path: str = ""):
    """Browse filesystem for map images (jpg, png) and PDFs."""
    import os
    if not path:
        home = os.path.expanduser("~")
        roots = [
            {"name": "Home", "path": home},
            {"name": "Desktop", "path": os.path.join(home, "Desktop")},
            {"name": "Downloads", "path": os.path.join(home, "Downloads")},
            {"name": "AIDM Source", "path": str(PROJECT_ROOT.parent)},
        ]
        roots = [r for r in roots if os.path.isdir(r["path"])]
        return {"path": "", "parent": "", "roots": roots, "dirs": [], "files": []}

    real_path = os.path.realpath(path)
    if not os.path.isdir(real_path):
        raise HTTPException(400, "Not a directory")

    parent = os.path.dirname(real_path)
    dirs, files = [], []
    map_exts = {".jpg", ".jpeg", ".png", ".gif", ".webp", ".pdf", ".tif", ".tiff"}
    try:
        for entry in sorted(os.listdir(real_path)):
            if entry.startswith(".") or entry.startswith("__"):
                continue
            full = os.path.join(real_path, entry)
            if os.path.isdir(full):
                dirs.append({"name": entry, "path": full})
            elif os.path.splitext(entry)[1].lower() in map_exts:
                size = os.path.getsize(full)
                files.append({"name": entry, "path": full, "size_mb": round(size / (1024*1024), 1)})
    except PermissionError:
        raise HTTPException(403, "Permission denied")
    return {"path": real_path, "parent": parent, "roots": [], "dirs": dirs, "files": files}


class AddMapsRequest(BaseModel):
    module: str
    files: list[dict]  # [{"path": "/abs/path", "label": "Ground Floor"}]


@app.post("/maps/add")
async def add_maps_to_module(req: AddMapsRequest):
    """Copy map files to a module's map directory and create/update map_data.json."""
    import os, shutil

    module_dir = PROJECT_ROOT / "data" / "maps" / req.module
    module_dir.mkdir(parents=True, exist_ok=True)

    # Load existing map_data or create new
    data_file = module_dir / "map_data.json"
    if data_file.exists():
        with open(data_file) as f:
            map_data = json.load(f)
    else:
        map_data = {"module": req.module, "maps": {}, "rooms": {}}

    added = []
    for f in req.files:
        src = f.get("path", "")
        label = f.get("label", "")
        if not os.path.isfile(src):
            continue

        ext = os.path.splitext(src)[1].lower()
        safe_name = label.lower().replace(" ", "_").replace("/", "_") if label else os.path.splitext(os.path.basename(src))[0].lower().replace(" ", "_")

        if ext == ".pdf":
            # Convert PDF pages to PNG images using PyMuPDF
            import fitz
            try:
                doc = fitz.open(src)
                for page_num in range(len(doc)):
                    page = doc[page_num]
                    # Render at 2x resolution for quality
                    mat = fitz.Matrix(2, 2)
                    pix = page.get_pixmap(matrix=mat)
                    if len(doc) == 1:
                        page_safe = safe_name
                        page_label = label or os.path.splitext(os.path.basename(src))[0]
                    else:
                        page_safe = f"{safe_name}_p{page_num+1}"
                        page_label = f"{label or os.path.splitext(os.path.basename(src))[0]} (Page {page_num+1})"

                    dest_name = page_safe + ".png"
                    dest = module_dir / dest_name
                    pix.save(str(dest))

                    map_data["maps"][page_safe] = {
                        "file": dest_name,
                        "label": page_label,
                        "sections": [],
                    }
                    added.append({"key": page_safe, "file": dest_name, "label": page_label})
                doc.close()
            except Exception as e:
                added.append({"key": safe_name, "file": "", "label": f"Error converting {os.path.basename(src)}: {e}"})
        elif ext in (".tif", ".tiff"):
            # Convert TIFF to PNG
            import fitz
            try:
                doc = fitz.open(src)
                page = doc[0]
                pix = page.get_pixmap()
                dest_name = safe_name + ".png"
                dest = module_dir / dest_name
                pix.save(str(dest))
                doc.close()

                if not label:
                    label = os.path.splitext(os.path.basename(src))[0]
                map_data["maps"][safe_name] = {"file": dest_name, "label": label, "sections": []}
                added.append({"key": safe_name, "file": dest_name, "label": label})
            except Exception as e:
                added.append({"key": safe_name, "file": "", "label": f"Error: {e}"})
        else:
            # Image file — just copy
            dest_name = safe_name + ext
            dest = module_dir / dest_name
            shutil.copy2(src, dest)

            if not label:
                label = os.path.splitext(os.path.basename(src))[0]
            map_data["maps"][safe_name] = {"file": dest_name, "label": label, "sections": []}
            added.append({"key": safe_name, "file": dest_name, "label": label})

    with open(data_file, "w") as f_out:
        json.dump(map_data, f_out, indent=2)

    return {"module": req.module, "added": added, "total_maps": len(map_data["maps"])}


@app.delete("/maps/{module}/{map_key}")
async def remove_map(module: str, map_key: str):
    """Remove a map from a module."""
    data_file = PROJECT_ROOT / "data" / "maps" / module / "map_data.json"
    if not data_file.exists():
        raise HTTPException(404, "Module maps not found")
    with open(data_file) as f:
        map_data = json.load(f)
    if map_key in map_data.get("maps", {}):
        # Delete the image file too
        img = PROJECT_ROOT / "data" / "maps" / module / map_data["maps"][map_key]["file"]
        if img.exists():
            img.unlink()
        del map_data["maps"][map_key]
        with open(data_file, "w") as f_out:
            json.dump(map_data, f_out, indent=2)
    return {"removed": map_key}


# ── Equipment Shop ──────────────────────────────────────────

@app.get("/shop")
async def get_shop():
    """Get all available equipment with prices."""
    from .game.equipment import WEAPONS, ARMOR, GEAR, AMMO, STARTING_PACKAGES
    from .game.character import CharacterClass

    return {
        "weapons": {name: {"cost": w[0], "damage": w[1], "weight": w[2], "properties": w[3]} for name, w in WEAPONS.items()},
        "armor": {name: {"cost": a[0], "ac": a[1], "weight": a[2]} for name, a in ARMOR.items()},
        "gear": {name: {"cost": g[0], "weight": g[1]} for name, g in GEAR.items()},
        "ammo": {name: {"cost": a[0], "weight": a[1]} for name, a in AMMO.items()},
        "starting_packages": {
            cls.value: {
                "weapons": pkg["weapons"],
                "armor": pkg["armor"],
                "shield": pkg["shield"],
                "gear": pkg["gear"],
                "ammo": pkg["ammo"],
            }
            for cls, pkg in STARTING_PACKAGES.items()
        },
    }


class ManualCharacterRequest(BaseModel):
    name: str
    player_name: str
    char_class: str
    stats: list[int]
    gold: int = 0
    weapons: list[str] = []
    armor: str = "None"
    shield: bool = False
    gear: list[str] = []
    ammo: list[str] = []


@app.post("/sessions/{session_id}/characters/create-manual")
async def add_character_manual(session_id: str, req: ManualCharacterRequest):
    """Create a character with manually chosen equipment."""
    session = app_state.sessions.get(session_id)
    if not session:
        raise HTTPException(404, "Session not found")

    try:
        char_class = CharacterClass(req.char_class)
    except ValueError:
        raise HTTPException(400, f"Invalid class: {req.char_class}")

    if len(req.stats) != 6 or not all(3 <= s <= 18 for s in req.stats):
        raise HTTPException(400, "Stats must be 6 values between 3 and 18")

    from .game.character import Character, ability_modifier
    from .game.equipment import WEAPONS, ARMOR, GEAR, AMMO

    char = Character(
        name=req.name,
        player_name=req.player_name,
        char_class=char_class,
        strength=req.stats[0],
        dexterity=req.stats[1],
        constitution=req.stats[2],
        intelligence=req.stats[3],
        wisdom=req.stats[4],
        charisma=req.stats[5],
        gold=req.gold,
    )
    char.apply_class_data()
    char.roll_hit_points()

    # Apply purchased equipment
    total_cost = 0
    for w in req.weapons:
        if w in WEAPONS:
            cost = WEAPONS[w][0]
            if char.gold >= cost:
                char.gold -= cost
                total_cost += cost
                char.weapons.append(w)

    if req.armor and req.armor in ARMOR:
        cost, ac, _ = ARMOR[req.armor]
        if char.gold >= cost:
            char.gold -= cost
            total_cost += cost
            char.armor = req.armor

    if req.shield and "Shield" in ARMOR:
        cost = ARMOR["Shield"][0]
        if char.gold >= cost:
            char.gold -= cost
            total_cost += cost
            char.inventory.append("Shield")

    for item in req.gear:
        if item in GEAR:
            cost = GEAR[item][0]
            if char.gold >= cost:
                char.gold -= cost
                total_cost += cost
                char.inventory.append(item)

    for item in req.ammo:
        if item in AMMO:
            cost = AMMO[item][0]
            if char.gold >= cost:
                char.gold -= cost
                total_cost += cost
                char.inventory.append(item)

    # Calculate AC with armor + shield + DEX
    base_ac = ARMOR[char.armor][1] if char.armor in ARMOR else 9
    shield_bonus = 1 if "Shield" in char.inventory else 0
    dex_mod = ability_modifier(char.dexterity)
    char.ac = base_ac - shield_bonus - dex_mod

    session.game_state.players.append(char)
    if app_state.db:
        app_state.db.save_character(char)

    await session.broadcast({
        "type": "character_joined",
        "character": json.loads(char.model_dump_json()),
    })

    return json.loads(char.model_dump_json())


# ── Maps ────────────────────────────────────────────────────

@app.get("/maps")
async def list_maps():
    """List available module maps."""
    maps_dir = PROJECT_ROOT / "data" / "maps"
    result = {}
    for module_dir in maps_dir.iterdir():
        if module_dir.is_dir():
            data_file = module_dir / "map_data.json"
            if data_file.exists():
                with open(data_file) as f:
                    data = json.load(f)
                result[module_dir.name] = {
                    "module": data.get("module", module_dir.name),
                    "maps": {
                        k: {"label": v["label"], "file": v["file"], "sections": v["sections"]}
                        for k, v in data.get("maps", {}).items()
                    },
                    "room_count": len(data.get("rooms", {})),
                }
    return result


@app.get("/maps/{module}/data")
async def get_map_data(module: str):
    """Get full map data for a module — rooms, connections, features."""
    data_file = PROJECT_ROOT / "data" / "maps" / module / "map_data.json"
    if not data_file.exists():
        raise HTTPException(404, f"No map data for module: {module}")
    with open(data_file) as f:
        return json.load(f)


@app.get("/maps/{module}/image/{filename}")
async def get_map_image(module: str, filename: str):
    """Serve a map image file."""
    # Sanitize filename
    if "/" in filename or "\\" in filename or ".." in filename:
        raise HTTPException(400, "Invalid filename")
    file_path = PROJECT_ROOT / "data" / "maps" / module / filename
    if not file_path.exists():
        raise HTTPException(404, "Map image not found")
    media_type = "image/jpeg" if filename.endswith(".jpg") else "image/png"
    return FileResponse(str(file_path), media_type=media_type)


@app.get("/maps/{module}/room/{room_id}")
async def get_room_info(module: str, room_id: str):
    """Get info about a specific room — connections, features, which map it's on."""
    data_file = PROJECT_ROOT / "data" / "maps" / module / "map_data.json"
    if not data_file.exists():
        raise HTTPException(404, f"No map data for module: {module}")
    with open(data_file) as f:
        data = json.load(f)
    room = data.get("rooms", {}).get(room_id)
    if not room:
        raise HTTPException(404, f"Room {room_id} not found")
    return {"room_id": room_id, **room}


@app.get("/maps/{module}/floor/{floor}")
async def get_floor_rooms(module: str, floor: str):
    """Get all rooms on a floor (ground, upper, dungeon)."""
    data_file = PROJECT_ROOT / "data" / "maps" / module / "map_data.json"
    if not data_file.exists():
        raise HTTPException(404, f"No map data for module: {module}")
    with open(data_file) as f:
        data = json.load(f)
    rooms = {
        rid: room for rid, room in data.get("rooms", {}).items()
        if room.get("floor") == floor
    }
    return {"floor": floor, "room_count": len(rooms), "rooms": rooms}


@app.post("/maps/{module}/analyze")
async def analyze_maps(module: str):
    """Run vision model analysis on all maps for a module. Results are cached."""
    vision = app_state.dm_engine.context_manager.vision if app_state.dm_engine else None
    if not vision:
        raise HTTPException(400, "No vision model configured or available")

    module_dir = PROJECT_ROOT / "data" / "maps" / module
    if not module_dir.exists():
        raise HTTPException(404, f"No maps for module: {module}")

    from .dm.vision import preanalyze_module_maps
    results = preanalyze_module_maps(module_dir, vision, module)
    return {"analyzed": len(results), "floors": list(results.keys())}


# ── PDF Ingestion ───────────────────────────────────────────

@app.post("/ingest")
async def trigger_ingest(req: IngestRequest):
    """Trigger PDF ingestion (can be slow)."""
    rag_config = app_state.config.get("rag", {})
    pdf_roots = req.pdf_roots or rag_config.get("pdf_roots", [])
    include_files = req.include_files or rag_config.get("include_files", [])

    if not pdf_roots:
        raise HTTPException(400, "No PDF roots configured")

    store = app_state.vector_store
    chunk_count = ingest_pdfs(
        pdf_roots=pdf_roots,
        store=store,
        embedding_model_name=rag_config.get("embedding_model", "all-MiniLM-L6-v2"),
        chunk_size=rag_config.get("chunk_size", 500),
        chunk_overlap=rag_config.get("chunk_overlap", 50),
        include_files=include_files if include_files else None,
    )

    # Reinitialize RAG query
    if store.count() > 0:
        embedding_model = rag_config.get("embedding_model", "all-MiniLM-L6-v2")
        app_state.rag_query = RAGQuery(store, embedding_model)
        app_state.dm_engine.context_manager.rag_query = app_state.rag_query

    return {"chunks_indexed": chunk_count}


# ── RAG Search ──────────────────────────────────────────────

@app.get("/search")
async def search_rag(query: str, n_results: int = 5):
    """Search the indexed PDF library."""
    if not app_state.rag_query:
        raise HTTPException(400, "No PDFs indexed. POST /ingest first.")
    results = app_state.rag_query.search(query, n_results=n_results)
    return {"results": results}


# ── WebSocket Game Session ──────────────────────────────────

@app.websocket("/ws/game/{session_id}")
async def game_websocket(ws: WebSocket, session_id: str):
    """WebSocket connection for live game play.

    Messages from client:
        {"type": "action", "player": "Grond", "text": "I search the chest"}
        {"type": "roll", "notation": "2d6"}
        {"type": "command", "command": "/save"}
        {"type": "start_adventure"}

    Messages from server:
        {"type": "dm_response", "text": "...", "tool_results": [...]}
        {"type": "dm_chunk", "text": "..."}  (streaming)
        {"type": "dm_stream_end"}
        {"type": "dice_roll", "result": {...}}
        {"type": "tool_result", "result": {...}}
        {"type": "turn_events", "events": [...]}
        {"type": "error", "message": "..."}
        {"type": "system", "text": "..."}
        {"type": "game_state", "state": {...}}
    """
    session = app_state.sessions.get(session_id)
    if not session:
        await ws.close(code=4004, reason="Session not found")
        return

    await ws.accept()
    session.connected_clients.append(ws)

    await ws.send_json({
        "type": "system",
        "text": f"Connected to session: {session.game_state.session_name}",
    })

    # Send current game state
    await ws.send_json({
        "type": "game_state",
        "state": json.loads(session.game_state.model_dump_json()),
    })

    try:
        while True:
            data = await ws.receive_json()
            msg_type = data.get("type", "")

            if msg_type == "action":
                await _handle_player_action(session, ws, data)
            elif msg_type == "roll":
                await _handle_roll(session, ws, data)
            elif msg_type == "start_adventure":
                await _handle_start_adventure(session, ws)
            elif msg_type == "command":
                await _handle_command(session, ws, data)
            else:
                await ws.send_json({"type": "error", "message": f"Unknown message type: {msg_type}"})

    except WebSocketDisconnect:
        session.connected_clients.remove(ws)
    except Exception as e:
        session.connected_clients.remove(ws)
        try:
            await ws.send_json({"type": "error", "message": str(e)})
        except Exception:
            pass


async def _handle_player_action(session: GameSession, ws: WebSocket, data: dict):
    """Handle a player action — send to DM engine, stream response."""
    player_name = data.get("player", "Unknown")
    action_text = data.get("text", "")

    if not action_text:
        await ws.send_json({"type": "error", "message": "Empty action"})
        return

    async with session._lock:
        game_state = session.game_state

        # Advance turn
        turn_events = game_state.advance_turn()
        if turn_events:
            await session.broadcast({"type": "turn_events", "events": turn_events})

        # Check for wandering monsters
        game_config = app_state.config.get("game", {})
        wm_interval = game_config.get("wandering_monster_interval", 2)
        if game_state.needs_wandering_check(wm_interval) and game_state.dungeon_level > 0 and not game_state.in_combat:
            game_state.reset_wandering_timer()
            # The DM will handle the wandering monster check via tools

        game_state.add_message("player", f"[{player_name}]: {action_text}")

        # Generate DM response
        toolkit = DMToolkit(game_state)
        session.toolkit = toolkit

        try:
            full_response = []
            for chunk in session.dm_engine.generate_response(game_state, action_text, stream=True):
                full_response.append(chunk)
                await session.broadcast({"type": "dm_chunk", "text": chunk})

            await session.broadcast({"type": "dm_stream_end"})

            response_text = "".join(full_response)
            game_state.add_message("dm", response_text)

            # Log any tool results
            if toolkit._toolkit if hasattr(toolkit, '_toolkit') else False:
                pass  # Already handled inline

            # Send updated game state
            await session.broadcast({
                "type": "game_state",
                "state": json.loads(game_state.model_dump_json()),
            })

            # Auto-save
            save_interval = game_config.get("auto_save_interval", 10)
            if game_config.get("auto_save", True) and game_state.turn_count % save_interval == 0:
                session.db_session_id = app_state.db.save_session(
                    game_state, session.db_session_id
                )
                await session.broadcast({"type": "system", "text": "(Auto-saved)"})

        except Exception as e:
            await ws.send_json({"type": "error", "message": f"DM engine error: {e}"})


async def _handle_start_adventure(session: GameSession, ws: WebSocket):
    """Start a new adventure with opening narration."""
    async with session._lock:
        if session.game_state.turn_count > 0:
            await ws.send_json({"type": "error", "message": "Adventure already in progress"})
            return

        if not session.game_state.players:
            await ws.send_json({"type": "error", "message": "Add characters first"})
            return

        try:
            full_response = []
            for chunk in session.dm_engine.start_adventure(session.game_state, stream=True):
                full_response.append(chunk)
                await session.broadcast({"type": "dm_chunk", "text": chunk})

            await session.broadcast({"type": "dm_stream_end"})

            response_text = "".join(full_response)
            session.game_state.add_message("dm", response_text)
            session.game_state.turn_count = 1

            await session.broadcast({
                "type": "game_state",
                "state": json.loads(session.game_state.model_dump_json()),
            })

        except Exception as e:
            await ws.send_json({"type": "error", "message": f"DM engine error: {e}"})


async def _handle_roll(session: GameSession, ws: WebSocket, data: dict):
    """Handle a manual dice roll from a player."""
    notation = data.get("notation", "1d20")
    try:
        result = roll(notation)
        await session.broadcast({
            "type": "dice_roll",
            "result": {
                "notation": result.notation,
                "rolls": result.rolls,
                "modifier": result.modifier,
                "total": result.total,
                "display": str(result),
                "player": data.get("player", "Unknown"),
            },
        })
    except ValueError as e:
        await ws.send_json({"type": "error", "message": str(e)})


async def _handle_command(session: GameSession, ws: WebSocket, data: dict):
    """Handle slash commands."""
    cmd = data.get("command", "").strip().lower()

    if cmd == "/save":
        session.db_session_id = app_state.db.save_session(
            session.game_state, session.db_session_id
        )
        await ws.send_json({
            "type": "system",
            "text": f"Session saved (ID: {session.db_session_id})",
        })
    elif cmd == "/party":
        chars = [json.loads(p.model_dump_json()) for p in session.game_state.players]
        await ws.send_json({"type": "party_info", "characters": chars})
    elif cmd.startswith("/search "):
        query = cmd[8:].strip()
        if app_state.rag_query and query:
            results = app_state.rag_query.search(query, n_results=3)
            await ws.send_json({"type": "search_results", "results": results})
        else:
            await ws.send_json({"type": "error", "message": "No indexed PDFs or empty query"})
    elif cmd.startswith("/module "):
        module = cmd[8:].strip()
        if module == "clear":
            session.game_state.active_module = ""
            await ws.send_json({"type": "system", "text": "Module filter cleared"})
        else:
            session.game_state.active_module = module
            await ws.send_json({"type": "system", "text": f"Module set: {module}"})
    else:
        await ws.send_json({"type": "error", "message": f"Unknown command: {cmd}"})


# ── REST Action Endpoint (non-WebSocket alternative) ────────

@app.post("/sessions/{session_id}/action")
async def player_action(session_id: str, req: PlayerActionRequest):
    """Submit a player action and get DM response (non-streaming)."""
    session = app_state.sessions.get(session_id)
    if not session:
        raise HTTPException(404, "Session not found")

    game_state = session.game_state
    game_state.add_message("player", f"[{req.player_name}]: {req.action}")
    game_state.advance_turn()

    response = session.dm_engine.generate_response(
        game_state, req.action, stream=False,
    )

    game_state.add_message("dm", response)

    return {
        "dm_response": response,
        "turn": game_state.turn_count,
        "game_state": json.loads(game_state.model_dump_json()),
    }


# ── Entry Point ─────────────────────────────────────────────

def main():
    """CLI entry point for the server."""
    config = load_config()
    server_config = config.get("server", {})
    host = server_config.get("host", "0.0.0.0")
    port = server_config.get("port", 8000)

    print(f"\n  AI Dungeon Master Server v0.2.0")
    print(f"  Listening on {host}:{port}")
    print(f"  WebSocket: ws://{host}:{port}/ws/game/{{session_id}}")
    print(f"  API docs: http://{host}:{port}/docs\n")

    uvicorn.run(
        "src.server:app",
        host=host,
        port=port,
        reload=False,
        log_level="info",
    )


if __name__ == "__main__":
    main()
