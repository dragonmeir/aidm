"""ChromaDB vector store wrapper."""

import os
import chromadb
from chromadb.config import Settings


class VectorStore:
    """Manages the ChromaDB vector store for PDF content."""

    def __init__(self, persist_dir: str = "data/chroma_db"):
        self.persist_dir = persist_dir
        os.makedirs(persist_dir, exist_ok=True)
        self.client = chromadb.PersistentClient(
            path=persist_dir,
            settings=Settings(anonymized_telemetry=False),
        )
        self.collection = self.client.get_or_create_collection(
            name="rpg_documents",
            metadata={"hnsw:space": "cosine"},
        )

    def add_documents(
        self,
        texts: list[str],
        metadatas: list[dict],
        ids: list[str],
        embeddings: list[list[float]],
    ) -> None:
        """Add document chunks with embeddings."""
        # ChromaDB has a batch limit, process in chunks of 5000
        batch_size = 5000
        for i in range(0, len(texts), batch_size):
            end = min(i + batch_size, len(texts))
            self.collection.add(
                documents=texts[i:end],
                metadatas=metadatas[i:end],
                ids=ids[i:end],
                embeddings=embeddings[i:end],
            )

    def query(
        self,
        query_embedding: list[float],
        n_results: int = 5,
        where: dict | None = None,
    ) -> dict:
        """Query the vector store for similar documents."""
        kwargs = {
            "query_embeddings": [query_embedding],
            "n_results": n_results,
            "include": ["documents", "metadatas", "distances"],
        }
        if where:
            kwargs["where"] = where
        return self.collection.query(**kwargs)

    def count(self) -> int:
        """Return the number of documents in the store."""
        return self.collection.count()

    def clear(self) -> None:
        """Delete all documents from the store."""
        self.client.delete_collection("rpg_documents")
        self.collection = self.client.get_or_create_collection(
            name="rpg_documents",
            metadata={"hnsw:space": "cosine"},
        )
