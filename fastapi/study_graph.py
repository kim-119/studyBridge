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
    hours: float = Field(..., ge=0, le=24)


class StudyGraphRequest(BaseModel):
    user_id: int
    data: List[DailyStudyTime]


class StudyGraphResponse(BaseModel):
    user_id: int
    total_hours: float
    average_hours: float
    attendance_days: int
    max_study_day: str
    max_study_hours: float
    graph_base64: str


def calculate_study_stats(data: List[DailyStudyTime]) -> dict:
    if not data:
        raise HTTPException(
            status_code=400,
            detail="공부 시간 데이터가 비어 있습니다."
        )

    total_hours = sum(item.hours for item in data)
    average_hours = total_hours / len(data)
    attendance_days = sum(1 for item in data if item.hours > 0)
    max_item = max(data, key=lambda item: item.hours)

    return {
        "total_hours": round(total_hours, 2),
        "average_hours": round(average_hours, 2),
        "attendance_days": attendance_days,
        "max_study_day": max_item.day,
        "max_study_hours": round(max_item.hours, 2)
    }


def create_study_time_graph(data: List[DailyStudyTime]) -> str:
    days = [item.day for item in data]
    hours = [item.hours for item in data]

    plt.figure(figsize=(9, 5))
    plt.bar(days, hours)
    plt.plot(days, hours, marker="o")
    plt.title("Weekly Study Time")
    plt.xlabel("Day")
    plt.ylabel("Study Hours")
    plt.ylim(0, max(hours) + 1 if max(hours) > 0 else 1)
    plt.grid(axis="y", linestyle="--", alpha=0.5)
    plt.tight_layout()

    image_buffer = io.BytesIO()
    plt.savefig(image_buffer, format="png", dpi=150)
    plt.close()

    image_buffer.seek(0)
    image_base64 = base64.b64encode(image_buffer.read()).decode("utf-8")

    return image_base64


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
        total_hours=stats["total_hours"],
        average_hours=stats["average_hours"],
        attendance_days=stats["attendance_days"],
        max_study_day=stats["max_study_day"],
        max_study_hours=stats["max_study_hours"],
        graph_base64=graph_base64
    )