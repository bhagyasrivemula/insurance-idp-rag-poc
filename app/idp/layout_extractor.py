"""
IDP Stage 2 - Layout-aware content extraction.

A brochure is not plain text: it has headings, multi-line paragraphs, dense
tables (eligibility grids, premium tables) and repeating page furniture
(headers, footers, "Page 3 of 27"). Feeding raw `page.get_text()` to a
chatbot loses that structure, so this module turns each PDF into an ordered
list of typed *elements*:

    {"type": "heading",   "text": "ELIGIBILITY CRITERIA", "page": 4}
    {"type": "paragraph", "text": "Premium payable ...",  "page": 4}
    {"type": "table",     "text": "| Age | Min | Max |...", "page": 4}

Steps per document:
    1. Detect tables (PyMuPDF table finder) and convert them to Markdown.
    2. Read the remaining text blocks, skipping anything inside a table.
    3. Classify short, emphasised lines as headings (font size, bold, ALL CAPS).
    4. Remove lines that repeat on many pages (headers/footers).
    5. Normalise Unicode (ligatures such as "\ufb01" -> "fi", smart quotes, bullets).
"""
from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass

import pymupdf

from app.idp.text_cleaning import normalize_text

# A line seen on at least this share of pages is treated as a header/footer.
REPEAT_THRESHOLD = 0.4
MAX_HEADING_CHARS = 80
MAX_HEADING_WORDS = 12


@dataclass
class Element:
    """One unit of content in reading order."""
    type: str          # heading | paragraph | table
    text: str
    page: int          # 1-based page number


def _furniture_key(line: str) -> str:
    """Key used to spot repeating lines: digits are masked so 'Page 3 of 27' == 'Page 4 of 27'."""
    return re.sub(r"\d+", "#", line.lower()).strip()


# --------------------------------------------------------------------------- #
# Tables
# --------------------------------------------------------------------------- #
def _clean_cell(cell) -> str:
    return normalize_text(str(cell).replace("\n", " ")) if cell is not None else ""


def table_to_markdown(raw_rows: list[list]) -> str:
    """
    Convert extracted table rows into a Markdown table.
    Empty rows/columns are dropped. Returns "" if what's left is not really a table.
    """
    rows = [[_clean_cell(c) for c in row] for row in raw_rows]
    rows = [r for r in rows if any(r)]
    if len(rows) < 2:
        return ""
    width = max(len(r) for r in rows)
    rows = [r + [""] * (width - len(r)) for r in rows]
    keep_cols = [i for i in range(width) if any(r[i] for r in rows)]
    rows = [[r[i] for i in keep_cols] for r in rows]
    if len(keep_cols) < 2:
        return ""

    header, body = rows[0], rows[1:]
    lines = ["| " + " | ".join(header) + " |", "|" + "---|" * len(header)]
    lines += ["| " + " | ".join(r) + " |" for r in body]
    return "\n".join(lines)


# --------------------------------------------------------------------------- #
# Heading detection
# --------------------------------------------------------------------------- #
def _is_heading(text: str, size: float, bold: bool, body_size: float) -> bool:
    """
    Heuristic heading test. Brochures are inconsistent (some use big fonts,
    some only bold or ALL CAPS), so several signals are combined.
    """
    if len(text) > MAX_HEADING_CHARS or len(text.split()) > MAX_HEADING_WORDS:
        return False
    if text.endswith((".", ",", ";")) or not re.search(r"[A-Za-z]{3}", text):
        return False
    # Regulatory identifiers, e-mails and web addresses are styled boldly but are not section titles.
    if re.search(r"\b(CIN|UIN|IRDAI|Reg\.? ?No)\b|@|www\.|https?:", text):
        return False
    letters = [c for c in text if c.isalpha()]
    all_caps = len(letters) >= 4 and sum(c.isupper() for c in letters) / len(letters) > 0.85
    bigger = size >= body_size * 1.15
    return bigger or (bold and len(text) < 60) or all_caps


# --------------------------------------------------------------------------- #
# Main extraction
# --------------------------------------------------------------------------- #
def _inside(bbox, rects) -> bool:
    """True if the centre of `bbox` falls inside any of the table rectangles."""
    cx, cy = (bbox[0] + bbox[2]) / 2, (bbox[1] + bbox[3]) / 2
    return any(r.x0 <= cx <= r.x1 and r.y0 <= cy <= r.y1 for r in rects)


def extract_elements(pdf_path: str) -> tuple[list[Element], dict]:
    """
    Turn a PDF into ordered elements. Also returns extraction statistics
    (pages, tables found, furniture lines removed) for the IDP report.
    """
    pdf = pymupdf.open(pdf_path)

    # ---- Pass 1: find the dominant (body) font size and repeating lines ----
    size_weights: Counter = Counter()
    line_pages: dict[str, set[int]] = {}
    for page in pdf:
        for block in page.get_text("dict")["blocks"]:
            for line in block.get("lines", []):
                text = normalize_text("".join(s["text"] for s in line["spans"]))
                if not text:
                    continue
                for span in line["spans"]:
                    size_weights[round(span["size"], 1)] += len(span["text"])
                line_pages.setdefault(_furniture_key(text), set()).add(page.number)
    body_size = size_weights.most_common(1)[0][0] if size_weights else 10.0
    min_pages = max(3, int(pdf.page_count * REPEAT_THRESHOLD))
    furniture = {k for k, pages in line_pages.items() if len(pages) >= min_pages and len(k) < 160}

    # ---- Pass 2: build elements page by page ----
    elements: list[Element] = []
    stats = {"pages": pdf.page_count, "tables": 0, "headings": 0, "paragraphs": 0,
             "furniture_lines_removed": 0, "body_font_size": body_size}

    for page in pdf:
        page_no = page.number + 1

        # 2a. Tables first, so their text is not duplicated as paragraphs.
        tables = []
        try:
            for tab in page.find_tables().tables:
                markdown = table_to_markdown(tab.extract())
                if markdown:
                    tables.append((tab.bbox[1], Element("table", markdown, page_no), pymupdf.Rect(tab.bbox)))
        except Exception:  # table detection is best effort; never fail the whole document
            tables = []
        table_rects = [t[2] for t in tables]
        stats["tables"] += len(tables)

        # 2b. Text blocks outside tables, in the PDF's natural reading order.
        page_items: list[tuple[float, Element]] = []
        for block in page.get_text("dict")["blocks"]:
            if block.get("type") != 0 or _inside(block["bbox"], table_rects):
                continue
            paragraph_lines: list[str] = []
            for line in block.get("lines", []):
                text = normalize_text("".join(s["text"] for s in line["spans"]))
                if not text:
                    continue
                if _furniture_key(text) in furniture:
                    stats["furniture_lines_removed"] += 1
                    continue
                span = max(line["spans"], key=lambda s: len(s["text"]))
                bold = bool(span["flags"] & 16) or "bold" in span["font"].lower()
                if _is_heading(text, span["size"], bold, body_size) and not paragraph_lines:
                    heading = text.lstrip("-:. ").strip()          # drop bullet remnants: "- Claims" -> "Claims"
                    page_items.append((line["bbox"][1], Element("heading", heading, page_no)))
                    stats["headings"] += 1
                else:
                    paragraph_lines.append(text)
            if paragraph_lines:
                page_items.append((block["bbox"][1], Element("paragraph", _join_lines(paragraph_lines), page_no)))
                stats["paragraphs"] += 1

        # 2c. Slot each table in front of the first text item that starts below it.
        for y_top, table_el, _ in tables:
            idx = next((i for i, (y, _) in enumerate(page_items) if y > y_top), len(page_items))
            page_items.insert(idx, (y_top, table_el))

        elements.extend(el for _, el in page_items)

    pdf.close()
    return _merge_adjacent_paragraphs(elements), stats


def _join_lines(lines: list[str]) -> str:
    """Join wrapped lines, repairing words hyphenated across line breaks."""
    text = ""
    for line in lines:
        if text.endswith("-") and line[:1].islower():
            text = text[:-1] + line
        else:
            text = f"{text} {line}" if text else line
    return text


def _merge_adjacent_paragraphs(elements: list[Element]) -> list[Element]:
    """
    Brochure layouts often split one sentence over several tiny text blocks.
    Merge consecutive paragraphs on the same page when the first one does not
    end a sentence.
    """
    merged: list[Element] = []
    for el in elements:
        prev = merged[-1] if merged else None
        if (prev and el.type == prev.type == "paragraph" and el.page == prev.page
                and not prev.text.endswith((".", ":", "?", "!")) and len(prev.text) < 400):
            prev.text = f"{prev.text} {el.text}"
        else:
            merged.append(el)
    return merged


def page_texts(pdf_path: str) -> list[str]:
    """Plain normalised text per page (used for key-fact page selection and grounding checks)."""
    with pymupdf.open(pdf_path) as pdf:
        return [normalize_text(page.get_text()) for page in pdf]
