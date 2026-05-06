import os
import io
from typing import List, Dict

import fitz
import pytesseract
from PIL import Image
from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, UploadFile, File, Form
from fastapi.middleware.cors import CORSMiddleware
from openai import OpenAI
from pydantic import BaseModel, Field
from pypdf import PdfReader


# =========================
# 환경변수 로드
# =========================

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
ENV_PATH = os.path.join(BASE_DIR, ".env")

load_dotenv(dotenv_path=ENV_PATH)


# =========================
# Tesseract 설정
# =========================

if os.name == "nt":
    pytesseract.pytesseract.tesseract_cmd = r"C:\Program Files\Tesseract-OCR\tesseract.exe"
else:
    pytesseract.pytesseract.tesseract_cmd = "/usr/bin/tesseract"


# =========================
# FastAPI 앱 생성
# =========================

app = FastAPI(title="StudyBridge FastAPI Server")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# =========================
# OpenAI 설정
# =========================

OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
OPENAI_MODEL = os.getenv("OPENAI_MODEL", "gpt-4o-mini")
OPENAI_MAX_OUTPUT_TOKENS = int(os.getenv("OPENAI_MAX_OUTPUT_TOKENS", "700"))
OPENAI_MAX_INPUT_CHARS = int(os.getenv("OPENAI_MAX_INPUT_CHARS", "12000"))

if OPENAI_API_KEY:
    openai_client = OpenAI(api_key=OPENAI_API_KEY)
else:
    openai_client = None


def check_openai_client():
    if openai_client is None:
        raise HTTPException(
            status_code=500,
            detail="OPENAI_API_KEY가 설정되지 않았습니다. fastapi/.env 파일을 확인하세요."
        )


def trim_prompt(prompt: str) -> str:
    if len(prompt) > OPENAI_MAX_INPUT_CHARS:
        return prompt[:OPENAI_MAX_INPUT_CHARS] + "\n\n[안내] 입력이 너무 길어 일부 내용이 잘렸습니다."
    return prompt


def generate_ai_text(prompt: str) -> str:
    check_openai_client()

    try:
        response = openai_client.responses.create(
            model=OPENAI_MODEL,
            input=trim_prompt(prompt),
            max_output_tokens=OPENAI_MAX_OUTPUT_TOKENS
        )

        if not response.output_text:
            raise HTTPException(
                status_code=500,
                detail="OpenAI 응답 텍스트가 비어 있습니다."
            )

        return response.output_text

    except HTTPException:
        raise

    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"OpenAI 호출 실패: {type(e).__name__}: {str(e)}"
        )


# =========================
# 기본 API
# =========================

@app.get("/")
def root():
    return {"message": "FastAPI running"}


@app.get("/health")
def health():
    return {
        "status": "ok",
        "message": "FastAPI server is running"
    }


@app.get("/debug/openai-key")
def debug_openai_key():
    return {
        "has_key": OPENAI_API_KEY is not None,
        "key_start": OPENAI_API_KEY[:7] if OPENAI_API_KEY else None,
        "model": OPENAI_MODEL,
        "max_output_tokens": OPENAI_MAX_OUTPUT_TOKENS,
        "max_input_chars": OPENAI_MAX_INPUT_CHARS,
        "env_path": ENV_PATH,
        "env_exists": os.path.exists(ENV_PATH)
    }


@app.get("/debug/gemini-key")
def debug_gemini_key_legacy():
    return {
        "message": "Gemini는 제거되었고 OpenAI API를 사용 중입니다.",
        "openai_has_key": OPENAI_API_KEY is not None,
        "openai_key_start": OPENAI_API_KEY[:7] if OPENAI_API_KEY else None,
        "model": OPENAI_MODEL,
        "env_path": ENV_PATH,
        "env_exists": os.path.exists(ENV_PATH)
    }


# =========================
# 기본 AI 질문 API
# =========================

class AiRequest(BaseModel):
    prompt: str = Field(..., min_length=1)


class AiResponse(BaseModel):
    result: str


@app.post("/ai/chat", response_model=AiResponse)
def ask_ai(request: AiRequest):
    result = generate_ai_text(request.prompt)
    return AiResponse(result=result)


@app.post("/ai/gemini", response_model=AiResponse)
def ask_ai_legacy_gemini_route(request: AiRequest):
    result = generate_ai_text(request.prompt)
    return AiResponse(result=result)


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


def get_or_create_agent(agent_id: int) -> dict:
    """
    Spring DB에는 agent_id가 있는데 FastAPI 메모리에는 없는 경우를 대비.
    FastAPI 서버가 재시작되어 agents 딕셔너리가 비어 있어도,
    채팅 요청이 들어오면 해당 agent_id로 기본 에이전트를 자동 생성한다.
    """
    global agent_id_sequence

    if agent_id not in agents:
        agents[agent_id] = {
            "id": agent_id,
            "name": f"AI 에이전트 {agent_id}",
            "role": "학습 도우미",
            "persona": "대학생의 질문을 쉽고 구조적으로 설명하는 AI 튜터",
            "tone": "친절하고 전문적인 말투",
            "goal": "사용자의 학습 이해를 돕는다"
        }

        if agent_id >= agent_id_sequence:
            agent_id_sequence = agent_id + 1

    return agents[agent_id]


@app.post("/agents", response_model=AgentResponse)
def create_agent(request: AgentCreateRequest):
    global agent_id_sequence

    if len(agents) >= MAX_AGENT_COUNT:
        raise HTTPException(
            status_code=400,
            detail="AI 에이전트는 최대 3개까지만 생성할 수 있습니다."
        )

    while agent_id_sequence in agents:
        agent_id_sequence += 1

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
    agent = get_or_create_agent(agent_id)
    return AgentResponse(**agent)


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
    agent = get_or_create_agent(agent_id)

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

    answer = generate_ai_text(prompt)

    return AgentChatResponse(
        agent_id=agent["id"],
        agent_name=agent["name"],
        role=agent["role"],
        answer=answer
    )


# Spring Boot 경로 호환용
@app.post("/api/users/{user_id}/agents/{agent_id}/chat", response_model=AgentChatResponse)
def chat_with_agent_for_spring(
        user_id: int,
        agent_id: int,
        request: AgentChatRequest
):
    return chat_with_agent(agent_id=agent_id, request=request)


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

    message = generate_ai_text(prompt)

    return RoadmapResponse(
        role="assistant",
        message=message
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

    message = generate_ai_text(prompt)

    return RoadmapResponse(
        role="assistant",
        message=message
    )