from app.training.studybridge_ft.utils.dedup import Deduper, sample_hash


def _s(u, a):
    return {"messages": [{"role": "system", "content": "S"},
                         {"role": "user", "content": u},
                         {"role": "assistant", "content": a}]}


def test_hash_stable():
    assert sample_hash(_s("q", "a")) == sample_hash(_s("q", "a"))
    assert sample_hash(_s("q", "a")) != sample_hash(_s("q", "b"))


def test_deduper_flags_second():
    d = Deduper()
    assert d.is_dup(_s("q", "a")) is False
    assert d.is_dup(_s("q", "a")) is True
