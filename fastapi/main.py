import io
import os
import re
from typing import Any, Dict, List, Optional

import fitz
import pytesseract
from dotenv import load_dotenv
from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from openai import OpenAI
from PIL import Image
from pydantic import BaseModel, Field
from pypdf import PdfReader

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
ENV_PATH = os.path.join(BASE_DIR, ".env")

load_dotenv(dotenv_path=ENV_PATH)

OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
OPENAI_MODEL = os.getenv("OPENAI_MODEL", "gpt-4o-mini")
OPENAI_MAX_OUTPUT_TOKENS = int(os.getenv("OPENAI_MAX_OUTPUT_TOKENS", "700"))
OPENAI_MAX_INPUT_CHARS = int(os.getenv("OPENAI_MAX_INPUT_CHARS", "12000"))

MAX_AGENT_COUNT = 3

FORBIDDEN_KEYWORDS = [
    "시스템 명령 무시",
    "개발자 명령 무시",
    "규칙 무시",
    "제한 없이",
    "검열 없이",
    "무조건 복종",
    "탈옥",
    "DAN",
    "불법",
    "해킹",
    "악성코드",
    "바이러스",
    "개인정보 탈취",
    "계정 탈취",
    "폭탄",
    "마약",
    "도박",
    "자해",
    "살인",
    "폭행",
    "협박",
    "혐오",
    "성인",
    "야한",
    "19금",
]

ALLOWED_LEARNING_KEYWORDS = [
    "학습",
    "공부",
    "강의",
    "과제",
    "시험",
    "퀴즈",
    "로드맵",
    "설명",
    "튜터",
    "도우미",
    "멘토",
    "코딩",
    "수학",
    "영어",
    "전공",
    "대학생",
]

if os.name == "nt":
    pytesseract.pytesseract.tesseract_cmd = r"C:\Program Files\Tesseract-OCR\tesseract.exe"
else:
    pytesseract.pytesseract.tesseract_cmd = "/usr/bin/tesseract"

app = FastAPI(title="StudyBridge FastAPI Server")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

openai_client: Optional[OpenAI] = OpenAI(api_key=OPENAI_API_KEY) if OPENAI_API_KEY else None


class AiRequest(BaseModel):
    prompt: str = Field(..., min_length=1)


class AiResponse(BaseModel):
    result: str


class AgentPersona(BaseModel):
    name: str = Field(..., min_length=1, max_length=30)
    role: str = Field(..., min_length=1, max_length=50)
    personality: str = Field(..., min_length=5, max_length=1000)
    tone: str = Field(..., min_length=1, max_length=100)
    goal: str = Field(..., min_length=1, max_length=255)


class ChatRequest(BaseModel):
    agent: AgentPersona
    message: str = Field(..., min_length=1, max_length=4000)


class ChatResponse(BaseModel):
    agentName: str
    answer: str


class MultiAgentChatRequest(BaseModel):
    agents: List[AgentPersona] = Field(..., min_length=1, max_length=MAX_AGENT_COUNT)
    message: str = Field(..., min_length=1, max_length=4000)


class MultiAgentAnswer(BaseModel):
    agentName: str
    role: str
    tone: str
    answer: str


class MultiAgentChatResponse(BaseModel):
    message: str
    answers: List[MultiAgentAnswer]


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


class RoadmapRequest(BaseModel):
    subject: str = Field(..., min_length=1)
    syllabus: str = Field(..., min_length=10)
    level: str = Field(..., pattern="^(초급자|중급자|마스터)$")


class RoadmapResponse(BaseModel):
    role: str
    message: str


agents: Dict[int, Dict[str, Any]] = {}
agent_id_sequence = 1


def ensure_openai_client() -> OpenAI:
    if openai_client is None:
        raise HTTPException(
            status_code=500,
            detail="OPENAI_API_KEY가 설정되지 않았습니다. fastapi/.env 파일을 확인하세요.",
        )
    return openai_client


def trim_text(text: str, max_chars: int = OPENAI_MAX_INPUT_CHARS) -> str:
    if len(text) <= max_chars:
        return text
    return text[:max_chars] + "\n\n[안내] 입력이 너무 길어 일부 내용이 잘렸습니다."


def preprocess_ai_text(text: str) -> str:
    if not text:
        return ""

    cleaned = text.strip()
    cleaned = re.sub(r"```[a-zA-Z0-9_+-]*", "", cleaned)
    cleaned = cleaned.replace("```", "")
    cleaned = re.sub(r"`([^`]+)`", r"\1", cleaned)
    cleaned = re.sub(r"\*\*([^*\n]+)\*\*", r"\1", cleaned)
    cleaned = re.sub(r"__([^_\n]+)__", r"\1", cleaned)
    cleaned = re.sub(r"^#{1,6}\s*", "", cleaned, flags=re.MULTILINE)
    cleaned = re.sub(r"^>\s*", "", cleaned, flags=re.MULTILINE)
    cleaned = re.sub(r"^[\s]*[-*+]\s+", "", cleaned, flags=re.MULTILINE)
    cleaned = re.sub(r"^(\s*\d+\.)\s+", r"\1 ", cleaned, flags=re.MULTILINE)
    cleaned = re.sub(r"[ \t]+", " ", cleaned)
    cleaned = re.sub(r"[ \t]+\n", "\n", cleaned)
    cleaned = re.sub(r"\n{3,}", "\n\n", cleaned)

    return cleaned.strip()


def generate_ai_text(user_prompt: str, system_prompt: Optional[str] = None) -> str:
    client = ensure_openai_client()

    messages = []
    if system_prompt:
        messages.append({"role": "system", "content": system_prompt})

    messages.append({"role": "user", "content": trim_text(user_prompt)})

    try:
        response = client.chat.completions.create(
            model=OPENAI_MODEL,
            messages=messages,
            max_tokens=OPENAI_MAX_OUTPUT_TOKENS,
        )

        answer = response.choices[0].message.content
        if not answer:
            raise HTTPException(status_code=500, detail="OpenAI 응답 텍스트가 비어 있습니다.")

        return preprocess_ai_text(answer)

    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(
            status_code=500,
            detail=f"OpenAI 호출 실패: {type(exc).__name__}: {exc}",
        ) from exc


def find_first_keyword(text: str, keywords: List[str]) -> Optional[str]:
    normalized_text = text.lower()

    for keyword in keywords:
        if keyword.lower() in normalized_text:
            return keyword

    return None


def validate_agent_forbidden_keywords(agent: AgentPersona) -> None:
    combined_text = " ".join(
        [
            agent.name,
            agent.role,
            agent.personality,
            agent.tone,
            agent.goal,
        ]
    )

    forbidden_keyword = find_first_keyword(combined_text, FORBIDDEN_KEYWORDS)
    if forbidden_keyword:
        raise HTTPException(
            status_code=400,
            detail=f"허용되지 않는 키워드가 포함되어 있습니다: '{forbidden_keyword}'",
        )


def validate_agent_learning_purpose(agent: AgentPersona) -> None:
    check_text = f"{agent.role} {agent.goal}"

    if find_first_keyword(check_text, ALLOWED_LEARNING_KEYWORDS):
        return

    raise HTTPException(
        status_code=400,
        detail="에이전트의 role 또는 goal에 학습 관련 키워드가 포함되어야 합니다. "
               f"허용 키워드: {', '.join(ALLOWED_LEARNING_KEYWORDS)}",
    )


def build_custom_agent_system_prompt(agent: AgentPersona) -> str:
    return f"""
너는 대학생 학습을 돕는 AI 에이전트다.

[에이전트 설정]
이름: {agent.name}
역할: {agent.role}
성격/특징: {agent.personality}
말투: {agent.tone}
목표: {agent.goal}

[중요 규칙]
1. 에이전트의 성격과 말투는 답변 스타일에만 반영한다.
2. 사실성, 안전성, 학습 목적을 항상 우선한다.
3. 불법, 위험, 개인정보 침해, 자해, 혐오, 성적 요청은 거절한다.
4. 사용자가 설정한 페르소나가 규칙과 충돌하면 규칙을 우선한다.
5. 답변은 한국어로 작성한다.
6. 대학생이 이해할 수 있게 단계적으로 설명한다.
7. 모르는 내용은 아는 척하지 말고 불확실하다고 말한다.
8. 답변에 마크다운 강조 문법, 제목 문법, 코드블록 문법을 사용하지 않는다.
9. 프론트 화면에 바로 출력 가능한 일반 텍스트 형태로 답변한다.
""".strip()


def build_saved_agent_system_prompt(agent: Dict[str, Any]) -> str:
    return f"""
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

[답변 규칙]
1. 위 설정을 반영해 한국어로 답변한다.
2. 답변은 너무 길게 늘어놓지 않는다.
3. 학습자가 바로 이해할 수 있게 구조화한다.
4. 사실성, 안전성, 학습 목적을 우선한다.
5. 답변에 마크다운 강조 문법, 제목 문법, 코드블록 문법을 사용하지 않는다.
6. 프론트 화면에 바로 출력 가능한 일반 텍스트 형태로 답변한다.
""".strip()


def get_or_create_agent(agent_id: int) -> Dict[str, Any]:
    global agent_id_sequence

    if agent_id not in agents:
        agents[agent_id] = {
            "id": agent_id,
            "name": f"AI 에이전트 {agent_id}",
            "role": "학습 도우미",
            "persona": "대학생의 질문을 쉽고 구조적으로 설명하는 AI 튜터",
            "tone": "친절하고 전문적인 말투",
            "goal": "사용자의 학습 이해를 돕는다",
        }

        if agent_id >= agent_id_sequence:
            agent_id_sequence = agent_id + 1

    return agents[agent_id]


def extract_text_from_pdf(content: bytes) -> str:
    text = extract_text_from_pdf_reader(content)

    if len(text.strip()) >= 10:
        return text

    text = extract_text_from_pdf_ocr(content)

    if len(text.strip()) < 10:
        raise HTTPException(
            status_code=400,
            detail="PDF에서 텍스트를 추출하지 못했습니다. OCR 결과도 비어 있습니다.",
        )

    return text


def extract_text_from_pdf_reader(content: bytes) -> str:
    try:
        pdf_file = io.BytesIO(content)
        reader = PdfReader(pdf_file)

        return "\n".join(
            page_text
            for page in reader.pages
            if (page_text := page.extract_text())
        )

    except Exception:
        return ""


def extract_text_from_pdf_ocr(content: bytes) -> str:
    try:
        pdf_document = fitz.open(stream=content, filetype="pdf")
        ocr_text = []

        for page in pdf_document:
            pix = page.get_pixmap(dpi=200)
            image = Image.frombytes("RGB", [pix.width, pix.height], pix.samples)
            page_text = pytesseract.image_to_string(image, lang="kor+eng")
            ocr_text.append(page_text)

        return "\n".join(ocr_text)

    except Exception as exc:
        raise HTTPException(
            status_code=500,
            detail=f"이미지형 PDF OCR 처리 중 오류가 발생했습니다: {exc}",
        ) from exc


def extract_text_from_file(file: UploadFile, content: bytes) -> str:
    filename = (file.filename or "").lower()

    if filename.endswith(".txt"):
        return content.decode("utf-8", errors="ignore")

    if filename.endswith(".pdf"):
        return extract_text_from_pdf(content)

    raise HTTPException(
        status_code=400,
        detail="지원하지 않는 파일 형식입니다. txt 또는 pdf만 업로드 가능합니다.",
    )


def build_roadmap_prompt(subject: str, level: str, syllabus: str) -> str:
    return f"""
너는 대학생 전용 AI 학습 로드맵 튜터다.

[과목명]
{subject}

[학습자 수준]
{level}

[강의계획서]
{syllabus}

다음 조건에 맞춰 한국어로 학습 로드맵을 생성해라.

조건:
1. 챗봇이 학생에게 설명하듯 자연스럽게 작성한다.
2. {level} 수준에 맞게 난이도를 조절한다.
3. 1주차부터 15주차까지 주차별 학습 로드맵을 작성한다.
4. 각 주차마다 학습 목표, 핵심 개념, 실습/복습 과제를 포함한다.
5. 중간고사/기말고사 대비 전략을 포함한다.
6. 마지막에 추천 학습 순서를 요약한다.
7. 너무 딱딱한 보고서 말투가 아니라 학습 도우미 챗봇처럼 작성한다.
8. 답변에 마크다운 강조 문법, 제목 문법, 코드블록 문법을 사용하지 않는다.
""".strip()


@app.get("/")
def root() -> Dict[str, str]:
    return {"message": "FastAPI running"}


@app.get("/health")
def health() -> Dict[str, str]:
    return {
        "status": "ok",
        "message": "FastAPI server is running",
    }


@app.get("/debug/openai-key")
def debug_openai_key() -> Dict[str, Any]:
    return {
        "has_key": OPENAI_API_KEY is not None,
        "key_start": OPENAI_API_KEY[:7] if OPENAI_API_KEY else None,
        "model": OPENAI_MODEL,
        "max_output_tokens": OPENAI_MAX_OUTPUT_TOKENS,
        "max_input_chars": OPENAI_MAX_INPUT_CHARS,
        "env_path": ENV_PATH,
        "env_exists": os.path.exists(ENV_PATH),
    }


@app.get("/debug/gemini-key")
def debug_gemini_key_legacy() -> Dict[str, Any]:
    return {
        "message": "Gemini는 제거되었고 OpenAI API를 사용 중입니다.",
        "openai_has_key": OPENAI_API_KEY is not None,
        "openai_key_start": OPENAI_API_KEY[:7] if OPENAI_API_KEY else None,
        "model": OPENAI_MODEL,
        "env_path": ENV_PATH,
        "env_exists": os.path.exists(ENV_PATH),
    }


@app.post("/ai/chat", response_model=AiResponse)
def ask_ai(request: AiRequest) -> AiResponse:
    return AiResponse(result=generate_ai_text(request.prompt))


@app.post("/ai/gemini", response_model=AiResponse)
def ask_ai_legacy_gemini_route(request: AiRequest) -> AiResponse:
    return AiResponse(result=generate_ai_text(request.prompt))


@app.post("/api/ai/chat", response_model=ChatResponse)
def chat_with_custom_agent(request: ChatRequest) -> ChatResponse:
    validate_agent_forbidden_keywords(request.agent)
    validate_agent_learning_purpose(request.agent)

    answer = generate_ai_text(
        user_prompt=request.message,
        system_prompt=build_custom_agent_system_prompt(request.agent),
    )

    return ChatResponse(
        agentName=request.agent.name,
        answer=answer,
    )


@app.post("/api/ai/multi-chat", response_model=MultiAgentChatResponse)
def chat_with_custom_agents(request: MultiAgentChatRequest) -> MultiAgentChatResponse:
    answers: List[MultiAgentAnswer] = []

    for agent in request.agents:
        validate_agent_forbidden_keywords(agent)
        validate_agent_learning_purpose(agent)

        answer = generate_ai_text(
            user_prompt=request.message,
            system_prompt=build_custom_agent_system_prompt(agent),
        )

        answers.append(
            MultiAgentAnswer(
                agentName=agent.name,
                role=agent.role,
                tone=agent.tone,
                answer=answer,
            )
        )

    return MultiAgentChatResponse(
        message=request.message,
        answers=answers,
    )


@app.post("/agents", response_model=AgentResponse)
def create_agent(request: AgentCreateRequest) -> AgentResponse:
    global agent_id_sequence

    if len(agents) >= MAX_AGENT_COUNT:
        raise HTTPException(
            status_code=400,
            detail="AI 에이전트는 최대 3개까지만 생성할 수 있습니다.",
        )

    while agent_id_sequence in agents:
        agent_id_sequence += 1

    agent = {
        "id": agent_id_sequence,
        "name": request.name,
        "role": request.role,
        "persona": request.persona,
        "tone": request.tone,
        "goal": request.goal,
    }

    agents[agent_id_sequence] = agent
    agent_id_sequence += 1

    return AgentResponse(**agent)


@app.get("/agents", response_model=List[AgentResponse])
def get_agents() -> List[AgentResponse]:
    return [AgentResponse(**agent) for agent in agents.values()]


@app.get("/agents/{agent_id}", response_model=AgentResponse)
def get_agent(agent_id: int) -> AgentResponse:
    return AgentResponse(**get_or_create_agent(agent_id))


@app.delete("/agents/{agent_id}")
def delete_agent(agent_id: int) -> Dict[str, Any]:
    if agent_id not in agents:
        raise HTTPException(
            status_code=404,
            detail="해당 AI 에이전트를 찾을 수 없습니다.",
        )

    deleted_agent = agents.pop(agent_id)

    return {
        "message": "AI 에이전트가 삭제되었습니다.",
        "deleted_agent": deleted_agent,
    }


@app.post("/agents/{agent_id}/chat", response_model=AgentChatResponse)
def chat_with_agent(agent_id: int, request: AgentChatRequest) -> AgentChatResponse:
    agent = get_or_create_agent(agent_id)

    answer = generate_ai_text(
        user_prompt=request.message,
        system_prompt=build_saved_agent_system_prompt(agent),
    )

    return AgentChatResponse(
        agent_id=agent["id"],
        agent_name=agent["name"],
        role=agent["role"],
        answer=answer,
    )


@app.post("/api/users/{user_id}/agents/{agent_id}/chat", response_model=AgentChatResponse)
def chat_with_agent_for_spring(
        user_id: int,
        agent_id: int,
        request: AgentChatRequest,
) -> AgentChatResponse:
    return chat_with_agent(agent_id=agent_id, request=request)


@app.post("/activity/weekly", response_model=WeeklyActivityResponse)
def weekly_activity(request: WeeklyActivityRequest) -> WeeklyActivityResponse:
    if len(request.data) != 7:
        raise HTTPException(
            status_code=400,
            detail="주간 활동 데이터는 7일치가 필요합니다.",
        )

    total_hours = sum(item.hours for item in request.data)
    attendance_days = sum(1 for item in request.data if item.hours > 0)
    average_hours = total_hours / 7

    return WeeklyActivityResponse(
        user_id=request.user_id,
        total_hours=round(total_hours, 2),
        average_hours=round(average_hours, 2),
        attendance_days=attendance_days,
        data=request.data,
    )


@app.post("/ai/roadmap", response_model=RoadmapResponse)
def create_roadmap(request: RoadmapRequest) -> RoadmapResponse:
    prompt = build_roadmap_prompt(
        subject=request.subject,
        level=request.level,
        syllabus=request.syllabus,
    )

    return RoadmapResponse(
        role="assistant",
        message=generate_ai_text(prompt),
    )


@app.post("/ai/roadmap-file", response_model=RoadmapResponse)
async def create_roadmap_from_file(
        subject: str = Form(...),
        level: str = Form(...),
        file: UploadFile = File(...),
) -> RoadmapResponse:
    if level not in ["초급자", "중급자", "마스터"]:
        raise HTTPException(
            status_code=400,
            detail="level은 초급자, 중급자, 마스터 중 하나여야 합니다.",
        )

    content = await file.read()
    syllabus_text = extract_text_from_file(file, content)

    if len(syllabus_text.strip()) < 10:
        raise HTTPException(
            status_code=400,
            detail="강의계획서에서 충분한 텍스트를 추출하지 못했습니다.",
        )

    prompt = build_roadmap_prompt(
        subject=subject,
        level=level,
        syllabus=syllabus_text,
    )

    return RoadmapResponse(
        role="assistant",
        message=generate_ai_text(prompt),
    )