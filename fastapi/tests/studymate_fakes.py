"""학습메이트 v2 테스트용 가짜 Ollama transport (실제 GPU 미사용)."""
from __future__ import annotations

import json
import re
import threading
from typing import Any, Callable, Dict, List, Optional

from app.studymate import llm_gateway as G

PERSONA_TEXT = {
    "friendly": ("처음 보면 헷갈리죠. 쉽게 말하면 {topic}은 마치 도서관 찾아보기처럼 생각해 보면 돼요. "
                 "왜 중요하냐면 전체를 뒤지지 않아도 되기 때문이에요. 예를 들어 {agent} 방식으로 보면 금방 이해돼요. "
                 "즉, 필요한 것만 빨리 꺼내는 구조예요. 단계는 먼저 요청을 받고 그다음 저장소를 확인하는 과정이에요. "
                 "표준 구현 방식은 키-값 자료구조예요. 다음에는 만료 정책을 같이 보면 좋아요."),
    "critical": ("'{topic}이면 무조건 빨라진다'는 전제부터 따져야 한다. 반례로 쓰기가 잦으면 오히려 느려지는 경우가 있다. "
                 "한계는 메모리 비용과 일관성 문제다. {agent} 관점에서 가정은 읽기 비율이 높다는 것이다. "
                 "경계조건은 캐시 적중률이 낮을 때이고 이때 이점이 성립하지 않는다. 실패 영역은 무효화 지연이다. "
                 "정의는 자주 쓰는 데이터를 앞단에 두는 구조다. 개선 방향은 측정 후 적용이다."),
    "creative": ("오케스트라의 악보대를 떠올려 보자. {topic}은 연주자 앞에 펼쳐둔 악보 같은 존재다. "
                 "관점을 뒤집어 보면 속도보다 기억의 배치 문제다. 정확히는 자주 쓰는 데이터를 가까이 두는 구조다. "
                 "{agent}의 새로운 각도로 보면 트레이드오프는 공간을 내주고 시간을 얻는 거래다. 실무에서는 세션 저장에 쓴다. "
                 "구조는 앞단 저장소와 원본 저장소의 계층이고 실패 모드는 오래된 값이다."),
    "concise": ("- 핵심: {topic}은 인메모리 키-값 저장소다.\n- 이유: 디스크 대비 접근이 빠르기 때문이다.\n"
                "- 정의: 자주 쓰는 데이터를 메모리에 두는 구조.\n- 결론: 따라서 조회 지연을 줄인다. ({agent})"),
    "sardonic": ("그래, {topic} 하나 붙이면 모든 게 빨라진다는 착각이지. 현실은 무효화가 늦으면 틀린 값을 빨리 줄 뿐이야. "
                 "문제는 일관성이야. 제대로 된 모델은 읽기 많은 경로에만 쓰는 거야. {agent}. "
                 "정의하자면 메모리 앞단 저장소고 과정은 조회 후 적재야. 표준 방식은 키-값 구조야."),
    "logical": ("정의: {topic}은 인메모리 키-값 저장소다.\n1) 전제: 메모리 접근은 디스크보다 빠르다.\n"
                "2) 전제: 조회가 반복된다.\n3) 추론: 따라서 반복 조회를 메모리에서 처리하면 지연이 준다.\n"
                "결론: 그러므로 읽기 중심 부하에 적합하다. ({agent}) 단계별 동작 원리와 표준 구현 방식은 해시 테이블이다."),
}


def _schema_instance(schema: Dict[str, Any], tag: str) -> Any:
    t = schema.get("type")
    if t == "object":
        return {k: _schema_instance(v, f"{tag}.{k}") for k, v in (schema.get("properties") or {}).items()}
    if t == "array":
        n = max(1, schema.get("minItems", 1))
        return [f"{tag} 항목{i + 1} 내용" for i in range(n)]
    if t == "boolean":
        return True
    return f"{tag} 값 설명"


class FakeOllama:
    def __init__(self, *, render: Optional[Callable[[G.LLMRequest], str]] = None,
                 fail: Optional[Dict[str, BaseException]] = None, planner_raw: Optional[List[str]] = None,
                 judge_value: bool = True):
        self.calls: List[G.LLMRequest] = []
        self.lock = threading.Lock()
        self.render = render
        self.fail = fail or {}
        self.planner_raw = list(planner_raw or [])
        self.judge_value = judge_value

    def count(self, task: Optional[str] = None) -> int:
        return len([c for c in self.calls if task is None or c.task == task])

    def __call__(self, req: G.LLMRequest):
        with self.lock:
            self.calls.append(req)
            n = len(self.calls)
        if req.task in self.fail:
            raise self.fail[req.task]
        if req.format is not None and req.task == "planner":
            text = self.planner_raw.pop(0) if self.planner_raw else json.dumps(_schema_instance(req.format, "plan"), ensure_ascii=False)
        elif req.format is not None and req.task == "judge":
            text = json.dumps({k: self.judge_value for k in req.format.get("properties", {})})
        elif self.render is not None:
            text = self.render(req)
        else:
            persona = next((k for k, v in {"friendly": "PERSONALITY: 친근함", "critical": "PERSONALITY: 비판형",
                                            "creative": "PERSONALITY: 독특함", "concise": "PERSONALITY: 효율적",
                                            "sardonic": "PERSONALITY: 냉소적", "logical": "PERSONALITY: 논리형"}.items()
                            if v in req.system), "logical")
            m = re.search(r"너의 이름은 '([^']+)'", req.system)
            agent = m.group(1) if m else f"agent{n}"
            text = PERSONA_TEXT[persona].format(topic="캐시", agent=f"{agent}-{n}-" + "가나다라마바사"[n % 7] * 3)
        return iter([{"message": {"content": text}, "done": False},
                     {"message": {"content": ""}, "done": True, "done_reason": "stop",
                      "prompt_eval_count": 1500, "eval_count": 300,
                      "prompt_eval_duration": 20_000_000, "eval_duration": 4_000_000_000}])


def install(monkeypatch, fake: FakeOllama) -> FakeOllama:
    # monkeypatch 가 '원래 값(None)'을 기록하도록 먼저 setattr 한다(테스트 간 transport 누수 방지).
    monkeypatch.setattr(G, "_TRANSPORT", fake)
    return fake


def parse_sse(text: str) -> List[tuple]:
    events = []
    for block in text.split("\n\n"):
        name, data = None, None
        for line in block.splitlines():
            if line.startswith("event: "):
                name = line[7:]
            elif line.startswith("data: "):
                data = line[6:]
        if name:
            events.append((name, json.loads(data) if data else {}))
    return events


AGENTS3 = [
    {"agentId": 101, "name": "김교수", "personality": "친근함", "personalityStyle": "friendly", "knowledgeLevel": "BEGINNER"},
    {"agentId": 102, "name": "이교수", "personality": "비판형", "personalityStyle": "honest", "knowledgeLevel": "DOCTOR"},
    {"agentId": 103, "name": "박교수", "personality": "독특함", "personalityStyle": "unique", "knowledgeLevel": "MASTER"},
]
