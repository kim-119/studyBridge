"""
전공 분야 + 핵심 객체 중심 AI 핵심 요약 노트.

EC2 Spring이 PDF 업로드 직후 자동 호출한다. FastAPI는 PDF 텍스트/OCR/표/캡션/이미지 설명/
사용자 질문을 받아 (1) 전공 분야를 14종 enum 중 하나로 분류하고, (2) PDF 안의 핵심 객체
(coreObject)를 찾아 (3) 그 객체 중심으로 학습 노트를 생성한다. Wikipedia는 보조 지식으로만
사용하며, PDF 문맥을 대체하지 않는다.

  POST /api/ai/major-analysis/note → 도메인/핵심객체 중심 학습 노트(JSON)

기존 요약/퀴즈/로드맵/RAG 계약과 별개의 신규 additive 경로. materialId 계약은 그대로 유지하며
부가 필드(folderId 등)는 무시한다(extra=ignore). LLM/Wikipedia 실패·timeout·빈입력은 분석을
실패시키지 않고 안전 fallback을 성공 응답(200)으로 반환한다(업로드 실패 방지).

금지: 의료 진단, 법률 자문, 투자 추천, 구조 안전 판정, 균종 확정 표현.
"""
import asyncio
import logging
import os
import re
from typing import Any, Dict, List, Optional, Tuple

from fastapi import APIRouter, Body
from pydantic import BaseModel, ConfigDict, Field

logger = logging.getLogger(__name__)
router = APIRouter(tags=["Major Analysis Note AI"])

MAJOR_ANALYSIS_TIMEOUT = int(os.getenv("AI_MAJOR_ANALYSIS_TIMEOUT_SECONDS", "90"))

MODE = "DOMAIN_OBJECT_CENTERED_STUDY_NOTE"
DISCLAIMER = (
    "이 결과는 강의자료 기반 학습 보조 설명이며, 의료 진단·법률 자문·투자 자문·전문 감정이 아닙니다."
)

# 입력 컷(프롬프트 폭주 방지)
_MAX_TOTAL_CHARS = 9000
_MAX_FIELD = 500
_MIN_MEANINGFUL = 40

# 고위험 분야(확정/판정 표현 추가 경고)
_HIGH_STAKES = {
    "MEDICINE_NURSING", "LAW_PUBLIC_ADMIN", "BUSINESS_ECONOMICS",
    "ARCHITECTURE_CIVIL", "BIOLOGY_MICROBIOLOGY",
}

# ── 도메인 정의: enum, 한국어 라벨, 분류 키워드(영/한), 생성 정책 힌트 ─────────────
_DOMAINS: List[Dict[str, Any]] = [
    {"enum": "MATH", "label": "수학",
     "kw": ["수학", "적분", "미분", "행렬", "고유값", "확률분포", "미분방정식", "정리", "증명",
            "integral", "matrix", "derivative", "eigen", "probability", "theorem", "equation", "calculus"],
     "policy": "수식을 인식하고 가능하면 LaTeX로 정리하라. 풀이가 필요한 수식이면 단계별 풀이와 개념을 제시하라. 수식 OCR 오류 가능성을 한계로 명시하라."},
    {"enum": "PHYSICS", "label": "물리",
     "kw": ["물리", "뉴턴", "관성", "운동량", "전기장", "자기장", "파동", "역학",
            "newton", "force", "velocity", "acceleration", "momentum", "wave", "field", "kinetic"],
     "policy": "주어진 물리량, 적용 공식, 단위 해석, 그래프/회로/힘의 관계를 설명하라. 자유물체도/회로가 나오면 개념 흐름을 먼저 설명하라."},
    {"enum": "CHEMISTRY", "label": "화학",
     "kw": ["화학", "반응식", "벤젠", "산염기", "작용기", "메커니즘", "몰", "원소",
            "reaction", "benzene", "acid", "base", "molecule", "bond", "sn1", "sn2", "functional group"],
     "policy": "반응식, 작용기, 반응 메커니즘, 실험표 해석 중심으로 설명하라. 위험한 실험 절차나 유해물질 제조법은 구체적으로 안내하지 마라."},
    {"enum": "BIOLOGY_MICROBIOLOGY", "label": "생명과학/미생물",
     "kw": ["미생물", "세균", "균주", "대장균", "포도상구균", "결핵균", "바이러스", "세포", "유전자", "염색",
            "bacteria", "coli", "escherichia", "gram", "virus", "cell", "gene", "microorganism", "pathogen", "strain"],
     "policy": "PDF에 나온 균명/질병명/염색법/형태학 용어를 중심으로 설명하라. 균명이 있으면 그 균 중심으로 작성하라. 실제 균종 확정/검체 진단 표현은 금지한다."},
    {"enum": "MEDICINE_NURSING", "label": "의학/간호",
     "kw": ["의학", "간호", "질환", "병리", "폐렴", "염증", "해부", "증상", "간호과정", "치료",
            "nursing", "disease", "diagnosis", "pathology", "clinical", "patient", "symptom", "anatomy"],
     "policy": "해부 구조, 질환 기전, 간호 과정, 병리 변화를 교육용으로 설명하라. 실제 진단/치료 지시는 금지한다."},
    {"enum": "COMPUTER_SCIENCE", "label": "컴퓨터공학",
     "kw": ["알고리즘", "자료구조", "복잡도", "트리", "스레드", "재귀", "정렬", "코드",
            "algorithm", "complexity", "loop", "for", "while", "function", "def", "tree", "sort", "thread", "api", "o(n"],
     "policy": "코드 동작, 오류 가능성, 시간복잡도, 자료구조/알고리즘 흐름을 설명하라. 악성코드 작성이나 공격 절차는 설명하지 마라."},
    {"enum": "DATA_STATISTICS", "label": "데이터분석/통계",
     "kw": ["통계", "회귀", "분포", "표본", "분산", "신뢰구간", "상관", "가설검정",
            "regression", "p-value", "pvalue", "variance", "statistics", "correlation", "sample", "confidence", "r2", "r²"],
     "policy": "표/그래프/회귀계수/p-value/신뢰구간/R²을 해석하라. 통계적 가정과 한계도 포함하라."},
    {"enum": "ELECTRONICS", "label": "전자공학",
     "kw": ["전자", "회로", "전압", "전류", "저항", "논리게이트", "플립플롭", "접지", "차단기", "배선", "파형", "진리표",
            "circuit", "voltage", "current", "resistor", "logic gate", "transistor", "grounding", "wiring", "breaker", "waveform"],
     "policy": "회로도, 파형, 논리회로, 진리표, 전류/전압 흐름을 설명하라. 전선/접지/차단기 등 배선 요소가 있으면 그 흐름을 중심으로 설명하라."},
    {"enum": "MECHANICAL_ENGINEERING", "label": "기계공학",
     "kw": ["기계", "응력", "변형률", "열역학", "유체", "자유물체도", "하중", "토크",
            "stress", "strain", "thermodynamics", "fluid", "torque", "mechanics", "load"],
     "policy": "자유물체도, 하중, 응력, 변형률, 열역학/유체역학 개념을 설명하라."},
    {"enum": "ARCHITECTURE_CIVIL", "label": "건축/토목",
     "kw": ["건축", "토목", "구조", "기초", "기둥", "철근", "콘크리트", "지반", "단면",
            "beam", "column", "foundation", "concrete", "structural", "soil", "reinforce"],
     "policy": "구조도, 지반 단면, 하중 전달, 기초, 보/기둥 개념을 설명하라. 실제 구조 안전 판정은 금지한다."},
    {"enum": "EARTH_GEOLOGY", "label": "지구과학/지질",
     "kw": ["지질", "지층", "단층", "습곡", "퇴적암", "판구조", "암석", "광물",
            "geology", "fault", "fold", "sediment", "tectonic", "mineral", "rock", "strata"],
     "policy": "지층, 단층, 습곡, 암석, 지도/단면도 해석을 설명하라."},
    {"enum": "BUSINESS_ECONOMICS", "label": "경영/경제",
     "kw": ["경영", "경제", "재무제표", "손익", "수요", "공급", "전략", "지표", "매출", "원가",
            "finance", "economics", "market", "supply", "demand", "revenue", "profit", "swot", "gdp"],
     "policy": "재무제표, 그래프, 케이스, 전략, 경제지표를 설명하라. 투자 추천은 금지한다."},
    {"enum": "LAW_PUBLIC_ADMIN", "label": "법학/행정",
     "kw": ["법", "판례", "조문", "원고적격", "처분성", "재량", "행정", "쟁점", "위법", "소송",
            "law", "statute", "court", "precedent", "plaintiff", "jurisdiction", "legal", "ruling"],
     "policy": "조문 구조, 판례 쟁점, 사실관계, 판단 구조를 설명하라. 실제 법률 자문은 금지한다."},
]
_DOMAIN_BY_ENUM = {d["enum"]: d for d in _DOMAINS}
_GENERAL = {"enum": "GENERAL", "label": "일반 전공자료", "kw": [], "policy": ""}

# 라틴 이명법(예: Escherichia coli) — 미생물 핵심 객체 후보
_BINOMIAL_RE = re.compile(r"\b[A-Z][a-z]{2,}\s[a-z]{3,}\b")
_TOKEN_RE = re.compile(r"[A-Za-z][A-Za-z0-9_\-]+|[가-힣]{2,}")
_STOPWORDS = {
    "있다", "한다", "된다", "이다", "그리고", "하지만", "또한", "위해", "대한", "통해", "관한",
    "this", "that", "with", "from", "have", "which", "some", "are", "and", "the", "for",
    "강의", "자료", "설명", "내용", "문서", "학습", "정리", "중심", "기반", "개념",
}


class _PageItem(BaseModel):
    model_config = ConfigDict(extra="ignore")
    page: Optional[int] = None
    text: Optional[str] = ""


class MajorAnalysisRequest(BaseModel):
    # folderId/parentFolderId 등 부가 필드는 무시(이 모델 한정, 전역 설정 변경 아님)
    model_config = ConfigDict(extra="ignore")

    materialId: Optional[int] = None
    materialTitle: Optional[str] = ""
    subject: Optional[str] = ""
    inputType: Optional[str] = "PDF"
    s3Key: Optional[str] = ""
    pageCount: Optional[int] = None
    pageTexts: List[_PageItem] = Field(default_factory=list)
    captions: List[_PageItem] = Field(default_factory=list)
    ocrTexts: List[_PageItem] = Field(default_factory=list)
    tables: List[_PageItem] = Field(default_factory=list)
    imageDescriptions: List[_PageItem] = Field(default_factory=list)
    userQuestion: Optional[str] = ""
    maxWikiResults: Optional[int] = 5


# ── 텍스트 조합 ──────────────────────────────────────────────────────────────

def _join(items: List[_PageItem]) -> str:
    return "\n".join((it.text or "").strip() for it in items if (it.text or "").strip())


def _combined_text(req: MajorAnalysisRequest) -> str:
    parts = [
        req.materialTitle or "", req.subject or "",
        _join(req.pageTexts), _join(req.ocrTexts), _join(req.captions),
        _join(req.tables), _join(req.imageDescriptions),
    ]
    return "\n".join(p for p in parts if p.strip())[:_MAX_TOTAL_CHARS]


# ── 페이지별 입력 수집(이미지 PDF 포함) ───────────────────────────────────────
# 입력 우선순위: pageTexts > ocrTexts > captions > tables > imageDescriptions.
# detectedTextSource는 FastAPI가 실제로 받은 텍스트 소스만 표기한다(읽지 않은 것을 읽었다고 하지 않음).
_PAGE_SOURCES = [
    ("pageTexts", "TEXT"),
    ("ocrTexts", "OCR"),
    ("captions", "CAPTION"),
    ("tables", "TABLE"),
    ("imageDescriptions", "IMAGE_DESCRIPTION"),
]
_MAX_PAGES = 40          # 프롬프트/출력 폭주 방지
_MAX_PAGE_CHARS = 1200   # 페이지당 입력 컷
_MIN_PAGE_MEANINGFUL = 12  # 이보다 짧으면 INSUFFICIENT
_MAX_PAGE_RETRY = 8       # 배치 누락 페이지 개별 재생성 상한(지연 방지)


def _collect_pages(req: MajorAnalysisRequest) -> List[Dict[str, Any]]:
    """모든 소스를 page 번호 기준으로 병합. 반환: [{page, text, source}] (page 오름차순)."""
    bucket: Dict[Any, Dict[str, Any]] = {}
    order: List[Any] = []
    for field, label in _PAGE_SOURCES:
        for it in getattr(req, field, []) or []:
            txt = (it.text or "").strip()
            if not txt:
                continue
            key = it.page if it.page is not None else f"_noidx_{label}_{len(order)}"
            if key not in bucket:
                bucket[key] = {"page": it.page, "texts": [], "sources": []}
                order.append(key)
            bucket[key]["texts"].append(txt)
            if label not in bucket[key]["sources"]:
                bucket[key]["sources"].append(label)

    pages: List[Dict[str, Any]] = []
    for key in order:
        b = bucket[key]
        merged = "\n".join(b["texts"])[:_MAX_PAGE_CHARS]
        meaningful = re.sub(r"\s+", "", merged)
        srcs = b["sources"]
        if len(meaningful) < _MIN_PAGE_MEANINGFUL or not srcs:
            source = "INSUFFICIENT"
        elif len(srcs) == 1:
            source = srcs[0]
        else:
            source = "MIXED"
        pages.append({"page": b["page"], "text": merged, "source": source})

    # page 번호 우선 정렬(None은 뒤로)
    pages.sort(key=lambda p: (p["page"] is None, p["page"] if p["page"] is not None else 0))
    return pages[:_MAX_PAGES]


def _page_fallback_entry(page: Optional[int]) -> Dict[str, Any]:
    return {
        "page": page,
        "title": "내용 식별 제한",
        "detectedTextSource": "INSUFFICIENT",
        "contentType": _content_type("INSUFFICIENT"),
        "pageOverview": "이 페이지는 OCR 또는 텍스트 추출 결과가 부족하여 핵심 내용을 명확히 식별하기 어렵습니다.",
        "keyConcepts": [],
        "conceptExplanations": [],
        "examples": [],
        "summaryBullets": [
            "페이지 이미지 또는 캡션 정보가 부족합니다.",
            "원본 PDF의 텍스트 추출 또는 OCR 품질을 확인해야 합니다.",
        ],
        "studyFocus": "이 페이지는 원본 화면을 직접 확인한 뒤 제목, 그림, 표의 캡션을 중심으로 복습해야 합니다.",
    }


# ── 도메인 분류(결정론적 키워드 스코어) ──────────────────────────────────────

def _classify_domain(text: str) -> Tuple[Dict[str, Any], float]:
    low = text.lower()
    best, best_score = _GENERAL, 0.0
    for d in _DOMAINS:
        hits = sum(1 for kw in d["kw"] if kw.lower() in low)
        if hits > best_score:
            best, best_score = d, hits
    return best, best_score


# ── 핵심 객체 후보(결정론적) — Wikipedia 검색어 생성용 ────────────────────────

def _concept_candidates(text: str, limit: int = 3) -> List[str]:
    cands: List[str] = []
    # 1) 라틴 이명법 우선(미생물/생명)
    for m in _BINOMIAL_RE.findall(text):
        if m not in cands:
            cands.append(m)
    # 2) 빈도 상위 토큰
    freq: Dict[str, int] = {}
    for tok in _TOKEN_RE.findall(text):
        t = tok.strip()
        if len(t) < 2 or t.lower() in _STOPWORDS:
            continue
        freq[t] = freq.get(t, 0) + 1
    for w, _ in sorted(freq.items(), key=lambda kv: (-kv[1], -len(kv[0]))):
        if w not in cands:
            cands.append(w)
        if len(cands) >= limit + 2:
            break
    return cands[:limit]


# ── Wikipedia 보강(실패해도 분석 실패 금지) ──────────────────────────────────

def _fetch_wiki(queries: List[str], max_results: int) -> List[Dict[str, Any]]:
    if max_results <= 0 or not queries:
        return []
    try:
        from app.services.material_summary_builder import sanitize_markdown_text
        from app.services.wikipedia_service import search_wikipedia
    except Exception:
        return []
    out: List[Dict[str, Any]] = []
    seen = set()
    for q in queries:
        if len(out) >= max_results:
            break
        try:
            hits = search_wikipedia(q, limit=2)
        except Exception as e:  # noqa: BLE001
            logger.info("Wikipedia 조회 실패(%s): %s — 보조 정보 없이 계속", q, e)
            continue
        for h in hits or []:
            title = (h.get("title") or "").strip()
            if not title or title in seen:
                continue
            seen.add(title)
            summary = sanitize_markdown_text(h.get("snippet") or "")[:400]
            out.append({"title": title, "summary": summary, "used": bool(summary)})
            if len(out) >= max_results:
                break
    return out


# ── LLM 프롬프트 ─────────────────────────────────────────────────────────────

_SYSTEM = "너는 대학 전공 학습자를 위한 AI 핵심 요약 노트 생성기다."


def _pages_block(pages: List[Dict[str, Any]]) -> str:
    """페이지별 입력을 LLM에 분리 제공(페이지 섞임 방지). INSUFFICIENT 페이지도 명시."""
    if not pages:
        return "(페이지 단위 입력 없음)"
    lines = []
    for p in pages:
        pno = p["page"] if p["page"] is not None else "?"
        if p["source"] == "INSUFFICIENT":
            lines.append(f"[페이지 {pno}] (source=INSUFFICIENT) 텍스트/OCR가 거의 없음 — 내용 식별 제한으로 처리하라.")
        else:
            lines.append(f"[페이지 {pno}] (source={p['source']})\n{p['text']}")
    return "\n\n".join(lines)


def _build_prompt(req: MajorAnalysisRequest, domain: Dict[str, Any],
                  wiki: List[Dict[str, Any]], candidates: List[str],
                  pages: List[Dict[str, Any]]) -> str:
    wiki_block = "\n".join(f"- {w['title']}: {w['summary']}" for w in wiki if w.get("summary")) or "(없음)"
    return (
        "너는 Univ 스타일의 전공 PDF 학습노트 생성기다. 입력된 PDF의 각 페이지 텍스트/OCR/캡션/표/"
        "이미지 설명을 바탕으로 단순 문서 요약이 아니라 (1) 전공 분야·핵심 객체 중심 노트와 "
        "(2) 페이지별 학습 요약을 생성한다.\n\n"
        f"[확정된 전공 분야] {domain['enum']} ({domain['label']})\n"
        f"[분야별 작성 정책] {domain['policy'] or '핵심 전공 개념 중심으로 구체적으로 작성한다.'}\n"
        f"[핵심 객체 후보(참고)] {', '.join(candidates) if candidates else '없음'}\n\n"
        "작성 규칙:\n"
        "- 문서 전체를 한 덩어리로만 요약하지 않는다. 각 페이지마다 독립적인 요약을 만든다.\n"
        "- 페이지 번호를 유지하고, 다른 페이지 내용을 섞지 않는다(p.2 내용을 p.9에 넣지 말 것).\n"
        "- 각 페이지에서 실제로 나온 개념만으로 title/pageOverview/keyConcepts/summaryBullets/studyFocus를 쓴다.\n"
        "- ★ 각 페이지의 핵심 개념은 이름만 나열하지 말고 conceptExplanations에 '용어(term) + 학습자가 이해할 수 있는 쉬운 설명(explanation)'으로 풀어 쓴다.\n"
        "- ★ 각 페이지마다 그 페이지 개념을 이해하는 데 도움이 되는 '추가 예시'를 examples에 1~3개 든다(PDF에 없어도 개념 설명용 예시는 만들어도 되지만, 사실을 왜곡하지 않는다).\n"
        "- (입력의 source 라벨이 TEXT면 텍스트 페이지, OCR/IMAGE_DESCRIPTION/CAPTION이면 이미지 기반 페이지다. 이미지 기반이면 인식 한계를 감안해 신중히 쓴다.)\n"
        "- source=INSUFFICIENT 페이지는 읽은 척하지 말고 '내용 식별 제한'으로 솔직히 처리한다.\n"
        "- 일반적인 추상 요약으로 끝내지 않고 PDF에 실제로 나온 구체 용어를 사용한다.\n"
        "- Wikipedia는 보조 지식으로만 쓰고 PDF보다 우선하지 않는다. PDF에 없는 내용을 확정 사실처럼 꾸미지 않는다.\n"
        "- 의료 진단/법률 자문/투자 추천/구조 안전 판정/균종 확정처럼 표현하지 않는다.\n"
        "- 모든 출력은 한국어로 작성한다.\n\n"
        "[페이지별 입력]\n"
        f"{_pages_block(pages)}\n\n"
        f"[사용자 질문] {(req.userQuestion or '')[:_MAX_FIELD]}\n\n"
        f"[Wikipedia 보조 정보]\n{wiki_block}\n\n"
        "아래 JSON 한 개로만 응답하라(마크다운/별표/해시/백틱 금지):\n"
        '{ "coreObject": "PDF의 핵심 객체(영문/원문 표기 가능)", '
        '"coreObjectLabel": "핵심 객체의 한국어 명칭", '
        '"documentOverview": "핵심 객체 중심 문서 개요 2~4문장", '
        '"keywords": ["핵심 키워드 5개 내외"], '
        '"coreContents": ["핵심 내용 문장 2~4개"], '
        '"studyPoints": ["학습 포인트 2~4개"], '
        '"aiStudyQuestions": ["학습 질문 3개"], '
        '"pageSummaries": [{"page": 2, "title": "페이지 제목", '
        '"pageOverview": "이 페이지가 무엇을 설명하는지 1~2문장", '
        '"keyConcepts": ["이 페이지의 핵심 개념(이름)"], '
        '"conceptExplanations": [{"term": "개념 이름", "explanation": "그 개념을 쉽게 풀어 설명"}], '
        '"examples": ["개념 이해를 돕는 추가 예시 1~3개"], '
        '"summaryBullets": ["이 페이지 핵심 요약 2~5개"], '
        '"studyFocus": "이 페이지에서 학습자가 이해해야 할 것 1~2문장"}] }\n'
        "pageSummaries는 위 [페이지별 입력]의 각 페이지마다 하나씩, 같은 page 번호로 만든다.\n"
        f"반드시 다음 페이지 각각에 대해 pageSummaries 항목을 하나씩 생성하라(누락 금지): {_required_pages(pages)}"
    )


def _required_pages(pages: List[Dict[str, Any]]) -> str:
    nums = [str(p["page"]) for p in pages if p["page"] is not None and p["source"] != "INSUFFICIENT"]
    return "[" + ", ".join(nums) + "]" if nums else "(해당 없음)"


def _summarize_single_page(domain: Dict[str, Any], page: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """배치에서 누락된 '실제 텍스트가 있는' 페이지를 개별 요약(거짓 생성 방지·커버리지 보장)."""
    from app.services.ai_pipeline import openai_refine, parse_json, qwen_draft
    pno = page["page"]
    prompt = (
        f"너는 전공 PDF의 한 페이지를 요약하는 학습노트 생성기다. 전공 분야는 {domain['enum']}"
        f"({domain['label']})이다. 아래 [페이지 {pno} 내용]만 근거로, 다른 페이지를 상상하지 말고 "
        "이 페이지만 한국어로 요약하라. 내용에 없는 것을 지어내지 마라.\n\n"
        f"[페이지 {pno} 내용 (source={page['source']})]\n{page['text']}\n\n"
        "핵심 개념은 이름만 적지 말고 conceptExplanations에 '용어+쉬운 설명'으로 풀어 쓰고, "
        "개념 이해를 돕는 추가 예시를 examples에 1~3개 든다.\n"
        "아래 JSON 한 개로만 응답하라(마크다운 금지):\n"
        f'{{ "page": {pno if pno is not None else "null"}, "title": "페이지 제목", '
        '"pageOverview": "이 페이지가 무엇을 설명하는지 1~2문장", '
        '"keyConcepts": ["핵심 개념(이름)"], '
        '"conceptExplanations": [{"term": "개념 이름", "explanation": "쉬운 설명"}], '
        '"examples": ["추가 예시 1~3개"], '
        '"summaryBullets": ["핵심 요약 2~5개"], '
        '"studyFocus": "학습자가 이해해야 할 것 1~2문장" }'
    )
    raw = qwen_draft(_SYSTEM, prompt, max_tokens=800)
    parsed = parse_json(raw)
    if not isinstance(parsed, dict):
        raw = openai_refine(_SYSTEM, prompt, max_tokens=800)
        parsed = parse_json(raw)
    if isinstance(parsed, dict):
        parsed["page"] = pno
        return parsed
    return None


# ── 정규화 ───────────────────────────────────────────────────────────────────

def _clean(v: Any) -> str:
    try:
        from app.services.material_summary_builder import sanitize_markdown_text
        return sanitize_markdown_text(v)
    except Exception:
        return str(v or "").strip()


def _str_list(v: Any, limit: int) -> List[str]:
    if isinstance(v, str):
        v = [v]
    if not isinstance(v, (list, tuple)):
        return []
    out = []
    for x in v:
        s = _clean(x)
        if s:
            out.append(s)
        if len(out) >= limit:
            break
    return out


def _detail_list(v: Any, limit: int) -> List[Dict[str, str]]:
    if not isinstance(v, (list, tuple)):
        return []
    out = []
    for x in v:
        if isinstance(x, dict):
            title = _clean(x.get("title"))
            content = _clean(x.get("content"))
            if title or content:
                out.append({"title": title or "핵심", "content": content})
        elif isinstance(x, str) and x.strip():
            out.append({"title": "핵심", "content": _clean(x)})
        if len(out) >= limit:
            break
    return out


_VALID_SOURCES = {"TEXT", "OCR", "CAPTION", "TABLE", "IMAGE_DESCRIPTION", "MIXED", "INSUFFICIENT"}

# 결정론적 source → 사람이 읽는 콘텐츠 유형(텍스트/이미지 구분). 페이지 카드에 그대로 표기한다.
_CONTENT_TYPE_BY_SOURCE = {
    "TEXT": "텍스트",
    "OCR": "이미지(OCR 인식)",
    "IMAGE_DESCRIPTION": "이미지",
    "CAPTION": "이미지(캡션)",
    "TABLE": "표",
    "MIXED": "텍스트+이미지",
    "INSUFFICIENT": "내용 식별 제한",
}


def _content_type(source: Optional[str]) -> str:
    return _CONTENT_TYPE_BY_SOURCE.get((source or "").upper(), "텍스트")


def _concept_detail_list(v: Any, limit: int = 8) -> List[Dict[str, str]]:
    """conceptExplanations: [{term, explanation}] 정규화(문자열만 오면 explanation 비움)."""
    if not isinstance(v, (list, tuple)):
        return []
    out: List[Dict[str, str]] = []
    for x in v:
        if isinstance(x, dict):
            term = _clean(x.get("term") or x.get("concept") or x.get("name") or x.get("title"))
            expl = _clean(x.get("explanation") or x.get("desc") or x.get("description") or x.get("content"))
            if term or expl:
                out.append({"term": term or "개념", "explanation": expl})
        elif isinstance(x, str) and x.strip():
            out.append({"term": _clean(x), "explanation": ""})
        if len(out) >= limit:
            break
    return out


def _normalize_page_summaries(parsed: Any, pages: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """LLM의 pageSummaries를 결정론적 pages(page 번호·detectedTextSource 기준)와 대조해 정규화.
    LLM이 빠뜨렸거나 INSUFFICIENT 페이지는 솔직한 fallback 엔트리로 채운다(읽은 척 금지)."""
    by_page: Dict[Any, Dict[str, Any]] = {}
    if isinstance(parsed, list):
        for item in parsed:
            if isinstance(item, dict) and item.get("page") is not None:
                by_page[item.get("page")] = item

    out: List[Dict[str, Any]] = []
    for p in pages:
        page_no = p["page"]
        source = p["source"]  # 결정론적: FastAPI가 실제 받은 소스만 표기(권위 있음)
        if source == "INSUFFICIENT":
            entry = _page_fallback_entry(page_no)
            out.append(entry)
            continue
        llm = by_page.get(page_no) or {}
        bullets = _str_list(llm.get("summaryBullets"), 5)
        overview = _clean(llm.get("pageOverview"))
        title = _clean(llm.get("title"))
        focus = _clean(llm.get("studyFocus"))
        # LLM이 해당 페이지를 사실상 비웠으면 솔직한 fallback으로 대체
        if not overview and not bullets:
            entry = _page_fallback_entry(page_no)
            entry["detectedTextSource"] = source
            out.append(entry)
            continue
        concept_details = _concept_detail_list(llm.get("conceptExplanations"), 8)
        key_concepts = _str_list(llm.get("keyConcepts"), 8)
        # keyConcepts가 비고 conceptExplanations만 있으면 term으로 역채움(하위호환).
        if not key_concepts and concept_details:
            key_concepts = [c["term"] for c in concept_details if c.get("term")][:8]
        out.append({
            "page": page_no,
            "title": title or "핵심 내용",
            "detectedTextSource": source,
            "contentType": _content_type(source),
            "pageOverview": overview or (bullets[0] if bullets else ""),
            "keyConcepts": key_concepts,
            "conceptExplanations": concept_details,
            "examples": _str_list(llm.get("examples"), 3),
            "summaryBullets": bullets,
            "studyFocus": focus or "이 페이지의 핵심 개념을 중심으로 복습하세요.",
        })
    return out


def _detailed_from_pages(page_summaries: List[Dict[str, Any]]) -> List[Dict[str, str]]:
    """detailedCoreContents를 페이지별 요약의 사람이 읽기 좋은 압축으로 구성."""
    out: List[Dict[str, str]] = []
    for ps in page_summaries:
        pno = ps.get("page")
        prefix = f"p.{pno} " if pno is not None else ""
        title = f"{prefix}{ps.get('title') or '핵심 내용'}".strip()
        bullets = ps.get("summaryBullets") or []
        overview = ps.get("pageOverview") or ""
        content = overview
        if bullets:
            content = (overview + " " if overview else "") + " ".join(bullets)
        out.append({"title": title, "content": content.strip()})
        if len(out) >= 12:
            break
    return out


def _limitations(req: MajorAnalysisRequest, domain: Dict[str, Any]) -> List[str]:
    lims: List[str] = []
    itype = (req.inputType or "").upper()
    has_image_only = bool(req.ocrTexts or req.imageDescriptions) and not req.pageTexts
    if "IMAGE" in itype or "OCR" in itype or has_image_only:
        lims.append("이미지 직접 분석 파이프라인이 없어 OCR/캡션/주변 문맥 기반 분석이며, 인식 오류 가능성이 있습니다.")
    if domain["enum"] == "MATH":
        lims.append("수식 OCR 인식 오류로 기호/지수가 잘못 읽혔을 수 있습니다.")
    if domain["enum"] == "BIOLOGY_MICROBIOLOGY":
        lims.append("PDF 문맥 기반 학습 보조 분석이며 실제 검체 진단이나 균종 확정이 아닙니다.")
    if domain["enum"] == "MEDICINE_NURSING":
        lims.append("교육용 설명이며 실제 진단·치료 지시가 아닙니다.")
    if domain["enum"] == "LAW_PUBLIC_ADMIN":
        lims.append("학습용 쟁점 정리이며 실제 법률 자문이 아닙니다.")
    if domain["enum"] == "BUSINESS_ECONOMICS":
        lims.append("학습용 해설이며 투자 추천이 아닙니다.")
    if domain["enum"] == "ARCHITECTURE_CIVIL":
        lims.append("개념 설명이며 실제 구조 안전 판정이 아닙니다.")
    if not lims:
        lims.append("PDF 문맥 기반 학습 보조 분석이며 전문적 판단을 대체하지 않습니다.")
    return lims


def _fallback(req: MajorAnalysisRequest, domain: Optional[Dict[str, Any]],
              wiki: List[Dict[str, Any]],
              pages: Optional[List[Dict[str, Any]]] = None) -> Dict[str, Any]:
    d = domain or _GENERAL
    core = "문서의 핵심 전공 개념"
    # 페이지가 식별돼 있으면 페이지별 솔직한(INSUFFICIENT 포함) 엔트리는 유지한다.
    page_summaries = _normalize_page_summaries([], pages) if pages else []
    return {
        "materialId": req.materialId,
        "mode": MODE,
        "domain": d["enum"],
        "domainLabel": d["label"],
        "coreObject": core,
        "coreObjectLabel": core,
        "disclaimer": DISCLAIMER,
        "documentOverview": "PDF에서 전공 분야와 핵심 객체를 명확히 식별할 수 있는 텍스트가 충분하지 않습니다.",
        "keywords": [],
        "coreContents": ["자료의 제목, 본문 텍스트, 그림 캡션, 표, OCR 정보가 더 필요합니다."],
        "detailedCoreContents": _detailed_from_pages(page_summaries),
        "pageSummaries": page_summaries,
        "studyPoints": [
            "PDF의 제목과 목차를 먼저 확인하세요.",
            "그림이나 표의 캡션을 함께 확인하세요.",
            "반복해서 등장하는 용어를 중심으로 복습하세요.",
        ],
        "aiStudyQuestions": [
            "이 자료에서 반복해서 등장하는 핵심 용어는 무엇인가?",
            "그 용어가 전공 개념에서 어떤 역할을 하는가?",
            "그림, 표, 본문 설명은 서로 어떻게 연결되는가?",
        ],
        "wikiSummaries": wiki,
        "limitations": ["입력 정보가 부족하여 상세 분석이 제한되었습니다."],
    }


def _generate_sync(req: MajorAnalysisRequest) -> Dict[str, Any]:
    from app.services.ai_pipeline import openai_refine, parse_json, qwen_draft

    pages = []
    # s3Key가 있으면 S3에서 직접 다운로드하여 멀티모달(GPT-4o Vision)로 분석
    if req.s3Key:
        try:
            from app.services.s3_pdf_loader import load_pdf_bytes_from_s3
            from app.services.pdf_page_extractor import extract_pdf_pages
            import base64
            from io import BytesIO

            def gpt4o_vision_ocr(image) -> str:
                from app.services.openai_client import get_sync_client
                try:
                    client = get_sync_client()
                    buffer = BytesIO()
                    image.save(buffer, format="JPEG")
                    b64 = base64.b64encode(buffer.getvalue()).decode("utf-8")
                    resp = client.chat.completions.create(
                        model="gpt-4o",
                        messages=[
                            {
                                "role": "user",
                                "content": [
                                    {"type": "text", "text": "이 이미지에 포함된 모든 텍스트, 수식, 표, 다이어그램의 내용을 빠짐없이 정확히 추출해줘. 마크다운 기호 없이 텍스트만 출력하고, 표나 그림은 그 내용을 요약해서 텍스트로 적어줘."},
                                    {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{b64}"}}
                                ]
                            }
                        ],
                        max_tokens=1500,
                        temperature=0.0
                    )
                    return resp.choices[0].message.content or ""
                except Exception as e:
                    logger.warning("GPT Vision OCR failed: %s", e)
                    return ""

            pdf_bytes = load_pdf_bytes_from_s3(req.s3Key)
            pdf_result = extract_pdf_pages(
                pdf_bytes,
                ocr_enabled=True,
                ocr_fn=gpt4o_vision_ocr,
                ocr_max_pages=40, # 전체 페이지 OCR 허용
                min_text_chars=12
            )
            # pdf_result.pages를 기반으로 pages 배열 구성
            for p in pdf_result.pages:
                source = "MIXED" if p["hasImage"] else "TEXT"
                merged = (p["text"] + "\n" + p["ocrText"]).strip()
                if not merged:
                    source = "INSUFFICIENT"
                pages.append({"page": p["page"], "text": merged, "source": source})
            logger.info("GPT-4o 멀티모달 분석 완료: 총 %d 페이지 추출", len(pages))
        except Exception as e:
            logger.warning("S3 멀티모달 분석 실패, 기존 텍스트로 폴백: %s", e)
            pages = _collect_pages(req)
    else:
        pages = _collect_pages(req)

    text = "\n".join([p["text"] for p in pages if p["source"] != "INSUFFICIENT"])[:_MAX_TOTAL_CHARS]
    if not text:
        text = _combined_text(req)
        
    meaningful = re.sub(r"\s+", "", text)
    max_wiki = max(0, min(int(req.maxWikiResults or 0), 8))

    domain, _score = _classify_domain(text)
    candidates = _concept_candidates(text)

    # 입력이 사실상 비었을 때만 안전 fallback(짧은 OCR 수식 등은 도메인/후보가 있으면 통과).
    if len(meaningful) < _MIN_MEANINGFUL and _score == 0 and not candidates:
        return _fallback(req, None, [], pages)
    wiki = _fetch_wiki(candidates, max_wiki)

    prompt = _build_prompt(req, domain, wiki, candidates, pages)
    raw = openai_refine(_SYSTEM, prompt, max_tokens=2200)
    parsed = parse_json(raw)
    if not parsed:
        raw = openai_refine(_SYSTEM, prompt, max_tokens=2200)
        parsed = parse_json(raw)
    if not isinstance(parsed, dict):
        # LLM 실패 → 도메인/페이지는 유지한 fallback(업로드 실패 방지)
        return _fallback(req, domain, wiki, pages)

    core_obj = _clean(parsed.get("coreObject")) or (candidates[0] if candidates else "문서의 핵심 전공 개념")
    core_label = _clean(parsed.get("coreObjectLabel")) or core_obj
    overview = _clean(parsed.get("documentOverview"))
    keywords = _str_list(parsed.get("keywords"), 8)
    core_contents = _str_list(parsed.get("coreContents"), 6)
    study_points = _str_list(parsed.get("studyPoints"), 6)
    questions = _str_list(parsed.get("aiStudyQuestions"), 5)

    # 배치에서 누락된 '실제 텍스트가 있는' 페이지는 개별 재생성으로 커버리지 보장(거짓 생성 금지).
    llm_pages = parsed.get("pageSummaries")
    llm_pages = list(llm_pages) if isinstance(llm_pages, list) else []
    covered = {
        item.get("page") for item in llm_pages
        if isinstance(item, dict) and (item.get("pageOverview") or item.get("summaryBullets"))
    }
    retried = 0
    for p in pages:
        if retried >= _MAX_PAGE_RETRY:
            break
        if p["source"] != "INSUFFICIENT" and p["page"] not in covered:
            single = _summarize_single_page(domain, p)
            if single:
                llm_pages.append(single)
                retried += 1

    # 페이지별 요약(결정론적 page/source 기준으로 정규화 + 누락/불충분 페이지 보강)
    page_summaries = _normalize_page_summaries(llm_pages, pages)
    # detailedCoreContents는 페이지별 요약의 압축으로 구성(전체 문서 한 덩어리 금지).
    # 페이지가 없으면(소스 미제공) LLM detailedCoreContents 또는 coreContents로 폴백.
    if page_summaries:
        detailed = _detailed_from_pages(page_summaries)
    else:
        detailed = _detail_list(parsed.get("detailedCoreContents"), 6)

    # 핵심 섹션이 비면 fallback(추상/빈 응답을 성공으로 내보내지 않음)
    if not overview or not core_contents:
        return _fallback(req, domain, wiki, pages)

    return {
        "materialId": req.materialId,
        "mode": MODE,
        "domain": domain["enum"],
        "domainLabel": domain["label"],
        "coreObject": core_obj,
        "coreObjectLabel": core_label,
        "disclaimer": DISCLAIMER,
        "documentOverview": overview,
        "keywords": keywords,
        "coreContents": core_contents,
        "detailedCoreContents": detailed,
        "pageSummaries": page_summaries,
        "studyPoints": study_points,
        "aiStudyQuestions": questions,
        "wikiSummaries": wiki,
        "limitations": _limitations(req, domain),
    }


@router.post("/api/ai/major-analysis/note", summary="전공 분야+핵심 객체 중심 AI 요약 노트")
async def major_analysis_note(req: MajorAnalysisRequest = Body(...)):
    # 분석 실패가 업로드 실패가 되면 안 되므로 어떤 경우에도 200 + 구조화 JSON 반환.
    try:
        result = await asyncio.wait_for(
            asyncio.to_thread(_generate_sync, req), timeout=MAJOR_ANALYSIS_TIMEOUT)
        return result
    except asyncio.TimeoutError:
        logger.info("major-analysis timeout materialId=%s → fallback", req.materialId)
    except Exception as e:  # noqa: BLE001
        logger.warning("major-analysis 실패 materialId=%s: %s → fallback", req.materialId, e)
    try:
        pages = _collect_pages(req)
    except Exception:  # noqa: BLE001
        pages = []
    return _fallback(req, None, [], pages)
