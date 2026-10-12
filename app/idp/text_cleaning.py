"""
Text clean-up for PDF extraction.

PDF text is messy: ligatures ("\ufb01" for "fi"), smart quotes, symbol-font
bullets stored in the Unicode private-use area, Wingdings bullets mapped onto
Latin letters, and a "Rupee font" where the backtick draws the Rupee sign.
normalize_text() turns all of that into plain, consistent text.
"""
from __future__ import annotations

import re
import unicodedata


# --------------------------------------------------------------------------- #
# Text normalisation
# --------------------------------------------------------------------------- #
_REPLACEMENTS = {
    "\u2019": "'", "\u2018": "'", "\u201c": '"', "\u201d": '"',
    "\u2013": "-", "\u2014": "-", "\u2022": "-", "\uf0b7": "-", "\u25cf": "-", "\u25aa": "-",
    "\u20b9": "Rs. ",  # Indian Rupee sign - spelled out so every model/tokenizer handles it
    "\u00a0": " ", "\ufffd": "'",
}


def normalize_text(text: str) -> str:
    """NFKC-normalise (expands ligatures), replace typographic symbols, collapse whitespace."""
    text = unicodedata.normalize("NFKC", text)
    for src, dst in _REPLACEMENTS.items():
        text = text.replace(src, dst)
    # Symbol/Wingdings fonts put bullets in the Unicode private-use area (e.g. \uf0a7).
    # \uf020 is that font's space; every other private-use glyph is treated as a bullet.
    text = text.replace("\uf020", " ")
    text = re.sub(r"[\ue000-\uf8ff]", " - ", text)
    # Some brochures map Wingdings bullets onto Latin letters ("\u00f2", "\u00a7", "\u00d8").
    # Replace them only when they stand alone like a bullet, never inside words.
    text = re.sub(r"(^|\s)[\u00f2\u00fc\u00d8\u00a7](?=\s)", r"\1- ", text)
    # Indian brochures often use a "Rupee font" where the backtick key draws the Rupee sign.
    text = re.sub(r"`\s?(?=\d)", "Rs. ", text)
    text = re.sub(r"[ \t]+", " ", text)
    return text.strip()
