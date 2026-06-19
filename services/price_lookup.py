import pandas as pd
from typing import Optional, Tuple
from rapidfuzz import fuzz, process
# normalized_name -> price
_prices: dict[str, int] = {}
# normalized_name -> original/canonical name as written in the source file
# (this is what gets shown to the user; _prices keys are normalized text
# and are NOT fit for display — lowercased, synonym-collapsed, ZWNJ-stripped)
_canonical_names: dict[str, str] = {}
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
# Persian/Arabic digits -> normal digits, in case product names/queries contain numbers.
# Covers both Persian (۰-۹) and Arabic-Indic (٠-٩) digit blocks — they look similar
# but are different Unicode code points, and Arabic-Indic digits show up often in
# text copy-pasted from phone keyboards set to Arabic locale.
_DIGIT_MAP = {
    "۰": "0", "۱": "1", "۲": "2", "۳": "3", "۴": "4",
    "۵": "5", "۶": "6", "۷": "7", "۸": "8", "۹": "9",
    "٠": "0", "١": "1", "٢": "2", "٣": "3", "٤": "4",
    "٥": "5", "٦": "6", "٧": "7", "٨": "8", "٩": "9",
}
# Multi-word phrases customers use interchangeably with a catalog term.
# Applied as a plain string replace BEFORE tokenizing (order matters: longer
# phrases first so e.g. "تلفن همراه" is caught before lone "تلفن").
_PHRASE_SYNONYMS = [
    ("تلفن همراه", "گوشی"),
    ("نوت بوک", "لپتاپ"),
    ("نوتبوک", "لپتاپ"),
    ("لپ تاپ", "لپتاپ"),
    # Multi-token brand transliterations MUST go here, not in _WORD_SYNONYMS:
    # _WORD_SYNONYMS is applied per single token after splitting, so a
    # two-word Persian spelling like "مک بوک" would never match there —
    # it'd be checked as "مک" and "بوک" separately and neither equals the
    # dict key "مک بوک". Phrase replace runs first, on the raw string.
    ("مک بوک", "macbook"),
    ("ال جی", "lg"),
    ("اچ پی", "hp"),
]
# Single-word synonyms, applied per-token AFTER tokenizing.
_WORD_SYNONYMS = {
    "موبایل": "گوشی",
    "تلفن": "گوشی",
}
# Brand-name transliterations: maps the common Persian spelling of a brand to
# its Latin spelling, so a Persian-typed query matches a catalog that stores
# brand names in Latin script (very common — sellers often write "Samsung",
# "Asus", "iPhone" in their Excel files even though customers type in Persian).
# rapidfuzz scores character similarity, so "سامسونگ" vs "samsung" looks like
# two unrelated strings to it even at 100% normalization elsewhere — this map
# is the only thing that bridges that gap. It is NOT exhaustive; extend it as
# new brands show up in real conversations or catalogs.
# NOTE: this is merged into _WORD_SYNONYMS at import time (see below), so it's
# applied as part of the same per-token pass — no separate pipeline step.
_BRAND_TRANSLITERATIONS = {
    "سامسونگ": "samsung",
    "اپل": "apple",
    "ایفون": "iphone",
    "آیفون": "iphone",
    "شیائومی": "xiaomi",
    "هواوی": "huawei",
    "ایسوس": "asus",
    "لنوو": "lenovo",
    "نوکیا": "nokia",
    "سونی": "sony",
    "دل": "dell",
    "گلکسی": "galaxy",
    # NOTE: "مک بوک", "ال جی", "اچ پی" are NOT here — they're two tokens each
    # after split() and belong in _PHRASE_SYNONYMS above instead, where the
    # replace runs on the raw string before tokenizing.
}
_WORD_SYNONYMS.update(_BRAND_TRANSLITERATIONS)
def normalize_text(text: str) -> str:
    """Make Persian text comparable: unify character variants, fix spacing,
    apply synonym mapping, lowercase."""
    text = str(text).strip().lower()
    for src, dst in {**_CHAR_MAP, **_DIGIT_MAP}.items():
        text = text.replace(src, dst)
    for phrase, canonical in _PHRASE_SYNONYMS:
        text = text.replace(phrase, canonical)
    # ZWNJ -> space above can produce doubled/irregular whitespace (e.g. from
    # "می‌خوام" or copy-pasted chat text with stray spaces); collapse it via
    # split()/join() rather than a second strip(), which only trims the ends.
    tokens = text.split()
    tokens = [_WORD_SYNONYMS.get(tok, tok) for tok in tokens]
    return " ".join(tokens)
def _parse_df(df: pd.DataFrame) -> Tuple[dict[str, int], dict[str, str]]:
    """Returns (prices, canonical_names), both keyed by normalized_name.

    If two rows normalize to the same key (e.g. "لپ تاپ X" and "لپتاپ X"),
    the later row in the file silently wins for both dicts — same behavior
    as the original code had for _prices, just made explicit here so it's
    not a surprise during a future refactor.
    """
    prices: dict[str, int] = {}
    canonical_names: dict[str, str] = {}
    for _, row in df.iterrows():
        raw_name = str(row["product"])
        key = normalize_text(raw_name)
        prices[key] = int(row["price"])
        canonical_names[key] = raw_name.strip()
    return prices, canonical_names
def load_prices(filepath: str) -> dict[str, int]:
    global _prices, _product_names, _canonical_names
    df = pd.read_excel(filepath)
    _prices, _canonical_names = _parse_df(df)
    _product_names = list(_prices.keys())
    return _prices
def load_prices_from_df(df: pd.DataFrame) -> dict[str, int]:
    global _prices, _product_names, _canonical_names
    _prices, _canonical_names = _parse_df(df)
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
def find_top_matches(item_name: str, limit: int = 3) -> list[Tuple[str, float]]:
    """
    Returns up to `limit` (normalized_name, score) candidates, best first,
    with no threshold filtering. Used when the top match alone isn't confident
    enough to answer outright but a "did you mean X or Y?" reply is still useful.
    Returns an empty list if there's no catalog loaded or no input.
    """
    query = normalize_text(item_name)
    if not query or not _prices:
        return []
    results = process.extract(query, _product_names, scorer=fuzz.WRatio, limit=limit)
    return [(name, score) for name, score, _ in results]
def get_price(item_name: str, threshold: float = 70.0) -> Optional[Tuple[str, int]]:
    """
    Returns a tuple of (canonical_product_name, price) if found, else None.
    canonical_product_name is the original text as written in the source file
    (not the normalized matching key) — this is what's safe to show the user.
    """
    match = find_best_match(item_name, threshold)
    if match is None:
        return None
    matched_key, _score = match

    price = _prices.get(matched_key)
    if price is None:
        return None

    canonical_name = _canonical_names.get(matched_key, matched_key)
    return canonical_name, price