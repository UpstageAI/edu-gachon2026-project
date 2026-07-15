# 파이프라인 정확도 평가 & Langfuse 연동

MathMate의 LLM 파이프라인(의도분류 → 오답진단 → 힌트생성)이 얼마나 정확한지 골든셋으로
측정하고, 그 결과를 Langfuse에 점수(score)로 남기는 방법을 정리한 문서입니다.

관련 코드: [`evals/eval_pipeline_accuracy.py`](../evals/eval_pipeline_accuracy.py)
실행: `python -m evals.eval_pipeline_accuracy`

---

## 1. Langfuse를 지금 어떻게 쓰고 있는가

Langfuse SDK를 앱 코드 안에서 직접 호출하는 게 아니라, **LiteLLM의 내장 콜백**을 켜는
방식으로 붙어있습니다 (`app/core/llm_client.py`).

```python
litellm.success_callback = ["langfuse"]
litellm.failure_callback = ["langfuse"]
```

이렇게 등록해두면, `litellm.completion()`으로 나가는 **모든 LLM 호출**(Solar든 Gemini든)이
자동으로 Langfuse에 트레이스(입력·출력·지연시간·비용·에러 여부)로 기록됩니다. 각 호출은
`trace_name`으로 파이프라인 단계를 구분합니다:

| trace_name | 어떤 호출인가 |
|---|---|
| `intent_classify` | Solar — 학생 메시지 의도 분류 |
| `diagnose_step` | Solar — 오답/막힌 지점 진단 |
| `confirm_single_answer` | Solar — 이중검증(정답 판정 시 2차 확인) |
| `generate_hint` | Solar — 힌트 생성 |
| `gemini_intent_classify` | Gemini — eval이 의도분류를 독립 재판정(폴백 아님) |
| `gemini_judge` | Gemini — eval이 진단/힌트 설명을 감사관처럼 독립 판정(폴백 아님) |

> **주의**: `gemini_intent_classify`/`gemini_judge`는 Solar 장애 시 발동하는 폴백과
> **다른 코드 경로**입니다. eval 스크립트가 신뢰성 검증을 위해 매번 일부러 Gemini를
> "주 모델"로 직접 호출하는 것이라, 실패와 무관하게 항상 발생합니다.

이것만으로는 **"얼마나 잘하는지"(정확도)는 안 나옵니다.** 트레이스는 호출 기록일 뿐이고,
정확도는 별도로 채점해서 **score**로 붙여야 Langfuse 대시보드에서 보입니다 — 그 작업이
`evals/eval_pipeline_accuracy.py`입니다.

---

## 2. 측정하는 7개 지표

| score 이름 | 무엇을 측정하는가 | 정답 기준 |
|---|---|---|
| `intent_accuracy` | 메시지를 normal/answer_seeking/off_topic 중 정확히 분류하는가 | 작성자가 정한 라벨 |
| `intent_gemini_agreement` | 같은 메시지를 Gemini도 독립 분류시켰을 때 Solar와 동의하는가 | Gemini의 독립 판단 |
| `diagnosis_solved_accuracy` | 학생이 최종 정답에 도달했는지 정확히 판별하는가 | 문제의 진짜 `answer`와 **기계적 비교** |
| `diagnosis_stuckpoint_accuracy` | 학생이 **어디서/왜 틀렸는지** 정확히 짚어내는가 | 작성자가 정한 기대 키워드 |
| `diagnosis_stuckpoint_gemini_judge` | 그 "막힌 지점" 설명이 맞는지 Gemini가 독립 판단 | Gemini의 독립 판단 |
| `hint_quality` | 힌트가 진단된 실수 내용을 실제로 반영하는가 | 작성자가 정한 기대 키워드 |
| `hint_quality_gemini_judge` | 그 힌트 내용이 맞는지 Gemini가 독립 판단 | Gemini의 독립 판단 |

### 왜 진단이 2개(정답판별 vs 막힌지점)로 나뉘어 있는가

`diagnose_step()` 호출 한 번이 `is_correct`/`solved`(판정)와 `stuck_point`(설명) 을 동시에
반환합니다. 이 둘은 성격이 달라서 따로 채점합니다:

- **정답판별**(`solved`/`is_correct`): 그래프의 **실제 라우팅**을 결정하는 값이라, 틀리면
  학생 경험이 바로 망가짐(예: 안 풀었는데 축하해버림). 문제의 진짜 정답과 비교만 하면 되므로
  **사람 라벨이 필요 없고 100% 객관적**입니다.
- **막힌지점**(`stuck_point`): 부가 설명 문장이라 자유 텍스트 비교가 필요해서, 근사치인
  키워드 매칭으로 채점합니다. 원래 "학생이 어디서 틀렸는지 AI가 잘 짚어내는가"라는 질문은
  이 지표가 답합니다.

---

## 3. 채점 로직 — 골든셋 예시로

### ① intent_accuracy — 라벨과 문자열 비교

```python
{"message": "그냥 답 알려주세요", "expected": "answer_seeking"}

intent = classify_intent("그냥 답 알려주세요", 문제)   # -> "answer_seeking"
correct = (intent == "answer_seeking")                  # True/False
```

10개 케이스는 우회 화법(직접형/간접형/애원형/긴급성유도)과 잡담, 그리고 **헷갈리기 쉬운
정상 케이스**("9권이면 2250원 맞죠?" — 확인 질문일 뿐 우회 아님)를 섞어서 구성했습니다.

### ② diagnosis_solved_accuracy — 기계적 비교 (사람 라벨 없음)

```python
def mechanical_solved(problem, attempt):
    answer_nums = 문제의_진짜_정답에서_숫자만_추출
    attempt_nums = 학생_답에서_숫자만_추출
    if len(attempt_nums) > 1:
        return False   # 여러 후보를 나열했으면 확신 있는 정답으로 안 침(이중검증과 동일 규칙)
    return 정답_숫자가_학생_답에_포함되는가
```

이 함수가 계산한 값과 `diagnose_step()`이 실제로 반환한 `solved`를 비교합니다.
사람이 케이스마다 "이건 정답이다/아니다"를 미리 정해둘 필요가 없습니다.

### ③ diagnosis_stuckpoint_accuracy / hint_quality — 키워드 근사 채점

"이 실수를 제대로 설명하면 반드시 나올 단어"를 역산해서 정합니다.

```python
# p_0060: "3권 750원, 9권이면?" (정답 2250원)
{"attempt": "9권이니까 750×9=6750원이요",
 "expect_stuck_any": ["1권", "나누", "250"]}
# → "1권 가격을 안 구하고 바로 곱했다"는 실수를 설명하려면 "1권"이라는 말 없이는 불가능
```

힌트 키워드는 같은 stuck_point에서 재사용합니다(힌트가 진단을 반영했는지 보는 것이므로).

**한계**: AI가 내용상 맞게 설명해도 정확히 그 단어를 안 쓰면 오답 처리될 수 있습니다
(실제 사례: `p_0001 "816이요"` 케이스 — 힌트가 "816 다음으로 큰 수"라고만 표현하고
"세 번째"라는 단어를 안 써서 3번 다 keyword 채점에서 FAIL. 그런데 Gemini 독립판단은
"맞음"으로 판정 → 키워드 방식의 실제 오탐 사례).

### ④ Gemini 교차검증 — 작성자 라벨과 무관한 두 번째 신뢰도 축

```python
def gemini_judge_explanation(problem, attempt, explanation, trace_id):
    # Solar가 만든 explanation을 다시 보여주는 게 아니라,
    # 문제·정답·학생답·AI설명만 주고 Gemini가 "이 설명이 맞나?"를 독립적으로 판단
    ...
```

Solar와 Gemini가 **서로 다른 모델**이라, 작성자의 키워드/라벨이 틀렸어도 걸러낼 수 있는
두 번째 검증 축입니다. 무료 티어 요청 제한(분당 제한 + **하루 20회**) 때문에 한 번에
전부 통과하지는 못할 수 있습니다 — 실패하면 조용히 건너뛰고 점수를 안 남깁니다.

---

## 4. Langfuse에서 확인하는 법

1. 왼쪽 사이드바 **Evaluation → Scores** 클릭
2. `Name` 필터에서 지표 이름 선택 → `Value`(True/False) 비율이 곧 정확도
3. **Scores → Analytics 탭**에서 지표 하나를 고르면 `Mode %`(=정확도), `Trend Over Time`
   (시간에 따른 변화)을 자동 집계
4. **"Second score" 비교(Beta)** — 예를 들어 `hint_quality` + `hint_quality_gemini_judge`를
   같이 선택하면 **Confusion Matrix, Agreement %, Cohen's κ, F1 Score**를 자동 계산해줍니다.
   "내 키워드 채점과 Gemini 독립판단이 얼마나 일치하는가"를 UI에서 바로 볼 수 있는 기능입니다
   (단, 매칭된 표본이 적으면 통계치가 안 정확하니 참고만 할 것).

### 예전 이름 정리

`diagnosis_accuracy`(정답판별+막힌지점을 합쳐서 채점하던 옛 이름)는 지금 코드에 더 이상
없습니다. Langfuse API로 관련 score를 전부 삭제했습니다. 혹시 대시보드에 아직 남아있다면
캐시 반영 지연(최대 24시간)일 뿐, 실제 데이터는 이미 없는 상태입니다.

---

## 5. 신뢰성에 대한 정직한 평가

| 층위 | 신뢰도 | 비고 |
|---|---|---|
| `diagnosis_solved_accuracy` | ★★★ 가장 높음 | 사람 판단 없이 기계적 비교 |
| `*_gemini_agreement`, `*_gemini_judge` | ★★☆ 중간 | 독립 모델 검증이지만 표본 수 적음(API 할당량) |
| `intent_accuracy`, `diagnosis_stuckpoint_accuracy`, `hint_quality` | ★☆☆ 참고용 | 작성자가 직접 만든 라벨/키워드, 자기검증 성격 |

이 골든셋은 **작성자가 직접 만든 가상 시나리오**를 기준으로 하는 자체 점검(smoke test)이지,
독립적으로 검증된 벤치마크는 아닙니다. 발표 등에서 인용할 때는 "제한된 골든셋(N=10~11) 기준
자체 평가 결과"라고 명확히 밝히는 것이 정직합니다. 신뢰성을 더 높이려면:

1. 팀원이 애매한 케이스를 블라인드로(라벨 안 보여주고) 재검토
2. 문제은행(690개)에서 랜덤 샘플링해 케이스 수를 늘림
3. Gemini 할당량이 회복된 뒤 교차검증 표본을 더 확보
4. 서비스가 실제로 쓰이기 시작하면, 지금 심어둔 `trace_id` 덕분에 Langfuse에 남는 진짜
   학생 대화를 골든셋으로 교체 가능
