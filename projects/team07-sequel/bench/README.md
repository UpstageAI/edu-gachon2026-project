# Solar 모델 라우팅 벤치마크

난이도(하/중/상/최상)별로 **solar-mini / solar-pro2 / solar-pro3** 의 Text-to-SQL
성능을 비교해, 어느 난이도를 어느 모델로 라우팅할지 근거를 만든다.
또한 **컨텍스트 조건(zero / few-shot / schema-linker / schema+few)** 별 ablation 으로
정확도를 끌어올리는 레버가 무엇인지 측정한다.

- **데이터**: AI Hub `자연어 기반 질의(NL2SQL) 검색 생성 데이터` Validation 세트
  (질문·gold SQL·hardness·db_id + db별 sqlite 동봉 → 실행 채점)
- **난이도**: easy→하, medium→중, hard→상, extra hard→최상
- **지표**
  - **EX** (execution match): gold/pred SQL 을 같은 sqlite 에 실행해 결과셋 일치 — 핵심
  - **EM** (exact match): 정규화 후 SQL 문자열 일치 — 보조
  - **토큰/가격 효율**: 문항당 토큰·비용, 정답당 비용 (Upstage 공식 단가)
  - **지연**: 문항당 평균 응답 시간

## 실험 조건 (2×2)

| 조건 (`--cond`) | 스키마 | few-shot |
|---|---|---|
| `zero` | DDL만 | ✗ |
| `few` | DDL | 같은 db 유사질문 K개 |
| `schema` | DDL + 컬럼별 샘플 값 (value_retriever 대용) | ✗ |
| `schema_few` | DDL + 샘플 값 | ✓ |

임베딩은 쓰지 않는다: few-shot 검색은 char-bigram Jaccard, 값은 `SELECT DISTINCT … LIMIT K`.

## 실행

```bash
# 1) 기준 평가셋 (오프라인·무료). 난이도별 25문항, sqlite 를 bench/dbs/ 로 복사
uv run python -m bench.build_eval_set

# 2) few-shot / schema-linker 조건 평가셋 (오프라인·무료)
uv run python -m bench.build_fewshot          # → eval_set_fewshot.json
uv run python -m bench.build_schema_linked    # → eval_set_schema.json, eval_set_schema_fewshot.json

# 3) 채점기 self-test (오프라인·무료). pred=gold 로 EM/EX 100% 확인
uv run python -m bench.evaluate

# 4) 조건별 벤치 실행 (유료: UPSTAGE_API_KEY 필요, 재개 가능)
export UPSTAGE_API_KEY=...                      # 또는 .env
uv run python -m bench.bench run --cond zero
uv run python -m bench.bench run --cond few
uv run python -m bench.bench run --cond schema
uv run python -m bench.bench run --cond schema_few

# 5) 단일 조건 콘솔 리포트
uv run python -m bench.bench report --cond schema_few

# 6) 전체 조건 ablation 을 마크다운으로 (→ docs/benchmark_routing.md)
uv run python -m bench.summarize_md
```

## 설정 (`bench/config.py`)

- `SAMPLES_PER_LEVEL` (env `BENCH_SAMPLES`): 난이도별 문항 수. 총 호출 = 문항×4×모델수×조건수
- `FEWSHOT_K` (env `BENCH_FEWSHOT_K`) / `SCHEMA_VALUE_K` (env `BENCH_VALUE_K`)
- `MODELS`: 모델 문자열과 단가(USD/1M). `solar-pro3` 문자열은 계정에서 한번 확인 권장
- `ROUTING_EX_TARGET` (env `BENCH_EX_TARGET`): 라우팅 판정 EX 임계값 (기획서 KPI 0.70)

## 파일

| 파일 | 역할 |
|---|---|
| `build_eval_set.py` | AI Hub zip → 층화표본 `eval_set.json` + sqlite 복사 |
| `build_fewshot.py` | 같은 db 유사질문 K개 부착 → `eval_set_fewshot.json` |
| `build_schema_linked.py` | 컬럼별 샘플 값 부착 → `eval_set_schema*.json` |
| `evaluate.py` | EM/EX 채점 (+ self-test) |
| `bench.py` | 모델 호출 + 채점, `run`/`report --cond` |
| `summarize_md.py` | 전 조건 → `docs/benchmark_routing.md` |

## 유의

- `eval_set*.json`, `dbs/`, `results*.jsonl` 은 gitignore (AI Hub 라이선스·용량). 공유는 집계 리포트만.
- 표본 난이도별 25문항에선 **모델 간 EX 차이가 통계 노이즈(±~18%p)** 안. 조건 효과는 크고 robust하나,
  모델별 라우팅 확정엔 표본 확대 필요.
- 단가: solar-mini 입출력 $0.15 flat, pro2·pro3 입력 $0.15 / 출력 $0.60 (동일).
