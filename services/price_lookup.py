import pandas as pd
from typing import Optional

_prices: dict[str, int] = {}

def load_prices(filepath: str) -> dict[str, int]:
    global _prices
    df = pd.read_excel(filepath)
    _prices = {
        str(row["product"]).lower().strip(): int(row["price"])
        for _, row in df.iterrows()
    }
    return _prices

def get_price(item_name: str) -> Optional[int]:
    return _prices.get(item_name.lower().strip())
