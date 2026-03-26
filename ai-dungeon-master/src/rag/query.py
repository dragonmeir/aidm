"""RAG query layer - search indexed content."""

from sentence_transformers import SentenceTransformer
from .store import VectorStore


class RAGQuery:
    """Queries the vector store for relevant RPG content."""

    def __init__(
        self,
        store: VectorStore,
        embedding_model_name: str = "all-MiniLM-L6-v2",
    ):
        self.store = store
        self.embed_model = SentenceTransformer(embedding_model_name)

    def search(
        self,
        query: str,
        n_results: int = 5,
        source_filter: str | None = None,
        source_labels: list[str] | None = None,
    ) -> list[dict]:
        """Search for relevant content.

        Filtering priority:
        1. source_labels (exact match list) — most precise, used when we know
           the exact source strings from a library entry's ingestion record.
        2. source_filter (substring match) — fallback for fuzzy matching.
        3. No filter — returns any matching content.
        """
        query_embedding = self.embed_model.encode(query).tolist()

        # Prefer exact source_labels matching when available
        if source_labels:
            results = self._query_with_source_labels(query_embedding, n_results, source_labels)
            if results:
                return results
            # Fall through to substring filter if exact match found nothing

        if source_filter:
            results = self._query_with_filter(query_embedding, n_results, source_filter)
            if results:
                return results
            return self._query_and_boost(query_embedding, n_results, source_filter)

        return self._query_raw(query_embedding, n_results)

    def _query_with_source_labels(self, embedding: list[float], n: int, labels: list[str]) -> list[dict]:
        """Filter to chunks whose source exactly matches one of the given labels."""
        # Fetch extra results and filter locally — more reliable than ChromaDB where clauses
        raw = self._query_raw(embedding, n * 5)
        if not raw:
            return []
        labels_lower = {l.lower() for l in labels}
        matching = [r for r in raw if r["source"].lower() in labels_lower]
        return matching[:n]

    def _query_with_filter(self, embedding: list[float], n: int, source_filter: str) -> list[dict]:
        """Try ChromaDB's where filter."""
        try:
            results = self.store.query(
                query_embedding=embedding,
                n_results=n,
                where={"source": {"$contains": source_filter}},
            )
            return self._parse_results(results)
        except Exception:
            return []

    def _query_and_boost(self, embedding: list[float], n: int, source_filter: str) -> list[dict]:
        """Search without filter, then sort to prioritize matching sources."""
        # Fetch more results than needed so we can filter/rerank
        results = self._query_raw(embedding, n * 3)
        if not results:
            return []

        filter_lower = source_filter.lower()

        # Split into matching and non-matching
        matching = [r for r in results if filter_lower in r["source"].lower()]
        others = [r for r in results if filter_lower not in r["source"].lower()]

        # Return matching first, fill with others up to n
        combined = matching + others
        return combined[:n]

    def _query_raw(self, embedding: list[float], n: int) -> list[dict]:
        """Query without any source filter."""
        results = self.store.query(
            query_embedding=embedding,
            n_results=n,
        )
        return self._parse_results(results)

    def _parse_results(self, results: dict) -> list[dict]:
        """Parse ChromaDB results into a list of dicts."""
        if not results["documents"] or not results["documents"][0]:
            return []

        output = []
        for doc, meta, dist in zip(
            results["documents"][0],
            results["metadatas"][0],
            results["distances"][0],
        ):
            output.append({
                "text": doc,
                "source": meta.get("source", "Unknown"),
                "distance": dist,
            })
        return output

    def get_context_string(
        self,
        query: str,
        n_results: int = 5,
        source_filter: str | None = None,
        source_labels: list[str] | None = None,
    ) -> str:
        """Get RAG results formatted as a context string for the LLM."""
        results = self.search(query, n_results, source_filter, source_labels=source_labels)
        if not results:
            return ""

        parts = ["[Reference Material]"]
        for r in results:
            parts.append(f"--- From: {r['source']} ---")
            parts.append(r["text"])
        parts.append("[End Reference Material]")
        return "\n".join(parts)
