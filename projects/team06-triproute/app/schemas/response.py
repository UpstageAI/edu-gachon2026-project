from typing import Any

from pydantic import BaseModel, Field


class TripPlanResponse(BaseModel):
    condition_summary: dict[str, Any]
    daily_schedule: list[dict[str, Any]]
    route_summary: list[dict[str, Any]]
    cost_summary: dict[str, Any]
    warnings: list[str] = Field(default_factory=list)
    react_trace: list[dict[str, Any]] = Field(default_factory=list)