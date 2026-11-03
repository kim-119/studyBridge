"""작업별 평가 프로파일(차원 가중치 합 100, 필수 검증기, 근거 요구 여부)."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, FrozenSet, Tuple

from app.contracts.response_quality_v1 import TaskType


@dataclass(frozen=True)
class Profile:
    name: str
    weights: Tuple[Tuple[str, int], ...]
    requires_evidence: bool = False      # PDF 계열: 근거 없으면 검증 불가/하드 실패
    factual_required: bool = True        # 사실 정확성이 '검증'돼야 승인 가능
    validators: FrozenSet[str] = field(default_factory=frozenset)
    judge_may_replace_evidence: bool = False

    def __post_init__(self) -> None:
        total = sum(w for _, w in self.weights)
        if total != 100:
            raise ValueError(f"profile {self.name} weights sum {total} != 100")

    def weight(self, dim: str) -> int:
        return dict(self.weights).get(dim, 0)


T = TaskType
_P = Profile

PROFILES: Dict[TaskType, Profile] = {
    T.GENERAL_EXPLANATION: _P("general", (("factual_correctness", 30), ("grounding", 25), ("request_fulfillment", 20),
                                         ("logical_consistency", 15), ("format", 10)), judge_may_replace_evidence=True),
    T.CREATIVE_EXPLORATION: _P("creative", (("request_fulfillment", 35), ("logical_consistency", 25),
                                           ("uncertainty_honesty", 20), ("format", 20)), factual_required=False),
    T.STUDYMATE_BASIC: _P("studymate_basic", (("factual_correctness", 30), ("grounding", 20), ("request_fulfillment", 20),
                                             ("logical_consistency", 10), ("persona_level", 10), ("format", 10)),
                          judge_may_replace_evidence=True),
    T.STUDYMATE_SOCRATIC: _P("studymate_socratic", (("question_quality", 30), ("request_fulfillment", 20),
                                                   ("factual_correctness", 20), ("logical_consistency", 10),
                                                   ("persona_level", 10), ("format", 10)),
                             validators=frozenset({"socratic"}), judge_may_replace_evidence=True),
    T.STUDYMATE_DEBATE: _P("studymate_debate", (("argument_evidence", 30), ("factual_correctness", 25),
                                               ("request_fulfillment", 15), ("logical_consistency", 15),
                                               ("persona_level", 5), ("format", 10)),
                           validators=frozenset({"debate"}), judge_may_replace_evidence=True),
    T.STUDYMATE_ROLEPLAY: _P("studymate_roleplay", (("scenario_consistency", 35), ("request_fulfillment", 25),
                                                   ("persona_level", 20), ("format", 20)), factual_required=False),
    T.PDF_SUMMARY: _P("pdf_summary", (("source_fidelity", 35), ("coverage", 20), ("grounding", 20),
                                      ("logical_consistency", 15), ("format", 10)), requires_evidence=True,
                      validators=frozenset({"source_fidelity", "scope"})),
    T.PDF_QA: _P("pdf_qa", (("factual_correctness", 30), ("grounding", 30), ("citation", 15),
                            ("request_fulfillment", 15), ("format", 10)), requires_evidence=True,
                 validators=frozenset({"source_fidelity", "scope"})),
    T.PDF_QUIZ: _P("pdf_quiz", (("structure", 25), ("answer_key", 30), ("grounding", 25), ("request_fulfillment", 10),
                                ("format", 10)), requires_evidence=True, validators=frozenset({"quiz", "scope"})),
    T.WRONG_NOTE_EXPLANATION: _P("wrong_note", (("solution_reverification", 35), ("concept_consistency", 25),
                                                ("grounding", 15), ("request_fulfillment", 15), ("format", 10)),
                                 validators=frozenset({"math"}), judge_may_replace_evidence=True),
    T.SIMILAR_QUESTION: _P("similar_question", (("structure", 20), ("answer_key", 35), ("concept_consistency", 25),
                                                ("request_fulfillment", 10), ("format", 10)),
                           validators=frozenset({"quiz", "math"}), judge_may_replace_evidence=True),
    T.MATH_SOLUTION: _P("math", (("factual_correctness", 45), ("logical_consistency", 25), ("request_fulfillment", 20),
                                 ("format", 10)), validators=frozenset({"math"})),
    T.PLANNER_COACHING: _P("planner", (("feasibility", 35), ("rule_consistency", 25), ("request_fulfillment", 20),
                                       ("format", 20)), factual_required=False, validators=frozenset({"plan"})),
    T.SEMANTIC_GRAPH: _P("semantic_graph", (("structure", 30), ("relation_validity", 30), ("grounding", 20),
                                            ("request_fulfillment", 10), ("format", 10)), factual_required=False,
                         validators=frozenset({"graph", "scope"})),
    T.VISION_CAPTION: _P("vision", (("observation_grounding", 35), ("uncertainty_honesty", 20), ("privacy", 20),
                                    ("request_fulfillment", 15), ("format", 10)), factual_required=False,
                         validators=frozenset({"vision"})),
    T.GROUP_STUDY_MESSAGE: _P("group_study", (("scope", 30), ("context_consistency", 25), ("factual_correctness", 25),
                                              ("request_fulfillment", 10), ("format", 10)),
                              validators=frozenset({"group"}), judge_may_replace_evidence=True),
}


def get_profile(task: TaskType) -> Profile:
    return PROFILES[task]
