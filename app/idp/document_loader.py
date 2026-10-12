"""
IDP Stage 1 - Document ingestion & classification.

For every PDF we produce a `DocumentInfo` record that answers:
    * What is it?        -> company, product name, product type, document type
    * Can we identify it? -> regulatory identifiers (UIN / CIN) found in the text
    * Has it changed?     -> SHA-256 fingerprint (lets the pipeline skip unchanged files)

Information comes from three places, in order of trust:
    1. sources.json manifest (written when the brochures were downloaded)
    2. regular expressions over the document text (identifiers)
    3. keyword classifiers (fallback when no manifest entry exists)
"""
from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass, asdict
from pathlib import Path

import pymupdf

from app import config

# --------------------------------------------------------------------------- #
# Keyword rules used when a document is not described in sources.json.
# Order matters: the first type whose keywords score highest wins.
# --------------------------------------------------------------------------- #
PRODUCT_TYPE_KEYWORDS: dict[str, list[str]] = {
    "ulip": ["unit linked", "ulip", "fund value", "nav", "fund management charge"],
    "term_life": ["pure risk", "term plan", "term insurance", "death benefit", "life cover"],
    "savings": ["guaranteed income", "maturity benefit", "endowment", "savings", "guaranteed maturity"],
    "health": ["hospitalisation", "hospitalization", "sum insured", "cashless", "pre-existing"],
    "motor": ["own damage", "third party", "vehicle", "idv", "motor"],
    "travel": ["trip", "passport", "baggage", "overseas", "travel"],
}

# Friendly labels for the UI.
PRODUCT_TYPE_LABELS = {
    "term_life": "Term Life",
    "savings": "Savings",
    "ulip": "ULIP (Investment)",
    "health": "Health",
    "motor": "Motor",
    "travel": "Travel",
    "other": "Other",
}

# Indian insurance identifiers: IRDAI Unique Identification Number of a product
# (e.g. 104N118V13, BAJHLIP26073V082526, IRDAN113RP0025V01200102) and company CIN.
UIN_PATTERN = re.compile(r"\bUIN\s*(?:No\.?|Number)?\s*[:\-]?\s*([A-Z0-9]{8,30})\b", re.IGNORECASE)
CIN_PATTERN = re.compile(r"\bCIN\s*(?:No\.?)?\s*[:\-]?\s*([LU]\d{5}[A-Z]{2}\d{4}[A-Z]{3}\d{6})\b", re.IGNORECASE)


@dataclass
class DocumentInfo:
    """Everything we know about a source document before reading its content in depth."""
    doc_id: str                      # stable id derived from the file name
    file_name: str
    file_path: str
    sha256: str
    page_count: int
    company: str
    product_name: str
    product_type: str                # one of PRODUCT_TYPE_LABELS keys
    product_type_label: str
    doc_type: str                    # brochure | prospectus | policy_wording | leaflet
    source_url: str = ""
    uin: str = ""
    cin: str = ""
    pdf_title: str = ""
    classification_method: str = ""  # "manifest" or "keywords" (recorded in the IDP output for transparency)

    def to_dict(self) -> dict:
        return asdict(self)


def file_sha256(path: Path) -> str:
    """Fingerprint a file so re-runs can skip documents that have not changed."""
    digest = hashlib.sha256()
    with path.open("rb") as fh:
        for block in iter(lambda: fh.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def load_manifest() -> dict[str, dict]:
    """Read sources.json (if present) and index it by file name."""
    if not config.SOURCES_FILE.exists():
        return {}
    entries = json.loads(config.SOURCES_FILE.read_text(encoding="utf-8"))
    return {entry["file"]: entry for entry in entries}


def classify_product_type(text: str) -> str:
    """Keyword-vote classifier: count keyword hits per product type, highest wins."""
    lowered = text.lower()
    scores = {ptype: sum(lowered.count(k) for k in words) for ptype, words in PRODUCT_TYPE_KEYWORDS.items()}
    best = max(scores, key=scores.get)
    return best if scores[best] > 0 else "other"


def classify_doc_type(file_name: str, cover_text: str, page_count: int) -> str:
    """Decide whether the PDF is a brochure, a prospectus, a policy wording or a short leaflet."""
    haystack = (file_name + " " + cover_text).lower()
    if "prospectus" in haystack:
        return "prospectus"
    if "policy wording" in haystack or "policy document" in haystack:
        return "policy_wording"
    if page_count <= 4:
        return "leaflet"
    return "brochure"


def _guess_from_filename(file_name: str) -> tuple[str, str]:
    """Fallback company/product guess: 'hdfc_life_sanchay_plus_brochure.pdf' -> ('Hdfc Life', 'Sanchay Plus')."""
    parts = Path(file_name).stem.replace("_brochure", "").split("_")
    company = " ".join(parts[:2]).title()
    product = " ".join(parts[2:]).title() or company
    return company, product


def load_document(path: Path, manifest: dict[str, dict]) -> DocumentInfo:
    """Open a PDF and build its DocumentInfo record."""
    with pymupdf.open(path) as pdf:
        page_count = pdf.page_count
        pdf_title = (pdf.metadata or {}).get("title", "") or ""
        # The cover page states what kind of document this is ("Prospectus", "Policy Wording").
        # Later pages often merely *mention* other documents, so they are not used for this.
        cover_text = pdf[0].get_text() + " " + pdf_title
        full_text = " ".join(page.get_text() for page in pdf)

    entry = manifest.get(path.name)
    if entry:
        company, product = entry["company"], entry["product"]
        product_type, method = entry.get("product_type", "other"), "manifest"
        source_url = entry.get("source_url", "")
    else:
        company, product = _guess_from_filename(path.name)
        product_type, method = classify_product_type(full_text), "keywords"
        source_url = ""

    uin_match = UIN_PATTERN.search(full_text)
    cin_match = CIN_PATTERN.search(full_text)

    return DocumentInfo(
        doc_id=path.stem,
        file_name=path.name,
        file_path=str(path),
        sha256=file_sha256(path),
        page_count=page_count,
        company=company,
        product_name=product,
        product_type=product_type,
        product_type_label=PRODUCT_TYPE_LABELS.get(product_type, product_type.title()),
        doc_type=(entry or {}).get("doc_type") or classify_doc_type(path.name, cover_text, page_count),
        source_url=source_url,
        uin=uin_match.group(1).upper() if uin_match else "",
        cin=cin_match.group(1).upper() if cin_match else "",
        pdf_title=pdf_title.strip(),
        classification_method=method,
    )


def discover_documents() -> list[DocumentInfo]:
    """Load every PDF in the brochure folder."""
    manifest = load_manifest()
    return [load_document(p, manifest) for p in sorted(config.BROCHURE_DIR.glob("*.pdf"))]
