"""AgentExecutionTrace / AgentCoverage — 관측 가능성.

프롬프트 원문은 로그에 남기지 않는다(promptHash 만). 트레이스는 all_complete.trace 로 내리고
[STUDYMATE-TRACE] 한 줄 JSON 로그로 남긴다.
"""
from __future__ import annotations

import json
import logging
import time
from dataclasses import asdict, dataclass, field
from typing import Any, Dict, List, Optional

logger = logging.getLogger("studybridge.studymate.trace")


@dataclass
class AgentExecutionTrace:
    requestId: str
    turnId: str
    agentId: Optional[str]
    agentIndex: Optional[int]
    mode: str
    stage: str
    personalityKey: Optional[str] = None
    knowledgeLevelKey: Optional[str] = None
    model: Optional[str] = None
    promptVersion: Optional[str] = None
    promptHash: Optional[str] = None
    numCtx: Optional[int] = None
    estimatedPromptTokens: Optional[int] = None
    actualPromptEvalCount: Optional[int] = None
    completionTokens: Optional[int] = None
    thinkingEnabled: bool = False
    groundingSources: List[str] = field(default_factory=list)
    groundingFailures: List[str] = field(default_factory=list)
    elapsedMs: int = 0
    ttftMs: Optional[int] = None
    status: str = "PENDING"
    failureCode: Optional[str] = None
    fallbackUsed: bool = False
    judgeUsed: bool = False
    repairCount: int = 0
    regenerationCount: int = 0
    cancelled: bool = False
    dedupDropped: int = 0
    parallelism: int = 1
    rubric: Dict[str, Any] = field(default_factory=dict)
    droppedSections: List[str] = field(default_factory=list)
    contextSaturated: bool = False
    startedAt: float = field(default_factory=time.time)

    def finish(self, status: str, failure_code: Optional[str] = None) -> "AgentExecutionTrace":
        self.status = status
        self.failureCode = failure_code
        self.elapsedMs = int((time.time() - self.startedAt) * 1000)
        return self

    def to_dict(self) -> Dict[str, Any]:
        d = asdict(self)
        d.pop("startedAt", None)
        return d

    PUBLIC_KEYS = ("agentId", "agentIndex", "stage", "personalityKey", "knowledgeLevelKey", "promptVersion",
                   "status", "failureCode", "elapsedMs", "ttftMs", "repairCount", "regenerationCount", "judgeUsed",
                   "fallbackUsed", "cancelled", "groundingSources")

    def public_dict(self) -> Dict[str, Any]:
        """클라이언트로 나가는 요약. 모델명/num_ctx/프롬프트 해시/토큰 수 등 내부 정보는 제외(서버 로그 전용)."""
        d = self.to_dict()
        out = {k: d.get(k) for k in self.PUBLIC_KEYS}
        out["groundingDegraded"] = bool(d.get("groundingFailures"))
        return out

    def log(self) -> None:
        logger.info("[STUDYMATE-TRACE] %s", json.dumps(self.to_dict(), ensure_ascii=False))


@dataclass
class AgentCoverage:
    selected: List[str] = field(default_factory=list)
    executed: List[str] = field(default_factory=list)
    emitted: List[str] = field(default_factory=list)
    failed: List[str] = field(default_factory=list)
    suppressed: List[str] = field(default_factory=list)
    suppressedReason: Optional[str] = None
    targeted: bool = False

    def mark(self, bucket: str, agent_id: Any) -> None:
        aid = str(agent_id)
        lst = getattr(self, bucket)
        if aid not in lst:
            lst.append(aid)

    def unexpected_gap(self) -> List[str]:
        """의도하지 않은 누락: 선택됐는데 emitted/failed/suppressed 어디에도 없는 에이전트."""
        accounted = set(self.emitted) | set(self.failed) | set(self.suppressed)
        return [a for a in self.selected if a not in accounted]

    def degraded(self) -> bool:
        return bool(self.failed) or bool(self.unexpected_gap())

    def to_dict(self) -> Dict[str, Any]:
        d = asdict(self)
        d["unexpectedGap"] = self.unexpected_gap()
        return d
