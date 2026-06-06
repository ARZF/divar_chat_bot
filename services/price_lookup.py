import pandas as pd


class PriceLookupService:
    def __init__(self):
        self.df = pd.read_excel("data/prices.xlsx")

    def get_price(self, product_name: str):

        result = self.df[
            self.df["product"]
            .str.lower()
            .str.strip()
            ==
            product_name.lower().strip()
        ]

        if result.empty:
            return None

        return result.iloc[0]["price"]