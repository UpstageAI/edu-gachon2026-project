import pandas as pd


def require_columns(df: pd.DataFrame, required: list[str], source_name: str) -> None:
    missing = [col for col in required if col not in df.columns]
    if missing:
        raise ValueError(f"{source_name}에 필수 컬럼이 없습니다: {missing}")
