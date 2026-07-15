# 주요 코드 정리

프로젝트명: **가천대학교 AI학과 길잡이**
목적: GitHub 문서화 및 발표 준비를 위해 핵심 코드 구조를 파일별로 정리한다.
기준: 업로드된 프로젝트 코드 기준
주의: `.env`, API Key, `.git` 내부 파일은 제외했다.

---

## 1. 전체 실행 흐름

```text
사용자
  ↓
Jinja2 Chat UI
  ↓
FastAPI /api/chat 또는 /api/chat/stream
  ↓
LangGraph Agent
  ├─ router_node: intent 분류
  ├─ rag_node: RAG 문서 검색
  ├─ tool_node: 졸업학점 계산 / 과목 추천
  └─ response_node: 최종 답변 생성
  ↓
Upstage Solar LLM
  ↓
SSE Streaming Response
  ↓
프론트엔드 채팅 UI
```

---

# 2. FastAPI 진입점

## `app/main.py`

### 역할

- FastAPI 앱 생성
- 정적 파일 `/static` 연결
- Jinja2 템플릿 연결
- `/api/chat`, `/api/chat/stream` 라우터 등록
- `/health`에서 DB 연결과 문서 적재 상태 확인

```python
# app/main.py
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from app import db
from app.routers import chat

BASE_DIR = Path(__file__).resolve().parent

app = FastAPI(title="AI 학과 길잡이 MVP")

app.mount(
    "/static",
    StaticFiles(directory=BASE_DIR / "static"),
    name="static",
)

templates = Jinja2Templates(directory=BASE_DIR / "templates")
# /api/chat 은 LangGraph 에이전트 라우터가 담당 (router → rag/tool → response)
app.include_router(chat.router)

@app.get("/", response_class=HTMLResponse)
async def home(request: Request):
    return templates.TemplateResponse(
        request=request,
        name="index.html",
        context={},
    )


@app.get("/health")
def health():
    status = {"status": "ok", "db": "unknown"}

    try:
        conn = db.connect()
        count = conn.execute("SELECT count(*) FROM documents").fetchone()[0]
        conn.close()
        status["db"] = "ok"
        status["documents"] = count
    except Exception as e:
        status["status"] = "degraded"
        status["db"] = f"error: {e}"

    return status
```

---

# 3. Chat API와 SSE Streaming

## `app/routers/chat.py`

### 역할

- 일반 JSON 응답 API: `POST /api/chat`
- SSE 스트리밍 API: `POST /api/chat/stream`
- LangGraph 실행 결과를 프론트엔드가 쓰기 좋은 형태로 변환
- RAG 출처, Tool 결과 출처, Guardrail 문의처를 sources로 정리
- SSE 이벤트 형식: `status`, `meta`, `delta`, `done`, `error`

## 핵심 코드 1: 요청 모델과 출처 정리

```python
# app/routers/chat.py — lines 16-50
router = APIRouter(prefix="/api", tags=["chat"])


class ChatRequest(BaseModel):
    message: str
    session_id: str | None = None


def _rag_sources(docs: list[dict]) -> list[dict]:
    """검색 문서를 출처별로 묶어 프론트가 쓰는 {source, page, score} 형태로."""
    best: dict[str, dict] = {}
    for d in docs:
        src = d.get("source") or "출처 없음"
        score = d.get("score", 0)
        if src not in best or score > best[src]["score"]:
            best[src] = {
                "source": src,
                "page": d.get("page"),
                "score": round(float(score), 3),
            }
    return sorted(best.values(), key=lambda s: s["score"], reverse=True)


def _contact_sources(contact: dict | None) -> list[dict]:
    """가드레일 안내의 문의처/링크를 프론트 sources({source}) 형태로."""
    if not contact:
        return []
    srcs: list[dict] = []
    if contact.get("matched"):
        phone = (contact.get("담당") or {}).get("전화") or contact.get("대표전화")
        label = contact["부서"] + (f" ☎ {phone}" if phone else "")
        srcs.append({"source": label})
    for link in contact.get("링크", []):
        srcs.append({"source": f"{link['이름']} ({link['URL']})"})
    return srcs
```

## 핵심 코드 2: 일반 채팅 API

```python
# app/routers/chat.py — lines 53-93
@router.post("/chat")
async def chat(req: ChatRequest):
    graph = get_graph()
    state = create_initial_state(
        session_id=req.session_id or "default",
        messages=[HumanMessage(content=req.message)],
    )
    result = await graph.ainvoke(state)

    answer = result["messages"][-1].content
    intent = result.get("intent")

    # 출처 표기 (프론트 chat.js는 {source, page, score} 객체 배열을 기대)
    sources: list[dict] = []
    response_type = "chat_answer"

    contact = result.get("contact")

    if intent == "rag" and result.get("guardrail"):
        response_type = "guardrail"
        sources = _contact_sources(contact)
    elif intent == "rag":
        docs = result.get("retrieved_docs", [])
        sources = _rag_sources(docs)
        response_type = "rag_llm_answer"
    elif intent == "tool":
        tr = result.get("tool_result") or {}
        data = tr.get("data") if isinstance(tr, dict) else None
        if isinstance(data, dict) and data.get("출처"):
            # page/score는 생략 → 프론트에서 undefined로 처리되어 표기 안 됨
            sources = [{"source": data["출처"]}]
        response_type = "tool_answer"

    return {
        "answer": answer,
        "type": response_type,
        "intent": intent,
        "tool_name": result.get("tool_name"),
        "sources": sources,
        "contact": contact,
    }
```

## 핵심 코드 3: SSE 이벤트 포맷과 response_node 직전까지 실행

```python
# app/routers/chat.py — lines 95-127
def sse_event(event: str, data: dict) -> str:
    return (
        f"event: {event}\n"
        f"data: {json.dumps(data, ensure_ascii=False)}\n\n"
    )


async def prepare_state_without_response(req: ChatRequest):
    """LangGraph의 response_node 직전까지 실행한다.

    즉,
    router → rag/tool
    까지만 수행하고, 최종 LLM 응답 생성은 stream=True로 따로 처리한다.
    """
    state = create_initial_state(
        session_id=req.session_id or "default",
        messages=[HumanMessage(content=req.message)],
    )

    router_update = await router_node(state)
    state.update(router_update)

    route = route_by_intent(state)

    if route == "rag":
        rag_update = await rag_node(state)
        state.update(rag_update)

    elif route == "tool":
        tool_update = await tool_node(state)
        state.update(tool_update)

    return state
```

## 핵심 코드 4: SSE Streaming API

```python
# app/routers/chat.py — lines 129-198
@router.post("/chat/stream")
async def chat_stream(req: ChatRequest):
    async def event_generator():
        yield sse_event("status", {"message": "질문을 분석하는 중이에요."})

        state = await prepare_state_without_response(req)

        intent = state.get("intent")
        sources: list[dict] = []
        response_type = "chat_answer"

        contact = state.get("contact")

        if intent == "rag" and state.get("guardrail"):
            response_type = "guardrail"
            sources = _contact_sources(contact)

        elif intent == "rag":
            docs = state.get("retrieved_docs", [])
            sources = _rag_sources(docs)
            response_type = "rag_llm_answer"

        elif intent == "tool":
            tr = state.get("tool_result") or {}
            data = tr.get("data") if isinstance(tr, dict) else None
            if isinstance(data, dict) and data.get("출처"):
                sources = [{"source": data["출처"]}]
            response_type = "tool_answer"

        yield sse_event(
            "meta",
            {
                "type": response_type,
                "intent": intent,
                "tool_name": state.get("tool_name"),
                "sources": sources,
                "contact": contact,
            },
        )

        system_prompt, user_input = build_response_inputs(state)

        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_input},
        ]

        try:
            for token in llm.chat_stream(messages):
                yield sse_event("delta", {"text": token})

            yield sse_event("done", {"message": "complete"})

        except Exception as e:
            yield sse_event(
                "error",
                {
                    "message": f"스트리밍 중 오류가 발생했습니다: {str(e)}"
                },
            )

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )
```

---

# 4. LangGraph State와 Graph 구조

## `app/graph/state.py`

### 역할

- LangGraph에서 노드 간 공유할 상태 정의
- intent, category, RAG 검색 결과, Tool 실행 결과, Guardrail 여부, session_id 관리

```python
# app/graph/state.py
"""LangGraph 에이전트 상태 정의."""
from typing import Annotated, Literal, TypedDict

from langchain_core.messages import BaseMessage
from langgraph.graph.message import add_messages


class AgentState(TypedDict):
    messages: Annotated[list[BaseMessage], add_messages]

    # Router가 결정한 의도
    intent: Literal["chat", "rag", "tool"] | None

    # Router가 분류한 카테고리 (rag 검색 필터용). None이면 전체 검색.
    category_l1: str | None

    # RAG 검색 결과 (문서 내용 + 출처)
    retrieved_docs: list[dict]

    # Tool 정보
    tool_name: str | None
    tool_args: dict | None
    tool_result: dict | None

    # 가드레일: RAG로 답을 못 찾아 문의처로 안내해야 할 때
    guardrail: bool
    contact: dict | None

    session_id: str


def create_initial_state(session_id: str, messages: list[BaseMessage] | None = None) -> AgentState:
    return AgentState(
        messages=messages or [],
        intent=None,
        category_l1=None,
        retrieved_docs=[],
        tool_name=None,
        tool_args=None,
        tool_result=None,
        guardrail=False,
        contact=None,
        session_id=session_id,
    )
```

---

## `app/graph/graph.py`

### 역할

- LangGraph의 전체 실행 흐름 정의
- `START → router → rag/tool/response → response → END`
- router 결과에 따라 조건부 분기

```python
# app/graph/graph.py
"""LangGraph 그래프 구성: START -> router -> (rag|tool|response) -> response -> END."""
from langgraph.graph import END, START, StateGraph

from app.graph.edges import route_by_intent
from app.graph.nodes import rag_node, response_node, router_node, tool_node
from app.graph.state import AgentState

_compiled = None


def create_graph():
    builder = StateGraph(AgentState)
    builder.add_node("router", router_node)
    builder.add_node("rag", rag_node)
    builder.add_node("tool", tool_node)
    builder.add_node("response", response_node)

    builder.add_edge(START, "router")
    builder.add_conditional_edges(
        source="router",
        path=route_by_intent,
        path_map={"rag": "rag", "tool": "tool", "response": "response"},
    )
    builder.add_edge("rag", "response")
    builder.add_edge("tool", "response")
    builder.add_edge("response", END)
    return builder.compile()


def get_graph():
    global _compiled
    if _compiled is None:
        _compiled = create_graph()
    return _compiled
```

---

## `app/graph/edges.py`

### 역할

- router_node가 결정한 intent에 따라 다음 노드 결정
- `rag`, `tool`, `response` 중 하나로 분기

```python
# app/graph/edges.py
"""조건부 라우팅: router 이후 intent에 따라 분기."""
from typing import Literal

from app.graph.state import AgentState


def route_by_intent(state: AgentState) -> Literal["rag", "tool", "response"]:
    intent = state.get("intent") or "chat"
    if intent == "rag":
        return "rag"
    if intent == "tool":
        return "tool"
    return "response"
```

---

# 5. LangGraph Node 구현

## `app/graph/nodes.py`

### 역할

- `router_node`: 사용자 intent 분류
- `rag_node`: RAG 검색 및 guardrail 판단
- `tool_node`: Tool 실행
- `response_node`: RAG/Tool/Guardrail에 맞는 최종 답변 생성
- `build_response_inputs`: SSE와 일반 응답에서 공통으로 쓰는 prompt 생성 로직

## 핵심 코드 1: Router 구조화 출력 모델

```python
# app/graph/nodes.py — lines 24-39
# "none" = 카테고리 미분류(전체 검색). Optional(null)보다 명시 값이 구조화 출력에서 안정적.
CATEGORY_L1 = Literal[
    "graduation", "course", "academic_calendar",
    "social_service", "leave_return", "contact", "none",
]


class IntentRoute(BaseModel):
    """LLM은 의도+카테고리만 분류. (숫자 인자 추출은 구조화 출력이 불안정하여 규칙으로 처리)"""

    intent: Literal["chat", "rag", "tool"] = Field(description="사용자 의도")
    category_l1: CATEGORY_L1 = Field(
        default="none",
        description="intent=rag 일 때 질문이 속한 카테고리. 판단 어려우면 'none'.",
    )

```

## 핵심 코드 2: 정보성 질문 감지 및 category 키워드 분류

```python
# app/graph/nodes.py — lines 41-95
# chat으로 오분류돼도 '사실 정보'를 묻는 신호가 있으면 rag로 강제 (근거 없는 답변/환각 방지)
_INFO_SIGNALS = (
    "문의", "연락처", "연락", "전화", "번호", "규정", "일정", "신청", "방법",
    "장학", "기숙사", "생활관", "벌점", "졸업", "수강", "성적", "학점", "도서관",
    "포털", "휴학", "복학", "전과", "재수강", "교육과정", "등록금", "증명", "취업",
)


def _looks_informational(text: str) -> bool:
    return any(sig in text for sig in _INFO_SIGNALS)


def _find_int(pattern: str, text: str) -> int | None:
    m = re.search(pattern, text)
    return int(m.group(1)) if m else None


def _detect_track(text: str) -> str | None:
    t = text.lower()
    if "aiot" in t:
        return "AIoT"
    if "vision" in t or "language" in t or "비전" in text or "자연어" in text:
        return "Vision & Language"
    if "intelligent" in t or "인텔리전트" in text:
        return "Intelligent SW"
    if "부트캠프" in text or "bootcamp" in t:
        return "AI부트캠프"
    return None


# 카테고리 키워드 분류(결정적). Solar 구조화출력이 category를 잘 안 채워 규칙을 주 경로로 쓴다.
# 순서 = 우선순위(위에서부터 먼저 매칭). 시간/일정 신호는 course 보다 먼저 둬 '언제' 질문을 일정으로.
_CATEGORY_KEYWORDS: list[tuple[str, tuple[str, ...]]] = [
    ("social_service", ("사회봉사", "봉사활동", "봉사시간", "자원봉사", "봉사")),
    ("leave_return", ("휴학", "복학", "휴학연기", "복적")),
    ("graduation", ("졸업", "학위", "졸업인증", "외국어인증", "외국어 졸업", "졸업요건", "졸업학점")),
    ("academic_calendar", (
        "일정", "날짜", "언제", "며칠", "기간", "개강", "종강", "방학",
        "시험", "중간고사", "기말고사", "성적", "등록금", "계절학기",
    )),
    ("course", (
        "수강신청", "수강 신청", "수강정정", "수강 정정", "수강포기", "수강 포기",
        "수강", "과목", "교육과정", "커리큘럼", "트랙", "시간표", "강의",
        "전공필수", "전공선택", "이수구분",
    )),
    ("contact", ("전화번호", "연락처", "문의", "사무실", "어디에 물어", "어디로 문의")),
]


def classify_category(text: str) -> str | None:
    """질문을 category_l1 로 분류(키워드 규칙). 매칭 없으면 None(전체 검색)."""
    for cat, words in _CATEGORY_KEYWORDS:
        if any(w in text for w in words):
            return cat
    return None
```

## 핵심 코드 3: Tool 인자 추출

```python
# app/graph/nodes.py — lines 98-130
def resolve_tool(text: str) -> tuple[str | None, dict | None]:
    """자연어에서 도구 이름과 인자를 규칙 기반으로 추출."""
    학년 = _find_int(r"([1-4])\s*학년", text)
    학기 = _find_int(r"([1-2])\s*학기", text)

    # 1) 졸업요건 계산: '학점' + ('졸업' 또는 '남')
    if "학점" in text and ("졸업" in text or "남" in text):
        args: dict = {}
        for key, pat in [
            ("전공필수", r"전공\s*필수\s*(\d+)"),
            ("전공선택", r"전공\s*선택\s*(\d+)"),
            ("공통필수", r"공통\s*필수\s*(\d+)"),
            ("공통선택", r"공통\s*선택\s*(\d+)"),
        ]:
            v = _find_int(pat, text)
            if v is not None:
                args[key] = v
        if "전공필수" not in args and "전공선택" not in args:
            v = _find_int(r"전공\D{0,3}(\d+)\s*학점", text) or _find_int(r"(\d+)\s*학점", text)
            if v is not None:
                args["전공"] = v
        if args:
            return "calc_graduation_progress", args

    # 2) 과목 추천: 학년+학기
    if 학년 and 학기:
        args = {"학년": 학년, "학기": 학기}
        trk = _detect_track(text)
        if trk:
            args["트랙"] = trk
        return "recommend_courses", args

    return None, None
```

## 핵심 코드 4: router_node

```python
# app/graph/nodes.py — lines 145-184
async def router_node(state: AgentState) -> dict:
    """LLM으로 의도 분류 → tool이면 규칙 기반으로 도구/인자 결정."""
    user_input = state["messages"][-1].content
    structured_llm = get_llm().with_structured_output(IntentRoute)
    llm_category = "none"
    try:
        result = await structured_llm.ainvoke(
            [SystemMessage(content=ROUTER_PROMPT), HumanMessage(content=user_input)]
        )
        intent = result.intent
        llm_category = result.category_l1
    except Exception:
        intent = "rag"

    # 안전망: chat으로 분류됐어도 '사실 정보'를 묻는 질문이면 rag로 (근거 없는 환각 방지)
    if intent == "chat" and _looks_informational(user_input):
        intent = "rag"

    # 카테고리 분류: 키워드 규칙 주 경로 + LLM 보조(규칙 미매칭 시).
    # ("none"/contact 는 문서가 없어 필터 안 함 → 전체 검색 후 가드레일이 문의처 안내)
    category_l1 = None
    if intent == "rag":
        category_l1 = classify_category(user_input)
        if category_l1 is None and llm_category not in ("none", "contact"):
            category_l1 = llm_category
        if category_l1 == "contact":
            category_l1 = None

    tool_name, tool_args = None, None
    if intent == "tool":
        tool_name, tool_args = resolve_tool(user_input)
        if tool_name is None:
            intent = "rag"  # 도구 판별 실패 → RAG로 폴백

    return {
        "intent": intent,
        "category_l1": category_l1,
        "tool_name": tool_name,
        "tool_args": tool_args,
    }
```

## 핵심 코드 5: rag_node와 guardrail

```python
# app/graph/nodes.py — lines 187-205
async def rag_node(state: AgentState) -> dict:
    """질문 관련 문서 검색. 자료가 없거나 관련도가 낮으면 가드레일로 전환."""
    user_input = state["messages"][-1].content
    try:
        docs = await get_rag_repository().search_similar(
            user_input, k=5, category_l1=state.get("category_l1")
        )
    except Exception:
        docs = []

    top_score = docs[0]["score"] if docs else 0.0
    if not docs or top_score < config.GUARDRAIL_MIN_SCORE:
        # 자료로 답할 수 없음 → 질문 주제에 맞는 문의처를 찾아 안내
        return {
            "retrieved_docs": docs,
            "guardrail": True,
            "contact": match_contact(user_input),
        }
    return {"retrieved_docs": docs, "guardrail": False, "contact": None}
```

## 핵심 코드 6: tool_node, build_response_inputs, response_node

```python
# app/graph/nodes.py — lines 208-253
async def tool_node(state: AgentState) -> dict:
    """Router가 고른 도구 실행."""
    result = await tool_executor.execute(
        tool_name=state["tool_name"],
        tool_args=state["tool_args"] or {},
        session_id=state["session_id"],
    )
    return {"tool_result": result}

def build_response_inputs(state: AgentState) -> tuple[str, str]:
    """최종 응답 생성을 위한 system_prompt, user_input 생성."""
    user_input = state["messages"][-1].content
    intent = state["intent"]

    if intent == "rag" and state.get("guardrail"):
        contact_text = format_contact(state.get("contact"))
        system_prompt = f"{RESPONSE_PROMPT}\n\n{GUARDRAIL_GROUNDING.format(contact=contact_text)}"

    elif intent == "rag":
        context = "\n\n".join(
            f"[자료{i + 1}] {d['content']}" for i, d in enumerate(state["retrieved_docs"])
        ) or "(관련 자료 없음)"
        system_prompt = f"{RESPONSE_PROMPT}\n\n{RAG_GROUNDING.format(context=context)}"

    elif intent == "tool":
        tool_result = json.dumps(state["tool_result"], ensure_ascii=False)
        system_prompt = f"{RESPONSE_PROMPT}\n\n{TOOL_GROUNDING.format(tool_result=tool_result)}"

    else:
        system_prompt = RESPONSE_PROMPT

    return system_prompt, user_input

async def response_node(state: AgentState) -> dict:
    """intent별 그라운딩을 붙여 최종 응답 생성."""
    llm = get_llm()

    system_prompt, user_input = build_response_inputs(state)

    messages = [
        SystemMessage(content=system_prompt),
        HumanMessage(content=user_input),
    ]

    answer = await llm.ainvoke(messages)
    return {"messages": [AIMessage(content=answer.content)]}
```

---

# 6. Prompt 설계

## `app/core/prompts.py`

### 역할

- Router 프롬프트
- 최종 응답 페르소나
- RAG grounding 지시
- Tool 결과 grounding 지시
- Guardrail 문의처 안내 지시

## 핵심 코드 1: Router Prompt

```python
# app/core/prompts.py — lines 3-58
# ===== 의도 분류 (Router) =====
ROUTER_PROMPT = """
너는 가천대학교 인공지능학과 학사 안내 AI의 의도 분류기야.
사용자 메시지를 분석해서 아래 형식으로 분류해.

## 분류 기준 (기본값은 rag. 정보를 묻는 모든 질문은 rag로 보내라)
### chat (일반 대화) — 매우 좁게만
- 인사("안녕"), 감사, 순수 잡담, 서비스 사용법("뭘 도와줘?")
- 학교/학과/학사/기숙사/규정 등 '사실 정보'를 묻는 질문은 chat이 아니다.

### rag (정보 검색) — 정보성 질문 전부
- 교육목표, 과목 설명, 트랙 소개, 진로/경력, 졸업요건 설명
- 학사·학교생활·기숙사·규정·일정 등 무엇이든 '사실'을 묻는 질문
- 문의처·연락처·전화번호·"어디에 물어봐야 하는지"를 묻는 질문도 전부 rag
- 예: "인공지능학과 교육목표 알려줘", "머신러닝은 뭘 배워?", "전공필수 뭐가 있어?",
  "기숙사 벌점 기준 알려줘", "수강신청 언제야?", "국가장학금 어디에 문의해?",
  "장학금 연락처 알려줘" (자료 유무와 무관하게 rag로 분류)

### tool (도구 실행) — 계산/추천이 필요한 경우
- calc_graduation_progress: 사용자가 '이수 학점'을 말하며 졸업까지 남은 학점을 물을 때.
  아래 학점 필드 중 언급된 것을 채워라(숫자만).
  - major_credits: 전공(전공필수+전공선택 통합) 이수학점
  - major_required_credits / major_elective_credits: 전공필수 / 전공선택 이수학점
  - common_required_credits / common_elective_credits: 공통필수 / 공통선택 이수학점
- recommend_courses: 특정 학년/학기에 뭘 들어야 하는지 물을 때. 아래를 채워라.
  - grade: 학년(1~4 정수), semester: 학기(1 또는 2 정수)
  - track: 트랙(선택). 반드시 "Intelligent SW" | "AIoT" | "Vision & Language" | "AI부트캠프" 중 하나

## 카테고리 분류 (category_l1) — intent=rag 일 때만
질문이 아래 6개 중 어디에 속하는지 하나만 고른다. 애매하면 "none"(전체 검색).
- graduation: 졸업요건, 졸업학점, 전공/교양 이수기준, 외국어 졸업인증
- course: 수강신청·정정·포기, 과목/교육과정, 트랙·학년별 개설과목, 학점 정보
- academic_calendar: 개강·종강·시험·성적·수강신청 등 '날짜/일정'
- social_service: 사회봉사 이수기준·제출방법
- leave_return: 휴학, 복학
- contact: 학과사무실·문의처·연락처·전화번호를 묻는 질문
(chat/tool 이면 category_l1 은 null)

## 출력 필드
- intent: "chat" | "rag" | "tool" (필수)
- category_l1: 위 6개 중 하나 또는 "none" (intent=rag 아니면 "none")
- tool_name: intent=tool일 때 "calc_graduation_progress" | "recommend_courses", 아니면 null
- 위 도구 파라미터 필드: 해당될 때만 채우고 나머지는 비워둠(null)

## 예시
- "전공 30학점 들었는데 얼마 남았어?" -> intent=tool, tool_name=calc_graduation_progress, major_credits=30
- "2학년 2학기 뭐 들어야 해?" -> intent=tool, tool_name=recommend_courses, grade=2, semester=2
- "AIoT 트랙 3학년 1학기 과목 추천해줘" -> intent=tool, tool_name=recommend_courses, grade=3, semester=1, track="AIoT"
- "인공지능학과 교육목표 알려줘" -> intent=rag, category_l1=course
- "졸업하려면 몇 학점 필요해?" -> intent=rag, category_l1=graduation
- "휴학 어떻게 해?" -> intent=rag, category_l1=leave_return
- "수강신청 언제야?" -> intent=rag, category_l1=academic_calendar
- "학과 사무실 전화번호 알려줘" -> intent=rag, category_l1=contact

애매하면 rag로 분류해. 학점 계산/과목 추천처럼 '수치 처리'가 필요할 때만 tool.
"""
```

## 핵심 코드 2: Response / RAG / Tool / Guardrail Prompt

```python
# app/core/prompts.py — lines 60-104
# ===== 응답 생성 페르소나 =====
RESPONSE_PROMPT = """
너는 가천대학교 인공지능학과 학생을 돕는 학사 안내 AI야.
친근한 학과 선배 같은 말투로, 정확하고 간결하게 답해.
- 학교/학과/학사/기숙사/규정/일정 등 '사실'은 주어진 근거 자료가 있을 때만 답해.
  근거가 없으면 절대 지어내지 말고 "제 자료에서 확인되지 않습니다"라고 말한 뒤
  학과사무실·교무처 등 문의처 확인을 안내해. (벌점표·연락처·날짜 등을 임의로 만들지 마라)
- 학점/과목/졸업요건 등 정확성이 중요한 정보는 근거를 함께 밝혀.
"""

# ===== 그라운딩 지시 (근거 데이터 옆에 붙임) =====
RAG_GROUNDING = """
아래 [참고자료]에 있는 내용만 근거로 답해.
참고자료에 답이 없으면 딱 이렇게만 해:
  (1) "제 자료에서 확인되지 않습니다"라고 말하고,
  (2) 학과사무실·교무처 등 어디에 문의하면 되는지만 안내한다.
이때 일반 상식·추정 일정·예시 날짜·전화번호·이메일 등 근거 없는 정보는
절대 덧붙이지 마라(모르면 모른다고만 한다). 실제 자료에 있는 것만 말한다.

[참고자료]
{context}
"""

TOOL_GROUNDING = """
아래 [도구 실행 결과]를 근거로 사용자에게 답해.
결과의 숫자를 그대로 사용하고, 계산/추천 결과임을 명확히 전달해.
결과가 참고용임을 덧붙이고, 최종 확인은 학과사무실/공식 자료 기준임을 안내해.

[도구 실행 결과]
{tool_result}
"""

# ===== 가드레일 (자료에 없는 질문 → 문의처 안내) =====
GUARDRAIL_GROUNDING = """
사용자의 질문은 내가 가진 학사 자료로는 정확히 확인할 수 없는 내용이야.
절대 추측하거나 지어내지 말고(벌점 기준·날짜·규정 등을 만들지 마라), 아래 원칙대로만 답해:
  (1) "제 자료에서는 정확히 확인하기 어려워요"라고 솔직하게 먼저 말한다.
  (2) 아래 [문의처]에 있는 부서명과 전화번호를 그대로 안내한다.
      번호를 바꾸거나 없는 번호를 새로 만들지 마라. [문의처]에 있는 값만 쓴다.
  (3) 관련 링크가 있으면 함께 안내한다.
  (4) 친근한 학과 선배 말투로, 2~3문장 정도로 짧고 명확하게.

[문의처]
{contact}
"""
```

---

# 7. RAG Repository

## `app/repositories/rag.py`

### 역할

- LangGraph node와 실제 retrieval 로직 사이의 Repository 계층
- DB 연결 생성 및 종료 책임
- 동기 DB 검색 함수를 `asyncio.to_thread`로 비동기 흐름에 연결

```python
# app/repositories/rag.py
"""RAG 검색 리포지토리 (pgvector). 병합 시 이 구현만 Supabase로 교체하면 됨."""
import asyncio

from app import db, retrieval


class RagRepository:
    async def search_similar(
        self, query: str, k: int = 4, category_l1: str | None = None
    ) -> list[dict]:
        def _search():
            conn = db.connect()
            try:
                return retrieval.search(conn, query, k=k, category_l1=category_l1)
            finally:
                conn.close()

        return await asyncio.to_thread(_search)


_repo: RagRepository | None = None


def get_rag_repository() -> RagRepository:
    global _repo
    if _repo is None:
        _repo = RagRepository()
    return _repo
```

---

# 8. Retrieval 검색 로직

## `app/retrieval.py`

### 역할

- 사용자 query 확장
- query embedding 생성
- pgvector cosine similarity 검색
- category_l1 기반 필터 검색
- 검색 실패 시 전체 검색 fallback
- 중복 제거 후 reranker 적용

## 핵심 코드 1: query 정규화, 토큰화, 확장

```python
# app/retrieval.py — lines 1-52
"""pgvector 기반 RAG 검색 + 간단 키워드 보정."""
import re

from app import embeddings


SYNONYM_MAP = {
    "수강": ["수강신청", "예비수강신청", "수강정정", "수강과목포기"],
    "수강신청": ["예비수강신청", "수강정정", "수강학점"],
    "졸업": ["졸업요건", "졸업학점", "졸업인증", "외국어능력 졸업인증"],
    "졸업학점": ["졸업요건", "전공필수", "전공선택", "교양필수"],
    "복학": ["복학기간", "휴학연기", "학적변동"],
    "휴학": ["미등록휴학", "등록휴학", "휴학연기", "학기중휴학"],
    "사회봉사": ["봉사활동", "30시간", "P/F", "졸업인증"],
    "봉사": ["사회봉사", "봉사활동", "30시간"],
    "전과": ["전공변경", "전과신청기간"],
    "재입학": ["재입학신청기간", "제적", "퇴학"],
    "외국어": ["외국어능력 졸업인증", "국제어학원"],
}


def normalize(text: str) -> str:
    return re.sub(r"\s+", " ", text.lower()).strip()


def tokenize(text: str) -> list[str]:
    text = normalize(text)
    tokens = re.findall(r"[가-힣a-zA-Z0-9]+", text)

    stopwords = {
        "언제", "뭐야", "무엇", "어떻게", "알려줘", "궁금해",
        "관련", "대해", "좀", "나는", "제가", "하면", "되나요",
    }

    return [token for token in tokens if len(token) >= 2 and token not in stopwords]


def expand_query(query: str) -> str:
    expanded_terms = []

    for key, values in SYNONYM_MAP.items():
        if key in query:
            expanded_terms.extend(values)

    if not expanded_terms:
        return query

    return f"{query} {' '.join(expanded_terms)}"


def deduplicate_hits(hits: list[dict]) -> list[dict]:
    seen = set()
```

## 핵심 코드 2: 중복 제거와 SELECT 컬럼

```python
# app/retrieval.py — lines 54-73

    for hit in hits:
        key = (
            hit.get("source"),
            hit.get("page"),
            normalize(hit.get("content", ""))[:120],
        )

        if key in seen:
            continue

        seen.add(key)
        unique_hits.append(hit)

    return unique_hits


_SELECT_COLS = (
    "source, page, content, category_l1, priority, academic_year, keywords, "
    "1 - (embedding <=> %s::vector) AS vector_score"
```

## 핵심 코드 3: pgvector 후보 검색

```python
# app/retrieval.py — lines 76-105

def _fetch_candidates(conn, qlit: str, candidates: int, category_l1: str | None):
    """pgvector 유사도 상위 후보 조회. category_l1 지정 시 해당 카테고리로 필터.
    is_active=TRUE 문서만 대상으로 한다(멘토링 결과 §9)."""
    if category_l1:
        return conn.execute(
            f"""
            SELECT {_SELECT_COLS}
            FROM documents
            WHERE is_active = TRUE AND category_l1 = %s
            ORDER BY embedding <=> %s::vector
            LIMIT %s
            """,
            (qlit, category_l1, qlit, candidates),
        ).fetchall()
    return conn.execute(
        f"""
        SELECT {_SELECT_COLS}
        FROM documents
        WHERE is_active = TRUE
        ORDER BY embedding <=> %s::vector
        LIMIT %s
        """,
        (qlit, qlit, candidates),
    ).fetchall()


def search(
    conn,
    query: str,
```

## 핵심 코드 4: search 메인 함수

```python
# app/retrieval.py — lines 108-152
    category_l1: str | None = None,
) -> list[dict]:
    """질의와 가장 유사한 문서 청크 반환.

    1. query를 확장한다.
    2. pgvector로 후보 문서를 넉넉히 가져온다. (category_l1 지정 시 그 카테고리 안에서만)
       - 멘토 원칙: 카테고리로 검색 공간을 먼저 좁힌다.
       - 안전망: 카테고리 필터 결과가 비면 전체에서 다시 검색(오분류로 답을 놓치지 않도록).
    3. lightweight reranker(vector/keyword/category/priority/recency)로 재정렬한다.
    4. 중복 문서를 제거한다.
    """
    from app.services import reranker  # 지연 임포트(순환 방지)

    expanded_query = expand_query(query)
    qvec = embeddings.embed_query(expanded_query)

    qlit = "[" + ",".join(map(str, qvec)) + "]"

    rows = _fetch_candidates(conn, qlit, candidates, category_l1)
    used_category = category_l1
    if category_l1 and not rows:
        # 카테고리 필터로 아무것도 못 찾음 → 전체 검색으로 폴백
        rows = _fetch_candidates(conn, qlit, candidates, None)
        used_category = None

    hits = [
        {
            "source": row[0],
            "page": row[1],
            "content": row[2],
            "category_l1": row[3],
            "priority": row[4],
            "academic_year": row[5],
            "keywords": row[6],
            "vector_score": float(row[7]),
        }
        for row in rows
    ]

    hits = deduplicate_hits(hits)
    hits = reranker.rerank(query, used_category, hits)

    if hits:
        hits[0]["_filtered_by"] = used_category  # 디버깅: 어떤 카테고리로 필터했는지
    return hits[:k]
```

---

# 9. Lightweight Reranker

## `app/services/reranker.py`

### 역할

- pgvector가 가져온 후보 문서들을 5개 신호로 재정렬
- 사용 신호:
  - vector_score
  - keyword_score
  - category_score
  - priority_score
  - recency_score

```python
# app/services/reranker.py
"""Lightweight reranker (멘토링 결과 §8).

pgvector가 가져온 후보 문서들을 여러 신호를 조합해 다시 정렬한다.

final_score =
    vector_score   * 0.65
  + keyword_score  * 0.15
  + category_score * 0.10
  + priority_score * 0.05
  + recency_score  * 0.05

각 부분 점수는 0~1 로 정규화한다.
"""
from __future__ import annotations

from app import retrieval

W_VECTOR = 0.65
W_KEYWORD = 0.15
W_CATEGORY = 0.10
W_PRIORITY = 0.05
W_RECENCY = 0.05

# 최신성 기준 학년도. Date.now 미사용(환경 고정) — 데이터 최신 학년도에 맞춰 상수로 둔다.
LATEST_YEAR = 2026


def keyword_score(query: str, content: str, keywords: list[str] | None) -> float:
    """질문 토큰이 문서 content/keywords 에 얼마나 매칭되는지 (0~1)."""
    q_tokens = retrieval.tokenize(query)
    if not q_tokens:
        return 0.0
    haystack = retrieval.normalize(content)
    kw = {retrieval.normalize(k) for k in (keywords or [])}
    hit = 0
    for t in q_tokens:
        if t in haystack or t in kw:
            hit += 1
    return hit / len(q_tokens)


def priority_score(priority: int | None) -> float:
    """priority 1(핵심)=1.0, 2=0.6, 3+=0.3. (작을수록 중요)"""
    return {1: 1.0, 2: 0.6}.get(priority or 2, 0.3)


def recency_score(academic_year: int | None) -> float:
    """최신 학년도일수록 높게. 연도 없으면 중립 0.5."""
    if academic_year is None:
        return 0.5
    diff = LATEST_YEAR - academic_year
    if diff <= 0:
        return 1.0
    if diff == 1:
        return 0.7
    if diff == 2:
        return 0.5
    return 0.3


def category_score(predicted: str | None, doc_category: str | None) -> float:
    """router 예측 카테고리와 문서 카테고리 일치 시 1.0. 예측 없으면 중립 0.5."""
    if not predicted:
        return 0.5
    return 1.0 if predicted == doc_category else 0.0


def rerank(query: str, predicted_category: str | None, hits: list[dict]) -> list[dict]:
    """후보(hits)에 final_score 를 매기고 내림차순 정렬해 반환.

    각 hit 는 최소한 vector_score, content, category_l1, priority,
    academic_year, keywords 키를 가진다고 가정한다.
    """
    for h in hits:
        vs = float(h.get("vector_score", 0.0))
        ks = keyword_score(query, h.get("content", ""), h.get("keywords"))
        cs = category_score(predicted_category, h.get("category_l1"))
        ps = priority_score(h.get("priority"))
        rs = recency_score(h.get("academic_year"))
        h["keyword_score"] = ks
        h["category_score"] = cs
        h["priority_score"] = ps
        h["recency_score"] = rs
        h["score"] = (
            vs * W_VECTOR
            + ks * W_KEYWORD
            + cs * W_CATEGORY
            + ps * W_PRIORITY
            + rs * W_RECENCY
        )
    hits.sort(key=lambda item: item["score"], reverse=True)
    return hits
```

---

# 10. PostgreSQL + pgvector DB Schema

## `app/db.py`

### 역할

- PostgreSQL 연결
- pgvector extension 등록
- documents, courses, graduation_requirements 테이블 생성
- category, priority, academic_year 등 RAG metadata 저장 구조 정의

```python
# app/db.py
"""PostgreSQL + pgvector 연결 및 스키마."""
import psycopg
from pgvector.psycopg import register_vector

from app import config


def connect():
    """pgvector 등록된 psycopg 연결 반환."""
    conn = psycopg.connect(config.DATABASE_URL, autocommit=True)
    conn.execute("CREATE EXTENSION IF NOT EXISTS vector")
    register_vector(conn)
    return conn


def init_schema(conn):
    """RAG 문서/과목/졸업요건 테이블 생성."""
    dim = config.EMBED_DIM
    conn.execute(
        f"""
        CREATE TABLE IF NOT EXISTS documents (
            id            BIGSERIAL PRIMARY KEY,
            source        TEXT NOT NULL,
            page          INT,
            category      TEXT,
            category_l1   TEXT,
            category_l2   TEXT,
            keywords      TEXT[],
            priority      INTEGER DEFAULT 2,
            academic_year INTEGER,
            semester      TEXT,
            is_active     BOOLEAN DEFAULT TRUE,
            content       TEXT NOT NULL,
            metadata      JSONB DEFAULT '{{}}'::jsonb,
            embedding     VECTOR({dim})
        )
        """
    )
    # 기존 DB(컬럼 없이 생성된 경우) 대응: 컬럼을 안전하게 추가한다. (멘토링 결과 §7)
    conn.execute("ALTER TABLE documents ADD COLUMN IF NOT EXISTS category_l1 TEXT")
    conn.execute("ALTER TABLE documents ADD COLUMN IF NOT EXISTS category_l2 TEXT")
    conn.execute("ALTER TABLE documents ADD COLUMN IF NOT EXISTS keywords TEXT[]")
    conn.execute("ALTER TABLE documents ADD COLUMN IF NOT EXISTS priority INTEGER DEFAULT 2")
    conn.execute("ALTER TABLE documents ADD COLUMN IF NOT EXISTS academic_year INTEGER")
    conn.execute("ALTER TABLE documents ADD COLUMN IF NOT EXISTS semester TEXT")
    conn.execute("ALTER TABLE documents ADD COLUMN IF NOT EXISTS is_active BOOLEAN DEFAULT TRUE")
    # 필터·정렬용 인덱스
    conn.execute("CREATE INDEX IF NOT EXISTS idx_documents_category ON documents (category_l1, category_l2)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_documents_active ON documents (is_active)")
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS courses (
            id            BIGSERIAL PRIMARY KEY,
            교과목명       TEXT NOT NULL,
            이수구분       TEXT,
            학점          INT,
            이론          INT,
            실습          INT,
            개설학년       TEXT,
            개설학기       TEXT,
            트랙          TEXT,
            교육과정_연도   INT
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS graduation_requirements (
            id            BIGSERIAL PRIMARY KEY,
            교육과정_연도   INT,
            data          JSONB NOT NULL
        )
        """
    )
    # 주의: pgvector HNSW/IVFFlat 인덱스는 최대 2000차원까지만 지원한다.
    # Upstage 임베딩은 4096차원이고 문서 수가 적으므로, 인덱스 없이
    # 정확(exact) 코사인 검색(<=>)을 사용한다. (데이터가 커지면 halfvec 전환 고려)
```

---

# 11. 데이터 적재 Pipeline

## `app/ingest.py`

### 역할

- `output/parsed/*.md` 문서를 chunk로 분할
- `_crawl_manifest.json` 또는 Markdown 헤더에서 category_l1/category_l2 파싱
- Upstage embedding 생성
- PostgreSQL documents 테이블에 embedding과 metadata 저장
- course_catalog, graduation_requirements 정형 데이터 적재
- 정형 데이터를 자연어 문서로 합성해 RAG에도 함께 적재

## 핵심 코드 1: 문서 metadata 생성

```python
# app/ingest.py — lines 21-35
def doc_meta(source: str, content: str, cat_l2: str | None,
             cat_l1: str | None = None) -> dict:
    """reranker 용 메타 계산: priority, academic_year, semester, keywords."""
    priority = _PRIORITY_BY_L2.get(cat_l2 or "", 2)
    # 학년도는 '제목'에서만 추출한다. 본문 연도(예: 2015학번, 2022.06.04)는
    # 문서의 학년도가 아니라 오탐이므로 쓰지 않는다.
    ym = re.search(r"20\d{2}", source)
    academic_year = int(ym.group()) if ym else None
    sm = re.search(r"([1-2])\s*학기", source)
    semester = f"{sm.group(1)}학기" if sm else None
    # 키워드: 제목 토큰 + 카테고리명 (질문-문서 매칭 보조)
    kws = retrieval.tokenize(source) + [c for c in (cat_l1, cat_l2) if c]
    keywords = list(dict.fromkeys(kws))  # 중복 제거, 순서 유지
    return {"priority": priority, "academic_year": academic_year,
            "semester": semester, "keywords": keywords}
```

## 핵심 코드 2: category 파싱

```python
# app/ingest.py — lines 38-64
MANIFEST = config.PARSED_DIR / "_crawl_manifest.json"
_CATEGORY_HEADER = re.compile(r"^>\s*카테고리:\s*([A-Za-z_]+)\s*/\s*([A-Za-z_]+)", re.M)


def load_json(path):
    return json.loads(path.read_text(encoding="utf-8"))


def load_category_map() -> dict[str, tuple[str, str]]:
    """_crawl_manifest.json → {source: (category_l1, category_l2)}."""
    if not MANIFEST.exists():
        return {}
    out = {}
    for m in load_json(MANIFEST):
        if m.get("category_l1"):
            out[m["source"]] = (m["category_l1"], m.get("category_l2"))
    return out


def category_for(source: str, md: str, cat_map: dict) -> tuple[str | None, str | None]:
    """카테고리 결정: manifest 우선, 없으면 .md 헤더의 `> 카테고리: l1/l2` 파싱."""
    if source in cat_map:
        return cat_map[source]
    m = _CATEGORY_HEADER.search(md)
    if m:
        return m.group(1), m.group(2)
    return None, None
```

## 핵심 코드 3: Markdown chunk 분할

```python
# app/ingest.py — lines 67-89
def chunk_markdown(md: str) -> list[str]:
    """빈 줄 기준 블록 → 목표 길이로 병합. 표(| ... |)는 연속 유지."""
    blocks, cur = [], []
    for line in md.splitlines():
        if line.strip() == "":
            if cur:
                blocks.append("\n".join(cur))
                cur = []
        else:
            cur.append(line)
    if cur:
        blocks.append("\n".join(cur))

    chunks, buf = [], ""
    for b in blocks:
        if len(buf) + len(b) + 1 <= CHUNK_TARGET or len(buf) < CHUNK_MIN:
            buf = (buf + "\n" + b).strip()
        else:
            chunks.append(buf)
            buf = b
    if buf:
        chunks.append(buf)
    return [c for c in chunks if c.strip()]
```

## 핵심 코드 4: documents 적재

```python
# app/ingest.py — lines 92-115
def ingest_documents(conn, source: str, cat_map: dict | None = None):
    """파싱 마크다운을 청킹·임베딩하여 documents에 적재. 카테고리(l1/l2)도 함께 저장."""
    md_path = config.PARSED_DIR / f"{source}.md"
    md = md_path.read_text(encoding="utf-8")
    cat_l1, cat_l2 = category_for(source, md, cat_map or {})
    chunks = chunk_markdown(md)
    tag = f"{cat_l1}/{cat_l2}" if cat_l1 else "미분류"
    print(f"[documents] {source} [{tag}]: {len(chunks)}개 청크 임베딩...")

    vectors = embeddings.embed_passages(chunks)
    with conn.cursor() as cur:
        for content, emb in zip(chunks, vectors):
            m = doc_meta(source, content, cat_l2, cat_l1)
            meta = {"source": source, "category_l1": cat_l1, "category_l2": cat_l2,
                    "priority": m["priority"], "academic_year": m["academic_year"]}
            cur.execute(
                "INSERT INTO documents "
                "(source, category_l1, category_l2, keywords, priority, "
                " academic_year, semester, content, metadata, embedding) "
                "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)",
                (source, cat_l1, cat_l2, m["keywords"], m["priority"],
                 m["academic_year"], m["semester"], content, json.dumps(meta), emb),
            )
    print(f"[documents] {source}: {len(chunks)}건 적재 완료 (dim={len(vectors[0])})")
```

## 핵심 코드 5: 전체 Markdown 문서 적재

```python
# app/ingest.py — lines 118-138
def ingest_all_documents(conn):
    """output/parsed/ 안의 모든 *.md 를 RAG 문서로 적재.
    팀원은 자기 문서를 parse_pdf.py로 파싱해 .md만 넣으면 자동 포함된다."""
    md_files = sorted(config.PARSED_DIR.glob("*.md"))
    if not md_files:
        print("[documents] output/parsed/*.md 없음 — 건너뜀")
        return
    cat_map = load_category_map()
    uncategorized = []
    for md_path in md_files:
        source = md_path.stem
        ingest_documents(conn, source, cat_map)
        if source not in cat_map and not _CATEGORY_HEADER.search(
            md_path.read_text(encoding="utf-8")
        ):
            uncategorized.append(source)
    if uncategorized:
        print(
            "[documents] [주의] 카테고리 미분류(NULL로 적재됨, manifest/헤더에 추가 필요): "
            + ", ".join(uncategorized)
        )
```

## 핵심 코드 6: 정형 데이터 합성 및 RAG 적재

```python
# app/ingest.py — lines 174-247
def synthesize_structured_docs(conn):
    """정형 카탈로그/졸업요건을 '깨끗한 자연어 문서'로 합성해 RAG에 적재.
    2단 인터리빙 표에서 오는 부정확성을 제거하고 과목/학점 질의 정확도를 높인다."""
    from collections import defaultdict

    catalog = load_json(config.STRUCTURED_DIR / "course_catalog.json")
    grad = load_json(config.STRUCTURED_DIR / "graduation_requirements.json")
    SRC = "2026 인공지능학과 교육과정(정형)"
    docs: list[str] = []

    # A) 과목별 사실 문서
    for c in catalog:
        docs.append(
            f"[교육과정] '{c['교과목명']}'은(는) 가천대 인공지능학과 {c['트랙']} 트랙 "
            f"{_when(c)} 개설 {c['이수구분']} 과목이며 {c['학점']}학점"
            f"(이론 {c['이론']}, 실습 {c['실습']})이다."
        )

    # B) 공통 트랙 (학년,학기)별 개설 과목 (이수구분 묶음)
    grp = defaultdict(lambda: defaultdict(list))
    for c in catalog:
        if c["트랙"] == "공통" and isinstance(c["개설학기"], int):
            grp[(c["개설학년"], c["개설학기"])][c["이수구분"]].append(c["교과목명"])
    for (yr, sem), gubuns in sorted(grp.items()):
        parts = "; ".join(f"{g}: {', '.join(ns)}" for g, ns in gubuns.items())
        docs.append(f"[교육과정] 인공지능학과 {yr}학년 {sem}학기 개설 과목 — {parts}.")

    # C) 트랙별 과목 목록
    for trk in ["Intelligent SW", "AIoT", "Vision & Language", "AI부트캠프"]:
        items = [f"{c['교과목명']}({_when(c)})" for c in catalog if c["트랙"] == trk]
        if items:
            docs.append(f"[교육과정] 인공지능학과 {trk} 트랙 과목: " + ", ".join(items) + ".")

    # D) 이수구분별 전체 목록
    for g in ["전공필수", "전공선택", "공통필수"]:
        names = [c["교과목명"] for c in catalog if c["이수구분"] == g]
        docs.append(
            f"[교육과정] 인공지능학과 {g} 과목 전체({len(names)}과목): " + ", ".join(names) + "."
        )

    # E) 졸업요건
    req = grad["이수구분별_최소학점"]
    docs.append(
        f"[졸업요건] {grad['교육과정_연도']} 가천대 인공지능학과 졸업 이수학점은 총 "
        f"{grad['총_졸업학점']}학점이다. 전공필수 {req['전공필수']}학점, 전공선택 {req['전공선택']}학점, "
        f"공통필수 {req['공통필수']}학점, 공통선택 {req['공통선택']}학점을 이수해야 한다. "
        f"전공(전공필수+전공선택)은 {req['전공필수'] + req['전공선택']}학점이다."
    )

    print(f"[synth] 정형 문서 {len(docs)}건 임베딩...")
    vectors = embeddings.embed_passages(docs)
    with conn.cursor() as cur:
        for content, emb in zip(docs, vectors):
            # 접두어로 카테고리 부여: [교육과정]→course/curriculum, [졸업요건]→graduation/credit_requirement
            if content.startswith("[졸업요건]"):
                cat_l1, cat_l2 = "graduation", "credit_requirement"
            else:
                cat_l1, cat_l2 = "course", "curriculum"
            m = doc_meta(SRC, content, cat_l2, cat_l1)
            # 졸업요건(기준)은 핵심 근거 → priority 1. 교육과정 목록은 기본(2).
            if cat_l2 == "credit_requirement":
                m["priority"] = 1
            meta = {"source": SRC, "kind": "structured",
                    "category_l1": cat_l1, "category_l2": cat_l2,
                    "priority": m["priority"], "academic_year": m["academic_year"]}
            cur.execute(
                "INSERT INTO documents "
                "(source, category_l1, category_l2, keywords, priority, "
                " academic_year, semester, content, metadata, embedding) "
                "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)",
                (SRC, cat_l1, cat_l2, m["keywords"], m["priority"],
                 m["academic_year"], m["semester"], content, json.dumps(meta), emb),
            )
    print(f"[synth] {len(docs)}건 적재 완료")
```

## 핵심 코드 7: 재적재 main

```python
# app/ingest.py — lines 250-269
def main():
    conn = db.connect()
    db.init_schema(conn)

    # 재적재를 위해 초기화 (idempotent)
    conn.execute("TRUNCATE documents, courses, graduation_requirements RESTART IDENTITY")

    ingest_courses(conn)
    ingest_graduation(conn)
    synthesize_structured_docs(conn)
    ingest_all_documents(conn)

    n_doc = conn.execute("SELECT count(*) FROM documents").fetchone()[0]
    n_course = conn.execute("SELECT count(*) FROM courses").fetchone()[0]
    print(f"\n✅ 적재 완료 — documents={n_doc}, courses={n_course}")
    conn.close()


if __name__ == "__main__":
    main()
```

---

# 12. Upstage Embedding / LLM Client

## `app/embeddings.py`

### 역할

- 문서 적재용 passage embedding 생성
- 사용자 질문 검색용 query embedding 생성

```python
# app/embeddings.py
"""Upstage 임베딩 클라이언트 (OpenAI 호환)."""
from openai import OpenAI

from app import config

_client = OpenAI(api_key=config.UPSTAGE_API_KEY, base_url=config.UPSTAGE_BASE_URL)


def embed_passages(texts: list[str]) -> list[list[float]]:
    """문서(passage) 임베딩. 적재용."""
    if not texts:
        return []
    resp = _client.embeddings.create(model=config.EMBED_MODEL_PASSAGE, input=texts)
    return [d.embedding for d in resp.data]


def embed_query(text: str) -> list[float]:
    """질의(query) 임베딩. 검색용."""
    resp = _client.embeddings.create(model=config.EMBED_MODEL_QUERY, input=[text])
    return resp.data[0].embedding
```

---

## `app/llm.py`

### 역할

- Solar LLM 일반 채팅 호출
- Solar LLM streaming 호출
- SSE에서 token 단위 출력에 사용

```python
# app/llm.py
"""Upstage Solar LLM 클라이언트."""
from collections.abc import Iterator

from openai import OpenAI

from app import config

_client = OpenAI(api_key=config.UPSTAGE_API_KEY, base_url=config.UPSTAGE_BASE_URL)


def chat(messages: list[dict], temperature: float = 0.2) -> str:
    """Solar 채팅 완성. messages=[{role, content}, ...]"""
    resp = _client.chat.completions.create(
        model=config.LLM_MODEL,
        messages=messages,
        temperature=temperature,
    )
    return resp.choices[0].message.content

def chat_stream(messages: list[dict], temperature: float = 0.2) -> Iterator[str]:
    """Solar 채팅 응답을 토큰 단위로 스트리밍."""
    stream = _client.chat.completions.create(
        model=config.LLM_MODEL,
        messages=messages,
        temperature=temperature,
        stream=True,
    )

    for chunk in stream:
        if not chunk.choices:
            continue

        delta = chunk.choices[0].delta
        content = getattr(delta, "content", None)

        if content:
            yield content
```

---

# 13. Tool 실행 구조

## `app/tools/executor.py`

### 역할

- Router가 선택한 tool을 실행
- 졸업학점 계산 Tool
- 학년/학기 기반 과목 추천 Tool
- Tool 결과를 `{success, data}` 또는 `{success, error}` 형태로 반환

```python
# app/tools/executor.py
"""Tool 실행기. Router가 고른 도구를 실행하고 {success, data|error}를 반환."""
import asyncio
from typing import Any

from app.repositories.academic import AcademicRepository

# 계열기초(None) 제외한 학점 계산 대상
_CATS = ["전공필수", "전공선택", "공통필수", "공통선택"]


class ToolExecutor:
    def __init__(self):
        self.academic = AcademicRepository()

    async def execute(self, tool_name: str, tool_args: dict, session_id: str | None = None) -> dict[str, Any]:
        args = tool_args or {}
        try:
            match tool_name:
                case "calc_graduation_progress":
                    return await asyncio.to_thread(self._calc_graduation, args)
                case "recommend_courses":
                    return await asyncio.to_thread(self._recommend_courses, args)
                case _:
                    return {"success": False, "error": f"알 수 없는 도구: {tool_name}"}
        except Exception as e:  # noqa: BLE001
            return {"success": False, "error": str(e)}

    # --- calc_graduation_progress ---
    def _calc_graduation(self, args: dict) -> dict:
        req = self.academic.get_graduation_requirements()
        mins = req["이수구분별_최소학점"]
        전공_필요 = mins["전공필수"] + mins["전공선택"]

        이수: dict[str, int] = {}
        남은: dict[str, int] = {}

        # 전공(전공필수+전공선택 통합)으로 물은 경우
        if args.get("전공") is not None:
            done = int(args["전공"])
            이수["전공"] = done
            남은["전공"] = max(0, 전공_필요 - done)

        # 세부 이수구분
        for k in _CATS:
            if args.get(k) is not None:
                done = int(args[k])
                이수[k] = done
                남은[k] = max(0, mins[k] - done)

        if not 이수:
            return {
                "success": False,
                "error": "이수 학점 정보가 필요합니다. 예: '전공 30학점 들었어'",
            }

        return {
            "success": True,
            "data": {
                "기준": {"총_졸업학점": req["총_졸업학점"], "전공_필요": 전공_필요, **mins},
                "이수": 이수,
                "남은": 남은,
                "출처": f"{req['교육과정_연도']} 인공지능학과 졸업요건",
            },
        }

    # --- recommend_courses ---
    def _recommend_courses(self, args: dict) -> dict:
        학년, 학기, 트랙 = args.get("학년"), args.get("학기"), args.get("트랙")
        if not 학년 or not 학기:
            return {"success": False, "error": "학년과 학기 정보가 필요합니다."}
        courses = self.academic.recommend_courses(int(학년), int(학기), 트랙)
        if not courses:
            return {
                "success": False,
                "error": f"{학년}학년 {학기}학기 개설 과목을 찾지 못했습니다.",
            }
        return {
            "success": True,
            "data": {
                "학년": 학년,
                "학기": 학기,
                "트랙": 트랙 or "전체",
                "과목수": len(courses),
                "과목": courses,
                "출처": "2026 인공지능학과 교육과정",
            },
        }
```

---

# 14. 정형 데이터 Repository

## `app/repositories/academic.py`

### 역할

- courses 테이블에서 학년/학기별 과목 조회
- graduation_requirements.json에서 졸업요건 조회

```python
# app/repositories/academic.py
"""학사 정형 데이터 접근 (courses / graduation_requirements)."""
import json

from app import config, db


class AcademicRepository:
    def recommend_courses(self, 학년: int, 학기: int, 트랙: str | None = None) -> list[dict]:
        """해당 학년/학기 개설 과목. 트랙 지정 시 공통+해당트랙만."""
        conn = db.connect()
        try:
            sql = (
                "SELECT 교과목명, 이수구분, 학점, 트랙 FROM courses "
                "WHERE 개설학년 = %s AND 개설학기 = %s"
            )
            params: list = [str(학년), str(학기)]
            if 트랙:
                sql += " AND 트랙 IN ('공통', %s)"
                params.append(트랙)
            sql += " ORDER BY 이수구분, 교과목명"
            rows = conn.execute(sql, params).fetchall()
            return [
                {"교과목명": r[0], "이수구분": r[1], "학점": r[2], "트랙": r[3]} for r in rows
            ]
        finally:
            conn.close()

    def get_graduation_requirements(self) -> dict:
        """졸업 이수학점 기준 (정형 JSON = 신뢰 원본)."""
        path = config.STRUCTURED_DIR / "graduation_requirements.json"
        return json.loads(path.read_text(encoding="utf-8"))
```

---

## `app/repositories/contacts.py`

### 역할

- RAG 검색 실패 또는 guardrail 상황에서 문의처 안내
- 질문 키워드와 contacts.json을 매칭하여 부서, 전화번호, 관련 링크 반환
- LLM에 전달할 문의처 grounding text 생성

## 핵심 코드 1: 문의처 매칭

```python
# app/repositories/contacts.py — lines 1-64
"""문의처/링크 정형 데이터 접근 + 질문 키워드 매칭 (가드레일 안내용).

RAG로 답을 못 찾은 질문에 대해, 질문 주제에 맞는 부서 연락처/공식 링크를
찾아 안내 문구의 근거로 제공한다. 모든 값은 contacts.json의 실제값을 사용하며
임의 생성하지 않는다.
"""
import json
import re
from functools import lru_cache

from app import config


@lru_cache(maxsize=1)
def _load() -> dict:
    path = config.STRUCTURED_DIR / "contacts.json"
    return json.loads(path.read_text(encoding="utf-8"))


def _kw_hits(query: str, keywords: list[str]) -> int:
    """질문 문자열에 포함된 키워드 개수."""
    q = query.lower()
    return sum(1 for kw in keywords if kw and kw.lower() in q)


def _tokens(text: str) -> set[str]:
    return {t for t in re.findall(r"[가-힣a-zA-Z0-9]+", text.lower()) if len(t) >= 2}


def _best_task(query: str, dept: dict) -> dict | None:
    """담당별 업무 중 질문과 토큰이 가장 많이 겹치는 항목."""
    qtokens = _tokens(query)
    best, best_score = None, 0
    for task in dept.get("담당별", []):
        score = len(qtokens & _tokens(task.get("업무", "")))
        if score > best_score:
            best, best_score = task, score
    return best


def match_contact(query: str) -> dict:
    """질문과 키워드가 가장 많이 겹치는 부서를 찾아 안내용 dict 반환.

    매칭 실패 시 기본안내(폴백)를 반환한다.
    """
    data = _load()

    best_dept, best_score = None, 0
    for dept in data["부서"]:
        s = _kw_hits(query, dept.get("키워드", []))
        if s > best_score:
            best_dept, best_score = dept, s

    links = [l for l in data["링크"] if _kw_hits(query, l.get("키워드", []))][:2]

    if best_dept is None:
        base = data.get("기본안내", {})
        return {
            "matched": False,
            "부서": None,
            "문구": base.get("문구"),
            "홈페이지": base.get("홈페이지"),
            "링크": links,
        }
```

## 핵심 코드 2: 문의처 format

```python
# app/repositories/contacts.py — lines 66-116
    return {
        "matched": True,
        "부서": best_dept["이름"],
        "대표전화": best_dept.get("대표전화"),
        "담당": _best_task(query, best_dept),  # {"업무","전화"} | None
        "담당별": best_dept.get("담당별", []),
        "홈페이지": best_dept.get("홈페이지"),
        "출처URL": best_dept.get("출처URL"),
        "링크": links,
    }


def contact_phone(c: dict) -> str | None:
    """안내에 쓸 대표 전화번호 (담당 매칭 우선 → 대표전화)."""
    if not c or not c.get("matched"):
        return None
    담당 = c.get("담당")
    if 담당 and 담당.get("전화"):
        return 담당["전화"]
    return c.get("대표전화")


def format_contact(c: dict) -> str:
    """match_contact 결과를 LLM 그라운딩용 텍스트 블록으로 변환."""
    if not c or not c.get("matched"):
        base = (c.get("문구") if c else None) or (
            "학과사무실(인공지능학과 031-750-8668) 또는 교무처 학사지원팀(031-750-5045)으로 문의해 주세요."
        )
        lines = [base]
        for l in (c.get("링크", []) if c else []):
            lines.append(f"관련 링크 - {l['이름']}: {l['URL']}")
        home = c.get("홈페이지") if c else None
        if home:
            lines.append(f"학교 홈페이지: {home}")
        return "\n".join(lines)

    lines = [f"부서: {c['부서']}"]
    담당 = c.get("담당")
    if 담당 and 담당.get("전화"):
        lines.append(f"담당({담당['업무']}): {담당['전화']}")
    elif c.get("대표전화"):
        lines.append(f"전화: {c['대표전화']}")
    else:
        # 대표전화가 없는 부서(예: 장학복지팀)는 업무별 번호를 안내
        for t in c.get("담당별", []):
            lines.append(f"- {t['업무']}: {t['전화']}")
    if c.get("홈페이지"):
        lines.append(f"홈페이지: {c['홈페이지']}")
    for l in c.get("링크", []):
        lines.append(f"관련 링크 - {l['이름']}: {l['URL']}")
    return "\n".join(lines)
```

---

# 15. Frontend SSE 처리

## `app/static/chat.js`

### 역할

- 사용자 메시지 UI 추가
- `/api/chat/stream` 호출
- SSE stream reader로 `status`, `meta`, `delta`, `done`, `error` 이벤트 처리
- delta 이벤트를 채팅 말풍선에 누적 출력
- sources를 답변 하단에 표시

## 핵심 코드 1: 메시지 UI 생성

```javascript
# app/static/chat.js — lines 1-120
const chatForm = document.getElementById("chat-form");
const messageInput = document.getElementById("message-input");
const chatBox = document.getElementById("chat-box");
const sendButton = document.getElementById("send-button");
const quickQuestions = document.querySelectorAll(".quick-question");

let loadingMessage = null;
let isSending = false;

if (!chatForm || !messageInput || !chatBox || !sendButton) {
    console.error("필수 DOM 요소를 찾지 못했습니다.", {
        chatForm,
        messageInput,
        chatBox,
        sendButton,
    });
}

function setControlsDisabled(disabled) {
    sendButton.disabled = disabled;
    messageInput.disabled = disabled;

    quickQuestions.forEach((btn) => {
        btn.disabled = disabled;
    });
}

function nowText() {
    const now = new Date();
    return now.toLocaleTimeString("ko-KR", {
        hour: "2-digit",
        minute: "2-digit",
    });
}

function scrollToBottom() {
    chatBox.scrollTop = chatBox.scrollHeight;
}

function createMessageElement(sender) {
    const messageDiv = document.createElement("div");
    messageDiv.classList.add("message");

    if (sender === "user") {
        messageDiv.classList.add("user-message");
    } else {
        messageDiv.classList.add("bot-message");
    }

    return messageDiv;
}

function createBotAvatar() {
    const avatar = document.createElement("img");
    avatar.src = "/static/img/mascot.png";
    avatar.alt = "가천이";
    avatar.classList.add("avatar");
    return avatar;
}

function addUserMessage(text) {
    const messageDiv = createMessageElement("user");

    const wrap = document.createElement("div");
    wrap.classList.add("bubble-wrap");

    const bubble = document.createElement("div");
    bubble.classList.add("bubble");
    bubble.textContent = text;

    const time = document.createElement("span");
    time.classList.add("timestamp");
    time.textContent = nowText();

    wrap.appendChild(bubble);
    wrap.appendChild(time);
    messageDiv.appendChild(wrap);
    chatBox.appendChild(messageDiv);
    scrollToBottom();
}

function addBotMessage(text, options = {}) {
    const messageDiv = createMessageElement("bot");
    messageDiv.appendChild(createBotAvatar());

    const wrap = document.createElement("div");
    wrap.classList.add("bubble-wrap");

    const bubble = document.createElement("div");
    bubble.classList.add("bubble");
    bubble.textContent = text;

    wrap.appendChild(bubble);

    if (options.sources && options.sources.length > 0) {
        appendSources(wrap, options.sources);
    }

    const time = document.createElement("span");
    time.classList.add("timestamp");
    time.textContent = nowText();
    wrap.appendChild(time);

    messageDiv.appendChild(wrap);
    chatBox.appendChild(messageDiv);
    scrollToBottom();

    return messageDiv;
}

function createStreamingBotMessage() {
    const messageDiv = createMessageElement("bot");
    messageDiv.appendChild(createBotAvatar());

    const wrap = document.createElement("div");
    wrap.classList.add("bubble-wrap");

    const bubble = document.createElement("div");
    bubble.classList.add("bubble");
    bubble.textContent = "질문을 분석하는 중이에요.";
```

## 핵심 코드 2: SSE 요청 및 이벤트 처리

```javascript
# app/static/chat.js — lines 148-233

function hideLoading() {
    if (loadingMessage) {
        loadingMessage.remove();
        loadingMessage = null;
    }
}

async function sendMessage(message) {
    const trimmed = message.trim();

    if (!trimmed || isSending) {
        return;
    }

    isSending = true;
    setControlsDisabled(true);

    addUserMessage(trimmed);
    messageInput.value = "";

    const { wrap, bubble } = createStreamingBotMessage();

    let meta = null;
    let buffer = "";
    let hasStartedAnswer = false;
    let hasFinished = false;

    try {
        const response = await fetch("/api/chat/stream", {
            method: "POST",
            headers: {
                "Content-Type": "application/json",
            },
            body: JSON.stringify({ message: trimmed }),
        });

        if (!response.ok || !response.body) {
            throw new Error("스트리밍 응답 오류");
        }

        const reader = response.body.getReader();
        const decoder = new TextDecoder("utf-8");

        while (true) {
            const { value, done } = await reader.read();

            if (done) {
                break;
            }

            buffer += decoder.decode(value, { stream: true });

            const events = buffer.split("\n\n");
            buffer = events.pop();

            for (const rawEvent of events) {
                const parsed = parseSseEvent(rawEvent);

                if (!parsed) {
                    continue;
                }

                if (parsed.event === "status") {
                    if (!hasStartedAnswer) {
                        bubble.textContent = parsed.data.message || "처리 중이에요.";
                    }
                }

                if (parsed.event === "meta") {
                    meta = parsed.data;
                    bubble.textContent = "";
                }

                if (parsed.event === "delta") {
                    if (!hasStartedAnswer) {
                        bubble.textContent = "";
                        hasStartedAnswer = true;
                    }

                    bubble.textContent += parsed.data.text || "";
                    scrollToBottom();
                }

                if (parsed.event === "error") {
                    bubble.textContent = parsed.data.message || "스트리밍 중 오류가 발생했어요.";
```

## 핵심 코드 3: SSE parser

```javascript
# app/static/chat.js — lines 234-267
                    hasFinished = true;
                }

                if (parsed.event === "done") {
                    if (meta && meta.sources && meta.sources.length > 0) {
                        appendSources(wrap, meta.sources);
                    }

                    appendTimestampOnce(wrap);
                    hasFinished = true;
                    scrollToBottom();
                }
            }
        }

        if (!hasFinished) {
            appendTimestampOnce(wrap);
        }
    } catch (error) {
        bubble.textContent = "오류가 발생했어요. 서버 상태, DB 연결, API Key를 확인해주세요.";
        appendTimestampOnce(wrap);
        console.error(error);
    } finally {
        isSending = false;
        setControlsDisabled(false);
        messageInput.focus();
    }
}

function parseSseEvent(rawEvent) {
    const lines = rawEvent.split("\n");

    let event = "message";
    const dataLines = [];
```

---

# 16. Docker Compose

## `docker-compose.yml`

### 역할

- PostgreSQL + pgvector DB 컨테이너 실행
- 로컬 개발 DB 환경 통일
- healthcheck로 DB 준비 상태 확인

```yaml
# docker-compose.yml
name: gachon_ai

services:
  db:
    image: pgvector/pgvector:pg16
    container_name: gachon_ai_db
    environment:
      POSTGRES_USER: postgres
      POSTGRES_PASSWORD: postgres
      POSTGRES_DB: gachon_ai
    ports:
      - "5432:5432"
    volumes:
      - pgdata:/var/lib/postgresql/data
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U postgres -d gachon_ai"]
      interval: 5s
      timeout: 5s
      retries: 10

volumes:
  pgdata:
```

---

### 17. Python Dependencies

## `pyproject.toml` · `uv sync` · `uv sync --extra dev`

### 역할

이 프로젝트는 `requirements.txt` 대신 `pyproject.toml`과 `uv.lock`을 기준으로 Python 의존성을 관리한다.

- `uv sync`: 운영 및 실행에 필요한 기본 의존성 설치
- `uv sync --extra dev`: 테스트, lint, pre-commit 등 개발용 의존성까지 설치

### 주요 의존성

#### Web Framework

- `fastapi`: API 서버 구현
- `uvicorn[standard]`: ASGI 서버 실행
- `jinja2`: HTML 템플릿 기반 UI 렌더링
- `python-multipart`: Form/File 요청 처리 지원

#### Agent Workflow

- `langgraph`: Agent workflow 구성
- `langchain-core`: LangChain 메시지 및 기본 인터페이스
- `langchain-upstage`: Upstage Solar LLM 연동

#### LLM / Embedding

- `openai`: Upstage OpenAI-compatible API 호출
- `httpx`: HTTP 요청 처리

#### Database

- `psycopg[binary]`: PostgreSQL 연결 드라이버
- `pgvector`: PostgreSQL pgvector 타입 연동

> PostgreSQL과 pgvector DB 자체는 Python 패키지가 아니라 Docker Compose의 DB 서비스로 실행한다.

#### Configuration

- `python-dotenv`: `.env` 파일 로드
- `pydantic`: 데이터 검증
- `pydantic-settings`: 환경변수 기반 설정 관리

#### External Action Tool

- `resend`: Resend API 기반 이메일 리마인드 PoC 및 확장용

#### Development / CI

`uv sync --extra dev` 실행 시 설치된다.

- `pytest`: 테스트 실행
- `pytest-asyncio`: 비동기 테스트 지원
- `pytest-cov`: 테스트 커버리지 확인
- `ruff`: lint 및 format 검사
- `pre-commit`: 커밋 전 자동 코드 품질 검사

### 실행 명령어

```bash
uv sync

# 18. 현재 코드 기준 핵심 포인트

## 구현된 핵심 기능

```text
1. FastAPI 기반 API 서버
2. LangGraph 기반 Agent Workflow
3. PostgreSQL + pgvector 기반 RAG 검색
4. Upstage Embedding / Solar LLM 연동
5. SSE 기반 token streaming
6. RAG score 기반 guardrail
7. Tool 기반 졸업학점 계산 / 과목 추천
8. contacts.json 기반 문의처 fallback
9. Docker PostgreSQL 개발 환경
```

## 코드상 주의할 점

```text
1. app/graph/state.py에는 현재 category_l1만 있고 category_l2는 state에 포함되어 있지 않다.
2. app/retrieval.py의 현재 검색은 category_l1 기준 필터 검색이다.
3. category 검색 결과가 없으면 전체 검색 fallback을 수행한다.
4. rag_node의 except Exception은 docs=[]로 처리하므로, 디버깅 시에는 traceback 로그를 추가하는 것이 좋다.
5. Resend 리마인드 PoC 코드는 현재 업로드된 zip의 app 코드에는 포함되어 있지 않으므로, 별도 service/router로 추가해야 한다.
```

---

# 19. GitHub에 넣는 추천 위치

```text
docs/MAJOR_CODE.md
```

또는

```text
docs/code-overview.md
```
