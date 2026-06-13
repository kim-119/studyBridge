"""
PDF/DOCX 자료 본문 기반 퀴즈 생성 서비스 (source_mode = PDF_BASED).

핵심 분리 원칙:
  - 퀴즈는 PDF/DOCX 자료 본문(document_text/core/detailed/summary/keywords) 기준이다.
  - 로드맵 day 를 기준으로 퀴즈를 만들지 않는다. roadmap_context / ROADMAP_ONLY 강제 없음.
  - 로드맵은 '플래너 생성'의 기준이며 퀴즈와 source 가 다르다.

난이도별 provider 비중 (일반 강의자료 PDF):
  - easy   : Qwen3B 100%
  - normal : Qwen3B 80% + OpenAI 20%
  - hard   : Qwen3B 50% + OpenAI/Wikipedia 50% (Wikipedia 실패 시 OpenAI 가 흡수)

강의계획서/OT(SYLLABUS/LECTURE_PLAN) 자료:
  - 교수/행정정보는 metadata_admin_info 로 분리하고 퀴즈 핵심 문제로 만들지 않는다.
  - 퀴즈는 주차별 강의 주제/학습 내용/과목 흐름 기준으로 만든다.
  - 모든 난이도에서 Qwen3B 100% (OpenAI/Wikipedia 미사용).

모델/temperature/max_tokens/provider 사용 여부는 .env 로 제어(하드코딩 금지).
"""
from __future__ import annotations

import logging
import os
import re
from typing import Any, Dict, List, Optional, Tuple

from app.services.material_summary_builder import sanitize_markdown_text
from app.services.quiz_difficulty_policy import (
    normalize_difficulty,
    difficulty_policy_text,
    build_hard_question,
    _HARD_SIGNALS,
)

logger = logging.getLogger(__name__)

# ── 환경 설정 ─────────────────────────────────────────────────────────────────
QUIZ_MAX_TOKENS = int(os.getenv("AI_QUIZ_MAX_TOKENS", "1600"))
QUIZ_CONTEXT_MAX = int(os.getenv("AI_QUIZ_CONTEXT_MAX_CHARS", "6000"))
HARD_MIN_LEN = int(os.getenv("AI_QUIZ_HARD_MIN_LEN", "80"))

SOURCE_MODE = "PDF_BASED"

# 문항 수 정책 (스펙 I): 최소 5, 최대 20, 기본 10. streaming/non-stream 공통.
QUIZ_MIN_COUNT = int(os.getenv("AI_QUIZ_MIN_COUNT", "5"))
QUIZ_MAX_COUNT = int(os.getenv("AI_QUIZ_MAX_COUNT", "20"))
QUIZ_DEFAULT_COUNT = int(os.getenv("AI_QUIZ_DEFAULT_COUNT", "10"))
# streaming batch 단위 (스펙 J): 5문항씩 생성 → 검증 → 통과분 누적.
QUIZ_BATCH_SIZE = int(os.getenv("AI_QUIZ_BATCH_SIZE", "5"))
# PDF 텍스트가 이 길이 미만이면(그리고 강의계획서 주차 정보도 없으면) 일반 지식 fallback 으로
# 속이지 않고 PDF_TEXT_INSUFFICIENT 로 명확히 실패한다. (난이도 낮춤/기본문제 대체 금지)
QUIZ_MIN_CONTEXT_CHARS = int(os.getenv("AI_QUIZ_MIN_CONTEXT_CHARS", "200"))

# 어떤 난이도에서도 절대 생성하면 안 되는 저품질 generic 템플릿/토큰 (스펙 [2],[3])
_BANNED_QUESTION_SUBSTR = [
    "세부 핵심 내용",
    "다음 중 올바른 것은",
    "자료의 핵심 내용은",
    "핵심 개념은 무엇인가",
    "핵심 개념을 가장 잘 설명",
    "...",
    "…",
]

# ── 강의계획서 판별 키워드 (A) ────────────────────────────────────────────────
_SYLLABUS_KEYWORDS = [
    "강의계획서", "수업계획서", "교과목명", "담당교수", "교수명", "주차별 강의계획",
    "주차별 수업계획", "주차별 강의", "평가방법", "평가비율", "수업목표", "강의개요",
    "교과목 개요", "수업 운영", "성적평가", "강의 일정", "강의일정",
]
_WEEK_HINT = re.compile(r"(\d{1,2})\s*주차")

# 행정정보(metadata) 키워드/패턴 (B-1)
_ADMIN_FIELDS = [
    ("professor_name", ["담당교수", "교수명", "교수 성명", "담당 교수", "강사명"]),
    ("office", ["연구실", "사무실", "교수 연구실", "교수 사무실", "office"]),
    ("email", ["이메일", "e-mail", "email", "메일주소"]),
    ("phone", ["연락처", "전화번호", "phone", "tel", "휴대폰"]),
    ("office_hours", ["상담시간", "상담 시간", "office hour", "면담시간"]),
    ("classroom", ["강의실", "수업 장소", "강의 장소"]),
    ("class_time", ["수업시간", "수업 시간", "강의시간"]),
    ("course_code", ["과목코드", "교과목코드", "학수번호", "과목 코드"]),
    ("credit", ["학점", "credit"]),
    ("evaluation_ratio", ["평가비율", "평가 비율", "성적 비율", "출석 비율", "평가방법"]),
    ("attendance_policy", ["출석정책", "출석 정책", "결석", "지각 처리"]),
    ("textbook", ["교재명", "주교재", "교재", "참고도서"]),
]

# 금지 퀴즈(행정정보 암기) 패턴 (C)
_ADMIN_QUESTION_PATTERNS = [
    re.compile(r"교수.{0,6}(성명|이름|누구|나이|연락처|이메일|전공)"),
    re.compile(r"담당\s*교수"),
    re.compile(r"(연구실|사무실).{0,6}(어디|위치|호실|주소)"),
    re.compile(r"이메일.{0,6}(무엇|뭐|어떻게)"),
    re.compile(r"상담\s*시간.{0,6}(언제|몇)"),
    re.compile(r"강의실.{0,6}(어디|몇|위치)"),
    re.compile(r"(평가\s*비율|평가비율).{0,8}(몇|퍼센트|얼마|비율)"),
    re.compile(r"과목\s*코드"),
    re.compile(r"학점.{0,6}(몇|얼마)"),
    re.compile(r"교재.{0,6}(무엇|뭐|어떤 책)"),
]

# 강의계획서 hard 가 가져야 할 커리큘럼 흐름 신호어 (실무 시나리오 대신)
_SYLLABUS_FLOW_SIGNALS = [
    "흐름", "순서", "선행", "커리큘럼", "주차", "전체", "구조", "초반", "중반", "후반",
    "이후", "단계", "연결", "구성",
]


# ── 요청/컨텍스트 정규화 ──────────────────────────────────────────────────────
def _g(d: Dict[str, Any], *keys: str) -> Any:
    for k in keys:
        v = d.get(k)
        if v not in (None, "", []):
            return v
    return None


def build_material_context(req: Dict[str, Any]) -> Dict[str, Any]:
    """요청에서 PDF source 들을 정규화해 우선순위 컨텍스트를 만든다."""
    document_text = str(_g(req, "document_text", "documentText", "pdf_text", "text") or "")
    core = str(_g(req, "core_content_text", "coreContentText", "core_content") or "")
    detailed = str(_g(req, "detailed_content_text", "detailedContentText", "detailed_content") or "")
    summary = str(_g(req, "summary", "summary_text") or "")
    kw_raw = _g(req, "keywords", "keyword_list") or []
    keywords = [str(k).strip() for k in kw_raw if str(k).strip()] if isinstance(kw_raw, list) else []
    title = str(_g(req, "material_title", "materialTitle", "title", "file_name") or "")

    # B 우선순위: document_text > core > detailed > summary > keywords > title
    based_on: List[str] = []
    parts: List[str] = []
    if document_text.strip():
        based_on.append("document_text"); parts.append(document_text)
    if core.strip():
        based_on.append("core_content_text"); parts.append(core)
    if detailed.strip():
        based_on.append("detailed_content_text"); parts.append(detailed)
    if summary.strip():
        based_on.append("summary"); parts.append(summary)
    if not parts and keywords:
        based_on.append("keywords"); parts.append(" / ".join(keywords))

    context = "\n\n".join(parts)[:QUIZ_CONTEXT_MAX]
    has_pdf_context = bool(context.strip()) and bool(based_on)
    return {
        "document_text": document_text,
        "core": core,
        "detailed": detailed,
        "summary": summary,
        "keywords": keywords,
        "title": title,
        "context": context,
        "based_on": based_on or (["material_title"] if title.strip() else []),
        "has_pdf_context": has_pdf_context,
        "material_id": _g(req, "material_id", "materialId"),
    }


# ── 강의계획서 판별 + 정보 분리 (A, B) ────────────────────────────────────────
def detect_document_type(ctx: Dict[str, Any]) -> str:
    """SYLLABUS / LECTURE_PLAN / GENERAL 판별."""
    blob = "\n".join([ctx.get("title", ""), ctx.get("context", "")]).lower()
    title = (ctx.get("title") or "").lower()
    kw_hits = sum(1 for k in _SYLLABUS_KEYWORDS if k.lower() in blob)
    week_hits = len(set(_WEEK_HINT.findall(blob)))
    if "강의계획서" in title or "수업계획서" in title:
        return "SYLLABUS"
    # 주차별 계획 + 행정 키워드가 같이 보이면 강의계획서
    if kw_hits >= 2 and week_hits >= 2:
        return "SYLLABUS"
    if kw_hits >= 1 and week_hits >= 3:
        return "LECTURE_PLAN"
    return "GENERAL"


def extract_weekly_plan(text: str) -> List[Dict[str, Any]]:
    """'N주차 ... 주제' 형태의 주차별 강의 계획을 추출한다. [{week, topic}]."""
    plan: Dict[int, str] = {}
    for line in (text or "").splitlines():
        m = _WEEK_HINT.search(line)
        if not m:
            continue
        week = int(m.group(1))
        # 주차 표기 뒤의 주제 텍스트
        after = line[m.end():]
        topic = re.sub(r"^[\s:.\-–—|]*", "", after).strip()
        topic = re.sub(r"(강의\s*주제|강의\s*내용|수업\s*내용|학습\s*내용|주제)\s*[:：-]?\s*", "", topic).strip()
        topic = sanitize_markdown_text(topic)[:60]
        if topic and 1 <= week <= 20 and week not in plan:
            plan[week] = topic
    return [{"week": w, "topic": plan[w]} for w in sorted(plan)]


def split_syllabus_content(ctx: Dict[str, Any]) -> Tuple[Dict[str, str], Dict[str, Any]]:
    """행정정보(metadata_admin_info)와 학습내용(academic_learning_content)을 분리한다."""
    text = ctx.get("context", "") or ""
    admin: Dict[str, str] = {}
    for field, kws in _ADMIN_FIELDS:
        for line in text.splitlines():
            low = line.lower()
            if any(k.lower() in low for k in kws):
                val = sanitize_markdown_text(line).strip()
                if val and field not in admin:
                    admin[field] = val[:120]
                break

    weekly = extract_weekly_plan(text)
    academic = {
        "weekly_schedule": weekly,
        "lecture_topics": [w["topic"] for w in weekly],
        "keywords": ctx.get("keywords", []),
        "title": ctx.get("title", ""),
    }
    return admin, academic


def _strip_admin_lines(text: str) -> str:
    """행정정보가 들어간 줄을 학습 컨텍스트에서 걷어낸다(로드맵/퀴즈 공용)."""
    all_kws = [k for _, kws in _ADMIN_FIELDS for k in kws]
    kept = []
    for line in (text or "").splitlines():
        low = line.lower()
        if any(k.lower() in low for k in all_kws) and not _WEEK_HINT.search(line):
            continue  # 주차 표기가 없는 순수 행정정보 줄만 제거
        kept.append(line)
    return "\n".join(kept)


def is_admin_question(question: str) -> bool:
    """행정정보 암기형 금지 문제인지 판별 (C)."""
    q = (question or "")
    return any(p.search(q) for p in _ADMIN_QUESTION_PATTERNS)


# ── provider_policy (C/D, 추가 프롬프트) ──────────────────────────────────────
def resolve_provider_policy(difficulty: str, is_syllabus: bool, wikipedia_used: bool) -> Dict[str, Any]:
    diff = normalize_difficulty(difficulty)
    if is_syllabus:
        return {
            "difficulty": diff, "qwen_ratio": 1.0, "openai_ratio": 0.0,
            "wikipedia_ratio": 0.0, "wikipedia_used": False,
            "description": "강의계획서 유형이므로 Qwen3B만 사용하여 PDF의 주차별 학습 내용 기반으로 생성",
        }
    if diff == "easy":
        return {"difficulty": "easy", "qwen_ratio": 1.0, "openai_ratio": 0.0,
                "wikipedia_ratio": 0.0, "wikipedia_used": False,
                "description": "PDF 직접 내용 기반, Qwen3B 단독 생성"}
    if diff == "normal":
        return {"difficulty": "normal", "qwen_ratio": 0.8, "openai_ratio": 0.2,
                "wikipedia_ratio": 0.0, "wikipedia_used": False,
                "description": "Qwen3B 1차 생성 후 OpenAI가 문장과 보기 품질을 가볍게 보정"}
    # hard
    if wikipedia_used:
        return {"difficulty": "hard", "qwen_ratio": 0.5, "openai_ratio": 0.35,
                "wikipedia_ratio": 0.15, "wikipedia_used": True,
                "description": "Qwen3B가 PDF 기반 초안을 만들고 OpenAI와 Wikipedia가 응용 및 실무 상황을 보강"}
    return {"difficulty": "hard", "qwen_ratio": 0.5, "openai_ratio": 0.5,
            "wikipedia_ratio": 0.0, "wikipedia_used": False,
            "description": "Wikipedia 조회 실패로 OpenAI가 PDF 기반 실무 상황을 보강"}


# ── 개념 추출 ─────────────────────────────────────────────────────────────────
def extract_concepts(ctx: Dict[str, Any], limit: int = 8) -> List[str]:
    """컨텍스트/키워드에서 핵심 개념 후보를 뽑는다."""
    concepts: List[str] = []
    for k in ctx.get("keywords", []):
        if k and k not in concepts:
            concepts.append(k)
    text = ctx.get("context", "") or ""
    for m in re.findall(r"[A-Z][A-Za-z0-9]{2,}", text):
        if m not in concepts:
            concepts.append(m)
    for m in re.findall(r"[가-힣]{2,6}", text):
        if m not in concepts and len(concepts) < limit * 2:
            concepts.append(m)
    return concepts[:limit] or [ctx.get("title") or "핵심 개념"]


# ── Wikipedia 보강 (hard, general 전용) ───────────────────────────────────────
def fetch_wikipedia_context(concepts: List[str]) -> Tuple[str, bool]:
    """hard general 보강용. (snippet, used)."""
    try:
        from app.services.wikipedia_service import search_wikipedia
    except Exception:
        return "", False
    for c in concepts[:3]:
        try:
            hits = search_wikipedia(c, limit=1)
        except Exception as e:  # noqa: BLE001
            logger.info("Wikipedia 조회 실패(%s): %s", c, e)
            continue
        if hits:
            snip = sanitize_markdown_text(hits[0].get("snippet") or "")
            if snip:
                return f"{c}: {snip}"[:400], True
    return "", False


# ── deterministic PDF-based fallback 문항 (I) ─────────────────────────────────
_GENERIC_WRONGS = [
    "데이터베이스 연결 설정을 자동으로 관리하기 위해",
    "화면 애니메이션 성능을 높이기 위해",
    "로그 출력을 자동으로 비활성화하기 위해",
    "직렬화 포맷을 임의로 변경하기 위해",
    "네트워크 패킷을 직접 암호화하기 위해",
]


def _context_snippet(ctx: Dict[str, Any], concept: str) -> str:
    text = ctx.get("context", "") or ""
    for sent in re.split(r"(?<=[.。\n])", text):
        if concept and concept in sent and len(sent.strip()) > 8:
            return sanitize_markdown_text(sent).strip()[:160]
    return sanitize_markdown_text(text[:160]).strip()


def build_general_easy(ctx: Dict[str, Any], concept: str, seq: int) -> Dict[str, Any]:
    snippet = _context_snippet(ctx, concept) or f"{concept}의 기본 개념"
    correct = f"{concept}의 기본 역할/개념에 해당한다"
    wrongs = [_GENERIC_WRONGS[(seq + i) % len(_GENERIC_WRONGS)] for i in range(3)]
    choices = [correct] + wrongs
    ans = seq % 4
    choices[0], choices[ans] = choices[ans], choices[0]
    return {
        "question": f"자료에서 설명하는 {concept}의 기본 역할로 가장 적절한 것은 무엇인가요?",
        "choices": choices,
        "correct_answer": choices[ans],
        "explanation": f"자료에 따르면 {snippet}. 따라서 {concept}의 기본 역할을 묻는 문제다.",
        "wrong_explanations": [f"'{w}'는 {concept}의 기본 역할과 거리가 멀다." for w in wrongs],
        "_concept": concept,
    }


def build_general_normal(ctx: Dict[str, Any], concept: str, seq: int) -> Dict[str, Any]:
    snippet = _context_snippet(ctx, concept) or f"{concept} 관련 내용"
    correct = f"{concept}의 책임을 분리해 흐름을 이해하기 쉽게 만들 수 있다"
    wrongs = [_GENERIC_WRONGS[(seq + i + 1) % len(_GENERIC_WRONGS)] for i in range(3)]
    choices = [correct] + wrongs
    ans = (seq + 1) % 4
    choices[0], choices[ans] = choices[ans], choices[0]
    return {
        "question": f"{concept}를 다른 구성요소와 분리하여 적용하면 어떤 장점이 있나요? 자료 내용을 응용해 고르세요.",
        "choices": choices,
        "correct_answer": choices[ans],
        "explanation": f"자료의 '{snippet}' 내용을 응용하면 {concept} 분리의 장점을 추론할 수 있다.",
        "wrong_explanations": [f"'{w}'는 {concept} 분리의 직접적 장점이 아니다." for w in wrongs],
        "_concept": concept,
    }


def build_general_hard(ctx: Dict[str, Any], concept: str, seq: int) -> Dict[str, Any]:
    base = build_hard_question(concept, seq=seq)  # 시나리오형(hard 신호어 포함, 검증 통과)
    opts = base["options"]
    ans_idx = base.get("answerIndex", 0)
    correct = opts[ans_idx]
    wrongs = [o for i, o in enumerate(opts) if i != ans_idx]
    snippet = _context_snippet(ctx, concept)
    return {
        "question": base["question"],
        "choices": opts,
        "correct_answer": correct,
        "explanation": (base["explanation"] + (f" (근거: {snippet})" if snippet else "")),
        "wrong_explanations": [f"'{w}'는 문제 상황의 핵심 원인/책임과 무관하다." for w in wrongs],
        "_concept": concept,
    }


def build_syllabus_easy(weekly: List[Dict[str, Any]], topics_pool: List[str], seq: int) -> Dict[str, Any]:
    item = weekly[seq % len(weekly)]
    week, correct = item["week"], item["topic"]
    wrongs = _pick_distractors(topics_pool, correct, 3)
    choices = [correct] + wrongs
    ans = seq % 4
    choices[0], choices[ans] = choices[ans], choices[0]
    return {
        "question": f"강의계획서 기준으로 {week}주차 강의 주제는 무엇인가요?",
        "choices": choices,
        "correct_answer": choices[ans],
        "explanation": f"강의계획서의 주차별 강의계획에서 {week}주차 주제는 '{correct}'로 기재되어 있다.",
        "wrong_explanations": [f"'{w}'는 {week}주차의 주제가 아니다." for w in wrongs],
        "_concept": f"{week}주차 강의 주제",
    }


def build_syllabus_normal(weekly: List[Dict[str, Any]], topics_pool: List[str], seq: int) -> Dict[str, Any]:
    early = weekly[0]["topic"]
    wrongs = _pick_distractors(topics_pool, early, 3)
    choices = [early] + wrongs
    ans = seq % 4
    choices[0], choices[ans] = choices[ans], choices[0]
    return {
        "question": "강의계획서의 주차별 흐름상 초반부에 다루는 학습 주제로 가장 적절한 것은 무엇인가요?",
        "choices": choices,
        "correct_answer": choices[ans],
        "explanation": f"주차별 계획의 앞 순서를 보면 초반부 주제는 '{early}'에 해당한다. 주차 흐름 이해를 묻는 문제다.",
        "wrong_explanations": [f"'{w}'는 초반부보다 뒤 순서에 가깝다." for w in wrongs],
        "_concept": "주차별 학습 흐름",
    }


def build_syllabus_hard(weekly: List[Dict[str, Any]], topics_pool: List[str], seq: int) -> Dict[str, Any]:
    early = weekly[0]["topic"]
    later = weekly[-1]["topic"]
    correct = f"{early} → {later} 순서로 선행 학습이 이어진다"
    wrongs = [
        f"{later} → {early} 순서로 학습해야 한다",
        "주차 순서와 무관하게 학습해도 된다",
        "행정 안내 이후에 본 학습이 진행된다",
    ]
    choices = [correct] + wrongs
    ans = seq % 4
    choices[0], choices[ans] = choices[ans], choices[0]
    return {
        "question": ("이 강의계획서의 주차별 흐름과 전체 커리큘럼 구조를 기준으로, "
                     "선행 학습 순서가 가장 적절하게 연결된 것은 무엇인가요?"),
        "choices": choices,
        "correct_answer": choices[ans],
        "explanation": (f"주차별 계획의 순서상 '{early}'가 '{later}'보다 앞서며, "
                        "전체 커리큘럼 흐름상 선행 학습 연결로 적절하다."),
        "wrong_explanations": [f"'{w}'는 강의계획서의 주차 흐름과 맞지 않는다." for w in wrongs],
        "_concept": "주차별 학습 흐름",
    }


def _pick_distractors(pool: List[str], correct: str, n: int) -> List[str]:
    out = [p for p in pool if p and p != correct]
    seen, uniq = set(), []
    for p in out:
        if p not in seen:
            seen.add(p); uniq.append(p)
    fillers = ["기초 개념 정리", "전체 내용 복습", "심화 응용 학습", "프로젝트 발표"]
    i = 0
    while len(uniq) < n:
        f = fillers[i % len(fillers)]
        if f != correct and f not in uniq:
            uniq.append(f)
        i += 1
    return uniq[:n]


def deterministic_questions(ctx: Dict[str, Any], doc_type: str, difficulty: str, count: int,
                            weekly: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    diff = normalize_difficulty(difficulty)
    is_syllabus = doc_type in ("SYLLABUS", "LECTURE_PLAN")
    out: List[Dict[str, Any]] = []
    if is_syllabus and weekly:
        pool = [w["topic"] for w in weekly]
        builder = {"easy": build_syllabus_easy, "normal": build_syllabus_normal,
                   "hard": build_syllabus_hard}[diff]
        for i in range(count):
            out.append(builder(weekly, pool, i))
    else:
        concepts = extract_concepts(ctx)
        builder = {"easy": build_general_easy, "normal": build_general_normal,
                   "hard": build_general_hard}[diff]
        for i in range(count):
            out.append(builder(ctx, concepts[i % len(concepts)], i))
    return out


# ── sanitize (J) ──────────────────────────────────────────────────────────────
def _sanitize_question(q: Dict[str, Any]) -> Dict[str, Any]:
    q["question"] = sanitize_markdown_text(q.get("question") or "")
    q["choices"] = [sanitize_markdown_text(c) for c in (q.get("choices") or [])][:4]
    q["correct_answer"] = sanitize_markdown_text(q.get("correct_answer") or "")
    q["explanation"] = sanitize_markdown_text(q.get("explanation") or "")
    q["wrong_explanations"] = [sanitize_markdown_text(w) for w in (q.get("wrong_explanations") or [])]
    return q


# ── 응답 단위 난이도/PDF 기반 검증 (G, F, I) ──────────────────────────────────
def validate_quiz_difficulty(response: Dict[str, Any], requested_difficulty: str,
                             material_context: str = "") -> Dict[str, Any]:
    """
    응답 전체가 PDF 기반 + 요청 난이도 + provider_policy 계약을 만족하는지 검증한다.
    {passed, reason}. 강의계획서 유형은 별도 규칙(Qwen3B 100%, 행정정보 금지)을 적용한다.
    """
    diff = normalize_difficulty(requested_difficulty)
    questions = response.get("questions") or []
    pol = response.get("provider_policy") or {}
    is_syllabus = response.get("document_type") in ("SYLLABUS", "LECTURE_PLAN")

    if len(questions) < 1:
        return {"passed": False, "reason": "questions 가 비어 있음"}

    if response.get("source_mode") != SOURCE_MODE:
        return {"passed": False, "reason": f"source_mode != {SOURCE_MODE}"}

    # provider_policy 비중 검증 (추가 프롬프트 F)
    if is_syllabus:
        if not (pol.get("qwen_ratio") == 1.0 and pol.get("openai_ratio") == 0.0
                and pol.get("wikipedia_ratio") == 0.0):
            return {"passed": False, "reason": "강의계획서는 Qwen3B 100% 여야 함"}
    elif diff == "easy":
        if pol.get("qwen_ratio") != 1.0:
            return {"passed": False, "reason": "easy 는 qwen_ratio==1.0 이어야 함"}
    elif diff == "normal":
        if not (pol.get("qwen_ratio") == 0.8 and pol.get("openai_ratio") == 0.2):
            return {"passed": False, "reason": "normal 은 qwen 0.8 + openai 0.2 여야 함"}
    elif diff == "hard":
        if pol.get("qwen_ratio") != 0.5:
            return {"passed": False, "reason": "hard 는 qwen_ratio==0.5 여야 함"}
        if round(float(pol.get("openai_ratio", 0)) + float(pol.get("wikipedia_ratio", 0)), 3) != 0.5:
            return {"passed": False, "reason": "hard 는 openai+wikipedia==0.5 여야 함"}

    expl_blob_ok = True
    for i, q in enumerate(questions):
        text = sanitize_markdown_text(q.get("question") or "")
        choices = q.get("choices") or []
        st = q.get("source_trace") or {}
        if not text:
            return {"passed": False, "reason": f"#{i+1} question 비어 있음"}
        if len(choices) != 4:
            return {"passed": False, "reason": f"#{i+1} choices 4개 아님"}
        if not q.get("correct_answer"):
            return {"passed": False, "reason": f"#{i+1} correct_answer 없음"}
        if not q.get("explanation"):
            return {"passed": False, "reason": f"#{i+1} explanation 없음"}
        # 저품질 generic 템플릿/토큰 금지 — 난이도 무관 reject (기본문제 대체 차단, 스펙 [2])
        _blob = " ".join([text] + [sanitize_markdown_text(c) for c in choices])
        for _bad in _BANNED_QUESTION_SUBSTR:
            if _bad in _blob:
                return {"passed": False, "reason": f"#{i+1} 금지 generic 템플릿/토큰('{_bad}') 포함"}
        # correct_answer 는 반드시 보기 중 하나와 정확히 일치
        _correct = sanitize_markdown_text(q.get("correct_answer") or "")
        if _correct not in [sanitize_markdown_text(c) for c in choices]:
            return {"passed": False, "reason": f"#{i+1} correct_answer 가 choices 안에 없음"}
        # source_trace PDF 기반 (F)
        expected_st = "PDF_BASED_SYLLABUS" if is_syllabus else "PDF_BASED"
        if st.get("source_type") != expected_st:
            return {"passed": False, "reason": f"#{i+1} source_trace.source_type != {expected_st}"}
        if not st.get("concepts"):
            return {"passed": False, "reason": f"#{i+1} source_trace.concepts 없음"}
        # 마크다운 잔여 금지 (J)
        for field_val in [text] + [sanitize_markdown_text(c) for c in choices]:
            if any(m in field_val for m in ("**", "###", "```")):
                return {"passed": False, "reason": f"#{i+1} 마크다운 잔여"}
        # 강의계획서: 행정정보 암기 금지 (C/I)
        if is_syllabus and is_admin_question(text) and not response.get("_allow_admin_quiz"):
            return {"passed": False, "reason": f"#{i+1} 교수/행정정보 암기형 문제 금지"}
        # 난이도 본문 규칙
        if is_syllabus:
            if diff == "hard" and not any(s in text for s in _SYLLABUS_FLOW_SIGNALS):
                return {"passed": False, "reason": f"#{i+1} 강의계획서 hard 는 커리큘럼 흐름 문제여야 함"}
        else:
            if diff == "hard":
                if len(text) < HARD_MIN_LEN:
                    return {"passed": False, "reason": f"#{i+1} hard question 길이 부족"}
                if not any(sig.lower() in text.lower() for sig in _HARD_SIGNALS):
                    return {"passed": False, "reason": f"#{i+1} hard 시나리오/설계 신호어 없음"}
                if re.search(r"무엇인가요\?$", text) and len(text) < HARD_MIN_LEN + 20:
                    return {"passed": False, "reason": f"#{i+1} hard 단순 정의형 금지"}

    return {"passed": True, "reason": "PDF 자료 내용을 기반으로 요청 난이도 조건을 만족했습니다."}


# ── source_trace 생성 (F, H) ──────────────────────────────────────────────────
def _build_source_trace(q: Dict[str, Any], ctx: Dict[str, Any], doc_type: str,
                        admin_keys: List[str]) -> Dict[str, Any]:
    is_syllabus = doc_type in ("SYLLABUS", "LECTURE_PLAN")
    concept = q.get("_concept") or "핵심 개념"
    concepts = [concept]
    if is_syllabus:
        return {
            "source_type": "PDF_BASED_SYLLABUS",
            "document_type": doc_type,
            "based_on": ["weekly_schedule", "lecture_topics"],
            "excluded_admin_info": admin_keys,
            "concepts": concepts,
            "evidence": "PDF의 주차별 강의계획에서 주차 제목과 학습 내용을 근거로 출제함",
        }
    return {
        "source_type": "PDF_BASED",
        "based_on": ctx.get("based_on", ["document_text"]),
        "concepts": concepts,
        "evidence": (sanitize_markdown_text(_context_snippet(ctx, concept))
                     or "PDF 자료 본문 핵심 내용 기반으로 출제함"),
    }


# ── 메인 진입점 ───────────────────────────────────────────────────────────────
def generate_pdf_quiz(req: Dict[str, Any]) -> Dict[str, Any]:
    """PDF 기반 퀴즈 생성 전체 파이프라인. 동기 함수(asyncio.to_thread 로 감쌀 것)."""
    ctx = build_material_context(req)
    difficulty = req.get("difficulty") or "normal"
    diff = normalize_difficulty(difficulty)
    # requestedCount 를 절대 임의로 낮추지 않는다. 정책 범위(1~20)로만 clamp.
    count = int(req.get("count") or req.get("num_questions") or req.get("numQuestions") or QUIZ_DEFAULT_COUNT)
    count = max(1, min(count, QUIZ_MAX_COUNT))
    allow_admin_quiz = bool(req.get("generate_admin_quiz") or req.get("admin_quiz"))

    # H: PDF 근거가 전혀 없거나 너무 짧으면 일반 지식 fallback 으로 속이지 않고 명확히 실패한다.
    #    (난이도 미반영을 이유로 기본문제로 낮추는 정책은 제거됨 — 스펙 [1].4)
    context_len = len((ctx.get("context") or "").strip())
    if not ctx["has_pdf_context"] or context_len < QUIZ_MIN_CONTEXT_CHARS:
        return {
            "success": False,
            "error_code": "PDF_TEXT_INSUFFICIENT",
            "message": "PDF 텍스트가 부족해 퀴즈를 생성할 수 없습니다.",
            "retryable": False,
            "context_len": context_len,
            "questions": [],
        }

    doc_type = detect_document_type(ctx)
    is_syllabus = doc_type in ("SYLLABUS", "LECTURE_PLAN")
    admin_info: Dict[str, str] = {}
    weekly: List[Dict[str, Any]] = []
    if is_syllabus:
        admin_info, academic = split_syllabus_content(ctx)
        weekly = academic["weekly_schedule"]
        # J: 강의계획서인데 주차별 학습 내용이 전혀 없으면 실패
        if not weekly and not academic["lecture_topics"]:
            return {
                "success": False,
                "error_code": "SYLLABUS_WEEKLY_CONTENT_REQUIRED",
                "message": "강의계획서에서 주차별 학습 내용을 찾지 못했습니다.",
                "recoverable": True,
                "questions": [],
            }

    # provider 비중 + Wikipedia 보강 (hard general 만)
    wikipedia_used = False
    wiki_context = ""
    if (not is_syllabus) and diff == "hard":
        wiki_context, wikipedia_used = fetch_wikipedia_context(extract_concepts(ctx))

    # 1) LLM 생성 시도 → 2) 실패 시 deterministic fallback (H 복구 순서)
    no_llm = bool(req.get("_no_llm"))
    questions, det_used = _generate_questions(ctx, doc_type, diff, count, weekly, wiki_context, allow_admin_quiz, no_llm)
    # source 판정: deterministic 으로 일부라도 채웠으면 DETERMINISTIC_PDF, 전부 LLM 이면 AI_REPAIRED.
    # 어느 쪽이든 PDF 근거 + 요청 난이도를 그대로 유지하므로 '기본문제 대체'가 아니다.
    source = "DETERMINISTIC_PDF" if det_used > 0 else "AI_REPAIRED"

    # admin 문제 필터 (C) — 강의계획서 기본 동작에서 행정정보 암기형 제거
    if is_syllabus and not allow_admin_quiz:
        questions = _replace_admin_questions(questions, ctx, doc_type, diff, weekly)

    # source_trace + sanitize
    admin_keys = list(admin_info.keys())
    final_q: List[Dict[str, Any]] = []
    for i, q in enumerate(questions[:count]):
        q = _sanitize_question(dict(q))
        q["source_trace"] = _build_source_trace(questions[i], ctx, doc_type, admin_keys)
        q.pop("_concept", None)
        final_q.append(q)

    provider_policy = resolve_provider_policy(diff, is_syllabus, wikipedia_used)

    response: Dict[str, Any] = {
        "success": True,
        "error_code": None,
        "source_mode": SOURCE_MODE,
        "document_type": doc_type,
        "is_syllabus": is_syllabus,
        "material_id": ctx.get("material_id"),
        "material_title": ctx.get("title"),
        "difficulty_requested": difficulty,
        "difficulty_applied": diff,   # 항상 요청 난이도와 동일 (낮추지 않음)
        "difficulty_policy": difficulty_policy_text(diff),
        "provider_policy": provider_policy,
        "questions": final_q,
        "source": source,
        "fallback_used": False,
        "_allow_admin_quiz": allow_admin_quiz,
    }
    if is_syllabus:
        response["academic_content_policy"] = "행정정보는 제외하고 주차별 강의 주제와 학습 내용을 중심으로 생성"
        response["metadata_admin_info"] = admin_info

    # 검증 + 실패 시 deterministic 재구성 (H)
    check = validate_quiz_difficulty(response, difficulty, ctx.get("context", ""))
    if not check["passed"]:
        logger.info("PDF 퀴즈 1차 검증 실패 → deterministic 재구성: %s", check["reason"])
        det = deterministic_questions(ctx, doc_type, diff, count, weekly)
        if is_syllabus and not allow_admin_quiz:
            det = _replace_admin_questions(det, ctx, doc_type, diff, weekly)
        rebuilt: List[Dict[str, Any]] = []
        for i, q in enumerate(det[:count]):
            qq = _sanitize_question(dict(q))
            qq["source_trace"] = _build_source_trace(det[i], ctx, doc_type, admin_keys)
            qq.pop("_concept", None)
            rebuilt.append(qq)
        response["questions"] = rebuilt
        response["source"] = "DETERMINISTIC_PDF"  # 재구성은 PDF 기반 결정론 생성기로 보충
        check = validate_quiz_difficulty(response, difficulty, ctx.get("context", ""))

    response.pop("_allow_admin_quiz", None)
    response["validation"] = check
    response["generated_count"] = len(response.get("questions") or [])
    if not check["passed"]:
        # PDF 기반 결정론 생성기로도 검증을 통과하지 못하면 입력 텍스트 부족으로 간주한다.
        # (난이도 미반영을 이유로 기본문제로 낮추지 않는다 — 명확히 실패)
        return {
            "success": False,
            "error_code": "PDF_TEXT_INSUFFICIENT",
            "message": "PDF 텍스트가 부족해 퀴즈를 생성할 수 없습니다.",
            "retryable": False,
            "questions": [],
            "validation": check,
        }
    return response


def _replace_admin_questions(questions: List[Dict[str, Any]], ctx, doc_type, diff, weekly):
    """행정정보 암기형 문제를 주차별 학습 내용 문제로 교체."""
    out = []
    replacement_pool = deterministic_questions(ctx, doc_type, diff, len(questions) + 3, weekly)
    ri = 0
    for q in questions:
        if is_admin_question(q.get("question") or ""):
            while ri < len(replacement_pool) and is_admin_question(replacement_pool[ri].get("question") or ""):
                ri += 1
            if ri < len(replacement_pool):
                out.append(replacement_pool[ri]); ri += 1
                continue
        out.append(q)
    return out


def _generate_questions(ctx, doc_type, diff, count, weekly, wiki_context, allow_admin_quiz, no_llm=False):
    """Qwen 1차 → (필요시 OpenAI 보정) → 실패 시 deterministic. 각 슬롯 검증 후 대체.
    Returns: (questions, det_used) — det_used 는 deterministic 으로 채운 슬롯 수(source 판정용)."""
    llm_qs = [] if no_llm else _llm_generate(ctx, doc_type, diff, count, weekly, wiki_context)
    det = deterministic_questions(ctx, doc_type, diff, count, weekly)
    out: List[Dict[str, Any]] = []
    det_used = 0
    for i in range(count):
        cand = llm_qs[i] if i < len(llm_qs) else None
        if cand and _question_shape_ok(cand):
            out.append(cand)
        else:
            out.append(det[i % len(det)])
            det_used += 1
    return out, det_used


def _question_shape_ok(q: Dict[str, Any]) -> bool:
    ch = q.get("choices") or []
    return bool((q.get("question") or "").strip()) and len(ch) == 4 and bool(q.get("correct_answer"))


# ── streaming 오케스트레이터 공용 헬퍼 (스펙 I/J/K) ────────────────────────────
def normalize_quiz_count(raw: Any) -> Tuple[int, int]:
    """(요청값, 적용값) 반환. 적용값은 5~20 clamp, 파싱 실패 시 기본 10."""
    try:
        requested = int(raw)
    except (TypeError, ValueError):
        requested = QUIZ_DEFAULT_COUNT
    applied = max(QUIZ_MIN_COUNT, min(requested, QUIZ_MAX_COUNT))
    return requested, applied


def _norm_q(question: Any) -> str:
    """중복 판정용 질문 정규화 키."""
    text = sanitize_markdown_text(str(question or "")).lower()
    return re.sub(r"\s+", " ", re.sub(r"[^0-9a-z가-힣 ]", " ", text)).strip()


def _question_difficulty_ok(q: Dict[str, Any], diff: str, is_syllabus: bool) -> bool:
    """단일 문항이 형식 + 요청 난이도 본문 규칙을 만족하는지(검증 통과분만 partial_validated 노출)."""
    if not _question_shape_ok(q) or not (q.get("explanation") or "").strip():
        return False
    text = sanitize_markdown_text(q.get("question") or "")
    if not text:
        return False
    for field_val in [text] + [sanitize_markdown_text(c) for c in (q.get("choices") or [])]:
        if any(m in field_val for m in ("**", "###", "```")):
            return False
    diff = normalize_difficulty(diff)
    if is_syllabus:
        if diff == "hard" and not any(s in text for s in _SYLLABUS_FLOW_SIGNALS):
            return False
    else:
        if diff == "hard":
            if len(text) < HARD_MIN_LEN:
                return False
            if not any(sig.lower() in text.lower() for sig in _HARD_SIGNALS):
                return False
            if re.search(r"무엇인가요\?$", text) and len(text) < HARD_MIN_LEN + 20:
                return False
    return True


def validate_quiz_response(response: Dict[str, Any], requested_difficulty: str,
                           expected_count: Optional[int] = None) -> Dict[str, Any]:
    """streaming 최종 검증 — validate_quiz_difficulty + 문항 수 확인. {passed, reason}."""
    check = validate_quiz_difficulty(response, requested_difficulty,
                                     str(response.get("material_title") or ""))
    if not check.get("passed"):
        return check
    if expected_count is not None:
        n = len(response.get("questions") or [])
        if n < int(expected_count):
            return {"passed": False, "reason": f"검증 통과 문항 {n} < 요청 {expected_count}"}
    return check


def _llm_generate(ctx, doc_type, diff, count, weekly, wiki_context) -> List[Dict[str, Any]]:
    """Qwen(주력)으로 PDF 기반 초안 생성. normal/hard 는 OpenAI 보정 경로 포함."""
    from app.services.study_action_router import primary_llm, refiner_llm
    from app.utils.json_parser import extract_json

    is_syllabus = doc_type in ("SYLLABUS", "LECTURE_PLAN")
    if is_syllabus and weekly:
        weekly_str = "\n".join(f"{w['week']}주차: {w['topic']}" for w in weekly)
        scope = (f"아래 강의계획서 주차별 계획만 근거로 사용한다(교수/연구실/이메일 등 행정정보로 문제 금지):\n{weekly_str}")
    else:
        scope = f"아래 PDF 자료 본문만 근거로 사용한다:\n{ctx.get('context', '')[:3500]}"
        if wiki_context and diff == "hard":
            scope += f"\n\n[참고: 아래 배경지식은 PDF 개념의 응용/실무 맥락 보강용이며 출제 근거의 핵심이 아니다]\n{wiki_context}"

    diff_rule = {
        "easy": "PDF에 직접 나온 정의/용어/기본 역할/흐름 확인 문제",
        "normal": "PDF 내용 기반 + 가벼운 응용(비교/흐름/간단한 원인 추론)",
        "hard": ("PDF 내용 기반 + 응용/실무 상황(오류 상황/설계 판단/책임 분리/테스트/유지보수/예외/성능 중 1개 이상). "
                 "단순 '무엇인가요?' 금지" if not is_syllabus else
                 "PDF 주차별 내용 + 전체 커리큘럼 흐름/선행 학습 순서 판단. 실무 시나리오 과도 금지"),
    }[diff]

    system = (
        "너는 PDF 학습 자료 기반 사지선다 퀴즈 출제자다. 반드시 자료 본문 근거로만 출제하고, "
        "PDF와 무관한 일반 상식/제목만 보고 만든 문제는 금지한다. 마크다운 없이 JSON 으로만 응답한다."
    )
    user = (
        f"## 출제 범위\n{scope}\n\n## 난이도 기준({diff})\n{diff_rule}\n\n"
        f"{count}개의 문항을 아래 JSON 으로만 응답하라(설명/마크다운 금지):\n"
        '{ "questions": [ { "question": "문제", "choices": ["보기1","보기2","보기3","보기4"], '
        '"correct_answer": "정답 보기 텍스트", "explanation": "정답 해설", '
        '"wrong_explanations": ["오답해설1","오답해설2","오답해설3"], "concept": "핵심 개념" } ] }'
    )
    try:
        # easy/강의계획서 = Qwen 단독. normal/hard general = OpenAI 보정 허용.
        if is_syllabus or diff == "easy":
            raw = primary_llm(system, user, max_tokens=QUIZ_MAX_TOKENS)
        else:
            draft = primary_llm(system, user, max_tokens=QUIZ_MAX_TOKENS)
            raw = refiner_llm(
                "너는 퀴즈 품질 보정자다. 아래 초안의 문장/보기/정답·오답 해설을 다듬되 PDF 근거를 벗어나지 마라. "
                "JSON 스키마는 그대로 유지하고 마크다운 없이 JSON 으로만 응답한다.",
                f"## 초안\n{draft}\n\n## 출제 범위\n{scope}", max_tokens=QUIZ_MAX_TOKENS,
            ) or draft
    except Exception as e:  # noqa: BLE001
        logger.info("PDF 퀴즈 LLM 생성 실패: %s", e)
        return []
    if not raw or raw.strip().startswith("[") or raw.strip().startswith("[GPT"):
        return []
    parsed = extract_json(raw)
    items = parsed.get("questions") if isinstance(parsed, dict) else (parsed if isinstance(parsed, list) else None)
    if not isinstance(items, list):
        return []
    out: List[Dict[str, Any]] = []
    for it in items:
        if not isinstance(it, dict):
            continue
        choices = it.get("choices") or it.get("options") or []
        ca = it.get("correct_answer") or it.get("answer") or ""
        if isinstance(ca, int) and 0 <= ca < len(choices):
            ca = choices[ca]
        out.append({
            "question": it.get("question") or "",
            "choices": [str(c) for c in choices][:4],
            "correct_answer": str(ca),
            "explanation": it.get("explanation") or "",
            "wrong_explanations": it.get("wrong_explanations") or [],
            "_concept": it.get("concept") or "핵심 개념",
        })
    return out
