from app.training.studybridge_ft.package_dataset import split_rows


def _s(i):
    return {"messages": [{"role": "system", "content": "S"},
            {"role": "user", "content": f"q{i}"}, {"role": "assistant", "content": f"a{i}"}]}


def test_split_ratios_and_no_overlap():
    rows = [_s(i) for i in range(100)]
    sp = split_rows(rows, {"train": 0.9, "valid": 0.05, "test": 0.05}, seed=1)
    assert 88 <= len(sp["train"]) <= 92
    from app.training.studybridge_ft.utils.dedup import sample_hash
    tr = {sample_hash(x) for x in sp["train"]}
    assert all(sample_hash(x) not in tr for x in sp["valid"] + sp["test"])
