import os
from dotenv import load_dotenv


load_dotenv()


class Settings:
    UPSTAGE_API_KEY: str | None = os.getenv("UPSTAGE_API_KEY")

    # data.go.kr 계정당 인증키가 1개라 TourAPI(15101578)와 연관 관광지 API(15128560)가 같은 키를 씀
    TOUR_API_KEY: str | None = os.getenv("TOUR_API_KEY")
    KAKAO_MOBILITY_API_KEY: str | None = os.getenv("KAKAO_MOBILITY_API_KEY")
    GOOGLE_PLACES_API_KEY: str | None = os.getenv("GOOGLE_PLACES_API_KEY")

    SUPABASE_URL: str | None = os.getenv("SUPABASE_URL")
    SUPABASE_KEY: str | None = os.getenv("SUPABASE_KEY")
    # 대화 기록(chat_sessions/chat_messages)은 RLS가 걸려 있어 anon 키로는 접근이
    # 막힌다. 백엔드가 소유권을 직접 검증하므로(chat_store._session_belongs_to_user)
    # 이 클라이언트만 service_role 키로 RLS를 우회한다 — 절대 브라우저로 노출하지 말 것.
    SUPABASE_SERVICE_KEY: str | None = os.getenv("SUPABASE_SERVICE_KEY")
    # LangGraph 체크포인트 저장용 Postgres 직접 연결 문자열(REST API용 SUPABASE_URL과는
    # 별개 — psycopg가 이 문자열로 Postgres 프로토콜에 직접 접속함). 비어있으면
    # app.graph.checkpointer.get_checkpointer()가 None을 반환해 체크포인트 없이 그냥 실행됨.
    SUPABASE_DB_URL: str | None = os.getenv("SUPABASE_DB_URL")

    LANGFUSE_PUBLIC_KEY: str | None = os.getenv("LANGFUSE_PUBLIC_KEY")
    LANGFUSE_SECRET_KEY: str | None = os.getenv("LANGFUSE_SECRET_KEY")
    LANGFUSE_HOST: str | None = os.getenv(
        "LANGFUSE_HOST",
        "https://cloud.langfuse.com",
    )


settings = Settings()