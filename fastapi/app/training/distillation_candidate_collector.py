"""
증류(distillation) 후보 수집기.
박사 수준 답변 중 depth verifier 통과 + source leakage 없는 것만 수집한다.
수집된 후보는 teacher_label_generator.py에서 처리된다.
현재는 distillation-ready dataset 구조 준비 단계이다.
"""
import logging
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

# 증류 후보 선별 기준
_CRITERIA = {
    "allowed_knowledge_levels": ["박사", "전문가"],
    "min_domain_depth_coverage": 0.70,
    "require_no_source_leakage": True,
    "allowed_modes": ["default", "tikitaka", "debate", "socratic"],
    "min_answer_length": 300,
    "max_answer_length": 4000,
}


def is_eligible(
    answer: str,
    knowledge_level: str,
    domain: str,
    mode: str = "default",
    depth_coverage: float = 0.0,
    source_leakage_detected: bool = False,
) -> tuple[bool, str]:
    """
    증류 후보 적합성을 판단한다.
    반환: (적합_여부, 사유)
    """
    if knowledge_level not in _CRITERIA["allowed_knowledge_levels"]:
        return False, f"knowledge_level={knowledge_level} 제외"

    if len(answer) < _CRITERIA["min_answer_length"]:
        return False, f"답변 너무 짧음 ({len(answer)}자)"

    if len(answer) > _CRITERIA["max_answer_length"]:
        return False, f"답변 너무 김 ({len(answer)}자)"

    if _CRITERIA["require_no_source_leakage"] and source_leakage_detected:
        return False, "출처 노출 감지"

    if depth_coverage < _CRITERIA["min_domain_depth_coverage"]:
        return False, f"domain_depth_coverage 미달 ({depth_coverage:.2f})"

    return True, "eligible"


def build_candidate_record(
    question: str,
    answer: str,
    knowledge_level: str,
    domain: str,
    personality: Optional[str],
    mode: str,
    depth_coverage: float,
    agent_name: Optional[str] = None,
    material_id: Optional[int] = None,
) -> Dict[str, Any]:
    """JSONL 저장용 증류 후보 레코드를 생성한다."""
    return {
        "type": "distillation_candidate",
        "question": question,
        "answer": answer,
        "knowledge_level": knowledge_level,
        "domain": domain,
        "personality": personality,
        "mode": mode,
        "domain_depth_coverage": round(depth_coverage, 3),
        "agent_name": agent_name,
        "material_id": material_id,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "status": "pending_teacher_label",
    }


def collect_to_db(record: Dict[str, Any]) -> bool:
    """DB의 training_candidate 테이블에 증류 후보를 저장한다."""
    try:
        import asyncio
        from app.db.postgres import get_db_pool

        async def _insert():
            pool = get_db_pool()
            if not pool:
                return False
            async with pool.acquire() as conn:
                await conn.execute(
                    """
                    INSERT INTO ai.training_candidate
                        (question, answer, agent_name, personality, knowledge_level,
                         context_type, source_material_id, quality_score, status, review_notes)
                    VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10)
                    ON CONFLICT DO NOTHING
                    """,
                    record["question"],
                    record["answer"],
                    record.get("agent_name", "distillation"),
                    record.get("personality"),
                    record["knowledge_level"],
                    f"distillation:{record['domain']}",
                    record.get("material_id"),
                    int(record["domain_depth_coverage"] * 100),
                    "pending",
                    f"distillation_candidate|domain={record['domain']}|mode={record['mode']}",
                )
            return True

        loop = asyncio.get_event_loop()
        if loop.is_running():
            return False  # 비동기 컨텍스트 내에서는 별도 처리 필요
        return loop.run_until_complete(_insert())
    except Exception as e:
        logger.warning("증류 후보 DB 저장 실패 (계속 진행): %s", e)
        return False
