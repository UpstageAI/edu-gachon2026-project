"""
"[재난유형 / 단계 / 세부카테고리] 문장" 형식의 txt를 파싱해서
process_disaster_guidelines.py가 읽을 수 있는 JSON(raw API 형식과 동일)으로 변환.

입력 예시:
[폭염 / 평상시 / 일반] 여름철 한낮의 폭염은 열사병, 열경련 등의 온열질환을...

실행: python preprocessors/parse_manual_guidelines.py <입력txt경로> <출력json경로>
예:   python preprocessors/parse_manual_guidelines.py raw_data/manual_heatwave.txt raw_data/manual_guidelines_raw.json
"""
import json
import re
import sys

LINE_PATTERN = re.compile(r'^\[([^/]+)/([^/]+)/([^\]]+)\]\s*(.+)$')

# 재난유형 -> 대분류 매핑 (필요한 유형이 늘어나면 여기에 추가)
DISASTER_TYPE_TO_DOMAIN = {
    "폭염": "자연재난", "호우": "자연재난", "대설": "자연재난", "한파": "자연재난",
    "강풍": "자연재난", "산사태": "자연재난", "홍수": "자연재난", "태풍": "자연재난",
    "지진": "자연재난", "지진해일": "자연재난", "풍랑": "자연재난", "가뭄": "자연재난",
    "안개": "자연재난", "황사": "자연재난", "해일": "자연재난",
    "산불": "사회재난", "화재": "사회재난", "붕괴": "사회재난",
    "환경오염사고": "사회재난", "미세먼지": "사회재난",
    "여름철물놀이": "생활안전", "빙판길낙상사고": "생활안전", "응급처치": "생활안전",
}


def parse_file(input_path: str) -> list:
    with open(input_path, "r", encoding="utf-8") as f:
        lines = f.readlines()

    results = []
    skipped = []
    for line_no, line in enumerate(lines, 1):
        line = line.strip()
        if not line:
            continue
        m = LINE_PATTERN.match(line)
        if not m:
            skipped.append((line_no, line))
            continue

        disaster_type, stage, detail, content = m.groups()
        disaster_type = disaster_type.strip()
        stage = stage.strip()
        detail = detail.strip()
        content = content.strip()

        domain = DISASTER_TYPE_TO_DOMAIN.get(disaster_type)
        if domain is None:
            print(f"[WARN] line {line_no}: '{disaster_type}' 대분류 매핑 없음 -> "
                  f"DISASTER_TYPE_TO_DOMAIN에 추가 필요. 임시로 '자연재난'으로 처리.")
            domain = "자연재난"

        results.append({
            "actRmks": content,
            "safety_cate_nm1": domain,
            "safety_cate_nm2": disaster_type,
            "safety_cate_nm3": f"{stage} - {detail}",
            "safety_cate1": None,
            "safety_cate2": None,
            "safety_cate3": None,
            "safety_cate4": None,
            "contentsUrl": None,
        })

    print(f"파싱 완료: {len(results)}건 성공, {len(skipped)}건 스킵")
    if skipped:
        print("스킵된 줄 (패턴 안 맞음):")
        for line_no, line in skipped[:5]:
            print(f"  line {line_no}: {line[:80]}")

    return results


if __name__ == "__main__":
    if len(sys.argv) < 3:
        print("사용법: python parse_manual_guidelines.py <입력txt> <출력json>")
        sys.exit(1)

    input_path, output_path = sys.argv[1], sys.argv[2]
    parsed = parse_file(input_path)

    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(parsed, f, ensure_ascii=False, indent=2)

    print(f"저장 완료: {output_path}")