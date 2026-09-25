import re
from .base import BaseGenerator
from ..validators.chatml import ChatMLValidator
from ..validators.professor import ProfessorValidator
from ..validators.safety import SafetyValidator

_SPEAKERS = ["김교수", "이교수", "박교수"]
_SYS = "너는 StudyBridge 멀티에이전트 교수다. 지정된 한 교수의 역할/말투만 유지한다."


class ProfessorGenerator(BaseGenerator):
    category = "professor"
    system_prompt = _SYS
    validators = [ChatMLValidator(), ProfessorValidator(), SafetyValidator()]
    _idx = 0

    def user_prompt(self):
        sp = _SPEAKERS[self._idx % len(_SPEAKERS)]
        return f"{sp}님께 질문합니다. {sp}만 '[{sp}] 내용' 형식으로 답하라."

    def parse(self, raw):
        up = self.user_prompt()
        sp = re.search(r"\[([^\]]+)\]", up)
        expected = sp.group(1) if sp else _SPEAKERS[0]
        ProfessorGenerator._idx += 1
        return {"messages": [{"role": "system", "content": self.system_prompt},
                {"role": "user", "content": up},
                {"role": "assistant", "content": (raw or "").strip()}],
                "metadata": {"expected_speaker": expected}}
