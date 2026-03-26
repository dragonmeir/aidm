"""Core DM engine - LLM interaction via Ollama with tool-calling support."""

import ollama

from ..game.state import GameState
from ..rag.query import RAGQuery
from ..systems.schema import RuleSystem
from .prompts import SYSTEM_PROMPT, ADVENTURE_START_PROMPT
from .prompt_builder import PromptBuilder
from .context import ContextManager
from .tools import DMToolkit, parse_tool_calls, process_dm_output, ToolResult


class DMEngine:
    """The AI Dungeon Master brain - connects to Ollama and executes game mechanics."""

    def __init__(
        self,
        model: str = "mistral",
        base_url: str = "http://localhost:11434",
        temperature: float = 0.8,
        context_length: int = 8192,
        rag_query: RAGQuery | None = None,
        top_k: int = 5,
        rule_system: RuleSystem | None = None,
    ):
        self.model = model
        self.temperature = temperature
        self.context_length = context_length
        self.context_manager = ContextManager(rag_query=rag_query, top_k=top_k)
        self.client = ollama.Client(host=base_url)
        self._toolkit: DMToolkit | None = None
        self.rule_system = rule_system
        self._prompt_builder = PromptBuilder() if rule_system else None

    def _get_system_prompt(self, toolkit: DMToolkit) -> str:
        """Build full system prompt with tool descriptions.

        Uses PromptBuilder when a RuleSystem is loaded, falls back to
        hardcoded OSE prompt otherwise.
        """
        if self._prompt_builder and self.rule_system:
            return self._prompt_builder.build_system_prompt(
                self.rule_system, toolkit.get_tool_descriptions()
            )
        return SYSTEM_PROMPT.replace("{tool_descriptions}", toolkit.get_tool_descriptions())

    def generate_response(
        self,
        game_state: GameState,
        player_input: str,
        extra_context: str = "",
        stream: bool = True,
    ):
        """Generate a DM response with tool execution.

        When streaming, yields chunks. Tool calls are buffered, executed,
        and their results injected into the stream.
        """
        if self.rule_system:
            toolkit = DMToolkit.from_system(game_state, self.rule_system)
        else:
            toolkit = DMToolkit(game_state)
        self._toolkit = toolkit

        context = self.context_manager.build_context(
            game_state=game_state,
            player_input=player_input,
            extra_context=extra_context,
        )

        messages = [
            {"role": "system", "content": self._get_system_prompt(toolkit)},
            {"role": "user", "content": context},
        ]

        if stream:
            return self._stream_with_tools(messages, toolkit)
        else:
            return self._full_with_tools(messages, toolkit)

    def _stream_with_tools(self, messages: list[dict], toolkit: DMToolkit):
        """Stream response, buffering for tool calls and executing them inline."""
        response = self.client.chat(
            model=self.model,
            messages=messages,
            stream=True,
            options={
                "temperature": self.temperature,
                "num_ctx": self.context_length,
            },
        )

        buffer = ""
        for chunk in response:
            if isinstance(chunk, dict):
                content = chunk.get("message", {}).get("content", "")
            else:
                content = getattr(getattr(chunk, "message", None), "content", "")

            if not content:
                continue

            buffer += content

            # Check if we have a complete tool call in the buffer
            if "[[TOOL:" in buffer:
                # Wait until the tool call is complete (closing ]])
                if "]]" in buffer[buffer.index("[[TOOL:"):]:
                    # Process the buffer - emit text before tool call, execute tool, emit result
                    processed, results = process_dm_output(buffer, toolkit)
                    yield processed
                    buffer = ""
                # Otherwise keep buffering
            else:
                # No tool call in progress, emit what we have
                yield buffer
                buffer = ""

        # Flush remaining buffer
        if buffer:
            processed, results = process_dm_output(buffer, toolkit)
            yield processed

    def _full_with_tools(self, messages: list[dict], toolkit: DMToolkit) -> str:
        """Get complete response and process all tool calls."""
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
            raw = response["message"]["content"]
        else:
            raw = response.message.content

        processed, results = process_dm_output(raw, toolkit)
        return processed

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

    @property
    def toolkit(self) -> DMToolkit | None:
        return self._toolkit
