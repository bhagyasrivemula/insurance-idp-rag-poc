"""
Intelligent Document Processing (IDP) pipeline for insurance brochures.

Stages (each in its own module, run in order by `pipeline.py`):

    1. document_loader   - find PDFs, fingerprint them, classify, read document metadata
    2. layout_extractor  - layout-aware extraction of headings, paragraphs and tables;
                           strips repeating headers/footers and normalises text
    3. key_facts         - LLM-based extraction of structured key data (entry age,
                           sum assured, waiting periods, ...) + grounding check
    4. chunker           - section-aware chunking with rich metadata and topic tags
    5. vector_store      - embeddings + ChromaDB with metadata filtering
"""
