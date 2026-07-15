from app.data.repositories.allergen_repository import find_all_allergens
from app.domain.models import Allergen


def list_allergens() -> list[Allergen]:
    rows = find_all_allergens()
    return [
        Allergen(id=row["id"], allergen_name=row["allergen_name"], category=row["category"])
        for row in rows
    ]
