from pydantic import BaseModel, Field


class Place(BaseModel):
    """
    관광지 1개를 표현하는 공통 데이터 모델입니다.
    TourAPI, RAG 검색 결과, 연관 관광지 API 결과를
    일정 생성 로직에서 동일한 형식으로 다루기 위해 사용합니다.
    """

    content_id: str | None = Field(default=None, description="TourAPI 콘텐츠 ID")
    name: str = Field(..., description="관광지명")
    category: str | None = Field(default=None, description="관광지 카테고리")
    address: str | None = Field(default=None, description="관광지 주소")

    latitude: float | None = Field(default=None, description="위도")
    longitude: float | None = Field(default=None, description="경도")

    overview: str | None = Field(default=None, description="관광지 개요 설명")
    image_url: str | None = Field(default=None, description="대표 이미지 URL")

    operating_time: str | None = Field(default=None, description="운영시간")
    closed_days: str | None = Field(default=None, description="휴무일")
    use_fee: str | None = Field(default=None, description="이용요금 원문 텍스트")

    source: str | None = Field(default="TourAPI", description="데이터 출처")