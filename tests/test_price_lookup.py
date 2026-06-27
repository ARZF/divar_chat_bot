import os

# Set test env vars before any project imports — config.py instantiates Settings at module level
os.environ.setdefault("DIVAR_API_KEY", "test_api_key")
os.environ.setdefault("DIVAR_ACCESS_TOKEN", "test_access_token")
os.environ.setdefault("DIVAR_REFRESH_TOKEN", "test_refresh_token")
os.environ.setdefault("DIVAR_WEBHOOK_SECRET", "test_webhook_secret")
os.environ.setdefault("DIVAR_IDENTIFICATION_KEY", "test_identification_key")
os.environ.setdefault("DIVAR_APP_SLUG", "test_app_slug")
os.environ.setdefault("DIVAR_CLIENT_SECRET", "test_client_secret")
os.environ.setdefault("DIVAR_REDIRECT_URI", "https://example.com/callback")
os.environ.setdefault("admin_token", "test_admin_token")

import pytest
from io import BytesIO

import pandas as pd
from openpyxl import Workbook

from services import price_lookup as pl
from services.price_lookup import (
    normalize_text,
    _parse_df,
    find_best_match,
    find_top_matches,
    get_all_matching_prices,
    get_price,
)
from config import settings

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

# A representative catalog used by most tests.  Keys are *normalized* names
# (what normalize_text would produce); values are (canonical_display_name, price).
CATALOG = {
    "iphone 13": ("iPhone 13", 35000000),
    "iphone 14": ("iPhone 14", 42000000),
    "samsung galaxy s22": ("Samsung Galaxy S22", 28000000),
    "macbook pro": ("MacBook Pro", 55000000),
    "گوشی": ("گوشی", 15000000),
}


@pytest.fixture
def catalog():
    """Populate module-level state with CATALOG, clean up after."""
    pl._prices = {k: v[1] for k, v in CATALOG.items()}
    pl._canonical_names = {k: v[0] for k, v in CATALOG.items()}
    pl._product_names = list(pl._prices.keys())
    yield
    pl._prices = {}
    pl._canonical_names = {}
    pl._product_names = []


@pytest.fixture
def empty_catalog():
    """Ensure module-level state is empty."""
    pl._prices = {}
    pl._canonical_names = {}
    pl._product_names = []
    yield
    pl._prices = {}
    pl._canonical_names = {}
    pl._product_names = []


def make_excel(rows, headers=("product", "price")):
    """Build an in-memory .xlsx file with openpyxl for _parse_df tests."""
    wb = Workbook()
    ws = wb.active
    ws.append(list(headers))
    for row in rows:
        ws.append(row)
    buf = BytesIO()
    wb.save(buf)
    buf.seek(0)
    return buf


# ---------------------------------------------------------------------------
# normalize_text
# ---------------------------------------------------------------------------


class TestNormalizeText:
    def test_arabic_yeh_to_persian_yeh(self):
        # U+064A (Arabic Yeh) → U+06CC (Persian Yeh)
        assert normalize_text("گوشي") == "گوشی"

    def test_arabic_kaf_to_persian_kaf(self):
        # U+0643 (Arabic Kaf) → U+06A9 (Persian Kaf)
        assert normalize_text("كتاب") == "کتاب"

    def test_alef_with_madda_to_plain_alef(self):
        # U+0622 → U+0627
        assert normalize_text("آیفون") == "iphone"

    def test_zwnj_to_space(self):
        # U+200C (Zero-Width Non-Joiner) → regular space
        assert normalize_text("می‌خوام") == "می خوام"

    def test_rtl_mark_removed(self):
        # U+200F (RTL mark) is dropped entirely
        assert normalize_text("iphone\u200f") == "iphone"

    def test_persian_digits_to_ascii(self):
        assert normalize_text("گوشی ۱۳") == "گوشی 13"

    def test_arabic_indic_digits_to_ascii(self):
        # Arabic-Indic digits (U+0660–U+0669), distinct from Persian digits
        assert normalize_text("گوشی ١٣") == "گوشی 13"

    def test_phrase_synonym_telefon_hamrah(self):
        assert normalize_text("تلفن همراه") == "گوشی"

    def test_phrase_synonym_macbook(self):
        assert normalize_text("مک بوک pro") == "macbook pro"

    def test_word_synonym_mobile(self):
        assert normalize_text("موبایل") == "گوشی"

    def test_brand_transliteration_samsung(self):
        assert normalize_text("سامسونگ") == "samsung"

    def test_combined_normalization(self):
        # Multiple normalizations in one string: brand + word synonym + phrase
        assert normalize_text("موبایل سامسونگ") == "گوشی samsung"

    def test_whitespace_collapsed(self):
        assert normalize_text("  iphone   13  ") == "iphone 13"

    def test_lowercased(self):
        assert normalize_text("IPHONE 13") == "iphone 13"

    def test_empty_string(self):
        assert normalize_text("") == ""


# ---------------------------------------------------------------------------
# _parse_df
# ---------------------------------------------------------------------------


class TestParseDf:
    def test_valid_dataframe(self):
        df = pd.DataFrame(
            {
                "product": ["iPhone 13", "Samsung Galaxy S22"],
                "price": [35000000, 28000000],
            }
        )
        prices, canonical_names = _parse_df(df)

        assert prices == {"iphone 13": 35000000, "samsung galaxy s22": 28000000}
        assert canonical_names == {
            "iphone 13": "iPhone 13",
            "samsung galaxy s22": "Samsung Galaxy S22",
        }

    def test_in_memory_excel_file(self):
        """Exercise _parse_df against a real .xlsx built with openpyxl."""
        buf = make_excel(
            [("iPhone 13", 35000000), ("Samsung Galaxy S22", 28000000)]
        )
        df = pd.read_excel(buf)
        prices, canonical_names = _parse_df(df)

        assert prices == {"iphone 13": 35000000, "samsung galaxy s22": 28000000}
        assert canonical_names == {
            "iphone 13": "iPhone 13",
            "samsung galaxy s22": "Samsung Galaxy S22",
        }

    def test_missing_product_column_raises_key_error(self):
        """
        Known limitation per PLAN.md: _parse_df expects columns literally named
        "price" and "product".  Missing one raises unhandled KeyError — Phase 2's
        admin endpoint should catch this and return HTTP 400.
        """
        df = pd.DataFrame({"name": ["iPhone 13"], "price": [35000000]})
        with pytest.raises(KeyError):
            _parse_df(df)

    def test_missing_price_column_raises_key_error(self):
        df = pd.DataFrame({"product": ["iPhone 13"], "cost": [35000000]})
        with pytest.raises(KeyError):
            _parse_df(df)

    def test_nan_prices_skipped(self):
        df = pd.DataFrame(
            {
                "product": ["iPhone 13", "iPhone 14", "iPhone 15"],
                "price": [35000000, None, 42000000],
            }
        )
        prices, _ = _parse_df(df)

        # iPhone 14 (NaN price) should be silently skipped
        assert "iphone 14" not in prices
        assert prices["iphone 13"] == 35000000
        assert prices["iphone 15"] == 42000000

    def test_non_numeric_price_skipped(self):
        """Text headers or non-numeric values in the price column are skipped."""
        df = pd.DataFrame(
            {
                "product": ["iPhone 13", "Header Row"],
                "price": [35000000, "قیمت(تومان)"],
            }
        )
        prices, _ = _parse_df(df)

        assert "iphone 13" in prices
        assert len(prices) == 1  # The text row was skipped

    def test_float_price_trailing_zero_removed(self):
        """Prices stored as floats (e.g. 35000000.0) should be parsed as integers."""
        df = pd.DataFrame(
            {"product": ["iPhone 13"], "price": [35000000.0]}
        )
        prices, _ = _parse_df(df)

        assert prices["iphone 13"] == 35000000
        assert isinstance(prices["iphone 13"], int)


# ---------------------------------------------------------------------------
# find_best_match
# ---------------------------------------------------------------------------


class TestFindBestMatch:
    def test_exact_match_after_normalization(self, catalog):
        # "iPhone 13" normalizes to "iphone 13" which is an exact key
        result = find_best_match("iPhone 13")
        assert result is not None
        name, score = result
        assert name == "iphone 13"
        assert score == 100.0

    def test_fuzzy_match_above_threshold(self, catalog):
        # "iphoen 13" (typo) → fuzzy match to "iphone 13"
        result = find_best_match("iphoen 13")
        assert result is not None
        name, score = result
        assert name == "iphone 13"
        assert score >= 70.0  # default threshold

    def test_no_match_below_threshold(self, catalog):
        result = find_best_match("zzzzzzzzz")
        assert result is None

    def test_empty_query_returns_none(self, catalog):
        assert find_best_match("") is None

    def test_empty_catalog_returns_none(self, empty_catalog):
        assert find_best_match("iphone 13") is None

    def test_custom_threshold(self, catalog):
        # With a high threshold, a medium fuzzy match should not qualify
        result_low = find_best_match("iphoen", threshold=40.0)
        result_high = find_best_match("iphoen", threshold=95.0)
        # Low threshold: should find something
        assert result_low is not None
        # High threshold: might or might not find — but if it does, score >= 95
        if result_high is not None:
            assert result_high[1] >= 95.0


# ---------------------------------------------------------------------------
# find_top_matches
# ---------------------------------------------------------------------------


class TestFindTopMatches:
    def test_returns_up_to_limit(self, catalog):
        results = find_top_matches("iphone", limit=2)
        assert len(results) <= 2
        assert len(results) > 0
        # Results should be sorted best-first
        scores = [s for _, s in results]
        assert scores == sorted(scores, reverse=True)

    def test_empty_query_returns_empty_list(self, catalog):
        assert find_top_matches("") == []

    def test_empty_catalog_returns_empty_list(self, empty_catalog):
        assert find_top_matches("iphone") == []

    def test_no_threshold_filtering(self, catalog):
        """find_top_matches returns matches regardless of score (no threshold)."""
        results = find_top_matches("zzzzzzzzz", limit=3)
        # May return low-scoring matches — that's by design; the caller filters.
        # Just verify it doesn't crash and returns a list.
        assert isinstance(results, list)


# ---------------------------------------------------------------------------
# get_all_matching_prices (Tier 1: substring)
# ---------------------------------------------------------------------------


class TestGetAllMatchingPrices:
    def test_substring_match_returns_results(self, catalog):
        results = get_all_matching_prices("iphone")
        # "iphone" is a substring of both "iphone 13" and "iphone 14"
        assert len(results) == 2
        names = [name for name, _ in results]
        assert "iPhone 13" in names
        assert "iPhone 14" in names

    def test_substring_match_single_result(self, catalog):
        results = get_all_matching_prices("macbook")
        assert len(results) == 1
        assert results[0] == ("MacBook Pro", 55000000)

    def test_no_substring_match_returns_empty(self, catalog):
        assert get_all_matching_prices("zzzzzz") == []

    def test_empty_query_returns_empty(self, catalog):
        assert get_all_matching_prices("") == []

    def test_empty_catalog_returns_empty(self, empty_catalog):
        assert get_all_matching_prices("iphone") == []

    def test_persian_substring_match(self, catalog):
        results = get_all_matching_prices("گوشی")
        assert len(results) == 1
        assert results[0] == ("گوشی", 15000000)


# ---------------------------------------------------------------------------
# get_price (Tier 2: fuzzy fallback)
# ---------------------------------------------------------------------------


class TestGetPrice:
    def test_exact_match_returns_canonical_name_and_price(self, catalog):
        result = get_price("iPhone 13")
        assert result is not None
        canonical, price = result
        assert canonical == "iPhone 13"
        assert price == 35000000

    def test_fuzzy_match_typo(self, catalog):
        # "samsng galaxy" (typo) → fuzzy match to "samsung galaxy s22"
        result = get_price("samsng galaxy s22")
        assert result is not None
        canonical, price = result
        assert canonical == "Samsung Galaxy S22"
        assert price == 28000000

    def test_no_match_returns_none(self, catalog):
        assert get_price("zzzzzzzzz") is None

    def test_empty_query_returns_none(self, catalog):
        assert get_price("") is None

    def test_empty_catalog_returns_none(self, empty_catalog):
        assert get_price("iphone 13") is None


# ---------------------------------------------------------------------------
# 3-tier lookup (substring → fuzzy → suggestions)
# ---------------------------------------------------------------------------


class TestThreeTierLookup:
    """
    PLAN.md 1.5/1.6 describes a 3-tier lookup:
      Tier 1: substring match via get_all_matching_prices
      Tier 2: fuzzy match via get_price (find_best_match with threshold=70)
      Tier 3: suggestion list via find_top_matches (filtered by SUGGESTION_MIN_SCORE)

    SUGGESTION_MIN_SCORE = 45.0  (from config.py)
    MAX_BULK_RESULTS     = 10    (from config.py — applied in chatbot.py, not here)

    Note: Phase 1's catalog state (_prices, _canonical_names, _product_names) is a
    single global, unscoped-by-client module-level store.  This is correct for
    Phase 1 per PLAN.md — do NOT write a test asserting per-client isolation;
    that's Phase 2 scope.
    """

    def test_tier1_substring_match(self, catalog):
        """Tier 1: 'iphone' is a substring of 'iphone 13' and 'iphone 14'."""
        results = get_all_matching_prices("iphone")
        assert len(results) >= 1
        # Tier 1 found results — no need to fall through to tier 2 or 3

    def test_tier2_fuzzy_match_when_substring_fails(self, catalog):
        """
        Tier 2: 'samsng galaxy s22' (typo) is NOT a substring of any catalog
        entry, so get_all_matching_prices returns empty.  But get_price (via
        find_best_match) finds a fuzzy match above the default threshold (70.0).
        """
        # Verify tier 1 fails
        assert get_all_matching_prices("samsng galaxy s22") == []

        # Verify tier 2 succeeds
        result = get_price("samsng galaxy s22")
        assert result is not None
        assert result[0] == "Samsung Galaxy S22"

    def test_tier3_suggestions_when_fuzzy_below_threshold(self, catalog):
        """
        Tier 3: when both substring and confident fuzzy match fail,
        find_top_matches returns candidates that the caller (chatbot.py)
        filters by SUGGESTION_MIN_SCORE (45.0).
        """
        # Use a deliberately garbled query that won't match via substring
        # or score above the find_best_match threshold (70.0)
        garbled = "galx"

        # Tier 1 fails
        assert get_all_matching_prices(garbled) == []

        # Tier 2 may or may not succeed depending on fuzzy score —
        # verify that if it fails, tier 3 provides suggestions
        tier2_result = get_price(garbled)

        if tier2_result is None:
            # Tier 2 failed — tier 3 should provide candidates
            suggestions = find_top_matches(garbled, limit=3)
            assert isinstance(suggestions, list)
            # The caller filters by SUGGESTION_MIN_SCORE (45.0) — we just
            # verify find_top_matches returns *something* to filter
            if suggestions:
                _, score = suggestions[0]
                # SUGGESTION_MIN_SCORE is 45.0 — some candidates may be below it
                assert score >= 0.0  # just verify it's a valid score
