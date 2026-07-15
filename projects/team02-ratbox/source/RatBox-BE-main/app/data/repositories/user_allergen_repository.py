from app.data.supabase_client import get_supabase


def create_user_allergens(user_id: str, allergen_ids: list[str]) -> list[dict]:
    if not allergen_ids:
        return []
    supabase = get_supabase()
    rows = [{"user_id": user_id, "allergen_id": allergen_id} for allergen_id in allergen_ids]
    response = supabase.table("user_allergens").insert(rows).execute()
    return response.data


def find_user_allergens(user_id: str) -> list[dict]:
    supabase = get_supabase()
    response = (
        supabase.table("user_allergens")
        .select("allergen_master(id, allergen_name, category)")
        .eq("user_id", user_id)
        .execute()
    )
    return [row["allergen_master"] for row in response.data]


def delete_user_allergens(user_id: str) -> None:
    supabase = get_supabase()
    supabase.table("user_allergens").delete().eq("user_id", user_id).execute()
