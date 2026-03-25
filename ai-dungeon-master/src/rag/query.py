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
    ) -> list[dict]:
        """Search for relevant content.

        Returns list of dicts with 'text', 'source', 'distance' keys.
        """
        query_embedding = self.embed_model.encode(query).tolist()

        where = None
        if source_filter:
            where = {"source": {"$contains": source_filter}}

        results = self.store.query(
            query_embedding=query_embedding,
            n_results=n_results,
            where=where,
        )

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
    ) -> str:
        """Get RAG results formatted as a context string for the LLM."""
        results = self.search(query, n_results, source_filter)
        if not results:
            return ""

        parts = ["[Reference Material]"]
        for r in results:
            parts.append(f"--- From: {r['source']} ---")
            parts.append(r["text"])
        parts.append("[End Reference Material]")
        return "\n".join(parts)
