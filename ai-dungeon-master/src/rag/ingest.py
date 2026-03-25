"""PDF ingestion pipeline - extract, chunk, embed, store."""

import os
import hashlib
from pathlib import Path

import fitz  # PyMuPDF
from rich.progress import Progress, SpinnerColumn, TextColumn, BarColumn
from rich.console import Console
from sentence_transformers import SentenceTransformer

from .store import VectorStore

console = Console()


def extract_text_from_pdf(pdf_path: str) -> str:
    """Extract all text from a PDF file."""
    try:
        doc = fitz.open(pdf_path)
        text_parts = []
        for page in doc:
            text_parts.append(page.get_text())
        doc.close()
        return "\n".join(text_parts)
    except Exception as e:
        console.print(f"[yellow]Warning: Could not read {pdf_path}: {e}[/yellow]")
        return ""


def chunk_text(text: str, chunk_size: int = 500, overlap: int = 50) -> list[str]:
    """Split text into overlapping chunks by approximate word count."""
    if not text.strip():
        return []

    words = text.split()
    chunks = []
    start = 0

    while start < len(words):
        end = start + chunk_size
        chunk = " ".join(words[start:end])
        if chunk.strip():
            chunks.append(chunk)
        start = end - overlap

    return chunks


def find_pdfs(
    pdf_roots: list[str],
    include_folders: list[str] | None = None,
    include_files: list[str] | None = None,
) -> list[tuple[str, str]]:
    """Find PDF files, searching across multiple root directories.

    Returns list of (full_path, root_dir) tuples so we can make relative labels.
    """
    # Specific files take priority - try each root until found
    if include_files:
        pdfs = []
        for rel_path in include_files:
            found = False
            for root_dir in pdf_roots:
                full_path = os.path.join(root_dir, rel_path)
                if os.path.isfile(full_path):
                    pdfs.append((full_path, root_dir))
                    found = True
                    break
            if not found:
                console.print(f"[yellow]Warning: File not found in any root, skipping: {rel_path}[/yellow]")
        return pdfs

    if include_folders:
        search_dirs = []
        for folder in include_folders:
            for root_dir in pdf_roots:
                full_path = os.path.join(root_dir, folder)
                if os.path.isdir(full_path):
                    search_dirs.append((full_path, root_dir))
                    break
            else:
                console.print(f"[yellow]Warning: Folder not found, skipping: {folder}[/yellow]")
    else:
        search_dirs = [(r, r) for r in pdf_roots]

    pdfs = []
    for search_dir, root_dir in search_dirs:
        for root, _dirs, files in os.walk(search_dir):
            for f in files:
                if f.lower().endswith(".pdf"):
                    pdfs.append((os.path.join(root, f), root_dir))
    return sorted(pdfs, key=lambda x: x[0])


def make_chunk_id(pdf_path: str, chunk_index: int) -> str:
    """Create a deterministic ID for a chunk."""
    path_hash = hashlib.md5(pdf_path.encode()).hexdigest()[:12]
    return f"{path_hash}_{chunk_index:05d}"


def get_source_label(pdf_path: str, base_dir: str) -> str:
    """Get a human-readable source label from the PDF path."""
    rel = os.path.relpath(pdf_path, base_dir)
    # Remove .pdf extension and clean up
    name = Path(rel).stem
    parent = str(Path(rel).parent)
    if parent == ".":
        return name
    return f"{parent}/{name}"


def ingest_pdfs(
    pdf_roots: list[str],
    store: VectorStore,
    embedding_model_name: str = "all-MiniLM-L6-v2",
    chunk_size: int = 500,
    chunk_overlap: int = 50,
    include_folders: list[str] | None = None,
    include_files: list[str] | None = None,
) -> int:
    """Ingest PDFs from one or more root directories into the vector store."""
    if include_files:
        console.print(f"\n[bold cyan]Loading specific PDFs from:[/bold cyan]")
        for root in pdf_roots:
            console.print(f"  [dim]{root}[/dim]")
        for f in include_files:
            console.print(f"  [cyan]- {f}[/cyan]")
    elif include_folders:
        console.print(f"\n[bold cyan]Scanning specific folders:[/bold cyan]")
        for folder in include_folders:
            console.print(f"  [cyan]- {folder}[/cyan]")
    else:
        console.print(f"\n[bold cyan]Scanning ALL PDFs in:[/bold cyan]")
        for root in pdf_roots:
            console.print(f"  [dim]{root}[/dim]")

    pdf_entries = find_pdfs(pdf_roots, include_folders, include_files)
    console.print(f"[green]Found {len(pdf_entries)} PDF files[/green]\n")

    if not pdf_entries:
        return 0

    # Load embedding model
    console.print("[cyan]Loading embedding model...[/cyan]")
    embed_model = SentenceTransformer(embedding_model_name)
    console.print("[green]Embedding model loaded[/green]\n")

    total_chunks = 0
    all_texts = []
    all_metadatas = []
    all_ids = []

    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        BarColumn(),
        TextColumn("[progress.percentage]{task.percentage:>3.0f}%"),
    ) as progress:
        task = progress.add_task("Processing PDFs...", total=len(pdf_entries))

        for pdf_path, root_dir in pdf_entries:
            source_label = get_source_label(pdf_path, root_dir)
            progress.update(task, description=f"Processing: {source_label[:50]}")

            text = extract_text_from_pdf(pdf_path)
            if not text:
                progress.advance(task)
                continue

            chunks = chunk_text(text, chunk_size, chunk_overlap)

            for i, chunk in enumerate(chunks):
                all_texts.append(chunk)
                all_metadatas.append({
                    "source": source_label,
                    "pdf_path": pdf_path,
                    "chunk_index": i,
                })
                all_ids.append(make_chunk_id(pdf_path, i))

            total_chunks += len(chunks)
            progress.advance(task)

    if not all_texts:
        console.print("[yellow]No text extracted from any PDFs.[/yellow]")
        return 0

    # Embed all chunks
    console.print(f"\n[cyan]Embedding {total_chunks} chunks...[/cyan]")
    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        BarColumn(),
        TextColumn("[progress.percentage]{task.percentage:>3.0f}%"),
    ) as progress:
        task = progress.add_task("Generating embeddings...", total=1)
        embeddings = embed_model.encode(all_texts, show_progress_bar=False).tolist()
        progress.update(task, completed=1)

    # Store in ChromaDB
    console.print("[cyan]Storing in vector database...[/cyan]")
    store.clear()
    store.add_documents(all_texts, all_metadatas, all_ids, embeddings)

    console.print(f"\n[bold green]Ingestion complete! {total_chunks} chunks indexed from {len(pdf_entries)} PDFs.[/bold green]")
    return total_chunks
