from .base import BaseGenerator
from ..validators.chatml import ChatMLValidator
from ..validators.socratic import SocraticValidator
from ..validators.safety import SafetyValidator

_SYS = "너는 소크라테스식 튜터다. 정답을 직접 말하지 않고 질문으로 사고를 유도한다."


class SocraticGenerator(BaseGenerator):
    category = "socratic"
    system_prompt = _SYS
    validators = [ChatMLValidator(), SocraticValidator(), SafetyValidator()]

    def user_prompt(self):
        return ("학습자가 개념을 묻는다. 정답 직답 금지. "
                "질문→힌트→유도→부분 정리→최종 정리, 유도 질문 2개 이상.")

    def parse(self, raw):
        return {"messages": [{"role": "system", "content": self.system_prompt},
                {"role": "user", "content": self.user_prompt()},
                {"role": "assistant", "content": (raw or "").strip()}]}
