# MathMate 🧮

> 정답을 알려주지 않고 힌트로만 유도하는 초등 수학 소크라테스식 튜터

---

## 1. 프로젝트 소개

MathMate는 초등학교 4~6학년 학생을 대상으로 하는 대화형 수학 튜터입니다.
일반적인 AI 튜터와 달리 **정답을 직접 알려주지 않고**, 학생이 틀려도
소크라테스식 힌트와 되질문으로만 스스로 답에 도달하도록 유도합니다.
Solar(Upstage) LLM과 LangGraph 기반 에이전트로 학생의 풀이 단계를 진단하고,
답 유출 방지 가드레일을 이중·삼중으로 걸어 "빠른 정답" 대신 "스스로 생각할 시간"을 지켜줍니다.

- **한 줄 소개**: 정답을 알려주지 않고 힌트로만 유도하는 초등 수학 소크라테스식 튜터
- **주요 사용자**: 초등학교 4~6학년 학생 (및 학습 진척도를 확인하는 학부모)
- **만들게 된 배경**: 숏폼 시대의 '빠른 정답' 의존이 스스로 사고하는 힘을 해친다는 문제의식
- **최종 결과물**: Streamlit 채팅 화면 + FastAPI(SSE) 백엔드로 배포된 대화형 튜터 웹 서비스

---

## 2. 문제 정의

최근 숏폼 콘텐츠(유튜브 쇼츠, 틱톡 등)의 범람으로, 즉각적인 보상에 길들여진
아이들의 '팝콘 브레인' 현상과 집중력 저하, 더 나아가 소아·청소년 ADHD 발병률
증가는 심각한 사회적 문제로 대두되고 있습니다.

이러한 상황에서 시장에 나온 대부분의 AI 튜터는 학생이 모르는 문제를 물어보면
정답과 풀이 과정을 즉각적으로 제공합니다. 당장 눈앞의 숙제를 끝내기에는
편하지만, 이는 '빠른 정답'이라는 또 다른 도파민을 제공할 뿐 학생이 스스로
끈기 있게 사고할 기회를 빼앗아 결과적으로 인지 능력과 학습 습관에 '독'이 됩니다.

특히 대상 사용자를 **초등학교 4~6학년**으로 특정한 이유는 다음과 같습니다.
중·고등학생은 성적이 입시와 직결되어 챗봇보다 인강·학원 학습이 더 효과적이라 타겟에서 제외했고,
초등 저학년은 아직 놀이 중심 시기, 고학년이 본격적으로 공부를 시작하는 타이밍입니다.
이 시기 핵심은 공부에 대한 흥미를 붙이는 것이기에, 온라인·대화형·즉각 반응형 챗봇은 피드백이 빨라
학원·인강보다 수학에 흥미를 붙이기 유리합니다.

---

## 3. 문제 해결

MathMate는 위 문제를 다음과 같이 풀어냅니다.

- **소크라테스식 대화**: 정답을 바로 주지 않고, 학생이 막힌 지점을 진단해
  "다음 한 걸음"만 힌트로 제시 → 스스로 생각할 여지를 남긴다.
- **답 유출 방지 가드레일(이중·삼중)**: "답만 알려줘" 같은 직접적인 요구를 입력단에서 거르고,
  응답을 내보내기 직전에도 정답 숫자가 새어 나가지 않는지 한 번 더 검사하며
  (`refuse_and_redirect` → `leak_verify`), 진단 결과는 Gemini로 교차검증한다.
- **단계적 힌트(1~3단계)**: 한 번에 다 알려주지 않고, 막힌 정도에 따라 점점
  구체화되는 힌트를 단계별로 제공한다. 3단계를 다 쓰고도 틀리면 정답과 해설을 공개한다.
- **진척도 추적**: 정답률이 아니라 "힌트를 얼마나 적게 쓰고 스스로 풀었는지"로
  단원별 숙련도를 측정해, 장기적으로 스스로 생각하는 습관을 강화하도록 설계했다.

**전체 동작 흐름**: 학생 입력 → 의도 분류(입력 가드레일) → 풀이 진단 →
힌트 생성 / 중간정답 칭찬 / 정답 공개 → 정답 유출 검증(출력 가드레일) → SSE로 응답 스트리밍.

---

## 4. 핵심 기능

- **실시간 SSE 스트리밍 채팅**: 튜터의 답변이 토큰 단위로 타이핑되듯 표시
- **실제 Solar(Upstage) LLM 연동**: 의도 분류 → 진단 → 힌트 생성까지 LangGraph
  에이전트가 조율, 실패 시 Retry·Fallback(Gemini)·Mock 규칙으로 자동 복구
- **초등학생 친화적 채팅 UI**: Streamlit 기반, 파스텔톤·큰 글씨·이모지 아바타로
  구성된 학생-튜터 말풍선 채팅 화면
- **학습 진척도·피드백**: 힌트 사용량 기반 진척도와 단원별 숙련도·난이도별 정답률을
  개인화된 리포트로 제공
- **LLMOps 운영 안정성**: 에러 유형별 재시도/폴백, Langfuse로 모든 LLM 호출 트레이싱
- **문제은행**: HuggingFace 공개 데이터셋에서 초등 4~6학년 문장제를 선별하고 부족한
  단원은 생성해, 단원·난이도·단계별 힌트로 가공(4~6학년 전 단원 커버)
- **원클릭 배포**: Docker Compose + GCE, GitHub Actions로 CI/CD 자동화

---

## 5. 데모 영상

- **데모 영상**:

https://github.com/user-attachments/assets/9682545e-31db-4bda-815e-d470be347189

- **배포 URL**: http://34.158.211.122:8501/
- **추가 시연 자료**: [발표자료(Google Slides)](https://docs.google.com/presentation/d/1x0U7ITbB2ES_dt2O26vNbChOKDnXoOHcxuWii-nsOBg/edit?usp=sharing)

---

## 6. 팀원 소개

| 이름 | 역할 | GitHub |
|---|---|---|
| 권지운 | Backend, Agent | [@jiwoon084](https://github.com/jiwoon084) |
| 이나영 | Frontend, Infra, LLMOps | [@leena-0](https://github.com/leena-0) |

---

## 7. 참고자료 / 발표자료

- **발표자료**: [MathMate 발표자료 (Google Slides)](https://docs.google.com/presentation/d/1x0U7ITbB2ES_dt2O26vNbChOKDnXoOHcxuWii-nsOBg/edit?usp=sharing)
- **기획서**: https://docs.google.com/document/d/1I8wwrhb9Zv6gZSmi82APVVAy7fcNs9-T4Ze3dxppQ2w/edit?usp=sharing
- **참고한 문서**: [개발 문서(설치·배포·LLMOps) — docs/DEVELOPMENT.md](docs/DEVELOPMENT.md)
- **참고한 오픈소스**: [LangGraph](https://github.com/langchain-ai/langgraph), [LiteLLM](https://github.com/BerriAI/litellm), [FastAPI](https://github.com/fastapi/fastapi), [Streamlit](https://github.com/streamlit/streamlit), [Supabase](https://github.com/supabase/supabase), [Langfuse](https://github.com/langfuse/langfuse)
- **데이터 출처**: [kuotient/orca-math-word-problems-193k-korean](https://huggingface.co/datasets/kuotient/orca-math-word-problems-193k-korean) (CC-BY-SA-4.0)
- **기타**: [GitHub 저장소 — leena-0/MathMate](https://github.com/leena-0/MathMate)
