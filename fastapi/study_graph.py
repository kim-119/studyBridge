import base64
import io
from datetime import date
from typing import List, Optional

import matplotlib

# 서버 환경에서 GUI 없이 그래프 이미지 생성 가능하게 설정
matplotlib.use("Agg")

import matplotlib.pyplot as plt
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field


router = APIRouter(
    prefix="/activity",
    tags=["Study Activity Graph"]
)


class DailyStudyTime(BaseModel):
    # 날짜 또는 요일 이름
    day: str = Field(..., min_length=1, max_length=20)

    # 공부 시간, 분 단위
    minutes: float = Field(..., ge=0)


class StudyGraphRequest(BaseModel):
    # 사용자 ID
    user_id: int

    # 날짜별 공부 시간 데이터
    data: List[DailyStudyTime]

    # 주간 그래프 시작일
    # 예: 2026-05-04
    week_start_date: Optional[date] = None

    # 주간 그래프 종료일
    # 예: 2026-05-10
    week_end_date: Optional[date] = None


class StudyGraphResponse(BaseModel):
    # 사용자 ID
    user_id: int

    # 그래프 타입: daily 또는 weekly
    graph_type: str

    # 총 공부 시간, 분
    total_minutes: float

    # 총 공부 시간, 시간
    total_hours: float

    # 평균 공부 시간, 분
    average_minutes: float

    # 평균 공부 시간, 시간
    average_hours: float

    # 실제 공부한 날짜 수
    attendance_days: int

    # 가장 많이 공부한 날짜
    max_study_day: str

    # 가장 많이 공부한 날짜의 분 단위 공부 시간
    max_study_minutes: float

    # 가장 많이 공부한 날짜의 시간 단위 공부 시간
    max_study_hours: float

    # 그래프 이미지 base64 문자열
    graph_base64: str

    # 주간 그래프 종료 여부
    is_week_finished: bool

    # 다운로드 가능 여부
    can_download: bool

    # 삭제 가능 여부
    can_delete: bool

    # 다운로드 파일명
    graph_file_name: str


GRAPH_COLORS = {
    "primary_green": "#5AC857",
    "dark_green": "#2F7D32",
    "soft_green": "#DDF7DC",
    "bar_edge": "#7BD979",
    "text_dark": "#111827",
    "text_muted": "#64748B",
    "grid": "#E5E7EB",
    "background": "#FFFFFF"
}


def calculate_study_stats(data: List[DailyStudyTime]) -> dict:
    # 데이터가 없으면 통계와 그래프를 만들 수 없음
    if not data:
        raise HTTPException(
            status_code=400,
            detail="공부 시간 데이터가 비어 있습니다."
        )

    # 총 공부 시간 계산
    total_minutes = sum(item.minutes for item in data)

    # 평균 공부 시간 계산
    average_minutes = total_minutes / len(data)

    # 0분보다 많이 공부한 날만 출석일로 계산
    attendance_days = sum(1 for item in data if item.minutes > 0)

    # 가장 많이 공부한 날짜 찾기
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


def check_week_finished(week_end_date: Optional[date]) -> bool:
    # 주 종료일이 없으면 종료 여부를 판단할 수 없음
    if week_end_date is None:
        return False

    # 오늘 날짜가 주 종료일보다 지나갔으면 한 주가 끝난 것으로 판단
    return date.today() > week_end_date


def create_study_time_graph(
        data: List[DailyStudyTime],
        graph_title: str
) -> str:
    # x축 데이터
    days = [item.day for item in data]

    # y축 데이터
    minutes = [item.minutes for item in data]

    # y축 최대값 계산
    max_minutes = max(minutes) if minutes else 0

    # 그래프 상단 여백 설정
    y_limit = max_minutes + 20 if max_minutes > 0 else 10

    # 그래프 크기 설정
    fig, ax = plt.subplots(figsize=(9, 4.8))

    # 카드 UI와 어울리도록 배경 흰색 적용
    fig.patch.set_facecolor(GRAPH_COLORS["background"])
    ax.set_facecolor(GRAPH_COLORS["background"])

    # 막대 그래프
    ax.bar(
        days,
        minutes,
        color=GRAPH_COLORS["soft_green"],
        edgecolor=GRAPH_COLORS["bar_edge"],
        linewidth=1.2,
        width=0.55,
        zorder=2
    )

    # 선 그래프
    ax.plot(
        days,
        minutes,
        color=GRAPH_COLORS["dark_green"],
        linewidth=2.2,
        marker="o",
        markersize=6,
        markerfacecolor=GRAPH_COLORS["background"],
        markeredgecolor=GRAPH_COLORS["dark_green"],
        markeredgewidth=2,
        zorder=3
    )

    # 그래프 제목
    ax.set_title(
        graph_title,
        fontsize=15,
        fontweight="bold",
        color=GRAPH_COLORS["text_dark"],
        pad=16
    )

    # x축 라벨
    ax.set_xlabel(
        "Day",
        fontsize=11,
        color=GRAPH_COLORS["text_muted"],
        labelpad=10
    )

    # y축 라벨
    ax.set_ylabel(
        "Study Minutes",
        fontsize=11,
        color=GRAPH_COLORS["text_muted"],
        labelpad=10
    )

    # y축 범위 설정
    ax.set_ylim(0, y_limit)

    # y축 grid만 은은하게 표시
    ax.grid(
        axis="y",
        linestyle="--",
        linewidth=0.8,
        alpha=0.8,
        color=GRAPH_COLORS["grid"],
        zorder=1
    )

    # 위쪽, 오른쪽 테두리 제거
    ax.spines["top"].set_visible(False)
    ax.spines["right"].set_visible(False)

    # 왼쪽, 아래쪽 테두리 색상 정리
    ax.spines["left"].set_color(GRAPH_COLORS["grid"])
    ax.spines["bottom"].set_color(GRAPH_COLORS["grid"])

    # x축 눈금 색상
    ax.tick_params(
        axis="x",
        colors=GRAPH_COLORS["text_dark"],
        labelsize=10
    )

    # y축 눈금 색상
    ax.tick_params(
        axis="y",
        colors=GRAPH_COLORS["text_muted"],
        labelsize=10
    )

    # 여백 자동 정리
    plt.tight_layout()

    # 이미지를 메모리에 저장
    image_buffer = io.BytesIO()
    plt.savefig(
        image_buffer,
        format="png",
        dpi=150,
        bbox_inches="tight",
        facecolor=fig.get_facecolor()
    )

    # matplotlib figure 닫기
    plt.close(fig)

    # base64 문자열로 변환
    image_buffer.seek(0)
    image_base64 = base64.b64encode(image_buffer.read()).decode("utf-8")

    return image_base64


def build_study_graph_response(
        request: StudyGraphRequest,
        graph_type: str,
        graph_title: str
) -> StudyGraphResponse:
    # 공부 통계 계산
    stats = calculate_study_stats(request.data)

    # 그래프 이미지 생성
    graph_base64 = create_study_time_graph(
        data=request.data,
        graph_title=graph_title
    )

    # 주간 그래프인지 확인
    is_weekly_graph = graph_type == "weekly"

    # 주간 그래프 종료 여부 확인
    is_week_finished = (
        check_week_finished(request.week_end_date)
        if is_weekly_graph
        else False
    )

    # 다운로드 파일명 생성
    if is_weekly_graph and request.week_start_date and request.week_end_date:
        graph_file_name = (
            f"study-weekly-graph-"
            f"{request.week_start_date}-to-{request.week_end_date}.png"
        )
    else:
        graph_file_name = "study-graph.png"

    return StudyGraphResponse(
        user_id=request.user_id,
        graph_type=graph_type,
        total_minutes=stats["total_minutes"],
        total_hours=stats["total_hours"],
        average_minutes=stats["average_minutes"],
        average_hours=stats["average_hours"],
        attendance_days=stats["attendance_days"],
        max_study_day=stats["max_study_day"],
        max_study_minutes=stats["max_study_minutes"],
        max_study_hours=stats["max_study_hours"],
        graph_base64=graph_base64,
        is_week_finished=is_week_finished,
        can_download=is_week_finished,
        can_delete=is_week_finished,
        graph_file_name=graph_file_name
    )


@router.post("/daily-graph", response_model=StudyGraphResponse)
def create_daily_study_graph(request: StudyGraphRequest):
    # 일간 그래프 생성
    return build_study_graph_response(
        request=request,
        graph_type="daily",
        graph_title="Daily Study Time"
    )


@router.post("/weekly-graph", response_model=StudyGraphResponse)
def create_weekly_study_graph(request: StudyGraphRequest):
    # 주간 그래프는 7일치 데이터가 필요함
    if len(request.data) != 7:
        raise HTTPException(
            status_code=400,
            detail="주간 공부 시간 그래프는 7일치 데이터가 필요합니다."
        )

    # 주간 종료 판단을 위해 시작일/종료일이 필요함
    if request.week_start_date is None or request.week_end_date is None:
        raise HTTPException(
            status_code=400,
            detail="주간 그래프는 week_start_date와 week_end_date가 필요합니다."
        )

    # 주간 그래프 생성
    return build_study_graph_response(
        request=request,
        graph_type="weekly",
        graph_title="Weekly Study Time"
    )