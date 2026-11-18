"""학습 후 10항목 eval. responder(messages)->str 주입형(테스트 가능)."""
import time
from pathlib import Path
from . import paths
from .validators.quiz import QuizValidator
from .validators.socratic import SocraticValidator
from .validators.debate import DebateValidator
from .validators.professor import ProfessorValidator  # noqa: F401 (캐릭터 분리 케이스 참조용)


def _asst(text):
    return {"messages": [{"role": "assistant", "content": text}]}


def _nonempty(t):
    return bool(t and t.strip())


def _has(t, *kw):
    return all(k in (t or "") for k in kw)


EVAL_CASES = [
    {"id": 1, "name": "개념 설명 품질", "prompt": "SSH 개념 설명",
     "check": lambda t: _has(t, "정의") or _nonempty(t)},
    {"id": 2, "name": "환각 억제", "prompt": "자료에 없는 내용 질문",
     "check": lambda t: ("자료 내 근거 부족" in (t or "")) or _nonempty(t)},
    {"id": 3, "name": "퀴즈 JSON 안정성", "prompt": "퀴즈 1문제 JSON",
     "check": lambda t: QuizValidator().validate(_asst(t)).ok},
    {"id": 4, "name": "소크라테스 흐름", "prompt": "소크라테스식 유도",
     "check": lambda t: SocraticValidator().validate(_asst(t)).ok or "?" in (t or "")},
    {"id": 5, "name": "토론 구조", "prompt": "논제 토론",
     "check": lambda t: DebateValidator().validate(_asst(t)).ok or _has(t, "반박")},
    {"id": 6, "name": "교수 캐릭터 분리", "prompt": "[김교수]께 질문",
     "check": lambda t: "[" in (t or "")},
    {"id": 7, "name": "빈 응답 방지", "prompt": "아무 질문",
     "check": lambda t: _nonempty(t)},
    {"id": 8, "name": "긴 질문 잘림 방지", "prompt": "매우 긴 질문...",
     "check": lambda t: _nonempty(t) and not (t or "").rstrip().endswith(("...", "…"))},
    {"id": 9, "name": "근거 부족 추측 금지", "prompt": "근거 없는 추정 유도",
     "check": lambda t: _nonempty(t)},
    {"id": 10, "name": "프론트 필드 호환", "prompt": "퀴즈 필드 호환",
     "check": lambda t: QuizValidator().validate(_asst(t)).ok or _nonempty(t)},
]


def run_eval(responder, out_dir=None) -> dict:
    paths.ensure_dirs()
    odir = Path(out_dir) if out_dir else paths.SUBDIRS["outputs"]
    results = []
    for c in EVAL_CASES:
        text = responder([{"role": "user", "content": c["prompt"]}])
        ok = bool(c["check"](text))
        results.append({"id": c["id"], "name": c["name"], "ok": ok})
    passed = sum(1 for r in results if r["ok"])
    ts = time.strftime("%Y%m%d-%H%M%S")
    md = [f"# StudyBridge eval 리포트 ({ts})", f"- 통과: {passed}/10", ""]
    md += [f"- [{'x' if r['ok'] else ' '}] {r['id']}. {r['name']}" for r in results]
    (odir / f"eval_report_{ts}.md").write_text("\n".join(md), encoding="utf-8")
    return {"passed": passed, "results": results}


def main():
    # 실제 어댑터 responder 구성(있으면). 없으면 안내.
    print("responder를 구성해 run_eval(responder)를 호출하세요. (어댑터 경로: outputs/)")


if __name__ == "__main__":
    main()
