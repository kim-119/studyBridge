from .base import BaseGenerator
from ..validators.chatml import ChatMLValidator
from ..validators.safety import SafetyValidator

_SYS = "너는 StudyBridge의 자료 기반 QA 도우미다. 자료에 근거해서만 답한다."


class ArchiveQAGenerator(BaseGenerator):
    category = "archive_qa"
    system_prompt = _SYS
    validators = [ChatMLValidator(), SafetyValidator()]

    def user_prompt(self):
        return ("자료 기반 질의응답을 수행하라. 근거가 있으면 근거에 기반해 답하고, "
                "근거가 부족하면 '자료 내 근거 부족'이라고 명시하라.")

    def parse(self, raw):
        return {"messages": [{"role": "system", "content": self.system_prompt},
                {"role": "user", "content": self.user_prompt()},
                {"role": "assistant", "content": (raw or "").strip()}]}
