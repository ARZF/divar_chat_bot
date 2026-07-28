from dataclasses import dataclass, field
import logging
from typing import Optional, Tuple

import pandas as pd
from rapidfuzz import fuzz, process
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from models.product import Product

logger = logging.getLogger("price_lookup")

# ---------------------------------------------------------------------------
# Per-client in-memory caches (rebuilt from DB via refresh_lookup_cache)
# ---------------------------------------------------------------------------
@dataclass(slots=True) # reduces memory usage
class ClientPriceCache:
    prices: dict[str, int] = field(default_factory=dict)          # normalized_name -> price
    canonical_names: dict[str, str] = field(default_factory=dict) # normalized_name -> item_name
    product_names: list[str] = field(default_factory=list)        # [normalized_name, ...]

_cache: dict[int, ClientPriceCache] = {}

# ---------------------------------------------------------------------------
# Character / synonym maps (unchanged from Phase 1)
# ---------------------------------------------------------------------------
_CHAR_MAP = {
    "ي": "ی",   # Arabic yeh -> Persian yeh
    "ك": "ک",   # Arabic kaf -> Persian kaf
    "ۀ": "ه",   # heh with hamza -> heh
    "\u200c": " ",  # ZWNJ (half-space) -> regular space
    "\u200f": "",   # RTL mark -> drop
    "آ": "ا",
}
_DIGIT_MAP = {
    "۰": "0", "۱": "1", "۲": "2", "۳": "3", "۴": "4",
    "۵": "5", "۶": "6", "۷": "7", "۸": "8", "۹": "9",
    "٠": "0", "١": "1", "٢": "2", "٣": "3", "٤": "4",
    "٥": "5", "٦": "6", "٧": "7", "٨": "8", "٩": "9",
}
_PHRASE_SYNONYMS = [
    ("تلفن همراه", "گوشی"),
    ("نوت بوک", "لپتاپ"),
    ("نوتبوک", "لپتاپ"),
    ("لپ تاپ", "لپتاپ"),
    ("مک بوک", "macbook"),
    ("ال جی", "lg"),
    ("اچ پی", "hp"),
]
_WORD_SYNONYMS: dict[str, str] = {
    "موبایل": "گوشی",
    "تلفن": "گوشی",
}
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
}
_WORD_SYNONYMS.update(_BRAND_TRANSLITERATIONS)


# ---------------------------------------------------------------------------
# Text normalization (pure function, no DB or client_id dependency)
# ---------------------------------------------------------------------------
_NORMALIZATION_MAP = {
    **_CHAR_MAP,
    **_DIGIT_MAP,
}

def normalize_text(text: str) -> str:
    """Make Persian text comparable: unify character variants, fix spacing,
    apply synonym mapping, lowercase."""
    text = str(text).strip().lower()
    for src, dst in _NORMALIZATION_MAP.items():
        text = text.replace(src, dst)
    for phrase, canonical in _PHRASE_SYNONYMS:
        text = text.replace(phrase, canonical)
    tokens = text.split()
    tokens = [_WORD_SYNONYMS.get(tok, tok) for tok in tokens]
    return " ".join(tokens)


# ---------------------------------------------------------------------------
# DataFrame parser (pure function, unchanged from Phase 1)
# ---------------------------------------------------------------------------
def _parse_df(df: pd.DataFrame) -> Tuple[dict[str, int], dict[str, str]]:
    """Returns (prices, canonical_names), both keyed by normalized_name.

    Safely skips rows with missing prices (NaN) or headers treated as data.
    """
    prices: dict[str, int] = {}
    canonical_names: dict[str, str] = {}

    for row in df.itertuples(index=False):
        raw_price = row.price
        if pd.isna(raw_price):
            continue

        price_str = str(raw_price).strip()
        if price_str.endswith('.0'):
            price_str = price_str[:-2]

        if not price_str.isdigit():
            logger.warning(
                "Skipping invalid non-numeric price row",
                extra={"raw_price": price_str},
            )
            continue

        raw_name = str(row.product)
        key = normalize_text(raw_name)

        prices[key] = int(price_str)
        canonical_names[key] = raw_name.strip()

    return prices, canonical_names


# ---------------------------------------------------------------------------
# DB-backed cache management
# ---------------------------------------------------------------------------
async def refresh_lookup_cache(db: AsyncSession, client_id: int) -> None:
    """Rebuild the in-memory fuzzy-search cache for *one* client from the
    ``products`` table. Call on app startup (per known client) and after every
    admin upload for the affected client."""
    stmt = select(Product).where(Product.client_id == client_id)
    result = await db.execute(stmt)
    products = result.scalars().all()

    prices: dict[str, int] = {}
    canonical: dict[str, str] = {}
    for p in products:
        prices[p.normalized_name] = p.price
        canonical[p.normalized_name] = p.item_name

    _cache[client_id] = ClientPriceCache(
        prices=prices,
        canonical_names=canonical,
        product_names=list(prices.keys()),
    )


async def load_prices_to_db(
    db: AsyncSession, client_id: int, df: pd.DataFrame
) -> int:
    """Transactional replace: delete all products for *client_id*, insert new
    rows parsed from *df*, commit, then refresh the in-memory cache.

    Returns the number of rows inserted.
    """
    parsed_prices, parsed_canonical = _parse_df(df)

    # Scoped delete — only this client's products
    await db.execute(
        delete(Product).where(Product.client_id == client_id)
    )

    # Scoped insert — tagged with this client_id
    products = [
        Product(
            client_id=client_id,
            item_name=parsed_canonical.get(normalized_name, normalized_name),
            normalized_name=normalized_name,
            price=price,
        )
        for normalized_name, price in parsed_prices.items()
    ]

    db.add_all(products)

    await db.commit()
    await refresh_lookup_cache(db, client_id)

    return len(parsed_prices)


# ---------------------------------------------------------------------------
# Lookup functions — all client_id-scoped
# ---------------------------------------------------------------------------
def find_best_match(
    client_id: int, item_name: str, threshold: float = 70.0
) -> Optional[Tuple[str, float]]:
    """Returns (matched_normalized_name, score) or None.
    score is 0-100; 100 means exact match after normalization."""
    entry = _cache.get(client_id)
    query = normalize_text(item_name)
    if not query or not entry or not entry.prices:
        return None
    if query in entry.prices:
        return query, 100.0
    result = process.extractOne(query, entry.product_names, scorer=fuzz.WRatio)
    if result is None:
        return None
    matched_name, score, _ = result
    if score >= threshold:
        return matched_name, score
    return None


def find_top_matches(
    client_id: int, item_name: str, limit: int = 3
) -> list[Tuple[str, float]]:
    """Returns up to *limit* (normalized_name, score) candidates, best first."""
    entry = _cache.get(client_id)
    query = normalize_text(item_name)
    if not query or not entry or not entry.prices:
        return []
    results = process.extract(query, entry.product_names, scorer=fuzz.WRatio, limit=limit)
    return [(name, score) for name, score, _ in results]


def get_all_matching_prices(
    client_id: int, item_name: str
) -> list[Tuple[str, int]]:
    """Substring matches: all products whose normalized name contains *query*.
    Returns [(canonical_product_name, price), ...]."""
    entry = _cache.get(client_id)
    query = normalize_text(item_name)

    if not query or not entry or not entry.prices:
        return []

    matches = []
    for normalized_key, price in entry.prices.items():
        if query in normalized_key:
            canonical_name = entry.canonical_names.get(normalized_key, normalized_key)
            matches.append((canonical_name, price))
    return matches


async def get_price(
    db: AsyncSession,
    client_id: int,
    item_name: str,
    threshold: float = 70.0,
) -> Optional[Tuple[str, int]]:
    """Returns (canonical_product_name, price) if found, else None.

    Two-stage lookup with defense-in-depth:
    1. Fuzzy match against the in-memory cache to resolve a candidate
       ``normalized_name`` (scoped to *client_id*).
    2. Re-fetch that row from the ``products`` table filtered by
       ``client_id`` and the matched ``normalized_name``, and return the
       **DB** values (source of truth). If the cache hit but the DB row is
       gone (deleted since the cache was warmed) or the price was changed,
       the DB wins; a pure cache miss (no DB row) is treated as "not found"
       and logged as a cache/DB divergence signal.
    """
    match = find_best_match(client_id, item_name, threshold)
    if match is None:
        return None
    matched_key, _score = match

    # Defense-in-depth: the cache is only a fuzzy index; the DB is the
    # source of truth. Re-verify against products scoped to this tenant.
    stmt = select(Product.item_name, Product.price).where(
        Product.client_id == client_id,
        Product.normalized_name == matched_key,
    )
    result = await db.execute(stmt)
    row = result.first()
    if row is None:
        # Cache said "match" but DB says "no such product for this client"
        # — stale cache (deleted/replaced catalog). Treat as not found and
        # log the divergence for observability.
        logger.info(
            "price lookup cache/DB divergence: cache hit but no DB row",
            extra={"client_id": client_id, "matched_key": matched_key},
        )
        return None

    return row.item_name, row.price
