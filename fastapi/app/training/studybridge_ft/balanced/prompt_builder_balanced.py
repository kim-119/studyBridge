"""셀(domain×subdomain×task×difficulty×persona) → system/user 프롬프트 + 샘플 골격.

스펙 51-55(난이도 깊이), 39-46/85-89(태스크 구조), 66-68(위험도메인), 83-84(제약), 56(메타데이터).
"""
from __future__ import annotations
from .balanced_sampler import Cell
from . import taxonomy as tx

SOURCE_STYLE = "self_distill_qwen3_14b"

# 난이도별 서술 깊이 (스펙 51-55)
DIFFICULTY_DEPTH = {
    "입문": "용어 정의와 쉬운 일상 예시를 중심으로, 전문용어는 풀어서 설명한다.",
    "학사": "전공 기초 개념과 표준적인 문제풀이/적용을 포함한다.",
    "석사": "개념 간 비교, 한계, 방법론, 논문식의 엄밀한 설명을 포함한다.",
    "박사": "반례, 비판적 검토, 실험/연구 설계, 이론적 한계, 엄밀한 검증을 포함한다.",
    "전문가": "실제 시스템 설계·의사결정·리스크 분석과 도메인 전문용어를 포함한다.",
}

# 공통 편향 방지 제약 (스펙 83, 84)
_ANTI_BIAS = (
    "반드시 '{domain} - {subdomain}'의 언어와 사례로만 답하라. "
    "다른 학문(특히 물리의 운동량, 컴퓨터/AI의 인공지능·알고리즘·모델)으로 비유하거나 "
    "주제와 무관하게 그 용어들을 끌어오지 마라."
)


def _risk_note(domain: str) -> str:
    note = tx.RISK_DOMAINS.get(domain)
    return f" 주의: {note}." if note else ""


def _system(cell: Cell) -> str:
    base = "너는 StudyBridge의 전문 학습 도우미다. 자연스럽고 정확한 한국어로 답한다."
    if cell.task_type == "professor" and cell.persona != "default":
        base += (f" 너는 '{cell.persona}' 성격의 교수 1명이다. "
                 f"오직 이 페르소나로만 답하고, 다른 교수나 다른 성격을 끌어들이지 마라.")
    base += " " + DIFFICULTY_DEPTH[cell.difficulty]
    base += _risk_note(cell.domain)
    return base


def _task_instruction(cell: Cell) -> str:
    d, s, diff = cell.domain, cell.subdomain, cell.difficulty
    anti = _ANTI_BIAS.format(domain=d, subdomain=s)
    t = cell.task_type
    if t == "concept":
        body = (f"[{d} · {s} · {diff}] 이 세부주제의 핵심 개념 1개를 다음 순서로 설명하라: "
                "정의 → 원리 → 예시 → 반례 → 흔한 오개념 교정 → 확인 질문.")
    elif t == "quiz":
        body = (f"[{d} · {s} · {diff}] 이 주제로 객관식 4지선다 퀴즈 1개를 JSON으로만 출력하라. "
                'JSON 키: question, choices(4개 배열), answer(정답 인덱스 0~3), '
                'explanation, difficulty, source_hint. 코드블록/설명 없이 JSON 객체 하나만.')
    elif t == "debate":
        body = (f"[{d} · {s} · {diff}] 이 주제의 쟁점 1개를 정하고 다음 구조로 토론하라: "
                "주장 → 반박 → 재반박 → 검증 기준 → 최종 정리. 각 단계를 명확히 표시하라.")
    elif t == "professor":
        body = (f"[{d} · {s} · {diff}] '{cell.persona}' 교수로서 이 주제의 학생 질문 하나를 "
                "스스로 상정하고, 그 성격이 드러나는 말투로 설명하라.")
    elif t == "format_safety":
        body = (f"[{d} · {s} · {diff}] 이 주제를 설명하되, 마크다운/표/리스트/코드블록 형식이 "
                "깨지지 않도록 올바르게 작성하라. 빈 응답·중간 잘림·JSON 깨짐이 없어야 한다.")
    elif t == "summary":
        body = (f"[{d} · {s} · {diff}] 이 주제의 학습자료를 가정하고 다음을 모두 제시하라: "
                "①한 줄 요약 ②핵심어 3~5개와 정의 ③상세 핵심 정리(불릿).")
    elif t == "feedback":
        body = (f"[{d} · {s} · {diff}] 이 주제에서 학생이 자주 하는 오답/오개념 1개를 상정하고, "
                "오답노트식 피드백을 제시하라: 무엇이 틀렸는지 → 왜 → 올바른 이해 → 다음 학습 제안.")
    elif t == "roadmap":
        body = (f"[{d} · {s} · {diff}] 이 주제를 {diff} 수준 학습자가 익히는 4주 학습 로드맵을 "
                "주차별 목표·활동·점검 기준으로 제시하라.")
    else:
        body = f"[{d} · {s} · {diff}] 이 주제를 정확히 설명하라."
    return body + " " + anti


def build(cell: Cell) -> tuple[str, str]:
    """(system, user) 프롬프트."""
    return _system(cell), _task_instruction(cell)


def make_sample(cell: Cell, assistant_text: str) -> dict:
    """ChatML 샘플 + 필수 메타데이터(스펙 56)."""
    system, user = build(cell)
    return {
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
            {"role": "assistant", "content": (assistant_text or "").strip()},
        ],
        "metadata": {
            "domain": cell.domain,
            "subdomain": cell.subdomain,
            "task_type": cell.task_type,
            "difficulty": cell.difficulty,
            "persona": cell.persona,
            "source_style": SOURCE_STYLE,
            "quality_tags": [],
        },
    }
