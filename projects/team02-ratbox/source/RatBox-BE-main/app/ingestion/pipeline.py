from dataclasses import dataclass
from pathlib import Path

import pandas as pd

from app.ingestion.cleaning import build_ingredient_tables, build_recipes, load_recipe_search_csv


@dataclass
class IngestionResult:
    recipes: pd.DataFrame
    ingredients_master: pd.DataFrame
    recipe_ingredients: pd.DataFrame
    allergen_master: pd.DataFrame
    ingredients_category: pd.DataFrame


def process_csv(csv_path: Path) -> IngestionResult:
    df = load_recipe_search_csv(csv_path)

    recipes_df = build_recipes(df)
    (
        recipe_ingredients_df,
        ingredients_master_df,
        allergen_master_df,
        ingredients_category_df,
    ) = build_ingredient_tables(df, recipes_df)

    return IngestionResult(
        recipes=recipes_df.reset_index(drop=True),
        ingredients_master=ingredients_master_df,
        recipe_ingredients=recipe_ingredients_df,
        allergen_master=allergen_master_df,
        ingredients_category=ingredients_category_df,
    )
