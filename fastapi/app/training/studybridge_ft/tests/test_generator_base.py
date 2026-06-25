from app.training.studybridge_ft.generators.base import BaseGenerator, GenResult
from app.training.studybridge_ft.validators.chatml import ChatMLValidator
from app.training.studybridge_ft.validators.safety import SafetyValidator
from app.training.studybridge_ft.utils.dedup import Deduper


class _FakeClient:
    def __init__(self, outs):
        self.outs = list(outs)
        self.i = 0

    def chat(self, s, u):
        v = self.outs[min(self.i, len(self.outs) - 1)]
        self.i += 1
        return v


class _G(BaseGenerator):
    category = "concept"
    system_prompt = "S"
    validators = [ChatMLValidator(), SafetyValidator()]

    def user_prompt(self):
        return "설명 요청"

    def parse(self, raw):
        return {"messages": [{"role": "system", "content": "S"},
                {"role": "user", "content": "u"}, {"role": "assistant", "content": raw}]}


def test_accept_valid(tmp_path):
    g = _G()
    client = _FakeClient(["좋은 한국어 설명입니다."])
    res = g.generate(1, client, Deduper(), tmp_path / "raw.jsonl",
                     tmp_path / "clean.jsonl", tmp_path / "rej")
    assert res.accepted == 1
    assert (tmp_path / "clean.jsonl").exists()


def test_repair_then_accept(tmp_path):
    g = _G()
    client = _FakeClient(["", "복구된 설명"])  # 첫 빈응답→repair
    res = g.generate(1, client, Deduper(), tmp_path / "raw.jsonl",
                     tmp_path / "clean.jsonl", tmp_path / "rej")
    assert res.accepted == 1 and res.repaired == 1


def test_reject_quarantined(tmp_path):
    g = _G()
    client = _FakeClient(["", ""])  # 계속 빈응답
    res = g.generate(1, client, Deduper(), tmp_path / "raw.jsonl",
                     tmp_path / "clean.jsonl", tmp_path / "rej")
    assert res.accepted == 0 and res.rejected == 1
    assert (tmp_path / "rej" / "empty_answer.jsonl").exists()


def test_resume_skips(tmp_path):
    from app.training.studybridge_ft.utils import jsonl_io
    clean = tmp_path / "clean.jsonl"
    jsonl_io.write_jsonl(clean, [{"messages": []}])
    g = _G()
    res = g.generate(1, _FakeClient(["x"]), Deduper(),
                     tmp_path / "raw.jsonl", clean, tmp_path / "rej")
    assert res.skipped is True and res.accepted == 0
