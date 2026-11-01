"""Document ingestion and retrieval for the local RAG assistant."""

from __future__ import annotations

import csv
import math
import hashlib
import os
import re
import zipfile
from collections import Counter, defaultdict
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
OLLAMA_BASE_URL = os.environ.get("OLLAMA_BASE_URL", "http://127.0.0.1:11434").rstrip("/")
MAX_LEXICAL_INDEX_DOCUMENTS = int(os.environ.get("RAG_MAX_LEXICAL_INDEX_DOCUMENTS", "20000"))
_LEXICAL_CACHE: dict[str, list[Document]] = {}
_TOKEN_RE = re.compile(r"[a-z0-9_]+", re.IGNORECASE)
_STOP_WORDS = set("a an and are as at be by for from has have how i in is it its of on or that the this to was were what when where which who why with about tell me explain".split())

EMBEDDING_KEEP_ALIVE = int(os.environ.get("OLLAMA_EMBEDDING_KEEP_ALIVE", "600"))
embeddings = OllamaEmbeddings(
    model=EMBEDDING_MODEL,
    base_url=OLLAMA_BASE_URL,
    keep_alive=EMBEDDING_KEEP_ALIVE,
)
vector_store = Chroma(
    collection_name="user_knowledge",
    persist_directory=DB_DIRECTORY,
    embedding_function=embeddings,
)


def _split_text(text: str, chunk_size: int = 1400, overlap: int = 200) -> list[str]:
    """Split text into overlapping chunks while retaining paragraph boundaries."""
    paragraphs = [re.sub(r"\s+", " ", item).strip() for item in re.split(r"\n\s*\n", text)]
    text = "\n\n".join(item for item in paragraphs if item)
    if not text:
        return []

    chunks: list[str] = []
    start = 0
    while start < len(text):
        end = min(start + chunk_size, len(text))
        if end < len(text):
            floor = start + chunk_size // 2
            boundary = max(text.rfind("\n\n", floor, end), text.rfind(". ", floor, end))
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
        return [("\n\n".join(paragraphs), {})]

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

        # Re-indexing replaces old content, including when the source is now empty.
        existing = vector_store._collection.get(
            where={"$and": [{"workspace": workspace}, {"source_path": source_path}]},
            include=["metadatas"],
        )
        if existing["ids"]:
            vector_store.delete(ids=existing["ids"])
            _LEXICAL_CACHE.clear()
        if documents:
            vector_store.add_documents(documents=documents, ids=ids)
            _LEXICAL_CACHE.clear()
            indexed += len(documents)
            sources.append(file_path.name)

    return indexed, sources


def retrieve(question: str, workspace: str, limit: int = 5) -> list[Document]:
    """Hybrid semantic and BM25 keyword retrieval, fused using reciprocal rank."""
    question = question.strip()
    if not question:
        return []
    if not 1 <= limit <= 20:
        raise ValueError("Retrieval limit must be between 1 and 20.")
    if vector_store._collection.count() == 0:
        return []

    candidate_limit = min(max(limit * 4, 20), 100)
    search_filter = None if workspace == "all" else {"workspace": workspace}
    semantic_docs = vector_store.similarity_search(question, k=candidate_limit, filter=search_filter)
    lexical_docs = _bm25_search(question, workspace, candidate_limit)

    # Reciprocal rank fusion rewards chunks surfaced by both search methods.
    fused: dict[tuple, tuple[float, Document]] = {}
    for ranked in (semantic_docs, lexical_docs):
        for rank, document in enumerate(ranked, start=1):
            key = _document_key(document)
            score, _ = fused.get(key, (0.0, document))
            fused[key] = (score + 1.0 / (60 + rank), document)
    return [item[1] for item in sorted(fused.values(), key=lambda item: item[0], reverse=True)[:limit]]


def _document_key(document: Document) -> tuple:
    metadata = document.metadata or {}
    return (
        metadata.get("workspace"), metadata.get("source_path"), metadata.get("page"),
        metadata.get("row"), metadata.get("chunk"), document.page_content,
    )


def _tokens(text: str) -> list[str]:
    return [token.lower() for token in _TOKEN_RE.findall(text) if token.lower() not in _STOP_WORDS]


def _workspace_documents(workspace: str) -> list[Document] | None:
    """Load and cache the bounded lexical corpus, or None for oversized indexes."""
    cache_key = workspace
    if cache_key in _LEXICAL_CACHE:
        return _LEXICAL_CACHE[cache_key]
    where = None if workspace == "all" else {"workspace": workspace}
    count = vector_store._collection.count() if where is None else len(
        vector_store._collection.get(where=where, include=["metadatas"]).get("ids", [])
    )
    if count > MAX_LEXICAL_INDEX_DOCUMENTS:
        return None
    result = vector_store._collection.get(where=where, include=["documents", "metadatas"])
    documents = [
        Document(page_content=text or "", metadata=metadata or {})
        for text, metadata in zip(result.get("documents") or [], result.get("metadatas") or [])
    ]
    _LEXICAL_CACHE[cache_key] = documents
    return documents


def _bm25_search(question: str, workspace: str, limit: int) -> list[Document]:
    query_terms = set(_tokens(question))
    if not query_terms:
        return []
    documents = _workspace_documents(workspace)
    if not documents:
        return []
    tokenized = [_tokens(document.page_content) for document in documents]
    document_frequency = Counter(term for terms in tokenized for term in set(terms))
    average_length = sum(map(len, tokenized)) / max(1, len(tokenized))
    total = len(documents)
    scores = []
    for document, terms in zip(documents, tokenized):
        frequencies = Counter(terms)
        length_norm = 1.5 * (1 - 0.75 + 0.75 * len(terms) / max(1, average_length))
        score = 0.0
        for term in query_terms:
            frequency = frequencies[term]
            if frequency:
                inverse_frequency = math.log(1 + (total - document_frequency[term] + 0.5) / (document_frequency[term] + 0.5))
                score += inverse_frequency * (frequency * 2.5 / (frequency + length_norm))
        if score > 0:
            scores.append((score, document))
    scores.sort(key=lambda item: item[0], reverse=True)
    return [document for _, document in scores[:limit]]


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
        _LEXICAL_CACHE.clear()
    return len(ids)
