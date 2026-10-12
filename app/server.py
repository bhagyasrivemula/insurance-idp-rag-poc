"""
FastAPI backend: serves the custom frontend and a small JSON API.

    GET  /                      -> the web app (frontend/index.html)
    GET  /api/health            -> OpenAI key/model status + vector store size
    GET  /api/products          -> product catalog with extracted key facts
    GET  /api/pipeline          -> IDP statistics for the "Knowledge base" view
    POST /api/search            -> retrieval only (shows metadata filtering + scores)
    POST /api/chat              -> streamed answer (NDJSON events, see app/bot.py)
    GET  /pdf/{file_name}       -> original brochure (citations link to #page=N)

Start with:  python -m app.server   (or run.ps1)
"""
from __future__ import annotations

import json
import mimetypes
import threading
from contextlib import asynccontextmanager
from pathlib import Path

import uvicorn
from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from app import bot, config, llm_client, retriever, vector_store
from app.idp.document_loader import PRODUCT_TYPE_LABELS
from app.idp.key_fact_fields import FIELD_LABELS

@asynccontextmanager
async def lifespan(_app: FastAPI):
    """
    Build the keyword index and check the OpenAI key at start-up, so problems show
    in the console straight away. Runs in a background thread so the page loads immediately.
    """
    def warm():
        retriever.bm25()
        status = llm_client.is_available()
        print(f"Ready: {config.CHAT_MODEL}" if status["reachable"] else f"OpenAI not reachable: {status['error']}")

    threading.Thread(target=warm, daemon=True).start()
    yield


app = FastAPI(title="InsureAssist", description="IDP + RAG insurance assistant on OpenAI",
              lifespan=lifespan)


@app.middleware("http")
async def no_cache_frontend(request, call_next):
    """Always revalidate the HTML/JS/CSS so browsers never show a stale UI after an update."""
    response = await call_next(request)
    if not request.url.path.startswith(("/api", "/pdf")):
        response.headers["Cache-Control"] = "no-cache"
    return response


# --------------------------------------------------------------------------- #
# Request models
# --------------------------------------------------------------------------- #
class ChatMessage(BaseModel):
    role: str
    content: str


class ChatRequest(BaseModel):
    question: str = Field(min_length=1, max_length=2000)
    persona: str = "buyer"                       # buyer | policyholder
    history: list[ChatMessage] = []
    filters: dict = {}                           # explicit filters chosen in the UI
    previous_filters: dict | None = None         # filters applied to the previous answer (for follow-ups)


class SearchRequest(BaseModel):
    query: str = Field(min_length=1, max_length=2000)
    filters: dict = {}
    persona: str = "buyer"
    mode: str = "hybrid"                         # hybrid | semantic | keyword
    top_k: int = Field(default=8, ge=1, le=30)


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #
def _processed_records() -> list[dict]:
    """All IDP output files (one per document)."""
    return [json.loads(p.read_text(encoding="utf-8")) for p in sorted(config.PROCESSED_DIR.glob("*.json"))]


# --------------------------------------------------------------------------- #
# API
# --------------------------------------------------------------------------- #
@app.get("/api/health")
def health():
    status = llm_client.is_available()
    return {
        "llm": status,
        "chat_model": config.CHAT_MODEL,
        "embed_model": config.EMBED_MODEL,
        "chunks_indexed": vector_store.get_collection().count(),
        "ready": status["chat_model_ready"] and status["embed_model_ready"],
    }


@app.get("/api/products")
def products():
    """Product catalog: document metadata + LLM-extracted key facts (+ grounding flags)."""
    items = []
    for rec in _processed_records():
        doc = rec["document"]
        items.append({
            **{k: doc[k] for k in ("doc_id", "file_name", "company", "product_name", "product_type",
                                   "product_type_label", "doc_type", "uin", "page_count", "source_url")},
            "key_facts": (rec.get("key_facts") or {}).get("facts"),
            "grounded": (rec.get("key_facts") or {}).get("grounded", {}),
            "pages_used": (rec.get("key_facts") or {}).get("pages_used", []),
        })
    return {"products": items, "field_labels": FIELD_LABELS, "type_labels": PRODUCT_TYPE_LABELS}


@app.get("/api/pipeline")
def pipeline_stats():
    """Per-document and overall IDP statistics."""
    docs, topics = [], {}
    for rec in _processed_records():
        d, s = rec["document"], rec["extraction_stats"]
        for topic, n in rec.get("topic_distribution", {}).items():
            topics[topic] = topics.get(topic, 0) + n
        grounded = (rec.get("key_facts") or {}).get("grounded", {})
        docs.append({
            "company": d["company"], "product_name": d["product_name"],
            "product_type_label": d["product_type_label"], "doc_type": d["doc_type"], "uin": d["uin"] or "-",
            "pages": s["pages"], "tables": s["tables"],
            "furniture_removed": s["furniture_lines_removed"], "chunks": rec["chunk_count"],
            "table_chunks": sum(c["metadata"]["content_type"] == "table" for c in rec["chunks"]),
            "key_facts": bool(rec.get("key_facts")),
            "verified_fields": sum(grounded.values()),
            "checked_fields": len(grounded),
        })
    totals = {k: sum(d[k] for d in docs) for k in ("pages", "tables", "chunks", "furniture_removed")}
    totals["documents"] = len(docs)
    totals["companies"] = len({d["company"] for d in docs})
    return {"documents": docs, "totals": totals, "topics": dict(sorted(topics.items(), key=lambda kv: -kv[1]))}


@app.post("/api/search")
def search(req: SearchRequest):
    """Retrieval only - lets the demo show exactly what the vector DB returns under each filter."""
    where = vector_store.build_where(req.filters)
    hits, info = retriever.search(req.query, req.filters, req.persona, top_k=req.top_k, mode=req.mode)
    return {"where": where, "info": info, "results": bot.source_cards(hits)}


@app.get("/api/evaluation")
def evaluation():
    """Latest RAGAS evaluation report (created by `python -m app.ragas_eval`)."""
    if not config.RAGAS_REPORT.exists():
        return {"available": False}
    return {"available": True, **json.loads(config.RAGAS_REPORT.read_text(encoding="utf-8"))}


@app.post("/api/chat")
def chat(req: ChatRequest):
    """Stream the answer as newline-delimited JSON events."""
    def events():
        try:
            for event in bot.answer_stream(req.question, req.persona, [h.model_dump() for h in req.history],
                                           req.filters, req.previous_filters):
                yield json.dumps(event, ensure_ascii=False) + "\n"
        except Exception as exc:  # surface model/server problems in the chat instead of a silent failure
            yield json.dumps({"type": "error", "message": str(exc)}) + "\n"

    return StreamingResponse(events(), media_type="application/x-ndjson")


@app.get("/pdf/{file_name}")
def pdf(file_name: str):
    """Serve an original brochure. Only plain file names inside the brochure folder are allowed."""
    path = (config.BROCHURE_DIR / Path(file_name).name).resolve()
    if path.parent != config.BROCHURE_DIR.resolve() or path.suffix.lower() != ".pdf" or not path.exists():
        raise HTTPException(404, "Brochure not found")
    return FileResponse(path, media_type="application/pdf")


# Windows can map ".js" to "text/plain" in the registry; browsers refuse to run ES modules
# served with that type, so register the correct types explicitly.
mimetypes.add_type("text/javascript", ".js")
mimetypes.add_type("text/css", ".css")

# Frontend (mounted last so /api routes take precedence)
app.mount("/", StaticFiles(directory=config.FRONTEND_DIR, html=True), name="frontend")


if __name__ == "__main__":
    uvicorn.run("app.server:app", host="127.0.0.1", port=8000, reload=False)
