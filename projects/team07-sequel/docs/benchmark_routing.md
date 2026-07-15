# Sequel — Solar 모델 라우팅 벤치마크 (조건별 ablation)

난이도(하/중/상/최상)별로 solar-mini / pro2 / pro3 의 Text-to-SQL 성능을 비교해,
어느 난이도를 어느 모델로 라우팅할지 근거를 만든다.

## 실험 설정

- **데이터**: AI Hub NL2SQL Validation, 난이도별 25문항 × 4 = 100문항 (seed 7)
- **난이도**: easy→하, medium→중, hard→상, extra hard→최상
- **지표**: EX(실행결과 일치, 핵심) · 문항당/정답당 비용 · 토큰 · 지연
- **조건 (2×2)**:
  - `zero-shot` — 스키마 DDL만
  - `few-shot` — DDL + 같은 DB 유사질문 예시 3개
  - `schema-linker` — DDL + 컬럼별 샘플 값(value_retriever), few-shot 없음
  - `schema+few` — DDL + 샘플 값 + few-shot
- **모델 단가** (USD / 1M tokens, upstage.ai/pricing/api):

| 모델 | 입력 | 출력 |
| --- | --- | --- |
| solar-mini | $0.15 | $0.15 |
| solar-pro2 | $0.15 | $0.60 |
| solar-pro3 | $0.15 | $0.60 |

---

## 1. 요약 — 조건별 전체 EX

| 조건 | 전체 EX | 하 | 중 | 상 | 최상 |
| --- | --- | --- | --- | --- | --- |
| zero-shot | **31%** (92/300) | 48% | 21% | 35% | 19% |
| few-shot | **66%** (199/300) (+36%p) | 84% | 59% | 59% | 64% |
| schema-linker | **45%** (135/300) (+14%p) | 53% | 48% | 56% | 23% |
| schema+few | **73%** (219/300) (+42%p) | 77% | 76% | 72% | 67% |

_난이도 칸은 3모델 평균 EX._

---

## 2. 조건별 EX (모델별)

### zero-shot
실패유형: correct 92 · wrong_result 190 · exec_error 18 · api_error 0

| 난이도\모델 | solar-mini | solar-pro2 | solar-pro3 |
| --- | --- | --- | --- |
| 하 | 60% (15/25) | 40% (10/25) | 44% (11/25) |
| 중 | 12% (3/25) | 32% (8/25) | 20% (5/25) |
| 상 | 28% (7/25) | 40% (10/25) | 36% (9/25) |
| 최상 | 16% (4/25) | 24% (6/25) | 16% (4/25) |

### few-shot
실패유형: correct 199 · wrong_result 100 · exec_error 1 · api_error 0

| 난이도\모델 | solar-mini | solar-pro2 | solar-pro3 |
| --- | --- | --- | --- |
| 하 | 88% (22/25) | 88% (22/25) | 76% (19/25) |
| 중 | 64% (16/25) | 56% (14/25) | 56% (14/25) |
| 상 | 64% (16/25) | 60% (15/25) | 52% (13/25) |
| 최상 | 56% (14/25) | 72% (18/25) | 64% (16/25) |

### schema-linker
실패유형: correct 135 · wrong_result 151 · exec_error 14 · api_error 0

| 난이도\모델 | solar-mini | solar-pro2 | solar-pro3 |
| --- | --- | --- | --- |
| 하 | 60% (15/25) | 56% (14/25) | 44% (11/25) |
| 중 | 52% (13/25) | 52% (13/25) | 40% (10/25) |
| 상 | 48% (12/25) | 60% (15/25) | 60% (15/25) |
| 최상 | 20% (5/25) | 32% (8/25) | 16% (4/25) |

### schema+few
실패유형: correct 219 · wrong_result 79 · exec_error 2 · api_error 0

| 난이도\모델 | solar-mini | solar-pro2 | solar-pro3 |
| --- | --- | --- | --- |
| 하 | 80% (20/25) | 76% (19/25) | 76% (19/25) |
| 중 | 72% (18/25) | 76% (19/25) | 80% (20/25) |
| 상 | 72% (18/25) | 76% (19/25) | 68% (17/25) |
| 최상 | 56% (14/25) | 80% (20/25) | 64% (16/25) |

---

## 3. 라우팅 추천 (최고 조건: **schema+few**)

| 난이도 | 추천 모델 | EX | 정답당 비용 | 근거 |
| --- | --- | --- | --- | --- |
| 하 | solar-pro3 | 76% | $0.00025 | 목표 충족 최저가 |
| 중 | solar-pro3 | 80% | $0.00028 | 목표 충족 최저가 |
| 상 | solar-pro2 | 76% | $0.00024 | 목표 충족 최저가 |
| 최상 | solar-pro2 | 80% | $0.00030 | 목표 충족 최저가 |

**라우팅 규칙: `하→solar-pro3, 중→solar-pro3, 상→solar-pro2, 최상→solar-pro2`**

- solar-pro3 가 일부 난이도에서 pro2 를 앞섬 → 후보 유지 검토.

### 최고 조건 — 문항당/정답당 비용

| 난이도\모델 | solar-mini | solar-pro2 | solar-pro3 |
| --- | --- | --- | --- |
| 하 | $0.00021 / $0.00026 | $0.00021 / $0.00027 | $0.00019 / $0.00025 |
| 중 | $0.00025 / $0.00035 | $0.00023 / $0.00030 | $0.00022 / $0.00028 |
| 상 | $0.00019 / $0.00026 | $0.00018 / $0.00024 | $0.00018 / $0.00026 |
| 최상 | $0.00024 / $0.00043 | $0.00024 / $0.00030 | $0.00023 / $0.00036 |

---

## 4. schema+few 가 고친 사례 (zero-shot 틀림 → 개선조건 맞음)

**[solar-mini] 등록 번호가 2021-1021인 한옥의 공사 완료 전 지원 보조금을 1차 지급하는 일자를 보여줘**

- gold: `SELECT PAYDATE2 FROM HANOK_PAY_INFO WHERE HANOKNUM = '2021-1021'`
- zero-shot: `SELECT "PAYDATE1" FROM "HANOK_PAY_INFO" WHERE "HANOKNUM" = '2021-1021'` ✗
- 개선조건: `SELECT PAYDATE2 FROM HANOK_PAY_INFO WHERE HANOKNUM = '2021-1021'` ○

**[solar-mini] 처분 내용이 영업정지인 업소 이름을 알려줘**

- gold: `SELECT UPSO_NM FROM SEODAEMUN_ADMIN_MESURE_PUBLIC WHERE DISPO_CTN_DT = '영업정지'`
- zero-shot: `SELECT SNT_COB_NM 
FROM SEODAEMUN_ADMIN_MESURE_PUBLIC 
WHERE DISPO_CTN_DT = '영업정지'` ✗
- 개선조건: `SELECT UPSO_NM FROM SEODAEMUN_ADMIN_MESURE_PUBLIC WHERE DISPO_CTN_DT = '영업정지'` ○

**[solar-mini] 대출 횟수가 10번을 넘는 인기 도서명은 뭐야**

- gold: `SELECT SIGNATURES_POPULARITYG FROM GG_PC_LIBRARY_BOOK_RENTAL_STS WHERE NUM_LOANSH > 10`
- zero-shot: `SELECT FIELDI FROM GG_PC_LIBRARY_BOOK_RENTAL_STS WHERE NUM_LOANSH > 10` ✗
- 개선조건: `SELECT SIGNATURES_POPULARITYG FROM GG_PC_LIBRARY_BOOK_RENTAL_STS WHERE NUM_LOANSH > 10` ○

---

## 유의사항

- EX 채점: gold/pred 를 같은 sqlite 에 실행해 결과셋 비교(순서 무시, gold 에 ORDER BY 시 순서 반영).
- schema-linker = 컬럼별 distinct 샘플 값 3개 주입(value_retriever 대용).
- few-shot 예시는 val 풀 in-domain(약간 낙관적). held-out train 은 db_id disjoint 라 불가.
- 표본 난이도별 25문항 — 신뢰도 확보하려면 확대 필요.
- 모델 문자열(solar-pro3)·단가는 계정/시점 기준으로 재확인 권장.
- 원자료(eval_set/dbs/results)는 AI Hub 라이선스·용량상 미커밋. 본 리포트는 집계값.