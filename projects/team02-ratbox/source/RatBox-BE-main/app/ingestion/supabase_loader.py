import math

import pandas as pd
from supabase import Client, create_client

from app.core.config import settings


def get_supabase_client() -> Client:
    return create_client(settings.supabase_url, settings.supabase_key)


def _clean_value(value):
    # float64 컬럼은 None을 담지 못해 df.where(...)로 NaN을 지워도 다시 NaN으로 돌아온다.
    # to_dict 이후 값 단위로 NaN을 걸러내야 JSON 직렬화가 안전하다.
    if isinstance(value, float) and math.isnan(value):
        return None
    return value


def load_dataframe(
    client: Client,
    table_name: str,
    df: pd.DataFrame,
    batch_size: int = 100,
    on_conflict: str | None = None,
) -> None:
    records = [
        {key: _clean_value(value) for key, value in record.items()}
        for record in df.to_dict(orient="records")
    ]

    total = len(records)
    for i in range(0, total, batch_size):
        batch = records[i : i + batch_size]
        try:
            _write_batch(client, table_name, batch, on_conflict)
        except Exception:
            for record in batch:
                try:
                    _write_batch(client, table_name, [record], on_conflict)
                except Exception as error:
                    print(f"스킵 ({table_name}): {record} - {error}")
        print(f"{table_name}: {min(i + batch_size, total)}/{total} 처리 완료")


def _write_batch(
    client: Client, table_name: str, batch: list[dict], on_conflict: str | None
) -> None:
    query = client.table(table_name)
    if on_conflict:
        query.upsert(batch, on_conflict=on_conflict).execute()
    else:
        query.insert(batch).execute()
