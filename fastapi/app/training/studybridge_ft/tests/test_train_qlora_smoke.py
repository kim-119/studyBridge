import importlib.util
import pytest

HAVE = all(importlib.util.find_spec(m) for m in ("torch", "peft", "trl", "bitsandbytes"))


@pytest.mark.skipif(not HAVE, reason="deps missing")
def test_lora_and_mem_helpers():
    from app.training.studybridge_ft import train_qlora as t
    lc = t.build_lora_config({"lora": {"r": 16, "alpha": 32, "dropout": 0.05}})
    assert set(lc.target_modules) == {"q_proj", "k_proj", "v_proj", "o_proj"}
    bnb = t.build_bnb_config()
    assert bnb.bnb_4bit_quant_type == "nf4"
