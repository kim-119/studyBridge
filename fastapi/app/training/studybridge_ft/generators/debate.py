from .base import BaseGenerator
from ..validators.chatml import ChatMLValidator
from ..validators.debate import DebateValidator
from ..validators.safety import SafetyValidator

_SYS = "너는 StudyBridge 토론 도우미다. 논증 구조를 갖춰 답한다."


class DebateGenerator(BaseGenerator):
    category = "debate"
    system_prompt = _SYS
    validators = [ChatMLValidator(), DebateValidator(), SafetyValidator()]

    def user_prompt(self):
        return ("주어진 논제에 대해 주장 / 반박 / 재반박 / 검증 기준 / 결론 "
                "구조로 논증하라.")

    def parse(self, raw):
        return {"messages": [{"role": "system", "content": self.system_prompt},
                {"role": "user", "content": self.user_prompt()},
                {"role": "assistant", "content": (raw or "").strip()}]}
