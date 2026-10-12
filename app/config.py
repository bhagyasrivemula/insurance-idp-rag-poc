"""
Central configuration for the Insurance Assistant demo.

Every tunable value lives here so the pipeline, the bot and the API all agree
on paths, model names and retrieval settings. Any value can be overridden with
an environment variable of the same name, or in the `.env` file at the project
root (see `.env.example`). The OpenAI API key is read from `.env` only.
"""
from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv

ROOT_DIR = Path(__file__).resolve().parent.parent
load_dotenv(ROOT_DIR / ".env")   # secrets such as OPENAI_API_KEY live in .env, never in code


def _env(name: str, default: str) -> str:
    """Read a setting from the environment (or .env), falling back to a default."""
    return os.environ.get(name) or default


# --------------------------------------------------------------------------- #
# Paths
# --------------------------------------------------------------------------- #
DATA_DIR = ROOT_DIR / "data"
BROCHURE_DIR = DATA_DIR / "brochures"          # raw PDFs (input to the IDP pipeline)
SOURCES_FILE = BROCHURE_DIR / "sources.json"    # optional manifest: company / product / type / URL
PROCESSED_DIR = DATA_DIR / "processed"          # IDP output, one JSON per document (human-inspectable)
CHROMA_DIR = DATA_DIR / "chroma"                # persistent vector database
EVAL_DIR = DATA_DIR / "eval"                    # RAGAS test set + reports
RAGAS_TESTSET = EVAL_DIR / "testset.json"
RAGAS_REPORT = EVAL_DIR / "ragas_report.json"
FRONTEND_DIR = ROOT_DIR / "frontend"

# --------------------------------------------------------------------------- #
# OpenAI models
# --------------------------------------------------------------------------- #
OPENAI_API_KEY = os.environ.get("OPENAI_API_KEY", "").strip()
if "your-key" in OPENAI_API_KEY:          # untouched placeholder copied from .env.example
    OPENAI_API_KEY = ""

CHAT_MODEL = _env("CHAT_MODEL", "gpt-4.1-mini")                 # answers questions live: fast and cheap
EXTRACT_MODEL = _env("EXTRACT_MODEL", "gpt-4.1")                # IDP key-fact extraction: accuracy over speed
EMBED_MODEL = _env("EMBED_MODEL", "text-embedding-3-small")     # turns chunks and questions into vectors
EVAL_MODEL = _env("EVAL_MODEL", "gpt-4.1-mini")                 # RAGAS judge model
MODERATION_MODEL = _env("MODERATION_MODEL", "omni-moderation-latest")   # free OpenAI safety classifier

# --------------------------------------------------------------------------- #
# LangSmith tracing (optional - enabled when LANGSMITH_API_KEY is set in .env)
# --------------------------------------------------------------------------- #
LANGSMITH_API_KEY = os.environ.get("LANGSMITH_API_KEY", "").strip()
LANGSMITH_PROJECT = _env("LANGSMITH_PROJECT", "insureassist")
TRACING_ENABLED = bool(LANGSMITH_API_KEY) and _env("LANGSMITH_TRACING", "true").lower() != "false"
# The langsmith SDK reads these environment variables itself; set them consistently here.
os.environ["LANGSMITH_TRACING"] = "true" if TRACING_ENABLED else "false"
os.environ.setdefault("LANGSMITH_PROJECT", LANGSMITH_PROJECT)

# --------------------------------------------------------------------------- #
# Vector store
# --------------------------------------------------------------------------- #
# Vectors from different embedding models are not compatible, so each embedding
# model gets its own collection: changing EMBED_MODEL never mixes them up.
_embed_slug = "".join(c if c.isalnum() else "_" for c in EMBED_MODEL.lower()).strip("_")
COLLECTION_NAME = _env("COLLECTION_NAME", f"insurance_brochures__{_embed_slug}")

# --------------------------------------------------------------------------- #
# Semantic chunking
# --------------------------------------------------------------------------- #
# Text is split where the meaning shifts: a breakpoint is placed between two sentences
# when their embedding similarity is in the lowest SEMANTIC_BREAK_PERCENTILE % of the document.
SEMANTIC_BREAK_PERCENTILE = float(_env("SEMANTIC_BREAK_PERCENTILE", "20"))
CHUNK_MIN_CHARS = int(_env("CHUNK_MIN_CHARS", "350"))          # smaller pieces are merged with a neighbour
CHUNK_MAX_CHARS = int(_env("CHUNK_MAX_CHARS", "1600"))         # hard ceiling (big tables are split by rows)

# --------------------------------------------------------------------------- #
# Retrieval (semantic + keyword hybrid search)
# --------------------------------------------------------------------------- #
TOP_K = int(_env("TOP_K", "8"))                    # chunks handed to the LLM per question
CANDIDATE_K = int(_env("CANDIDATE_K", "25"))       # candidates per retriever before fusion
HISTORY_TURNS = int(_env("HISTORY_TURNS", "6"))    # previous messages sent to the LLM
# Cosine similarity below which a vector hit is considered unrelated and dropped.
MIN_SIMILARITY = float(_env("MIN_SIMILARITY", "0.25"))

# --------------------------------------------------------------------------- #
# Guardrails
# --------------------------------------------------------------------------- #
# If even the best chunk is this dissimilar, the question is treated as off-topic.
OFF_TOPIC_SIMILARITY = float(_env("OFF_TOPIC_SIMILARITY", "0.22"))
USE_MODERATION = _env("USE_MODERATION", "true").lower() != "false"
