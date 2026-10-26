#!/usr/bin/env bash
set -euo pipefail

REPOSITORY="${REPOSITORY:?REPOSITORY is required (owner/name)}"
COMMIT_SHA="${COMMIT_SHA:?COMMIT_SHA is required}"
CI_WORKFLOW_FILE="${CI_WORKFLOW_FILE:-ci.yml}"
TIMEOUT_SECONDS="${TIMEOUT_SECONDS:-2700}"
POLL_SECONDS="${POLL_SECONDS:-30}"

RUNS_URL="https://api.github.com/repos/${REPOSITORY}/actions/workflows/${CI_WORKFLOW_FILE}/runs?head_sha=${COMMIT_SHA}&event=push&per_page=20"

fetch_latest_run() {
  local auth_header=()
  if [ -n "${GH_TOKEN:-}" ]; then
    auth_header=(-H "Authorization: Bearer ${GH_TOKEN}")
  fi

  curl -fsS "${auth_header[@]}" -H "Accept: application/vnd.github+json" "$RUNS_URL" \
    | jq -c '[.workflow_runs[]] | sort_by(.run_number) | last // empty'
}

deadline=$(( $(date +%s) + TIMEOUT_SECONDS ))
echo "CI gate: ${CI_WORKFLOW_FILE} @ ${COMMIT_SHA}"

while true; do
  latest_run="$(fetch_latest_run)"

  if [ -n "$latest_run" ]; then
    status="$(jq -r '.status' <<< "$latest_run")"
    conclusion="$(jq -r '.conclusion // ""' <<< "$latest_run")"
    run_url="$(jq -r '.html_url' <<< "$latest_run")"
    echo "  status=${status} conclusion=${conclusion:-pending} ${run_url}"

    if [ "$status" = "completed" ]; then
      if [ "$conclusion" = "success" ]; then
        echo "PASS: 동일 SHA의 CI가 성공했습니다."
        exit 0
      fi
      echo "FAIL: 동일 SHA의 CI 결과가 ${conclusion} 입니다. 배포하지 않습니다."
      exit 1
    fi
  else
    echo "  CI 실행을 아직 찾지 못했습니다."
  fi

  if [ "$(date +%s)" -ge "$deadline" ]; then
    echo "FAIL: ${TIMEOUT_SECONDS}초 안에 CI가 끝나지 않았습니다. 배포하지 않습니다."
    exit 1
  fi

  sleep "$POLL_SECONDS"
done
