"""
핵심 키워드 개념 정의 — 자료보관함 chip 클릭 → Spring → 아래 엔드포인트.

  POST /api/ai/keyword/define
    req:  {keyword, source(auto|gpt|wikipedia), level, context?}
    resp: {success, name, shortDefinition, detailedDefinition, importance,
           examples[], relatedConcepts[], sourceUsed(GPT|Wikipedia|Mixed), wikiUrl?}

전략: GPT 우선 + Wikipedia(ko) 보강. Wikipedia 실패/미존재 시 GPT-only로 graceful fallback.
하드코딩 금지: 타임아웃/위키 베이스 URL은 env로 제어.
"""
import asyncio
import json
import logging
import os
from typing import Any, Dict, List, Optional

import httpx
from fastapi import APIRouter
from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/ai", tags=["Keyword Define"])

KEYWORD_DEFINE_TIMEOUT = int(os.getenv("AI_KEYWORD_DEFINE_TIMEOUT_SECONDS", "60"))
WIKIPEDIA_API_BASE = os.getenv(
    "WIKIPEDIA_API_BASE", "https://ko.wikipedia.org/api/rest_v1/page/summary"
)
WIKIPEDIA_TIMEOUT = int(os.getenv("WIKIPEDIA_TIMEOUT_SECONDS", "8"))


class KeywordDefineReq(BaseModel):
    keyword: str = Field(..., description="정의할 키워드")
    source: str = Field("auto", description="auto | gpt | wikipedia")
    level: str = Field("undergraduate", description="학습 수준 (undergraduate 등)")
    context: Optional[str] = Field(None, description="문서 맥락 (선택)")


def _listify(v: Any) -> List[str]:
    if isinstance(v, list):
        return [str(x).strip() for x in v if str(x).strip()]
    if isinstance(v, str) and v.strip():
        return [s.strip() for s in v.replace("\n", ",").split(",") if s.strip()]
    return []


def _llm(system: str, user: str, max_tokens: int) -> str:
    """주력 LLM(Ollama/Qwen) 우선, 실패 시 GPT fallback. ai07은 GPT 비활성이라 Ollama가 주력."""
    from app.services.material_ai_manager import _call_gpt
    try:
        from app.services.llm_engine_router import call_primary_llm
        out = call_primary_llm(system_prompt=system, user_prompt=user, max_tokens=max_tokens, temperature=0.3)
        if out and not out.strip().startswith("["):
            return out
    except Exception as e:
        logger.info("primary LLM 실패, GPT 시도: %s", e)
    return _call_gpt(system, user, max_tokens=max_tokens)


def _gpt_define(keyword: str, level: str, context: Optional[str]) -> Optional[Dict[str, Any]]:
    """LLM으로 구조화된 개념 정의 JSON을 생성한다 (Ollama 우선)."""
    from app.utils.json_parser import extract_json

    system = (
        "너는 학습 개념을 명확하게 설명하는 교육 전문가다. "
        "반드시 한국어로, 아래 JSON 스키마에 맞춰 사실에 근거해 답한다. "
        "추측이 필요하면 일반적으로 통용되는 정의를 제공한다."
    )
    ctx = f"\n\n## 문서 맥락(참고)\n{context[:1500]}" if context else ""
    user = (
        f"## 정의할 개념\n{keyword}\n\n"
        f"## 학습 수준\n{level}{ctx}\n\n"
        "아래 JSON 형식으로만 응답하라(설명/마크다운 금지):\n"
        "{\n"
        '  "name": "개념명",\n'
        '  "shortDefinition": "한 문장 정의",\n'
        '  "detailedDefinition": "3~5문장 자세한 정의",\n'
        '  "importance": "왜 중요한지 2~3문장",\n'
        '  "examples": ["예시1", "예시2"],\n'
        '  "relatedConcepts": ["관련개념1", "관련개념2"]\n'
        "}"
    )
    raw = _llm(system, user, max_tokens=900)
    if not raw or raw.strip().startswith("[GPT") or raw.strip().startswith("["):
        return None
    parsed = extract_json(raw)
    if not isinstance(parsed, dict):
        return None
    return {
        "name": str(parsed.get("name") or keyword).strip(),
        "shortDefinition": str(parsed.get("shortDefinition") or "").strip(),
        "detailedDefinition": str(parsed.get("detailedDefinition") or "").strip(),
        "importance": str(parsed.get("importance") or "").strip(),
        "examples": _listify(parsed.get("examples")),
        "relatedConcepts": _listify(parsed.get("relatedConcepts")),
    }


async def _wikipedia_define(keyword: str) -> Optional[Dict[str, Any]]:
    """Wikipedia(ko) REST summary 조회. 없으면 None."""
    from urllib.parse import quote
    url = f"{WIKIPEDIA_API_BASE}/{quote(keyword, safe='')}"
    try:
        async with httpx.AsyncClient(timeout=WIKIPEDIA_TIMEOUT, follow_redirects=True) as client:
            resp = await client.get(
                url,
                headers={"accept": "application/json", "user-agent": "StudyBridge/1.0"},
            )
        if resp.status_code != 200:
            return None
        data = resp.json()
        if data.get("type") == "disambiguation":
            return None
        extract = (data.get("extract") or "").strip()
        if not extract:
            return None
        return {
            "name": data.get("title") or keyword,
            "extract": extract,
            "wikiUrl": (data.get("content_urls", {}).get("desktop", {}) or {}).get("page"),
        }
    except Exception as e:
        logger.info("Wikipedia 조회 실패(%s): %s", keyword, e)
        return None


@router.post("/keyword/define", summary="핵심 키워드 개념 정의 (GPT + Wikipedia)")
async def keyword_define(req: KeywordDefineReq) -> Dict[str, Any]:
    keyword = (req.keyword or "").strip()
    if not keyword:
        return {"success": False, "errorCode": "KEYWORD_EMPTY", "message": "키워드가 비어 있습니다."}

    source = (req.source or "auto").lower()
    want_gpt = source in ("auto", "gpt")
    want_wiki = source in ("auto", "wikipedia")

    gpt_task = asyncio.to_thread(_gpt_define, keyword, req.level, req.context) if want_gpt else None
    wiki_task = _wikipedia_define(keyword) if want_wiki else None

    try:
        if gpt_task is not None and wiki_task is not None:
            gpt_res, wiki_res = await asyncio.wait_for(
                asyncio.gather(gpt_task, wiki_task), timeout=KEYWORD_DEFINE_TIMEOUT
            )
        elif gpt_task is not None:
            gpt_res = await asyncio.wait_for(gpt_task, timeout=KEYWORD_DEFINE_TIMEOUT)
            wiki_res = None
        else:
            wiki_res = await asyncio.wait_for(wiki_task, timeout=KEYWORD_DEFINE_TIMEOUT)
            gpt_res = None
    except asyncio.TimeoutError:
        return {"success": False, "errorCode": "AI_TIMEOUT",
                "message": "개념 정의 시간이 초과되었습니다. 잠시 후 다시 시도해주세요."}
    except Exception as e:
        logger.error("keyword/define 실패: %s", e)
        return {"success": False, "errorCode": "KEYWORD_DEFINE_FAILED",
                "message": "개념 정의 생성에 실패했습니다. 다시 시도해주세요."}

    if not gpt_res and not wiki_res:
        return {"success": False, "errorCode": "KEYWORD_NO_RESULT",
                "message": "해당 키워드의 개념 정의를 찾지 못했습니다."}

    # 병합: GPT 기반 골격 + Wikipedia 정의 보강
    base = gpt_res or {
        "name": keyword, "shortDefinition": "", "detailedDefinition": "",
        "importance": "", "examples": [], "relatedConcepts": [],
    }
    wiki_url = None
    if wiki_res:
        wiki_url = wiki_res.get("wikiUrl")
        if not base.get("name"):
            base["name"] = wiki_res.get("name") or keyword
        # GPT 정의가 비었으면 Wikipedia extract로 채운다
        if not base.get("shortDefinition"):
            base["shortDefinition"] = wiki_res["extract"].split(". ")[0][:300]
        if not base.get("detailedDefinition"):
            base["detailedDefinition"] = wiki_res["extract"][:1200]

    if gpt_res and wiki_res:
        source_used = "Mixed"
    elif wiki_res:
        source_used = "Wikipedia"
    else:
        source_used = "GPT"

    return {
        "success": True,
        "name": base["name"],
        "shortDefinition": base["shortDefinition"],
        "detailedDefinition": base["detailedDefinition"],
        "importance": base["importance"],
        "examples": base["examples"],
        "relatedConcepts": base["relatedConcepts"],
        "sourceUsed": source_used,
        "wikiUrl": wiki_url,
        "wikiExtract": wiki_res["extract"] if wiki_res else None,
    }
