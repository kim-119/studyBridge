from .base import BaseGenerator
from ..validators.chatml import ChatMLValidator
from ..validators.safety import SafetyValidator

_SYS = "너는 StudyBridge의 전문 학습 도우미다. 자연스럽고 정확한 한국어로 답한다."


class ConceptGenerator(BaseGenerator):
    category = "concept"
    system_prompt = _SYS
    validators = [ChatMLValidator(), SafetyValidator()]

    def user_prompt(self):
        return ("전공 개념 1개를 골라 다음 순서로 설명하라: "
                "정의 → 원리 → 예시 → 오개념 경고 → 확인 질문.")

    def parse(self, raw):
        return {"messages": [{"role": "system", "content": self.system_prompt},
                {"role": "user", "content": self.user_prompt()},
                {"role": "assistant", "content": (raw or "").strip()}]}
