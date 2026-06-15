import pandas as pd
from typing import Optional

_prices: dict[str, int] = {}


def load_prices(filepath: str) -> dict[str, int]:
    global _prices
    df = pd.read_excel(filepath)
    _prices = _parse_df(df)
    return _prices


def load_prices_from_df(df: pd.DataFrame) -> dict[str, int]:
    global _prices
    _prices = _parse_df(df)
    return _prices


def _parse_df(df: pd.DataFrame) -> dict[str, int]:
    return {
        str(row["product"]).lower().strip(): int(row["price"])
        for _, row in df.iterrows()
    }


def get_price(item_name: str) -> Optional[int]:
    return _prices.get(item_name.lower().strip())