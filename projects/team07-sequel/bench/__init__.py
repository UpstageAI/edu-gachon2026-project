try:  # .env 로드는 있으면 좋고, 없어도 오프라인 스크립트는 stdlib 만으로 동작
    from dotenv import load_dotenv

    load_dotenv()  # bench 실행 시 프로젝트 .env 의 UPSTAGE_API_KEY 로드
except ModuleNotFoundError:
    pass
