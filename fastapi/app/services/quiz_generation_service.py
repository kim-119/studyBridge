"""
PDF 기반 객관식 퀴즈 생성 서비스.

흐름: S3 로드 → PDF 텍스트 추출 → LLM 퀴즈 생성 (OpenAI 우선, Ollama fallback)
각 단계 실패 시 fallback quiz를 반환하며, 응답 구조는 항상 명세를 준수한다.
difficulty / knowledgeLevel 을 프롬프트에 반영한다.
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


def _fallback_questions(count: int) -> List[QuizQuestion]:
    count = max(1, min(int(count or 3), 10))
    return [_FALLBACK_QUESTIONS[idx % len(_FALLBACK_QUESTIONS)] for idx in range(count)]

# 난이도별 출제 지침 (한국어/영어 모두 허용)
_DIFFICULTY_MAP = {
    "쉬움": "easy", "보통": "medium", "어려움": "hard",
    "easy": "easy", "medium": "medium", "normal": "medium", "hard": "hard",
}

_DIFFICULTY_INSTRUCTIONS = {
    "easy": (
        "쉬운 난이도로 출제한다. "
        "개념 확인, 정의, 핵심 용어 중심의 기본 문제를 만든다. "
        "명확한 정답이 있고 혼동 가능성이 낮은 문제여야 한다."
    ),
    "medium": (
        "보통 난이도로 출제한다. "
        "원리 이해, 개념 비교, 간단한 적용 문제를 포함한다. "
        "어느 정도 학습이 되어 있어야 풀 수 있는 수준이다."
    ),
    "hard": (
        "어려운 난이도로 출제한다. "
        "사례 적용, 함정 선지, 개념 간 연결, 추론이 필요한 문제를 만든다. "
        "깊은 이해 없이는 오답을 고르기 쉬운 문제여야 한다."
    ),
}

_LEVEL_INSTRUCTIONS = {
    "입문": "쉬운 표현, 비유, 전문용어 최소화. 핵심 개념 1~2개만.",
    "학사": "전공 기초 수준. 핵심 용어 사용. 기본 원리 확인.",
    "석사": "구조적 설명, 이론 간 연결, 트레이드오프 포함.",
    "박사": "엄밀한 개념 구분, 한계와 예외 포함, 고급 분석 수준.",
    "전문가": "실무/연구 맥락, 성능·복잡도·트레이드오프 수준.",
}

_QUESTION_TYPE_MAP = {
    "객관식": "multiple_choice",
    "주관식": "short_answer",
    "혼합": "mixed",
    "multiple_choice": "multiple_choice",
    "short_answer": "short_answer",
    "mixed": "mixed",
}

_QUESTION_TYPE_INSTRUCTIONS = {
    "multiple_choice": (
        "모든 문항은 4지선다 객관식이다. options 4개, correctAnswer(0~3), "
        "explanation을 반드시 포함한다."
    ),
    "short_answer": (
        "모든 문항은 주관식이다. options는 빈 배열로 두고, correctAnswer는 null, "
        "answer와 explanation을 반드시 포함한다."
    ),
    "mixed": (
        "객관식과 주관식을 섞어 출제한다. 객관식은 options 4개와 correctAnswer(0~3), "
        "주관식은 options 빈 배열, correctAnswer null, answer를 포함한다. "
        "모든 문항에 explanation을 포함한다."
    ),
}

_LANGUAGE_INSTRUCTIONS = {
    "ko": "한국어로 출제한다.",
    "kr": "한국어로 출제한다.",
    "en": "Write all quiz content in English.",
}

_QUIZ_SYSTEM_PROMPT_TEMPLATE = """\
너는 대학교 강의 자료 기반 퀴즈 출제 전문가다.
다음 규칙을 반드시 지켜라:
1. 정확히 {num_questions}개의 문제를 만든다.
2. 난이도 기준: {difficulty_instruction}
3. 지식수준 기준: {level_instruction}
4. 문항 유형 기준: {question_type_instruction}
5. 해설 깊이: 쉬움은 핵심 근거 1문장, 보통은 개념 연결 1~2문장, 어려움은 오답 함정과 추론 근거까지 설명한다.
6. 언어 기준: {language_instruction}
7. 반드시 아래 JSON 배열 형식으로만 응답한다. 다른 텍스트 없이 JSON만 출력한다.

응답 형식:
[
  {{
    "question": "문제 내용",
    "questionType": "multiple_choice",
    "options": ["보기1", "보기2", "보기3", "보기4"],
    "correctAnswer": 0,
    "answer": "정답 텍스트",
    "explanation": "해설",
    "timeLimitSeconds": 30
  }}
]
"""


def _normalize_question_type(question_type: str) -> str:
    return _QUESTION_TYPE_MAP.get(str(question_type or "객관식").strip(), "multiple_choice")


def _build_system_prompt(
    num_questions: int,
    difficulty: str,
    knowledge_level: str,
    question_type: str = "객관식",
    language: str = "ko",
) -> str:
    diff_key = _DIFFICULTY_MAP.get(difficulty, "medium")
    diff_instr = _DIFFICULTY_INSTRUCTIONS[diff_key]
    level_instr = _LEVEL_INSTRUCTIONS.get(knowledge_level, _LEVEL_INSTRUCTIONS["학사"])
    qtype_key = _normalize_question_type(question_type)
    lang_instr = _LANGUAGE_INSTRUCTIONS.get(str(language or "ko").lower(), "한국어로 출제한다.")
    return _QUIZ_SYSTEM_PROMPT_TEMPLATE.format(
        num_questions=num_questions,
        difficulty_instruction=diff_instr,
        level_instruction=level_instr,
        question_type_instruction=_QUESTION_TYPE_INSTRUCTIONS[qtype_key],
        language_instruction=lang_instr,
    )


def _build_quiz_user_prompt(file_name: str, text: str) -> str:
    context = truncate_context(text, max_chars=2500)
    return (
        f"## 자료명\n{file_name}\n\n"
        f"## 자료 내용\n{context}\n\n"
        "위 자료를 기반으로 JSON 형식으로 퀴즈를 출제하라."
    )


def _generate_with_openai(system_prompt: str, file_name: str, text: str, max_tokens: int) -> str:
    from app.services.openai_client import chat_sync, is_enabled
    if not is_enabled():
        raise RuntimeError("OpenAI API Key가 설정되지 않았습니다.")
    return chat_sync(
        system=system_prompt,
        user=_build_quiz_user_prompt(file_name, text),
        max_tokens=max_tokens,
        temperature=0.3,
    )


def _generate_with_ollama(system_prompt: str, file_name: str, text: str, max_tokens: int) -> str:
    from app.services.ollama_client import ask_ollama, is_ollama_available
    if not is_ollama_available():
        raise RuntimeError("Ollama 서버를 사용할 수 없습니다.")
    return ask_ollama(
        system_prompt=system_prompt,
        user_prompt=_build_quiz_user_prompt(file_name, text),
        max_tokens=max_tokens,
        temperature=0.3,
    )


def _parse_quiz_questions(llm_output: str, max_questions: int, question_type: str) -> List[QuizQuestion]:
    items = safe_parse_quiz_json(llm_output)
    if not items:
        logger.warning("LLM 퀴즈 JSON 파싱 실패. fallback 반환.")
        return _FALLBACK_QUESTIONS[:max_questions]

    requested_type = _normalize_question_type(question_type)
    questions = []
    for index, item in enumerate(items[:max_questions]):
        try:
            raw_type = _normalize_question_type(item.get("questionType") or requested_type)
            if requested_type == "mixed" and not item.get("questionType"):
                raw_type = "multiple_choice" if index % 2 == 0 else "short_answer"

            options = [str(o) for o in item.get("options", [])]
            correct = item.get("correctAnswer")
            if raw_type == "multiple_choice":
                if len(options) != 4:
                    continue
                correct = int(0 if correct is None else correct)
                if not (0 <= correct <= 3):
                    correct = 0
            else:
                options = []
                correct = None

            questions.append(
                QuizQuestion(
                    question=str(item.get("question", "문제를 불러올 수 없습니다.")),
                    questionType=raw_type,
                    options=options,
                    correctAnswer=correct,
                    answer=(str(item.get("answer")) if item.get("answer") is not None else None),
                    explanation=(str(item.get("explanation")) if item.get("explanation") is not None else None),
                    timeLimitSeconds=int(item.get("timeLimitSeconds", 30)),
                )
            )
        except Exception as e:
            logger.warning("문항 파싱 오류 (건너뜀): %s", e)

    return questions if questions else _FALLBACK_QUESTIONS[:max_questions]


def generate_quiz_from_pdf(
    material_id: int,
    s3_key: str,
    file_name: str,
    difficulty: str = "보통",
    knowledge_level: str = "학사",
    num_questions: int = 3,
    question_type: str = "객관식",
    language: str = "ko",
) -> QuizGenerateResponse:
    """
    S3 PDF 기반 퀴즈 생성.
    각 단계 실패 시 fallback으로 안전한 응답 구조를 유지한다.
    """
    num_questions = max(1, min(int(num_questions or 3), 10))
    title = f"[{file_name}] 자료 기반 학습 퀴즈"
    applied_difficulty = _DIFFICULTY_MAP.get(difficulty, "medium")

    # 1. S3 PDF 로드
    pdf_bytes = None
    try:
        from app.services.s3_pdf_loader import load_pdf_from_s3
        pdf_bytes = load_pdf_from_s3(s3_key)
    except Exception as e:
        logger.error("S3 PDF 로드 실패 (fallback 반환): %s", e)
        return QuizGenerateResponse(
            quizTitle=_FALLBACK_QUIZ_TITLE,
            questions=_fallback_questions(num_questions),
            difficulty=applied_difficulty,
            knowledgeLevel=knowledge_level,
        )

    # 2. PDF 텍스트 추출
    pdf_text = None
    try:
        from app.services.pdf_text_extractor import extract_text_from_bytes, is_text_sufficient
        pdf_text = extract_text_from_bytes(pdf_bytes)
        if not is_text_sufficient(pdf_text):
            logger.warning("PDF 텍스트가 너무 짧습니다 (%d자). fallback 반환.", len(pdf_text))
            return QuizGenerateResponse(
                quizTitle=_FALLBACK_QUIZ_TITLE,
                questions=_fallback_questions(num_questions),
                difficulty=applied_difficulty,
                knowledgeLevel=knowledge_level,
            )
    except Exception as e:
        logger.error("PDF 텍스트 추출 실패 (fallback 반환): %s", e)
        return QuizGenerateResponse(
            quizTitle=_FALLBACK_QUIZ_TITLE,
            questions=_fallback_questions(num_questions),
            difficulty=applied_difficulty,
            knowledgeLevel=knowledge_level,
        )

    # 3. LLM 퀴즈 생성 (OpenAI 우선, Ollama fallback)
    system_prompt = _build_system_prompt(num_questions, difficulty, knowledge_level, question_type, language)
    llm_output = None
    try:
        llm_output = _generate_with_openai(system_prompt, file_name, pdf_text, max(1500, num_questions * 450))
        logger.info("OpenAI로 퀴즈 생성 완료 (difficulty=%s, level=%s).", difficulty, knowledge_level)
    except Exception as e:
        logger.warning("OpenAI 퀴즈 생성 실패: %s. Ollama로 fallback합니다.", e)
        try:
            llm_output = _generate_with_ollama(system_prompt, file_name, pdf_text, max(1500, num_questions * 450))
            logger.info("Ollama로 퀴즈 생성 완료.")
        except Exception as e2:
            logger.error("Ollama 퀴즈 생성도 실패: %s. fallback quiz 반환.", e2)

    if not llm_output:
        return QuizGenerateResponse(
            quizTitle=_FALLBACK_QUIZ_TITLE,
            questions=_fallback_questions(num_questions),
            difficulty=applied_difficulty,
            knowledgeLevel=knowledge_level,
        )

    questions = _parse_quiz_questions(llm_output, num_questions, question_type)
    return QuizGenerateResponse(
        quizTitle=title,
        questions=questions,
        difficulty=applied_difficulty,
        knowledgeLevel=knowledge_level,
    )
