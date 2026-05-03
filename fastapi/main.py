import os
import io
from typing import List, Dict

import fitz
import pytesseract
from PIL import Image
from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, UploadFile, File, Form
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from google import genai
from pydantic import BaseModel, Field
from pypdf import PdfReader

load_dotenv()

pytesseract.pytesseract.tesseract_cmd = r"C:\Program Files\Tesseract-OCR\tesseract.exe"

app = FastAPI(title="StudyBridge FastAPI Server")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")

if GEMINI_API_KEY:
    gemini_client = genai.Client(api_key=GEMINI_API_KEY)
else:
    gemini_client = None


# =========================
# 기본 API
# =========================

@app.get("/")
def frontend():
    return FileResponse("index.html")


@app.get("/health")
def health():
    return {
        "status": "ok",
        "message": "FastAPI server is running"
    }


def check_gemini_client():
    if gemini_client is None:
        raise HTTPException(
            status_code=500,
            detail="GEMINI_API_KEY가 설정되지 않았습니다. .env 파일을 확인하세요."
        )


# =========================
# 기본 Gemini 질문 API
# =========================

class GeminiRequest(BaseModel):
    prompt: str = Field(..., min_length=1)


class GeminiResponse(BaseModel):
    result: str


@app.post("/ai/chat", response_model=GeminiResponse)
def ask_gemini(request: GeminiRequest):
    check_gemini_client()

    response = gemini_client.models.generate_content(
        model="gemini-2.5-flash",
        contents=request.prompt
    )

    return GeminiResponse(result=response.text)


# =========================
# 사용자 커스텀 AI 에이전트 기능
# 최대 3개
# =========================

MAX_AGENT_COUNT = 3

agents: Dict[int, dict] = {}
agent_id_sequence = 1


class AgentCreateRequest(BaseModel):
    name: str = Field(..., min_length=1, max_length=30)
    role: str = Field(..., min_length=1, max_length=50)
    persona: str = Field(..., min_length=5, max_length=1000)
    tone: str = Field(default="친절하고 전문적인 말투", max_length=100)
    goal: str = Field(default="사용자의 학습을 돕는다", max_length=200)


class AgentResponse(BaseModel):
    id: int
    name: str
    role: str
    persona: str
    tone: str
    goal: str


class AgentChatRequest(BaseModel):
    message: str = Field(..., min_length=1)


class AgentChatResponse(BaseModel):
    agent_id: int
    agent_name: str
    role: str
    answer: str


@app.post("/agents", response_model=AgentResponse)
def create_agent(request: AgentCreateRequest):
    global agent_id_sequence

    if len(agents) >= MAX_AGENT_COUNT:
        raise HTTPException(
            status_code=400,
            detail="AI 에이전트는 최대 3개까지만 생성할 수 있습니다."
        )

    agent_id = agent_id_sequence
    agent_id_sequence += 1

    agent = {
        "id": agent_id,
        "name": request.name,
        "role": request.role,
        "persona": request.persona,
        "tone": request.tone,
        "goal": request.goal
    }

    agents[agent_id] = agent

    return AgentResponse(**agent)


@app.get("/agents", response_model=List[AgentResponse])
def get_agents():
    return [AgentResponse(**agent) for agent in agents.values()]


@app.get("/agents/{agent_id}", response_model=AgentResponse)
def get_agent(agent_id: int):
    if agent_id not in agents:
        raise HTTPException(
            status_code=404,
            detail="해당 AI 에이전트를 찾을 수 없습니다."
        )

    return AgentResponse(**agents[agent_id])


@app.delete("/agents/{agent_id}")
def delete_agent(agent_id: int):
    if agent_id not in agents:
        raise HTTPException(
            status_code=404,
            detail="해당 AI 에이전트를 찾을 수 없습니다."
        )

    deleted_agent = agents.pop(agent_id)

    return {
        "message": "AI 에이전트가 삭제되었습니다.",
        "deleted_agent": deleted_agent
    }


@app.post("/agents/{agent_id}/chat", response_model=AgentChatResponse)
def chat_with_agent(agent_id: int, request: AgentChatRequest):
    check_gemini_client()

    if agent_id not in agents:
        raise HTTPException(
            status_code=404,
            detail="해당 AI 에이전트를 찾을 수 없습니다."
        )

    agent = agents[agent_id]

    prompt = f"""
너는 StudyBridge 플랫폼의 사용자 커스텀 AI 에이전트다.

[에이전트 이름]
{agent["name"]}

[에이전트 역할]
{agent["role"]}

[페르소나]
{agent["persona"]}

[말투]
{agent["tone"]}

[목표]
{agent["goal"]}

[사용자 질문]
{request.message}

위 설정을 반드시 반영해서 한국어로 답변해라.
답변은 너무 길게 늘어놓지 말고, 학습자가 바로 이해할 수 있게 구조화해라.
"""

    response = gemini_client.models.generate_content(
        model="gemini-2.5-flash",
        contents=prompt
    )

    return AgentChatResponse(
        agent_id=agent["id"],
        agent_name=agent["name"],
        role=agent["role"],
        answer=response.text
    )


# =========================
# 주간 활동 API
# =========================

class DailyStudyTime(BaseModel):
    day: str
    hours: float = Field(..., ge=0)


class WeeklyActivityRequest(BaseModel):
    user_id: int
    data: List[DailyStudyTime]


class WeeklyActivityResponse(BaseModel):
    user_id: int
    total_hours: float
    average_hours: float
    attendance_days: int
    data: List[DailyStudyTime]


@app.post("/activity/weekly", response_model=WeeklyActivityResponse)
def weekly_activity(request: WeeklyActivityRequest):
    if len(request.data) != 7:
        raise HTTPException(
            status_code=400,
            detail="주간 활동 데이터는 7일치가 필요합니다."
        )

    total_hours = sum(item.hours for item in request.data)
    attendance_days = sum(1 for item in request.data if item.hours > 0)
    average_hours = total_hours / 7

    return WeeklyActivityResponse(
        user_id=request.user_id,
        total_hours=round(total_hours, 2),
        average_hours=round(average_hours, 2),
        attendance_days=attendance_days,
        data=request.data
    )


# =========================
# 로드맵 생성 API
# =========================

class RoadmapRequest(BaseModel):
    subject: str = Field(..., min_length=1)
    syllabus: str = Field(..., min_length=10)
    level: str = Field(..., pattern="^(초급자|중급자|마스터)$")


class RoadmapResponse(BaseModel):
    role: str
    message: str


@app.post("/ai/roadmap", response_model=RoadmapResponse)
def create_roadmap(request: RoadmapRequest):
    check_gemini_client()

    prompt = f"""
너는 대학생 전용 AI 학습 로드맵 튜터다.

[과목명]
{request.subject}

[학습자 수준]
{request.level}

[강의계획서]
{request.syllabus}

다음 조건에 맞춰 한국어로 학습 로드맵을 생성해라.

조건:
1. 챗봇이 학생에게 설명하듯 자연스럽게 작성
2. {request.level} 수준에 맞게 난이도 조절
3. 1주차부터 15주차까지 주차별 학습 로드맵 작성
4. 각 주차마다 학습 목표, 핵심 개념, 실습/복습 과제 포함
5. 시험 대비 전략 포함
6. 마지막에 추천 학습 순서 요약
"""

    response = gemini_client.models.generate_content(
        model="gemini-2.5-flash",
        contents=prompt
    )

    return RoadmapResponse(
        role="assistant",
        message=response.text
    )


# =========================
# 파일 텍스트 추출
# =========================

def extract_text_from_file(file: UploadFile, content: bytes) -> str:
    filename = file.filename.lower()

    if filename.endswith(".txt"):
        return content.decode("utf-8", errors="ignore")

    if filename.endswith(".pdf"):
        text = ""

        try:
            pdf_file = io.BytesIO(content)
            reader = PdfReader(pdf_file)

            for page in reader.pages:
                page_text = page.extract_text()
                if page_text:
                    text += page_text + "\n"

        except Exception:
            text = ""

        if len(text.strip()) < 10:
            try:
                pdf_document = fitz.open(stream=content, filetype="pdf")
                ocr_text = ""

                for page in pdf_document:
                    pix = page.get_pixmap(dpi=200)

                    image = Image.frombytes(
                        "RGB",
                        [pix.width, pix.height],
                        pix.samples
                    )

                    page_ocr_text = pytesseract.image_to_string(
                        image,
                        lang="kor+eng"
                    )

                    ocr_text += page_ocr_text + "\n"

                text = ocr_text

            except Exception as e:
                raise HTTPException(
                    status_code=500,
                    detail=f"이미지형 PDF OCR 처리 중 오류가 발생했습니다: {str(e)}"
                )

        if len(text.strip()) < 10:
            raise HTTPException(
                status_code=400,
                detail="PDF에서 텍스트를 추출하지 못했습니다. OCR 결과도 비어 있습니다."
            )

        return text

    raise HTTPException(
        status_code=400,
        detail="지원하지 않는 파일 형식입니다. txt 또는 pdf만 업로드 가능합니다."
    )


@app.post("/ai/roadmap-file", response_model=RoadmapResponse)
async def create_roadmap_from_file(
    subject: str = Form(...),
    level: str = Form(...),
    file: UploadFile = File(...)
):
    check_gemini_client()

    if level not in ["초급자", "중급자", "마스터"]:
        raise HTTPException(
            status_code=400,
            detail="level은 초급자, 중급자, 마스터 중 하나여야 합니다."
        )

    content = await file.read()
    syllabus_text = extract_text_from_file(file, content)

    if len(syllabus_text.strip()) < 10:
        raise HTTPException(
            status_code=400,
            detail="강의계획서에서 충분한 텍스트를 추출하지 못했습니다."
        )

    prompt = f"""
너는 대학생 전용 AI 학습 로드맵 튜터다.

[과목명]
{subject}

[학습자 수준]
{level}

[강의계획서 내용]
{syllabus_text}

다음 조건에 맞춰 한국어로 학습 로드맵을 생성해라.

조건:
1. 챗봇이 학생에게 설명하듯 자연스럽게 작성
2. {level} 수준에 맞게 난이도 조절
3. 1주차부터 15주차까지 주차별 학습 로드맵 작성
4. 각 주차마다 학습 목표, 핵심 개념, 실습/복습 과제 포함
5. 중간고사/기말고사 대비 전략 포함
6. 마지막에 추천 학습 순서 요약
7. 너무 딱딱한 보고서 말투가 아니라 학습 도우미 챗봇처럼 작성
"""

    response = gemini_client.models.generate_content(
        model="gemini-2.5-flash",
        contents=prompt
    )

    return RoadmapResponse(
        role="assistant",
        message=response.text
    )