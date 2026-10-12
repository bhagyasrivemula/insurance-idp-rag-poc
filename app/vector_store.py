"""
Vector database layer (ChromaDB, persisted on disk) + a keyword (BM25) index.

ChromaDB stores, for every chunk:  id, embedding, text, metadata.
Metadata filters use Chroma's `where` syntax, for example

    {"product_type": "health"}
    {"$and": [{"company": "HDFC Life"}, {"topic_claims": True}]}

Why also BM25? Embeddings are great at meaning ("what if I die early?" ->
death benefit) but weak at exact tokens such as product names, UINs or
"Section 80D". BM25 is the opposite. The retriever fuses both result lists.
"""
from __future__ import annotations

import math
import re
from collections import Counter

import chromadb

from app import config

_client = None
_collection = None


def get_collection(reset: bool = False):
    """Open (or create) the persistent Chroma collection. Cosine distance suits text embeddings."""
    global _client, _collection
    if _client is None:
        config.CHROMA_DIR.mkdir(parents=True, exist_ok=True)
        _client = chromadb.PersistentClient(path=str(config.CHROMA_DIR))
    if reset:
        try:
            _client.delete_collection(config.COLLECTION_NAME)
        except Exception:
            pass
        _collection = None
    if _collection is None:
        _collection = _client.get_or_create_collection(
            name=config.COLLECTION_NAME,
            metadata={"hnsw:space": "cosine"},
            embedding_function=None,   # we always pass our own embeddings (see llm_client.embed)
        )
    return _collection


def upsert_chunks(ids: list[str], texts: list[str], metadatas: list[dict], embeddings: list[list[float]]) -> None:
    """Insert or replace chunks (Chroma metadata must be str/int/float/bool - no None)."""
    clean_meta = [{k: ("" if v is None else v) for k, v in m.items()} for m in metadatas]
    get_collection().upsert(ids=ids, documents=texts, metadatas=clean_meta, embeddings=embeddings)


def delete_document(doc_id: str) -> None:
    """Remove every chunk of a document (used before re-indexing it)."""
    get_collection().delete(where={"doc_id": doc_id})


def vector_search(query_embedding: list[float], where: dict | None, n: int) -> list[dict]:
    """Nearest-neighbour search restricted by an optional metadata filter."""
    col = get_collection()
    if col.count() == 0:
        return []
    res = col.query(query_embeddings=[query_embedding], n_results=n, where=where or None,
                    include=["documents", "metadatas", "distances"])
    return [
        {"id": i, "text": d, "metadata": m, "score": 1 - dist}
        for i, d, m, dist in zip(res["ids"][0], res["documents"][0], res["metadatas"][0], res["distances"][0])
    ]


def build_where(filters: dict) -> dict | None:
    """
    Convert simple UI filters into a Chroma `where` clause.
    Example: {"company": "HDFC Life", "product_type": None, "topic": "claims"}
          -> {"$and": [{"company": "HDFC Life"}, {"topic_claims": True}]}
    """
    clauses = []
    for key, value in filters.items():
        if value in (None, "", "all"):
            continue
        if key == "topic":
            clauses.append({f"topic_{value}": True})
        elif isinstance(value, list):
            clauses.append({key: {"$in": value}} if len(value) > 1 else {key: value[0]})
        else:
            clauses.append({key: value})
    if not clauses:
        return None
    return clauses[0] if len(clauses) == 1 else {"$and": clauses}


def matches(metadata: dict, filters: dict) -> bool:
    """Python-side equivalent of build_where(), used to filter BM25 results."""
    for key, value in filters.items():
        if value in (None, "", "all"):
            continue
        if key == "topic":
            if not metadata.get(f"topic_{value}"):
                return False
        elif isinstance(value, list):
            if metadata.get(key) not in value:
                return False
        elif metadata.get(key) != value:
            return False
    return True


# --------------------------------------------------------------------------- #
# BM25 keyword index (built in memory from the Chroma contents at start-up)
# --------------------------------------------------------------------------- #
_TOKEN = re.compile(r"[a-z0-9]+")
_STOP = {"the", "a", "an", "of", "to", "and", "or", "in", "on", "for", "is", "are", "be", "will", "with",
         "by", "as", "at", "this", "that", "it", "if", "any", "from", "under", "shall", "your", "you",
         "what", "how", "can", "i", "my", "me", "do", "does", "which", "plan", "policy"}


def tokenize(text: str) -> list[str]:
    return [t for t in _TOKEN.findall(text.lower()) if t not in _STOP]


class BM25Index:
    """Classic Okapi BM25 (k1=1.5, b=0.75). A few hundred chunks -> instant in pure Python."""

    def __init__(self, k1: float = 1.5, b: float = 0.75):
        self.k1, self.b = k1, b
        self.docs: list[dict] = []
        self.tfs: list[Counter] = []
        self.idf: dict[str, float] = {}
        self.avg_len = 0.0

    def build(self) -> "BM25Index":
        data = get_collection().get(include=["documents", "metadatas"])
        self.docs = [{"id": i, "text": d, "metadata": m}
                     for i, d, m in zip(data["ids"], data["documents"], data["metadatas"])]
        self.tfs = [Counter(tokenize(d["text"])) for d in self.docs]
        n = len(self.docs) or 1
        df = Counter(term for tf in self.tfs for term in tf)
        self.idf = {t: math.log(1 + (n - f + 0.5) / (f + 0.5)) for t, f in df.items()}
        self.avg_len = sum(sum(tf.values()) for tf in self.tfs) / n
        return self

    def search(self, query: str, filters: dict, n: int) -> list[dict]:
        terms = tokenize(query)
        scored = []
        for doc, tf in zip(self.docs, self.tfs):
            if not matches(doc["metadata"], filters):
                continue
            length = sum(tf.values())
            score = sum(
                self.idf.get(t, 0) * tf[t] * (self.k1 + 1) /
                (tf[t] + self.k1 * (1 - self.b + self.b * length / (self.avg_len or 1)))
                for t in terms if t in tf
            )
            if score > 0:
                scored.append({**doc, "score": score})
        return sorted(scored, key=lambda d: d["score"], reverse=True)[:n]
