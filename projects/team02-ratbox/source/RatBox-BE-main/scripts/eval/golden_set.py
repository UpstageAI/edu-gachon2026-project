"""추천 품질 평가용 골든셋 (v1).

각 케이스는 실제 서비스 입력(재료 이름 조합)과, 왜 이 조합을 넣었는지에 대한 노트로
구성된다. "정답 레시피"를 사람이 미리 라벨링해두지 않은 이유는 라벨링 자체가 비용이
크고 주관적이기 때문 - 대신 run_baseline.py가 계산하는 결정론적 지표(핵심재료 매칭
여부, 후보 레시피 크기 편향, 재시도 발동 여부)로 1차 스크리닝을 하고, Langfuse
대시보드에 남는 트레이스를 사람이 보고 pass/fail을 라벨링하는 2단계로 간다.

케이스 구성 의도:
- bug_salt_potato_milk: 실제 리포트된 버그 재현 케이스 (감자/우유가 핵심이어야 하는데
  소금만 겹쳐서 무관한 레시피가 뜸)
- seasoning_only_*: 핵심재료가 아예 없는 입력 - 시스템이 "추천 불가/재료 더 필요"로
  판단해야 하는지, 아무 레시피나 베스트에포트로 내보내는지 확인
- *_strong_combo: 흔히 쓰이는 조합으로 정상 케이스의 베이스라인 확인
- rare_anchor_*: 희귀 재료 하나만으로도 명확히 관련된 레시피가 나와야 하는 케이스
"""

GOLDEN_CASES: list[dict] = [
    {
        "case_id": "bug_salt_potato_milk",
        "ingredient_names": ["소금", "감자", "우유"],
        "notes": "실제 버그 리포트 재현 케이스. 감자/우유 기반 요리(감자수프 등)가 나와야"
        " 하는데 소금만 겹치는 무관한 레시피(전복죽, 들기름두부지짐 등)가 뜸.",
    },
    {
        "case_id": "seasoning_only_salt_pepper",
        "ingredient_names": ["소금", "후추"],
        "notes": "핵심재료 없이 조미료만 입력한 극단 케이스. 아무 레시피나 베스트에포트로"
        " 내보내는 대신 재료 부족을 인지해야 하는지 확인.",
    },
    {
        "case_id": "seasoning_only_soy_sugar_garlic",
        "ingredient_names": ["간장", "설탕", "마늘"],
        "notes": "3개 다 흔한 조미료/부재료지만 마늘은 상대적으로 덜 흔함 - 양념장"
        " 베이스로 애매하게 통과되는지 확인하는 경계 케이스.",
    },
    {
        "case_id": "pork_kimchi_strong_combo",
        "ingredient_names": ["돼지고기", "김치"],
        "notes": "명확한 핵심재료 2개 조합 (김치찌개/두루치기 계열). 정상 케이스 베이스라인.",
    },
    {
        "case_id": "tofu_egg_scallion_strong_combo",
        "ingredient_names": ["두부", "계란", "파"],
        "notes": "흔한 밑반찬 재료 조합. 매칭은 쉽지만 조미료성 재료(파)가 섞여있어"
        " 핵심재료 판별 로직이 필요한 케이스.",
    },
    {
        "case_id": "shrimp_garlic_oliveoil_strong_combo",
        "ingredient_names": ["새우", "마늘", "올리브유"],
        "notes": "감바스류로 이어져야 하는 조합.",
    },
    {
        "case_id": "chicken_broccoli_strong_combo",
        "ingredient_names": ["닭가슴살", "브로콜리"],
        "notes": "다이어트식 조합, 핵심재료 2개 모두 희귀도가 높아 매칭 난이도는 낮음.",
    },
    {
        "case_id": "potato_onion_carrot_strong_combo",
        "ingredient_names": ["감자", "양파", "당근"],
        "notes": "카레/조림류 재료 조합.",
    },
    {
        "case_id": "beef_curry_set",
        "ingredient_names": ["소고기", "양파", "당근", "감자"],
        "notes": "재료 4개 조합 - min_match=2 기준 통과가 쉬워야 정상.",
    },
    {
        "case_id": "rare_anchor_abalone_rice",
        "ingredient_names": ["전복", "찹쌀"],
        "notes": "전복죽이 나오는 게 정답인 케이스 - bug_salt_potato_milk에서 전복죽이"
        " '우연히' 뜨는 것과 대조하기 위한 대조군.",
    },
    {
        "case_id": "rare_anchor_abalone_only",
        "ingredient_names": ["전복"],
        "notes": "희귀 핵심재료 단독 입력 - 명확히 관련된 레시피만 나와야 함.",
    },
    {
        "case_id": "cabbage_pork_strong_combo",
        "ingredient_names": ["양배추", "돼지고기"],
        "notes": "제육볶음 계열 조합.",
    },
    {
        "case_id": "spinach_bacon_strong_combo",
        "ingredient_names": ["시금치", "베이컨"],
        "notes": "샐러드/파스타 계열 조합.",
    },
    {
        "case_id": "single_generic_salt",
        "ingredient_names": ["소금"],
        "notes": "극단 엣지케이스: 재료 1개, 그마저도 최상위 범용 조미료. 시스템이 이걸"
        " 추천 불가로 처리하는지, 아니면 아무 레시피나 내보내는지 확인.",
    },
    {
        "case_id": "single_generic_egg",
        "ingredient_names": ["계란"],
        "notes": "재료 1개, 비교적 흔하지만 소금만큼 극단적이지는 않은 재료 - 임계값"
        " 캘리브레이션 참고용.",
    },
]
