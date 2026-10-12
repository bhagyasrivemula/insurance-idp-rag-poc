# InsureAssist: insurance brochure intelligence with IDP and RAG

InsureAssist reads official insurance product brochures (PDF) and answers questions about them. It serves two kinds of user: people **choosing a policy** and people who **already hold one**. Every answer cites the brochure page it came from. It runs on **OpenAI** models.

```
 PDF brochures ──► IDP pipeline ──► ChromaDB (vectors + metadata) ──► Hybrid retriever ──► OpenAI ──► Web app
                   (extract, understand,                                (filters, BM25,                   (chat, catalog,
                    chunk, enrich)                                       fusion)                           knowledge base)
```

---

## 1. What's inside

| Layer | What it does | Where |
|---|---|---|
| **Document collection** | 9 official brochures/prospectuses from 4 insurers (HDFC Life, Axis Max Life, Star Health, Bajaj General) covering term life, savings, ULIP, health, motor and travel | `data/brochures/` + `sources.json` |
| **IDP pipeline** | Classifies each document, extracts layout (headings, paragraphs, tables), removes headers/footers, extracts structured key facts with an LLM, checks those facts against the source, chunks by section, tags topics, embeds and indexes | `app/idp/` |
| **Vector DB** | ChromaDB (persistent) holding every chunk with its embedding and filterable metadata | `app/vector_store.py`, `data/chroma/` |
| **Retriever** | Detects products, insurers and product types in the question, then runs vector search plus BM25 keyword search inside those filters and fuses the results | `app/retriever.py` |
| **Bot** | Prompts that differ for buyers and policyholders, grounded answers with `[n]` citations, follow-up awareness, streaming | `app/bot.py` |
| **API** | FastAPI with streaming chat, product catalog, pipeline stats, retrieval explorer and PDF serving | `app/server.py` |
| **Frontend** | Hand-written HTML/CSS/JS (no build step) | `frontend/` |

### Models

All model calls go through `app/llm_client.py`.

| Purpose | Model | Why |
|---|---|---|
| Chat answers | `gpt-4.1-mini` | Fast and cheap, good at grounded answers |
| Key-fact extraction (batch) | `gpt-4.1` | Accurate structured output (strict JSON schema) |
| Embeddings | `text-embedding-3-small` | Strong retrieval quality at low cost |

Each model can be overridden in `.env` (see [Configuration](#6-configuration)).

---

## 2. Quick start (Windows)

```powershell
cd C:\Demo
powershell -ExecutionPolicy Bypass -File .\setup.ps1     # one time: Python env, creates .env
notepad .env                                            # paste your key:  OPENAI_API_KEY=sk-...
.\ingest.ps1                                            # run the IDP pipeline (a few minutes with OpenAI)
.\run.ps1                                               # starts the server and opens http://127.0.0.1:8000
```

Requirements: Python 3.11+ and an OpenAI API key. Processing all 9 brochures costs well under US$1. Each chat question costs a fraction of a cent.
To add more products, drop PDFs into `data/brochures/`, optionally add an entry to `sources.json`, and run `.\ingest.ps1` again. Unchanged PDFs are skipped automatically because each file is fingerprinted with SHA-256.

---

## 3. The IDP pipeline in detail

Run it with `python -m app.idp.pipeline [--force] [--skip-llm] [--only <name>]`.

| # | Stage | Module | Highlights |
|---|---|---|---|
| 1 | **Ingest & classify** | `document_loader.py` | SHA-256 fingerprint; company, product and type from the manifest, with a keyword classifier as fallback; document type (brochure, prospectus, leaflet); regulatory IDs (IRDAI **UIN**, company **CIN**) found with regular expressions |
| 2 | **Layout extraction** | `layout_extractor.py` | PyMuPDF table detection turns tables into Markdown. Headings are found from font size, bold and ALL CAPS. Lines that repeat across pages (headers, footers, "Page 3 of 27") are removed. Text is cleaned of ligatures, symbol-font bullets and the Rupee-font backtick |
| 3 | **Key-fact extraction** | `key_facts.py` | Three focused LLM passes (overview, eligibility, terms), each given only its most relevant pages. Strict JSON-schema output means no fragile parsing. A **grounding check** flags any value whose numbers or words are not in the PDF, and flagged values are never shown to the chatbot |
| 4 | **Semantic chunking** | `chunker.py` | Each sentence is embedded together with its neighbours. A boundary is placed where the similarity between consecutive sentences falls into the lowest 20% for the document, i.e. where the topic changes. Pieces are kept between 350 and 1,600 characters, and oversized pieces split at their weakest semantic link. Section headings are hard boundaries, and tables are split by rows with their headers repeated. Each chunk gets a context line ("HDFC Life \| Sanchay Plus \| Savings \| Section: ELIGIBILITY") and topic tags |
| 5 | **Embed & index** | `pipeline.py`, `vector_store.py` | `text-embedding-3-small` embeddings go into ChromaDB with cosine distance; re-indexing a document replaces its old chunks |

Each document produces `data/processed/<doc_id>.json`, a complete, human-readable record of what was extracted: metadata, statistics, key facts with verification flags, and every chunk.

### Chunk metadata (all filterable in ChromaDB)

```
doc_id, file_name, company, product_name, product_type, doc_type, uin, source_url,
section, page_start, page_end, content_type (text | table | key_facts), char_count,
topic (primary) + topic_eligibility, topic_benefits, topic_premiums, topic_exclusions,
topic_waiting_period, topic_claims, topic_policy_servicing, topic_riders, topic_tax, topic_contact (booleans)
```

Example filter that the retriever builds:

```python
{"$and": [{"company": "Bajaj General"}, {"product_type": "health"}, {"topic_claims": True}]}
```

---

## 4. How a question is answered

1. **Input guardrails** (`guardrails.py`).
   - Personal data (Aadhaar, PAN, phone, email, card numbers) is masked before anything reaches the model.
   - Prompt-injection attempts are blocked.
   - OpenAI moderation blocks harmful content.
2. **Scope.** The question is scanned for product names (including variants such as "Click to Protect" or "Sanchay"), insurers and product types.
   - A product named in the question overrides the sidebar filters. Otherwise the sidebar filters apply.
   - A follow-up such as *"what is its waiting period?"* inherits the previous scope, and the LLM **rewrites it into a standalone search query**.
3. **Semantic + keyword search.**
   - Semantic search (embeddings) finds chunks by meaning. Hits below a similarity of 0.25 are dropped as irrelevant.
   - BM25 catches exact terms such as product names, "80D" or UINs.
   - Both run inside the metadata filter and are merged with Reciprocal Rank Fusion. The explorer can switch between hybrid, semantic-only and keyword-only to compare them.
4. **Off-topic guardrail.** If even the best semantic match is very weak and the question contains no insurance terms, the assistant declines politely without calling the LLM.
5. **Grounded generation.** The LLM receives numbered excerpts and a persona-specific system prompt. It must answer only from the excerpts, cite them as `[n]`, and quote numbers exactly.
6. **Output guardrails.**
   - Every figure in the answer must appear in the excerpts.
   - Substantive answers must cite their sources.
   - Claim-approval promises and buy recommendations are flagged.
   - Results appear under each answer ("Guardrails: 6 passed · 1 warning").
7. **Streaming and tracing.** Tokens stream to the browser. With LangSmith enabled, the whole run is one trace: guardrails, query rewrite, retrieval (with the retrieved documents) and every OpenAI call. A **LangSmith trace ↗** link appears under each answer.

### LangSmith tracing

Add `LANGSMITH_API_KEY=...` to `.env` (free account at smith.langchain.com) and restart. Traces appear in the `insureassist` project:

- every chat answer, with guardrail and retrieval steps;
- every ingestion run, one trace per document;
- every RAGAS evaluation call.

Without a key, tracing is switched off and costs nothing.

---

### RAGAS evaluation

`python -m app.ragas_eval` runs the 17 questions in `data/eval/testset.json` through the full assistant and scores the answers with RAGAS, using `gpt-4.1-mini` as judge. A full run costs a few cents.

| Metric | What it measures |
|---|---|
| Faithfulness | The answer's claims are supported by the retrieved excerpts (low means hallucination) |
| Answer relevancy | The answer addresses the question |
| Context precision | Relevant excerpts are ranked at the top |
| Context recall | The excerpts contain everything the reference answer needs |
| Factual correctness | The answer agrees with the reference answer |

Results go to `data/eval/ragas_report.json` and `ragas_results.csv`, and are shown in **Knowledge base → Quality evaluation**. The reference answers were written from the brochures; review them when you add products. Use `--limit 5` for a quick check.

### Measured retrieval quality

`python -m app.evaluate` runs 18 test questions (buyer and policyholder, every product) without the LLM:

```
Product hit rate @ top-8: 18/18 (100%)
Answer  hit rate @ top-8: 18/18 (100%)
Average retrieval time: ~400 ms per question
```

End-to-end, answers start streaming in about 1-2 seconds and finish in 2-6 seconds. Re-processing all 9 brochures takes about 2 minutes, and 99 of 102 extracted key-fact values are verified against the PDFs.

---

## 5. Demo script (about 10 minutes)

1. **Knowledge base tab.** Start here to show the pipeline: 9 brochures, 155 pages, 131 tables extracted, 756 chunks, and more than 1,000 header/footer lines removed. Walk through the five pipeline steps.
2. **Retrieval explorer** (same tab). Search *"waiting period for pre-existing diseases"*, then set *Product type = Health* and *Topic = Waiting periods*. The Chroma `where` clause and the vector and keyword ranks of each hit are shown, which demonstrates metadata filtering live.
3. **Products tab.** Show the cards built automatically from the brochures. Open **Key facts** on a product and point out the ✓ verified and ⚠ check badges from the grounding check.
4. **Assistant tab, "Looking to buy" persona:**
   - *Compare the Travel Ace and Travel Prime Individual plans.* The answer is a comparison table with citations.
   - *Does Health Guard cover maternity expenses?* Click a `[1]` citation, then **Open PDF** to land on the source page.
5. **Switch to the "A policyholder" persona:**
   - *What is the grace period if I miss a premium on Sanchay Plus?*
   - Follow up with *What happens if I don't pay within that time?* The scope chip shows the conversation context carried over.
   - *How do I make a cashless claim under Family Health Optima?*
6. **Honesty check.** Ask *Do you offer crop insurance for farmers?* No brochure covers it, and the bot says so instead of inventing an answer.
7. **Hidden detail.** Ask *Does any plan cover pet-related costs?* The bot finds Travel Ace's optional "Extended Pet Stay" benefit, a single row in a large 11-column table. Click the citation to show the source.

> Tip: answers start streaming within a few seconds. The demo needs an internet connection, so check it before the client arrives.

---

## 6. Configuration

Each setting in `app/config.py` can be overridden with an environment variable of the same name:

| Variable | Default | Meaning |
|---|---|---|
| `OPENAI_API_KEY` | – | Your key (put it in `.env`; never commit it) |
| `CHAT_MODEL` | `gpt-4.1-mini` | Model that answers questions |
| `EXTRACT_MODEL` | `gpt-4.1` | Model used by the IDP key-fact step (changing it triggers re-extraction on the next ingest) |
| `EMBED_MODEL` | `text-embedding-3-small` | Embedding model (has its own collection; run ingest after changing it) |
| `TOP_K` | `8` | Excerpts given to the LLM per question |
| `CHUNK_TARGET_CHARS` / `CHUNK_MAX_CHARS` | `1000` / `1600` | Chunk sizes |

---

## 7. Project structure

Each source file has one responsibility and stays under 200 lines.

```
C:\Demo
├── app/
│   ├── config.py            settings (paths, models, thresholds) - read from .env
│   ├── llm_client.py        OpenAI: embeddings, JSON extraction, chat, moderation (+ LangSmith wrapping)
│   ├── server.py            FastAPI app (API + static frontend + PDFs)
│   ├── bot.py               answer pipeline: guardrails -> scope -> search -> generate -> guardrails
│   ├── prompts.py           system/user prompts and personas
│   ├── scope.py             which products/insurers a question is about (filter inference)
│   ├── retriever.py         query rewriting, semantic + keyword search, rank fusion
│   ├── vector_store.py      ChromaDB wrapper + metadata filters + BM25 index
│   ├── guardrails.py        input/output guardrails (PII, injection, moderation, topic, grounding)
│   ├── evaluate.py          retrieval quality test (18 questions, no LLM)
│   ├── ragas_eval.py        RAGAS evaluation of full answers (17 questions with references)
│   └── idp/
│       ├── document_loader.py   stage 1: ingest & classify
│       ├── layout_extractor.py  stage 2: layout-aware extraction
│       ├── text_cleaning.py     stage 2: Unicode / PDF-font clean-up
│       ├── key_facts.py         stage 3: LLM key facts + grounding check
│       ├── key_fact_fields.py   stage 3: which fields are extracted, and the prompt
│       ├── splitting.py         stage 4: semantic text splitting + table splitting
│       ├── chunker.py           stage 4: chunks, topic tags, metadata
│       └── pipeline.py          orchestrator / CLI (stage 5: embed & index)
├── frontend/
│   ├── index.html  styles.css
│   └── js/                  ES modules (no build step), entry point main.js
│       ├── main.js            boot + event wiring
│       ├── chat.js            sending questions, streaming answers
│       ├── api.js             all server calls (incl. NDJSON stream)
│       ├── markdown.js        safe Markdown + citation rendering
│       ├── sources.js         source cards, citation focus
│       ├── answer-meta.js     answer footer + guardrail panel
│       ├── filters.js         sidebar filters, context chips, suggestions
│       ├── products.js        catalog + key-facts modal
│       ├── knowledge.js       pipeline stats + retrieval explorer
│       ├── evaluation.js      RAGAS scorecard
│       ├── views.js  theme.js  status.js  state.js  constants.js  dom.js
│       └── theme-init.js      applies saved theme before first paint
├── data/
│   ├── brochures/           source PDFs + sources.json (where each came from)
│   ├── processed/           IDP output, one JSON per document
│   ├── eval/                RAGAS test set + reports
│   └── chroma/              vector database files
├── setup.ps1  ingest.ps1  run.ps1
└── requirements.txt
```

---

## 8. Notes and limitations

- Brochures are summaries. The policy wording is the legal contract, which the UI disclaimer states.
- Brochures were downloaded from insurer websites, or from a bank partner's site where the insurer's own copy was not reachable (see `sources.json`). They are used here for demonstration only.
- An LLM can occasionally misread a complex premium table. The grounding check, the citations and the "Open PDF" links let users verify any answer quickly.
- Scanned (image-only) PDFs would need an OCR step, such as Tesseract via `pymupdf`'s OCR support. All current brochures are digital PDFs, so OCR is not enabled.
