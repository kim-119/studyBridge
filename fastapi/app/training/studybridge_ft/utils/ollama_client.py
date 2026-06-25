"""Ollama qwen3:14b self-distillation 클라이언트. think=False, concurrency=1, VRAM 가드."""
import subprocess
import threading
import time

import requests

_GEN_SEM = threading.Semaphore(1)  # max_concurrent_generation=1


def _vram_used_mib() -> int:
    try:
        out = subprocess.run(
            ["nvidia-smi", "--query-gpu=memory.used", "--format=csv,noheader,nounits"],
            capture_output=True, text=True, timeout=10).stdout
        return max(int(x) for x in out.split() if x.strip().isdigit())
    except Exception:
        return 0


class OllamaClient:
    def __init__(self, base_url, model, think=False, num_predict=1024,
                 temperature=0.7, timeout_s=180, vram_guard_mib=14000):
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.think = think
        self.num_predict = num_predict
        self.temperature = temperature
        self.timeout_s = timeout_s
        self.vram_guard_mib = vram_guard_mib

    def _wait_for_vram(self, tries=20, sleep_s=15):
        for _ in range(tries):
            if _vram_used_mib() < self.vram_guard_mib:
                return True
            time.sleep(sleep_s)
        return False

    def _post_once(self, system, user) -> str:
        payload = {
            "model": self.model, "stream": False, "think": self.think,
            "options": {"num_predict": self.num_predict, "temperature": self.temperature},
            "messages": [{"role": "system", "content": system},
                         {"role": "user", "content": user}],
        }
        r = requests.post(f"{self.base_url}/api/chat", json=payload, timeout=self.timeout_s)
        r.raise_for_status()
        return (r.json().get("message", {}).get("content") or "").strip()

    def chat(self, system: str, user: str) -> str:
        with _GEN_SEM:
            self._wait_for_vram()
            try:
                out = self._post_once(system, user)
                if out:
                    return out
            except Exception:
                pass
            try:
                return self._post_once(system, user)  # 1회 재시도
            except Exception:
                return ""

    def model_digest(self) -> str:
        try:
            r = requests.post(f"{self.base_url}/api/show", json={"name": self.model},
                              timeout=30)
            r.raise_for_status()
            j = r.json()
            return j.get("digest") or (j.get("details", {}) or {}).get("parent_model") or "unknown"
        except Exception:
            return "unknown"
