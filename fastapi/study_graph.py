import base64
import io
from typing import List

import matplotlib
matplotlib.use("Agg")

import matplotlib.pyplot as plt
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field


router = APIRouter(
    prefix="/activity",
    tags=["Study Activity Graph"]
)


class DailyStudyTime(BaseModel):
    day: str = Field(..., min_length=1, max_length=20)
    minutes: float = Field(..., ge=0)


class StudyGraphRequest(BaseModel):
    user_id: int
    data: List[DailyStudyTime]


class StudyGraphResponse(BaseModel):
    user_id: int
    total_minutes: float
    total_hours: float
    average_minutes: float
    average_hours: float
    attendance_days: int
    max_study_day: str
    max_study_minutes: float
    max_study_hours: float
    graph_base64: str


def calculate_study_stats(data: List[DailyStudyTime]) -> dict:
    if not data:
        raise HTTPException(
            status_code=400,
            detail="공부 시간 데이터가 비어 있습니다."
        )

    total_minutes = sum(item.minutes for item in data)
    average_minutes = total_minutes / len(data)
    attendance_days = sum(1 for item in data if item.minutes > 0)
    max_item = max(data, key=lambda item: item.minutes)

    return {
        "total_minutes": round(total_minutes, 2),
        "total_hours": round(total_minutes / 60, 2),
        "average_minutes": round(average_minutes, 2),
        "average_hours": round(average_minutes / 60, 2),
        "attendance_days": attendance_days,
        "max_study_day": max_item.day,
        "max_study_minutes": round(max_item.minutes, 2),
        "max_study_hours": round(max_item.minutes / 60, 2)
    }


def create_study_time_graph(data: List[DailyStudyTime]) -> str:
    days = [item.day for item in data]
    minutes = [item.minutes for item in data]

    plt.figure(figsize=(9, 5))
    plt.bar(days, minutes)
    plt.plot(days, minutes, marker="o")
    plt.title("Daily Study Time")
    plt.xlabel("Day")
    plt.ylabel("Study Minutes")
    plt.ylim(0, max(minutes) + 10 if max(minutes) > 0 else 10)
    plt.grid(axis="y", linestyle="--", alpha=0.5)
    plt.tight_layout()

    image_buffer = io.BytesIO()
    plt.savefig(image_buffer, format="png", dpi=150)
    plt.close()

    image_buffer.seek(0)
    image_base64 = base64.b64encode(image_buffer.read()).decode("utf-8")

    return image_base64


@router.post("/daily-graph", response_model=StudyGraphResponse)
def create_daily_study_graph(request: StudyGraphRequest):
    stats = calculate_study_stats(request.data)
    graph_base64 = create_study_time_graph(request.data)

    return StudyGraphResponse(
        user_id=request.user_id,
        total_minutes=stats["total_minutes"],
        total_hours=stats["total_hours"],
        average_minutes=stats["average_minutes"],
        average_hours=stats["average_hours"],
        attendance_days=stats["attendance_days"],
        max_study_day=stats["max_study_day"],
        max_study_minutes=stats["max_study_minutes"],
        max_study_hours=stats["max_study_hours"],
        graph_base64=graph_base64
    )


@router.post("/weekly-graph", response_model=StudyGraphResponse)
def create_weekly_study_graph(request: StudyGraphRequest):
    if len(request.data) != 7:
        raise HTTPException(
            status_code=400,
            detail="주간 공부 시간 그래프는 7일치 데이터가 필요합니다."
        )

    stats = calculate_study_stats(request.data)
    graph_base64 = create_study_time_graph(request.data)

    return StudyGraphResponse(
        user_id=request.user_id,
        total_minutes=stats["total_minutes"],
        total_hours=stats["total_hours"],
        average_minutes=stats["average_minutes"],
        average_hours=stats["average_hours"],
        attendance_days=stats["attendance_days"],
        max_study_day=stats["max_study_day"],
        max_study_minutes=stats["max_study_minutes"],
        max_study_hours=stats["max_study_hours"],
        graph_base64=graph_base64
    )