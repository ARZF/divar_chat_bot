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

# Test client_id used throughout — all lookups scoped to this value
CID = 1

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
    """Populate per-client module-level state with CATALOG, clean up after."""
    prices = {k: v[1] for k, v in CATALOG.items()}
    canonical = {k: v[0] for k, v in CATALOG.items()}
    pl._cache[CID] = pl.ClientPriceCache(
        prices=prices,
        canonical_names=canonical,
        product_names=list(prices.keys()),
    )
    yield
    pl._cache.pop(CID, None)


@pytest.fixture
def empty_catalog():
    """Ensure per-client module-level state is empty."""
    pl._cache.pop(CID, None)
    yield
    pl._cache.pop(CID, None)


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
        assert normalize_text("گوشي") == "گوشی"

    def test_arabic_kaf_to_persian_kaf(self):
        assert normalize_text("كتاب") == "کتاب"

    def test_alef_with_madda_to_plain_alef(self):
        assert normalize_text("آیفون") == "iphone"

    def test_zwnj_to_space(self):
        assert normalize_text("می‌خوام") == "می خوام"

    def test_rtl_mark_removed(self):
        assert normalize_text("iphone\u200f") == "iphone"

    def test_persian_digits_to_ascii(self):
        assert normalize_text("گوشی ۱۳") == "گوشی 13"

    def test_arabic_indic_digits_to_ascii(self):
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

        assert "iphone 14" not in prices
        assert prices["iphone 13"] == 35000000
        assert prices["iphone 15"] == 42000000

    def test_non_numeric_price_skipped(self):
        df = pd.DataFrame(
            {
                "product": ["iPhone 13", "Header Row"],
                "price": [35000000, "قیمت(تومان)"],
            }
        )
        prices, _ = _parse_df(df)

        assert "iphone 13" in prices
        assert len(prices) == 1

    def test_float_price_trailing_zero_removed(self):
        df = pd.DataFrame(
            {"product": ["iPhone 13"], "price": [35000000.0]}
        )
        prices, _ = _parse_df(df)

        assert prices["iphone 13"] == 35000000
        assert isinstance(prices["iphone 13"], int)


# ---------------------------------------------------------------------------
# find_best_match  (now requires client_id as first arg)
# ---------------------------------------------------------------------------


class TestFindBestMatch:
    def test_exact_match_after_normalization(self, catalog):
        result = find_best_match(CID, "iPhone 13")
        assert result is not None
        name, score = result
        assert name == "iphone 13"
        assert score == 100.0

    def test_fuzzy_match_above_threshold(self, catalog):
        result = find_best_match(CID, "iphoen 13")
        assert result is not None
        name, score = result
        assert name == "iphone 13"
        assert score >= 70.0

    def test_no_match_below_threshold(self, catalog):
        result = find_best_match(CID, "zzzzzzzzz")
        assert result is None

    def test_empty_query_returns_none(self, catalog):
        assert find_best_match(CID, "") is None

    def test_empty_catalog_returns_none(self, empty_catalog):
        assert find_best_match(CID, "iphone 13") is None

    def test_custom_threshold(self, catalog):
        result_low = find_best_match(CID, "iphoen", threshold=40.0)
        result_high = find_best_match(CID, "iphoen", threshold=95.0)
        assert result_low is not None
        if result_high is not None:
            assert result_high[1] >= 95.0


# ---------------------------------------------------------------------------
# find_top_matches
# ---------------------------------------------------------------------------


class TestFindTopMatches:
    def test_returns_up_to_limit(self, catalog):
        results = find_top_matches(CID, "iphone", limit=2)
        assert len(results) <= 2
        assert len(results) > 0
        scores = [s for _, s in results]
        assert scores == sorted(scores, reverse=True)

    def test_empty_query_returns_empty_list(self, catalog):
        assert find_top_matches(CID, "") == []

    def test_empty_catalog_returns_empty_list(self, empty_catalog):
        assert find_top_matches(CID, "iphone") == []

    def test_no_threshold_filtering(self, catalog):
        results = find_top_matches(CID, "zzzzzzzzz", limit=3)
        assert isinstance(results, list)


# ---------------------------------------------------------------------------
# get_all_matching_prices (Tier 1: substring)
# ---------------------------------------------------------------------------


class TestGetAllMatchingPrices:
    def test_substring_match_returns_results(self, catalog):
        results = get_all_matching_prices(CID, "iphone")
        assert len(results) == 2
        names = [name for name, _ in results]
        assert "iPhone 13" in names
        assert "iPhone 14" in names

    def test_substring_match_single_result(self, catalog):
        results = get_all_matching_prices(CID, "macbook")
        assert len(results) == 1
        assert results[0] == ("MacBook Pro", 55000000)

    def test_no_substring_match_returns_empty(self, catalog):
        assert get_all_matching_prices(CID, "zzzzzz") == []

    def test_empty_query_returns_empty(self, catalog):
        assert get_all_matching_prices(CID, "") == []

    def test_empty_catalog_returns_empty(self, empty_catalog):
        assert get_all_matching_prices(CID, "iphone") == []

    def test_persian_substring_match(self, catalog):
        results = get_all_matching_prices(CID, "گوشی")
        assert len(results) == 1
        assert results[0] == ("گوشی", 15000000)


# ---------------------------------------------------------------------------
# get_price (Tier 2: fuzzy fallback)
# ---------------------------------------------------------------------------


class TestGetPrice:
    def test_exact_match_returns_canonical_name_and_price(self, catalog):
        result = get_price(CID, "iPhone 13")
        assert result is not None
        canonical, price = result
        assert canonical == "iPhone 13"
        assert price == 35000000

    def test_fuzzy_match_typo(self, catalog):
        result = get_price(CID, "samsng galaxy s22")
        assert result is not None
        canonical, price = result
        assert canonical == "Samsung Galaxy S22"
        assert price == 28000000

    def test_no_match_returns_none(self, catalog):
        assert get_price(CID, "zzzzzzzzz") is None

    def test_empty_query_returns_none(self, catalog):
        assert get_price(CID, "") is None

    def test_empty_catalog_returns_none(self, empty_catalog):
        assert get_price(CID, "iphone 13") is None


# ---------------------------------------------------------------------------
# 3-tier lookup (substring → fuzzy → suggestions)
# ---------------------------------------------------------------------------


class TestThreeTierLookup:
    def test_tier1_substring_match(self, catalog):
        results = get_all_matching_prices(CID, "iphone")
        assert len(results) >= 1

    def test_tier2_fuzzy_match_when_substring_fails(self, catalog):
        assert get_all_matching_prices(CID, "samsng galaxy s22") == []

        result = get_price(CID, "samsng galaxy s22")
        assert result is not None
        assert result[0] == "Samsung Galaxy S22"

    def test_tier3_suggestions_when_fuzzy_below_threshold(self, catalog):
        garbled = "galx"

        assert get_all_matching_prices(CID, garbled) == []

        tier2_result = get_price(CID, garbled)

        if tier2_result is None:
            suggestions = find_top_matches(CID, garbled, limit=3)
            assert isinstance(suggestions, list)
            if suggestions:
                _, score = suggestions[0]
                assert score >= 0.0
