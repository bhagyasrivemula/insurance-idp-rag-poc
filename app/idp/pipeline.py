"""
IDP pipeline orchestrator.

Run it from the project root:

    python -m app.idp.pipeline              # process new/changed PDFs
    python -m app.idp.pipeline --force      # re-process everything
    python -m app.idp.pipeline --skip-llm   # fast run without LLM key-fact extraction

For each PDF in data/brochures it runs:

    load & classify  ->  layout extraction  ->  key-fact extraction (LLM)
        ->  chunking + metadata  ->  embeddings  ->  ChromaDB

and writes data/processed/<doc_id>.json, a complete, human-readable record of
what was extracted (document metadata, stats, key facts, every chunk). That
file doubles as a cache: unchanged PDFs (same SHA-256) are skipped next time.
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from datetime import datetime, timezone

from langsmith import traceable

from app import config, llm_client, vector_store
from app.idp import chunker, key_facts as kf
from app.idp.document_loader import DocumentInfo, discover_documents
from app.idp.layout_extractor import extract_elements, page_texts


def log(message: str) -> None:
    print(f"[{datetime.now():%H:%M:%S}] {message}", flush=True)


def processed_path(doc: DocumentInfo):
    return config.PROCESSED_DIR / f"{doc.doc_id}.json"


def load_previous(doc: DocumentInfo) -> dict | None:
    """Return the earlier IDP record for this document, if the PDF has not changed."""
    path = processed_path(doc)
    if not path.exists():
        return None
    record = json.loads(path.read_text(encoding="utf-8"))
    return record if record["document"]["sha256"] == doc.sha256 else None


@traceable(run_type="chain", name="IDP: process document",
           process_inputs=lambda inputs: {"document": inputs["doc"].file_name, "skip_llm": inputs["skip_llm"]},
           process_outputs=lambda rec: {"chunks": rec["chunk_count"], "chunking": rec["chunking"],
                                        "key_facts_verified": sum((rec.get("key_facts") or {}).get("grounded", {}).values())})
def process_document(doc: DocumentInfo, skip_llm: bool, previous: dict | None) -> dict:
    """Run all IDP stages for one document and index its chunks."""
    started = time.perf_counter()

    # Stage 2: layout-aware extraction
    elements, stats = extract_elements(doc.file_path)
    pages = page_texts(doc.file_path)
    log(f"   layout: {stats['pages']} pages, {stats['tables']} tables, {stats['headings']} headings, "
        f"{stats['furniture_lines_removed']} header/footer lines removed")

    # Stage 3: key facts (reuse a previous run when the PDF and the extraction model are unchanged)
    facts = _reusable_facts(previous)
    if facts:
        log(f"   key facts: reused from previous run ({facts['model']})")
    elif not skip_llm:
        t0 = time.perf_counter()
        try:
            facts = kf.extract_key_facts(doc, pages)
            ok = sum(facts["grounded"].values())
            log(f"   key facts: extracted in {time.perf_counter() - t0:.0f}s "
                f"({ok}/{len(facts['grounded'])} fields verified against source)")
        except Exception as exc:  # the pipeline must survive a model hiccup
            log(f"   key facts: FAILED ({exc}) - continuing without them")
            facts = None

    # Stage 4: semantic chunking + metadata
    chunks, chunk_stats = chunker.build_chunks(doc, elements)
    if facts:
        chunks.append(chunker.key_facts_chunk(doc, kf.facts_to_text(doc, facts)))
    log(f"   chunks: {len(chunks)} ({sum(c.metadata['content_type'] == 'table' for c in chunks)} tables) - "
        f"semantic split of {chunk_stats['sentences']} sentences at similarity < {chunk_stats['similarity_threshold']}")

    # Stage 5: embed + store (old chunks of this document are replaced)
    t0 = time.perf_counter()
    vectors = llm_client.embed([c.text for c in chunks])
    vector_store.delete_document(doc.doc_id)
    vector_store.upsert_chunks([c.chunk_id for c in chunks], [c.text for c in chunks],
                               [c.metadata for c in chunks], vectors)
    log(f"   indexed: {len(chunks)} vectors in {time.perf_counter() - t0:.0f}s")

    record = {
        "document": doc.to_dict(),
        "processed_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "processing_seconds": round(time.perf_counter() - started, 1),
        "extraction_stats": stats,
        "chunking": chunk_stats,
        "key_facts": facts,
        "chunk_count": len(chunks),
        "topic_distribution": _topic_distribution(chunks),
        "chunks": [{"id": c.chunk_id, "text": c.text, "metadata": c.metadata} for c in chunks],
    }
    processed_path(doc).write_text(json.dumps(record, indent=2, ensure_ascii=False), encoding="utf-8")
    return record


def _reusable_facts(previous: dict | None) -> dict | None:
    """Earlier key facts, but only if they were produced by the currently configured extraction model."""
    facts = (previous or {}).get("key_facts")
    return facts if facts and facts.get("model") == config.EXTRACT_MODEL else None


def _topic_distribution(chunks) -> dict[str, int]:
    counts: dict[str, int] = {}
    for c in chunks:
        counts[c.metadata["topic"]] = counts.get(c.metadata["topic"], 0) + 1
    return dict(sorted(counts.items(), key=lambda kv: -kv[1]))


def run(force: bool = False, skip_llm: bool = False, only: str | None = None) -> None:
    config.PROCESSED_DIR.mkdir(parents=True, exist_ok=True)

    health = llm_client.is_available()
    if not health["reachable"]:
        sys.exit(f"OpenAI is not reachable: {health['error']}\nCheck OPENAI_API_KEY in .env and your connection.")
    if not health["embed_model_ready"]:
        sys.exit(f"Embedding model '{config.EMBED_MODEL}' is not available to this API key.")
    if not skip_llm and not health["extract_model_ready"]:
        sys.exit(f"Extraction model '{config.EXTRACT_MODEL}' is not available to this API key.")
    log(f"Models: extract={config.EXTRACT_MODEL} embed={config.EMBED_MODEL} | collection: {config.COLLECTION_NAME}")

    if force and not only:
        vector_store.get_collection(reset=True)   # full rebuild; with --only just that document is replaced

    # Stage 1: ingestion + classification
    documents = discover_documents()
    if only:
        documents = [d for d in documents if only in d.doc_id]
    log(f"Found {len(documents)} PDF(s) in {config.BROCHURE_DIR}")

    collection = vector_store.get_collection()
    for n, doc in enumerate(documents, 1):
        log(f"[{n}/{len(documents)}] {doc.company} - {doc.product_name} "
            f"({doc.product_type_label}, {doc.doc_type}, {doc.page_count} pages, UIN {doc.uin or 'n/a'})")
        previous = None if force else load_previous(doc)
        already_indexed = bool(collection.get(where={"doc_id": doc.doc_id}, limit=1)["ids"])
        if previous and already_indexed and (_reusable_facts(previous) or skip_llm):
            log("   unchanged and already indexed - skipped")
            continue
        process_document(doc, skip_llm, previous)

    log(f"Done. Vector store now holds {collection.count()} chunks.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Run the IDP pipeline over data/brochures.")
    parser.add_argument("--force", action="store_true", help="re-process every document and rebuild the index")
    parser.add_argument("--skip-llm", action="store_true", help="skip LLM key-fact extraction (faster)")
    parser.add_argument("--only", help="process only documents whose id contains this text")
    args = parser.parse_args()
    run(force=args.force, skip_llm=args.skip_llm, only=args.only)
