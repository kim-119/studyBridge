from .base import BaseGenerator
from ..validators.chatml import ChatMLValidator
from ..validators.quiz import QuizValidator
from ..validators.safety import SafetyValidator

_SYS = "너는 StudyBridge 퀴즈 출제기다. 반드시 유효한 JSON 1개만 출력한다."


class QuizGenerator(BaseGenerator):
    category = "quiz"
    system_prompt = _SYS
    validators = [ChatMLValidator(), QuizValidator(), SafetyValidator()]

    def user_prompt(self):
        return ('객관식 1문제를 JSON으로만 출력: '
                '{"question","choices":[4개],"answer":정답인덱스,'
                '"explanation","difficulty","source_hint"}')

    def parse(self, raw):
        return {"messages": [{"role": "system", "content": self.system_prompt},
                {"role": "user", "content": self.user_prompt()},
                {"role": "assistant", "content": (raw or "").strip()}]}
