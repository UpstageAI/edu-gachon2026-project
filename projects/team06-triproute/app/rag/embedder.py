from typing import List

from app.services.upstage_client import embed_passages, embed_query


def embed_place_overviews(overviews: List[str]) -> List[List[float]]:
    """
    관광지 개요 텍스트 여러 개를 저장용(passage) 임베딩으로 변환합니다.
    """

    return embed_passages(overviews)


def embed_user_taste(taste_text: str) -> List[float]:
    """
    사용자 취향 문장을 검색용(query) 임베딩으로 변환합니다.
    """

    return embed_query(taste_text)
