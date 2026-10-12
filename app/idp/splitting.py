"""
Splitting a document into chunk-sized pieces (used by chunker.py).

    * Section headings are hard boundaries (tiny sections fold into the next one).
    * Text is split SEMANTICALLY: every sentence is embedded together with its
      neighbours, and a boundary is placed where the similarity between
      consecutive sentences falls into the lowest SEMANTIC_BREAK_PERCENTILE % for
      the document - i.e. where the topic changes. Pieces are then kept between
      CHUNK_MIN_CHARS and CHUNK_MAX_CHARS; oversized pieces split at their
      weakest semantic link.
    * Tables are split by rows; every piece repeats the header row(s).
"""
from __future__ import annotations

import re

import numpy as np

from app import config, llm_client
from app.idp.layout_extractor import Element

TINY_SECTION_CHARS = 250       # a section shorter than this is merged into the next one
MAX_HEADER_ROWS = 4            # header + separator + up to two sub-header rows


def split_sentences(text: str, limit: int) -> list[str]:
    """Split text into sentences; a sentence longer than `limit` is hard-cut (rare, e.g. long lists)."""
    out = []
    for sentence in re.split(r"(?<=[.!?;])\s+(?=[A-Z0-9(\-])", text):
        while len(sentence) > limit:
            out.append(sentence[:limit])
            sentence = sentence[limit:]
        if sentence.strip():
            out.append(sentence.strip())
    return out


def _is_subheader_row(row: str) -> bool:
    """
    Rows like '| Family Size | Age-band | Sum Insured (Rs.) |' or '|  |  | 1,00,000 | 2,00,000 |'
    describe the columns rather than holding data: their first two cells carry no number.
    """
    cells = [c.strip() for c in row.strip("|").split("|")]
    return not re.search(r"\d", " ".join(cells[:2]))


def split_table(markdown: str, limit: int) -> list[str]:
    """Split a Markdown table by rows, repeating the header (and leading sub-header rows) in every piece."""
    lines = markdown.split("\n")
    header, rows = lines[:2], lines[2:]
    if len(markdown) > limit:
        while rows and len(header) < MAX_HEADER_ROWS and _is_subheader_row(rows[0]):
            header.append(rows.pop(0))
    pieces, current = [], []
    for row in rows:
        if sum(len(line) + 1 for line in header + current + [row]) > limit and current:
            pieces.append("\n".join(header + current))
            current = []
        current.append(row)
    if current:
        pieces.append("\n".join(header + current))
    return pieces


def group_sections(elements: list[Element]) -> list[dict]:
    """
    Layout elements -> blocks in reading order:
        {"type": "text",  "section": str, "sentences": [(sentence, page), ...]}
        {"type": "table", "section": str, "content": markdown, "page": int}
    """
    blocks: list[dict] = []
    section, current = "Overview", []

    def close():
        nonlocal current
        if current:
            blocks.append({"type": "text", "section": section, "sentences": current})
        current = []

    for el in elements:
        if el.type == "heading":
            if current and sum(len(s) for s, _ in current) < TINY_SECTION_CHARS:
                current.append((f"{el.text}:", el.page))           # fold a tiny section into the next
                continue
            close()
            section = el.text
        elif el.type == "table":
            close()
            blocks.append({"type": "table", "section": section, "content": el.text, "page": el.page})
        else:
            current += [(s, el.page) for s in split_sentences(el.text, config.CHUNK_MAX_CHARS)]
    close()
    return blocks


def sentence_similarities(blocks: list[dict]) -> list[np.ndarray]:
    """
    Cosine similarity between each sentence and the next, per text block.
    Each sentence is embedded with its neighbours (3-sentence window), which keeps
    short fragments such as bullet points stable. One batched call per document.
    """
    windows, spans = [], []
    for block in blocks:
        sentences = [s for s, _ in block.get("sentences", [])]
        start = len(windows)
        windows += [" ".join(sentences[max(0, i - 1): i + 2]) for i in range(len(sentences))]
        spans.append((start, len(windows)))
    if not windows:
        return [np.array([]) for _ in blocks]
    vectors = np.array(llm_client.embed(windows))
    vectors /= np.linalg.norm(vectors, axis=1, keepdims=True)       # unit vectors: dot product = cosine
    return [np.sum(vectors[a:b - 1] * vectors[a + 1:b], axis=1) if b - a > 1 else np.array([]) for a, b in spans]


def split_semantic(sentences: list[str], sims: np.ndarray, threshold: float) -> list[list[int]]:
    """
    Group sentence indexes into chunks:
      1. break wherever similarity to the next sentence < threshold (topic shift);
      2. split pieces larger than CHUNK_MAX_CHARS again at their weakest link;
      3. merge pieces smaller than CHUNK_MIN_CHARS into a neighbour.
    """
    def size(idx: list[int]) -> int:
        return sum(len(sentences[i]) + 1 for i in idx)

    groups, current = [], [0]
    for i in range(1, len(sentences)):
        if sims[i - 1] < threshold:
            groups.append(current)
            current = []
        current.append(i)
    groups.append(current)

    def split_large(idx: list[int]) -> list[list[int]]:
        if size(idx) <= config.CHUNK_MAX_CHARS or len(idx) == 1:
            return [idx]
        cut = min(range(1, len(idx)), key=lambda k: sims[idx[k] - 1])    # weakest link
        return split_large(idx[:cut]) + split_large(idx[cut:])

    merged: list[list[int]] = []
    for group in (piece for g in groups for piece in split_large(g)):
        too_small = merged and (size(merged[-1]) < config.CHUNK_MIN_CHARS or size(group) < config.CHUNK_MIN_CHARS)
        if too_small and size(merged[-1]) + size(group) <= config.CHUNK_MAX_CHARS:
            merged[-1] = merged[-1] + group
        else:
            merged.append(group)
    return merged


def split_document(elements: list[Element]) -> tuple[list[dict], dict]:
    """
    Split a whole document. Returns (pieces, stats) where each piece is
    {"content", "section", "pages", "type": "text" | "table"}.
    """
    blocks = group_sections(elements)
    sims_per_block = sentence_similarities(blocks)
    all_sims = [s for s in sims_per_block if s.size]
    threshold = float(np.percentile(np.concatenate(all_sims), config.SEMANTIC_BREAK_PERCENTILE)) if all_sims else 1.0

    pieces: list[dict] = []
    for block, sims in zip(blocks, sims_per_block):
        if block["type"] == "table":
            pieces += [{"content": p, "section": block["section"], "pages": [block["page"]], "type": "table"}
                       for p in split_table(block["content"], config.CHUNK_MAX_CHARS)]
            continue
        sentences = [s for s, _ in block["sentences"]]
        for idx in split_semantic(sentences, sims, threshold):
            pieces.append({"content": " ".join(sentences[i] for i in idx), "section": block["section"],
                           "pages": [block["sentences"][i][1] for i in idx], "type": "text"})

    stats = {"method": "semantic", "sentences": sum(len(b.get("sentences", [])) for b in blocks),
             "similarity_threshold": round(threshold, 3), "text_chunks": sum(p["type"] == "text" for p in pieces)}
    return pieces, stats
