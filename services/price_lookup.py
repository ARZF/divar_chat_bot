import pandas as pd
from typing import Optional, Tuple
from rapidfuzz import fuzz, process

# normalized_name -> price
_prices: dict[str, int] = {}
# list of normalized names, kept in sync with _prices (used for fuzzy search)
_product_names: list[str] = []

# Map inconsistent Persian/Arabic characters to one canonical form.
# Extend this as you notice more variants in your real data.
_CHAR_MAP = {
    "ي": "ی",   # Arabic yeh -> Persian yeh
    "ك": "ک",   # Arabic kaf -> Persian kaf
    "ۀ": "ه",   # heh with hamza -> heh
    "\u200c": " ",  # ZWNJ (half-space) -> regular space
    "\u200f": "",   # RTL mark -> drop
    "آ": "ا",
}

# Persian/Arabic digits -> normal digits, in case product names/queries contain numbers
_DIGIT_MAP = {
    "۰": "0", "۱": "1", "۲": "2", "۳": "3", "۴": "4",
    "۵": "5", "۶": "6", "۷": "7", "۸": "8", "۹": "9",
}

# Multi-word phrases customers use interchangeably with a catalog term.
# Applied as a plain string replace BEFORE tokenizing (order matters: longer
# phrases first so e.g. "تلفن همراه" is caught before lone "تلفن").
_PHRASE_SYNONYMS = [
    ("تلفن همراه", "گوشی"),
    ("نوت بوک", "لپتاپ"),
    ("نوتبوک", "لپتاپ"),
    ("لپ تاپ", "لپتاپ"),
]

# Single-word synonyms, applied per-token AFTER tokenizing.
_WORD_SYNONYMS = {
    "موبایل": "گوشی",
    "تلفن": "گوشی",
}


def normalize_text(text: str) -> str:
    """Make Persian text comparable: unify character variants, fix spacing,
    apply synonym mapping, lowercase."""
    text = str(text).strip().lower()
    for src, dst in {**_CHAR_MAP, **_DIGIT_MAP}.items():
        text = text.replace(src, dst)

    for phrase, canonical in _PHRASE_SYNONYMS:
        text = text.replace(phrase, canonical)

    tokens = text.split()
    tokens = [_WORD_SYNONYMS.get(tok, tok) for tok in tokens]

    return " ".join(tokens)


def _parse_df(df: pd.DataFrame) -> dict[str, int]:
    return {
        normalize_text(row["product"]): int(row["price"])
        for _, row in df.iterrows()
    }


def load_prices(filepath: str) -> dict[str, int]:
    global _prices, _product_names
    df = pd.read_excel(filepath)
    _prices = _parse_df(df)
    _product_names = list(_prices.keys())
    return _prices


def load_prices_from_df(df: pd.DataFrame) -> dict[str, int]:
    global _prices, _product_names
    _prices = _parse_df(df)
    _product_names = list(_prices.keys())
    return _prices


def find_best_match(item_name: str, threshold: float = 70.0) -> Optional[Tuple[str, float]]:
    """
    Returns (matched_normalized_name, score) or None.
    score is 0-100; 100 means exact match after normalization.
    """
    query = normalize_text(item_name)
    if not query or not _prices:
        return None

    if query in _prices:
        return query, 100.0

    result = process.extractOne(query, _product_names, scorer=fuzz.WRatio)
    if result is None:
        return None

    matched_name, score, _ = result
    if score >= threshold:
        return matched_name, score
    return None


def get_price(item_name: str, threshold: float = 70.0) -> Optional[Tuple[str, int]]:
    """
    Returns a tuple of (canonical_product_name, price) if found, else None.
    """
    match = find_best_match(item_name, threshold)
    if match is None:
        return None
    matched_name, _score = match
    
    price = _prices.get(matched_name)
    if price is None:
        return None
        
    return matched_name, price