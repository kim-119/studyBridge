

<!-- STUDYBRIDGE_MAIN_REPO_GUARD_START -->
# StudyBridge EC2 Claude Operating Rules

## Mandatory working directory

All Claude commands, Claude agents, and Claude subagents must work only inside this directory:

/home/ubuntu/studyBridge

The active branch must be:

LLM-clean

## Forbidden paths

Never create, edit, or use these paths for implementation work:

- /home/ubuntu/studyBridge/.claude/worktrees
- /home/ubuntu/sb-restore
- /home/ubuntu/sb-roadmap-video
- frontend/dist
- backend/build
- backend/.gradle
- node_modules
- .env
- __pycache__

## Source of truth

All code changes must be visible from:

cd /home/ubuntu/studyBridge
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

For frontend changes, verify:

cd frontend
npm run build

For Spring/backend changes, verify with the relevant Gradle or Docker Compose check before commit.

## Commit policy

Commit only real source or approved ops artifacts:

- frontend/src
- frontend/public
- backend/src
- fastapi/app
- fastapi/tests
- docker-compose.yml
- CLAUDE.md
- .claude/agents/studybridge-main-repo-guard.md

Never commit secrets, build outputs, node_modules, backend build artifacts, or Claude worktrees.
<!-- STUDYBRIDGE_MAIN_REPO_GUARD_END -->

