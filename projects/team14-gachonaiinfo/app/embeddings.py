"""Upstage 임베딩 클라이언트 (OpenAI 호환)."""

from functools import lru_cache

from openai import OpenAI

from app import config


@lru_cache(maxsize=1)
def _get_client() -> OpenAI:
    """OpenAI 호환 클라이언트를 지연 생성한다(최초 사용 시 1회).

    모듈 로드 시점에 생성하면 API 키가 없는 환경(예: 그래프 모듈을 import하는
    단위 테스트 CI)에서 import만으로 OpenAIError가 난다. 실제 임베딩 호출
    시점까지 생성을 미뤄 그런 환경에서도 import 자체는 성공하게 한다.
    """
    return OpenAI(api_key=config.UPSTAGE_API_KEY, base_url=config.UPSTAGE_BASE_URL)


def embed_passages(texts: list[str]) -> list[list[float]]:
    """문서(passage) 임베딩. 적재용."""
    if not texts:
        return []
    resp = _get_client().embeddings.create(model=config.EMBED_MODEL_PASSAGE, input=texts)
    return [d.embedding for d in resp.data]


def embed_query(text: str) -> list[float]:
    """질의(query) 임베딩. 검색용."""
    resp = _get_client().embeddings.create(model=config.EMBED_MODEL_QUERY, input=[text])
    return resp.data[0].embedding
