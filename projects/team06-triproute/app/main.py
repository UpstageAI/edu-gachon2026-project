import gradio as gr
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse

from app.agents.react_loop import run_triproute_react_loop
from app.schemas.request import TripPlanRequest
from app.schemas.response import TripPlanResponse
from ui.gradio_app import CUSTOM_CSS, HEAD_HTML, demo


app = FastAPI(
    title="TripRoute API",
    description="Agentic Workflow 기반 여행 일정 자동 생성 API",
    version="0.1.0",
)

# previous_result(직전 턴 전체 결과)까지 실어 보내는 후속 요청은 payload가 커질 수
# 있으므로 여유 있게 잡되, 무제한으로 두지는 않는다.
MAX_TRIP_PLAN_BODY_BYTES = 1_000_000


@app.middleware("http")
async def limit_trip_plan_body_size(request: Request, call_next):
    if request.url.path == "/trip/plan":
        content_length = request.headers.get("content-length")
        if content_length is not None and int(content_length) > MAX_TRIP_PLAN_BODY_BYTES:
            return JSONResponse(
                status_code=413, content={"detail": "요청 본문이 너무 큽니다."}
            )
    return await call_next(request)


@app.get("/")
def health_check() -> dict:
    return {
        "status": "ok",
        "message": "TripRoute API is running",
    }


@app.post("/trip/plan", response_model=TripPlanResponse)
def create_trip_plan(request: TripPlanRequest) -> TripPlanResponse:
    try:
        result = run_triproute_react_loop(
            user_input=request.user_input,
            transport_mode=request.transport_mode,
            people_count=request.people_count,
            previous_condition_summary=request.previous_condition_summary,
            previous_result=(
                request.previous_result.model_dump()
                if request.previous_result is not None
                else None
            ),
            thread_id=request.thread_id,
        )
    except ValueError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error
    except Exception as error:
        raise HTTPException(
            status_code=500, detail=f"여행 계획을 생성하는 중 오류가 발생했습니다: {error}"
        ) from error

    return TripPlanResponse(
        condition_summary=result["condition_summary"],
        daily_schedule=result["daily_schedule"],
        route_summary=result["route_summary"],
        cost_summary=result["cost_summary"],
        warnings=result["warnings"],
        react_trace=result["react_trace"],
    )


# Gradio UI를 FastAPI의 /ui 경로에 연결
app = gr.mount_gradio_app(
    app,
    demo,
    path="/ui",
    theme=gr.themes.Default(),
    css=CUSTOM_CSS,
    head=HEAD_HTML,
    show_error=True,
)