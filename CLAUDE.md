

<!-- STUDYBRIDGE_MAIN_REPO_GUARD_START -->
# StudyBridge ai07 Claude Operating Rules

## Mandatory working directory

All Claude commands, Claude agents, and Claude subagents must work only inside this directory:

/home/ai07/capstoneLLM

The active branch must be:

LLM-clean

## Forbidden paths

Never create, edit, or use these paths for implementation work:

- /home/ai07/capstoneLLM/.claude/worktrees
- /home/ai07/capstoneLLM-*
- frontend/dist
- backend/build
- node_modules
- .env
- .venv
- __pycache__

## Source of truth

All code changes must be visible from:

cd /home/ai07/capstoneLLM
git status -sb
git diff --name-status

If changes only appear inside a Claude worktree, the task is invalid.

## Required before editing

Before editing, print:

pwd
git branch --show-current
git status -sb

## Required after editing

After editing, print:

git status -sb
git diff --name-status
python3 -m compileall -q fastapi/app fastapi/tests fastapi/*.py

For FastAPI changes, restart and verify:

sudo systemctl restart studybridge-ai.service
curl -sS -i --max-time 8 http://127.0.0.1:8000/health

## Commit policy

Commit only real source or approved ops artifacts:

- fastapi/app
- fastapi/tests
- fastapi/*.py
- ops/n8n
- CLAUDE.md
- .claude/agents/studybridge-main-repo-guard.md

Never commit secrets, virtualenvs, build outputs, node_modules, or Claude worktrees.
<!-- STUDYBRIDGE_MAIN_REPO_GUARD_END -->

