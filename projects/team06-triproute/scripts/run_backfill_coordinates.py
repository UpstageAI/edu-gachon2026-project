from app.rag.vector_store import backfill_coordinates

if __name__ == "__main__":
    print("기존 places 데이터의 누락된 좌표(latitude, longitude) 백필을 시작합니다...")
    result = backfill_coordinates()
    print(f"작업 완료: {result}")
