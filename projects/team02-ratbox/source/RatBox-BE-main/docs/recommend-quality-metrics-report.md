# 추천 품질 지표 — 수치 개선 결과 보고서

> 2026-07-15. `feat/#41-추천-품질-평가-골든셋-langfuse-연동` 브랜치. 무엇을 어떻게 고쳤는지는
> `docs/recommend-quality-improvement-report.md`에 있고, 이 문서는 **그 개선이 지표상으로 정확히
> 얼마나 나아졌는지**에만 집중한다.

---

## 1. 측정 방법론

같은 골든셋(재료 조합 15케이스, `scripts/eval/golden_set.py`)을 코드 변경 전/후 **3개 시점**에서
동일하게 실행하고, 매번 Langfuse Dataset Run으로 남겨 나란히 비교했다.

| 시점 | 코드 상태 | Langfuse Run |
|---|---|---|
| **베이스라인** | 원본 알고리즘 (raw match count, 가중치/하드필터 없음) | [run: f9dc5864](https://jp.cloud.langfuse.com/project/cmrgi7x5o00frad0elhn9n7h8/datasets/cmrllbqfi0001ad0c7re4yu0q/runs/f9dc5864-1cff-4396-a124-144af7a5cc7d) |
| **A-1 이후** | 재료 가중치 + 핵심재료 하드필터 + PostgREST 트렁케이션 버그 수정 (커밋 `d6c8961`) | [run: 757cdab9](https://jp.cloud.langfuse.com/project/cmrgi7x5o00frad0elhn9n7h8/datasets/cmrllbqfi0001ad0c7re4yu0q/runs/757cdab9-3c99-43f4-b8db-e62bcefa7e85) |
| **최종(A-2+A-3 이후)** | verify_relevance 판단근거 노출 + 재시도 단계별 완화 (커밋 `dd84369`) | [run: 53c9df45](https://jp.cloud.langfuse.com/project/cmrgi7x5o00frad0elhn9n7h8/datasets/cmrllbqfi0001ad0c7re4yu0q/runs/53c9df45-e7aa-4139-bd52-a440af74ed2f) |

지표는 **LLM 자기평가가 아니라 결정론적 Python 코드로 계산**했다 (`scripts/eval/run_baseline.py`의
evaluator 함수들). "추천이 좋아 보인다"는 LLM의 주관적 판단에 의존하지 않고, DB에서 직접 계산한
재료 문서빈도와 실제 매칭 재료 목록을 대조해서 채점한다 — 그래야 알고리즘을 바꿀 때마다 같은
기준으로 재현 가능하게 비교할 수 있다.

---

## 2. 지표 정의

| 지표 | 계산식 | 무엇을 재는가 |
|---|---|---|
| `core_ingredient_hit_rate` | top-3 후보 중, 매칭된 재료에 코퍼스 문서빈도(df) 비율 ≤ 0.15인(=흔하지 않은) 재료가 하나라도 있는 비율 | 조미료 하나만 겹쳐서 추천된 게 아닌지 |
| `zero_candidate_rate` | 재시도까지 다 거쳐도 후보가 0건인 케이스 비율 | 필터가 너무 엄격해 커버리지를 해치지 않는지 |
| `retry_rate` | broaden_search가 실제로 발동한 케이스 비율 | 1차 검색만으로 충분한지 |
| `avg_recipe_ingredient_count_top` | top-3 후보의 평균 총 재료 수 | "재료 적은 레시피" 쏠림 여부 |

---

## 3. 종합 지표 변화

| 지표 | 베이스라인 | A-1 이후 | 최종 | 변화폭 |
|---|---|---|---|---|
| `core_ingredient_hit_rate` (평균) | **0.60** | 1.00 | **1.00** | **+0.40 (+67%)** |
| `retry_rate` | **0.667** | 0.467 | **0.400** | **-0.267 (-40%)** |
| `zero_candidate_rate` | 0.000 | 0.067 | 0.067 | +0.067 (§5-3 참고, 의도된 변화) |

### 가장 중요한 숫자: "확신을 갖고 완전히 틀린 추천"을 한 케이스 수

`core_ingredient_hit_rate == 0.0`이면서 `zero_candidates == 0`인 케이스 — 즉 **후보를 냈는데 그
후보 전부가 조미료 하나만 겹친, 사용자에게 그대로 보여줬을 "확신에 찬 오답"** 케이스만 따로 셌다.

| 시점 | 확신에 찬 오답 케이스 수 | 비율 |
|---|---|---|
| 베이스라인 | **6 / 15** | 40% |
| A-1 이후 | **0 / 15** | 0% |
| 최종 | **0 / 15** | 0% |

베이스라인에서 확신에 찬 오답이었던 6케이스: `bug_salt_potato_milk`, `seasoning_only_salt_pepper`,
`tofu_egg_scallion_strong_combo`, `potato_onion_carrot_strong_combo`, `beef_curry_set`,
`single_generic_salt`. 이 중 5개는 최종적으로 **핵심재료가 실제로 매칭된 정상 추천**으로 바뀌었고,
나머지 1개(`single_generic_salt`, 재료가 소금 하나뿐인 케이스)는 최종적으로 **"추천 불가"로
정직하게 응답**하도록 바뀌었다(§5-3) — 즉 오답률 40% → 0%, 남은 것은 "틀린 확신"이 아니라 "정직한
모름"이다.

---

## 4. 케이스별 상세 (15케이스 전체, 3시점 비교)

`core_hit / retry / zero / avg_size` 순. `-`는 후보가 없어 계산 불가(N/A).

| 케이스 | 베이스라인 | A-1 이후 | 최종 |
|---|---|---|---|
| bug_salt_potato_milk | 0.0 / 1 / 0 / 3.7 | 1.0 / 0 / 0 / 6.0 | 1.0 / 0 / 0 / 6.0 |
| seasoning_only_salt_pepper | 0.0 / 1 / 0 / 3.7 | 1.0 / 1 / 0 / 5.0 | 1.0 / 1 / 0 / 5.0 |
| seasoning_only_soy_sugar_garlic | 1.0 / 1 / 0 / 5.7 | 1.0 / 1 / 0 / 8.0 | **1.0 / 0 / 0 / 9.3** |
| pork_kimchi_strong_combo | 1.0 / 0 / 0 / 4.3 | 1.0 / 0 / 0 / 4.3 | 1.0 / 0 / 0 / 4.3 |
| tofu_egg_scallion_strong_combo | 0.0 / 1 / 0 / 4.7 | 1.0 / 0 / 0 / 4.7 | 1.0 / 0 / 0 / 4.7 |
| shrimp_garlic_oliveoil_strong_combo | 1.0 / 0 / 0 / 7.0 | 1.0 / 0 / 0 / 6.7 | 1.0 / 1 / 0 / 4.7 |
| chicken_broccoli_strong_combo | 1.0 / 1 / 0 / 4.3 | 1.0 / 1 / 0 / 2.3 | 1.0 / 1 / 0 / 2.3 |
| potato_onion_carrot_strong_combo | 0.0 / 1 / 0 / 5.3 | 1.0 / 0 / 0 / 5.3 | 1.0 / 0 / 0 / 5.3 |
| beef_curry_set | 0.0 / 1 / 0 / 5.3 | 1.0 / 0 / 0 / 6.7 | 1.0 / 0 / 0 / 6.7 |
| rare_anchor_abalone_rice | 1.0 / 0 / 0 / 5.0 | 1.0 / 0 / 0 / 5.0 | 1.0 / 0 / 0 / 5.0 |
| rare_anchor_abalone_only | 1.0 / 1 / 0 / 2.7 | 1.0 / 1 / 0 / 2.7 | 1.0 / 1 / 0 / 3.3 |
| cabbage_pork_strong_combo | 1.0 / 0 / 0 / 8.3 | 1.0 / 1 / 0 / 5.7 | 1.0 / 0 / 0 / 8.3 |
| spinach_bacon_strong_combo | 1.0 / 0 / 0 / 7.3 | 1.0 / 0 / 0 / 7.3 | 1.0 / 0 / 0 / 7.3 |
| single_generic_salt | 0.0 / 1 / 0 / 3.7 | - / 1 / **1** / - | - / 1 / **1** / - |
| single_generic_egg | 1.0 / 1 / 0 / 3.0 | 1.0 / 1 / 0 / 3.0 | 1.0 / 1 / 0 / 3.0 |

**굵게 표시한 3곳**을 짚어보면:

- `bug_salt_potato_milk`(원 버그 리포트 케이스): `core_hit 0.0→1.0`, `retry 1→0` — 재시도 없이 바로
  핵심재료 기반 추천이 나온다.
- `seasoning_only_soy_sugar_garlic`: A-1까지는 여전히 재시도가 필요했으나, A-2(판단근거 노출)
  이후에는 재시도 없이 통과 — verify_relevance 프롬프트 수정의 효과가 이 케이스에서 가장 뚜렷하게
  보인다.
- `single_generic_salt`: `core_hit 0.0`(확신에 찬 오답) → `zero_candidates 1`(정직하게 "모름"으로
  전환). 지표상으로는 "후보 없음"이 늘어난 것처럼 보이지만, 실제로는 **오답을 없앤 결과**다(§5-3).

---

## 5. 해석과 한계

### 5-1. `retry_rate` 감소가 의미하는 것

재시도 1회는 최소한 검색 1회 + `verify_relevance` LLM 호출 1회를 추가로 발생시킨다. 베이스라인
대비 재시도가 필요했던 케이스가 15개 중 10개(66.7%)에서 6개(40%)로 줄었다 — 요청당 평균 LLM 호출
및 왕복 횟수가 그만큼 줄어든다는 뜻으로, 지연시간·비용 관점에서도 개선이다.

### 5-2. `cabbage_pork_strong_combo`와 `shrimp_garlic_oliveoil_strong_combo`가 보여주는 것

이 두 케이스는 3시점 사이에 단조롭게 좋아지지 않고 중간에 흔들렸다(`cabbage_pork`는 A-1 단계에서
일시적으로 retry가 발생했다가 최종 단계에서 다시 사라짐, `shrimp_garlic_oliveoil`은 반대로 최종
단계에서 새로 retry가 발생함). `verify_relevance`가 LLM 판단이라 **매 실행마다 약간의 변동성이
있다** — core_ingredient_hit_rate처럼 결정론적 코드로 계산하는 지표는 안정적이지만, retry_rate·
low_confidence_fallback처럼 LLM 판단이 개입하는 지표는 1회 실행 결과만으로 "이 케이스는
확실히 나아졌다/나빠졌다"고 단정하기보다 여러 번 반복 실행한 평균으로 봐야 한다. 이번 보고서의
숫자는 각 시점 1회 실행 기준이라는 점을 명시해둔다.

### 5-3. `zero_candidate_rate`가 늘어난 게 왜 개선인가

`single_generic_salt`(재료가 소금 하나뿐인 케이스)는 베이스라인에서 `core_hit=0.0`으로, 핵심재료가
전혀 없는데도 레시피를 억지로 추천하고 있었다(확신에 찬 오답). 핵심재료 하드필터 적용 후에는 이
케이스가 정직하게 "추천할 후보 없음"으로 응답한다. 지표 표에서는 `zero_candidate_rate`가 늘어난
것으로 보이지만, 실제로는 **"틀린 답을 자신 있게 주는 것"에서 "모른다고 정직하게 말하는 것"으로
전환된 것**이라 나쁜 신호가 아니다. 다만 이 케이스가 사용자에게 실제로 어떻게 보여야 하는지(예:
"재료를 더 알려주세요" 안내)는 `ask_clarification` 노드의 몫이고, 이번 브랜치에서 그 응답 문구
자체를 바꾸지는 않았다.

### 5-4. 이 지표들의 한계

- **표본 크기(n=15)가 작다.** 비율 변화(예: 0.667→0.4)는 golden set을 30~50개로 늘리면 신뢰구간이
  더 좁아질 것이다.
- **`core_ingredient_hit_rate`는 "핵심재료가 매칭됐는가"의 대리 지표이지, "추천이 실제로 맛있고
  적절한가"를 재는 지표가 아니다.** 진짜 Precision@3(사람이 매긴 정답과 대조)은 아직 없다 — 이번에
  만든 Langfuse Dataset Run에 사람이 pass/fail 라벨을 채우는 게 다음 단계다.
- **`GENERIC_DF_RATIO_THRESHOLD=0.15`가 지표 계산 자체에 들어간다.** 이 값이 바뀌면
  `core_ingredient_hit_rate` 수치도 같이 바뀐다 — 지금 값은 소금(28.1%)과 감자(5.1%) 사이에서 잡은
  잠정값이라는 점을 다시 한번 명시한다.

---

## 6. 요약

| | 베이스라인 | 최종 |
|---|---|---|
| 확신에 찬 오답 케이스 | 6/15 (40%) | **0/15 (0%)** |
| core_ingredient_hit_rate | 0.60 | **1.00** |
| retry_rate (LLM 재호출 빈도) | 0.667 | **0.400** |
| 회귀 테스트 | (해당 없음) | **97개 통과** |

같은 골든셋·같은 지표로 3번 측정해 비교했고, 원 버그 리포트 케이스(`bug_salt_potato_milk`)를
포함해 확신에 찬 오답 6건이 전부 해소됐다.
