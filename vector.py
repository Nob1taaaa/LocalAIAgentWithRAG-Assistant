"""Document ingestion and retrieval for the local RAG assistant."""

from __future__ import annotations

import csv
import hashlib
import os
import re
import zipfile
from pathlib import Path
from xml.etree import ElementTree

from langchain_chroma import Chroma
from langchain_core.documents import Document
from langchain_ollama import OllamaEmbeddings


SUPPORTED_EXTENSIONS = {".csv", ".docx", ".md", ".pdf", ".txt"}
_configured_db_directory = Path(os.environ.get("RAG_DB_DIR", "knowledge_base_db")).expanduser()
DB_DIRECTORY = str(
    _configured_db_directory
    if _configured_db_directory.is_absolute()
    else Path(__file__).resolve().parent / _configured_db_directory
)
EMBEDDING_MODEL = os.environ.get("OLLAMA_EMBEDDING_MODEL", "mxbai-embed-large")

embeddings = OllamaEmbeddings(model=EMBEDDING_MODEL)
vector_store = Chroma(
    collection_name="user_knowledge",
    persist_directory=DB_DIRECTORY,
    embedding_function=embeddings,
)


def _split_text(text: str, chunk_size: int = 1400, overlap: int = 200) -> list[str]:
    """Split text into overlapping chunks, preferring paragraph boundaries."""
    text = re.sub(r"\s+", " ", text).strip()
    if not text:
        return []

    chunks: list[str] = []
    start = 0
    while start < len(text):
        end = min(start + chunk_size, len(text))
        if end < len(text):
            boundary = text.rfind(". ", start + chunk_size // 2, end)
            if boundary != -1:
                end = boundary + 1
        chunk = text[start:end].strip()
        if chunk:
            chunks.append(chunk)
        if end >= len(text):
            break
        start = max(end - overlap, start + 1)
    return chunks


def _read_file(path: Path) -> list[tuple[str, dict[str, int]]]:
    """Return text units with optional page or row metadata."""
    suffix = path.suffix.lower()

    if suffix in {".txt", ".md"}:
        return [(path.read_text(encoding="utf-8", errors="replace"), {})]

    if suffix == ".csv":
        with path.open(encoding="utf-8-sig", errors="replace", newline="") as handle:
            rows = []
            for row_number, row in enumerate(csv.DictReader(handle), start=2):
                content = " | ".join(
                    f"{key}: {value}" for key, value in row.items() if value
                )
                if content.strip():
                    rows.append((content, {"row": row_number}))
            return rows

    if suffix == ".pdf":
        try:
            from pypdf import PdfReader
        except ImportError as exc:
            raise RuntimeError("PDF support needs pypdf. Install it with: python3 -m pip install pypdf") from exc
        reader = PdfReader(str(path))
        return [
            (page.extract_text() or "", {"page": page_number})
            for page_number, page in enumerate(reader.pages, start=1)
        ]

    if suffix == ".docx":
        with zipfile.ZipFile(path) as archive:
            xml = ElementTree.fromstring(archive.read("word/document.xml"))
        namespace = {"w": "http://schemas.openxmlformats.org/wordprocessingml/2006/main"}
        paragraphs = []
        for paragraph in xml.findall(".//w:p", namespace):
            text = "".join(node.text or "" for node in paragraph.findall(".//w:t", namespace))
            if text.strip():
                paragraphs.append(text)
        return [("\n".join(paragraphs), {})]

    return []


def _document_id(workspace: str, source_path: str, location: dict[str, int], chunk: str) -> str:
    key = f"{workspace}|{source_path}|{location}|{chunk}"
    return hashlib.sha256(key.encode("utf-8")).hexdigest()


def add_path(path_text: str, workspace: str) -> tuple[int, list[str]]:
    """Index one supported file or every supported file under a directory."""
    path = Path(path_text).expanduser().resolve()
    if not path.exists():
        raise FileNotFoundError(f"Path not found: {path}")

    if path.is_file():
        candidates = [path]
    else:
        candidates = [
            item for item in path.rglob("*")
            if item.is_file()
            and item.suffix.lower() in SUPPORTED_EXTENSIONS
            and not any(part.startswith(".") or part in {"__pycache__", "knowledge_base_db"} for part in item.parts)
        ]

    indexed = 0
    sources: list[str] = []
    for file_path in sorted(candidates):
        if file_path.suffix.lower() not in SUPPORTED_EXTENSIONS:
            continue
        source_path = str(file_path)
        units = _read_file(file_path)
        documents: list[Document] = []
        ids: list[str] = []

        for text, location in units:
            for chunk_number, chunk in enumerate(_split_text(text)):
                metadata = {
                    "workspace": workspace,
                    "source_path": source_path,
                    "source_name": file_path.name,
                    **location,
                    "chunk": chunk_number,
                }
                documents.append(Document(page_content=chunk, metadata=metadata))
                ids.append(_document_id(workspace, source_path, location, chunk))

        if documents:
            # Re-indexing a file replaces its old chunks instead of duplicating them.
            existing = vector_store._collection.get(
                where={"$and": [{"workspace": workspace}, {"source_path": source_path}]},
                include=["metadatas"],
            )
            if existing["ids"]:
                vector_store.delete(ids=existing["ids"])
            vector_store.add_documents(documents=documents, ids=ids)
            indexed += len(documents)
            sources.append(file_path.name)

    return indexed, sources


def retrieve(question: str, workspace: str, limit: int = 5) -> list[Document]:
    """Search a single workspace, or all workspaces when workspace is 'all'."""
    if vector_store._collection.count() == 0:
        return []
    if workspace == "all":
        return vector_store.similarity_search(question, k=limit)
    matches = vector_store._collection.get(where={"workspace": workspace})
    if not matches.get("ids"):
        return []
    return vector_store.similarity_search(
        question,
        k=limit,
        filter={"workspace": workspace},
    )


def list_sources(workspace: str) -> list[dict[str, str | int]]:
    where = None if workspace == "all" else {"workspace": workspace}
    result = vector_store._collection.get(where=where, include=["metadatas"])
    grouped: dict[tuple[str, str], dict[str, str | int]] = {}
    for metadata in result.get("metadatas") or []:
        if not metadata:
            continue
        key = (str(metadata.get("workspace", "general")), str(metadata.get("source_path", "")))
        if key not in grouped:
            grouped[key] = {
                "workspace": key[0],
                "name": str(metadata.get("source_name", Path(key[1]).name)),
                "path": key[1],
                "chunks": 0,
            }
        grouped[key]["chunks"] = int(grouped[key]["chunks"]) + 1
    return sorted(grouped.values(), key=lambda source: (str(source["workspace"]), str(source["name"]).lower()))


def remove_source(source_name: str, workspace: str) -> int:
    """Remove a source by its displayed filename from the chosen workspace."""
    result = vector_store._collection.get(
        where={"$and": [{"workspace": workspace}, {"source_name": source_name}]},
        include=["metadatas"],
    )
    ids = result.get("ids") or []
    if ids:
        vector_store.delete(ids=ids)
    return len(ids)
