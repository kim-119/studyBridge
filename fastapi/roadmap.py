from __future__ import annotations

import json
import os
import re
from io import BytesIO
from typing import Any, List

from openai import OpenAI
from pydantic import BaseModel, ConfigDict, Field

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.cidfonts import UnicodeCIDFont
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import (
    SimpleDocTemplate,
    Paragraph,
    Spacer,
    Table,
    TableStyle,
)


# =========================================================
# 1. 데이터 스키마
# =========================================================

class RoadmapWeek(BaseModel):
    model_config = ConfigDict(extra="forbid")

    week: int = Field(..., ge=1)
    title: str
    learning_goal: str
    core_concepts: List[str]
    study_flow: List[str]
    practice_tasks: List[str]
    checkpoint: str


class RoadmapResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    subject: str
    level: str
    overview: str
    roadmap: List[RoadmapWeek]
    final_summary: str


class CrossValidationReport(BaseModel):
    model_config = ConfigDict(extra="forbid")

    passed: bool
    score: int = Field(..., ge=0, le=100)
    factuality_issues: List[str]
    structure_issues: List[str]
    level_issues: List[str]
    markdown_issues: List[str]
    improvement_required: bool
    judge_summary: str


class GeneratedRoadmapBundle(BaseModel):
    model_config = ConfigDict(extra="forbid")

    result: RoadmapResult
    validation_report: CrossValidationReport


# =========================================================
# 2. 입력값 검증 및 마크다운 제거
# =========================================================

ALLOWED_LEVELS = [
    "입문 수준",
    "학사 수준",
    "석사 수준",
    "박사 수준",
    "전문가 수준",
]

LEVEL_ALIASES = {
    "입문": "입문 수준",
    "입문자": "입문 수준",
    "초급": "입문 수준",
    "초급자": "입문 수준",

    "학사": "학사 수준",
    "학부": "학사 수준",
    "학부생": "학사 수준",
    "대학생": "학사 수준",

    "석사": "석사 수준",
    "대학원": "석사 수준",
    "대학원생": "석사 수준",

    "박사": "박사 수준",
    "박사과정": "박사 수준",

    "전문가": "전문가 수준",
    "고급": "전문가 수준",
    "고급자": "전문가 수준",
}

MARKDOWN_PATTERNS = [
    r"```",
    r"^\s*#{1,6}\s+",
    r"^\s*[-*]\s+",
    r"^\s*\d+\.\s+",
    r"\*\*",
    r"__",
    r"`",
]


def validate_subject(subject: str) -> str:
    cleaned = subject.strip()

    if not cleaned:
        raise ValueError("과목명이 비어 있습니다.")

    if len(cleaned) > 100:
        raise ValueError("과목명이 너무 깁니다.")

    return cleaned


def validate_level(level: str) -> str:
    cleaned = level.strip()

    if cleaned in LEVEL_ALIASES:
        cleaned = LEVEL_ALIASES[cleaned]

    if cleaned not in ALLOWED_LEVELS:
        raise ValueError(
            f"허용되지 않는 학습 수준입니다: {level}. "
            f"사용 가능 값: {', '.join(ALLOWED_LEVELS)}"
        )

    return cleaned


def validate_source_text(source_text: str) -> str:
    cleaned = source_text.strip()

    if len(cleaned) < 100:
        raise ValueError(
            "PDF 추출 텍스트가 너무 짧습니다. "
            "스캔본 PDF이거나 텍스트 추출이 제대로 되지 않았을 가능성이 있습니다."
        )

    broken_ratio = cleaned.count("�") / max(len(cleaned), 1)

    if broken_ratio > 0.03:
        raise ValueError(
            "PDF 텍스트 품질이 낮습니다. "
            "OCR 처리 또는 PDF 인코딩 확인이 필요합니다."
        )

    return cleaned


def validate_week_count(week_count: int) -> None:
    if week_count < 1 or week_count > 20:
        raise ValueError("로드맵 주차 수는 1 이상 20 이하만 가능합니다.")


def strip_markdown(text: str) -> str:
    if not isinstance(text, str):
        return text

    cleaned = text

    cleaned = cleaned.replace("```", "")
    cleaned = cleaned.replace("**", "")
    cleaned = cleaned.replace("__", "")
    cleaned = cleaned.replace("`", "")

    cleaned = re.sub(r"^\s*#{1,6}\s+", "", cleaned, flags=re.MULTILINE)
    cleaned = re.sub(r"^\s*[-*]\s+", "", cleaned, flags=re.MULTILINE)
    cleaned = re.sub(r"^\s*\d+\.\s+", "", cleaned, flags=re.MULTILINE)

    return cleaned.strip()


def contains_markdown(text: str) -> bool:
    if not isinstance(text, str):
        return False

    for pattern in MARKDOWN_PATTERNS:
        if re.search(pattern, text, flags=re.MULTILINE):
            return True

    return False


def sanitize_roadmap_result(result: RoadmapResult) -> RoadmapResult:
    data = result.model_dump()

    data["subject"] = strip_markdown(data["subject"])
    data["level"] = strip_markdown(data["level"])
    data["overview"] = strip_markdown(data["overview"])
    data["final_summary"] = strip_markdown(data["final_summary"])

    for week in data["roadmap"]:
        week["title"] = strip_markdown(week["title"])
        week["learning_goal"] = strip_markdown(week["learning_goal"])
        week["checkpoint"] = strip_markdown(week["checkpoint"])

        week["core_concepts"] = [
            strip_markdown(item) for item in week["core_concepts"]
        ]

        week["study_flow"] = [
            strip_markdown(item) for item in week["study_flow"]
        ]

        week["practice_tasks"] = [
            strip_markdown(item) for item in week["practice_tasks"]
        ]

    return RoadmapResult.model_validate(data)


def deterministic_validate_result(
        result: RoadmapResult,
        expected_week_count: int,
) -> None:
    errors: List[str] = []

    if len(result.roadmap) != expected_week_count:
        errors.append(
            f"로드맵 주차 수 불일치: 요청 {expected_week_count}, 결과 {len(result.roadmap)}"
        )

    week_numbers = [week.week for week in result.roadmap]
    expected_week_numbers = list(range(1, expected_week_count + 1))

    if week_numbers != expected_week_numbers:
        errors.append("로드맵 week 번호가 1부터 순서대로 이어지지 않습니다.")

    text_fields = [
        result.subject,
        result.level,
        result.overview,
        result.final_summary,
    ]

    for week in result.roadmap:
        text_fields.extend([
            week.title,
            week.learning_goal,
            week.checkpoint,
        ])

        text_fields.extend(week.core_concepts)
        text_fields.extend(week.study_flow)
        text_fields.extend(week.practice_tasks)

        if not week.title.strip():
            errors.append(f"{week.week}주차 title이 비어 있습니다.")

        if not week.learning_goal.strip():
            errors.append(f"{week.week}주차 learning_goal이 비어 있습니다.")

        if len(week.core_concepts) < 1:
            errors.append(f"{week.week}주차 core_concepts가 비어 있습니다.")

        if len(week.study_flow) < 1:
            errors.append(f"{week.week}주차 study_flow가 비어 있습니다.")

        if len(week.practice_tasks) < 1:
            errors.append(f"{week.week}주차 practice_tasks가 비어 있습니다.")

        if not week.checkpoint.strip():
            errors.append(f"{week.week}주차 checkpoint가 비어 있습니다.")

    for value in text_fields:
        if contains_markdown(value):
            errors.append(f"마크다운 문법이 남아 있습니다: {value[:50]}")

    if errors:
        raise ValueError(" / ".join(errors))


# =========================================================
# 3. 프롬프트
# =========================================================

def build_roadmap_prompt(
        subject: str,
        level: str,
        week_count: int,
        source_text: str,
) -> str:
    return f"""
너는 StudyBridge의 대학생 전용 학습 로드맵 설계 AI다.

목표:
PDF 학습 자료를 기반으로 실제 학생이 따라갈 수 있는 고품질 학습 로드맵을 생성한다.

과목명:
{subject}

학습자 수준:
{level}

로드맵 주차 수:
{week_count}

PDF 추출 텍스트:
{source_text}

로드맵 생성 기준:
1. PDF 내용을 개념 흐름에 따라 재구성한다.
2. 쉬운 개념에서 어려운 개념으로 점진적으로 배치한다.
3. 각 주차는 단순 제목 나열이 아니라 학습 목표, 핵심 개념, 학습 흐름, 실습 과제, 점검 기준을 포함한다.
4. 학습자가 무엇을 이해하고 넘어가야 하는지 명확하게 만든다.
5. 중간 복습 흐름과 최종 정리 흐름이 자연스럽게 포함되도록 구성한다.
6. PDF에 없는 내용을 과도하게 지어내지 않는다.
7. 학습 연결을 위해 필요한 최소한의 선행 개념은 보완할 수 있다.
8. 모든 문장은 자연스러운 한국어 평서문으로 작성한다.
9. 마크다운 문법을 절대 사용하지 않는다.
10. 제목 앞에 #, ##, -, *, 숫자목록 기호를 붙이지 않는다.
11. 코드블록 기호를 절대 사용하지 않는다.
12. 로드맵은 반드시 주차별 학습 흐름이 이어져야 한다.
13. 각 주차의 학습 과제는 실제 학생이 수행 가능한 형태로 작성한다.
14. overview는 전체 학습 방향을 3문장 이상으로 작성한다.
15. final_summary는 학습자가 마지막에 무엇을 완성하게 되는지 중심으로 작성한다.

출력은 반드시 지정된 JSON Schema만 따른다.
"""


def build_cross_validation_prompt(
        source_text: str,
        roadmap_json: str,
        expected_week_count: int,
        level: str,
) -> str:
    return f"""
너는 StudyBridge의 로드맵 품질 검증 AI다.

아래 원본 PDF 텍스트와 생성된 로드맵 JSON을 비교해서 검증하라.

검증 기준:
1. 로드맵이 원본 PDF 내용과 충돌하지 않는가.
2. PDF에 없는 내용을 과도하게 창작하지 않았는가.
3. 로드맵 주차 수가 {expected_week_count}개인가.
4. 학습 난이도가 {level}에 맞는가.
5. 마크다운 문법이 포함되어 있지 않은가.
6. 각 주차가 실제 학습 흐름으로 자연스러운가.
7. 개요, 주차별 학습 흐름, 최종 요약이 서로 일관되는가.
8. 주차별 핵심 개념과 학습 과제가 서로 연결되는가.
9. 학습 목표가 추상적이지 않고 학생이 이해 가능한 수준인가.
10. 점검 기준이 각 주차의 학습 목표와 연결되는가.

원본 PDF 텍스트:
{source_text}

생성된 로드맵 JSON:
{roadmap_json}

판정 방식:
1. score는 0부터 100까지 부여한다.
2. 85점 이상이고 심각한 오류가 없으면 passed는 true다.
3. 사실 오류, 구조 오류, 수준 오류, 마크다운 오류를 각각 배열로 작성한다.
4. 수정이 필요하면 improvement_required를 true로 둔다.
5. judge_summary에는 전체 판단을 짧게 작성한다.

출력은 반드시 지정된 JSON Schema만 따른다.
"""


def build_repair_prompt(
        source_text: str,
        roadmap_json: str,
        validation_report_json: str,
        expected_week_count: int,
) -> str:
    return f"""
너는 StudyBridge의 로드맵 수정 AI다.

아래 검증 리포트를 기준으로 로드맵 JSON을 수정하라.

수정 목표:
1. 원본 PDF 텍스트와 충돌하는 내용을 제거한다.
2. 과도하게 창작된 내용을 줄인다.
3. 로드맵 주차 수를 {expected_week_count}개로 맞춘다.
4. week 번호를 1부터 {expected_week_count}까지 순서대로 정리한다.
5. 마크다운 문법을 전부 제거한다.
6. 문장을 자연스러운 한국어 평서문으로 정리한다.
7. 기존 장점은 유지하고 오류만 고친다.
8. 학습 흐름이 끊기지 않도록 주차별 순서를 정리한다.
9. 모든 필수 필드를 반드시 채운다.

원본 PDF 텍스트:
{source_text}

기존 로드맵 JSON:
{roadmap_json}

검증 리포트:
{validation_report_json}

출력은 반드시 지정된 JSON Schema만 따른다.
"""


# =========================================================
# 4. 한글 PDF 폰트 자동 탐색 및 PDF 생성
# =========================================================

def find_korean_font_path(font_path: str | None = None) -> str | None:
    if font_path and os.path.exists(font_path):
        return font_path

    env_font_path = os.getenv("ROADMAP_PDF_FONT_PATH")

    if env_font_path and os.path.exists(env_font_path):
        return env_font_path

    candidate_paths = [
        "C:/Windows/Fonts/malgun.ttf",
        "C:/Windows/Fonts/malgunbd.ttf",
        "C:/Windows/Fonts/gulim.ttc",
        "C:/Windows/Fonts/batang.ttc",

        "/usr/share/fonts/truetype/nanum/NanumGothic.ttf",
        "/usr/share/fonts/truetype/nanum/NanumGothicBold.ttf",
        "/usr/share/fonts/truetype/noto/NotoSansCJK-Regular.ttc",
        "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
        "/usr/share/fonts/opentype/noto/NotoSansCJKkr-Regular.otf",

        "/System/Library/Fonts/AppleSDGothicNeo.ttc",
        "/Library/Fonts/AppleGothic.ttf",
    ]

    for candidate in candidate_paths:
        if os.path.exists(candidate):
            return candidate

    return None


def register_korean_font(font_path: str | None = None) -> str:
    selected_font_path = find_korean_font_path(font_path)

    font_name = "StudyBridgeKoreanFont"

    if selected_font_path:
        if font_name not in pdfmetrics.getRegisteredFontNames():
            pdfmetrics.registerFont(TTFont(font_name, selected_font_path))

        return font_name

    fallback_font_name = "HYSMyeongJo-Medium"

    if fallback_font_name not in pdfmetrics.getRegisteredFontNames():
        pdfmetrics.registerFont(UnicodeCIDFont(fallback_font_name))

    return fallback_font_name


def safe_text(text: str) -> str:
    return (
        str(text)
        .replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace("\n", "<br/>")
    )


def paragraph(text: str, style: ParagraphStyle) -> Paragraph:
    return Paragraph(safe_text(text), style)


def make_list_text(items: list[str]) -> str:
    return " / ".join(str(item) for item in items)


def build_roadmap_pdf_bytes(
        result: RoadmapResult,
        validation_report: CrossValidationReport,
        font_path: str | None = None,
) -> bytes:
    font_name = register_korean_font(font_path)

    buffer = BytesIO()

    doc = SimpleDocTemplate(
        buffer,
        pagesize=A4,
        rightMargin=16 * mm,
        leftMargin=16 * mm,
        topMargin=14 * mm,
        bottomMargin=14 * mm,
    )

    title_style = ParagraphStyle(
        name="StudyBridgeTitle",
        fontName=font_name,
        fontSize=20,
        leading=27,
        spaceAfter=14,
        textColor=colors.HexColor("#222222"),
    )

    section_style = ParagraphStyle(
        name="StudyBridgeSection",
        fontName=font_name,
        fontSize=14,
        leading=20,
        spaceBefore=10,
        spaceAfter=7,
        textColor=colors.HexColor("#222222"),
    )

    body_style = ParagraphStyle(
        name="StudyBridgeBody",
        fontName=font_name,
        fontSize=10.5,
        leading=16,
        spaceAfter=5,
        textColor=colors.HexColor("#333333"),
    )

    small_style = ParagraphStyle(
        name="StudyBridgeSmall",
        fontName=font_name,
        fontSize=9.3,
        leading=14,
        textColor=colors.HexColor("#444444"),
    )

    story = []

    story.append(paragraph("StudyBridge 학습 로드맵", title_style))
    story.append(paragraph(f"과목명: {result.subject}", body_style))
    story.append(paragraph(f"학습 수준: {result.level}", body_style))
    story.append(paragraph(f"교차검증 점수: {validation_report.score}점", body_style))
    story.append(Spacer(1, 8))

    story.append(paragraph("전체 개요", section_style))
    story.append(paragraph(result.overview, body_style))

    story.append(paragraph("주차별 학습 로드맵", section_style))

    for week in result.roadmap:
        story.append(Spacer(1, 6))
        story.append(paragraph(f"{week.week}주차. {week.title}", section_style))
        story.append(paragraph(f"학습 목표: {week.learning_goal}", body_style))
        story.append(paragraph(f"핵심 개념: {make_list_text(week.core_concepts)}", body_style))

        table_rows = [[paragraph("학습 흐름", small_style)]]

        for item in week.study_flow:
            table_rows.append([paragraph(item, small_style)])

        flow_table = Table(
            table_rows,
            colWidths=[170 * mm],
            repeatRows=1,
        )

        flow_table.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#eeeeee")),
            ("BOX", (0, 0), (-1, -1), 0.5, colors.HexColor("#bbbbbb")),
            ("INNERGRID", (0, 0), (-1, -1), 0.25, colors.HexColor("#dddddd")),
            ("VALIGN", (0, 0), (-1, -1), "TOP"),
            ("LEFTPADDING", (0, 0), (-1, -1), 7),
            ("RIGHTPADDING", (0, 0), (-1, -1), 7),
            ("TOPPADDING", (0, 0), (-1, -1), 5),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
        ]))

        story.append(flow_table)
        story.append(Spacer(1, 5))

        story.append(
            paragraph(
                f"실습 및 복습 과제: {make_list_text(week.practice_tasks)}",
                body_style,
            )
        )

        story.append(paragraph(f"점검 기준: {week.checkpoint}", body_style))

    story.append(Spacer(1, 10))
    story.append(paragraph("최종 요약", section_style))
    story.append(paragraph(result.final_summary, body_style))

    story.append(Spacer(1, 8))
    story.append(paragraph("교차검증 결과", section_style))
    story.append(paragraph(validation_report.judge_summary, body_style))

    if validation_report.factuality_issues:
        story.append(
            paragraph(
                f"사실성 점검: {make_list_text(validation_report.factuality_issues)}",
                small_style,
            )
        )

    if validation_report.structure_issues:
        story.append(
            paragraph(
                f"구조 점검: {make_list_text(validation_report.structure_issues)}",
                small_style,
            )
        )

    if validation_report.level_issues:
        story.append(
            paragraph(
                f"난이도 점검: {make_list_text(validation_report.level_issues)}",
                small_style,
            )
        )

    if validation_report.markdown_issues:
        story.append(
            paragraph(
                f"마크다운 점검: {make_list_text(validation_report.markdown_issues)}",
                small_style,
            )
        )

    doc.build(story)

    pdf_bytes = buffer.getvalue()
    buffer.close()

    return pdf_bytes


# =========================================================
# 5. 로드맵 생성 도구
# =========================================================

class StudyBridgeRoadmapTool:
    def __init__(
            self,
            openai_api_key: str,
            model: str = "gpt-4o-mini",
            validator_model: str = "gpt-4o-mini",
            max_source_chars: int = 25000,
    ):
        self.client = OpenAI(api_key=openai_api_key)
        self.model = model
        self.validator_model = validator_model
        self.max_source_chars = max_source_chars

    def _limit_text(self, text: str) -> str:
        if len(text) <= self.max_source_chars:
            return text

        return text[:self.max_source_chars]

    def _roadmap_schema(self) -> dict[str, Any]:
        return {
            "name": "studybridge_roadmap_result",
            "strict": True,
            "schema": RoadmapResult.model_json_schema(),
        }

    def _validation_schema(self) -> dict[str, Any]:
        return {
            "name": "studybridge_validation_report",
            "strict": True,
            "schema": CrossValidationReport.model_json_schema(),
        }

    def _call_json_schema(
            self,
            model: str,
            system_prompt: str,
            user_prompt: str,
            schema: dict[str, Any],
            temperature: float = 0.2,
    ) -> dict[str, Any]:
        response = self.client.chat.completions.create(
            model=model,
            temperature=temperature,
            messages=[
                {
                    "role": "system",
                    "content": system_prompt,
                },
                {
                    "role": "user",
                    "content": user_prompt,
                },
            ],
            response_format={
                "type": "json_schema",
                "json_schema": schema,
            },
        )

        content = response.choices[0].message.content

        if not content:
            raise ValueError("AI 응답이 비어 있습니다.")

        return json.loads(content)

    def _model_to_json_text(self, model: BaseModel) -> str:
        return json.dumps(
            model.model_dump(),
            ensure_ascii=False,
            indent=2,
        )

    def _create_structure_error_report(self, error_message: str) -> CrossValidationReport:
        return CrossValidationReport(
            passed=False,
            score=60,
            factuality_issues=[],
            structure_issues=[error_message],
            level_issues=[],
            markdown_issues=[],
            improvement_required=True,
            judge_summary="코드 레벨 구조 검증에서 오류가 발견되어 자동 수정이 필요합니다.",
        )

    def generate(
            self,
            source_text: str,
            subject: str,
            level: str = "학사 수준",
            week_count: int = 15,
    ) -> GeneratedRoadmapBundle:
        subject = validate_subject(subject)
        level = validate_level(level)
        validate_week_count(week_count)

        source_text = validate_source_text(source_text)
        limited_source_text = self._limit_text(source_text)

        generation_prompt = build_roadmap_prompt(
            subject=subject,
            level=level,
            week_count=week_count,
            source_text=limited_source_text,
        )

        raw_result = self._call_json_schema(
            model=self.model,
            system_prompt=(
                "너는 대학생 학습 로드맵을 JSON으로 생성하는 StudyBridge AI다. "
                "마크다운 없이 구조화된 JSON만 출력한다."
            ),
            user_prompt=generation_prompt,
            schema=self._roadmap_schema(),
            temperature=0.25,
        )

        result = RoadmapResult.model_validate(raw_result)
        result = sanitize_roadmap_result(result)

        try:
            deterministic_validate_result(
                result=result,
                expected_week_count=week_count,
            )

        except ValueError as structure_error:
            structure_report = self._create_structure_error_report(str(structure_error))

            result = self.repair(
                source_text=limited_source_text,
                result=result,
                validation_report=structure_report,
                expected_week_count=week_count,
            )

            result = sanitize_roadmap_result(result)

            deterministic_validate_result(
                result=result,
                expected_week_count=week_count,
            )

        validation_report = self.cross_validate(
            source_text=limited_source_text,
            result=result,
            expected_week_count=week_count,
            level=level,
        )

        if validation_report.improvement_required or not validation_report.passed:
            result = self.repair(
                source_text=limited_source_text,
                result=result,
                validation_report=validation_report,
                expected_week_count=week_count,
            )

            result = sanitize_roadmap_result(result)

            deterministic_validate_result(
                result=result,
                expected_week_count=week_count,
            )

            validation_report = self.cross_validate(
                source_text=limited_source_text,
                result=result,
                expected_week_count=week_count,
                level=level,
            )

        if validation_report.score < 80:
            raise ValueError(
                f"로드맵 교차검증 점수가 낮습니다: {validation_report.score}. "
                f"검증 요약: {validation_report.judge_summary}"
            )

        return GeneratedRoadmapBundle(
            result=result,
            validation_report=validation_report,
        )

    def cross_validate(
            self,
            source_text: str,
            result: RoadmapResult,
            expected_week_count: int,
            level: str,
    ) -> CrossValidationReport:
        prompt = build_cross_validation_prompt(
            source_text=source_text,
            roadmap_json=self._model_to_json_text(result),
            expected_week_count=expected_week_count,
            level=level,
        )

        raw_report = self._call_json_schema(
            model=self.validator_model,
            system_prompt=(
                "너는 생성된 학습 로드맵을 원본 자료와 비교해 검증하는 "
                "엄격한 평가자다."
            ),
            user_prompt=prompt,
            schema=self._validation_schema(),
            temperature=0.1,
        )

        return CrossValidationReport.model_validate(raw_report)

    def repair(
            self,
            source_text: str,
            result: RoadmapResult,
            validation_report: CrossValidationReport,
            expected_week_count: int,
    ) -> RoadmapResult:
        prompt = build_repair_prompt(
            source_text=source_text,
            roadmap_json=self._model_to_json_text(result),
            validation_report_json=self._model_to_json_text(validation_report),
            expected_week_count=expected_week_count,
        )

        repaired_raw = self._call_json_schema(
            model=self.model,
            system_prompt=(
                "너는 검증 리포트를 반영해 로드맵 JSON을 수정하는 StudyBridge AI다. "
                "마크다운 없이 JSON만 출력한다."
            ),
            user_prompt=prompt,
            schema=self._roadmap_schema(),
            temperature=0.15,
        )

        repaired_result = RoadmapResult.model_validate(repaired_raw)

        return sanitize_roadmap_result(repaired_result)

    def generate_pdf_bytes(
            self,
            source_text: str,
            subject: str,
            level: str = "학사 수준",
            week_count: int = 15,
            font_path: str | None = None,
    ) -> bytes:
        bundle = self.generate(
            source_text=source_text,
            subject=subject,
            level=level,
            week_count=week_count,
        )

        return build_roadmap_pdf_bytes(
            result=bundle.result,
            validation_report=bundle.validation_report,
            font_path=font_path,
        )