"""MathMate FastAPI 진입점."""
from fastapi import FastAPI
from app.api import health, chat, problems, progress, profile, feedback

app = FastAPI(title="MathMate", description="초등 수학 소크라테스식 튜터")

app.include_router(health.router, prefix="/api")
app.include_router(chat.router, prefix="/api")
app.include_router(problems.router, prefix="/api")
app.include_router(progress.router, prefix="/api")
app.include_router(profile.router, prefix="/api")
app.include_router(feedback.router, prefix="/api")


@app.get("/")
def root():
    return {"service": "MathMate", "status": "running"}
