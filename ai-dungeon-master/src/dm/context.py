"""Context manager - assembles the full prompt for the LLM."""

import json
from pathlib import Path

from ..game.state import GameState
from ..rag.query import RAGQuery
from .prompts import CONTEXT_TEMPLATE

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent


class ContextManager:
    """Assembles context for LLM calls from game state, RAG, and history."""

    def __init__(self, rag_query: RAGQuery | None = None, top_k: int = 5):
        self.rag_query = rag_query
        self.top_k = top_k
        self._map_cache: dict[str, dict] = {}
        self._vision_cache: dict[str, str] = {}
        self._briefing_cache: dict[str, str] = {}
        self.vision = None
        self.library = None  # Set by server — the Library object

    def _get_library_entry(self, game_state) -> "LibraryEntry | None":
        """Get the library entry for the current module, using module_key first."""
        if not self.library:
            return None
        # Direct key lookup (reliable)
        if game_state.module_key:
            entry = self.library.entries.get(game_state.module_key)
            if entry:
                return entry
        # Fallback: fuzzy match on active_module display name
        if game_state.active_module:
            return self.library.get_entry_for_module(game_state.active_module)
        return None

    def _get_source_labels(self, game_state) -> list[str]:
        """Get the source labels for RAG filtering from the library entry."""
        entry = self._get_library_entry(game_state)
        if entry and entry.source_labels:
            return entry.source_labels
        return []

    def _load_briefing(self, game_state) -> str:
        """Load the pre-digested module briefing. Always included in context.

        Uses module_key for direct library lookup, falls back to fuzzy matching.
        """
        module = game_state.active_module
        if not module:
            return ""

        cache_key = game_state.module_key or module
        if cache_key in self._briefing_cache:
            return self._briefing_cache[cache_key]

        # Direct library lookup via module_key (preferred)
        entry = self._get_library_entry(game_state)
        if entry and entry.briefing:
            self._briefing_cache[cache_key] = entry.briefing
            return entry.briefing

        # Fallback: check for briefing files on disk
        maps_dir = PROJECT_ROOT / "data" / "maps"
        if maps_dir.exists():
            # Try module_key as directory name first
            for dir_name in [game_state.module_key, module]:
                if not dir_name:
                    continue
                for module_dir in maps_dir.iterdir():
                    if module_dir.is_dir():
                        briefing_file = module_dir / "module_briefing.md"
                        if briefing_file.exists():
                            if (dir_name.lower() == module_dir.name.lower()
                                    or dir_name.lower() in module_dir.name.lower()):
                                text = briefing_file.read_text()
                                self._briefing_cache[cache_key] = text
                                return text
        return ""

    def _load_map_data(self, module: str) -> dict | None:
        """Load the room graph for a module."""
        if module in self._map_cache:
            return self._map_cache[module]

        # Try to find map data by module name
        maps_dir = PROJECT_ROOT / "data" / "maps"
        if not maps_dir.exists():
            return None

        for module_dir in maps_dir.iterdir():
            if module_dir.is_dir():
                data_file = module_dir / "map_data.json"
                if data_file.exists():
                    with open(data_file) as f:
                        data = json.load(f)
                    if module.lower() in data.get("module", "").lower():
                        self._map_cache[module] = data
                        return data

        return None

    def _get_room_context(self, game_state: GameState) -> str:
        """Get spatial context for the current location from the room graph."""
        if not game_state.active_module:
            return ""

        map_data = self._load_map_data(game_state.active_module)
        if not map_data:
            return ""

        rooms = map_data.get("rooms", {})
        location = game_state.current_location

        # Try to match current location to a room ID
        current_room = None
        current_id = None
        for rid, room in rooms.items():
            if rid == location or rid in location or room["name"].lower() in location.lower():
                current_room = room
                current_id = rid
                break

        if not current_room:
            return ""

        # Build spatial context
        lines = [f"## Current Room: {current_id}. {current_room['name']}"]
        lines.append(f"Section: {current_room['section']} ({current_room['floor']} floor)")
        lines.append(f"Size: {current_room['size']}")

        # Features
        features = current_room.get("features", {})
        feature_tags = []
        if features.get("secret_door"):
            feature_tags.append("SECRET DOOR")
        if features.get("trap"):
            feature_tags.append("TRAP")
        if features.get("monster"):
            feature_tags.append("MONSTER")
        if features.get("treasure"):
            feature_tags.append("TREASURE")
        if features.get("npc"):
            feature_tags.append("NPC")
        if features.get("stairs"):
            feature_tags.append("STAIRS/LEVEL CHANGE")
        if feature_tags:
            lines.append(f"Features: {', '.join(feature_tags)}")

        # Connected rooms
        connections = current_room.get("connections", [])
        if connections:
            conn_descs = []
            for cid in connections:
                if cid in rooms:
                    conn_descs.append(f"  {cid}. {rooms[cid]['name']} ({rooms[cid]['section']}, {rooms[cid]['floor']})")
                else:
                    conn_descs.append(f"  {cid}")
            lines.append("Connected rooms:")
            lines.extend(conn_descs)

        # Nearby rooms in same section (adjacent by number)
        prefix = current_id[0] if current_id else ""
        num_match = None
        import re
        num_match = re.search(r'(\d+)', current_id) if current_id else None
        if prefix and num_match:
            num = int(num_match.group(1))
            nearby = []
            for offset in [-2, -1, 1, 2]:
                nid = f"{prefix}{num + offset}"
                if nid in rooms and nid not in connections and nid != current_id:
                    nearby.append(f"  {nid}. {rooms[nid]['name']}")
            if nearby:
                lines.append("Nearby rooms (same section):")
                lines.extend(nearby)

        # Visited rooms for reference
        visited_rooms = [v for v in game_state.visited_locations if v in rooms]
        if visited_rooms:
            lines.append(f"Previously visited: {', '.join(visited_rooms[-10:])}")

        # Vision analysis of the current floor's map
        floor = current_room.get("floor", "")
        if floor and self.vision:
            vision_text = self._get_vision_for_floor(floor, current_room.get("map", ""), game_state.active_module, map_data)
            if vision_text:
                lines.append(f"\n## Map Analysis ({floor} floor):")
                lines.append(vision_text)

        return "\n".join(lines)

    def _get_vision_for_floor(self, floor: str, map_file: str, module: str, map_data: dict) -> str:
        """Get or generate vision analysis for a floor's map."""
        cache_key = f"{module}:{floor}"
        if cache_key in self._vision_cache:
            return self._vision_cache[cache_key]

        if not self.vision or not map_file:
            return ""

        # Find the module directory
        maps_dir = PROJECT_ROOT / "data" / "maps"
        image_path = None
        for module_dir in maps_dir.iterdir():
            if module_dir.is_dir():
                candidate = module_dir / map_file
                if candidate.exists():
                    image_path = str(candidate)
                    break

        if not image_path:
            return ""

        # Find the floor label from map data
        floor_label = floor
        for mk, mv in map_data.get("maps", {}).items():
            if mv.get("file") == map_file:
                floor_label = mv.get("label", floor)
                break

        module_name = map_data.get("module", module)
        analysis = self.vision.analyze_map(image_path, floor_label, module_name)
        self._vision_cache[cache_key] = analysis
        return analysis

    def build_context(
        self,
        game_state: GameState,
        player_input: str,
        extra_context: str = "",
        max_chars: int = 20000,
    ) -> str:
        """Build the full context string for the LLM.

        max_chars limits total context to fit within model's token window.
        ~20K chars ≈ ~5K tokens, leaving room for system prompt + tools.
        """

        # Module briefing ALWAYS goes first — this is the DM's essential knowledge
        briefing = ""
        if game_state.active_module:
            briefing = self._load_briefing(game_state)

        # RAG pulls situation-specific content
        rag_context = self._get_rag_context(game_state, player_input)

        # Room graph context for spatial awareness
        room_context = self._get_room_context(game_state)
        if room_context:
            rag_context = f"{room_context}\n\n{rag_context}" if rag_context else room_context

        if extra_context:
            rag_context = f"{extra_context}\n\n{rag_context}" if rag_context else extra_context

        # Combine: briefing first, then RAG details
        if briefing:
            full_reference = f"{briefing}\n\n{rag_context}" if rag_context else briefing
        else:
            full_reference = rag_context

        # Truncate to fit token budget
        # Reserve ~4000 chars for game state + history + player input + template
        rag_budget = max_chars - 4000
        if full_reference and len(full_reference) > rag_budget:
            # Keep the full briefing, truncate the RAG part
            if briefing and len(briefing) < rag_budget:
                remaining = rag_budget - len(briefing) - 10
                if rag_context and remaining > 200:
                    full_reference = briefing + "\n\n" + rag_context[:remaining] + "\n[...truncated...]"
                else:
                    full_reference = briefing
            else:
                full_reference = full_reference[:rag_budget] + "\n[...truncated...]"

        rag_context = full_reference

        # Format recent history (last 6 messages to save tokens)
        recent = game_state.history[-6:]
        history_lines = []
        for msg in recent:
            role = msg["role"].upper()
            # Truncate long messages in history
            content = msg['content'][:500] if len(msg['content']) > 500 else msg['content']
            history_lines.append(f"{role}: {content}")
        recent_history = "\n".join(history_lines) if history_lines else "(Session just started)"

        return CONTEXT_TEMPLATE.format(
            game_state=game_state.get_state_summary(),
            rag_context=rag_context or "(No reference material found)",
            recent_history=recent_history,
            player_input=player_input,
        )

    def _get_rag_context(self, game_state: GameState, player_input: str) -> str:
        """Pull relevant content from the RAG store.

        Uses source_labels from the library entry for precise filtering
        (only chunks from this module's PDFs). Falls back to display_name
        substring matching if no source_labels are available.
        """
        if not self.rag_query:
            return ""

        search_query = player_input
        if game_state.current_location != "Unknown":
            search_query = f"{game_state.current_location} {player_input}"

        # Get precise source labels from library entry
        source_labels = self._get_source_labels(game_state)
        # Fallback to display_name substring filter
        source_filter = game_state.active_module if game_state.active_module else None

        # Also include the rules system's source labels for rule lookups
        rules_labels = self._get_rules_source_labels(game_state)
        all_labels = source_labels + rules_labels if source_labels else None

        # At adventure start, do broad multi-query to pull in module context
        if game_state.turn_count == 0 and game_state.active_module:
            return self._multi_query_intro(game_state, source_labels, source_filter)

        # During combat, also search for monster/room specifics
        if game_state.in_combat and game_state.current_location != "Unknown":
            combat_context = self.rag_query.get_context_string(
                query=f"{game_state.current_location} combat encounter monsters",
                n_results=3,
                source_filter=source_filter,
                source_labels=all_labels,
            )
            general_context = self.rag_query.get_context_string(
                query=search_query,
                n_results=self.top_k,
                source_filter=source_filter,
                source_labels=all_labels,
            )
            parts = [p for p in [general_context, combat_context] if p]
            return "\n\n".join(parts)

        return self.rag_query.get_context_string(
            query=search_query,
            n_results=self.top_k,
            source_filter=source_filter,
            source_labels=all_labels,
        )

    def _get_rules_source_labels(self, game_state) -> list[str]:
        """Get source labels for the session's rule system PDFs."""
        if not self.library or not game_state.system_id:
            return []
        rules_entries = self.library.rules_for_system(game_state.system_id)
        labels = []
        for entry in rules_entries:
            labels.extend(entry.source_labels)
        return labels

    def _multi_query_intro(self, game_state, source_labels: list[str] | None,
                           source_filter: str | None) -> str:
        """Pull the module's starting content using data-driven queries.

        Uses source_labels for precise scoping to this module's PDFs only.
        """
        module = game_state.active_module
        queries = []

        # Get module-specific queries from the library
        if self.library:
            queries = self.library.get_intro_queries(module)

        # Fallback: generic queries
        if not queries:
            queries = [
                f"{module} introduction overview starting location",
                f"{module} NPCs key characters",
                f"{module} rumors hooks leads",
                f"{module} approach entrance beginning",
            ]

        # Also include rules system source labels for rule lookups
        rules_labels = self._get_rules_source_labels(game_state)
        all_labels = (source_labels or []) + rules_labels if source_labels else None

        parts = []
        seen_texts = set()
        for q in queries:
            results = self.rag_query.search(
                q, n_results=2,
                source_filter=source_filter,
                source_labels=all_labels,
            )
            for r in results:
                sig = r["text"][:100]
                if sig not in seen_texts:
                    seen_texts.add(sig)
                    parts.append(f"--- {r['source'][:40]} ---\n{r['text']}")
        return "\n\n".join(parts) if parts else ""
