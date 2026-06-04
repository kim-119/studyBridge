"""
PDF 기반 객관식 퀴즈 생성 서비스.

흐름: S3 로드 → PDF 텍스트 추출 → LLM 퀴즈 생성 (OpenAI 우선, Ollama fallback)
각 단계 실패 시 fallback quiz를 반환하며, 응답 구조는 항상 명세를 준수한다.
"""
import logging
from typing import List

from app.schemas.quiz_schema import QuizGenerateResponse, QuizQuestion
from app.utils.json_parser import safe_parse_quiz_json
from app.utils.response_cleaner import truncate_context

logger = logging.getLogger(__name__)

_FALLBACK_QUIZ_TITLE = "자료 기반 학습 퀴즈 (기본 안내형)"

_FALLBACK_QUESTIONS: List[QuizQuestion] = [
    QuizQuestion(
        question="다음 중 효과적인 학습 방법으로 알려진 것은?",
        options=[
            "한 번에 몰아서 공부하기",
            "분산 학습(Spaced Repetition) 활용하기",
            "밑줄만 긋고 다시 보지 않기",
            "소리만 듣고 노트 필기 안 하기",
        ],
        correctAnswer=1,
        timeLimitSeconds=30,
    ),
    QuizQuestion(
        question="학습 내용을 장기 기억으로 전환하는 데 가장 효과적인 방법은?",
        options=[
            "한 번 읽고 넘어가기",
            "형광펜으로 중요 부분만 표시하기",
            "자신이 배운 내용을 직접 설명해보기 (인출 연습)",
            "공부 후 바로 자기",
        ],
        correctAnswer=2,
        timeLimitSeconds=30,
    ),
    QuizQuestion(
        question="집중력을 높이기 위한 포모도로 기법에서 기본 집중 시간은?",
        options=["10분", "25분", "45분", "60분"],
        correctAnswer=1,
        timeLimitSeconds=30,
    ),
]

_QUIZ_SYSTEM_PROMPT = """\
너는 대학교 강의 자료 기반 객관식 퀴즈 출제 전문가다.
다음 규칙을 반드시 지켜라:
1. 반드시 4지선다 객관식 문제 3개를 만든다.
2. 학습용으로 적절한 난이도로 출제한다 (너무 쉽거나 너무 어렵지 않게).
3. 보기 4개는 서로 명확히 구분되어야 한다.
4. 정답은 0-indexed로 반환한다 (0, 1, 2, 3 중 하나).
5. 반드시 아래 JSON 형식으로만 응답한다. 다른 텍스트 없이 JSON만 출력한다.

응답 형식:
[
  {
    "question": "문제 내용",
    "options": ["보기1", "보기2", "보기3", "보기4"],
    "correctAnswer": 0,
    "timeLimitSeconds": 30
  }
]
"""


def _build_quiz_user_prompt(file_name: str, text: str) -> str:
    context = truncate_context(text, max_chars=2500)
    return (
        f"## 자료명\n{file_name}\n\n"
        f"## 자료 내용\n{context}\n\n"
        "위 자료를 기반으로 객관식 퀴즈 3개를 JSON 형식으로 출제하라."
    )


def _generate_with_openai(file_name: str, text: str) -> str:
    from app.services.openai_client import chat_sync, is_enabled
    if not is_enabled():
        raise RuntimeError("OpenAI API Key가 설정되지 않았습니다.")
    return chat_sync(
        system=_QUIZ_SYSTEM_PROMPT,
        user=_build_quiz_user_prompt(file_name, text),
        max_tokens=1200,
        temperature=0.3,
    )


def _generate_with_ollama(file_name: str, text: str) -> str:
    from app.services.ollama_client import ask_ollama, is_ollama_available
    if not is_ollama_available():
        raise RuntimeError("Ollama 서버를 사용할 수 없습니다.")
    return ask_ollama(
        system_prompt=_QUIZ_SYSTEM_PROMPT,
        user_prompt=_build_quiz_user_prompt(file_name, text),
        max_tokens=1200,
        temperature=0.3,
    )


def _parse_quiz_questions(llm_output: str, file_name: str) -> List[QuizQuestion]:
    items = safe_parse_quiz_json(llm_output)
    if not items:
        logger.warning("LLM 퀴즈 JSON 파싱 실패. fallback 반환.")
        return _FALLBACK_QUESTIONS

    questions = []
    for item in items[:5]:
        try:
            options = item.get("options", [])
            if len(options) != 4:
                continue
            correct = int(item.get("correctAnswer", 0))
            if not (0 <= correct <= 3):
                correct = 0
            questions.append(
                QuizQuestion(
                    question=str(item.get("question", "문제를 불러올 수 없습니다.")),
                    options=[str(o) for o in options],
                    correctAnswer=correct,
                    timeLimitSeconds=int(item.get("timeLimitSeconds", 30)),
                )
            )
        except Exception as e:
            logger.warning("문항 파싱 오류 (건너뜀): %s", e)

    return questions if questions else _FALLBACK_QUESTIONS


def generate_quiz_from_pdf(
    material_id: int,
    s3_key: str,
    file_name: str,
) -> QuizGenerateResponse:
    """
    S3 PDF 기반 퀴즈 생성.
    각 단계 실패 시 fallback으로 안전한 응답 구조를 유지한다.
    """
    title = f"[{file_name}] 자료 기반 학습 퀴즈"

    # 1. S3 PDF 로드
    pdf_bytes = None
    try:
        from app.services.s3_pdf_loader import load_pdf_from_s3
        pdf_bytes = load_pdf_from_s3(s3_key)
    except Exception as e:
        logger.error("S3 PDF 로드 실패 (fallback 반환): %s", e)
        return QuizGenerateResponse(quizTitle=_FALLBACK_QUIZ_TITLE, questions=_FALLBACK_QUESTIONS)

    # 2. PDF 텍스트 추출
    pdf_text = None
    try:
        from app.services.pdf_text_extractor import extract_text_from_bytes, is_text_sufficient
        pdf_text = extract_text_from_bytes(pdf_bytes)
        if not is_text_sufficient(pdf_text):
            logger.warning("PDF 텍스트가 너무 짧습니다 (%d자). fallback 반환.", len(pdf_text))
            return QuizGenerateResponse(quizTitle=_FALLBACK_QUIZ_TITLE, questions=_FALLBACK_QUESTIONS)
    except Exception as e:
        logger.error("PDF 텍스트 추출 실패 (fallback 반환): %s", e)
        return QuizGenerateResponse(quizTitle=_FALLBACK_QUIZ_TITLE, questions=_FALLBACK_QUESTIONS)

    # 3. LLM 퀴즈 생성 (OpenAI 우선, Ollama fallback)
    llm_output = None
    try:
        llm_output = _generate_with_openai(file_name, pdf_text)
        logger.info("OpenAI로 퀴즈 생성 완료.")
    except Exception as e:
        logger.warning("OpenAI 퀴즈 생성 실패: %s. Ollama로 fallback합니다.", e)
        try:
            llm_output = _generate_with_ollama(file_name, pdf_text)
            logger.info("Ollama로 퀴즈 생성 완료.")
        except Exception as e2:
            logger.error("Ollama 퀴즈 생성도 실패: %s. fallback quiz 반환.", e2)

    if not llm_output:
        return QuizGenerateResponse(quizTitle=_FALLBACK_QUIZ_TITLE, questions=_FALLBACK_QUESTIONS)

    questions = _parse_quiz_questions(llm_output, file_name)
    return QuizGenerateResponse(quizTitle=title, questions=questions)
