"""
오프라인 추론(batch inference) 작업.
자주 묻는 질문, 기본 개념, 박사 수준 depth answer를 사전 생성하여 캐시한다.
검증 통과 결과만 캐시에 저장한다.
"""
import logging
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


def run_batch(
    questions: List[Dict[str, Any]],
    dry_run: bool = True,
) -> Dict[str, Any]:
    """
    오프라인 배치 추론을 실행한다.

    questions 형식:
        [{"question": "...", "domain": "...", "knowledge_level": "...",
          "personality": "...", "mode": "...", "material_id": ...}]

    dry_run=True: 실제 생성 없이 대상 목록만 확인.
    """
    results = {"processed": 0, "cached": 0, "skipped": 0, "errors": 0}

    if dry_run:
        logger.info("오프라인 추론 dry-run: %d개 대상", len(questions))
        results["dry_run"] = True
        results["targets"] = len(questions)
        return results

    for q in questions:
        try:
            question = q.get("question", "")
            domain = q.get("domain", "general_study")
            level = q.get("knowledge_level", "학사")
            personality = q.get("personality")
            mode = q.get("mode", "default")
            material_id = q.get("material_id")

            if not question:
                results["skipped"] += 1
                continue

            # 캐시 hit 확인
            from app.services.offline_answer_cache import get as cache_get
            cached = cache_get(question, domain, level, personality, mode, material_id)
            if cached:
                results["skipped"] += 1
                continue

            # 생성 파이프라인 실행
            answer = _generate_and_verify(q)
            if not answer:
                results["skipped"] += 1
                continue

            # 캐시 저장
            from app.services.offline_answer_cache import set as cache_set
            cache_set(
                question=question,
                domain=domain,
                knowledge_level=level,
                answer_data={"answer": answer},
                personality=personality,
                mode=mode,
                material_id=material_id,
            )
            results["cached"] += 1
            results["processed"] += 1

        except Exception as e:
            logger.warning("오프라인 추론 실패 (건너뜀): %s", e)
            results["errors"] += 1

    logger.info(
        "오프라인 배치 추론 완료: processed=%d cached=%d errors=%d",
        results["processed"], results["cached"], results["errors"],
    )
    return results


def _generate_and_verify(q: Dict[str, Any]) -> Optional[str]:
    """단건 생성 + 검증. 검증 통과 시에만 반환."""
    try:
        from app.services.llm_engine_router import call_primary_llm
        from app.services.generation_config_resolver import resolve as resolve_config
        from app.services.academic_depth_verifier import verify
        from app.services.source_leakage_guard import detect as detect_leakage

        level = q.get("knowledge_level", "학사")
        domain = q.get("domain", "general_study")
        gen_cfg = resolve_config(
            knowledge_level=level,
            domain=domain,
            personality=q.get("personality"),
            mode=q.get("mode", "default"),
        )

        answer = call_primary_llm(
            system_prompt=f"너는 {domain} 분야 {level} 수준 학습 도우미다.",
            user_prompt=q["question"],
            max_tokens=gen_cfg.get("max_tokens", 1000),
            temperature=gen_cfg.get("temperature", 0.45),
        )
        if not answer or answer.startswith("["):
            return None

        # 소스 누출 검사
        leakage, _ = detect_leakage(answer)
        if leakage:
            return None

        # 박사/전문가 수준 depth 검증
        if level in ("박사", "전문가"):
            v = verify(answer, domain, level)
            if v.rewrite_required:
                return None  # 오프라인 배치는 재작성 없이 폐기

        return answer
    except Exception as e:
        logger.warning("오프라인 추론 단건 실패: %s", e)
        return None
