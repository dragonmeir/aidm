"""Core DM engine - LLM interaction via Ollama."""

import ollama

from ..game.state import GameState
from ..rag.query import RAGQuery
from .prompts import SYSTEM_PROMPT, ADVENTURE_START_PROMPT
from .context import ContextManager


class DMEngine:
    """The AI Dungeon Master brain - connects to Ollama for LLM responses."""

    def __init__(
        self,
        model: str = "mistral",
        base_url: str = "http://localhost:11434",
        temperature: float = 0.8,
        context_length: int = 8192,
        rag_query: RAGQuery | None = None,
        top_k: int = 5,
    ):
        self.model = model
        self.temperature = temperature
        self.context_length = context_length
        self.context_manager = ContextManager(rag_query=rag_query, top_k=top_k)
        self.system_prompt = SYSTEM_PROMPT

        # Configure Ollama client
        self.client = ollama.Client(host=base_url)

    def generate_response(
        self,
        game_state: GameState,
        player_input: str,
        extra_context: str = "",
        stream: bool = True,
    ):
        """Generate a DM response. Yields chunks if streaming, else returns full text."""
        context = self.context_manager.build_context(
            game_state=game_state,
            player_input=player_input,
            extra_context=extra_context,
        )

        messages = [
            {"role": "system", "content": self.system_prompt},
            {"role": "user", "content": context},
        ]

        if stream:
            return self._stream_response(messages)
        else:
            return self._full_response(messages)

    def _stream_response(self, messages: list[dict]):
        """Yield response chunks for streaming display."""
        response = self.client.chat(
            model=self.model,
            messages=messages,
            stream=True,
            options={
                "temperature": self.temperature,
                "num_ctx": self.context_length,
            },
        )
        for chunk in response:
            # Handle both dict and typed object responses
            if isinstance(chunk, dict):
                content = chunk.get("message", {}).get("content", "")
            else:
                content = getattr(getattr(chunk, "message", None), "content", "")
            if content:
                yield content

    def _full_response(self, messages: list[dict]) -> str:
        """Get complete response at once."""
        response = self.client.chat(
            model=self.model,
            messages=messages,
            stream=False,
            options={
                "temperature": self.temperature,
                "num_ctx": self.context_length,
            },
        )
        if isinstance(response, dict):
            return response["message"]["content"]
        return response.message.content

    def start_adventure(self, game_state: GameState, stream: bool = True):
        """Generate the opening scene for a new adventure."""
        return self.generate_response(
            game_state=game_state,
            player_input=ADVENTURE_START_PROMPT,
            stream=stream,
        )

    def check_connection(self) -> bool:
        """Test if Ollama is reachable and the model is available."""
        try:
            response = self.client.list()
            # Handle both dict (old) and typed object (new) ollama client
            if hasattr(response, "models"):
                models_list = response.models
            else:
                models_list = response.get("models", [])

            available = []
            for m in models_list:
                name = getattr(m, "model", None) or (m.get("name", "") if isinstance(m, dict) else "")
                available.append(name)

            return any(self.model in name for name in available)
        except Exception:
            return False
