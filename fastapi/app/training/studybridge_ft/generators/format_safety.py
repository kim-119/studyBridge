from .base import BaseGenerator
from ..validators.chatml import ChatMLValidator
from ..validators.safety import SafetyValidator

_SYS = "너는 StudyBridge 응답 형식 안정화 도우미다. 잘림/빈응답 없이 완결된 응답을 만든다."


class FormatSafetyGenerator(BaseGenerator):
    category = "format_safety"
    system_prompt = _SYS
    validators = [ChatMLValidator(), SafetyValidator()]

    def user_prompt(self):
        return "완결된 형식의 응답을 작성하라. 잘림/빈응답 금지."

    def parse(self, raw):
        return {"messages": [{"role": "system", "content": self.system_prompt},
                {"role": "user", "content": self.user_prompt()},
                {"role": "assistant", "content": (raw or "").strip()}]}
