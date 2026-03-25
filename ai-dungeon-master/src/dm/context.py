"""Context manager - assembles the full prompt for the LLM."""

from ..game.state import GameState
from ..rag.query import RAGQuery
from .prompts import CONTEXT_TEMPLATE


class ContextManager:
    """Assembles context for LLM calls from game state, RAG, and history."""

    def __init__(self, rag_query: RAGQuery | None = None, top_k: int = 5):
        self.rag_query = rag_query
        self.top_k = top_k

    def build_context(
        self,
        game_state: GameState,
        player_input: str,
        extra_context: str = "",
    ) -> str:
        """Build the full context string for the LLM."""

        # Get RAG context based on player input and current situation
        rag_context = ""
        if self.rag_query:
            # Combine player input with location for better RAG results
            search_query = player_input
            if game_state.current_location != "Unknown":
                search_query = f"{game_state.current_location} {player_input}"

            # Search with module filter if one is active
            source_filter = None
            if game_state.active_module:
                source_filter = game_state.active_module

            # Pull more results from the adventure module for richer context
            n = self.top_k

            # At the start of the adventure, do multiple searches to pull
            # in the module's intro, background, and key details
            if game_state.turn_count == 0 and game_state.active_module:
                intro_queries = [
                    f"{game_state.active_module} introduction background",
                    f"{game_state.active_module} town rumors hooks",
                    f"{game_state.active_module} overview map description",
                ]
                parts = []
                for q in intro_queries:
                    result = self.rag_query.get_context_string(
                        query=q, n_results=3, source_filter=source_filter,
                    )
                    if result:
                        parts.append(result)
                rag_context = "\n\n".join(parts)
            else:
                rag_context = self.rag_query.get_context_string(
                    query=search_query,
                    n_results=n,
                    source_filter=source_filter,
                )

        if extra_context:
            rag_context = f"{extra_context}\n\n{rag_context}" if rag_context else extra_context

        # Format recent history (last 10 messages for context window)
        recent = game_state.history[-10:]
        history_lines = []
        for msg in recent:
            role = msg["role"].upper()
            history_lines.append(f"{role}: {msg['content']}")
        recent_history = "\n".join(history_lines) if history_lines else "(Session just started)"

        return CONTEXT_TEMPLATE.format(
            game_state=game_state.get_state_summary(),
            rag_context=rag_context or "(No reference material found)",
            recent_history=recent_history,
            player_input=player_input,
        )
