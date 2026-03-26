"""Library management — organize PDFs into rulesets and modules.

Each PDF gets tagged as 'rules', 'module', or 'both' and assigned to a
named collection (e.g., "ose" for rules, "xyntillan" for a module).
Sessions pick a rules collection + module collection at creation time.

The library is system-aware: entries are tagged with a system ID that
links to the extracted RuleSystem definitions in data/systems/.
"""

import json
import os
from pathlib import Path
from pydantic import BaseModel, Field

PROJECT_ROOT = Path(__file__).resolve().parent.parent
LIBRARY_PATH = PROJECT_ROOT / "data" / "library.json"


class LibraryEntry(BaseModel):
    """A PDF or group of PDFs in the library."""
    name: str                          # e.g., "ose", "xyntillan", "ad&d-1e"
    display_name: str                  # e.g., "Old-School Essentials", "Castle Xyntillan"
    entry_type: str                    # "rules", "module", or "both"
    system: str = ""                   # game system tag, e.g., "ose", "coc7e", "forbidden-lands"
    pdf_files: list[str] = Field(default_factory=list)  # relative or absolute paths
    description: str = ""
    briefing: str = ""                 # pre-digested summary for the DM
    # For modules: key facts the DM must know
    setting: str = ""                  # e.g., "Castle on a lake in the mountains"
    starting_location: str = ""        # e.g., "Tours-en-Savoy"
    # Intro search queries for context building (system/module specific)
    intro_queries: list[str] = Field(default_factory=list)
    # Compatible systems (for modules that work with multiple systems)
    compatible_systems: list[str] = Field(default_factory=list)
    # Source labels used when this entry's PDFs were ingested.
    # Populated during ingestion. Used for exact RAG source filtering.
    source_labels: list[str] = Field(default_factory=list)


class Library(BaseModel):
    """The full library of available rulesets and modules."""
    entries: dict[str, LibraryEntry] = Field(default_factory=dict)

    def rules(self) -> dict[str, LibraryEntry]:
        return {k: v for k, v in self.entries.items() if v.entry_type in ("rules", "both")}

    def modules(self) -> dict[str, LibraryEntry]:
        return {k: v for k, v in self.entries.items() if v.entry_type in ("module", "both")}

    def rules_for_system(self, system: str) -> list[LibraryEntry]:
        return [v for v in self.entries.values()
                if v.entry_type in ("rules", "both") and v.system == system]

    def modules_for_system(self, system: str) -> list[LibraryEntry]:
        """Get modules compatible with a system (matches system tag or compatible_systems list)."""
        results = []
        for v in self.entries.values():
            if v.entry_type not in ("module", "both"):
                continue
            if v.system == system:
                results.append(v)
            elif system in v.compatible_systems:
                results.append(v)
        return results

    def systems_in_use(self) -> list[str]:
        """Get unique system tags across all entries."""
        systems = set()
        for v in self.entries.values():
            if v.system:
                systems.add(v.system)
        return sorted(systems)

    def has_system_definition(self, system: str) -> bool:
        """Check if a RuleSystem YAML exists for the given system tag."""
        system_dir = PROJECT_ROOT / "data" / "systems" / system
        return (system_dir / "system.yaml").exists()

    def get_entry_for_module(self, module_name: str) -> LibraryEntry | None:
        """Find a library entry by display name or key (case-insensitive)."""
        name_lower = module_name.lower()
        for key, entry in self.entries.items():
            if (name_lower == key.lower()
                    or name_lower in entry.display_name.lower()
                    or name_lower in entry.name.lower()):
                return entry
        return None

    def get_intro_queries(self, module_name: str) -> list[str]:
        """Get intro search queries for a module.

        Returns module-specific queries if defined, otherwise generates
        generic queries from the module's setting/starting_location data.
        """
        entry = self.get_entry_for_module(module_name)
        if not entry:
            return []

        # Use custom queries if defined
        if entry.intro_queries:
            return entry.intro_queries

        # Auto-generate from module metadata
        queries = []
        if entry.starting_location:
            queries.append(f"{entry.starting_location} town shops tavern inn NPCs")
        if entry.display_name:
            queries.append(f"rumors about {entry.display_name} hooks adventure leads")
            queries.append(f"{entry.display_name} retainers hirelings available")
        if entry.setting:
            queries.append(f"{entry.setting} approach entrance")
        else:
            queries.append(f"{entry.display_name} entrance approach overview")

        return queries


def load_library() -> Library:
    """Load library from disk."""
    if LIBRARY_PATH.exists():
        with open(LIBRARY_PATH) as f:
            data = json.load(f)
        entries = {k: LibraryEntry(**v) for k, v in data.get("entries", {}).items()}
        return Library(entries=entries)
    return Library()


def save_library(lib: Library) -> None:
    """Save library to disk."""
    LIBRARY_PATH.parent.mkdir(parents=True, exist_ok=True)
    data = {"entries": {k: v.model_dump() for k, v in lib.entries.items()}}
    with open(LIBRARY_PATH, "w") as f:
        json.dump(data, f, indent=2)


def generate_briefing_prompt(module_name: str, chunks: list[str], system_name: str = "", genre: str = "") -> str:
    """Build a prompt to generate a module briefing from RAG chunks.

    Adapts the prompt based on the game system's genre for better results:
    - Fantasy: focuses on dungeons, treasure, monsters, taverns
    - Horror: focuses on investigations, clues, sanity, NPCs
    - Sci-fi: focuses on locations, factions, technology, missions
    """
    combined = "\n\n---\n\n".join(chunks[:15])

    # Genre-specific briefing structure
    if genre and "horror" in genre.lower():
        sections = """The briefing must include:
1. SETTING — where the scenario takes place (exact location names, time period)
2. STARTING SITUATION — how the investigators get involved, the initial hook
3. KEY NPCs — important characters, their names, roles, motivations, and any stats
4. KEY LOCATIONS — the major locations with brief descriptions
5. THE MYSTERY — the core mystery or threat (spoilers OK, this is for the GM)
6. CLUES — key clues the investigators can find, and where they lead
7. SANITY THREATS — any sanity-affecting encounters or revelations
8. TIMELINE — what happens if the investigators don't intervene
9. IMPORTANT RULES — any special rules for this scenario"""
    elif genre and "sci" in genre.lower():
        sections = """The briefing must include:
1. SETTING — where the adventure takes place (system, planet, station, time period)
2. STARTING SITUATION — the mission or situation the characters face
3. KEY NPCs — important characters, their names, affiliations, motivations, and any stats
4. KEY LOCATIONS — the major locations with brief descriptions
5. FACTIONS — any groups or organizations involved and their goals
6. THREATS — dangers, enemies, environmental hazards
7. REWARDS — payment, salvage, information, or other rewards
8. IMPORTANT RULES — any special rules for this adventure"""
    else:
        sections = """The briefing must include:
1. SETTING — where the adventure takes place (exact location names)
2. STARTING LOCATION — the town/village name and ALL named establishments (shops, taverns, NPCs with their classes/levels)
3. KEY NPCs — the important characters, their names, motivations, and stats if given
4. KEY LOCATIONS — the major areas of the adventure site with brief descriptions
5. RUMORS — any rumors or hooks mentioned in the text, marked (T)rue, (F)alse, or (P)artially true
6. MAJOR TREASURES — any significant treasure or artifacts mentioned
7. IMPORTANT RULES — any special rules for this module (e.g., curses, special encounters)"""

    system_note = f" (for the {system_name} system)" if system_name else ""

    return f"""Read the following excerpts from the adventure module "{module_name}"{system_note} and write a GM briefing document.

{sections}

CRITICAL: Use ONLY information from the excerpts below. Do NOT invent anything.
At the end, add a section called "LOCATIONS THAT EXIST" listing every named place, and a note saying "There are NO other named locations. Do not invent any."

--- MODULE EXCERPTS ---
{combined}
--- END EXCERPTS ---

Write the GM briefing now:"""


# ── Pre-seed with current data ──────────────────────────────

def init_default_library() -> Library:
    """Create a default library from the current config and existing data.

    Populates the library with OSE rules and any existing modules on first run.
    On subsequent loads, ensures existing entries get new fields (intro_queries, etc.)
    if they were created before the universal system update.
    """
    lib = load_library()

    if lib.entries:
        # Backfill new fields on existing entries if missing
        _backfill_entries(lib)
        return lib

    # Seed with OSE rules
    lib.entries["ose"] = LibraryEntry(
        name="ose",
        display_name="Old-School Essentials",
        entry_type="rules",
        system="ose",
        pdf_files=[
            "OSR/Old-School Essentials/Old-School Essentials Classic Fantasy Rules Tome [1.3].pdf",
            "OSR/Old-School Essentials/Old-School Essentials Classic Fantasy Monsters [1.0].pdf",
            "OSR/Old-School Essentials/Old-School Essentials Classic Fantasy Treasures [1.0].pdf",
            "OSR/Old-School Essentials/Old-School Essentials Classic Fantasy Cleric and Magic-User Spells [1.0].pdf",
        ],
        description="B/X D&D rules as presented in Old-School Essentials Classic Fantasy.",
    )

    # Seed with Xyntillan module
    briefing_path = PROJECT_ROOT / "data" / "maps" / "xyntillan" / "module_briefing.md"
    briefing = ""
    if briefing_path.exists():
        briefing = briefing_path.read_text()

    lib.entries["xyntillan"] = LibraryEntry(
        name="xyntillan",
        display_name="Castle Xyntillan",
        entry_type="module",
        system="ose",
        pdf_files=[
            "OSR/Castle Xyntillan (S+W)/EMDT60 Castle Xyntillan (SW).pdf",
            "OSR/Castle Xyntillan (S+W)/EMDT60 Castle Xyntillan GM's Worksheet.pdf",
        ],
        description="A haunted castle crawl for levels 1-6. The Malévol family's crumbling castle on a crystal-clear lake.",
        briefing=briefing,
        setting="Valley of the Three Rainbows, mountain lake",
        starting_location="Tours-en-Savoy",
        intro_queries=[
            "Tours-en-Savoy town shops tavern inn NPCs",
            "rumors about the castle hooks adventure leads",
            "retainers hirelings men at arms available",
            "castle approach entrance gatehouse grounds",
        ],
    )

    save_library(lib)
    return lib


def _backfill_entries(lib: Library) -> None:
    """Add new fields to existing library entries created before the universal update."""
    changed = False

    for key, entry in lib.entries.items():
        # Add intro_queries for xyntillan if missing
        if key == "xyntillan" and not entry.intro_queries:
            entry.intro_queries = [
                "Tours-en-Savoy town shops tavern inn NPCs",
                "rumors about the castle hooks adventure leads",
                "retainers hirelings men at arms available",
                "castle approach entrance gatehouse grounds",
            ]
            changed = True

    if changed:
        save_library(lib)
