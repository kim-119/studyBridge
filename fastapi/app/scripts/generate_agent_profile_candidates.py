#!/usr/bin/env python3
"""
generate_agent_profile_candidates.py
지식수준/성격/역할별 에이전트 QA 후보를 생성한다.

실행 예시:
  python app/scripts/generate_agent_profile_candidates.py \
    --out app/dataset/samples/sample_agent_profile_qa.jsonl
"""
import argparse
import json
from pathlib import Path

SYSTEM_PROMPT = (
    "너는 StudyBridge의 AI 학습 에이전트다. "
    "제공된 근거를 우선 사용하고, 근거 없는 내용은 단정하지 않는다. "
    "에이전트 설정과 지식수준을 반영해 한국어로 답변한다."
)

QUESTIONS_BY_LEVEL = [
    {
        "question": "운영체제에서 프로세스가 뭐야?",
        "levels": {
            "입문": {
                "agent": {"name": "쉬운설명봇", "role": "입문 도우미", "persona": "친절 설명형", "tone": "쉽고 친근하게", "goal": "어려운 말 없이 설명"},
                "answer": "프로세스는 쉽게 말해서 '실행 중인 프로그램'이에요!\n\n예를 들어, 카카오톡을 켜면 그게 프로세스가 되는 거예요. 컴퓨터는 여러 프로세스를 동시에 돌리면서 멀티태스킹을 해요.\n\n각 프로세스는 메모리, CPU 등 자원을 받아서 실행돼요."
            },
            "학사": {
                "agent": {"name": "전공지식봇", "role": "컴퓨터공학 튜터", "persona": "논리적 탐구형", "tone": "전공 수준 설명", "goal": "개념과 구조 설명"},
                "answer": "### 프로세스(Process) 정의\n\n프로세스는 실행 중인 프로그램의 인스턴스입니다.\n\n**구성 요소**:\n- **PCB(Process Control Block)**: 프로세스 상태, PID, PC, 레지스터 등\n- **스택**: 함수 호출, 지역 변수\n- **힙**: 동적 메모리 할당\n- **코드/데이터 영역**: 실행 코드, 전역 변수\n\n**프로세스 상태**: New → Ready → Running → Waiting → Terminated\n\n**스레드와의 차이**: 프로세스는 독립된 메모리 공간, 스레드는 같은 프로세스 내 메모리 공유"
            }
        }
    }
]

def build_user_content(agent: dict, question: str) -> str:
    return (
        f"[에이전트 설정]\n"
        f"이름: {agent['name']}\n"
        f"역할: {agent['role']}\n"
        f"성격/말투: {agent['persona']}\n"
        f"사용자 추가 요구사항: {agent['goal']}\n\n"
        f"[근거]\n없음 (일반 지식 기반 답변)\n\n"
        f"[질문]\n{question}"
    )

def generate_candidates(out_path: str):
    samples = []
    idx = 1

    for item in QUESTIONS_BY_LEVEL:
        question = item["question"]
        for level, data in item["levels"].items():
            agent = data["agent"]
            answer = data["answer"]

            sid = f"sb_agent_{idx:06d}"
            sample = {
                "id": sid,
                "messages": [
                    {"role": "system", "content": SYSTEM_PROMPT},
                    {"role": "user", "content": build_user_content(agent, question)},
                    {"role": "assistant", "content": answer},
                ],
                "metadata": {
                    "source_type": "agent_profile",
                    "quality_status": "auto_generated",
                    "requires_human_review": True,
                    "contains_code": False,
                    "contains_personal_data": False,
                    "contains_secret_candidate": False,
                    "language": "ko",
                    "project": "StudyBridge",
                    "repo_branch": "develop",
                    "agent_name": agent["name"],
                    "knowledge_level": level,
                    "created_by": "dataset_pipeline",
                    "notes": f"지식수준 {level} 샘플 (자동 생성)",
                }
            }
            samples.append(sample)
            idx += 1

    out = Path(out_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    with out.open("a", encoding="utf-8") as f:
        for s in samples:
            f.write(json.dumps(s, ensure_ascii=False) + "\n")

    print(f"[INFO] {len(samples)}개 agent_profile 후보 추가 → {out_path}")
    return samples

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", required=True)
    args = parser.parse_args()
    generate_candidates(args.out)

if __name__ == "__main__":
    main()
