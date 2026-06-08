"""
Teacher 모델(OpenAI/GPT)을 사용하여 증류 후보에 고품질 레이블을 생성한다.
teacher output은 verifier를 통과한 것만 distillation candidate로 사용한다.
현재는 dataset 구조 준비 단계이다. 실제 student 학습은 별도 readiness check 후 수행.
"""
import logging
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


def generate_teacher_label(
    question: str,
    domain: str,
    knowledge_level: str,
    additional_context: str = "",
) -> Optional[str]:
    """
    GPT teacher 모델로 고품질 답변(레이블)을 생성한다.
    verifier 통과 기준을 명시적으로 시스템 프롬프트에 포함한다.
    """
    try:
        from app.services.openai_client import call_openai
        from app.services.academic_depth_verifier import verify

        system = (
            f"너는 {domain} 분야의 {knowledge_level} 수준 학술 답변 생성 전문가다.\n"
            "다음 기준을 엄격히 지켜 답변하라:\n"
            "1. 이론적 배경과 엄밀한 개념 정의를 포함한다.\n"
            "2. 방법론적 한계, 반례, 예외 사례를 포함한다.\n"
            "3. 대안 관점이나 논쟁점을 언급한다.\n"
            "4. 출처명, DOI, 인용 수를 직접 노출하지 않는다.\n"
            "5. 학문 분야에 적합한 깊이의 전문 용어를 사용한다.\n"
        )
        if additional_context:
            user_prompt = f"[참고 컨텍스트]\n{additional_context[:600]}\n\n[질문]\n{question}"
        else:
            user_prompt = question

        answer = call_openai(
            system_prompt=system,
            user_prompt=user_prompt,
            max_tokens=1800,
            temperature=0.4,
        )
        if not answer:
            return None

        # 검증
        verify_result = verify(answer, domain, knowledge_level)
        if verify_result.rewrite_required:
            logger.info(
                "teacher label 검증 미달 (coverage=%.2f): 폐기",
                verify_result.domain_depth_coverage,
            )
            return None

        return answer
    except Exception as e:
        logger.warning("teacher label 생성 실패: %s", e)
        return None


def batch_generate(
    candidates: List[Dict[str, Any]],
    max_items: int = 50,
) -> List[Dict[str, Any]]:
    """
    증류 후보 목록에 teacher 레이블을 일괄 생성한다.
    검증 통과한 것만 반환한다.
    """
    results = []
    processed = 0

    for candidate in candidates[:max_items]:
        try:
            label = generate_teacher_label(
                question=candidate["question"],
                domain=candidate.get("domain", "general_study"),
                knowledge_level=candidate.get("knowledge_level", "박사"),
                additional_context=candidate.get("rag_context", ""),
            )
            if label:
                record = dict(candidate)
                record["teacher_answer"] = label
                record["teacher_model"] = "gpt-4o-mini"
                record["status"] = "teacher_labeled"
                results.append(record)
                processed += 1
        except Exception as e:
            logger.warning("teacher label 처리 실패 (건너뜀): %s", e)

    logger.info("teacher label 생성 완료: %d/%d건", processed, len(candidates[:max_items]))
    return results
